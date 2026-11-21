import datetime as dt

from django.contrib import messages
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.bookings.services.availability import get_simulation
from apps.core.views import search_form_context

from .constants import CLASS_LAYOUTS, class_label
from .models import Station, Train
from .services import format_duration, journey_minutes, search_trains


def search(request):
    qp = request.GET
    from_code = (qp.get("from") or "").upper()
    to_code = (qp.get("to") or "").upper()
    coach_class = qp.get("class") or ""
    try:
        passengers = max(1, min(int(qp.get("passengers") or 1), 6))
    except ValueError:
        passengers = 1
    try:
        journey_date = dt.date.fromisoformat(qp.get("date")) if qp.get("date") else timezone.localdate()
    except ValueError:
        journey_date = timezone.localdate()
        messages.error(request, "That date was not valid; showing today instead.")

    stations = {s.code: s for s in Station.objects.filter(code__in=[from_code, to_code])}
    initial = {
        "from": from_code, "to": to_code, "date": journey_date, "class": coach_class, "passengers": passengers,
        "from_label": str(stations[from_code]) if from_code in stations else "",
        "to_label": str(stations[to_code]) if to_code in stations else "",
    }
    results, error, searched = [], "", False
    if from_code and to_code:
        searched = True
        if from_code not in stations or to_code not in stations:
            error = "Choose both stations from the suggestions list."
        elif from_code == to_code:
            error = "Origin and destination must be different."
        elif journey_date < timezone.localdate():
            error = "The journey date is in the past. Pick today or a later date."
        else:
            results = search_trains(from_code, to_code, journey_date, coach_class or None, passengers)
    ctx = {
        **search_form_context(initial),
        "results": results,
        "error": error,
        "searched": searched,
        "from_station": stations.get(from_code),
        "to_station": stations.get(to_code),
        "journey_date": journey_date,
        "passengers": passengers,
        "coach_class": coach_class,
        "active_nav": "search",
        "date_strip": [journey_date + dt.timedelta(days=i) for i in range(-1, 6)
                       if journey_date + dt.timedelta(days=i) >= timezone.localdate()][:6],
    }
    return render(request, "railway/search.html", ctx)


def train_list(request):
    trains = Train.objects.filter(is_active=True).select_related("route").prefetch_related("coaches")
    rows = []
    for t in trains:
        stops = list(t.get_stops())
        if len(stops) < 2:
            continue
        rows.append({"train": t, "src": stops[0], "dst": stops[-1], "stops": len(stops),
                     "duration": format_duration(journey_minutes(timezone.localdate(), stops[0], stops[-1])),
                     "classes": t.available_classes()})
    return render(request, "railway/train_list.html", {"rows": rows, "active_nav": "trains"})


def train_detail(request, number):
    train = get_object_or_404(Train.objects.select_related("route"), number=number)
    stops = list(train.get_stops())
    today = timezone.localdate()
    sim = get_simulation(train, today)
    coaches = []
    for c in train.coaches.filter(is_active=True).order_by("position"):
        coaches.append({"coach": c, "label": class_label(c.coach_class), "seats": c.seats.filter(is_active=True).count(),
                        "kind": CLASS_LAYOUTS[c.coach_class]["kind"]})
    total = journey_minutes(today, stops[0], stops[-1]) if len(stops) > 1 else 0
    return render(request, "railway/train_detail.html", {
        "train": train, "stops": stops, "coaches": coaches, "sim": sim, "duration": format_duration(total),
        "next_runs": [today + dt.timedelta(days=i) for i in range(14) if train.runs_on(today + dt.timedelta(days=i))][:5],
        "active_nav": "trains",
    })
