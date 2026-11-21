"""Database-level tests of the segment-based seat reallocation engine."""
import datetime as dt
from itertools import combinations
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import User
from apps.bookings.exceptions import (
    BoardingActionError,
    CancellationError,
    InsufficientSeatsError,
    InvalidJourneyError,
    SeatUnavailableError,
    TrainDepartedError,
)
from apps.bookings.models import BoardingStatus, Booking, Passenger, SeatAllocation
from apps.bookings.services.availability import (
    build_journey_context,
    check_seat_availability,
    class_availability,
    find_eligible_seats,
    get_available_seats,
    released_seats_report,
)
from apps.bookings.services.boarding import mark_passenger_boarded, process_no_show
from apps.bookings.services.cancellation import cancel_booking
from apps.bookings.services.reservation import reserve_seats
from apps.core.testing import make_route_train, make_user, next_run_date, pax, stop
from apps.operations.services.simulation import advance_simulation, get_or_create_simulation, start_simulation

A, B, C, D, E = range(5)


class EngineTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.train = make_route_train(seats=4)
        cls.alice = make_user("alice")
        cls.bob = make_user("bob")
        cls.carol = make_user("carol")
        cls.tt = make_user("ttone", role=User.Role.TT)
        cls.tt.tt_profile.assigned_trains.add(cls.train)
        cls.admin = make_user("boss", role=User.Role.ADMIN)
        cls.seats = list(cls.train.coaches.get().seats.order_by("seat_number"))

    def setUp(self):
        self.date = next_run_date(self.train)

    # helpers ---------------------------------------------------------------
    def book(self, user, s, d, seats=None, n=1, date=None):
        return reserve_seats(
            user=user, train=self.train, journey_date=date or self.date,
            from_stop=stop(self.train, s), to_stop=stop(self.train, d), coach_class="SL",
            passengers=[pax(f"Traveller {chr(65 + i)}") for i in range(n)],
            seat_ids=[x.id for x in seats] if seats else None,
        )

    def seat_free(self, seat, s, d, date=None):
        return check_seat_availability(seat, date or self.date, s, d).available

    def fill_other_seats(self):
        """Occupy seats 2..4 for the whole route so only seat 1 matters."""
        return self.book(self.carol, A, E, seats=self.seats[1:], n=3)

    def start_run(self):
        sim = get_or_create_simulation(self.train, self.date)
        return start_simulation(sim, self.admin)


class ReservationTests(EngineTestCase):
    def test_booking_creates_one_allocation_per_segment(self):
        booking = self.book(self.alice, B, E, seats=[self.seats[0]])
        self.assertEqual(len(booking.pnr), 10)
        self.assertTrue(booking.pnr.isdigit())
        allocs = SeatAllocation.objects.filter(passenger__booking=booking).order_by("segment_index")
        self.assertEqual([a.segment_index for a in allocs], [1, 2, 3])
        self.assertTrue(all(a.status == SeatAllocation.Status.ACTIVE for a in allocs))
        self.assertEqual(BoardingStatus.objects.get(passenger__booking=booking).status, "PENDING")

    def test_full_journey_blocks_every_sub_journey(self):
        self.book(self.alice, A, E, seats=[self.seats[0]])
        for s, d in combinations(range(5), 2):
            self.assertFalse(self.seat_free(self.seats[0], s, d), (s, d))

    def test_spec_non_overlapping_bookings_share_a_seat(self):
        seat = self.seats[0]
        self.book(self.alice, B, C, seats=[seat])
        self.book(self.bob, C, D, seats=[seat])  # touches at C only
        self.book(self.carol, A, B, seats=[seat])
        self.book(self.carol, D, E, seats=[seat])
        self.assertEqual(SeatAllocation.objects.filter(seat=seat, status="ACTIVE").count(), 4)

    def test_spec_overlapping_bookings_rejected(self):
        seat = self.seats[0]
        self.book(self.alice, B, D, seats=[seat])
        with self.assertRaises(SeatUnavailableError) as ctx:
            self.book(self.bob, C, E, seats=[seat])
        self.assertIn("overlap", ctx.exception.message.lower())
        self.assertEqual(Booking.objects.count(), 1)  # nothing half-written

    def test_every_pair_of_journeys_matches_interval_overlap(self):
        """Exhaustive check over all 10 x 10 journey pairs on a 5-stop route."""
        journeys = list(combinations(range(5), 2))
        offset = 0
        for first in journeys:
            for second in journeys:
                offset += 1
                date = next_run_date(self.train, offset % 110 + 1)
                SeatAllocation.objects.filter(journey_date=date).delete()
                seat = self.seats[0]
                self.book(self.alice, *first, seats=[seat], date=date)
                overlap = bool(set(range(*first)) & set(range(*second)))
                if overlap:
                    with self.assertRaises(SeatUnavailableError, msg=f"{first} vs {second}"):
                        self.book(self.bob, *second, seats=[seat], date=date)
                else:
                    self.book(self.bob, *second, seats=[seat], date=date)
                SeatAllocation.objects.filter(journey_date=date).delete()

    def test_partial_failure_rolls_back_whole_group(self):
        self.book(self.alice, C, D, seats=[self.seats[1]])
        with self.assertRaises(SeatUnavailableError):
            self.book(self.bob, B, E, seats=[self.seats[0], self.seats[1]], n=2)
        self.assertFalse(Booking.objects.filter(user=self.bob).exists())
        self.assertTrue(self.seat_free(self.seats[0], A, E))

    def test_stale_seat_selection_is_revalidated(self):
        """User A picks seat 1 on the map, user B books it first; A's confirm must fail."""
        seat = self.seats[0]
        self.assertTrue(self.seat_free(seat, B, D))      # what A saw
        self.book(self.bob, C, E, seats=[seat])          # B wins the race
        with self.assertRaises(SeatUnavailableError):
            self.book(self.alice, B, D, seats=[seat])    # A confirms with stale view

    def test_database_constraint_blocks_duplicate_active_segment(self):
        booking = self.book(self.alice, A, C, seats=[self.seats[0]])
        passenger = booking.passengers.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SeatAllocation.objects.create(
                passenger=passenger, seat=self.seats[0], journey_date=self.date, segment_index=1
            )

    def test_race_lost_inside_transaction_is_reported_cleanly(self):
        """Simulate a concurrent request that slipped past the availability check."""
        seat = self.seats[0]
        self.book(self.alice, A, E, seats=[seat])
        with mock.patch("apps.bookings.services.reservation.occupied_segments", return_value={}):
            with self.assertRaises(SeatUnavailableError) as ctx:
                self.book(self.bob, B, C, seats=[seat])
        self.assertEqual(ctx.exception.code, "race_lost")
        self.assertEqual(Booking.objects.filter(user=self.bob).count(), 0)

    def test_validation_errors(self):
        with self.assertRaises(InvalidJourneyError):
            self.book(self.alice, D, B)
        with self.assertRaises(InvalidJourneyError):
            self.book(self.alice, A, B, date=dt.date.today() - dt.timedelta(days=2))
        with self.assertRaises(InvalidJourneyError):
            self.book(self.alice, A, B, seats=[self.seats[0], self.seats[0]], n=2)
        with self.assertRaises(InvalidJourneyError):
            reserve_seats(user=self.alice, train=self.train, journey_date=self.date, from_stop=stop(self.train, A),
                          to_stop=stop(self.train, B), coach_class="SL", passengers=[pax("Xavier", age=0)])
        with self.assertRaises(InvalidJourneyError):
            reserve_seats(user=self.alice, train=self.train, journey_date=self.date, from_stop=stop(self.train, A),
                          to_stop=stop(self.train, B), coach_class="1A", passengers=[pax()])

    def test_train_not_running_on_date(self):
        self.train.running_days = "1000000"  # Mondays only
        self.train.save()
        date = next_run_date(None, 1)
        while date.weekday() == 0:
            date += dt.timedelta(days=1)
        with self.assertRaises(InvalidJourneyError) as ctx:
            self.book(self.alice, A, B, date=date)
        self.assertEqual(ctx.exception.code, "not_running")

    def test_insufficient_seats(self):
        self.book(self.alice, A, E, seats=self.seats[:3], n=3)
        with self.assertRaises(InsufficientSeatsError):
            self.book(self.bob, B, C, n=2)

    def test_class_availability_counts(self):
        self.book(self.alice, A, C, seats=[self.seats[0]])
        summary = class_availability(self.train, self.date, C, E)
        self.assertEqual(summary["SL"], {"total": 4, "available": 4, "reallocated": 0})
        summary = class_availability(self.train, self.date, B, D)
        self.assertEqual(summary["SL"]["available"], 3)


class NoShowReallocationTests(EngineTestCase):
    def test_complete_specification_scenario(self):
        """A->E passenger no-show; B->C and C->D then share the seat; overlaps rejected."""
        seat = self.seats[0]
        self.fill_other_seats()
        p1 = self.book(self.alice, A, E, seats=[seat]).passengers.get()

        # Before verification nothing is available for B->C.
        ctx = build_journey_context(self.train, self.date, stop(self.train, B), stop(self.train, C))
        with self.assertRaises(InsufficientSeatsError):
            find_eligible_seats(ctx, "SL", 1)

        self.start_run()  # train at A
        result = process_no_show(p1, self.tt)
        self.assertEqual(result["released_segments"], [0, 1, 2, 3])
        p1.refresh_from_db()
        self.assertEqual(p1.boarding.status, BoardingStatus.Status.NOT_BOARDED)
        self.assertEqual(p1.boarding.verified_by, self.tt)

        # Passenger 2: B->C is auto-assigned the released seat and flagged as a reallocation.
        b2 = self.book(self.bob, B, C)
        self.assertEqual(b2.passengers.get().seat, seat)
        self.assertTrue(b2.is_reallocated)
        # Passenger 3: C->D on the same seat is allowed.
        b3 = self.book(self.carol, C, D, seats=[seat])
        self.assertTrue(b3.passengers.get().is_reallocated_seat)
        # Overlaps with the new occupants are rejected.
        for s, d in [(B, D), (C, E), (A, C), (B, C)]:
            with self.assertRaises((SeatUnavailableError, InsufficientSeatsError), msg=(s, d)):
                self.book(self.alice, s, d, seats=[seat])
        # D->E is still free and can be sold.
        self.book(self.alice, D, E, seats=[seat])

    def test_alternative_overlap_pair(self):
        seat = self.seats[0]
        p1 = self.book(self.alice, A, E, seats=[seat]).passengers.get()
        self.start_run()
        process_no_show(p1, self.tt)
        self.book(self.bob, B, D, seats=[seat])
        with self.assertRaises(SeatUnavailableError):
            self.book(self.carol, C, E, seats=[seat])

    def test_seat_not_released_without_verification(self):
        seat = self.seats[0]
        self.book(self.alice, A, E, seats=[seat])
        self.start_run()
        with self.assertRaises(SeatUnavailableError):
            self.book(self.bob, B, C, seats=[seat])

    def test_boarded_passenger_cannot_be_marked_no_show(self):
        seat = self.seats[0]
        p1 = self.book(self.alice, A, E, seats=[seat]).passengers.get()
        self.start_run()
        mark_passenger_boarded(p1, self.tt)
        with self.assertRaises(BoardingActionError):
            process_no_show(p1, self.tt)
        self.assertFalse(self.seat_free(seat, B, C))
        self.assertEqual(SeatAllocation.objects.filter(seat=seat, status="ACTIVE").count(), 4)

    def test_no_show_cannot_be_marked_twice_or_reverted(self):
        p1 = self.book(self.alice, A, E, seats=[self.seats[0]]).passengers.get()
        self.start_run()
        process_no_show(p1, self.tt)
        with self.assertRaises(BoardingActionError):
            process_no_show(p1, self.tt)
        with self.assertRaises(BoardingActionError):
            mark_passenger_boarded(p1, self.tt)

    def test_no_show_requires_train_to_reach_boarding_station(self):
        p = self.book(self.alice, C, E, seats=[self.seats[0]]).passengers.get()
        with self.assertRaises(BoardingActionError):  # run not started
            process_no_show(p, self.tt)
        self.start_run()  # at A, passenger boards at C
        with self.assertRaises(BoardingActionError):
            process_no_show(p, self.tt)

    def test_unassigned_tt_and_passengers_cannot_verify(self):
        other_tt = make_user("tttwo", role=User.Role.TT)
        p = self.book(self.alice, A, E, seats=[self.seats[0]]).passengers.get()
        self.start_run()
        with self.assertRaises(PermissionDenied):
            process_no_show(p, other_tt)
        with self.assertRaises(PermissionDenied):
            process_no_show(p, self.alice)
        process_no_show(p, self.admin)  # administrators may act on any train

    def test_departed_segments_never_reopen(self):
        """No-show verified late (train already past B): only C onwards becomes sellable."""
        seat = self.seats[0]
        self.fill_other_seats()
        p1 = self.book(self.alice, A, E, seats=[seat]).passengers.get()
        sim = self.start_run()
        advance_simulation(sim, self.admin, to_next_station=True)  # at B
        advance_simulation(sim, self.admin)                        # departed B
        result = process_no_show(p1, self.tt)
        self.assertEqual(result["sellable_segments"], [2, 3])
        with self.assertRaises(TrainDepartedError):
            self.book(self.bob, B, C, seats=[seat])
        with self.assertRaises(TrainDepartedError):
            self.book(self.bob, A, D)
        b = self.book(self.bob, C, E)
        self.assertEqual(b.passengers.get().seat, seat)

    def test_booking_from_current_station_while_halted(self):
        seat = self.seats[0]
        p1 = self.book(self.alice, A, E, seats=[seat]).passengers.get()
        sim = self.start_run()
        advance_simulation(sim, self.admin, to_next_station=True)  # halted at B
        process_no_show(p1, self.tt)
        self.book(self.bob, B, C, seats=[seat])  # boarding at the current halt is allowed

    def test_partial_no_show_only_releases_that_passengers_seat(self):
        booking = self.book(self.alice, A, E, seats=self.seats[:2], n=2)
        p1, p2 = booking.passengers.order_by("id")
        self.start_run()
        process_no_show(p1, self.tt)
        mark_passenger_boarded(p2, self.tt)
        self.assertTrue(self.seat_free(self.seats[0], B, E))
        self.assertFalse(self.seat_free(self.seats[1], B, E))

    def test_released_seats_report_lists_eligible_ranges(self):
        seat = self.seats[0]
        p1 = self.book(self.alice, A, E, seats=[seat]).passengers.get()
        self.start_run()
        process_no_show(p1, self.tt)
        self.book(self.bob, B, C, seats=[seat])
        report = released_seats_report(self.train, self.date)
        self.assertEqual(len(report), 1)
        ranges = [(r["from_index"], r["to_index"]) for r in report[0]["eligible_ranges"]]
        self.assertEqual(ranges, [(A, B), (C, E)])
        states = [t["state"] for t in report[0]["timeline"]]
        self.assertEqual(states, ["released", "occupied", "released", "released"])

    def test_best_fit_prefers_released_fragment(self):
        """With an empty seat and a released B->C gap available, B->C goes to the gap."""
        seat = self.seats[0]
        self.book(self.carol, A, B, seats=[seat])
        self.book(self.carol, C, E, seats=[seat])
        ctx = build_journey_context(self.train, self.date, stop(self.train, B), stop(self.train, C))
        chosen = find_eligible_seats(ctx, "SL", 1)
        self.assertEqual(chosen[0], seat)


class CancellationTests(EngineTestCase):
    def test_cancellation_frees_segments_immediately(self):
        booking = self.book(self.alice, A, E, seats=[self.seats[0]])
        cancellation = cancel_booking(booking, self.alice, reason="Plans changed")
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)
        self.assertEqual(cancellation.segments_released, 4)
        self.assertTrue(self.seat_free(self.seats[0], A, E))
        self.assertGreater(cancellation.refund_amount, 0)
        self.assertEqual(
            SeatAllocation.objects.filter(passenger__booking=booking, status="CANCELLED").count(), 4
        )
        self.book(self.bob, A, E, seats=[self.seats[0]])

    def test_only_owner_or_admin_can_cancel(self):
        booking = self.book(self.alice, A, E)
        with self.assertRaises(PermissionDenied):
            cancel_booking(booking, self.bob)
        cancel_booking(booking, self.admin)

    def test_cannot_cancel_twice(self):
        booking = self.book(self.alice, A, E)
        cancel_booking(booking, self.alice)
        with self.assertRaises(CancellationError):
            cancel_booking(booking, self.alice)

    def test_cannot_cancel_after_verification_or_departure(self):
        booking = self.book(self.alice, A, E, seats=[self.seats[0]])
        later = self.book(self.bob, C, E, seats=[self.seats[1]])
        sim = self.start_run()
        mark_passenger_boarded(booking.passengers.get(), self.tt)
        with self.assertRaises(CancellationError):
            cancel_booking(booking, self.alice)
        advance_simulation(sim, self.admin, to_next_station=True)
        advance_simulation(sim, self.admin, to_next_station=True)  # at C
        cancel_booking(later, self.bob)  # still at boarding station: allowed

    def test_cancel_blocked_once_boarding_station_departed(self):
        booking = self.book(self.alice, B, E, seats=[self.seats[0]])
        sim = self.start_run()
        advance_simulation(sim, self.admin, to_next_station=True)  # at B
        advance_simulation(sim, self.admin)                        # departed B
        with self.assertRaises(CancellationError):
            cancel_booking(booking, self.alice)


class AvailabilityListTests(EngineTestCase):
    def test_get_available_seats_ignores_inactive(self):
        self.seats[3].is_active = False
        self.seats[3].save()
        seats = get_available_seats(self.train, self.date, A, E)
        self.assertEqual(len(seats), 3)

    def test_passenger_rows_reference_chosen_seat(self):
        b = self.book(self.alice, A, B, seats=[self.seats[2]])
        self.assertEqual(Passenger.objects.get(booking=b).seat, self.seats[2])
