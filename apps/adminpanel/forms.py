from django import forms
from django.contrib.auth.password_validation import validate_password

from apps.accounts.models import TTProfile, User
from apps.core.forms import BootstrapFormMixin
from apps.railway.constants import CLASS_LAYOUTS, BerthType
from apps.railway.models import WEEKDAY_LABELS, Coach, Seat, Station, Train, TrainStop


class RunningDaysField(forms.MultipleChoiceField):
    """Seven weekday checkboxes <-> the ``running_days`` 0/1 string."""

    def __init__(self, **kwargs):
        super().__init__(choices=[(str(i), d) for i, d in enumerate(WEEKDAY_LABELS)],
                         widget=forms.CheckboxSelectMultiple, **kwargs)

    def prepare_value(self, value):
        if isinstance(value, str) and len(value) == 7 and set(value) <= {"0", "1"}:
            return [str(i) for i, f in enumerate(value) if f == "1"]
        return value

    def clean(self, value):
        days = super().clean(value)
        return "".join("1" if str(i) in days else "0" for i in range(7))


class TrainForm(BootstrapFormMixin, forms.ModelForm):
    running_days = RunningDaysField(label="Runs on", help_text="Pick at least one day.")

    class Meta:
        model = Train
        fields = ("number", "name", "train_type", "running_days", "description", "is_active")
        widgets = {"number": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": 5, "placeholder": "e.g. 24051"})}

    def clean_running_days(self):
        days = self.cleaned_data["running_days"]
        if "1" not in days:
            raise forms.ValidationError("A train must run on at least one day.")
        return days


class StationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Station
        fields = ("code", "name", "city", "state", "zone", "is_active")
        widgets = {"code": forms.TextInput(attrs={"style": "text-transform:uppercase", "placeholder": "e.g. NDLS"})}

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class TrainStopForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = TrainStop
        fields = ("station", "arrival_time", "departure_time", "day_offset", "distance_km", "platform")
        widgets = {"arrival_time": forms.TimeInput(attrs={"type": "time"}),
                   "departure_time": forms.TimeInput(attrs={"type": "time"})}

    def __init__(self, *args, route=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.route = route
        self.fields["station"].queryset = Station.objects.filter(is_active=True).order_by("name")

    def clean_station(self):
        station = self.cleaned_data["station"]
        if self.route and self.route.stops.filter(station=station).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This station is already on the route.")
        return station

    def clean(self):
        data = super().clean()
        if not data.get("arrival_time") and not data.get("departure_time"):
            raise forms.ValidationError("Enter an arrival or a departure time (origin has only departure, terminus only arrival).")
        return data


class CoachForm(BootstrapFormMixin, forms.ModelForm):
    seat_count = forms.IntegerField(
        min_value=1, max_value=120, required=False,
        help_text="Seats to generate with the standard berth layout. Leave empty for the class default.",
    )

    class Meta:
        model = Coach
        fields = ("coach_number", "coach_class", "position", "is_active")
        widgets = {"coach_number": forms.TextInput(attrs={"style": "text-transform:uppercase", "placeholder": "S3"})}

    def __init__(self, *args, train=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.train = train
        if self.instance.pk:
            self.fields.pop("seat_count")
            self.fields["coach_class"].disabled = True
            self.fields["coach_class"].help_text = "Class cannot change once seats exist."
        else:
            defaults = ", ".join(f"{c}: {v['seats']}" for c, v in CLASS_LAYOUTS.items())
            self.fields["seat_count"].help_text += f" Defaults — {defaults}."

    def clean_coach_number(self):
        number = self.cleaned_data["coach_number"].strip().upper()
        train = self.train or self.instance.train
        if Coach.objects.filter(train=train, coach_number=number).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This coach number already exists on the train.")
        return number


class SeatForm(BootstrapFormMixin, forms.ModelForm):
    berth_type = forms.ChoiceField(choices=BerthType.choices)

    class Meta:
        model = Seat
        fields = ("seat_number", "berth_type", "is_active")

    def __init__(self, *args, coach=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.coach = coach

    def clean_seat_number(self):
        n = self.cleaned_data["seat_number"]
        coach = self.coach or self.instance.coach
        if Seat.objects.filter(coach=coach, seat_number=n).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("That seat number already exists in this coach.")
        return n


class StaffForm(BootstrapFormMixin, forms.ModelForm):
    """Create or edit a TT/TTE account together with its profile and train assignments."""

    employee_id = forms.CharField(max_length=12, help_text="Uppercase letters, digits or hyphens, e.g. TTE-1042.")
    designation = forms.ChoiceField(choices=TTProfile.Designation.choices)
    division = forms.CharField(max_length=80, required=False)
    assigned_trains = forms.ModelMultipleChoiceField(
        queryset=Train.objects.filter(is_active=True).order_by("number"), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    is_on_duty = forms.BooleanField(required=False, initial=True, label="On duty")
    password = forms.CharField(widget=forms.PasswordInput(render_value=False), required=False,
                               help_text="Required for new accounts. Leave blank to keep the current password.")

    class Meta:
        model = User
        fields = ("first_name", "last_name", "username", "email", "phone", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profile = getattr(self.instance, "tt_profile", None) if self.instance.pk else None
        if profile:
            self.fields["employee_id"].initial = profile.employee_id
            self.fields["designation"].initial = profile.designation
            self.fields["division"].initial = profile.division
            self.fields["assigned_trains"].initial = list(profile.assigned_trains.all())
            self.fields["is_on_duty"].initial = profile.is_on_duty
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True

    def clean_employee_id(self):
        emp = self.cleaned_data["employee_id"].strip().upper()
        qs = TTProfile.objects.filter(employee_id=emp)
        if self.instance.pk:
            qs = qs.exclude(user=self.instance)
        if qs.exists():
            raise forms.ValidationError("Another TT already uses this employee ID.")
        return emp

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another account already uses this e-mail.")
        return email

    def clean_password(self):
        pw = self.cleaned_data.get("password")
        if not self.instance.pk and not pw:
            raise forms.ValidationError("Set an initial password for the new account.")
        if pw:
            validate_password(pw, self.instance if self.instance.pk else None)
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.TT
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        user.save()
        profile, _ = TTProfile.objects.get_or_create(user=user, defaults={"employee_id": self.cleaned_data["employee_id"]})
        profile.employee_id = self.cleaned_data["employee_id"]
        profile.designation = self.cleaned_data["designation"]
        profile.division = self.cleaned_data["division"]
        profile.is_on_duty = self.cleaned_data["is_on_duty"]
        profile.save()
        profile.assigned_trains.set(self.cleaned_data["assigned_trains"])
        return user
