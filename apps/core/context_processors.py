from django.conf import settings
from django.utils import timezone


def site_context(request):
    user = getattr(request, "user", None)
    role = None
    if user is not None and user.is_authenticated:
        role = "ADMIN" if user.is_portal_admin else user.role
    return {
        "BRAND_NAME": settings.SITESMART["BRAND_NAME"],
        "CURRENT_ROLE": role,
        "TODAY": timezone.localdate(),
        "MAX_PASSENGERS": settings.SITESMART["MAX_PASSENGERS_PER_BOOKING"],
    }
