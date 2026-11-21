"""Passenger/admin cancellation of bookings."""
from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from apps.bookings.exceptions import CancellationError
from apps.bookings.models import BoardingStatus, Booking, Cancellation, Passenger, SeatAllocation
from apps.operations.models import ActivityLog, TrainSimulation
from apps.operations.services.activity import log_activity

from .availability import get_simulation
from .fares import refund_terms
from .release import release_seat_segments


def cancellation_eligibility(booking: Booking, simulation: TrainSimulation | None = None) -> tuple[bool, str]:
    if booking.status == Booking.Status.CANCELLED:
        return False, "This booking is already cancelled."
    simulation = simulation if simulation is not None else get_simulation(booking.train, booking.journey_date)
    if simulation is not None and simulation.has_departed(booking.from_index):
        return False, f"The train has already departed {booking.from_stop.station.name}."
    if simulation is not None and simulation.status == TrainSimulation.Status.COMPLETED:
        return False, "This journey has been completed."
    running = simulation is not None and simulation.is_running
    if booking.journey_date < timezone.localdate() and not running:
        return False, "Past journeys cannot be cancelled."
    verified = BoardingStatus.objects.filter(
        passenger__booking=booking, passenger__status=Passenger.Status.CONFIRMED
    ).exclude(status=BoardingStatus.Status.PENDING)
    if verified.exists():
        return False, "The TT has already verified passengers on this ticket."
    return True, ""


def cancel_booking(booking: Booking, user, *, reason: str = "", request=None) -> Cancellation:
    """Cancel every passenger on a booking and free their seat segments immediately."""
    if not (user.is_portal_admin or booking.user_id == user.pk):
        raise PermissionDenied("You can only cancel your own bookings.")
    with transaction.atomic():
        booking = (
            Booking.objects.select_for_update()
            .select_related("train", "from_stop__station", "to_stop__station")
            .get(pk=booking.pk)
        )
        ok, why = cancellation_eligibility(booking)
        if not ok:
            raise CancellationError(why)
        released = 0
        for passenger in booking.passengers.filter(status=Passenger.Status.CONFIRMED):
            released += len(release_seat_segments(passenger, new_status=SeatAllocation.Status.CANCELLED))
            passenger.status = Passenger.Status.CANCELLED
            passenger.save(update_fields=["status", "updated_at"])
        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status", "updated_at"])
        charge, refund = refund_terms(
            booking.coach_class, booking.total_fare, booking.passenger_count, booking.journey_date,
            timezone.localdate(),
        )
        cancellation = Cancellation.objects.create(
            booking=booking, cancelled_by=user, reason=reason[:255], cancellation_charge=charge,
            refund_amount=refund, segments_released=released,
        )
        log_activity(
            ActivityLog.Action.BOOKING_CANCELLED,
            f"PNR {booking.pnr} cancelled; {released} seat-segment(s) released, simulated refund ₹{refund}",
            actor=user, train=booking.train, booking=booking, request=request,
        )
    return cancellation
