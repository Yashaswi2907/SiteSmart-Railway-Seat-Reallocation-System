"""Narrate the Delhi → Kanpur → Lucknow → Varanasi no-show scenario in the terminal.

    python manage.py run_demo_scenario            # dry run: everything is rolled back
    python manage.py run_demo_scenario --commit   # keep the result (as if done in the UI)

Requires the data from ``seed_demo``. Each step calls the same service functions the
web interface uses, so the printed outcome is exactly what the UI would show.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.exceptions import AllocationError
from apps.bookings.models import Passenger
from apps.bookings.services.availability import check_seat_availability, class_availability
from apps.bookings.services.boarding import process_no_show
from apps.bookings.services.reservation import reserve_seats
from apps.operations.services.simulation import get_or_create_simulation, start_simulation
from apps.railway.models import Train


class Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Walk through the no-show reallocation scenario step by step (rolled back unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--commit", action="store_true", help="Keep the changes instead of rolling back.")

    def ok(self, msg):
        self.stdout.write(self.style.SUCCESS("  ✓ ") + msg)

    def no(self, msg):
        self.stdout.write(self.style.ERROR("  ✗ ") + msg)

    def step(self, n, title):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nStep {n}. {title}"))

    def avail(self, train, date, a, b):
        stops = {s.station.code: s.sequence for s in train.get_stops()}
        return class_availability(train, date, stops[a], stops[b]).get("SL", {})

    def handle(self, *args, **opts):
        try:
            train = Train.objects.get(number="24051")
            rahul = Passenger.objects.select_related("seat__coach", "booking").get(
                name="Rahul Verma", booking__train=train, booking__journey_date=timezone.localdate())
            tt = User.objects.get(username="tt_demo")
            p2, p3 = User.objects.get(username="passenger"), User.objects.get(username="passenger2")
        except (Train.DoesNotExist, Passenger.DoesNotExist, User.DoesNotExist):
            raise CommandError("Demo data for today was not found. Run: python manage.py seed_demo --reset") from None

        date, seat = timezone.localdate(), rahul.seat
        self.stdout.write(self.style.SQL_TABLE(f"Train {train} · run of {date:%d %b %Y} · seat {seat.label}"))
        try:
            with transaction.atomic():
                self.step(1, "Before verification — Sleeper is sold out on the middle segments")
                for a, b in [("CNB", "LKO"), ("LKO", "BSB"), ("NDLS", "CNB")]:
                    av = self.avail(train, date, a, b)
                    self.stdout.write(f"    SL {a}→{b}: {av.get('available', 0)} of {av.get('total', 0)} free")

                self.step(2, "TT starts the run and marks Rahul Verma as DID NOT BOARD at New Delhi")
                sim = get_or_create_simulation(train, date)
                if sim.status == sim.Status.SCHEDULED:
                    start_simulation(sim, tt)
                if rahul.boarding.status == "PENDING":
                    result = process_no_show(rahul, tt, remarks="Demo scenario")
                    self.ok(f"Seat {result['seat']} released for {', '.join(result['released_ranges'])}")
                else:
                    self.ok(f"Already verified as {rahul.boarding.get_status_display()}")
                av = self.avail(train, date, "CNB", "LKO")
                self.stdout.write(f"    SL CNB→LKO now: {av['available']} free ({av['reallocated']} released by a no-show)")

                self.step(3, "Passenger 2 books Kanpur → Lucknow")
                b2 = reserve_seats(user=p2, train=train, journey_date=date, from_stop="CNB", to_stop="LKO",
                                   coach_class="SL", passengers=[{"name": "Ananya Iyer", "age": 27, "gender": "F"}])
                self.ok(f"PNR {b2.pnr} → seat {b2.passengers.get().seat.label} (reallocated: {b2.is_reallocated})")

                self.step(4, "Passenger 3 books Lucknow → Varanasi on the same berth")
                b3 = reserve_seats(user=p3, train=train, journey_date=date, from_stop="LKO", to_stop="BSB",
                                   coach_class="SL", passengers=[{"name": "Rohan Gupta", "age": 31, "gender": "M"}],
                                   seat_ids=[seat.id])
                self.ok(f"PNR {b3.pnr} → seat {b3.passengers.get().seat.label}; CNB→LKO and LKO→BSB only touch at LKO")

                self.step(5, "Overlapping journeys on the same berth are rejected")
                for a, b in [("CNB", "BSB"), ("NDLS", "LKO")]:
                    stops = {s.station.code: s.sequence for s in train.get_stops()}
                    check = check_seat_availability(seat, date, stops[a], stops[b])
                    try:
                        reserve_seats(user=p2, train=train, journey_date=date, from_stop=a, to_stop=b,
                                      coach_class="SL", passengers=[{"name": "Test Rider", "age": 30, "gender": "M"}],
                                      seat_ids=[seat.id])
                        self.no(f"{a}→{b} was accepted — this should never happen")
                    except AllocationError as exc:
                        self.ok(f"{a}→{b} rejected: {exc.message}")
                        if check.conflicts:
                            self.stdout.write(f"      conflicts on: {', '.join(c['segment'] for c in check.conflicts)}")
                if not opts["commit"]:
                    raise Rollback
        except Rollback:
            self.stdout.write(self.style.WARNING("\nDry run complete — all changes rolled back. Use --commit to keep them."))
            return
        self.stdout.write(self.style.SUCCESS("\nScenario committed."))
