"""Releasing seat segments back into the bookable pool."""
from __future__ import annotations

from django.utils import timezone

from apps.bookings.models import Passenger, SeatAllocation


def release_seat_segments(passenger: Passenger, *, from_index: int | None = None,
                          new_status: str = SeatAllocation.Status.RELEASED) -> list[int]:
    """Deactivate a passenger's ACTIVE allocations and return the freed segment indices.

    * ``new_status=RELEASED`` is used for verified no-shows (the rows stay as an
      audit trail and let the UI show "reallocated" seats).
    * ``new_status=CANCELLED`` is used for passenger cancellations.
    * ``from_index`` limits the release to segments at or after that index.

    Because availability only looks at ACTIVE rows, the freed segments become
    bookable immediately — subject to the train-position rule, which keeps
    already-departed segments closed.
    """
    qs = passenger.allocations.filter(status=SeatAllocation.Status.ACTIVE)
    if from_index is not None:
        qs = qs.filter(segment_index__gte=from_index)
    segments = sorted(qs.values_list("segment_index", flat=True))
    if segments:
        now = timezone.now()
        qs.update(status=new_status, released_at=now, updated_at=now)
    return segments
