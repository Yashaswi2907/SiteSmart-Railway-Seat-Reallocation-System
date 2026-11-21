"""Aggregations for the administrator dashboard (every number comes from the database)."""
from __future__ import annotations

import datetime as dt
from collections import OrderedDict

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.models import BoardingStatus, Booking, Passenger, SeatAllocation
from apps.bookings.services.availability import get_route_stops
from apps.operations.models import ActivityLog, TrainSimulation
from apps.railway.constants import CLASS_ORDER
from apps.railway.models import Seat, Station, Train


def run_utilisation(train: Train, journey_date: dt.date, seat_count: int | None = None,
                    segments: int | None = None) -> float:
    """Share of seat-segments sold (ACTIVE) on one run, in percent."""
    if seat_count is None:
        seat_count = Seat.objects.filter(coach__train=train, is_active=True, coach__is_active=True).count()
    if segments is None:
        segments = max(len(get_route_stops(train)) - 1, 1)
    if not seat_count:
        return 0.0
    used = SeatAllocation.objects.filter(seat__coach__train=train, journey_date=journey_date,
                                         status=SeatAllocation.Status.ACTIVE).count()
    return round(used / (seat_count * segments) * 100, 1)


def dashboard_stats() -> dict:
    today = timezone.localdate()
    trains = list(Train.objects.filter(is_active=True).select_related("route"))
    seat_counts = dict(
        Seat.objects.filter(is_active=True, coach__is_active=True)
        .values_list("coach__train").annotate(n=Count("id"))
    )
    segment_counts = {t.pk: max(t.route.stops.count() - 1, 1) if hasattr(t, "route") else 1 for t in trains}

    # Utilisation per train over the next 7 run days (only dates the train runs).
    horizon = [today + dt.timedelta(days=i) for i in range(7)]
    active_rows = dict(
        SeatAllocation.objects.filter(status=SeatAllocation.Status.ACTIVE, journey_date__in=horizon)
        .values_list("seat__coach__train").annotate(n=Count("id"))
    )
    utilisation = []
    total_used = total_capacity = 0
    for t in trains:
        runs = sum(1 for d in horizon if t.runs_on(d))
        capacity = seat_counts.get(t.pk, 0) * segment_counts[t.pk] * runs
        used = active_rows.get(t.pk, 0)
        total_used += used
        total_capacity += capacity
        utilisation.append({"train": f"{t.number}", "name": t.name,
                            "value": round(used / capacity * 100, 1) if capacity else 0})

    # Bookings created per day (last 14 days).
    start = today - dt.timedelta(days=13)
    start_dt = timezone.make_aware(dt.datetime.combine(start, dt.time.min))
    daily = (
        Booking.objects.filter(created_at__gte=start_dt)
        .annotate(day=TruncDate("created_at", tzinfo=timezone.get_current_timezone()))
        .values("day")
        .annotate(confirmed=Count("id", filter=Q(status=Booking.Status.CONFIRMED)),
                  cancelled=Count("id", filter=Q(status=Booking.Status.CANCELLED)))
    )
    by_day = OrderedDict((start + dt.timedelta(days=i), {"confirmed": 0, "cancelled": 0}) for i in range(14))
    for row in daily:
        if row["day"] in by_day:
            by_day[row["day"]] = {"confirmed": row["confirmed"], "cancelled": row["cancelled"]}

    class_rows = dict(
        Passenger.objects.filter(status=Passenger.Status.CONFIRMED, booking__journey_date__gte=today)
        .values_list("booking__coach_class").annotate(n=Count("id"))
    )
    boarding = dict(
        BoardingStatus.objects.filter(passenger__status=Passenger.Status.CONFIRMED)
        .values_list("status").annotate(n=Count("id"))
    )
    released_seat_runs = (
        SeatAllocation.objects.filter(status=SeatAllocation.Status.RELEASED)
        .values("seat_id", "journey_date").distinct().count()
    )
    return {
        "totals": {
            "trains": len(trains),
            "stations": Station.objects.filter(is_active=True).count(),
            "passengers": User.objects.filter(role=User.Role.PASSENGER, is_active=True).count(),
            "bookings": Booking.objects.filter(status=Booking.Status.CONFIRMED).count(),
            "cancelled": Booking.objects.filter(status=Booking.Status.CANCELLED).count(),
            "tt_active": User.objects.filter(role=User.Role.TT, is_active=True).count(),
            "released_seats": released_seat_runs,
            "reallocated_passengers": Passenger.objects.filter(is_reallocated_seat=True,
                                                               status=Passenger.Status.CONFIRMED).count(),
            "utilisation": round(total_used / total_capacity * 100, 1) if total_capacity else 0,
            "running_now": TrainSimulation.objects.filter(
                status__in=[TrainSimulation.Status.AT_STATION, TrainSimulation.Status.IN_TRANSIT]).count(),
            "upcoming_journeys": Booking.objects.filter(status=Booking.Status.CONFIRMED,
                                                        journey_date__gte=today).count(),
        },
        "charts": {
            "bookings_trend": {
                "labels": [d.strftime("%d %b") for d in by_day],
                "confirmed": [v["confirmed"] for v in by_day.values()],
                "cancelled": [v["cancelled"] for v in by_day.values()],
            },
            "utilisation": utilisation,
            "classes": {"labels": [c for c in CLASS_ORDER if c in class_rows],
                        "values": [class_rows[c] for c in CLASS_ORDER if c in class_rows]},
            "boarding": {
                "labels": ["Boarded", "Did not board", "Pending"],
                "values": [boarding.get("BOARDED", 0), boarding.get("NOT_BOARDED", 0), boarding.get("PENDING", 0)],
            },
        },
        "recent_activity": list(ActivityLog.objects.select_related("actor")[:8]),
    }


def seat_matrix(train: Train, journey_date: dt.date, coach_id: int | None = None) -> dict:
    """Seats x segments occupancy grid for the allocation monitor."""
    stops = get_route_stops(train)
    sim = TrainSimulation.objects.filter(train=train, journey_date=journey_date).first()
    min_boardable = sim.min_boardable_index(len(stops)) if sim else 0
    coaches = list(train.coaches.filter(is_active=True).order_by("position"))
    coach = next((c for c in coaches if c.pk == coach_id), coaches[0] if coaches else None)
    if coach is None or len(stops) < 2:
        return {"coach": None, "coaches": [], "segments": [], "rows": []}
    allocs = (
        SeatAllocation.objects.filter(seat__coach=coach, journey_date=journey_date)
        .exclude(status=SeatAllocation.Status.CANCELLED)
        .select_related("passenger__booking")
    )
    grid: dict[tuple[int, int], dict] = {}
    for a in allocs:
        key = (a.seat_id, a.segment_index)
        if a.status == SeatAllocation.Status.ACTIVE:
            grid[key] = {"s": "A", "pnr": a.passenger.booking.pnr, "r": a.passenger.is_reallocated_seat}
        elif key not in grid:
            grid[key] = {"s": "R", "pnr": a.passenger.booking.pnr}
    seg_count = len(stops) - 1
    rows = []
    for seat in coach.seats.filter(is_active=True).order_by("seat_number"):
        cells = []
        for seg in range(seg_count):
            cell = dict(grid.get((seat.id, seg), {"s": "F"}))
            cell["d"] = seg < min_boardable
            cells.append(cell)
        rows.append({"seat_id": seat.id, "number": seat.seat_number, "berth": seat.berth_type, "cells": cells})
    return {
        "coach": {"id": coach.pk, "number": coach.coach_number, "coach_class": coach.coach_class},
        "coaches": [{"id": c.pk, "number": c.coach_number, "coach_class": c.coach_class} for c in coaches],
        "segments": [f"{stops[i].station.code}→{stops[i + 1].station.code}" for i in range(seg_count)],
        "stops": [{"index": s.sequence, "code": s.station.code, "name": s.station.name} for s in stops],
        "min_boardable": min_boardable,
        "rows": rows,
    }
