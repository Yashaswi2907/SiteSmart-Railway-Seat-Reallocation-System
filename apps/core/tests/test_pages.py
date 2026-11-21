"""Every HTML page renders for the right role, and is refused for the wrong one."""
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import Booking
from apps.railway.models import Coach, Train, TrainStop


class PageRenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", "--light", verbosity=0, stdout=open("/dev/null", "w"))
        cls.train = Train.objects.get(number="24051")
        cls.today = timezone.localdate().isoformat()
        cls.booking = Booking.objects.filter(train=cls.train).first()

    def login(self, username):
        self.client.force_login(User.objects.get(username=username))

    def assertPages(self, urls, status=200):
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status, f"{url} -> {response.status_code}")

    def test_public_pages(self):
        self.assertPages([
            reverse("core:home"),
            reverse("railway:search"),
            reverse("railway:search") + f"?from=CNB&to=LKO&date={self.today}&class=SL",
            reverse("railway:search") + f"?from=LKO&to=CNB&date={self.today}",
            reverse("railway:train_list"),
            reverse("railway:train_detail", args=["24051"]),
            reverse("bookings:pnr_status"),
            reverse("bookings:pnr_status") + f"?pnr={self.booking.pnr}",
            reverse("bookings:pnr_status") + "?pnr=123",
            reverse("accounts:login"),
            reverse("accounts:register"),
        ])
        self.assertPages(["/does-not-exist/"], status=404)

    def test_passenger_pages(self):
        self.login("passenger")
        self.assertPages([
            reverse("bookings:passenger_dashboard"),
            reverse("bookings:my_bookings"),
            reverse("bookings:my_bookings") + "?tab=all",
            reverse("accounts:profile"),
            reverse("bookings:book", args=[self.train.pk]) + f"?from=NDLS&to=CNB&date={self.today}&class=SL&passengers=2",
        ])

    def test_booking_owner_pages(self):
        self.client.force_login(self.booking.user)
        pnr = self.booking.pnr
        self.assertPages([
            reverse("bookings:booking_detail", args=[pnr]) + "?new=1",
            reverse("bookings:ticket", args=[pnr]),
            reverse("bookings:ticket_qr", args=[pnr]),
        ])
        pdf = self.client.get(reverse("bookings:ticket_pdf", args=[pnr]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))

    def test_other_passengers_cannot_see_booking(self):
        self.login("passenger3")
        self.assertPages([reverse("bookings:booking_detail", args=[self.booking.pnr]),
                          reverse("bookings:ticket_pdf", args=[self.booking.pnr])], status=404)

    def test_tt_pages(self):
        self.login("tt_demo")
        self.assertPages([
            reverse("operations:dashboard"),
            reverse("operations:run_console", args=[self.train.pk, self.today]),
            reverse("operations:lookup"),
            reverse("accounts:profile"),
        ])
        other = Train.objects.get(number="13511")  # not assigned to tt_demo
        self.assertPages([reverse("operations:run_console", args=[other.pk, self.today])], status=403)

    def test_admin_pages(self):
        self.login("admin")
        coach = Coach.objects.filter(train=self.train).first()
        stop = TrainStop.objects.filter(route__train=self.train).first()
        tt = User.objects.get(username="tt_demo")
        self.assertPages([reverse(f"adminpanel:{name}") for name in [
            "dashboard", "train_list", "train_create", "station_list", "station_create", "schedules", "simulation",
            "allocation", "released", "boarding", "booking_list", "cancellations", "passenger_list", "staff_list",
            "staff_create", "activity",
        ]] + [
            reverse("adminpanel:train_detail", args=[self.train.pk]),
            reverse("adminpanel:train_edit", args=[self.train.pk]),
            reverse("adminpanel:coach_seats", args=[coach.pk]),
            reverse("adminpanel:coach_edit", args=[coach.pk]),
            reverse("adminpanel:stop_edit", args=[stop.pk]),
            reverse("adminpanel:staff_edit", args=[tt.pk]),
            reverse("adminpanel:booking_list") + "?status=CONFIRMED&realloc=1",
            reverse("bookings:booking_detail", args=[self.booking.pnr]),
            reverse("operations:run_console", args=[self.train.pk, self.today]),
            reverse("admin:index"),
        ])

    def test_role_isolation(self):
        self.login("passenger")
        self.assertPages([reverse("adminpanel:dashboard"), reverse("operations:dashboard")], status=403)
        self.login("tt_demo")
        self.assertPages([reverse("adminpanel:dashboard"), reverse("bookings:passenger_dashboard")], status=403)
        self.client.logout()
        for url in [reverse("bookings:passenger_dashboard"), reverse("adminpanel:dashboard"), reverse("operations:dashboard")]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("accounts:login"), response["Location"])
