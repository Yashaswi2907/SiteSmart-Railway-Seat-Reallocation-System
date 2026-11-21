"""TT/TTE boarding verification and no-show processing."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.bookings.exceptions import BoardingActionError
from apps.bookings.models import BoardingStatus, Booking, Passenger
from apps.operations.models import ActivityLog, TrainSimulation
from apps.operations.services.activity import log_activity

from .availability import get_route_stops, get_simulation
from .release import release_seat_segments
from .segments import free_ranges


def user_can_operate_train(user, train) -> bool:
    """Admins may operate any train; a TT only the trains assigned to them."""
    if not user or not user.is_authenticated:
        return False
    if user.is_portal_admin:
        return True
    if user.is_tt and hasattr(user, "tt_profile"):
        return user.tt_profile.assigned_trains.filter(pk=train.pk).exists()
    return False


def verification_eligibility(passenger: Passenger, simulation: TrainSimulation | None) -> tuple[bool, str]:
    """Can a TT mark this passenger as BOARDED / DID NOT BOARD right now?"""
    booking = passenger.booking
    if booking.status == Booking.Status.CANCELLED or passenger.status == Passenger.Status.CANCELLED:
        return False, "This ticket has been cancelled."
    boarding = getattr(passenger, "boarding", None)
    if boarding and boarding.status != BoardingStatus.Status.PENDING:
        return False, f"Already verified as {boarding.get_status_display().lower()}."
    if simulation is None or simulation.status == TrainSimulation.Status.SCHEDULED:
        return False, "Start the train run before verifying passengers."
    if simulation.status == TrainSimulation.Status.COMPLETED:
        return False, "This train run has been completed."
    if not simulation.has_reached(booking.from_index):
        return False, f"The train has not reached {booking.from_stop.station.name} yet."
    if simulation.has_reached(booking.to_index):
        return False, f"This passenger's journey ended at {booking.to_stop.station.name}."
    return True, ""


def _locked_context(passenger_id: int, user):
    passenger = (
        Passenger.objects.select_for_update()
        .select_related("booking__train", "booking__from_stop__station", "booking__to_stop__station", "seat__coach")
        .get(pk=passenger_id)
    )
    if not user_can_operate_train(user, passenger.booking.train):
        raise PermissionDenied("You are not assigned to this train.")
    boarding, _ = BoardingStatus.objects.select_for_update().get_or_create(passenger=passenger)
    passenger.boarding = boarding
    simulation = get_simulation(passenger.booking.train, passenger.booking.journey_date)
    ok, reason = verification_eligibility(passenger, simulation)
    if not ok:
        raise BoardingActionError(reason)
    stops = get_route_stops(passenger.booking.train)
    return passenger, boarding, simulation, stops


def mark_passenger_boarded(passenger: Passenger, user, *, remarks: str = "", request=None) -> BoardingStatus:
    """Record that the passenger is on board. Their seat can never be released as a no-show afterwards."""
    with transaction.atomic():
        passenger, boarding, simulation, stops = _locked_context(passenger.pk, user)
        boarding.status = BoardingStatus.Status.BOARDED
        boarding.verified_by = user
        boarding.verified_at = timezone.now()
        boarding.verified_at_stop = stops[min(simulation.current_index, len(stops) - 1)]
        boarding.remarks = remarks[:200]
        boarding.save()
        log_activity(
            ActivityLog.Action.PASSENGER_BOARDED,
            f"{passenger.name} (PNR {passenger.booking.pnr}, {passenger.seat.label}) verified on board",
            actor=user, train=passenger.booking.train, booking=passenger.booking, request=request,
        )
    return boarding


def process_no_show(passenger: Passenger, user, *, remarks: str = "", request=None) -> dict:
    """Mark a passenger as DID NOT BOARD and release the remaining seat segments.

    Steps (all in one transaction):
      1. lock the passenger + boarding rows and re-check eligibility;
      2. set boarding status to NOT_BOARDED with verifier, time and station;
      3. release every ACTIVE segment of the seat (``release_seat_segments``);
      4. log the no-show and the release, and report which journeys the seat can now serve.
    """
    with transaction.atomic():
        passenger, boarding, simulation, stops = _locked_context(passenger.pk, user)
        boarding.status = BoardingStatus.Status.NOT_BOARDED
        boarding.verified_by = user
        boarding.verified_at = timezone.now()
        boarding.verified_at_stop = stops[min(simulation.current_index, len(stops) - 1)]
        boarding.remarks = remarks[:200]
        boarding.save()

        released = release_seat_segments(passenger)
        booking = passenger.booking
        min_boardable = simulation.min_boardable_index(len(stops))
        sellable = [s for s in released if s >= min_boardable]
        ranges = free_ranges(set(range(len(stops) - 1)) - set(sellable), 0, len(stops) - 1)
        readable = [f"{stops[a].station.code}→{stops[b].station.code}" for a, b in ranges]

        log_activity(
            ActivityLog.Action.PASSENGER_NO_SHOW,
            f"{passenger.name} (PNR {booking.pnr}) did not board at {booking.from_stop.station.name}",
            actor=user, train=booking.train, booking=booking, request=request,
        )
        log_activity(
            ActivityLog.Action.SEATS_RELEASED,
            f"Seat {passenger.seat.label} released for {', '.join(readable) or 'no remaining segments'}",
            actor=user, train=booking.train, booking=booking, request=request,
            metadata={"seat_id": passenger.seat_id, "segments": released, "sellable_segments": sellable},
        )
    return {
        "passenger_id": passenger.pk,
        "seat": passenger.seat.label,
        "released_segments": released,
        "sellable_segments": sellable,
        "released_ranges": readable,
    }
