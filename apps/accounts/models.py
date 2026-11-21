"""User accounts, roles and role-specific profiles."""
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import TimeStampedModel

phone_validator = RegexValidator(
    regex=r"^[6-9]\d{9}$", message="Enter a valid 10-digit Indian mobile number."
)


class User(AbstractUser):
    """Custom user with a single role that drives permissions and navigation."""

    class Role(models.TextChoices):
        PASSENGER = "PASSENGER", "Passenger"
        TT = "TT", "TT / TTE"
        ADMIN = "ADMIN", "Administrator"

    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.PASSENGER, db_index=True)
    phone = models.CharField(max_length=10, blank=True, validators=[phone_validator])

    objects = UserManager()

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
        if self.role == self.Role.ADMIN:
            self.is_staff = True
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    # Role helpers -------------------------------------------------------
    @property
    def is_passenger(self) -> bool:
        return self.role == self.Role.PASSENGER

    @property
    def is_tt(self) -> bool:
        return self.role == self.Role.TT

    @property
    def is_portal_admin(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser

    @property
    def display_name(self) -> str:
        return self.get_full_name() or self.username

    @property
    def initials(self) -> str:
        parts = [p for p in [self.first_name, self.last_name] if p]
        if not parts:
            return self.username[:2].upper()
        return "".join(p[0] for p in parts[:2]).upper()

    def __str__(self) -> str:
        return f"{self.display_name} ({self.get_role_display()})"


class PassengerProfile(TimeStampedModel):
    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"

    class BerthPreference(models.TextChoices):
        NONE = "", "No preference"
        LOWER = "LB", "Lower"
        MIDDLE = "MB", "Middle"
        UPPER = "UB", "Upper"
        SIDE_LOWER = "SL", "Side lower"
        SIDE_UPPER = "SU", "Side upper"
        WINDOW = "WS", "Window"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="passenger_profile")
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True)
    preferred_class = models.CharField(max_length=3, blank=True)
    preferred_berth = models.CharField(max_length=2, choices=BerthPreference.choices, blank=True)

    class Meta:
        verbose_name = "passenger profile"

    def __str__(self) -> str:
        return f"Profile of {self.user.display_name}"


class TTProfile(TimeStampedModel):
    class Designation(models.TextChoices):
        TTE = "TTE", "Travelling Ticket Examiner"
        SR_TTE = "SR_TTE", "Senior TTE"
        CTI = "CTI", "Chief Ticket Inspector"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="tt_profile")
    employee_id = models.CharField(
        max_length=12,
        unique=True,
        validators=[RegexValidator(r"^[A-Z0-9-]{4,12}$", "Use 4-12 uppercase letters, digits or hyphens.")],
    )
    designation = models.CharField(max_length=10, choices=Designation.choices, default=Designation.TTE)
    division = models.CharField(max_length=80, blank=True, help_text="Railway division (fictional/demo).")
    assigned_trains = models.ManyToManyField("railway.Train", blank=True, related_name="assigned_tts")
    is_on_duty = models.BooleanField(default=True)

    class Meta:
        verbose_name = "TT/TTE profile"
        ordering = ["employee_id"]

    def __str__(self) -> str:
        return f"{self.employee_id} — {self.user.display_name}"
