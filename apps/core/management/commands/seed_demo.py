"""Load fictional demonstration data so the application is usable immediately.

    python manage.py seed_demo            # first-time load (refuses if data exists)
    python manage.py seed_demo --reset    # wipe the database and load fresh demo data

Every booking is created through the real allocation engine (``reserve_seats``),
so seed data obeys exactly the same no-overlap rules as live bookings.
"""
from __future__ import annotations

import datetime as dt
import os
import random

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import PassengerProfile, TTProfile, User
from apps.bookings.exceptions import AllocationError
from apps.bookings.models import BoardingStatus, Booking, Cancellation, Passenger, SeatAllocation
from apps.bookings.services.cancellation import cancel_booking
from apps.bookings.services.reservation import reserve_seats
from apps.core import seed_data as D
from apps.operations.models import ActivityLog, TrainSimulation
from apps.railway.models import Coach, Station, Train, TrainRoute, TrainStop

DEMO_TRAIN = "24051"


class Command(BaseCommand):
    help = "Load fictional demonstration data (stations, trains, users, bookings and the no-show scenario)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete ALL existing data first.")
        parser.add_argument("--seed", type=int, default=2026, help="Random seed for reproducible data.")
        parser.add_argument("--light", action="store_true", help="Only the demo scenario (faster, used by tests).")

    def handle(self, *args, **opts):
        if opts["reset"]:
            self.stdout.write("Resetting database…")
            call_command("flush", interactive=False, verbosity=0)
        elif Train.objects.exists():
            raise CommandError("Data already exists. Re-run with --reset to wipe it and load fresh demo data.")

        self.rng = random.Random(opts["seed"])
        self.password = os.getenv("DEMO_PASSWORD", "Demo@12345")
        self.today = timezone.localdate()

        with transaction.atomic():
            self.create_stations()
            self.create_trains()
            self.create_users()
        self.stage_demo_scenario()
        if not opts["light"]:
            self.create_history()
            self.create_future_bookings()
            self.create_demo_passenger_history()
            ActivityLog.objects.filter(action__in=["LOGIN", "LOGIN_FAILED"]).delete()
        self.print_summary()

    # ------------------------------------------------------------------ network
    def create_stations(self):
        for code, name, city, state, zone in D.STATIONS:
            Station.objects.create(code=code, name=name, city=city, state=state, zone=zone)

    def create_trains(self):
        stations = {s.code: s for s in Station.objects.all()}
        for spec in D.TRAINS:
            train = Train.objects.create(number=spec["number"], name=spec["name"], train_type=spec["type"],
                                         running_days=spec["days"], description=spec["description"])
            route = TrainRoute.objects.create(train=train, name=f"{spec['name']} route")
            for i, (code, arr, dep, day, km) in enumerate(spec["stops"]):
                TrainStop.objects.create(route=route, station=stations[code], sequence=i, arrival_time=arr,
                                         departure_time=dep, day_offset=day, distance_km=km,
                                         platform=str(self.rng.randint(1, 9)))
            for pos, (number, cls) in enumerate(spec["coaches"], start=1):
                Coach.objects.create(train=train, coach_number=number, coach_class=cls, position=pos).generate_seats()

    # -------------------------------------------------------------------- users
    def _user(self, username, first, last, email, role, **extra):
        user = User(username=username, first_name=first, last_name=last, email=email, role=role, **extra)
        user.set_password(self.password)
        user.save()
        return user

    def create_users(self):
        u, first, last, email = D.DEMO_ADMIN
        admin = self._user(u, first, last, email, User.Role.ADMIN, is_superuser=True, is_staff=True)
        self.admin = admin
        trains = {t.number: t for t in Train.objects.all()}
        self.tts = []
        for username, first, last, email, emp, desig, division, numbers in D.DEMO_TTS:
            tt = self._user(username, first, last, email, User.Role.TT, phone="98" + str(self.rng.randint(10000000, 99999999)))
            profile = TTProfile.objects.create(user=tt, employee_id=emp, designation=desig, division=division)
            profile.assigned_trains.set([trains[n] for n in numbers])
            self.tts.append(tt)
        self.demo_passengers = []
        for username, first, last, email, gender, berth in D.DEMO_PASSENGERS:
            p = self._user(username, first, last, email, User.Role.PASSENGER,
                           phone="9" + str(self.rng.randint(100000000, 999999999)))
            PassengerProfile.objects.filter(user=p).update(gender=gender, preferred_berth=berth, city="New Delhi",
                                                           state="Delhi", preferred_class="SL",
                                                           date_of_birth=dt.date(1998 + len(self.demo_passengers), 5, 14))
            self.demo_passengers.append(p)
        u, first, last, email, gender = D.NO_SHOW_PASSENGER
        self.no_show_user = self._user(u, first, last, email, User.Role.PASSENGER)
        self.fillers = [self._user(u, f, l, f"{u}@sitesmart.demo", User.Role.PASSENGER) for u, f, l in D.FILLER_USERS]

    # ---------------------------------------------------------------- helpers
    def _name(self):
        return f"{self.rng.choice(D.FIRST_NAMES)} {self.rng.choice(D.LAST_NAMES)}"

    def _pax(self, n):
        return [{"name": self._name(), "age": self.rng.randint(8, 74), "gender": self.rng.choice("MFMF")} for _ in range(n)]

    def _book(self, user, train, date, s, d, cls, seats=None, n=None, enforce=True, pax=None):
        stops = list(train.get_stops())
        return reserve_seats(
            user=user, train=train, journey_date=date, from_stop=stops[s], to_stop=stops[d], coach_class=cls,
            passengers=pax or self._pax(n or len(seats)), seat_ids=[x.id for x in seats] if seats else None,
            enforce_schedule=enforce,
        )

    # ------------------------------------------------------------ demo scenario
    def stage_demo_scenario(self):
        """24051 today: SL coaches fully sold on Kanpur→Lucknow and Lucknow→Varanasi.

        * S1: all 72 berths Delhi→Varanasi. Berth 25 belongs to Rahul Verma — the
          passenger the TT will mark as DID NOT BOARD during the presentation.
        * S2: berths 1-30 Kanpur→Varanasi; 31-50 shared by Kanpur→Lucknow and
          Lucknow→Varanasi passengers (segment sharing); 51-72 Delhi→Varanasi.
          Delhi→Kanpur is therefore still free on S2 berths 1-50.
        """
        train = Train.objects.get(number=DEMO_TRAIN)
        date = self.today
        s1 = list(Coach.objects.get(train=train, coach_number="S1").seats.order_by("seat_number"))
        s2 = list(Coach.objects.get(train=train, coach_number="S2").seats.order_by("seat_number"))

        groups = [s1[i:i + 6] for i in range(0, 24, 6)] + [[s1[24]]] + [s1[25:30]] + [s1[i:i + 6] for i in range(30, 72, 6)]
        for g in groups:
            if g[0].seat_number == 25:
                self._book(self.no_show_user, train, date, 0, 3, "SL", seats=g,
                           pax=[{"name": "Rahul Verma", "age": 34, "gender": "M"}])
            else:
                self._book(self.rng.choice(self.fillers), train, date, 0, 3, "SL", seats=g)
        for i in range(0, 30, 6):
            self._book(self.rng.choice(self.fillers), train, date, 1, 3, "SL", seats=s2[i:i + 6])
        for i in range(30, 50, 5):
            self._book(self.rng.choice(self.fillers), train, date, 1, 2, "SL", seats=s2[i:i + 5])
            self._book(self.rng.choice(self.fillers), train, date, 2, 3, "SL", seats=s2[i:i + 5])
        for i in range(50, 72, 6):
            self._book(self.rng.choice(self.fillers), train, date, 0, 3, "SL", seats=s2[i:i + 6])
        # Some AC passengers for realism (leaves AC classes partly available).
        for _ in range(9):
            s, d = sorted(self.rng.sample(range(4), 2))
            try:
                self._book(self.rng.choice(self.fillers), train, date, s, d, self.rng.choice(["3A", "3A", "2A"]),
                           n=self.rng.randint(1, 4))
            except AllocationError:
                pass
        self.demo_train = train

    # -------------------------------------------------------- historical runs
    def _random_bookings(self, train, date, attempts, enforce=True, users=None):
        stops = len(train.get_stops())
        classes = train.available_classes()
        made = []
        for _ in range(attempts):
            s, d = sorted(self.rng.sample(range(stops), 2))
            cls = self.rng.choice(classes)
            try:
                made.append(self._book(self.rng.choice(users or self.fillers), train, date, s, d, cls,
                                       n=self.rng.choice([1, 1, 2, 2, 3, 4]), enforce=enforce))
            except AllocationError:
                continue
        return made

    def _backdate(self, bookings, run_date):
        for b in bookings:
            when = timezone.make_aware(dt.datetime.combine(
                run_date - dt.timedelta(days=self.rng.randint(1, 12)),
                dt.time(self.rng.randint(7, 22), self.rng.randint(0, 59))))
            when = min(when, timezone.now() - dt.timedelta(minutes=5))
            Booking.objects.filter(pk=b.pk).update(created_at=when)
            ActivityLog.objects.filter(booking=b).update(created_at=when)

    def create_history(self):
        """Completed runs over the last 10 days, with TT verification, no-shows and reallocations."""
        self.stdout.write("Creating completed runs…")
        for train in Train.objects.exclude(number=DEMO_TRAIN).order_by("number"):
            tt = next((t for t in self.tts if t.tt_profile.assigned_trains.filter(pk=train.pk).exists()), self.tts[0])
            stops = list(train.get_stops())
            for back in range(10, 0, -1):
                date = self.today - dt.timedelta(days=back)
                if not train.runs_on(date):
                    continue
                bookings = self._random_bookings(train, date, 12, enforce=False)
                passengers = list(Passenger.objects.filter(booking__in=bookings).select_related("booking", "boarding"))
                no_shows = [p for p in passengers if self.rng.random() < 0.09]
                verified_at = timezone.make_aware(dt.datetime.combine(date, dt.time(9, 0)))
                for p in no_shows:
                    BoardingStatus.objects.filter(passenger=p).update(
                        status="NOT_BOARDED", verified_by=tt, verified_at=verified_at,
                        verified_at_stop=stops[p.booking.from_index])
                    SeatAllocation.objects.filter(passenger=p).update(status="RELEASED", released_at=verified_at)
                    log = ActivityLog.objects.create(
                        actor=tt, action="PASSENGER_NO_SHOW", category="BOARDING", train=train, booking=p.booking,
                        description=f"{p.name} (PNR {p.booking.pnr}) did not board at "
                                    f"{stops[p.booking.from_index].station.name}")
                    ActivityLog.objects.filter(pk=log.pk).update(created_at=verified_at)
                # Reallocate part of the released segments to later boarders.
                for p in no_shows[:2]:
                    b = p.booking
                    if b.to_index - b.from_index >= 2:
                        try:
                            rb = self._book(self.rng.choice(self.fillers), train, date, b.from_index + 1, b.to_index,
                                            b.coach_class, seats=[p.seat], enforce=False)
                            bookings.append(rb)
                        except AllocationError:
                            pass
                BoardingStatus.objects.filter(passenger__booking__in=bookings, status="PENDING").update(
                    status="BOARDED", verified_by=tt, verified_at=verified_at)
                TrainSimulation.objects.create(
                    train=train, journey_date=date, status=TrainSimulation.Status.COMPLETED,
                    current_index=len(stops) - 1, started_at=verified_at, completed_at=verified_at,
                    last_moved_at=verified_at, last_moved_by=tt)
                self._backdate(bookings, date)

    def create_future_bookings(self):
        self.stdout.write("Creating upcoming bookings…")
        cancelled = []
        for train in Train.objects.order_by("number"):
            for ahead in range(0, 8):
                date = self.today + dt.timedelta(days=ahead)
                if not train.runs_on(date) or (train.number == DEMO_TRAIN and ahead == 0):
                    continue
                made = self._random_bookings(train, date, 16)
                for b in made:
                    Booking.objects.filter(pk=b.pk).update(
                        created_at=timezone.now() - dt.timedelta(days=self.rng.randint(0, 9), hours=self.rng.randint(0, 20)))
                for b in made:
                    if self.rng.random() < 0.1:
                        cancelled.append(cancel_booking(b, b.user, reason=self.rng.choice(
                            ["Change of plans", "Travelling by road", "Meeting postponed", "Booked a different train"])))
        for c in cancelled:
            when = timezone.now() - dt.timedelta(days=self.rng.randint(0, 6), hours=self.rng.randint(1, 20))
            Cancellation.objects.filter(pk=c.pk).update(created_at=when)

    def create_demo_passenger_history(self):
        """Give the main demo passenger a realistic dashboard: upcoming, completed and cancelled trips."""
        ananya = self.demo_passengers[0]
        pink = Train.objects.get(number="19621")
        west = Train.objects.get(number="22907")
        date = self.today + dt.timedelta(days=3)
        while not pink.runs_on(date):
            date += dt.timedelta(days=1)
        self._book(ananya, pink, date, 0, 4, "CC", pax=[{"name": "Ananya Iyer", "age": 27, "gender": "F"},
                                                       {"name": "Lata Iyer", "age": 58, "gender": "F"}])
        b = self._book(ananya, west, self.today + dt.timedelta(days=5), 1, 4, "CC",
                       pax=[{"name": "Ananya Iyer", "age": 27, "gender": "F"}])
        cancel_booking(b, ananya, reason="Plans changed")
        past = self.today - dt.timedelta(days=4)
        while not pink.runs_on(past):
            past -= dt.timedelta(days=1)
        old = self._book(ananya, pink, past, 0, 4, "CC", enforce=False,
                         pax=[{"name": "Ananya Iyer", "age": 27, "gender": "F"}])
        BoardingStatus.objects.filter(passenger__booking=old).update(status="BOARDED", verified_by=self.tts[0],
                                                                     verified_at=timezone.now() - dt.timedelta(days=4))
        self._backdate([old], past)

    # ---------------------------------------------------------------- summary
    def print_summary(self):
        s = self.style
        self.stdout.write(s.SUCCESS("\nDemo data loaded."))
        self.stdout.write(f"  Stations: {Station.objects.count()}   Trains: {Train.objects.count()}   "
                          f"Bookings: {Booking.objects.count()}   Seat-segment rows: {SeatAllocation.objects.count()}")
        self.stdout.write(s.MIGRATE_HEADING("\nDemo accounts (password: %s)" % self.password))
        self.stdout.write("  Administrator   admin")
        self.stdout.write("  TT / TTE        tt_demo   (assigned to 24051 Kashi SmartSeat Express)")
        self.stdout.write("  Passengers      passenger, passenger2, passenger3")
        self.stdout.write(s.MIGRATE_HEADING("\nNo-show demonstration (run date %s)" % self.today.strftime("%d %b %Y")))
        self.stdout.write("  1. Sign in as tt_demo → open 24051 → Start run (train at New Delhi).")
        self.stdout.write("  2. Mark Rahul Verma (S1/25, New Delhi → Varanasi) as Did not board.")
        self.stdout.write("  3. Sign in as passenger → search Kanpur → Lucknow, Sleeper → book S1/25.")
        self.stdout.write("  4. Sign in as passenger2 → search Lucknow → Varanasi, Sleeper → book S1/25.")
        self.stdout.write("  5. Kanpur → Varanasi on S1/25 is rejected (overlaps step 3).")
