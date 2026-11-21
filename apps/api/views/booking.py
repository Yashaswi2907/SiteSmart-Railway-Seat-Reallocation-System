"""Passenger booking endpoints: coaches, seat map, seat suggestion, create, cancel."""
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.permissions import IsPassenger
from apps.api.presenters import booking_summary
from apps.api.serializers import BookingCreateSerializer, CancelSerializer
from apps.bookings.exceptions import InvalidJourneyError
from apps.bookings.models import Booking
from apps.bookings.services.availability import (
    bookable_seats_qs,
    build_journey_context,
    find_eligible_seats,
    occupied_segments,
    released_seat_ids,
)
from apps.bookings.services.cancellation import cancel_booking
from apps.bookings.services.fares import calculate_fare
from apps.bookings.services.reservation import reserve_seats
from apps.bookings.services.status import annotate_states
from apps.railway.constants import CLASS_LAYOUTS, class_label

from .common import get_train, int_param, journey_params


def _context(request, train):
    p = journey_params(request)
    ctx = build_journey_context(train, p["date"], p["from_code"], p["to_code"])
    return ctx


class CoachAvailabilityView(APIView):
    """Coaches of a train (optionally one class) with free seats for the requested journey."""

    permission_classes = [IsAuthenticated]

    def get(self, request, train_id):
        train = get_train(train_id)
        ctx = _context(request, train)
        coach_class = request.query_params.get("class") or None
        blocked = occupied_segments(ctx.journey_date, train=train, from_index=ctx.from_index, to_index=ctx.to_index)
        released = released_seat_ids(train, ctx.journey_date, ctx.from_index, ctx.to_index)
        coaches: dict[int, dict] = {}
        for seat in bookable_seats_qs(train, coach_class=coach_class):
            c = seat.coach
            row = coaches.setdefault(c.pk, {
                "id": c.pk, "number": c.coach_number, "coach_class": c.coach_class,
                "class_label": class_label(c.coach_class), "position": c.position,
                "total": 0, "available": 0, "reallocated": 0,
            })
            row["total"] += 1
            if seat.id not in blocked:
                row["available"] += 1
                if seat.id in released:
                    row["reallocated"] += 1
        classes = sorted({c["coach_class"] for c in coaches.values()})
        return Response({
            "journey": {
                "from_code": ctx.from_stop.station.code, "from_name": ctx.from_stop.station.name,
                "to_code": ctx.to_stop.station.code, "to_name": ctx.to_stop.station.name,
                "date": ctx.journey_date.isoformat(), "distance_km": ctx.distance_km,
            },
            "fares": {c: int(calculate_fare(c, ctx.distance_km)) for c in classes},
            "coaches": sorted(coaches.values(), key=lambda r: (r["position"], r["number"])),
        })


class SeatMapView(APIView):
    """Seat-by-seat availability of one coach for the requested journey segment range."""

    permission_classes = [IsAuthenticated]

    def get(self, request, train_id):
        train = get_train(train_id)
        ctx = _context(request, train)
        coach_id = int_param(request, "coach", required=True)
        seats = list(bookable_seats_qs(train, coach_id=coach_id))
        if not seats:
            raise InvalidJourneyError("That coach does not exist on this train.", code="coach_not_found")
        coach = seats[0].coach
        seat_ids = [s.id for s in seats]
        in_range = occupied_segments(ctx.journey_date, seat_ids=seat_ids, from_index=ctx.from_index,
                                     to_index=ctx.to_index)
        released = released_seat_ids(train, ctx.journey_date, ctx.from_index, ctx.to_index)
        codes = {s.sequence: s.station.code for s in ctx.stops}
        payload = []
        for s in seats:
            busy = sorted(in_range.get(s.id, []))
            if busy:
                state = "booked"
            elif s.id in released:
                state = "reallocated"
            else:
                state = "available"
            payload.append({
                "id": s.id,
                "number": s.seat_number,
                "berth": s.berth_type,
                "berth_label": s.get_berth_type_display(),
                "state": state,
                "occupied_on": [f"{codes[i]}→{codes[i + 1]}" for i in busy],
            })
        return Response({
            "coach": {"id": coach.pk, "number": coach.coach_number, "coach_class": coach.coach_class,
                      "kind": CLASS_LAYOUTS[coach.coach_class]["kind"],
                      "bay_size": len(CLASS_LAYOUTS[coach.coach_class]["pattern"])},
            "seats": payload,
            "counts": {
                "available": sum(1 for p in payload if p["state"] != "booked"),
                "reallocated": sum(1 for p in payload if p["state"] == "reallocated"),
                "booked": sum(1 for p in payload if p["state"] == "booked"),
            },
        })


class SuggestSeatsView(APIView):
    """Best-fit automatic seat choice (same algorithm the booking service uses)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, train_id):
        train = get_train(train_id)
        ctx = _context(request, train)
        count = max(1, min(int_param(request, "count", 1), 6))
        coach_class = request.query_params.get("class")
        if not coach_class:
            raise InvalidJourneyError("Choose a class first.", code="class_required")
        prefs = [p for p in request.query_params.get("prefs", "").split(",") if p][:count]
        seats = find_eligible_seats(ctx, coach_class, count, berth_preferences=prefs,
                                    coach_id=int_param(request, "coach"))
        return Response({"seats": [{"id": s.id, "coach_id": s.coach_id, "coach": s.coach.coach_number,
                                    "number": s.seat_number, "berth": s.berth_type} for s in seats]})


class BookingListCreateView(APIView):
    def get_permissions(self):
        return [IsPassenger()]

    def get(self, request):
        bookings = list(
            Booking.objects.filter(user=request.user)
            .select_related("train", "from_stop__station", "to_stop__station")
            .prefetch_related("passengers__boarding")[:100]
        )
        annotate_states(bookings)
        return Response({"results": [booking_summary(b) for b in bookings]})

    def post(self, request):
        s = BookingCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        train = get_train(d["train_id"])
        booking = reserve_seats(
            user=request.user,
            train=train,
            journey_date=d["journey_date"],
            from_stop=d["from_code"].upper(),
            to_stop=d["to_code"].upper(),
            coach_class=d["coach_class"],
            passengers=[dict(p) for p in d["passengers"]],
            seat_ids=d.get("seat_ids") or None,
            contact_email=d.get("contact_email") or None,
            contact_phone=d.get("contact_phone") or "",
            request=request,
        )
        return Response(
            {
                "pnr": booking.pnr,
                "total_fare": str(booking.total_fare),
                "is_reallocated": booking.is_reallocated,
                "seats": [p.seat.label for p in booking.passengers.select_related("seat__coach")],
                "redirect_url": reverse("bookings:booking_detail", args=[booking.pnr]) + "?new=1",
            },
            status=status.HTTP_201_CREATED,
        )


class BookingCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pnr):
        booking = get_object_or_404(Booking, pnr=pnr)
        if not (request.user.is_portal_admin or booking.user_id == request.user.pk):
            # Do not reveal that the PNR exists.
            return Response({"error": {"code": "not_found", "message": "Booking not found.", "details": {}}},
                            status=status.HTTP_404_NOT_FOUND)
        s = CancelSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        cancellation = cancel_booking(booking, request.user, reason=s.validated_data["reason"], request=request)
        return Response({
            "pnr": booking.pnr,
            "status": "CANCELLED",
            "refund_amount": str(cancellation.refund_amount),
            "cancellation_charge": str(cancellation.cancellation_charge),
            "segments_released": cancellation.segments_released,
        })
