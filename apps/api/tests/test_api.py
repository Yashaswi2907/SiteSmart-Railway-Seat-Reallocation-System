"""REST API: search, booking flow, TT verification, simulation and authorisation."""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.bookings.models import Booking, SeatAllocation
from apps.bookings.services.pnr import sign_ticket
from apps.core.testing import make_route_train, make_user, next_run_date, pax

A, B, C, D, E = range(5)


class ApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.train = make_route_train(seats=4)
        cls.passenger = make_user("pia")
        cls.other = make_user("omar")
        cls.tt = make_user("ttapi", role=User.Role.TT)
        cls.tt.tt_profile.assigned_trains.add(cls.train)
        cls.stranger_tt = make_user("ttfar", role=User.Role.TT)
        cls.admin = make_user("root", role=User.Role.ADMIN)
        cls.seats = list(cls.train.coaches.get().seats.order_by("seat_number"))

    def setUp(self):
        self.date = next_run_date(self.train).isoformat()

    def create(self, user, s, d, seats=None, n=1, expect=201):
        self.client.force_login(user)
        codes = ["TA", "TB", "TC", "TD", "TE"]
        payload = {
            "train_id": self.train.pk, "journey_date": self.date, "from_code": codes[s], "to_code": codes[d],
            "coach_class": "SL", "passengers": [pax(f"Person {chr(65 + i)}") for i in range(n)],
        }
        if seats:
            payload["seat_ids"] = [x.id for x in seats]
        r = self.client.post(reverse("api:bookings"), payload, content_type="application/json")
        self.assertEqual(r.status_code, expect, r.content)
        return r.json()

    def run_url(self, name):
        return reverse(f"api:{name}", args=[self.train.pk, self.date])


class PublicApiTests(ApiTestCase):
    def test_station_lookup_and_search(self):
        r = self.client.get(reverse("api:stations"), {"q": "TB"})
        self.assertEqual(r.json()["results"][0]["code"], "TB")
        r = self.client.get(reverse("api:train_search"), {"from": "TB", "to": "TD", "date": self.date})
        data = r.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["classes"][0]["available"], 4)
        self.assertEqual(data["results"][0]["from"]["code"], "TB")

    def test_search_validation_and_wrong_direction(self):
        r = self.client.get(reverse("api:train_search"), {"from": "TB", "to": "TB", "date": self.date})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "validation_error")
        r = self.client.get(reverse("api:train_search"), {"from": "TD", "to": "TB", "date": self.date})
        self.assertEqual(r.json()["count"], 0)

    def test_pnr_status_hides_names(self):
        pnr = self.create(self.passenger, A, C)["pnr"]
        self.client.logout()
        r = self.client.get(reverse("api:pnr_status", args=[pnr]))
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Person", r.content.decode())

    def test_ticket_signature_verification(self):
        pnr = self.create(self.passenger, A, C)["pnr"]
        self.client.logout()
        ok = self.client.get(reverse("bookings:verify_ticket", args=[pnr, sign_ticket(pnr)]))
        self.assertContains(ok, "Genuine SiteSmart ticket")
        bad = self.client.get(reverse("bookings:verify_ticket", args=[pnr, "forged-signature"]))
        self.assertContains(bad, "could not be verified")


class BookingApiTests(ApiTestCase):
    def test_booking_flow_creates_pnr_and_allocations(self):
        self.client.force_login(self.passenger)
        coaches = self.client.get(reverse("api:coaches", args=[self.train.pk]),
                                  {"from": "TB", "to": "TD", "date": self.date, "class": "SL"}).json()
        coach_id = coaches["coaches"][0]["id"]
        seat_map = self.client.get(reverse("api:seat_map", args=[self.train.pk]),
                                   {"from": "TB", "to": "TD", "date": self.date, "coach": coach_id}).json()
        self.assertEqual(seat_map["counts"]["available"], 4)
        data = self.create(self.passenger, B, D, seats=[self.seats[0], self.seats[1]], n=2)
        self.assertRegex(data["pnr"], r"^\d{10}$")
        booking = Booking.objects.get(pnr=data["pnr"])
        self.assertEqual(SeatAllocation.objects.filter(passenger__booking=booking).count(), 4)
        seat_map = self.client.get(reverse("api:seat_map", args=[self.train.pk]),
                                   {"from": "TA", "to": "TE", "date": self.date, "coach": coach_id}).json()
        booked = [s for s in seat_map["seats"] if s["state"] == "booked"]
        self.assertEqual(booked[0]["occupied_on"], ["TB→TC", "TC→TD"])

    def test_overlap_rejected_with_409(self):
        self.create(self.passenger, B, D, seats=[self.seats[0]])
        data = self.create(self.other, C, E, seats=[self.seats[0]], expect=409)
        self.assertEqual(data["error"]["code"], "seat_unavailable")
        self.create(self.other, D, E, seats=[self.seats[0]])  # touching segment is fine

    def test_suggest_seats_and_invalid_passenger(self):
        self.client.force_login(self.passenger)
        r = self.client.get(reverse("api:suggest_seats", args=[self.train.pk]),
                            {"from": "TA", "to": "TB", "date": self.date, "class": "SL", "count": 2})
        self.assertEqual(len(r.json()["seats"]), 2)
        r = self.client.post(reverse("api:bookings"), {
            "train_id": self.train.pk, "journey_date": self.date, "from_code": "TA", "to_code": "TB",
            "coach_class": "SL", "passengers": [{"name": "X", "age": 200, "gender": "Q"}],
        }, content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_only_passengers_can_book_and_anonymous_is_refused(self):
        self.client.logout()
        r = self.client.post(reverse("api:bookings"), {}, content_type="application/json")
        self.assertIn(r.status_code, (401, 403))
        self.create(self.tt, A, B, expect=403)

    def test_csrf_required_for_session_api_writes(self):
        client = self.client_class(enforce_csrf_checks=True)
        client.force_login(self.passenger)
        r = client.post(reverse("api:bookings"), {}, content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_cancel_own_booking_only(self):
        pnr = self.create(self.passenger, A, E, seats=[self.seats[0]])["pnr"]
        self.client.force_login(self.other)
        r = self.client.post(reverse("api:booking_cancel", args=[pnr]), {}, content_type="application/json")
        self.assertEqual(r.status_code, 404)
        self.client.force_login(self.passenger)
        r = self.client.post(reverse("api:booking_cancel", args=[pnr]), {"reason": "test"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["segments_released"], 4)
        self.create(self.other, B, C, seats=[self.seats[0]])


class TTApiTests(ApiTestCase):
    def control(self, user, action, expect=200):
        self.client.force_login(user)
        r = self.client.post(self.run_url("run_control"), {"action": action}, content_type="application/json")
        self.assertEqual(r.status_code, expect, r.content)
        return r.json()

    def test_full_no_show_reallocation_through_api(self):
        booking = self.create(self.passenger, A, E, seats=[self.seats[0]])
        sim = self.control(self.tt, "start")["simulation"]
        self.assertEqual(sim["current_code"], "TA")
        passengers = self.client.get(self.run_url("run_passengers")).json()["results"]
        target = next(p for p in passengers if p["pnr"] == booking["pnr"])
        self.assertTrue(target["can_verify"])
        r = self.client.post(reverse("api:verify_passenger", args=[target["id"]]), {"status": "NOT_BOARDED"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["released_segments"], [0, 1, 2, 3])
        released = self.client.get(self.run_url("run_released")).json()
        self.assertEqual(released["count"], 1)
        # Reallocate: B->C then C->D on the released seat.
        self.create(self.other, B, C, seats=[self.seats[0]])
        self.create(self.passenger, C, D, seats=[self.seats[0]])
        self.create(self.other, B, D, seats=[self.seats[0]], expect=409)
        self.client.force_login(self.tt)
        occ = self.client.get(self.run_url("run_occupancy"), {"segment": 1}).json()
        self.assertEqual(occ["seats"][0]["state"], "reserved-realloc")
        stats = self.client.get(self.run_url("run_console")).json()["stats"]
        self.assertEqual(stats["not_boarded"], 1)
        self.assertEqual(stats["released_seats"], 1)

    def test_boarded_cannot_be_released_via_api(self):
        booking = self.create(self.passenger, A, E, seats=[self.seats[0]])
        self.control(self.tt, "start")
        pid = Booking.objects.get(pnr=booking["pnr"]).passengers.get().pk
        url = reverse("api:verify_passenger", args=[pid])
        self.assertEqual(self.client.post(url, {"status": "BOARDED"}, content_type="application/json").status_code, 200)
        r = self.client.post(url, {"status": "NOT_BOARDED"}, content_type="application/json")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["error"]["code"], "boarding_not_allowed")

    def test_unauthorised_tt_actions_refused(self):
        booking = self.create(self.passenger, A, E)
        pid = Booking.objects.get(pnr=booking["pnr"]).passengers.get().pk
        self.control(self.stranger_tt, "start", expect=403)
        self.control(self.passenger, "start", expect=403)
        self.control(self.tt, "start")
        self.client.force_login(self.stranger_tt)
        r = self.client.post(reverse("api:verify_passenger", args=[pid]), {"status": "NOT_BOARDED"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 403)
        self.client.force_login(self.passenger)
        r = self.client.post(reverse("api:verify_passenger", args=[pid]), {"status": "NOT_BOARDED"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get(self.run_url("run_passengers")).status_code, 403)

    def test_train_movement_closes_segments_for_booking(self):
        self.control(self.tt, "start")
        self.control(self.tt, "next_station")   # at B
        self.control(self.tt, "step")           # departed B
        data = self.create(self.passenger, B, D, expect=409)
        self.assertEqual(data["error"]["code"], "segment_departed")
        self.create(self.passenger, C, D)
        r = self.client.get(reverse("api:train_search"), {"from": "TA", "to": "TC", "date": self.date})
        self.assertTrue(r.json()["results"][0]["departed"])
        self.control(self.tt, "pause")
        self.control(self.tt, "step", expect=409)
        self.control(self.tt, "resume")
        self.control(self.tt, "auto_on")

    def test_admin_endpoints(self):
        self.create(self.passenger, B, D, seats=[self.seats[0]])
        self.client.force_login(self.admin)
        r = self.client.get(reverse("api:allocation_check"), {
            "train": self.train.pk, "date": self.date, "seat": self.seats[0].pk, "from": "TC", "to": "TE"})
        self.assertFalse(r.json()["bookable"])
        self.assertEqual(r.json()["conflicts"][0]["segment_index"], 2)
        r = self.client.get(reverse("api:allocation_check"), {
            "train": self.train.pk, "date": self.date, "seat": self.seats[0].pk, "from": "TD", "to": "TE"})
        self.assertTrue(r.json()["bookable"])
        self.assertEqual(self.client.get(reverse("api:seat_matrix"), {"train": self.train.pk, "date": self.date}).status_code, 200)
        self.assertEqual(self.client.get(reverse("api:admin_stats")).status_code, 200)
        self.client.force_login(self.tt)
        self.assertEqual(self.client.get(reverse("api:admin_stats")).status_code, 403)
