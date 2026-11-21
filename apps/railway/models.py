"""Railway network inventory: stations, trains, routes, coaches and seats.

Every route is an ordered list of ``TrainStop`` rows with a 0-based ``sequence``.
The segment between stop ``i`` and stop ``i + 1`` is "segment i". A journey from
stop ``s`` to stop ``d`` therefore occupies the half-open segment range ``[s, d)``.
"""
from __future__ import annotations

import datetime as dt

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models

from apps.core.models import TimeStampedModel

from .constants import CLASS_LAYOUTS, BerthType, TravelClass, berth_for

WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class Station(TimeStampedModel):
    code = models.CharField(
        max_length=5,
        unique=True,
        validators=[RegexValidator(r"^[A-Z]{2,5}$", "Use 2-5 uppercase letters, e.g. NDLS.")],
    )
    name = models.CharField(max_length=100)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=80)
    zone = models.CharField(max_length=40, blank=True, help_text="Railway zone (demo data).")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["name"]), models.Index(fields=["city"])]

    def save(self, *args, **kwargs):
        self.code = (self.code or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class Train(TimeStampedModel):
    class TrainType(models.TextChoices):
        SUPERFAST = "SUPERFAST", "Superfast Express"
        EXPRESS = "EXPRESS", "Express"
        MAIL = "MAIL", "Mail"
        INTERCITY = "INTERCITY", "Intercity"
        PREMIUM = "PREMIUM", "Premium Chair Car"

    number = models.CharField(
        max_length=5, unique=True, validators=[RegexValidator(r"^\d{5}$", "Train number must be 5 digits.")]
    )
    name = models.CharField(max_length=100)
    train_type = models.CharField(max_length=12, choices=TrainType.choices, default=TrainType.EXPRESS)
    running_days = models.CharField(
        max_length=7,
        default="1111111",
        validators=[RegexValidator(r"^[01]{7}$", "Seven 0/1 flags, Monday first.")],
        help_text="Seven 0/1 flags for Mon..Sun, e.g. 1010100 = Mon, Wed, Fri.",
    )
    is_active = models.BooleanField(default=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["number"]

    def __str__(self) -> str:
        return f"{self.number} {self.name}"

    def clean(self):
        if self.running_days and "1" not in self.running_days:
            raise ValidationError({"running_days": "A train must run on at least one day."})

    # Schedule helpers ---------------------------------------------------
    def runs_on(self, date: dt.date) -> bool:
        return self.running_days[date.weekday()] == "1"

    @property
    def running_days_display(self) -> str:
        if self.running_days == "1111111":
            return "Daily"
        return ", ".join(day for flag, day in zip(self.running_days, WEEKDAY_LABELS) if flag == "1")

    @property
    def running_day_flags(self) -> list[tuple[str, bool]]:
        return [(day, flag == "1") for flag, day in zip(self.running_days, WEEKDAY_LABELS)]

    def get_stops(self):
        route = getattr(self, "route", None)
        if route is None:
            return TrainStop.objects.none()
        return route.stops.select_related("station").order_by("sequence")

    @property
    def source_stop(self):
        return self.get_stops().first()

    @property
    def destination_stop(self):
        return self.get_stops().last()

    def available_classes(self) -> list[str]:
        from .constants import CLASS_ORDER

        present = set(self.coaches.filter(is_active=True).values_list("coach_class", flat=True))
        return [c for c in CLASS_ORDER if c in present]


class TrainRoute(TimeStampedModel):
    """One route per train; the ordered stops live in ``TrainStop``."""

    train = models.OneToOneField(Train, on_delete=models.CASCADE, related_name="route")
    name = models.CharField(max_length=120, blank=True)

    class Meta:
        verbose_name = "train route"

    def __str__(self) -> str:
        return self.name or f"Route of {self.train}"

    @property
    def stop_count(self) -> int:
        return self.stops.count()

    @property
    def segment_count(self) -> int:
        return max(self.stop_count - 1, 0)

    def resequence(self):
        """Close gaps so sequences are exactly 0..n-1 (two passes avoid unique clashes)."""
        stops = list(self.stops.order_by("sequence", "id"))
        offset = 1000
        for i, stop in enumerate(stops):
            TrainStop.objects.filter(pk=stop.pk).update(sequence=offset + i)
        for i, stop in enumerate(stops):
            TrainStop.objects.filter(pk=stop.pk).update(sequence=i)


class TrainStop(TimeStampedModel):
    route = models.ForeignKey(TrainRoute, on_delete=models.CASCADE, related_name="stops")
    station = models.ForeignKey(Station, on_delete=models.PROTECT, related_name="stops")
    sequence = models.PositiveSmallIntegerField(help_text="0-based position of the stop on the route.")
    arrival_time = models.TimeField(null=True, blank=True, help_text="Empty for the origin station.")
    departure_time = models.TimeField(null=True, blank=True, help_text="Empty for the terminating station.")
    day_offset = models.PositiveSmallIntegerField(default=0, help_text="Days after the run date (0 = same day).")
    distance_km = models.PositiveIntegerField(default=0, help_text="Cumulative distance from origin.")
    platform = models.CharField(max_length=4, blank=True)

    class Meta:
        ordering = ["route", "sequence"]
        constraints = [
            models.UniqueConstraint(fields=["route", "sequence"], name="uniq_stop_sequence_per_route"),
            models.UniqueConstraint(fields=["route", "station"], name="uniq_station_per_route"),
        ]
        indexes = [models.Index(fields=["station", "route"])]

    def __str__(self) -> str:
        return f"{self.sequence}. {self.station.name}"

    @property
    def display_time(self):
        return self.departure_time or self.arrival_time

    @property
    def halt_minutes(self) -> int | None:
        if not (self.arrival_time and self.departure_time):
            return None
        a = dt.datetime.combine(dt.date.today(), self.arrival_time)
        d = dt.datetime.combine(dt.date.today(), self.departure_time)
        if d < a:
            d += dt.timedelta(days=1)
        return int((d - a).total_seconds() // 60)


class Coach(TimeStampedModel):
    train = models.ForeignKey(Train, on_delete=models.CASCADE, related_name="coaches")
    coach_number = models.CharField(
        max_length=4, validators=[RegexValidator(r"^[A-Z]{1,2}\d{1,2}$", "Format like S1, B2, A1, H1, C1.")]
    )
    coach_class = models.CharField(max_length=3, choices=TravelClass.choices)
    position = models.PositiveSmallIntegerField(default=1, help_text="Order of the coach in the rake.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["train", "position", "coach_number"]
        verbose_name_plural = "coaches"
        constraints = [
            models.UniqueConstraint(fields=["train", "coach_number"], name="uniq_coach_number_per_train"),
        ]
        indexes = [models.Index(fields=["train", "coach_class"])]

    def __str__(self) -> str:
        return f"{self.train.number} / {self.coach_number} ({self.coach_class})"

    @property
    def layout(self) -> dict:
        return CLASS_LAYOUTS[self.coach_class]

    def generate_seats(self, count: int | None = None) -> int:
        """Create the standard berth layout for this class. Returns seats created."""
        total = count or self.layout["seats"]
        existing = set(self.seats.values_list("seat_number", flat=True))
        new = [
            Seat(coach=self, seat_number=n, berth_type=berth_for(self.coach_class, n))
            for n in range(1, total + 1)
            if n not in existing
        ]
        Seat.objects.bulk_create(new)
        return len(new)


class Seat(TimeStampedModel):
    coach = models.ForeignKey(Coach, on_delete=models.CASCADE, related_name="seats")
    seat_number = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    berth_type = models.CharField(max_length=2, choices=BerthType.choices)
    is_active = models.BooleanField(default=True, help_text="Inactive seats are never offered for booking.")

    class Meta:
        ordering = ["coach", "seat_number"]
        constraints = [
            models.UniqueConstraint(fields=["coach", "seat_number"], name="uniq_seat_number_per_coach"),
        ]
        indexes = [models.Index(fields=["coach", "is_active"])]

    def __str__(self) -> str:
        return f"{self.coach.coach_number}-{self.seat_number} ({self.berth_type})"

    @property
    def label(self) -> str:
        return f"{self.coach.coach_number}/{self.seat_number}"
