"""Seat availability: checking, listing and choosing seats for a journey segment.

Availability of a seat for a journey ``[from_index, to_index)`` on a run date is
decided by two independent rules:

1. **Occupancy** — no ACTIVE ``SeatAllocation`` exists for that seat, date and any
   segment inside the range (RELEASED / CANCELLED rows are ignored, which is what
   makes a no-show's seat reusable).
2. **Train position** — the journey must not start at a stop the train has already
   departed (``TrainSimulation.min_boardable_index``). Departed segments are never
   offered again, even if they are technically unoccupied.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.bookings.exceptions import InsufficientSeatsError, InvalidJourneyError, TrainDepartedError
from apps.bookings.models import SeatAllocation
from apps.operations.models import TrainSimulation
from apps.railway.models import Seat, Train, TrainStop

from .segments import fit_waste, free_ranges, segment_range

ACTIVE = SeatAllocation.Status.ACTIVE
RELEASED = SeatAllocation.Status.RELEASED


# ---------------------------------------------------------------------------
# Journey context
# ---------------------------------------------------------------------------
@dataclass
class JourneyContext:
    """Everything the engine needs to know about a requested journey."""

    train: Train
    journey_date: dt.date
    stops: list[TrainStop]
    from_index: int
    to_index: int
    simulation: TrainSimulation | None
    min_boardable: int
    notes: list[str] = field(default_factory=list)

    @property
    def from_stop(self) -> TrainStop:
        return self.stops[self.from_index]

    @property
    def to_stop(self) -> TrainStop:
        return self.stops[self.to_index]

    @property
    def segment_count(self) -> int:
        return len(self.stops) - 1

    @property
    def segments(self) -> range:
        return segment_range(self.from_index, self.to_index)

    @property
    def distance_km(self) -> int:
        return max(self.to_stop.distance_km - self.from_stop.distance_km, 1)


def get_route_stops(train: Train) -> list[TrainStop]:
    return list(train.get_stops())


def get_simulation(train: Train, journey_date: dt.date) -> TrainSimulation | None:
    return TrainSimulation.objects.filter(train=train, journey_date=journey_date).first()


def get_min_boardable_index(train: Train, journey_date: dt.date, stop_count: int | None = None,
                            simulation: TrainSimulation | None = None) -> int:
    """First stop index from which a new journey can still start on this run."""
    if stop_count is None:
        stop_count = len(get_route_stops(train))
    simulation = simulation if simulation is not None else get_simulation(train, journey_date)
    if simulation is None:
        return 0
    return simulation.min_boardable_index(stop_count)


def _index_of(stops: list[TrainStop], stop) -> int:
    """Accept a TrainStop, a stop id or a station code and return its route index."""
    for stop_obj in stops:
        if isinstance(stop, TrainStop) and stop_obj.pk == stop.pk:
            return stop_obj.sequence
        if isinstance(stop, int) and stop_obj.pk == stop:
            return stop_obj.sequence
        if isinstance(stop, str) and stop_obj.station.code == stop.upper():
            return stop_obj.sequence
    raise InvalidJourneyError("The selected station is not on this train's route.", code="station_not_on_route")


def build_journey_context(train: Train, journey_date: dt.date, from_stop, to_stop, *,
                          enforce_schedule: bool = True, enforce_position: bool = True) -> JourneyContext:
    """Validate a journey request and return its context.

    Raises ``InvalidJourneyError`` / ``TrainDepartedError`` with a clear message.
    """
    if not train.is_active:
        raise InvalidJourneyError("This train is not currently accepting bookings.", code="train_inactive")
    stops = get_route_stops(train)
    if len(stops) < 2:
        raise InvalidJourneyError("This train has no route configured yet.", code="no_route")
    # Guard against non-contiguous sequences (route editor always re-sequences).
    if [s.sequence for s in stops] != list(range(len(stops))):
        raise InvalidJourneyError("The route for this train is being reconfigured.", code="route_inconsistent")

    from_index = _index_of(stops, from_stop)
    to_index = _index_of(stops, to_stop)
    if from_index >= to_index:
        raise InvalidJourneyError(
            "The destination must come after the boarding station on this route.", code="wrong_direction"
        )

    simulation = get_simulation(train, journey_date)
    today = timezone.localdate()
    if enforce_schedule:
        if not train.runs_on(journey_date):
            raise InvalidJourneyError(
                f"Train {train.number} does not run on {journey_date:%A, %d %b %Y}.", code="not_running"
            )
        run_in_progress = simulation is not None and simulation.is_running
        if journey_date < today and not run_in_progress:
            raise InvalidJourneyError("Bookings cannot be made for a past journey date.", code="past_date")
        horizon = today + dt.timedelta(days=settings.SITESMART["ADVANCE_BOOKING_DAYS"])
        if journey_date > horizon:
            raise InvalidJourneyError(
                f"Reservations open {settings.SITESMART['ADVANCE_BOOKING_DAYS']} days in advance.",
                code="too_far_ahead",
            )

    min_boardable = simulation.min_boardable_index(len(stops)) if simulation else 0
    if enforce_position and from_index < min_boardable:
        if simulation and simulation.status == TrainSimulation.Status.COMPLETED:
            msg = "This train has completed its journey for the selected date."
        else:
            msg = (
                f"The train has already departed {stops[from_index].station.name}. "
                f"The earliest boarding point now is "
                f"{stops[min(min_boardable, len(stops) - 1)].station.name}."
            )
        raise TrainDepartedError(msg, details={"min_boardable_index": min_boardable})

    return JourneyContext(
        train=train,
        journey_date=journey_date,
        stops=stops,
        from_index=from_index,
        to_index=to_index,
        simulation=simulation,
        min_boardable=min_boardable,
    )


# ---------------------------------------------------------------------------
# Occupancy queries
# ---------------------------------------------------------------------------
def _overlap_filter(from_index: int | None, to_index: int | None) -> Q:
    if from_index is None:
        return Q()
    return Q(segment_index__gte=from_index, segment_index__lt=to_index)


def occupied_segments(journey_date: dt.date, *, seat_ids: Iterable[int] | None = None, train: Train | None = None,
                      from_index: int | None = None, to_index: int | None = None) -> dict[int, set[int]]:
    """Map ``seat_id -> {occupied segment indices}`` for ACTIVE allocations."""
    qs = SeatAllocation.objects.filter(journey_date=journey_date, status=ACTIVE).filter(
        _overlap_filter(from_index, to_index)
    )
    if seat_ids is not None:
        qs = qs.filter(seat_id__in=list(seat_ids))
    if train is not None:
        qs = qs.filter(seat__coach__train=train)
    result: dict[int, set[int]] = defaultdict(set)
    for seat_id, segment in qs.values_list("seat_id", "segment_index"):
        result[seat_id].add(segment)
    return result


@dataclass
class SeatCheck:
    available: bool
    reason: str = ""
    conflicts: list[dict] = field(default_factory=list)


def check_seat_availability(seat: Seat, journey_date: dt.date, from_index: int, to_index: int,
                            *, stops: list[TrainStop] | None = None) -> SeatCheck:
    """Explain whether ``seat`` is free for ``[from_index, to_index)`` (occupancy rule only)."""
    segment_range(from_index, to_index)  # validates indices
    if not seat.is_active or not seat.coach.is_active:
        return SeatCheck(False, "This seat is not in service.")
    conflicts_qs = (
        SeatAllocation.objects.filter(seat=seat, journey_date=journey_date, status=ACTIVE)
        .filter(_overlap_filter(from_index, to_index))
        .select_related("passenger__booking")
        .order_by("segment_index")
    )
    stops = stops or get_route_stops(seat.coach.train)
    names = {s.sequence: s.station.code for s in stops}
    conflicts = [
        {
            "pnr": a.passenger.booking.pnr,
            "passenger": a.passenger.name,
            "segment_index": a.segment_index,
            "segment": f"{names.get(a.segment_index, a.segment_index)} → {names.get(a.segment_index + 1, '')}",
        }
        for a in conflicts_qs
    ]
    if conflicts:
        pnrs = sorted({c["pnr"] for c in conflicts})
        segs = ", ".join(dict.fromkeys(c["segment"] for c in conflicts))
        return SeatCheck(False, f"Overlaps an existing booking (PNR {', '.join(pnrs)}) on {segs}.", conflicts)
    return SeatCheck(True, "Seat is free for every segment of this journey.")


def is_seat_available(seat: Seat, journey_date: dt.date, from_index: int, to_index: int) -> bool:
    """Boolean shortcut for :func:`check_seat_availability`."""
    return check_seat_availability(seat, journey_date, from_index, to_index).available


def bookable_seats_qs(train: Train, *, coach_class: str | None = None, coach_id: int | None = None):
    qs = Seat.objects.filter(coach__train=train, coach__is_active=True, is_active=True).select_related("coach")
    if coach_class:
        qs = qs.filter(coach__coach_class=coach_class)
    if coach_id:
        qs = qs.filter(coach_id=coach_id)
    return qs.order_by("coach__position", "coach__coach_number", "seat_number")


def get_available_seats(train: Train, journey_date: dt.date, from_index: int, to_index: int, *,
                        coach_class: str | None = None, coach_id: int | None = None) -> list[Seat]:
    """All in-service seats free for every segment of ``[from_index, to_index)``."""
    seats = list(bookable_seats_qs(train, coach_class=coach_class, coach_id=coach_id))
    blocked = occupied_segments(journey_date, train=train, from_index=from_index, to_index=to_index)
    return [s for s in seats if s.id not in blocked]


def released_seat_ids(train: Train, journey_date: dt.date, from_index: int | None = None,
                      to_index: int | None = None) -> set[int]:
    """Seats with segments released by a verified no-show (optionally overlapping a range)."""
    qs = SeatAllocation.objects.filter(
        journey_date=journey_date, status=RELEASED, seat__coach__train=train
    ).filter(_overlap_filter(from_index, to_index))
    return set(qs.values_list("seat_id", flat=True).distinct())


def class_availability(train: Train, journey_date: dt.date, from_index: int, to_index: int) -> dict[str, dict]:
    """Per-class seat counts for a journey: total, available and released-and-available."""
    seats = bookable_seats_qs(train).values_list("id", "coach__coach_class")
    blocked = occupied_segments(journey_date, train=train, from_index=from_index, to_index=to_index)
    released = released_seat_ids(train, journey_date, from_index, to_index)
    summary: dict[str, dict] = {}
    for seat_id, coach_class in seats:
        row = summary.setdefault(coach_class, {"total": 0, "available": 0, "reallocated": 0})
        row["total"] += 1
        if seat_id not in blocked:
            row["available"] += 1
            if seat_id in released:
                row["reallocated"] += 1
    return summary


# ---------------------------------------------------------------------------
# Seat selection
# ---------------------------------------------------------------------------
def find_eligible_seats(ctx: JourneyContext, coach_class: str, count: int = 1, *,
                        berth_preferences: list[str] | None = None, coach_id: int | None = None) -> list[Seat]:
    """Choose ``count`` seats for an upcoming journey using a best-fit strategy.

    1. Candidates are seats free for every requested segment.
    2. Each candidate gets a *waste* score — free segments it would leave stranded
       next to the booking (see :func:`segments.fit_waste`). Seats released by a
       no-show whose gap matches the journey score 0 and are chosen first.
    3. The group is kept in one coach when possible; berth preferences are honoured
       when a matching seat exists.
    """
    candidates = get_available_seats(
        ctx.train, ctx.journey_date, ctx.from_index, ctx.to_index, coach_class=coach_class, coach_id=coach_id
    )
    if len(candidates) < count:
        raise InsufficientSeatsError(
            f"Only {len(candidates)} seat(s) are free in {coach_class} for this journey; {count} requested.",
            details={"available": len(candidates)},
        )
    occupancy = occupied_segments(ctx.journey_date, seat_ids=[s.id for s in candidates])
    lower = max(ctx.min_boardable, 0)

    def score(seat: Seat) -> tuple:
        waste = fit_waste(occupancy.get(seat.id, set()), ctx.from_index, ctx.to_index, lower, ctx.segment_count)
        return (waste, seat.coach.position, seat.seat_number)

    ranked = sorted(candidates, key=score)

    # Prefer a single coach that can host the whole group (lowest total waste).
    by_coach: dict[int, list[Seat]] = defaultdict(list)
    for seat in ranked:
        by_coach[seat.coach_id].append(seat)
    group_coaches = [seats for seats in by_coach.values() if len(seats) >= count]
    if group_coaches:
        pool = min(group_coaches, key=lambda seats: sum(score(s)[0] for s in seats[:count]) * 1000
                   + seats[0].coach.position)
    else:
        pool = ranked

    preferences = list(berth_preferences or [])
    preferences += [""] * (count - len(preferences))
    chosen: list[Seat] = []
    remaining = list(pool)
    for pref in preferences[:count]:
        pick = next((s for s in remaining if pref and s.berth_type == pref), None) or remaining[0]
        chosen.append(pick)
        remaining.remove(pick)
    return chosen


# ---------------------------------------------------------------------------
# Timelines & released-seat reports (TT / admin views)
# ---------------------------------------------------------------------------
def seat_segment_timeline(seat: Seat, journey_date: dt.date, stops: list[TrainStop] | None = None,
                          min_boardable: int | None = None) -> list[dict]:
    """Per-segment state of one seat on one run, for visualisation and auditing."""
    stops = stops or get_route_stops(seat.coach.train)
    if min_boardable is None:
        min_boardable = get_min_boardable_index(seat.coach.train, journey_date, len(stops))
    allocations = (
        SeatAllocation.objects.filter(seat=seat, journey_date=journey_date)
        .exclude(status=SeatAllocation.Status.CANCELLED)
        .select_related("passenger__booking")
    )
    active: dict[int, SeatAllocation] = {}
    released: dict[int, SeatAllocation] = {}
    for alloc in allocations:
        (active if alloc.status == ACTIVE else released)[alloc.segment_index] = alloc
    timeline = []
    for seg in range(len(stops) - 1):
        alloc = active.get(seg)
        rel = released.get(seg)
        timeline.append({
            "segment_index": seg,
            "from_code": stops[seg].station.code,
            "to_code": stops[seg + 1].station.code,
            "departed": seg < min_boardable,
            "state": "occupied" if alloc else ("released" if rel else "free"),
            "pnr": alloc.passenger.booking.pnr if alloc else None,
            "passenger": alloc.passenger.name if alloc else None,
            "is_reallocation": bool(alloc and alloc.passenger.is_reallocated_seat),
            "released_pnr": rel.passenger.booking.pnr if rel else None,
        })
    return timeline


def released_seats_report(train: Train, journey_date: dt.date) -> list[dict]:
    """Seats freed by verified no-shows on a run, and which journeys they can still serve."""
    stops = get_route_stops(train)
    if len(stops) < 2:
        return []
    min_boardable = get_min_boardable_index(train, journey_date, len(stops))
    released = (
        SeatAllocation.objects.filter(journey_date=journey_date, status=RELEASED, seat__coach__train=train)
        .select_related("seat__coach", "passenger__booking", "passenger__boarding__verified_by")
        .order_by("seat__coach__position", "seat__seat_number", "segment_index")
    )
    by_seat: dict[int, dict] = {}
    for alloc in released:
        entry = by_seat.setdefault(alloc.seat_id, {"seat": alloc.seat, "no_shows": {}})
        p = alloc.passenger
        entry["no_shows"].setdefault(p.id, {
            "passenger": p.name,
            "pnr": p.booking.pnr,
            "from_code": stops[p.booking.from_index].station.code,
            "to_code": stops[p.booking.to_index].station.code,
            "verified_by": getattr(getattr(p.boarding, "verified_by", None), "display_name", ""),
            "released_at": alloc.released_at,
        })
    if not by_seat:
        return []
    occupancy = occupied_segments(journey_date, seat_ids=by_seat.keys())
    report = []
    seg_count = len(stops) - 1
    for seat_id, entry in by_seat.items():
        seat = entry["seat"]
        occupied = occupancy.get(seat_id, set())
        ranges = free_ranges(occupied, min(min_boardable, seg_count), seg_count)
        report.append({
            "seat_id": seat_id,
            "seat_label": f"{seat.coach.coach_number}-{seat.seat_number}",
            "coach": seat.coach.coach_number,
            "seat_number": seat.seat_number,
            "berth": seat.berth_type,
            "coach_class": seat.coach.coach_class,
            "no_shows": list(entry["no_shows"].values()),
            "eligible_ranges": [
                {
                    "from_index": a, "to_index": b,
                    "from_code": stops[a].station.code, "to_code": stops[b].station.code,
                    "from_name": stops[a].station.name, "to_name": stops[b].station.name,
                }
                for a, b in ranges
            ],
            "timeline": seat_segment_timeline(seat, journey_date, stops, min_boardable),
        })
    return report
