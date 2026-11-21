"""Pure segment arithmetic — the mathematical heart of the reallocation engine."""
from itertools import combinations

from django.test import SimpleTestCase

from apps.bookings.services.segments import (
    fit_waste,
    free_ranges,
    is_range_free,
    segment_range,
    segments_overlap,
)

# Route A(0) -> B(1) -> C(2) -> D(3) -> E(4)
A, B, C, D, E = range(5)


class SegmentRangeTests(SimpleTestCase):
    def test_journey_occupies_half_open_range(self):
        self.assertEqual(list(segment_range(A, E)), [0, 1, 2, 3])
        self.assertEqual(list(segment_range(B, C)), [1])
        self.assertEqual(list(segment_range(C, D)), [2])

    def test_invalid_ranges_rejected(self):
        for bad in [(C, C), (D, B), (-1, 2)]:
            with self.assertRaises(ValueError):
                segment_range(*bad)


class OverlapTests(SimpleTestCase):
    def test_specification_examples(self):
        # B->C and C->D only touch at C: allowed on the same seat.
        self.assertFalse(segments_overlap(B, C, C, D))
        # B->D and C->E share segment C->D: must be rejected.
        self.assertTrue(segments_overlap(B, D, C, E))
        # Original A->E overlaps every possible journey.
        for s, d in combinations(range(5), 2):
            self.assertTrue(segments_overlap(A, E, s, d), (s, d))

    def test_overlap_is_symmetric_and_matches_brute_force(self):
        journeys = list(combinations(range(6), 2))
        for (s1, d1) in journeys:
            for (s2, d2) in journeys:
                brute = bool(set(range(s1, d1)) & set(range(s2, d2)))
                self.assertEqual(segments_overlap(s1, d1, s2, d2), brute, (s1, d1, s2, d2))
                self.assertEqual(segments_overlap(s1, d1, s2, d2), segments_overlap(s2, d2, s1, d1))

    def test_is_range_free(self):
        occupied = {1}  # B->C taken
        self.assertTrue(is_range_free(occupied, C, E))
        self.assertTrue(is_range_free(occupied, A, B))
        self.assertFalse(is_range_free(occupied, A, C))


class FreeRangeTests(SimpleTestCase):
    def test_free_ranges_split_around_occupied(self):
        self.assertEqual(free_ranges({1}, 0, 4), [(0, 1), (2, 4)])
        self.assertEqual(free_ranges(set(), 1, 4), [(1, 4)])
        self.assertEqual(free_ranges({0, 1, 2, 3}, 0, 4), [])
        self.assertEqual(free_ranges({3}, 1, 4), [(1, 3)])

    def test_free_ranges_respect_start(self):
        # Train already past B: only C onwards is sellable.
        self.assertEqual(free_ranges(set(), 2, 4), [(2, 4)])
        self.assertEqual(free_ranges(set(), 4, 4), [])


class FitWasteTests(SimpleTestCase):
    def test_exact_fit_has_zero_waste(self):
        # Seat occupied A->B and C->E; request B->C fits perfectly.
        self.assertEqual(fit_waste({0, 2, 3}, B, C, 0, 4), 0)

    def test_empty_seat_wastes_the_rest_of_the_route(self):
        self.assertEqual(fit_waste(set(), B, C, 0, 4), 3)
        # Segments behind the train (before lower bound) are not counted.
        self.assertEqual(fit_waste(set(), B, C, 1, 4), 2)
