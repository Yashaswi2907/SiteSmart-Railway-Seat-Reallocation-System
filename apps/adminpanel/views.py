"""Custom administrator portal (Django Admin remains available as a secondary interface)."""
from __future__ import annotations

import datetime as dt

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.bookings.models import BoardingStatus, Booking, Cancellation, Passenger, SeatAllocation
from apps.core.permissions import role_required
from apps.operations.models import ActivityLog, TrainSimulation
from apps.operations.services.activity import log_activity
from apps.railway.constants import CLASS_LAYOUTS, class_label
from apps.railway.models import Coach, Seat, Station, Train, TrainRoute, TrainStop

from .forms import CoachForm, SeatForm, StaffForm, StationForm, TrainForm, TrainStopForm
from .services import dashboard_stats

admin_only = role_required("ADMIN")


def _log(request, description: str, train=None):
    log_activity(ActivityLog.Action.ADMIN_CHANGE, description, actor=request.user, train=train, request=request)


def _paginate(request, qs, per_page=20):
    return Paginator(qs, per_page).get_page(request.GET.get("page"))


def _form_page(request, form, *, title, subtitle="", back_url, submit="Save", active_nav="", crumbs=None, extra=None):
    return render(request, "adminpanel/form.html", {
        "form": form, "title": title, "subtitle": subtitle, "back_url": back_url, "submit": submit,
        "active_nav": active_nav, "crumbs": crumbs or [], **(extra or {}),
    })


def _parse_date(value, default=None):
    try:
        return dt.date.fromisoformat(value) if value else default
    except ValueError:
        return default


# --------------------------------------------------------------------- Dashboard
@admin_only
def dashboard(request):
    stats = dashboard_stats()
    today = timezone.localdate()
    runs_today = []
    for t in Train.objects.filter(is_active=True).order_by("number"):
        if t.runs_on(today):
            sim = TrainSimulation.objects.filter(train=t, journey_date=today).first()
            runs_today.append({"train": t, "sim": sim,
                               "url": reverse("operations:run_console", args=[t.pk, today.isoformat()])})
    return render(request, "adminpanel/dashboard.html", {
        "stats": stats, "chart": stats["charts"], "runs_today": runs_today, "active_nav": "admin_dashboard",
    })


# ------------------------------------------------------------------------ Trains
def route_locked(train: Train) -> str:
    """Reason why structural route edits are blocked, or '' if they are allowed."""
    today = timezone.localdate()
    if Booking.objects.filter(train=train, journey_date__gte=today, status=Booking.Status.CONFIRMED).exists():
        return "This train has upcoming confirmed bookings. Stop sequence changes would invalidate their segment indices."
    if TrainSimulation.objects.filter(train=train, status__in=["AT_STATION", "IN_TRANSIT"]).exists():
        return "A run of this train is in progress."
    return ""


@admin_only
def train_list(request):
    q = (request.GET.get("q") or "").strip()
    trains = Train.objects.select_related("route").annotate(
        coach_count=Count("coaches", distinct=True), booking_count=Count("bookings", distinct=True))
    if q:
        trains = trains.filter(Q(number__startswith=q) | Q(name__icontains=q))
    rows = []
    for t in trains.order_by("number"):
        stops = list(t.get_stops())
        rows.append({"train": t, "src": stops[0] if stops else None, "dst": stops[-1] if stops else None,
                     "stops": len(stops), "classes": t.available_classes()})
    return render(request, "adminpanel/train_list.html", {"rows": rows, "q": q, "active_nav": "trains"})


@admin_only
def train_create(request):
    form = TrainForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        train = form.save()
        TrainRoute.objects.create(train=train, name=f"{train.name} route")
        _log(request, f"Created train {train}", train)
        messages.success(request, f"Train {train.number} created. Now add its route stops and coaches.")
        return redirect("adminpanel:train_detail", pk=train.pk)
    return _form_page(request, form, title="Add train", back_url=reverse("adminpanel:train_list"),
                      submit="Create train", active_nav="trains",
                      crumbs=[("Trains", reverse("adminpanel:train_list"))])


@admin_only
def train_edit(request, pk):
    train = get_object_or_404(Train, pk=pk)
    form = TrainForm(request.POST or None, instance=train)
    if request.method == "POST" and form.is_valid():
        form.save()
        _log(request, f"Updated train {train}", train)
        messages.success(request, "Train details saved.")
        return redirect("adminpanel:train_detail", pk=train.pk)
    return _form_page(request, form, title=f"Edit {train.number}", subtitle=train.name,
                      back_url=reverse("adminpanel:train_detail", args=[train.pk]), active_nav="trains",
                      crumbs=[("Trains", reverse("adminpanel:train_list")), (train.number, reverse("adminpanel:train_detail", args=[train.pk]))])


@admin_only
def train_detail(request, pk):
    train = get_object_or_404(Train.objects.select_related("route"), pk=pk)
    if not hasattr(train, "route"):
        TrainRoute.objects.create(train=train, name=f"{train.name} route")
        train.refresh_from_db()
    coaches = train.coaches.annotate(seat_total=Count("seats"), seat_active=Count("seats", filter=Q(seats__is_active=True)))
    today = timezone.localdate()
    return render(request, "adminpanel/train_detail.html", {
        "train": train,
        "stops": train.get_stops(),
        "coaches": coaches.order_by("position"),
        "stop_form": TrainStopForm(route=train.route),
        "coach_form": CoachForm(train=train),
        "locked_reason": route_locked(train),
        "tts": User.objects.filter(tt_profile__assigned_trains=train),
        "upcoming_bookings": Booking.objects.filter(train=train, journey_date__gte=today,
                                                    status=Booking.Status.CONFIRMED).count(),
        "active_nav": "trains",
    })


@admin_only
@require_POST
def train_delete(request, pk):
    train = get_object_or_404(Train, pk=pk)
    label = str(train)
    try:
        train.delete()
    except ProtectedError:
        messages.error(request, f"{label} has bookings and cannot be deleted. Deactivate it instead.")
        return redirect("adminpanel:train_detail", pk=pk)
    _log(request, f"Deleted train {label}")
    messages.success(request, f"{label} deleted.")
    return redirect("adminpanel:train_list")


# ------------------------------------------------------------------- Route stops
@admin_only
@require_POST
def stop_add(request, pk):
    train = get_object_or_404(Train.objects.select_related("route"), pk=pk)
    reason = route_locked(train)
    if reason:
        messages.error(request, reason)
        return redirect("adminpanel:train_detail", pk=pk)
    form = TrainStopForm(request.POST, route=train.route)
    if form.is_valid():
        stop = form.save(commit=False)
        stop.route = train.route
        stop.sequence = train.route.stops.count()
        stop.save()
        _log(request, f"Added stop {stop.station.code} to {train.number}", train)
        messages.success(request, f"{stop.station.name} added as stop {stop.sequence + 1}.")
    else:
        messages.error(request, "Stop not added: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect(reverse("adminpanel:train_detail", args=[pk]) + "#route")


@admin_only
def stop_edit(request, pk):
    stop = get_object_or_404(TrainStop.objects.select_related("route__train", "station"), pk=pk)
    train = stop.route.train
    form = TrainStopForm(request.POST or None, instance=stop, route=stop.route)
    if route_locked(train):
        form.fields["station"].disabled = True
        form.fields["distance_km"].disabled = True
    if request.method == "POST" and form.is_valid():
        form.save()
        _log(request, f"Edited stop {stop.station.code} of {train.number}", train)
        messages.success(request, "Stop timings saved.")
        return redirect(reverse("adminpanel:train_detail", args=[train.pk]) + "#route")
    return _form_page(request, form, title=f"Edit stop {stop.sequence + 1}: {stop.station.name}",
                      subtitle=f"Train {train.number}", back_url=reverse("adminpanel:train_detail", args=[train.pk]),
                      active_nav="schedules",
                      crumbs=[("Trains", reverse("adminpanel:train_list")), (train.number, reverse("adminpanel:train_detail", args=[train.pk]))])


@admin_only
@require_POST
def stop_delete(request, pk):
    stop = get_object_or_404(TrainStop.objects.select_related("route__train", "station"), pk=pk)
    train = stop.route.train
    reason = route_locked(train)
    if reason:
        messages.error(request, reason)
    else:
        try:
            with transaction.atomic():
                stop.delete()
                stop.route.resequence()
            _log(request, f"Removed stop {stop.station.code} from {train.number}", train)
            messages.success(request, f"{stop.station.name} removed from the route.")
        except ProtectedError:
            messages.error(request, "This stop is referenced by past bookings and cannot be removed.")
    return redirect(reverse("adminpanel:train_detail", args=[train.pk]) + "#route")


@admin_only
@require_POST
def stop_move(request, pk, direction):
    stop = get_object_or_404(TrainStop.objects.select_related("route__train"), pk=pk)
    train = stop.route.train
    reason = route_locked(train)
    if reason:
        messages.error(request, reason)
        return redirect(reverse("adminpanel:train_detail", args=[train.pk]) + "#route")
    target = stop.sequence - 1 if direction == "up" else stop.sequence + 1
    other = stop.route.stops.filter(sequence=target).first()
    if other:
        with transaction.atomic():
            a, b = stop.sequence, other.sequence
            TrainStop.objects.filter(pk=stop.pk).update(sequence=999)
            TrainStop.objects.filter(pk=other.pk).update(sequence=a)
            TrainStop.objects.filter(pk=stop.pk).update(sequence=b)
        _log(request, f"Reordered stops of {train.number}", train)
    return redirect(reverse("adminpanel:train_detail", args=[train.pk]) + "#route")


# ---------------------------------------------------------------- Coaches & seats
@admin_only
@require_POST
def coach_add(request, pk):
    train = get_object_or_404(Train, pk=pk)
    form = CoachForm(request.POST, train=train)
    if form.is_valid():
        coach = form.save(commit=False)
        coach.train = train
        coach.save()
        created = coach.generate_seats(form.cleaned_data.get("seat_count"))
        _log(request, f"Added coach {coach.coach_number} ({coach.coach_class}) with {created} seats to {train.number}", train)
        messages.success(request, f"Coach {coach.coach_number} added with {created} seats.")
    else:
        messages.error(request, "Coach not added: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect(reverse("adminpanel:train_detail", args=[pk]) + "#coaches")


@admin_only
def coach_edit(request, pk):
    coach = get_object_or_404(Coach.objects.select_related("train"), pk=pk)
    form = CoachForm(request.POST or None, instance=coach, train=coach.train)
    if request.method == "POST" and form.is_valid():
        form.save()
        _log(request, f"Edited coach {coach.coach_number} of {coach.train.number}", coach.train)
        messages.success(request, "Coach saved.")
        return redirect(reverse("adminpanel:train_detail", args=[coach.train.pk]) + "#coaches")
    return _form_page(request, form, title=f"Edit coach {coach.coach_number}", subtitle=str(coach.train),
                      back_url=reverse("adminpanel:train_detail", args=[coach.train.pk]), active_nav="trains",
                      crumbs=[("Trains", reverse("adminpanel:train_list")), (coach.train.number, reverse("adminpanel:train_detail", args=[coach.train.pk]))])


@admin_only
@require_POST
def coach_delete(request, pk):
    coach = get_object_or_404(Coach.objects.select_related("train"), pk=pk)
    train = coach.train
    if SeatAllocation.objects.filter(seat__coach=coach).exists() or Passenger.objects.filter(seat__coach=coach).exists():
        messages.error(request, f"Coach {coach.coach_number} has booking history. Deactivate it instead of deleting.")
    else:
        coach.delete()
        _log(request, f"Deleted coach {coach.coach_number} from {train.number}", train)
        messages.success(request, f"Coach {coach.coach_number} deleted.")
    return redirect(reverse("adminpanel:train_detail", args=[train.pk]) + "#coaches")


@admin_only
def coach_seats(request, pk):
    coach = get_object_or_404(Coach.objects.select_related("train"), pk=pk)
    form = SeatForm(request.POST or None, coach=coach,
                    initial={"seat_number": (coach.seats.order_by("-seat_number").values_list("seat_number", flat=True).first() or 0) + 1})
    if request.method == "POST" and form.is_valid():
        seat = form.save(commit=False)
        seat.coach = coach
        seat.save()
        _log(request, f"Added seat {seat.seat_number} to {coach}", coach.train)
        messages.success(request, f"Seat {seat.seat_number} added.")
        return redirect("adminpanel:coach_seats", pk=coach.pk)
    booked = set(SeatAllocation.objects.filter(seat__coach=coach).values_list("seat_id", flat=True).distinct())
    return render(request, "adminpanel/coach_seats.html", {
        "coach": coach, "seats": coach.seats.order_by("seat_number"), "form": form, "booked": booked,
        "layout": CLASS_LAYOUTS[coach.coach_class], "class_label": class_label(coach.coach_class), "active_nav": "trains",
    })


@admin_only
@require_POST
def seat_toggle(request, pk):
    seat = get_object_or_404(Seat.objects.select_related("coach__train"), pk=pk)
    seat.is_active = not seat.is_active
    seat.save(update_fields=["is_active", "updated_at"])
    _log(request, f"Seat {seat} {'activated' if seat.is_active else 'taken out of service'}", seat.coach.train)
    messages.success(request, f"Seat {seat.seat_number} is now {'in service' if seat.is_active else 'out of service'}.")
    return redirect("adminpanel:coach_seats", pk=seat.coach_id)


@admin_only
@require_POST
def seat_delete(request, pk):
    seat = get_object_or_404(Seat.objects.select_related("coach__train"), pk=pk)
    coach_id = seat.coach_id
    try:
        seat.delete()
        _log(request, f"Deleted seat {seat}", seat.coach.train)
        messages.success(request, f"Seat {seat.seat_number} deleted.")
    except ProtectedError:
        messages.error(request, f"Seat {seat.seat_number} has booking history; take it out of service instead.")
    return redirect("adminpanel:coach_seats", pk=coach_id)


# ---------------------------------------------------------------------- Stations
@admin_only
def station_list(request):
    q = (request.GET.get("q") or "").strip()
    stations = Station.objects.annotate(train_count=Count("stops", distinct=True))
    if q:
        stations = stations.filter(Q(code__istartswith=q) | Q(name__icontains=q) | Q(city__icontains=q) | Q(state__icontains=q))
    return render(request, "adminpanel/station_list.html", {
        "page_obj": _paginate(request, stations.order_by("name"), 25), "q": q, "active_nav": "stations"})


@admin_only
def station_form(request, pk=None):
    station = get_object_or_404(Station, pk=pk) if pk else None
    form = StationForm(request.POST or None, instance=station)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        _log(request, f"{'Updated' if pk else 'Created'} station {obj}")
        messages.success(request, f"Station {obj.code} saved.")
        return redirect("adminpanel:station_list")
    return _form_page(request, form, title=f"Edit {station}" if station else "Add station",
                      back_url=reverse("adminpanel:station_list"), active_nav="stations",
                      crumbs=[("Stations", reverse("adminpanel:station_list"))])


@admin_only
@require_POST
def station_delete(request, pk):
    station = get_object_or_404(Station, pk=pk)
    try:
        station.delete()
        _log(request, f"Deleted station {station}")
        messages.success(request, f"{station} deleted.")
    except ProtectedError:
        messages.error(request, f"{station} is used by train routes and cannot be deleted. Deactivate it instead.")
    return redirect("adminpanel:station_list")


# --------------------------------------------------------------------- Schedules
@admin_only
def schedules(request):
    rows = []
    for t in Train.objects.select_related("route").order_by("number"):
        stops = list(t.get_stops())
        rows.append({"train": t, "stops": stops})
    return render(request, "adminpanel/schedules.html", {"rows": rows, "active_nav": "schedules"})


# ------------------------------------------------------------------------ People
@admin_only
def passenger_list(request):
    q = (request.GET.get("q") or "").strip()
    users = User.objects.filter(role=User.Role.PASSENGER).annotate(
        booking_count=Count("bookings", distinct=True),
        active_count=Count("bookings", filter=Q(bookings__status="CONFIRMED"), distinct=True))
    if q:
        users = users.filter(Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
    return render(request, "adminpanel/passenger_list.html", {
        "page_obj": _paginate(request, users.order_by("-date_joined")), "q": q, "active_nav": "passengers"})


@admin_only
@require_POST
def user_toggle(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "You cannot deactivate your own account.")
    else:
        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        _log(request, f"{'Activated' if user.is_active else 'Deactivated'} account {user.username}")
        messages.success(request, f"{user.display_name} is now {'active' if user.is_active else 'deactivated'}.")
    return redirect(request.POST.get("next") or "adminpanel:passenger_list")


@admin_only
def staff_list(request):
    staff = User.objects.filter(role=User.Role.TT).select_related("tt_profile").prefetch_related("tt_profile__assigned_trains")
    return render(request, "adminpanel/staff_list.html", {"staff": staff.order_by("first_name"), "active_nav": "staff"})


@admin_only
def staff_form(request, pk=None):
    user = get_object_or_404(User, pk=pk, role=User.Role.TT) if pk else None
    form = StaffForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        trains = ", ".join(t.number for t in saved.tt_profile.assigned_trains.all()) or "none"
        _log(request, f"{'Updated' if pk else 'Created'} TT account {saved.username}; trains: {trains}")
        messages.success(request, f"TT account {saved.username} saved.")
        return redirect("adminpanel:staff_list")
    return _form_page(request, form, title=f"Edit {user.display_name}" if user else "Add TT / TTE account",
                      subtitle="Assign trains to control which runs this TT can operate.",
                      back_url=reverse("adminpanel:staff_list"), active_nav="staff",
                      crumbs=[("TT / TTE staff", reverse("adminpanel:staff_list"))])


# ---------------------------------------------------------------------- Bookings
@admin_only
def booking_list(request):
    qs = Booking.objects.select_related("train", "from_stop__station", "to_stop__station", "user")
    f = {k: (request.GET.get(k) or "").strip() for k in ("q", "status", "train", "date", "realloc")}
    if f["q"]:
        qs = qs.filter(Q(pnr__startswith=f["q"]) | Q(user__username__icontains=f["q"]) | Q(passengers__name__icontains=f["q"])).distinct()
    if f["status"] in Booking.Status.values:
        qs = qs.filter(status=f["status"])
    if f["train"].isdigit():
        qs = qs.filter(train_id=int(f["train"]))
    if _parse_date(f["date"]):
        qs = qs.filter(journey_date=_parse_date(f["date"]))
    if f["realloc"] == "1":
        qs = qs.filter(is_reallocated=True)
    return render(request, "adminpanel/booking_list.html", {
        "page_obj": _paginate(request, qs.order_by("-created_at"), 25), "f": f,
        "trains": Train.objects.order_by("number"), "active_nav": "bookings"})


@admin_only
def cancellations(request):
    qs = Cancellation.objects.select_related("booking__train", "booking__from_stop__station",
                                             "booking__to_stop__station", "cancelled_by")
    return render(request, "adminpanel/cancellations.html", {
        "page_obj": _paginate(request, qs.order_by("-created_at"), 25), "active_nav": "cancellations"})


@admin_only
def boarding_monitor(request):
    qs = BoardingStatus.objects.select_related(
        "passenger__booking__train", "passenger__seat__coach", "verified_by", "verified_at_stop__station",
        "passenger__booking__from_stop__station", "passenger__booking__to_stop__station",
    ).filter(passenger__status=Passenger.Status.CONFIRMED)
    status = request.GET.get("status") or "verified"
    if status == "verified":
        qs = qs.exclude(status=BoardingStatus.Status.PENDING)
    elif status in BoardingStatus.Status.values:
        qs = qs.filter(status=status)
    train = request.GET.get("train") or ""
    if train.isdigit():
        qs = qs.filter(passenger__booking__train_id=int(train))
    counts = dict(BoardingStatus.objects.filter(passenger__status="CONFIRMED").values_list("status").annotate(n=Count("id")))
    return render(request, "adminpanel/boarding.html", {
        "page_obj": _paginate(request, qs.order_by("-verified_at", "-id"), 25), "status": status, "train": train,
        "trains": Train.objects.order_by("number"), "counts": counts, "active_nav": "boarding"})


@admin_only
def released(request):
    rows = (
        SeatAllocation.objects.filter(status=SeatAllocation.Status.RELEASED)
        .values("seat__coach__train_id", "seat__coach__train__number", "seat__coach__train__name", "journey_date")
        .annotate(seats=Count("seat_id", distinct=True), passengers=Count("passenger_id", distinct=True))
        .order_by("-journey_date", "seat__coach__train__number")
    )
    runs = []
    for r in rows:
        rebooked = Passenger.objects.filter(is_reallocated_seat=True, booking__train_id=r["seat__coach__train_id"],
                                            booking__journey_date=r["journey_date"], status="CONFIRMED").count()
        runs.append({**r, "rebooked": rebooked,
                     "console": reverse("operations:run_console", args=[r["seat__coach__train_id"], r["journey_date"].isoformat()])})
    return render(request, "adminpanel/released.html", {"runs": runs, "active_nav": "released"})


@admin_only
def allocation(request):
    today = timezone.localdate()
    trains = Train.objects.filter(is_active=True).order_by("number")
    train = (trains.filter(pk=request.GET.get("train") or 0).first()
             or trains.filter(number="24051").first() or trains.first())
    date = _parse_date(request.GET.get("date"), today)
    stops = list(train.get_stops()) if train else []
    coaches = train.coaches.filter(is_active=True).order_by("position") if train else []
    return render(request, "adminpanel/allocation.html", {
        "trains": trains, "train": train, "date": date, "stops": stops, "coaches": coaches,
        "config": {"train": train.pk if train else None, "date": date.isoformat(),
                   "matrix": reverse("api:seat_matrix"), "check": reverse("api:allocation_check")},
        "active_nav": "allocation"})


@admin_only
def simulation(request):
    date = _parse_date(request.GET.get("date"), timezone.localdate())
    rows = []
    for t in Train.objects.filter(is_active=True).order_by("number"):
        sim = TrainSimulation.objects.filter(train=t, journey_date=date).first()
        stops = list(t.get_stops())
        rows.append({"train": t, "sim": sim, "runs": t.runs_on(date), "stops": stops,
                     "current": stops[sim.current_index] if sim and sim.is_running and stops else None,
                     "bookings": Booking.objects.filter(train=t, journey_date=date, status="CONFIRMED").count(),
                     "url": reverse("operations:run_console", args=[t.pk, date.isoformat()])})
    recent = TrainSimulation.objects.select_related("train").exclude(status="SCHEDULED").order_by("-updated_at")[:8]
    return render(request, "adminpanel/simulation.html", {"rows": rows, "date": date, "recent": recent,
                                                          "active_nav": "simulation"})


@admin_only
def activity(request):
    qs = ActivityLog.objects.select_related("actor", "train", "booking")
    category = request.GET.get("category") or ""
    q = (request.GET.get("q") or "").strip()
    if category in ActivityLog.Category.values:
        qs = qs.filter(category=category)
    if q:
        qs = qs.filter(Q(description__icontains=q) | Q(actor__username__icontains=q))
    return render(request, "adminpanel/activity.html", {
        "page_obj": _paginate(request, qs, 30), "category": category, "q": q,
        "categories": ActivityLog.Category.choices, "active_nav": "activity"})
