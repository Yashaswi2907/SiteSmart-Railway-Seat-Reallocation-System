"""Administrator portal CRUD, route-lock protection and demo-data commands."""
import io

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import TTProfile, User
from apps.bookings.models import Booking
from apps.bookings.services.availability import class_availability
from apps.bookings.services.reservation import reserve_seats
from apps.core.testing import make_route_train, make_user, next_run_date, pax, stop
from apps.operations.models import ActivityLog
from apps.railway.models import Coach, Station, Train, TrainStop


class AdminCrudTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("chief", role=User.Role.ADMIN)
        cls.train = make_route_train(seats=4)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_create_train_route_and_coach(self):
        r = self.client.post(reverse("adminpanel:train_create"), {
            "number": "55555", "name": "Campus Shuttle", "train_type": "EXPRESS",
            "running_days": ["0", "2", "4"], "description": "", "is_active": "on"})
        train = Train.objects.get(number="55555")
        self.assertRedirects(r, reverse("adminpanel:train_detail", args=[train.pk]))
        self.assertEqual(train.running_days, "1010100")
        a, b = Station.objects.get(code="TA"), Station.objects.get(code="TB")
        for st, arr, dep, km in [(a, "", "08:00", 0), (b, "09:00", "", 60)]:
            self.client.post(reverse("adminpanel:stop_add", args=[train.pk]), {
                "station": st.pk, "arrival_time": arr, "departure_time": dep, "day_offset": 0, "distance_km": km})
        self.assertEqual([s.station.code for s in train.get_stops()], ["TA", "TB"])
        self.client.post(reverse("adminpanel:coach_add", args=[train.pk]),
                         {"coach_number": "s1", "coach_class": "SL", "position": 1, "is_active": "on"})
        coach = Coach.objects.get(train=train)
        self.assertEqual(coach.coach_number, "S1")
        self.assertEqual(coach.seats.count(), 72)
        self.assertEqual(coach.seats.get(seat_number=7).berth_type, "SL")
        self.assertTrue(ActivityLog.objects.filter(action="ADMIN_CHANGE").exists())

    def test_running_days_requires_one_day(self):
        r = self.client.post(reverse("adminpanel:train_create"), {
            "number": "55556", "name": "Ghost", "train_type": "EXPRESS", "is_active": "on"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Train.objects.filter(number="55556").exists())

    def test_route_locked_when_future_bookings_exist(self):
        reserve_seats(user=make_user("rider"), train=self.train, journey_date=next_run_date(self.train),
                      from_stop=stop(self.train, 0), to_stop=stop(self.train, 2), coach_class="SL", passengers=[pax()])
        first = stop(self.train, 0)
        self.client.post(reverse("adminpanel:stop_delete", args=[first.pk]))
        self.client.post(reverse("adminpanel:stop_move", args=[first.pk, "down"]))
        self.assertEqual([s.sequence for s in self.train.get_stops()], [0, 1, 2, 3, 4])
        self.assertEqual(stop(self.train, 0).pk, first.pk)

    def test_stop_reorder_and_delete_resequence(self):
        second = stop(self.train, 1)
        self.client.post(reverse("adminpanel:stop_move", args=[second.pk, "up"]))
        self.assertEqual(stop(self.train, 0).pk, second.pk)
        self.client.post(reverse("adminpanel:stop_delete", args=[second.pk]))
        self.assertEqual([s.sequence for s in self.train.get_stops()], [0, 1, 2, 3])

    def test_station_crud_and_protection(self):
        self.client.post(reverse("adminpanel:station_create"),
                         {"code": "xyz", "name": "Xyz Halt", "city": "X", "state": "Y", "zone": "", "is_active": "on"})
        xyz = Station.objects.get(code="XYZ")
        self.client.post(reverse("adminpanel:station_delete", args=[xyz.pk]))
        self.assertFalse(Station.objects.filter(code="XYZ").exists())
        used = Station.objects.get(code="TA")
        self.client.post(reverse("adminpanel:station_delete", args=[used.pk]))
        self.assertTrue(Station.objects.filter(code="TA").exists())

    def test_train_with_bookings_cannot_be_deleted(self):
        reserve_seats(user=make_user("rider2"), train=self.train, journey_date=next_run_date(self.train),
                      from_stop=stop(self.train, 0), to_stop=stop(self.train, 1), coach_class="SL", passengers=[pax()])
        self.client.post(reverse("adminpanel:train_delete", args=[self.train.pk]))
        self.assertTrue(Train.objects.filter(pk=self.train.pk).exists())

    def test_create_tt_and_assign_trains(self):
        r = self.client.post(reverse("adminpanel:staff_create"), {
            "first_name": "Om", "last_name": "Prakash", "username": "om_tt", "email": "om@example.test",
            "phone": "", "is_active": "on", "employee_id": "tte-2001", "designation": "TTE", "division": "Test",
            "assigned_trains": [self.train.pk], "is_on_duty": "on", "password": "Ex4mple!Pass#1"})
        self.assertRedirects(r, reverse("adminpanel:staff_list"))
        user = User.objects.get(username="om_tt")
        self.assertEqual(user.role, User.Role.TT)
        self.assertTrue(user.check_password("Ex4mple!Pass#1"))
        profile = TTProfile.objects.get(user=user)
        self.assertEqual(profile.employee_id, "TTE-2001")
        self.assertEqual(list(profile.assigned_trains.all()), [self.train])

    def test_toggle_user_and_seat(self):
        rider = make_user("rider3")
        self.client.post(reverse("adminpanel:user_toggle", args=[rider.pk]))
        rider.refresh_from_db()
        self.assertFalse(rider.is_active)
        seat = self.train.coaches.first().seats.first()
        self.client.post(reverse("adminpanel:seat_toggle", args=[seat.pk]))
        seat.refresh_from_db()
        self.assertFalse(seat.is_active)

    def test_non_admin_cannot_post(self):
        self.client.force_login(make_user("sneaky"))
        r = self.client.post(reverse("adminpanel:train_delete", args=[self.train.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Train.objects.filter(pk=self.train.pk).exists())


class DemoDataTests(TestCase):
    def test_seed_light_stages_the_demo_and_scenario_runs(self):
        call_command("seed_demo", "--light", stdout=io.StringIO())
        train = Train.objects.get(number="24051")
        today = timezone.localdate()
        idx = {s.station.code: s.sequence for s in train.get_stops()}
        self.assertEqual(class_availability(train, today, idx["CNB"], idx["LKO"])["SL"]["available"], 0)
        self.assertEqual(class_availability(train, today, idx["LKO"], idx["BSB"])["SL"]["available"], 0)
        self.assertEqual(class_availability(train, today, idx["NDLS"], idx["CNB"])["SL"]["available"], 50)
        for username in ["admin", "tt_demo", "passenger", "passenger2", "passenger3"]:
            self.assertTrue(User.objects.filter(username=username).exists())

        before = Booking.objects.count()
        out = io.StringIO()
        call_command("run_demo_scenario", stdout=out)
        text = out.getvalue()
        self.assertIn("CNB→BSB rejected", text)
        self.assertNotIn("should never happen", text)
        self.assertEqual(Booking.objects.count(), before)  # dry run rolled back
        call_command("run_demo_scenario", "--commit", stdout=io.StringIO())
        self.assertEqual(Booking.objects.count(), before + 2)
