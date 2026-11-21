from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm

from apps.core.forms import BootstrapFormMixin
from apps.railway.constants import TravelClass

from .models import PassengerProfile, User


class LoginForm(BootstrapFormMixin, AuthenticationForm):
    username = forms.CharField(
        label="Username or e-mail",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username", "placeholder": "e.g. passenger"}),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "placeholder": "Your password"}),
    )
    error_messages = {
        "invalid_login": "That username/e-mail and password combination is not correct.",
        "inactive": "This account has been deactivated. Contact the administrator.",
    }


class RegistrationForm(BootstrapFormMixin, UserCreationForm):
    first_name = forms.CharField(max_length=60)
    last_name = forms.CharField(max_length=60)
    email = forms.EmailField()
    phone = forms.CharField(
        max_length=10, required=False, help_text="Optional. 10-digit mobile number.",
        widget=forms.TextInput(attrs={"inputmode": "numeric", "pattern": "[6-9][0-9]{9}"}),
    )
    accept_terms = forms.BooleanField(
        label="I understand this is an academic simulation and not an official railway service."
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name", "username", "email", "phone")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this e-mail already exists.")
        return email

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is taken.")
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.PASSENGER
        if commit:
            user.save()
        return user


class UserDetailsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "phone")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another account already uses this e-mail.")
        return email


class PassengerProfileForm(BootstrapFormMixin, forms.ModelForm):
    preferred_class = forms.ChoiceField(choices=[("", "No preference")] + list(TravelClass.choices), required=False)

    class Meta:
        model = PassengerProfile
        fields = ("date_of_birth", "gender", "preferred_class", "preferred_berth", "address", "city", "state")
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"})}


class StyledPasswordChangeForm(BootstrapFormMixin, PasswordChangeForm):
    pass
