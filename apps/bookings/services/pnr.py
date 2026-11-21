"""PNR generation and signed ticket tokens."""
from __future__ import annotations

import secrets

from django.core import signing

TICKET_SALT = "sitesmart.ticket.v1"


def generate_pnr() -> str:
    """Return a new, unused 10-digit PNR (first digit 1-9)."""
    from apps.bookings.models import Booking

    for _ in range(25):
        pnr = str(secrets.randbelow(9) + 1) + "".join(str(secrets.randbelow(10)) for _ in range(9))
        if not Booking.objects.filter(pnr=pnr).exists():
            return pnr
    raise RuntimeError("Could not generate a unique PNR")  # pragma: no cover


def sign_ticket(pnr: str) -> str:
    """Tamper-evident token embedded in the ticket QR code."""
    return signing.Signer(salt=TICKET_SALT).sign(pnr).split(":", 1)[1]


def verify_ticket_signature(pnr: str, signature: str) -> bool:
    try:
        return signing.Signer(salt=TICKET_SALT).unsign(f"{pnr}:{signature}") == pnr
    except signing.BadSignature:
        return False
