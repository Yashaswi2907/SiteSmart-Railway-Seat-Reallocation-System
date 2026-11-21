"""Bookings, passengers, segment-level seat allocations and boarding verification.

Seat occupancy is stored per *segment*: a passenger travelling from stop 1 to
stop 4 owns three ``SeatAllocation`` rows (segments 1, 2 and 3). A partial
unique constraint guarantees that, for a given seat and journey date, at most one
ACTIVE row can exist per segment — so the database itself rejects any overlapping
allocation, even if application-level checks were bypassed.
"""
from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel
from apps.railway.constants import TravelClass


class Booking(TimeStampedModel):
    class Status(models.TextChoices):
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"

    pnr = models.CharField("PNR", max_length=10, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings")
    train = models.ForeignKey("railway.Train", on_delete=models.PROTECT, related_name="bookings")
    journey_date = models.DateField(db_index=True, help_text="Run date of the train (departure from origin).")
    from_stop = models.ForeignKey("railway.TrainStop", on_delete=models.PROTECT, related_name="+")
    to_stop = models.ForeignKey("railway.TrainStop", on_delete=models.PROTECT, related_name="+")
    from_index = models.PositiveSmallIntegerField()
    to_index = models.PositiveSmallIntegerField()
    coach_class = models.CharField(max_length=3, choices=TravelClass.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED, db_index=True)
    passenger_count = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(6)])
    total_fare = models.DecimalField(max_digits=10, decimal_places=2)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=10, blank=True)
    is_reallocated = models.BooleanField(
        default=False, help_text="At least one seat came from segments released by a no-show."
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["train", "journey_date"]),
            models.Index(fields=["user", "journey_date"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(from_index__lt=models.F("to_index")), name="booking_from_before_to"),
        ]

    def __str__(self) -> str:
        return f"PNR {self.pnr}"

    @property
    def is_cancelled(self) -> bool:
        return self.status == self.Status.CANCELLED

    @property
    def active_passengers(self):
        return self.passengers.filter(status=Passenger.Status.CONFIRMED)


class Passenger(TimeStampedModel):
    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"

    class Status(models.TextChoices):
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="passengers")
    name = models.CharField(max_length=80)
    age = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(120)])
    gender = models.CharField(max_length=1, choices=Gender.choices)
    berth_preference = models.CharField(max_length=2, blank=True)
    seat = models.ForeignKey("railway.Seat", on_delete=models.PROTECT, related_name="passengers")
    fare = models.DecimalField(max_digits=9, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED)
    is_reallocated_seat = models.BooleanField(default=False)

    class Meta:
        ordering = ["booking", "id"]
        indexes = [models.Index(fields=["seat", "status"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.booking.pnr})"


class BoardingStatus(TimeStampedModel):
    """TT verification state for one passenger (exactly one row per passenger)."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending verification"
        BOARDED = "BOARDED", "Boarded"
        NOT_BOARDED = "NOT_BOARDED", "Did not board"

    passenger = models.OneToOneField(Passenger, on_delete=models.CASCADE, related_name="boarding")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="verifications"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_at_stop = models.ForeignKey(
        "railway.TrainStop", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    remarks = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "boarding status"
        verbose_name_plural = "boarding statuses"

    def __str__(self) -> str:
        return f"{self.passenger.name}: {self.get_status_display()}"


class SeatAllocation(TimeStampedModel):
    """Occupancy of one seat for one route segment on one journey date."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        RELEASED = "RELEASED", "Released (no-show)"
        CANCELLED = "CANCELLED", "Cancelled"

    passenger = models.ForeignKey(Passenger, on_delete=models.CASCADE, related_name="allocations")
    seat = models.ForeignKey("railway.Seat", on_delete=models.PROTECT, related_name="allocations")
    journey_date = models.DateField()
    segment_index = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["seat", "journey_date", "segment_index"]
        constraints = [
            # THE double-booking guard: one ACTIVE occupant per seat, date and segment.
            models.UniqueConstraint(
                fields=["seat", "journey_date", "segment_index"],
                condition=Q(status="ACTIVE"),
                name="uniq_active_seat_segment",
            ),
        ]
        indexes = [
            models.Index(fields=["seat", "journey_date", "status"]),
            models.Index(fields=["journey_date", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.seat} seg {self.segment_index} on {self.journey_date} [{self.status}]"


class Cancellation(TimeStampedModel):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name="cancellation")
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="cancellations"
    )
    reason = models.CharField(max_length=255, blank=True)
    cancellation_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    segments_released = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Cancellation of {self.booking.pnr}"
