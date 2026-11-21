"""Travel classes, berth layouts and the simulated fare table."""
from decimal import Decimal

from django.db import models


class TravelClass(models.TextChoices):
    FIRST_AC = "1A", "AC First Class (1A)"
    SECOND_AC = "2A", "AC 2 Tier (2A)"
    THIRD_AC = "3A", "AC 3 Tier (3A)"
    SLEEPER = "SL", "Sleeper (SL)"
    CHAIR_CAR = "CC", "AC Chair Car (CC)"
    SECOND_SITTING = "2S", "Second Sitting (2S)"


class BerthType(models.TextChoices):
    LOWER = "LB", "Lower"
    MIDDLE = "MB", "Middle"
    UPPER = "UB", "Upper"
    SIDE_LOWER = "SL", "Side lower"
    SIDE_UPPER = "SU", "Side upper"
    WINDOW = "WS", "Window"
    MIDDLE_SEAT = "MS", "Middle seat"
    AISLE = "AS", "Aisle"


# Repeating berth pattern per "bay" (compartment) and default seats per coach.
CLASS_LAYOUTS: dict[str, dict] = {
    "1A": {"pattern": ["LB", "UB", "LB", "UB"], "seats": 24, "prefix": "H", "kind": "berth"},
    "2A": {"pattern": ["LB", "UB", "LB", "UB", "SL", "SU"], "seats": 48, "prefix": "A", "kind": "berth"},
    "3A": {"pattern": ["LB", "MB", "UB", "LB", "MB", "UB", "SL", "SU"], "seats": 64, "prefix": "B", "kind": "berth"},
    "SL": {"pattern": ["LB", "MB", "UB", "LB", "MB", "UB", "SL", "SU"], "seats": 72, "prefix": "S", "kind": "berth"},
    "CC": {"pattern": ["WS", "MS", "AS", "AS", "WS"], "seats": 75, "prefix": "C", "kind": "seat"},
    "2S": {"pattern": ["WS", "MS", "AS", "AS", "MS", "WS"], "seats": 90, "prefix": "D", "kind": "seat"},
}

# Simulated fare table (academic approximation, not official tariffs).
FARE_PER_KM: dict[str, Decimal] = {
    "1A": Decimal("3.90"),
    "2A": Decimal("2.30"),
    "3A": Decimal("1.65"),
    "SL": Decimal("0.62"),
    "CC": Decimal("1.30"),
    "2S": Decimal("0.38"),
}
RESERVATION_CHARGE: dict[str, Decimal] = {
    "1A": Decimal("60"), "2A": Decimal("50"), "3A": Decimal("40"),
    "SL": Decimal("20"), "CC": Decimal("40"), "2S": Decimal("15"),
}
MINIMUM_FARE: dict[str, Decimal] = {
    "1A": Decimal("850"), "2A": Decimal("520"), "3A": Decimal("390"),
    "SL": Decimal("150"), "CC": Decimal("260"), "2S": Decimal("70"),
}
CLASS_ORDER = ["1A", "2A", "3A", "CC", "SL", "2S"]


def berth_for(coach_class: str, seat_number: int) -> str:
    pattern = CLASS_LAYOUTS[coach_class]["pattern"]
    return pattern[(seat_number - 1) % len(pattern)]


def class_label(code: str) -> str:
    return dict(TravelClass.choices).get(code, code)
