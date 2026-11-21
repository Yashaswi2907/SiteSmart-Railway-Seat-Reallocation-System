"""Role-based access control for HTML views."""
from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

ROLE_CHECKS = {
    "PASSENGER": lambda u: u.is_passenger,
    "TT": lambda u: u.is_tt,
    "ADMIN": lambda u: u.is_portal_admin,
}


def user_has_role(user, *roles: str) -> bool:
    return bool(user and user.is_authenticated and any(ROLE_CHECKS[r](user) for r in roles))


def role_required(*roles: str):
    """Decorator: user must be signed in *and* hold one of ``roles`` (403 otherwise)."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not user_has_role(request.user, *roles):
                raise PermissionDenied("Your account does not have access to this page.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles: tuple[str, ...] = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not user_has_role(request.user, *self.allowed_roles):
            raise PermissionDenied("Your account does not have access to this page.")
        return super().dispatch(request, *args, **kwargs)


class PassengerRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("PASSENGER",)


class TTRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("TT", "ADMIN")


class AdminRequiredMixin(RoleRequiredMixin):
    allowed_roles = ("ADMIN",)
