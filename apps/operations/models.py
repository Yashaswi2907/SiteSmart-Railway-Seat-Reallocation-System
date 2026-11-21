"""Train-movement simulation state and the system activity log."""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class TrainSimulation(TimeStampedModel):
    """Simulated position of one train run (train + run date).

    State machine::

        SCHEDULED --start--> AT_STATION(0) --depart--> IN_TRANSIT(0) --arrive--> AT_STATION(1) ...
                                                     ... AT_STATION(last) --finish--> COMPLETED

    ``IN_TRANSIT(k)`` means the train has left stop ``k`` and is heading to ``k + 1``.
    """

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        AT_STATION = "AT_STATION", "At station"
        IN_TRANSIT = "IN_TRANSIT", "In transit"
        COMPLETED = "COMPLETED", "Journey completed"

    train = models.ForeignKey("railway.Train", on_delete=models.CASCADE, related_name="simulations")
    journey_date = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    current_index = models.PositiveSmallIntegerField(default=0)
    is_paused = models.BooleanField(default=False)
    auto_advance = models.BooleanField(default=False)
    step_interval_seconds = models.PositiveSmallIntegerField(default=20)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_moved_at = models.DateTimeField(null=True, blank=True)
    last_moved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-journey_date", "train__number"]
        constraints = [
            models.UniqueConstraint(fields=["train", "journey_date"], name="uniq_simulation_per_run"),
        ]

    def __str__(self) -> str:
        return f"{self.train.number} run on {self.journey_date:%d %b %Y} — {self.get_status_display()}"

    @property
    def is_running(self) -> bool:
        return self.status in (self.Status.AT_STATION, self.Status.IN_TRANSIT)

    def min_boardable_index(self, stop_count: int) -> int:
        """Smallest stop index a *new* journey may start from.

        * Scheduled: any stop (0).
        * Halted at stop k: passengers may still board at k.
        * In transit after k: the next boarding opportunity is k + 1.
        * Completed: nothing is bookable (returns ``stop_count``).
        """
        if self.status == self.Status.SCHEDULED:
            return 0
        if self.status == self.Status.AT_STATION:
            return self.current_index
        if self.status == self.Status.IN_TRANSIT:
            return self.current_index + 1
        return stop_count

    def has_reached(self, stop_index: int) -> bool:
        """True once the train has arrived at (or passed) ``stop_index``."""
        if self.status == self.Status.SCHEDULED:
            return False
        if self.status == self.Status.COMPLETED:
            return True
        return self.current_index >= stop_index

    def has_departed(self, stop_index: int) -> bool:
        """True once the train has left ``stop_index``."""
        if self.status == self.Status.SCHEDULED:
            return False
        if self.status == self.Status.COMPLETED:
            return True
        if self.status == self.Status.IN_TRANSIT:
            return self.current_index >= stop_index
        return self.current_index > stop_index


class ActivityLog(models.Model):
    class Category(models.TextChoices):
        AUTH = "AUTH", "Authentication"
        BOOKING = "BOOKING", "Booking"
        BOARDING = "BOARDING", "Boarding"
        REALLOCATION = "REALLOCATION", "Reallocation"
        SIMULATION = "SIMULATION", "Simulation"
        ADMIN = "ADMIN", "Administration"

    class Action(models.TextChoices):
        LOGIN = "LOGIN", "Signed in"
        LOGIN_FAILED = "LOGIN_FAILED", "Failed sign-in"
        LOGOUT = "LOGOUT", "Signed out"
        REGISTER = "REGISTER", "Registered"
        BOOKING_CREATED = "BOOKING_CREATED", "Booking created"
        BOOKING_CANCELLED = "BOOKING_CANCELLED", "Booking cancelled"
        PASSENGER_BOARDED = "PASSENGER_BOARDED", "Passenger boarded"
        PASSENGER_NO_SHOW = "PASSENGER_NO_SHOW", "Passenger did not board"
        SEATS_RELEASED = "SEATS_RELEASED", "Seat segments released"
        SEAT_REALLOCATED = "SEAT_REALLOCATED", "Released seat rebooked"
        SIM_STARTED = "SIM_STARTED", "Simulation started"
        SIM_PAUSED = "SIM_PAUSED", "Simulation paused"
        SIM_RESUMED = "SIM_RESUMED", "Simulation resumed"
        TRAIN_DEPARTED = "TRAIN_DEPARTED", "Train departed"
        TRAIN_ARRIVED = "TRAIN_ARRIVED", "Train arrived"
        SIM_COMPLETED = "SIM_COMPLETED", "Journey completed"
        ADMIN_CHANGE = "ADMIN_CHANGE", "Administrative change"

    CATEGORY_FOR_ACTION = {
        "LOGIN": "AUTH", "LOGIN_FAILED": "AUTH", "LOGOUT": "AUTH", "REGISTER": "AUTH",
        "BOOKING_CREATED": "BOOKING", "BOOKING_CANCELLED": "BOOKING",
        "PASSENGER_BOARDED": "BOARDING", "PASSENGER_NO_SHOW": "BOARDING",
        "SEATS_RELEASED": "REALLOCATION", "SEAT_REALLOCATED": "REALLOCATION",
        "SIM_STARTED": "SIMULATION", "SIM_PAUSED": "SIMULATION", "SIM_RESUMED": "SIMULATION",
        "TRAIN_DEPARTED": "SIMULATION", "TRAIN_ARRIVED": "SIMULATION", "SIM_COMPLETED": "SIMULATION",
        "ADMIN_CHANGE": "ADMIN",
    }

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="activities"
    )
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True)
    category = models.CharField(max_length=14, choices=Category.choices, db_index=True)
    description = models.CharField(max_length=300)
    train = models.ForeignKey("railway.Train", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    booking = models.ForeignKey(
        "bookings.Booking", null=True, blank=True, on_delete=models.SET_NULL, related_name="activities"
    )
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"[{self.created_at:%Y-%m-%d %H:%M}] {self.get_action_display()}: {self.description}"
