"""Train-movement simulation.

There is no real GPS or railway feed in this academic project; instead each run
(train + date) has a ``TrainSimulation`` row that an administrator or the assigned
TT moves forward step by step (or lets auto-advance on a timer).

Moving the train is what closes segments for sale: once the train has *departed*
stop ``k``, ``min_boardable_index`` becomes ``k + 1`` and no new journey can start
at or before ``k`` — so departed segments never become bookable again, even if a
no-show left them unoccupied.
"""
from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.bookings.exceptions import SimulationError
from apps.operations.models import ActivityLog, TrainSimulation
from apps.operations.services.activity import log_activity
from apps.railway.models import Train

Status = TrainSimulation.Status


def get_or_create_simulation(train: Train, journey_date: dt.date) -> TrainSimulation:
    sim, _ = TrainSimulation.objects.get_or_create(
        train=train,
        journey_date=journey_date,
        defaults={"step_interval_seconds": settings.SITESMART["SIMULATION_DEFAULT_INTERVAL"]},
    )
    return sim


def _stops(train: Train) -> list:
    return list(train.get_stops())


def _lock(sim: TrainSimulation) -> TrainSimulation:
    return TrainSimulation.objects.select_for_update().select_related("train").get(pk=sim.pk)


def start_simulation(sim: TrainSimulation, user, *, request=None) -> TrainSimulation:
    """Put the train at its origin station, ready to depart."""
    with transaction.atomic():
        sim = _lock(sim)
        if sim.status != Status.SCHEDULED:
            raise SimulationError("This run has already been started.")
        if sim.journey_date < timezone.localdate():
            raise SimulationError("Past runs cannot be started. Choose today's or a future run date.")
        if not sim.train.runs_on(sim.journey_date):
            raise SimulationError(f"Train {sim.train.number} does not run on {sim.journey_date:%A}.")
        stops = _stops(sim.train)
        if len(stops) < 2:
            raise SimulationError("Configure the train route before starting a run.")
        now = timezone.now()
        sim.status = Status.AT_STATION
        sim.current_index = 0
        sim.is_paused = False
        sim.started_at = sim.last_moved_at = now
        sim.last_moved_by = user
        sim.save()
        log_activity(ActivityLog.Action.SIM_STARTED,
                     f"Run of {sim.train.number} on {sim.journey_date:%d %b} started at {stops[0].station.name}",
                     actor=user, train=sim.train, request=request)
    return sim


def set_paused(sim: TrainSimulation, user, paused: bool, *, request=None) -> TrainSimulation:
    with transaction.atomic():
        sim = _lock(sim)
        if not sim.is_running:
            raise SimulationError("Only a running train can be paused or resumed.")
        sim.is_paused = paused
        if not paused:
            sim.last_moved_at = timezone.now()  # restart the auto-advance timer
        sim.save()
        log_activity(ActivityLog.Action.SIM_PAUSED if paused else ActivityLog.Action.SIM_RESUMED,
                     f"Run of {sim.train.number} on {sim.journey_date:%d %b} {'paused' if paused else 'resumed'}",
                     actor=user, train=sim.train, request=request)
    return sim


def set_auto_advance(sim: TrainSimulation, user, enabled: bool, interval: int | None = None) -> TrainSimulation:
    with transaction.atomic():
        sim = _lock(sim)
        sim.auto_advance = enabled
        if interval:
            sim.step_interval_seconds = max(5, min(int(interval), 600))
        sim.last_moved_at = timezone.now()
        sim.save()
    return sim


def _step(sim: TrainSimulation, stops: list, user, request=None) -> str:
    """Apply one state transition to an already-locked simulation. Returns an event label."""
    last = len(stops) - 1
    now = timezone.now()
    if sim.status == Status.AT_STATION and sim.current_index < last:
        sim.status = Status.IN_TRANSIT
        event = "departed"
        log_activity(ActivityLog.Action.TRAIN_DEPARTED,
                     f"{sim.train.number} departed {stops[sim.current_index].station.name} "
                     f"towards {stops[sim.current_index + 1].station.name}",
                     actor=user, train=sim.train, request=request,
                     metadata={"journey_date": sim.journey_date.isoformat(), "index": sim.current_index})
    elif sim.status == Status.IN_TRANSIT:
        sim.current_index += 1
        sim.status = Status.AT_STATION
        event = "arrived"
        log_activity(ActivityLog.Action.TRAIN_ARRIVED,
                     f"{sim.train.number} arrived at {stops[sim.current_index].station.name}",
                     actor=user, train=sim.train, request=request,
                     metadata={"journey_date": sim.journey_date.isoformat(), "index": sim.current_index})
    elif sim.status == Status.AT_STATION and sim.current_index >= last:
        sim.status = Status.COMPLETED
        sim.completed_at = now
        sim.auto_advance = False
        event = "completed"
        log_activity(ActivityLog.Action.SIM_COMPLETED,
                     f"{sim.train.number} completed its run of {sim.journey_date:%d %b} at {stops[-1].station.name}",
                     actor=user, train=sim.train, request=request)
    else:
        raise SimulationError("This run cannot move any further.")
    sim.last_moved_at = now
    sim.last_moved_by = user
    return event


def advance_simulation(sim: TrainSimulation, user, *, to_next_station: bool = False, request=None) -> TrainSimulation:
    """Move the train one step (depart / arrive / finish).

    With ``to_next_station=True`` a halted train departs *and* arrives at the next
    stop in one action — the "Move to next station" button.
    """
    with transaction.atomic():
        sim = _lock(sim)
        if sim.status == Status.SCHEDULED:
            raise SimulationError("Start the run first.")
        if sim.status == Status.COMPLETED:
            raise SimulationError("This run has already been completed.")
        if sim.is_paused:
            raise SimulationError("The simulation is paused. Resume it to move the train.")
        stops = _stops(sim.train)
        event = _step(sim, stops, user, request)
        if to_next_station and event == "departed":
            _step(sim, stops, user, request)
        sim.save()
    return sim


def apply_auto_advance(sim: TrainSimulation) -> TrainSimulation:
    """Lazily apply timer-based movement when a status poll arrives (no background worker needed)."""
    if not (sim.auto_advance and sim.is_running and not sim.is_paused and sim.last_moved_at):
        return sim
    elapsed = (timezone.now() - sim.last_moved_at).total_seconds()
    if elapsed < sim.step_interval_seconds:
        return sim
    with transaction.atomic():
        sim = _lock(sim)
        if not (sim.auto_advance and sim.is_running and not sim.is_paused):
            return sim
        elapsed = (timezone.now() - sim.last_moved_at).total_seconds()
        steps = min(int(elapsed // sim.step_interval_seconds), 4)
        stops = _stops(sim.train)
        for _ in range(steps):
            if sim.status == Status.COMPLETED:
                break
            _step(sim, stops, None)
        sim.save()
    return sim


def simulation_snapshot(sim: TrainSimulation | None, train: Train, journey_date: dt.date) -> dict:
    """Serializable state for dashboards: position, progress and per-stop status."""
    stops = _stops(train)
    n = len(stops)
    status = sim.status if sim else Status.SCHEDULED
    idx = sim.current_index if sim else 0
    min_boardable = sim.min_boardable_index(n) if sim else 0

    if status == Status.SCHEDULED:
        progress = 0.0
    elif status == Status.COMPLETED:
        progress = 100.0
    else:
        steps_total = max((n - 1) * 2, 1)
        done = idx * 2 + (1 if status == Status.IN_TRANSIT else 0)
        progress = round(done / steps_total * 100, 1)

    def stop_state(i: int) -> str:
        if status == Status.SCHEDULED:
            return "upcoming"
        if status == Status.COMPLETED:
            return "passed"
        if i < idx or (i == idx and status == Status.IN_TRANSIT):
            return "passed"
        if i == idx:
            return "current"
        return "upcoming"

    current = stops[idx] if stops and status in (Status.AT_STATION, Status.IN_TRANSIT) else None
    if status == Status.AT_STATION:
        next_stop = stops[idx + 1] if idx + 1 < n else None
        headline = f"Halted at {current.station.name}"
    elif status == Status.IN_TRANSIT:
        next_stop = stops[idx + 1]
        headline = f"Between {current.station.name} and {next_stop.station.name}"
    elif status == Status.COMPLETED:
        next_stop = None
        headline = f"Arrived at destination {stops[-1].station.name}" if stops else "Completed"
    else:
        next_stop = stops[0] if stops else None
        headline = "Not started — waiting at origin"

    if status == Status.AT_STATION and idx < n - 1:
        next_action = f"Depart {current.station.name}"
    elif status == Status.AT_STATION:
        next_action = "Complete journey"
    elif status == Status.IN_TRANSIT:
        next_action = f"Arrive at {next_stop.station.name}"
    else:
        next_action = ""

    return {
        "train_id": train.pk,
        "train_number": train.number,
        "train_name": train.name,
        "journey_date": journey_date.isoformat(),
        "status": status,
        "status_label": Status(status).label,
        "headline": headline,
        "current_index": idx,
        "current_station": current.station.name if current else None,
        "current_code": current.station.code if current else None,
        "next_station": next_stop.station.name if next_stop else None,
        "next_code": next_stop.station.code if next_stop else None,
        "next_action": next_action,
        "min_boardable_index": min_boardable,
        "progress": progress,
        "is_paused": bool(sim and sim.is_paused),
        "auto_advance": bool(sim and sim.auto_advance),
        "step_interval_seconds": sim.step_interval_seconds if sim else settings.SITESMART["SIMULATION_DEFAULT_INTERVAL"],
        "started_at": sim.started_at.isoformat() if sim and sim.started_at else None,
        "last_moved_at": sim.last_moved_at.isoformat() if sim and sim.last_moved_at else None,
        "can_start": status == Status.SCHEDULED and journey_date >= timezone.localdate() and train.runs_on(journey_date),
        "can_move": status in (Status.AT_STATION, Status.IN_TRANSIT) and not (sim and sim.is_paused),
        "stops": [
            {
                "index": s.sequence,
                "code": s.station.code,
                "name": s.station.name,
                "arrival": s.arrival_time.strftime("%H:%M") if s.arrival_time else None,
                "departure": s.departure_time.strftime("%H:%M") if s.departure_time else None,
                "distance_km": s.distance_km,
                "state": stop_state(s.sequence),
                "bookable_from": s.sequence >= min_boardable and s.sequence < n - 1,
            }
            for s in stops
        ],
    }
