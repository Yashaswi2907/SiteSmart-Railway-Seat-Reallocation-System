"""Passenger-facing pages: dashboard, booking wizard, bookings, tickets, PNR status."""
import datetime as dt
from collections import Counter, OrderedDict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.bookings.exceptions import AllocationError
from apps.core.permissions import role_required
from apps.railway.constants import BerthType, class_label
from apps.railway.models import Train
from apps.railway.services import format_duration, journey_minutes

from .models import Booking
from .services.availability import build_journey_context, class_availability
from .services.cancellation import cancellation_eligibility
from .services.fares import calculate_fare, refund_terms
from .services.pnr import verify_ticket_signature
from .services.status import JourneyState, annotate_states, booking_journey_state
from .services.tickets import qr_png_bytes, render_ticket_pdf, ticket_qr_payload


def _bookings_for(user):
    return (
        Booking.objects.filter(user=user)
        .select_related("train", "from_stop__station", "to_stop__station")
        .prefetch_related("passengers__boarding", "passengers__seat__coach")
    )


# ---------------------------------------------------------------- Dashboard
@role_required("PASSENGER")
def passenger_dashboard(request):
    bookings = annotate_states(list(_bookings_for(request.user)))
    counts = Counter(b.journey_state for b in bookings)
    upcoming = sorted(
        [b for b in bookings if b.journey_state in (JourneyState.UPCOMING, JourneyState.IN_PROGRESS)],
        key=lambda b: (b.journey_date, b.from_stop.departure_time or dt.time(0)),
    )
    # Spend over the last six months (confirmed bookings only).
    today = timezone.localdate()
    months = OrderedDict()
    for i in range(5, -1, -1):
        y, m = today.year, today.month - i
        while m <= 0:
            m += 12
            y -= 1
        months[(y, m)] = 0
    for b in bookings:
        key = (b.created_at.year, b.created_at.month)
        if key in months and b.status == Booking.Status.CONFIRMED:
            months[key] += float(b.total_fare)
    chart = {
        "status": {
            "labels": ["Upcoming", "On journey", "Completed", "Did not board", "Cancelled"],
            "values": [counts[JourneyState.UPCOMING], counts[JourneyState.IN_PROGRESS], counts[JourneyState.COMPLETED],
                       counts[JourneyState.NO_SHOW], counts[JourneyState.CANCELLED]],
        },
        "spend": {
            "labels": [dt.date(y, m, 1).strftime("%b") for (y, m) in months],
            "values": list(months.values()),
        },
    }
    return render(request, "bookings/dashboard.html", {
        "stats": {
            "total": len(bookings),
            "upcoming": counts[JourneyState.UPCOMING] + counts[JourneyState.IN_PROGRESS],
            "completed": counts[JourneyState.COMPLETED] + counts[JourneyState.NO_SHOW],
            "cancelled": counts[JourneyState.CANCELLED],
            "reallocated": sum(1 for b in bookings if b.is_reallocated),
            "spent": sum(b.total_fare for b in bookings if b.status == Booking.Status.CONFIRMED),
        },
        "upcoming": upcoming[:4],
        "recent": bookings[:5],
        "chart": chart,
        "active_nav": "passenger_dashboard",
    })


# ---------------------------------------------------------------- Booking wizard
@role_required("PASSENGER")
def book(request, train_id):
    train = get_object_or_404(Train, pk=train_id, is_active=True)
    qp = request.GET
    search_url = reverse("railway:search") + "?" + qp.urlencode()
    try:
        journey_date = dt.date.fromisoformat(qp.get("date", ""))
        ctx = build_journey_context(train, journey_date, (qp.get("from") or "").upper(), (qp.get("to") or "").upper())
    except ValueError:
        messages.error(request, "Choose a valid journey date to continue.")
        return redirect(search_url)
    except AllocationError as exc:
        messages.error(request, exc.message)
        return redirect(search_url)

    availability = class_availability(train, journey_date, ctx.from_index, ctx.to_index)
    classes = [
        {"code": c, "label": class_label(c), "fare": int(calculate_fare(c, ctx.distance_km)), **availability[c]}
        for c in train.available_classes() if c in availability
    ]
    try:
        pax = max(1, min(int(qp.get("passengers") or 1), 6))
    except ValueError:
        pax = 1
    selected_class = qp.get("class") if qp.get("class") in {c["code"] for c in classes} else (classes[0]["code"] if classes else "")
    profile = getattr(request.user, "passenger_profile", None)
    config = {
        "trainId": train.pk,
        "trainNumber": train.number,
        "trainName": train.name,
        "date": journey_date.isoformat(),
        "dateLabel": journey_date.strftime("%a, %d %b %Y"),
        "from": {"code": ctx.from_stop.station.code, "name": ctx.from_stop.station.name,
                 "time": ctx.from_stop.departure_time.strftime("%H:%M") if ctx.from_stop.departure_time else ""},
        "to": {"code": ctx.to_stop.station.code, "name": ctx.to_stop.station.name,
               "time": ctx.to_stop.arrival_time.strftime("%H:%M") if ctx.to_stop.arrival_time else ""},
        "distance": ctx.distance_km,
        "duration": format_duration(journey_minutes(journey_date, ctx.from_stop, ctx.to_stop)),
        "classes": classes,
        "selectedClass": selected_class,
        "passengers": pax,
        "maxPassengers": 6,
        "user": {
            "name": request.user.get_full_name(),
            "email": request.user.email,
            "phone": request.user.phone,
            "gender": getattr(profile, "gender", "") or "",
            "age": ((timezone.localdate() - profile.date_of_birth).days // 365) if profile and profile.date_of_birth else "",
            "berth": getattr(profile, "preferred_berth", "") or "",
        },
        "berths": [{"code": c, "label": l} for c, l in BerthType.choices],
        "urls": {
            "coaches": reverse("api:coaches", args=[train.pk]),
            "seatMap": reverse("api:seat_map", args=[train.pk]),
            "suggest": reverse("api:suggest_seats", args=[train.pk]),
            "create": reverse("api:bookings"),
            "search": search_url,
        },
    }
    return render(request, "bookings/book.html", {
        "train": train, "ctx": ctx, "config": config, "active_nav": "search",
        "intermediate": ctx.stops[ctx.from_index:ctx.to_index + 1],
    })


# ---------------------------------------------------------------- Lists & detail
@role_required("PASSENGER")
def my_bookings(request):
    tab = request.GET.get("tab", "upcoming")
    q = (request.GET.get("q") or "").strip()
    bookings = _bookings_for(request.user)
    if q:
        bookings = bookings.filter(Q(pnr__startswith=q) | Q(passengers__name__icontains=q)
                                   | Q(train__number__startswith=q)).distinct()
    bookings = annotate_states(list(bookings))
    groups = {
        "upcoming": [b for b in bookings if b.journey_state in (JourneyState.UPCOMING, JourneyState.IN_PROGRESS)],
        "completed": [b for b in bookings if b.journey_state in (JourneyState.COMPLETED, JourneyState.NO_SHOW)],
        "cancelled": [b for b in bookings if b.journey_state == JourneyState.CANCELLED],
        "all": bookings,
    }
    if tab not in groups:
        tab = "upcoming"
    rows = groups[tab]
    if tab == "upcoming":
        rows = sorted(rows, key=lambda b: b.journey_date)
    page = Paginator(rows, 10).get_page(request.GET.get("page"))
    return render(request, "bookings/my_bookings.html", {
        "page_obj": page, "tab": tab, "q": q, "counts": {k: len(v) for k, v in groups.items()},
        "active_nav": "my_bookings",
    })


def _get_visible_booking(request, pnr) -> Booking:
    booking = get_object_or_404(
        Booking.objects.select_related("train", "from_stop__station", "to_stop__station", "user")
        .prefetch_related("passengers__seat__coach", "passengers__boarding__verified_by"),
        pnr=pnr,
    )
    if not (request.user.is_portal_admin or booking.user_id == request.user.pk):
        raise Http404("Booking not found")
    return booking


@login_required
def booking_detail(request, pnr):
    booking = _get_visible_booking(request, pnr)
    from .services.availability import get_route_stops, get_simulation

    sim = get_simulation(booking.train, booking.journey_date)
    state = booking_journey_state(booking, sim)
    can_cancel, cancel_reason = cancellation_eligibility(booking, sim)
    charge, refund = refund_terms(booking.coach_class, booking.total_fare, booking.passenger_count,
                                  booking.journey_date, timezone.localdate())
    stops = get_route_stops(booking.train)
    journey_stops = stops[booking.from_index:booking.to_index + 1]
    return render(request, "bookings/booking_detail.html", {
        "booking": booking,
        "sim": sim,
        "state": state,
        "state_label": JourneyState.LABELS[state][0],
        "state_tone": JourneyState.LABELS[state][1],
        "can_cancel": can_cancel,
        "cancel_reason": cancel_reason,
        "refund_preview": {"charge": charge, "refund": refund},
        "journey_stops": journey_stops,
        "duration": format_duration(journey_minutes(booking.journey_date, booking.from_stop, booking.to_stop)),
        "is_new": request.GET.get("new") == "1",
        "distance": booking.to_stop.distance_km - booking.from_stop.distance_km,
        "active_nav": "bookings" if request.user.is_portal_admin else "my_bookings",
        "run_api": reverse("api:run_position", args=[booking.train_id, booking.journey_date.isoformat()]),
        "fare_per_head": booking.passengers.first().fare if booking.passengers.exists() else 0,
    })


@login_required
def ticket(request, pnr):
    booking = _get_visible_booking(request, pnr)
    return render(request, "bookings/ticket.html", {
        "booking": booking,
        "verify_url": ticket_qr_payload(booking, request),
        "duration": format_duration(journey_minutes(booking.journey_date, booking.from_stop, booking.to_stop)),
        "active_nav": "my_bookings",
    })


@login_required
@require_GET
def ticket_pdf(request, pnr):
    booking = _get_visible_booking(request, pnr)
    pdf = render_ticket_pdf(booking, request)
    response = HttpResponse(pdf, content_type="application/pdf")
    disposition = "inline" if request.GET.get("inline") else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="SiteSmart-ticket-{booking.pnr}.pdf"'
    return response


@login_required
@require_GET
def ticket_qr(request, pnr):
    booking = _get_visible_booking(request, pnr)
    response = HttpResponse(qr_png_bytes(ticket_qr_payload(booking, request)), content_type="image/png")
    response["Cache-Control"] = "private, max-age=3600"
    return response


def _mask(name: str) -> str:
    return " ".join(part[0] + "•" * max(len(part) - 1, 1) for part in name.split())


def verify_ticket(request, pnr, signature):
    """Public QR target: confirms the ticket is genuine without exposing personal data."""
    valid = verify_ticket_signature(pnr, signature)
    booking = None
    if valid:
        booking = (
            Booking.objects.select_related("train", "from_stop__station", "to_stop__station")
            .prefetch_related("passengers__seat__coach", "passengers__boarding").filter(pnr=pnr).first()
        )
        valid = booking is not None
    passengers = []
    if booking:
        for p in booking.passengers.all():
            passengers.append({"name": _mask(p.name), "age": p.age, "seat": p.seat.label, "status": p.status,
                               "boarding": getattr(p, "boarding", None)})
    return render(request, "bookings/verify_ticket.html", {
        "valid": valid, "booking": booking, "passengers": passengers, "pnr": pnr,
        "state_label": JourneyState.LABELS[booking_journey_state(booking)][0] if booking else "",
    })


def pnr_status(request):
    pnr = (request.GET.get("pnr") or "").strip()
    booking, error = None, ""
    if pnr:
        if not (pnr.isdigit() and len(pnr) == 10):
            error = "A PNR is a 10-digit number."
        else:
            booking = (
                Booking.objects.select_related("train", "from_stop__station", "to_stop__station")
                .prefetch_related("passengers__seat__coach", "passengers__boarding").filter(pnr=pnr).first()
            )
            if booking is None:
                error = "No booking was found with that PNR."
    state = booking_journey_state(booking) if booking else None
    use_app_layout = request.user.is_authenticated and request.user.is_passenger
    return render(request, "bookings/pnr_status.html", {
        "pnr": pnr, "booking": booking, "error": error,
        "state_label": JourneyState.LABELS[state][0] if state else "",
        "state_tone": JourneyState.LABELS[state][1] if state else "",
        "layout": "layouts/app.html" if use_app_layout else "layouts/public.html",
        "active_nav": "pnr",
        "is_owner": booking is not None and request.user.is_authenticated and booking.user_id == request.user.pk,
    })

