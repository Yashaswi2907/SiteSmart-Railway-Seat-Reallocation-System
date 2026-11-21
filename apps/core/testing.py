"""Shared test fixtures: a compact railway network used by every app's tests."""
from __future__ import annotations

import datetime as dt

from django.utils import timezone

from apps.accounts.models import TTProfile, User
from apps.railway.models import Coach, Station, Train, TrainRoute, TrainStop

PASSWORD = "Test@Pass123"


def next_run_date(train: Train | None = None, offset: int = 1) -> dt.date:
    date = timezone.localdate() + dt.timedelta(days=offset)
    if train is not None:
        while not train.runs_on(date):
            date += dt.timedelta(days=1)
    return date


def make_user(username: str, role: str = User.Role.PASSENGER, **extra) -> User:
    user = User.objects.create_user(
        username=username, email=f"{username}@example.test", password=PASSWORD,
        first_name=extra.pop("first_name", username.title()), last_name=extra.pop("last_name", "Tester"),
        role=role, **extra,
    )
    if role == User.Role.TT:
        TTProfile.objects.create(user=user, employee_id=f"TT-{user.pk:04d}")
    return user


def make_route_train(codes=("A", "B", "C", "D", "E"), number="10001", seats=8, coach_class="SL",
                     extra_coaches: int = 0) -> Train:
    """Train A -> B -> C -> D -> E with one small coach (``seats`` berths)."""
    train = Train.objects.create(number=number, name=f"Test Express {number}", running_days="1111111")
    route = TrainRoute.objects.create(train=train, name="Test route")
    hour = 6
    for i, code in enumerate(codes):
        station, _ = Station.objects.get_or_create(
            code=f"T{code}" if len(code) == 1 else code,
            defaults={"name": f"Station {code}", "city": f"City {code}", "state": "Test State"},
        )
        TrainStop.objects.create(
            route=route, station=station, sequence=i,
            arrival_time=None if i == 0 else dt.time(hour, 0),
            departure_time=None if i == len(codes) - 1 else dt.time(hour, 10),
            distance_km=i * 120,
        )
        hour += 2
    for n in range(1 + extra_coaches):
        coach = Coach.objects.create(train=train, coach_number=f"S{n + 1}", coach_class=coach_class, position=n + 1)
        coach.generate_seats(seats)
    return train


def stop(train: Train, index: int) -> TrainStop:
    return train.route.stops.get(sequence=index)


def pax(name: str = "Asha Rao", age: int = 30, gender: str = "F", berth: str = "") -> dict:
    return {"name": name, "age": age, "gender": gender, "berth_preference": berth}
