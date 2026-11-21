"""Simultaneous booking requests for the same seat: exactly one may win."""
import threading

from django.db import close_old_connections, connection
import unittest

from django.test import TransactionTestCase

from apps.bookings.exceptions import SeatUnavailableError
from apps.bookings.models import Booking, SeatAllocation
from apps.bookings.services.reservation import reserve_seats
from apps.core.testing import make_route_train, make_user, next_run_date, pax, stop


class ConcurrentBookingTests(TransactionTestCase):
    """Uses real threads, each with its own database connection (needs a file-backed test DB)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if connection.vendor == "sqlite" and connection.is_in_memory_db():
            raise unittest.SkipTest("Concurrency tests need a file-backed test database.")

    def setUp(self):
        self.train = make_route_train(seats=2)
        self.users = [make_user(f"racer{i}") for i in range(8)]
        self.seat = self.train.coaches.get().seats.order_by("seat_number").first()
        self.date = next_run_date(self.train)

    def race(self, journeys):
        barrier = threading.Barrier(len(journeys))
        outcomes = []
        lock = threading.Lock()

        def attempt(user, s, d):
            close_old_connections()
            try:
                barrier.wait()
                reserve_seats(user=user, train=self.train, journey_date=self.date, from_stop=stop(self.train, s),
                              to_stop=stop(self.train, d), coach_class="SL", passengers=[pax()],
                              seat_ids=[self.seat.id])
                result = "won"
            except SeatUnavailableError:
                result = "lost"
            except Exception as exc:  # any other error is a test failure
                result = f"error: {exc!r}"
            finally:
                connection.close()
            with lock:
                outcomes.append(result)

        threads = [threading.Thread(target=attempt, args=(u, s, d)) for u, (s, d) in zip(self.users, journeys)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        return outcomes

    def test_eight_identical_requests_produce_one_booking(self):
        outcomes = self.race([(0, 4)] * 8)
        self.assertEqual(outcomes.count("won"), 1, outcomes)
        self.assertEqual(outcomes.count("lost"), 7, outcomes)
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(SeatAllocation.objects.filter(seat=self.seat, status="ACTIVE").count(), 4)

    def test_overlapping_concurrent_requests_never_double_book(self):
        # B->D, C->E, A->C, B->C all overlap pairwise in some way; D->E overlaps none of A->C/B->C.
        journeys = [(1, 3), (2, 4), (0, 2), (1, 2), (3, 4), (0, 1)]
        self.race(journeys)
        segments = list(SeatAllocation.objects.filter(seat=self.seat, status="ACTIVE")
                        .values_list("segment_index", flat=True))
        self.assertEqual(len(segments), len(set(segments)), "a segment was sold twice")
        self.assertGreaterEqual(Booking.objects.count(), 2)
