"""QR codes and PDF e-tickets (simulated, for academic verification only)."""
from __future__ import annotations

import io

import qrcode
from django.urls import reverse
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from apps.bookings.models import Booking
from apps.railway.constants import class_label

from .pnr import sign_ticket

NAVY = colors.HexColor("#0B1F3A")
BLUE = colors.HexColor("#1F5FBF")
INK = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#5B6B82")
LINE = colors.HexColor("#DCE3EC")
SOFT = colors.HexColor("#F3F6FA")
GREEN = colors.HexColor("#15803D")
RED = colors.HexColor("#B91C1C")
AMBER = colors.HexColor("#B45309")


def ticket_verify_path(booking: Booking) -> str:
    return reverse("bookings:verify_ticket", args=[booking.pnr, sign_ticket(booking.pnr)])


def ticket_qr_payload(booking: Booking, request=None) -> str:
    path = ticket_verify_path(booking)
    return request.build_absolute_uri(path) if request is not None else path


def qr_png_bytes(data: str, box_size: int = 8) -> bytes:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box_size, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0B1F3A", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fmt_time(stop) -> str:
    t = stop.departure_time or stop.arrival_time
    return t.strftime("%H:%M") if t else "--:--"


def render_ticket_pdf(booking: Booking, request=None) -> bytes:
    """Draw a railway-style electronic reservation slip with an embedded QR code."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"E-Ticket PNR {booking.pnr}")
    c.setAuthor("SiteSmart Rail (academic simulation)")
    W, H = A4
    M = 16 * mm
    train = booking.train
    src, dst = booking.from_stop, booking.to_stop

    # Header band -----------------------------------------------------------
    c.setFillColor(NAVY)
    c.rect(0, H - 34 * mm, W, 34 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.roundRect(M, H - 24 * mm, 11 * mm, 11 * mm, 2.5 * mm, stroke=0, fill=1)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(M + 5.5 * mm, H - 20 * mm, "SS")
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(M + 15 * mm, H - 17.5 * mm, "SiteSmart Rail")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(colors.HexColor("#B9C7DD"))
    c.drawString(M + 15 * mm, H - 22.5 * mm, "Electronic Reservation Slip  ·  Academic simulation — not valid for travel")
    c.setFillColor(colors.HexColor("#B9C7DD"))
    c.setFont("Helvetica", 8)
    c.drawRightString(W - M, H - 14 * mm, "PNR NUMBER")
    c.setFillColor(colors.white)
    c.setFont("Courier-Bold", 20)
    c.drawRightString(W - M, H - 22 * mm, booking.pnr)

    # Status chip -----------------------------------------------------------
    y = H - 46 * mm
    status_text = "CANCELLED" if booking.is_cancelled else "CONFIRMED"
    chip = RED if booking.is_cancelled else GREEN
    c.setFillColor(chip)
    c.roundRect(M, y, 30 * mm, 7 * mm, 3.5 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(M + 15 * mm, y + 2.3 * mm, status_text)
    if booking.is_reallocated:
        c.setFillColor(BLUE)
        c.roundRect(M + 33 * mm, y, 40 * mm, 7 * mm, 3.5 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.drawCentredString(M + 53 * mm, y + 2.3 * mm, "REALLOCATED SEAT")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    booked = timezone.localtime(booking.created_at)
    c.drawRightString(W - M, y + 2.3 * mm, f"Booked on {booked:%d %b %Y, %H:%M} IST")

    # Train & journey card -------------------------------------------------------
    top = y - 6 * mm
    card_h = 52 * mm
    c.setStrokeColor(LINE)
    c.setFillColor(SOFT)
    c.roundRect(M, top - card_h, W - 2 * M, card_h, 3 * mm, stroke=1, fill=1)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(M + 6 * mm, top - 9 * mm, f"{train.number}  {train.name}")
    c.setFont("Helvetica", 8.5)
    c.setFillColor(MUTED)
    c.drawString(M + 6 * mm, top - 14 * mm,
                 f"{class_label(booking.coach_class)}  ·  General quota  ·  "
                 f"{max(dst.distance_km - src.distance_km, 0)} km")

    col1, col3 = M + 6 * mm, W - M - 62 * mm
    for x, stop, label, align in ((col1, src, "BOARDING", "l"), (col3, dst, "DESTINATION", "l")):
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7.5)
        c.drawString(x, top - 24 * mm, label)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 22)
        c.drawString(x, top - 33 * mm, stop.station.code)
        c.setFont("Helvetica", 9)
        c.drawString(x, top - 39 * mm, stop.station.name[:30])
        c.setFont("Helvetica-Bold", 10)
        day = f"  (+{stop.day_offset}d)" if stop.day_offset else ""
        c.drawString(x, top - 45 * mm, f"{_fmt_time(stop)}{day}")
    mid_x1, mid_x2 = M + 52 * mm, W - M - 68 * mm
    c.setStrokeColor(BLUE)
    c.setLineWidth(1.2)
    c.setDash(3, 2)
    c.line(mid_x1, top - 30 * mm, mid_x2, top - 30 * mm)
    c.setDash()
    c.setFillColor(BLUE)
    c.circle(mid_x1, top - 30 * mm, 1.4 * mm, stroke=0, fill=1)
    c.circle(mid_x2, top - 30 * mm, 1.4 * mm, stroke=0, fill=1)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    c.drawCentredString((mid_x1 + mid_x2) / 2, top - 26 * mm, f"Run date {booking.journey_date:%a, %d %b %Y}")

    # QR --------------------------------------------------------------------
    qr_size = 38 * mm
    qr_png = qr_png_bytes(ticket_qr_payload(booking, request))
    qr_y = top - card_h - 8 * mm - qr_size
    c.drawImage(ImageReader(io.BytesIO(qr_png)), W - M - qr_size, qr_y, qr_size, qr_size)
    c.setFont("Helvetica", 7)
    c.setFillColor(MUTED)
    c.drawCentredString(W - M - qr_size / 2, qr_y - 4 * mm, "Scan to verify (simulation)")

    # Passenger table ---------------------------------------------------------
    table_top = top - card_h - 8 * mm
    table_w = W - 2 * M - qr_size - 8 * mm
    headers = ["#", "Passenger", "Age", "Sex", "Coach", "Seat", "Berth", "Status", "Boarding"]
    widths = [0.05, 0.27, 0.07, 0.07, 0.09, 0.08, 0.09, 0.14, 0.14]
    xs = [M]
    for w in widths[:-1]:
        xs.append(xs[-1] + w * table_w)
    c.setFillColor(NAVY)
    c.rect(M, table_top - 7 * mm, table_w, 7 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 7.5)
    for x, h in zip(xs, headers):
        c.drawString(x + 1.5 * mm, table_top - 4.8 * mm, h)
    row_y = table_top - 7 * mm
    c.setFont("Helvetica", 8)
    for i, p in enumerate(booking.passengers.select_related("seat__coach", "boarding").all(), start=1):
        row_y -= 7 * mm
        if i % 2 == 0:
            c.setFillColor(SOFT)
            c.rect(M, row_y, table_w, 7 * mm, stroke=0, fill=1)
        boarding = getattr(p, "boarding", None)
        values = [
            str(i), p.name[:24], str(p.age), p.gender, p.seat.coach.coach_number, str(p.seat.seat_number),
            p.seat.berth_type, "CNF" if p.status == "CONFIRMED" else "CAN",
            boarding.get_status_display() if boarding else "Pending",
        ]
        for j, (x, v) in enumerate(zip(xs, values)):
            if j == 7:
                c.setFillColor(GREEN if v == "CNF" else RED)
            elif j == 8 and boarding and boarding.status == "NOT_BOARDED":
                c.setFillColor(AMBER)
            else:
                c.setFillColor(INK)
            c.drawString(x + 1.5 * mm, row_y + 2.4 * mm, v[:18] if j == 8 else v)
    c.setStrokeColor(LINE)
    c.line(M, row_y, M + table_w, row_y)

    # Fare summary --------------------------------------------------------------
    fy = min(row_y, qr_y) - 12 * mm
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(M, fy, "Fare summary (simulated)")
    c.setFont("Helvetica", 9)
    per = booking.passengers.first().fare if booking.passengers.exists() else 0
    lines = [
        ("Fare per passenger", f"Rs. {per:,.2f}"),
        ("Passengers", str(booking.passenger_count)),
        ("Total fare", f"Rs. {booking.total_fare:,.2f}"),
    ]
    cancellation = getattr(booking, "cancellation", None)
    if cancellation:
        lines += [("Cancellation charge", f"Rs. {cancellation.cancellation_charge:,.2f}"),
                  ("Refund (simulated)", f"Rs. {cancellation.refund_amount:,.2f}")]
    for k, (label, val) in enumerate(lines):
        yy = fy - (6 + k * 5.5) * mm
        c.setFillColor(MUTED)
        c.drawString(M, yy, label)
        c.setFillColor(INK)
        c.drawRightString(M + 85 * mm, yy, val)

    # Contact + notes ----------------------------------------------------------
    ny = fy - (12 + len(lines) * 5.5) * mm
    c.setStrokeColor(LINE)
    c.line(M, ny + 4 * mm, W - M, ny + 4 * mm)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(M, ny - 2 * mm, "Important")
    c.setFont("Helvetica", 7.8)
    c.setFillColor(MUTED)
    notes = [
        "This ticket was generated by an academic railway simulation project. It is not an official railway ticket.",
        "Carry a valid photo identity document during the (simulated) journey; the TT/TTE verifies boarding.",
        "If you do not board at your boarding station, the TT may mark you as 'Did not board' and your seat",
        "will be released to passengers boarding at upcoming stations. Released segments are not refunded.",
        f"Contact on booking: {booking.contact_email}" + (f"  ·  {booking.contact_phone}" if booking.contact_phone else ""),
    ]
    for k, line in enumerate(notes):
        c.drawString(M, ny - (7 + k * 4.4) * mm, line)

    c.setFont("Helvetica", 7)
    c.setFillColor(MUTED)
    c.drawString(M, 10 * mm, "SiteSmart Railway Vacant Seat Reallocation System — Full Stack Development Lab project")
    c.drawRightString(W - M, 10 * mm, f"Generated {timezone.localtime():%d %b %Y %H:%M}")
    c.showPage()
    c.save()
    return buf.getvalue()
