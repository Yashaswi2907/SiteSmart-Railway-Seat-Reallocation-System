"""Pure, database-free helpers for reasoning about route segments.

Terminology
-----------
* A route has ``n`` stops indexed ``0 .. n-1``.
* Segment ``i`` is the stretch of track between stop ``i`` and stop ``i + 1``.
* A journey from stop ``s`` to stop ``d`` (``s < d``) occupies segments
  ``s, s+1, ..., d-1`` — the half-open interval ``[s, d)``.

Two journeys on the same seat conflict if and only if their intervals intersect::

    [s1, d1) and [s2, d2) overlap  <=>  s1 < d2 and s2 < d1

So A->E [0,4) conflicts with everything, B->C [1,2) and C->D [2,3) do not
conflict (they only *touch* at C), while B->D [1,3) and C->E [2,4) conflict on
segment 2 (C->D).
"""
from __future__ import annotations

from collections.abc import Iterable


def segment_range(from_index: int, to_index: int) -> range:
    """Segments occupied by a journey from ``from_index`` to ``to_index``."""
    if from_index < 0 or to_index <= from_index:
        raise ValueError(f"Invalid journey indices: {from_index} -> {to_index}")
    return range(from_index, to_index)


def segments_overlap(a_from: int, a_to: int, b_from: int, b_to: int) -> bool:
    """True if journeys ``[a_from, a_to)`` and ``[b_from, b_to)`` share any segment."""
    return a_from < b_to and b_from < a_to


def is_range_free(occupied: Iterable[int], from_index: int, to_index: int) -> bool:
    """True if none of the segments of ``[from_index, to_index)`` is occupied."""
    occupied = set(occupied)
    return all(seg not in occupied for seg in segment_range(from_index, to_index))


def free_ranges(occupied: Iterable[int], start: int, end: int) -> list[tuple[int, int]]:
    """Maximal contiguous free journeys inside segments ``[start, end)``.

    Returns ``(from_stop, to_stop)`` pairs. Example: with 5 stops (segments 0..3),
    ``occupied={1}``, ``start=0`` -> ``[(0, 1), (2, 4)]``.
    """
    occupied = set(occupied)
    ranges: list[tuple[int, int]] = []
    run_start: int | None = None
    for seg in range(start, end):
        if seg in occupied:
            if run_start is not None:
                ranges.append((run_start, seg))
                run_start = None
        elif run_start is None:
            run_start = seg
    if run_start is not None and run_start < end:
        ranges.append((run_start, end))
    return ranges


def fit_waste(occupied: Iterable[int], from_index: int, to_index: int, lower_bound: int, segment_count: int) -> int:
    """How many free segments a booking would leave stranded around itself.

    Used for *best-fit* seat selection: filling a seat whose free gap exactly
    matches the requested journey keeps longer gaps on other seats intact for
    longer journeys, which maximises overall seat utilisation.

    ``lower_bound`` is the first segment that can still be sold (segments before it
    have already been travelled), so stranded segments behind the train are ignored.
    """
    occupied = set(occupied)
    left = from_index
    while left - 1 >= lower_bound and (left - 1) not in occupied:
        left -= 1
    right = to_index
    while right < segment_count and right not in occupied:
        right += 1
    return (from_index - left) + (right - to_index)
