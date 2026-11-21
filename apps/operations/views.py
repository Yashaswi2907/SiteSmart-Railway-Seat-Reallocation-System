"""TT/TTE pages: duty dashboard, live run console and PNR lookup."""
import datetime as dt

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import BoardingStatus, Booking, Passenger, SeatAllocation
from apps.bookings.services.boarding import user_can_operate_train
from apps.core.permissions import role_required
from apps.railway.models import Train

from .models import TrainSimulation


def operable_trains(user):
    qs = Train.objects.filter(is_active=True).select_related("route")
    if user.is_portal_admin:
        return qs
    profile = getattr(user, "tt_profile", None)
    return qs.filter(pk__in=profile.assigned_trains.values("pk")) if profile else qs.none()


def next_run_date(train: Train, start: dt.date) -> dt.date | None:
    for i in range(8):
        d = start + dt.timedelta(days=i)
        if train.runs_on(d):
            return d
    return None


@role_required("TT", "ADMIN")
def dashboard(request):
    today = timezone.localdate()
    trains = list(operable_trains(request.user))
    runs = []
    for t in trains:
        run_date = next_run_date(t, today)
        stops = list(t.get_stops())
        if not run_date or len(stops) < 2:
            continue
        sim = TrainSimulation.objects.filter(train=t, journey_date=run_date).first()
        pax = Passenger.objects.filter(booking__train=t, booking__journey_date=run_date,
                                       booking__status=Booking.Status.CONFIRMED, status=Passenger.Status.CONFIRMED)
        agg = pax.aggregate(total=Count("id"),
                            boarded=Count("id", filter=Q(boarding__status=BoardingStatus.Status.BOARDED)),
                            nb=Count("id", filter=Q(boarding__status=BoardingStatus.Status.NOT_BOARDED)))
        current = stops[sim.current_index] if sim and sim.is_running else None
        runs.append({"train": t, "date": run_date, "sim": sim, "stops": stops, "current": current, **agg,
                     "pending": agg["total"] - agg["boarded"] - agg["nb"],
                     "url": reverse("operations:run_console", args=[t.pk, run_date.isoformat()])})
    totals = {k: sum(r[k] for r in runs) for k in ("total", "boarded", "nb", "pending")}
    run_dates = {(r["train"].pk, r["date"]) for r in runs}
    released = 0
    for train_id, d in run_dates:
        released += (SeatAllocation.objects.filter(seat__coach__train_id=train_id, journey_date=d,
                                                   status=SeatAllocation.Status.RELEASED)
                     .values("seat_id").distinct().count())
    live = next((r for r in runs if r["sim"] and r["sim"].is_running), None)
    return render(request, "tt/dashboard.html", {
        "runs": runs, "totals": totals, "released": released, "live": live,
        "chart": {"labels": ["Boarded", "Did not board", "Pending"],
                  "values": [totals["boarded"], totals["nb"], totals["pending"]]},
        "active_nav": "tt_dashboard",
    })


@role_required("TT", "ADMIN")
def run_console(request, train_id, date):
    train = get_object_or_404(Train, pk=train_id)
    if not user_can_operate_train(request.user, train):
        raise PermissionDenied("You are not assigned to this train.")
    try:
        journey_date = dt.date.fromisoformat(date)
    except ValueError:
        messages.error(request, "Invalid run date.")
        return redirect("operations:dashboard")
    if request.GET.get("date") and request.GET["date"] != date:
        return redirect("operations:run_console", train_id=train.pk, date=request.GET["date"])
    config = {
        "trainId": train.pk,
        "trainNumber": train.number,
        "date": journey_date.isoformat(),
        "isAdmin": request.user.is_portal_admin,
        "urls": {
            "console": reverse("api:run_console", args=[train.pk, journey_date.isoformat()]),
            "control": reverse("api:run_control", args=[train.pk, journey_date.isoformat()]),
            "passengers": reverse("api:run_passengers", args=[train.pk, journey_date.isoformat()]),
            "occupancy": reverse("api:run_occupancy", args=[train.pk, journey_date.isoformat()]),
            "released": reverse("api:run_released", args=[train.pk, journey_date.isoformat()]),
            "verify": reverse("api:verify_passenger", args=[0]).replace("/0/", "/{id}/"),
            "search": reverse("railway:search"),
        },
    }
    return render(request, "tt/run_console.html", {
        "train": train, "journey_date": journey_date, "config": config,
        "runs_on": train.runs_on(journey_date),
        "active_nav": "tt_console" if request.user.is_tt else "simulation",
    })


@role_required("TT", "ADMIN")
def lookup(request):
    return render(request, "tt/lookup.html", {"active_nav": "tt_lookup", "pnr": request.GET.get("pnr", "")})
