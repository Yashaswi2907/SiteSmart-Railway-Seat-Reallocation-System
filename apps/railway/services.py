"""Train search: which trains connect two stations and how many seats are free per class."""
from __future__ import annotations

import datetime as dt

from django.db.models import Q

from apps.bookings.services.availability import class_availability, get_simulation
from apps.bookings.services.fares import calculate_fare

from .constants import CLASS_ORDER, class_label
from .models import Station, TrainStop


def stop_datetime(run_date: dt.date, stop: TrainStop, *, arrival: bool) -> dt.datetime | None:
    t = (stop.arrival_time or stop.departure_time) if arrival else (stop.departure_time or stop.arrival_time)
    if t is None:
        return None
    return dt.datetime.combine(run_date + dt.timedelta(days=stop.day_offset), t)


def journey_minutes(run_date: dt.date, from_stop: TrainStop, to_stop: TrainStop) -> int:
    dep = stop_datetime(run_date, from_stop, arrival=False)
    arr = stop_datetime(run_date, to_stop, arrival=True)
    if not (dep and arr):
        return 0
    if arr < dep:  # defensive: data entered without day offsets
        arr += dt.timedelta(days=1)
    return int((arr - dep).total_seconds() // 60)


def format_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m"


def suggest_stations(query: str, limit: int = 12) -> list[Station]:
    query = (query or "").strip()
    qs = Station.objects.filter(is_active=True)
    if query:
        qs = qs.filter(Q(code__istartswith=query) | Q(name__icontains=query) | Q(city__icontains=query))
    return list(qs.order_by("name")[:limit])


def search_trains(from_code: str, to_code: str, journey_date: dt.date, coach_class: str | None = None,
                  passengers: int = 1) -> list[dict]:
    """Every active train serving ``from_code`` before ``to_code``, with per-class availability."""
    from_code, to_code = from_code.upper(), to_code.upper()
    origin_stops = (
        TrainStop.objects.filter(station__code=from_code, route__train__is_active=True)
        .select_related("route__train", "station")
    )
    results = []
    for fs in origin_stops:
        ts = (
            TrainStop.objects.filter(route=fs.route, station__code=to_code, sequence__gt=fs.sequence)
            .select_related("station")
            .first()
        )
        if ts is None:
            continue
        train = fs.route.train
        stop_count = fs.route.stops.count()
        sim = get_simulation(train, journey_date)
        min_boardable = sim.min_boardable_index(stop_count) if sim else 0
        runs = train.runs_on(journey_date)
        departed = fs.sequence < min_boardable
        availability = class_availability(train, journey_date, fs.sequence, ts.sequence) if runs else {}
        distance = max(ts.distance_km - fs.distance_km, 1)
        classes = []
        for code in CLASS_ORDER:
            if code not in availability:
                continue
            info = availability[code]
            classes.append({
                "code": code,
                "label": class_label(code),
                "total": info["total"],
                "available": info["available"],
                "reallocated": info["reallocated"],
                "fare": int(calculate_fare(code, distance)),
                "bookable": runs and not departed and info["available"] >= passengers,
                "selected": code == coach_class,
            })
        if coach_class and runs and not any(c["code"] == coach_class for c in classes):
            continue  # train does not carry the requested class
        minutes = journey_minutes(journey_date, fs, ts)
        if sim and sim.status == sim.Status.COMPLETED:
            departed_message = "This run has been completed."
        elif departed:
            departed_message = f"Train has already left {fs.station.name} on this run."
        else:
            departed_message = ""
        results.append({
            "train": train,
            "train_id": train.pk,
            "number": train.number,
            "name": train.name,
            "train_type": train.get_train_type_display(),
            "running_days": train.running_days_display,
            "runs_on_date": runs,
            "from_stop": fs,
            "to_stop": ts,
            "from_index": fs.sequence,
            "to_index": ts.sequence,
            "departure": fs.departure_time,
            "arrival": ts.arrival_time,
            "arrival_day_offset": ts.day_offset - fs.day_offset,
            "duration_minutes": minutes,
            "duration": format_duration(minutes),
            "distance_km": distance,
            "classes": classes,
            "departed": departed,
            "departed_message": departed_message,
            "simulation_status": sim.get_status_display() if sim else "Scheduled",
            "intermediate_stops": ts.sequence - fs.sequence - 1,
        })
    results.sort(key=lambda r: (not r["runs_on_date"], r["departed"], r["departure"] or dt.time(0)))
    return results
