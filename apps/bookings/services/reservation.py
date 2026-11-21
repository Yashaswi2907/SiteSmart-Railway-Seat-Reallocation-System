"""Reserving seats: the only code path that creates bookings and allocations.

Concurrency strategy (defence in depth)
---------------------------------------
1. ``transaction.atomic()`` — with SQLite configured in ``IMMEDIATE`` transaction
   mode, the write lock is taken when the block starts, so concurrent booking
   requests are serialised: the second request only reads availability after the
   first has committed.
2. ``select_for_update()`` on the chosen seats — a no-op on SQLite, but gives
   row-level locking on PostgreSQL/MySQL if the project is moved there.
3. Availability and train position are **re-validated inside the transaction**,
   immediately before rows are written.
4. The partial unique constraint ``uniq_active_seat_segment`` makes the database
   reject any overlapping ACTIVE allocation. An ``IntegrityError`` is converted
   into a friendly ``SeatUnavailableError`` and the whole booking rolls back.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.bookings.exceptions import InvalidJourneyError, SeatUnavailableError
from apps.bookings.models import BoardingStatus, Booking, Passenger, SeatAllocation
from apps.operations.models import ActivityLog
from apps.operations.services.activity import log_activity
from apps.railway.constants import BerthType
from apps.railway.models import Seat, Train

from .availability import build_journey_context, find_eligible_seats, occupied_segments, released_seat_ids
from .fares import calculate_fare
from .pnr import generate_pnr

VALID_GENDERS = {"M", "F", "O"}
VALID_BERTHS = {""} | {c for c, _ in BerthType.choices}


@dataclass
class PassengerInput:
    name: str
    age: int
    gender: str
    berth_preference: str = ""


def normalize_passengers(raw: list) -> list[PassengerInput]:
    """Validate passenger details server-side (never trust the browser)."""
    limit = settings.SITESMART["MAX_PASSENGERS_PER_BOOKING"]
    if not raw:
        raise InvalidJourneyError("Add at least one passenger.", code="no_passengers")
    if len(raw) > limit:
        raise InvalidJourneyError(f"A booking can have at most {limit} passengers.", code="too_many_passengers")
    cleaned: list[PassengerInput] = []
    for i, item in enumerate(raw, start=1):
        if isinstance(item, PassengerInput):
            item = item.__dict__
        name = " ".join(str(item.get("name", "")).split())
        if not (2 <= len(name) <= 80) or not all(ch.isalpha() or ch in " .'-" for ch in name):
            raise InvalidJourneyError(f"Passenger {i}: enter a valid name (letters only).", code="invalid_passenger")
        try:
            age = int(item.get("age"))
        except (TypeError, ValueError):
            raise InvalidJourneyError(f"Passenger {i}: age must be a number.", code="invalid_passenger") from None
        if not 1 <= age <= 120:
            raise InvalidJourneyError(f"Passenger {i}: age must be between 1 and 120.", code="invalid_passenger")
        gender = str(item.get("gender", "")).upper()
        if gender not in VALID_GENDERS:
            raise InvalidJourneyError(f"Passenger {i}: choose a gender.", code="invalid_passenger")
        berth = str(item.get("berth_preference", "") or "").upper()
        if berth not in VALID_BERTHS:
            berth = ""
        cleaned.append(PassengerInput(name=name.title(), age=age, gender=gender, berth_preference=berth))
    return cleaned


def reserve_seats(*, user, train: Train, journey_date: dt.date, from_stop, to_stop, coach_class: str,
                  passengers: list, seat_ids: list[int] | None = None, contact_email: str | None = None,
                  contact_phone: str = "", enforce_schedule: bool = True, request=None) -> Booking:
    """Atomically create a confirmed booking with segment-level seat allocations.

    ``seat_ids`` (optional) are seats picked on the seat map, one per passenger in
    order. If omitted, seats are chosen automatically with best-fit selection.
    ``enforce_schedule=False`` is used only by the seed command to create history
    (it skips the running-day, date-window and train-position checks; the
    segment-overlap guarantees always apply).
    """
    people = normalize_passengers(passengers)
    if coach_class not in train.available_classes():
        raise InvalidJourneyError(f"Train {train.number} has no {coach_class} coaches.", code="class_unavailable")
    if seat_ids is not None:
        seat_ids = [int(s) for s in seat_ids]
        if len(seat_ids) != len(people) or len(set(seat_ids)) != len(seat_ids):
            raise InvalidJourneyError("Select exactly one different seat for each passenger.", code="seat_count")

    # Fast pre-check outside the lock gives immediate feedback for obvious problems.
    build_journey_context(train, journey_date, from_stop, to_stop, enforce_schedule=enforce_schedule,
                          enforce_position=enforce_schedule)

    for attempt in range(3):
        try:
            with transaction.atomic():
                booking = _reserve_locked(
                    user=user, train=train, journey_date=journey_date, from_stop=from_stop, to_stop=to_stop,
                    coach_class=coach_class, people=people, seat_ids=seat_ids,
                    contact_email=contact_email or user.email, contact_phone=contact_phone or user.phone,
                    enforce_schedule=enforce_schedule, request=request,
                )
            return booking
        except IntegrityError as exc:
            if "pnr" in str(exc).lower() and attempt < 2:
                continue  # astronomically rare PNR clash: retry with a new PNR
            raise SeatUnavailableError(
                "One of the selected seats was booked by another passenger a moment ago. "
                "Please refresh the seat map and choose again.",
                code="race_lost",
            ) from exc
    raise SeatUnavailableError("Could not complete the booking. Please try again.")  # pragma: no cover


def _reserve_locked(*, user, train, journey_date, from_stop, to_stop, coach_class, people, seat_ids,
                    contact_email, contact_phone, enforce_schedule, request) -> Booking:
    # 1. Re-validate the journey inside the write transaction (train may have moved).
    ctx = build_journey_context(train, journey_date, from_stop, to_stop, enforce_schedule=enforce_schedule,
                                enforce_position=enforce_schedule)

    # 2. Resolve and lock seats, then re-check every requested segment.
    if seat_ids:
        locked = {
            s.id: s
            for s in Seat.objects.select_for_update().select_related("coach").filter(id__in=seat_ids, coach__train=train)
        }
        if len(locked) != len(seat_ids):
            raise SeatUnavailableError("One or more selected seats do not belong to this train.", code="invalid_seat")
        seats = [locked[i] for i in seat_ids]
        for seat in seats:
            if seat.coach.coach_class != coach_class:
                raise SeatUnavailableError(f"Seat {seat.label} is not in class {coach_class}.", code="invalid_seat")
            if not (seat.is_active and seat.coach.is_active):
                raise SeatUnavailableError(f"Seat {seat.label} is not in service.", code="invalid_seat")
        clashes = occupied_segments(journey_date, seat_ids=seat_ids, from_index=ctx.from_index, to_index=ctx.to_index)
        if clashes:
            labels = ", ".join(s.label for s in seats if s.id in clashes)
            raise SeatUnavailableError(
                f"Seat {labels} is no longer free for {ctx.from_stop.station.name} → {ctx.to_stop.station.name}. "
                "Its journey would overlap an existing reservation.",
                details={"seat_ids": list(clashes)},
            )
    else:
        seats = find_eligible_seats(
            ctx, coach_class, len(people), berth_preferences=[p.berth_preference for p in people]
        )
        list(Seat.objects.select_for_update().filter(id__in=[s.id for s in seats]))

    # 3. Write booking, passengers, boarding rows and per-segment allocations.
    reused = released_seat_ids(train, journey_date, ctx.from_index, ctx.to_index) & {s.id for s in seats}
    fare = calculate_fare(coach_class, ctx.distance_km)
    booking = Booking.objects.create(
        pnr=generate_pnr(),
        user=user,
        train=train,
        journey_date=journey_date,
        from_stop=ctx.from_stop,
        to_stop=ctx.to_stop,
        from_index=ctx.from_index,
        to_index=ctx.to_index,
        coach_class=coach_class,
        passenger_count=len(people),
        total_fare=fare * len(people),
        contact_email=contact_email,
        contact_phone=contact_phone or "",
        is_reallocated=bool(reused),
    )
    allocations = []
    for person, seat in zip(people, seats):
        passenger = Passenger.objects.create(
            booking=booking, name=person.name, age=person.age, gender=person.gender,
            berth_preference=person.berth_preference, seat=seat, fare=fare,
            is_reallocated_seat=seat.id in reused,
        )
        BoardingStatus.objects.create(passenger=passenger)
        allocations.extend(
            SeatAllocation(passenger=passenger, seat=seat, journey_date=journey_date, segment_index=seg)
            for seg in ctx.segments
        )
    SeatAllocation.objects.bulk_create(allocations)

    seat_text = ", ".join(s.label for s in seats)
    log_activity(
        ActivityLog.Action.BOOKING_CREATED,
        f"PNR {booking.pnr}: {len(people)} pax {ctx.from_stop.station.code}→{ctx.to_stop.station.code} "
        f"on {journey_date:%d %b}, seats {seat_text}",
        actor=user, train=train, booking=booking, request=request,
        metadata={"seats": [s.id for s in seats], "segments": list(ctx.segments)},
    )
    if reused:
        log_activity(
            ActivityLog.Action.SEAT_REALLOCATED,
            f"Released seat(s) {', '.join(s.label for s in seats if s.id in reused)} reallocated to PNR "
            f"{booking.pnr} for {ctx.from_stop.station.code}→{ctx.to_stop.station.code}",
            actor=user, train=train, booking=booking, request=request,
        )
    return booking
