import os

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from apps.operations.models import ActivityLog
from apps.operations.services.activity import log_activity

from .forms import LoginForm, PassengerProfileForm, RegistrationForm, StyledPasswordChangeForm, UserDetailsForm
from .models import PassengerProfile


class SignInView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Quick-fill buttons for the fictional demo accounts (development mode only).
        if settings.DEBUG:
            ctx["demo_password"] = os.getenv("DEMO_PASSWORD", "Demo@12345")
            ctx["demo_accounts"] = [
                ("Passenger", "passenger", "bi-person"),
                ("TT / TTE", "tt_demo", "bi-clipboard2-check"),
                ("Administrator", "admin", "bi-shield-lock"),
            ]
        return ctx


@require_POST
def sign_out(request):
    if request.user.is_authenticated:
        log_activity(ActivityLog.Action.LOGOUT, f"{request.user.display_name} signed out",
                     actor=request.user, request=request)
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("core:home")


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("core:post_login")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        log_activity(ActivityLog.Action.REGISTER, f"New passenger account {user.username}", actor=user, request=request)
        login(request, user, backend="apps.accounts.backends.EmailOrUsernameBackend")
        messages.success(request, f"Welcome aboard, {user.first_name}! Your account is ready.")
        return redirect(request.GET.get("next") or reverse("bookings:passenger_dashboard"))
    return render(request, "accounts/register.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    user = request.user
    profile_obj = PassengerProfile.objects.get_or_create(user=user)[0] if user.is_passenger else None
    details_form = UserDetailsForm(instance=user, prefix="u")
    profile_form = PassengerProfileForm(instance=profile_obj, prefix="p") if profile_obj else None
    password_form = StyledPasswordChangeForm(user, prefix="pw")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "details":
            details_form = UserDetailsForm(request.POST, instance=user, prefix="u")
            if profile_obj:
                profile_form = PassengerProfileForm(request.POST, instance=profile_obj, prefix="p")
            valid = details_form.is_valid() and (profile_form is None or profile_form.is_valid())
            if valid:
                details_form.save()
                if profile_form:
                    profile_form.save()
                messages.success(request, "Your profile has been updated.")
                return redirect("accounts:profile")
            messages.error(request, "Please correct the highlighted fields.")
        elif action == "password":
            password_form = StyledPasswordChangeForm(user, request.POST, prefix="pw")
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, "Your password has been changed.")
                return redirect("accounts:profile")
            messages.error(request, "Your password could not be changed. See the errors below.")

    layout = "layouts/app.html"
    return render(request, "accounts/profile.html", {
        "details_form": details_form,
        "profile_form": profile_form,
        "password_form": password_form,
        "layout": layout,
        "active_nav": "profile",
    })
