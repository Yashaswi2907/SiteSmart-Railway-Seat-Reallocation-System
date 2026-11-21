"""Simulated fare and refund calculation (academic approximation)."""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from apps.railway.constants import FARE_PER_KM, MINIMUM_FARE, RESERVATION_CHARGE

GST_RATE = Decimal("0.05")
AC_CLASSES = {"1A", "2A", "3A", "CC"}
FLAT_CLERKAGE = {"1A": Decimal("240"), "2A": Decimal("200"), "3A": Decimal("180"),
                 "CC": Decimal("180"), "SL": Decimal("120"), "2S": Decimal("60")}


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def calculate_fare(coach_class: str, distance_km: int) -> Decimal:
    """Fare for one passenger: distance x class rate + reservation charge (+5% GST on AC)."""
    base = max(FARE_PER_KM[coach_class] * Decimal(distance_km), MINIMUM_FARE[coach_class])
    fare = base + RESERVATION_CHARGE[coach_class]
    if coach_class in AC_CLASSES:
        fare += base * GST_RATE
    return _money(fare)


def refund_terms(coach_class: str, total_fare: Decimal, passengers: int, journey_date: dt.date,
                 today: dt.date) -> tuple[Decimal, Decimal]:
    """Return ``(cancellation_charge, refund_amount)`` for a simulated cancellation.

    * 2+ days before the run date: flat clerkage per passenger.
    * 1 day before: 25% of the fare.
    * Same day (before the train leaves the boarding station): 50% of the fare.
    """
    days_left = (journey_date - today).days
    if days_left >= 2:
        charge = FLAT_CLERKAGE[coach_class] * passengers
    elif days_left == 1:
        charge = total_fare * Decimal("0.25")
    else:
        charge = total_fare * Decimal("0.50")
    charge = min(_money(charge), total_fare)
    return charge, _money(total_fare - charge)
