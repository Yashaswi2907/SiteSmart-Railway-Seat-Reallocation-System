"""PDF tickets, signed QR tokens and the simulated fare/refund rules."""
import datetime as dt
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from apps.bookings.services.fares import calculate_fare, refund_terms
from apps.bookings.services.pnr import sign_ticket, verify_ticket_signature
from apps.bookings.services.reservation import reserve_seats
from apps.bookings.services.tickets import qr_png_bytes, render_ticket_pdf
from apps.core.testing import make_route_train, make_user, next_run_date, pax, stop


class TicketTests(TestCase):
    def test_pdf_ticket_contents(self):
        train = make_route_train(seats=2)
        booking = reserve_seats(user=make_user("tix"), train=train, journey_date=next_run_date(train),
                                from_stop=stop(train, 0), to_stop=stop(train, 3), coach_class="SL",
                                passengers=[pax("Kiran Das")])
        pdf = render_ticket_pdf(booking)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn(f"E-Ticket PNR {booking.pnr}".encode(), pdf)   # document title metadata
        self.assertIn(b"/Subtype /Image", pdf)                       # embedded QR code
        self.assertGreater(len(pdf), 3000)
        self.assertTrue(qr_png_bytes("x").startswith(b"\x89PNG"))


class FareAndSignatureTests(SimpleTestCase):
    def test_fares(self):
        self.assertEqual(calculate_fare("SL", 10), Decimal("170"))      # minimum fare + reservation
        self.assertGreater(calculate_fare("3A", 500), calculate_fare("SL", 500))
        self.assertGreater(calculate_fare("SL", 800), calculate_fare("SL", 400))

    def test_refund_tiers_and_signatures(self):
        today = dt.date(2026, 1, 10)
        charge, refund = refund_terms("SL", Decimal("1000"), 2, today + dt.timedelta(days=5), today)
        self.assertEqual((charge, refund), (Decimal("240"), Decimal("760")))
        self.assertEqual(refund_terms("SL", Decimal("1000"), 1, today + dt.timedelta(days=1), today)[1], Decimal("750"))
        self.assertEqual(refund_terms("SL", Decimal("1000"), 1, today, today)[1], Decimal("500"))
        sig = sign_ticket("1234567890")
        self.assertTrue(verify_ticket_signature("1234567890", sig))
        self.assertFalse(verify_ticket_signature("1234567891", sig))
