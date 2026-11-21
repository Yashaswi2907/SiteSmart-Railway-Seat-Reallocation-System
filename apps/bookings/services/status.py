"""Derive a booking's journey state (upcoming / on board / completed / ...) from the simulation."""
from __future__ import annotations

from collections.abc import Iterable

from django.utils import timezone

from apps.bookings.models import BoardingStatus, Booking, Passenger
from apps.operations.models import TrainSimulation


class JourneyState:
    UPCOMING = "UPCOMING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"

    LABELS = {
        UPCOMING: ("Upcoming", "info"),
        IN_PROGRESS: ("On journey", "primary"),
        COMPLETED: ("Completed", "secondary"),
        CANCELLED: ("Cancelled", "danger"),
        NO_SHOW: ("Did not board", "warning"),
    }


def simulations_for(bookings: Iterable[Booking]) -> dict[tuple[int, object], TrainSimulation]:
    keys = {(b.train_id, b.journey_date) for b in bookings}
    if not keys:
        return {}
    train_ids = {k[0] for k in keys}
    dates = {k[1] for k in keys}
    sims = TrainSimulation.objects.filter(train_id__in=train_ids, journey_date__in=dates)
    return {(s.train_id, s.journey_date): s for s in sims}


def booking_journey_state(booking: Booking, simulation: TrainSimulation | None = None,
                          *, simulations: dict | None = None) -> str:
    if booking.status == Booking.Status.CANCELLED:
        return JourneyState.CANCELLED
    if simulations is not None:
        simulation = simulations.get((booking.train_id, booking.journey_date))
    statuses = [
        getattr(getattr(p, "boarding", None), "status", BoardingStatus.Status.PENDING)
        for p in booking.passengers.all()
        if p.status == Passenger.Status.CONFIRMED
    ]
    if statuses and all(s == BoardingStatus.Status.NOT_BOARDED for s in statuses):
        return JourneyState.NO_SHOW
    if simulation is not None:
        if simulation.has_reached(booking.to_index):
            return JourneyState.COMPLETED
        if simulation.has_departed(booking.from_index) or BoardingStatus.Status.BOARDED in statuses:
            return JourneyState.IN_PROGRESS
        return JourneyState.UPCOMING
    if booking.journey_date < timezone.localdate():
        return JourneyState.COMPLETED
    return JourneyState.UPCOMING


def annotate_states(bookings: list[Booking]) -> list[Booking]:
    """Attach ``journey_state``, ``state_label`` and ``state_tone`` to each booking."""
    sims = simulations_for(bookings)
    for b in bookings:
        b.journey_state = booking_journey_state(b, simulations=sims)
        b.state_label, b.state_tone = JourneyState.LABELS[b.journey_state]
    return bookings
