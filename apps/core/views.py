from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import redirect, render

from apps.bookings.models import Passenger, SeatAllocation
from apps.railway.constants import TravelClass
from apps.railway.models import Seat, Station, Train


def search_form_context(initial: dict | None = None) -> dict:
    from django.conf import settings

    return {
        "class_choices": TravelClass.choices,
        "pax_range": range(1, settings.SITESMART["MAX_PASSENGERS_PER_BOOKING"] + 1),
        "initial": initial or {},
    }


def home(request):
    from django.utils import timezone

    stations = {s.code: s for s in Station.objects.filter(code__in=["NDLS", "BSB", "CNB", "LKO", "ADI", "MMCT"])}
    routes = [("NDLS", "BSB"), ("CNB", "LKO"), ("LKO", "BSB"), ("ADI", "MMCT")]
    popular = [
        {"from": stations[a], "to": stations[b]} for a, b in routes if a in stations and b in stations
    ]
    initial = {"date": timezone.localdate(), "passengers": 1}
    if "NDLS" in stations and "BSB" in stations:
        initial.update({"from": "NDLS", "from_label": str(stations["NDLS"]),
                        "to": "BSB", "to_label": str(stations["BSB"])})
    ctx = {
        "stats": {
            "trains": Train.objects.filter(is_active=True).count(),
            "stations": Station.objects.filter(is_active=True).count(),
            "seats": Seat.objects.filter(is_active=True).count(),
            "reallocated": Passenger.objects.filter(is_reallocated_seat=True).count(),
            "released": SeatAllocation.objects.filter(status=SeatAllocation.Status.RELEASED)
            .values("seat_id", "journey_date").distinct().count(),
        },
        "popular_routes": popular,
        "busiest": Train.objects.filter(is_active=True).annotate(n=Count("bookings")).order_by("-n")[:3],
        **search_form_context(initial),
    }
    return render(request, "core/home.html", ctx)


@login_required
def post_login(request):
    user = request.user
    if user.is_portal_admin:
        return redirect("adminpanel:dashboard")
    if user.is_tt:
        return redirect("operations:dashboard")
    return redirect("bookings:passenger_dashboard")


def error_403(request, exception=None):
    return render(request, "errors/403.html", {"message": str(exception) if exception else ""}, status=403)


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    return render(request, "errors/500.html", status=500)
