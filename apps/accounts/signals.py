from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import PassengerProfile, User


@receiver(post_save, sender=User)
def ensure_passenger_profile(sender, instance: User, created: bool, **kwargs):
    """Every passenger account always has a profile row."""
    if instance.role == User.Role.PASSENGER:
        PassengerProfile.objects.get_or_create(user=instance)


@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    from apps.operations.services.activity import log_activity
    from apps.operations.models import ActivityLog

    log_activity(ActivityLog.Action.LOGIN, f"{user.display_name} signed in", actor=user, request=request)


@receiver(user_login_failed)
def log_failed_login(sender, credentials, request=None, **kwargs):
    from apps.operations.services.activity import log_activity
    from apps.operations.models import ActivityLog

    username = (credentials or {}).get("username", "")[:60]
    log_activity(
        ActivityLog.Action.LOGIN_FAILED,
        f"Failed sign-in attempt for '{username}'",
        request=request,
    )
