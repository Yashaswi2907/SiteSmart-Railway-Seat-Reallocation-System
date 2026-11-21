"""TT/TTE and administrator run-console endpoints."""
import datetime as dt

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.permissions import IsTTOrAdmin
from apps.api.presenters import booking_summary, passenger_row
from apps.api.serializers import SimulationControlSerializer, VerifySerializer
from apps.bookings.models import BoardingStatus, Booking, Passenger, SeatAllocation
from apps.bookings.services.availability import get_route_stops, released_seats_report
from apps.bookings.services.boarding import mark_passenger_boarded, process_no_show, user_can_operate_train
from apps.operations.models import TrainSimulation
from apps.operations.services.simulation import (
    advance_simulation,
    apply_auto_advance,
    get_or_create_simulation,
    set_auto_advance,
    set_paused,
    simulation_snapshot,
    start_simulation,
)
from apps.railway.constants import CLASS_LAYOUTS
from apps.railway.models import Seat

from .common import get_operable_train, get_train, int_param


def _parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise ValidationError({"date": "Use YYYY-MM-DD."}) from None


def _run_passengers(train, journey_date):
    return (
        Passenger.objects.filter(
            booking__train=train, booking__journey_date=journey_date,
            booking__status=Booking.Status.CONFIRMED, status=Passenger.Status.CONFIRMED,
        )
        .select_related("booking__from_stop__station", "booking__to_stop__station", "booking__train",
                        "seat__coach", "boarding__verified_by")
        .order_by("seat__coach__position", "seat__seat_number", "booking__from_index")
    )


def run_stats(train, journey_date, simulation) -> dict:
    qs = Passenger.objects.filter(
        booking__train=train, booking__journey_date=journey_date,
        booking__status=Booking.Status.CONFIRMED, status=Passenger.Status.CONFIRMED,
    )
    agg = qs.aggregate(
        total=Count("id"),
        boarded=Count("id", filter=Q(boarding__status=BoardingStatus.Status.BOARDED)),
        not_boarded=Count("id", filter=Q(boarding__status=BoardingStatus.Status.NOT_BOARDED)),
        reallocated=Count("id", filter=Q(is_reallocated_seat=True)),
    )
    agg["pending"] = agg["total"] - agg["boarded"] - agg["not_boarded"]
    agg["released_seats"] = (
        SeatAllocation.objects.filter(journey_date=journey_date, status=SeatAllocation.Status.RELEASED,
                                      seat__coach__train=train)
        .values("seat_id").distinct().count()
    )
    if simulation and simulation.is_running:
        cur = simulation.current_index
        agg["boarding_here"] = qs.filter(booking__from_index=cur).count()
        agg["pending_here"] = qs.filter(booking__from_index__lte=cur, booking__to_index__gt=cur,
                                        boarding__status=BoardingStatus.Status.PENDING).count()
    else:
        agg["boarding_here"] = agg["pending_here"] = 0
    seat_total = Seat.objects.filter(coach__train=train, is_active=True, coach__is_active=True).count()
    segments = max(len(get_route_stops(train)) - 1, 1)
    used = SeatAllocation.objects.filter(journey_date=journey_date, status=SeatAllocation.Status.ACTIVE,
                                         seat__coach__train=train).count()
    agg["seat_total"] = seat_total
    agg["utilisation"] = round(used / (seat_total * segments) * 100, 1) if seat_total else 0
    return agg


class RunPositionView(APIView):
    """Live simulated position — any signed-in user (passengers track their train)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, train_id, date):
        train = get_train(train_id)
        journey_date = _parse_date(date)
        sim = TrainSimulation.objects.filter(train=train, journey_date=journey_date).first()
        if sim:
            sim = apply_auto_advance(sim)
        return Response(simulation_snapshot(sim, train, journey_date))


class RunConsoleView(APIView):
    permission_classes = [IsTTOrAdmin]

    def get(self, request, train_id, date):
        train = get_operable_train(request, train_id)
        journey_date = _parse_date(date)
        sim = TrainSimulation.objects.filter(train=train, journey_date=journey_date).first()
        if sim:
            sim = apply_auto_advance(sim)
        return Response({
            "simulation": simulation_snapshot(sim, train, journey_date),
            "stats": run_stats(train, journey_date, sim),
            "coaches": [{"id": c.pk, "number": c.coach_number, "coach_class": c.coach_class}
                        for c in train.coaches.filter(is_active=True).order_by("position")],
        })


class RunControlView(APIView):
    permission_classes = [IsTTOrAdmin]

    def post(self, request, train_id, date):
        train = get_operable_train(request, train_id)
        journey_date = _parse_date(date)
        s = SimulationControlSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        action = s.validated_data["action"]
        sim = get_or_create_simulation(train, journey_date)
        if action == "start":
            sim = start_simulation(sim, request.user, request=request)
        elif action in ("pause", "resume"):
            sim = set_paused(sim, request.user, action == "pause", request=request)
        elif action == "step":
            sim = advance_simulation(sim, request.user, request=request)
        elif action == "next_station":
            sim = advance_simulation(sim, request.user, to_next_station=True, request=request)
        else:
            sim = set_auto_advance(sim, request.user, action == "auto_on", s.validated_data.get("interval"))
        return Response({
            "simulation": simulation_snapshot(sim, train, journey_date),
            "stats": run_stats(train, journey_date, sim),
        })


class RunPassengersView(APIView):
    permission_classes = [IsTTOrAdmin]

    def get(self, request, train_id, date):
        train = get_operable_train(request, train_id)
        journey_date = _parse_date(date)
        sim = TrainSimulation.objects.filter(train=train, journey_date=journey_date).first()
        stops = get_route_stops(train)
        qs = _run_passengers(train, journey_date)
        coach_id = int_param(request, "coach")
        if coach_id:
            qs = qs.filter(seat__coach_id=coach_id)
        status = request.query_params.get("status")
        if status in BoardingStatus.Status.values:
            qs = qs.filter(boarding__status=status)
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(booking__pnr__startswith=q) | Q(name__icontains=q))
        scope = request.query_params.get("scope")
        if scope == "here" and sim and sim.is_running:
            qs = qs.filter(booking__from_index=sim.current_index)
        elif scope == "onboard" and sim and sim.is_running:
            qs = qs.filter(booking__from_index__lte=sim.current_index, booking__to_index__gt=sim.current_index)
        rows = [passenger_row(p, sim, stops) for p in qs[:400]]
        return Response({"count": len(rows), "results": rows})


class RunOccupancyView(APIView):
    """Seat states of one coach on a single segment (default: the segment the train is on/next)."""

    permission_classes = [IsTTOrAdmin]

    def get(self, request, train_id, date):
        train = get_operable_train(request, train_id)
        journey_date = _parse_date(date)
        stops = get_route_stops(train)
        last_seg = max(len(stops) - 2, 0)
        sim = TrainSimulation.objects.filter(train=train, journey_date=journey_date).first()
        default_seg = 0
        if sim and sim.status == TrainSimulation.Status.COMPLETED:
            default_seg = last_seg
        elif sim:
            default_seg = min(sim.current_index, last_seg)
        segment = min(max(int_param(request, "segment", default_seg), 0), last_seg)
        coach_id = int_param(request, "coach")
        coaches = train.coaches.filter(is_active=True).order_by("position")
        coach = coaches.filter(pk=coach_id).first() if coach_id else coaches.first()
        if coach is None:
            return Response({"coach": None, "seats": [], "segment": segment})
        allocs = (
            SeatAllocation.objects.filter(seat__coach=coach, journey_date=journey_date, segment_index=segment)
            .exclude(status=SeatAllocation.Status.CANCELLED)
            .select_related("passenger__booking", "passenger__boarding")
        )
        active, released = {}, {}
        for a in allocs:
            (active if a.status == SeatAllocation.Status.ACTIVE else released)[a.seat_id] = a
        seats = []
        for seat in coach.seats.filter(is_active=True).order_by("seat_number"):
            a = active.get(seat.id)
            if a:
                b_status = getattr(a.passenger.boarding, "status", "PENDING")
                state = "occupied" if b_status == BoardingStatus.Status.BOARDED else "reserved"
                if a.passenger.is_reallocated_seat:
                    state += "-realloc"
                info = {"pnr": a.passenger.booking.pnr, "name": a.passenger.name,
                        "journey": f"{stops[a.passenger.booking.from_index].station.code}→"
                                   f"{stops[a.passenger.booking.to_index].station.code}"}
            elif seat.id in released:
                state, info = "released", {"pnr": released[seat.id].passenger.booking.pnr}
            else:
                state, info = "vacant", {}
            seats.append({"id": seat.id, "number": seat.seat_number, "berth": seat.berth_type,
                          "state": state, **info})
        return Response({
            "coach": {"id": coach.pk, "number": coach.coach_number, "coach_class": coach.coach_class,
                      "kind": CLASS_LAYOUTS[coach.coach_class]["kind"],
                      "bay_size": len(CLASS_LAYOUTS[coach.coach_class]["pattern"])},
            "segment": segment,
            "segment_label": f"{stops[segment].station.name} → {stops[segment + 1].station.name}" if len(stops) > 1 else "",
            "segments": [{"index": i, "label": f"{stops[i].station.code}→{stops[i + 1].station.code}"}
                         for i in range(len(stops) - 1)],
            "seats": seats,
        })


class RunReleasedView(APIView):
    permission_classes = [IsTTOrAdmin]

    def get(self, request, train_id, date):
        train = get_operable_train(request, train_id)
        report = released_seats_report(train, _parse_date(date))
        for row in report:
            for ns in row["no_shows"]:
                ns["released_at"] = ns["released_at"].isoformat() if ns["released_at"] else None
        return Response({"count": len(report), "results": report})


class VerifyPassengerView(APIView):
    permission_classes = [IsTTOrAdmin]

    def post(self, request, passenger_id):
        passenger = get_object_or_404(Passenger.objects.select_related("booking__train"), pk=passenger_id)
        if not user_can_operate_train(request.user, passenger.booking.train):
            return Response({"error": {"code": "permission_denied",
                                       "message": "You are not assigned to this train.", "details": {}}},
                            status=403)
        s = VerifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if s.validated_data["status"] == "BOARDED":
            mark_passenger_boarded(passenger, request.user, remarks=s.validated_data["remarks"], request=request)
            result = {"message": f"{passenger.name} marked as boarded."}
        else:
            outcome = process_no_show(passenger, request.user, remarks=s.validated_data["remarks"], request=request)
            ranges = ", ".join(outcome["released_ranges"]) or "no remaining segments"
            result = {"message": f"{passenger.name} marked as did not board. Seat {outcome['seat']} "
                                 f"released for {ranges}.", **outcome}
        passenger.refresh_from_db()
        sim = TrainSimulation.objects.filter(train=passenger.booking.train,
                                             journey_date=passenger.booking.journey_date).first()
        p = _run_passengers(passenger.booking.train, passenger.booking.journey_date).get(pk=passenger.pk)
        result["passenger"] = passenger_row(p, sim, get_route_stops(passenger.booking.train))
        return Response(result)


class TTPnrLookupView(APIView):
    permission_classes = [IsTTOrAdmin]

    def get(self, request, pnr):
        booking = get_object_or_404(
            Booking.objects.select_related("train", "from_stop__station", "to_stop__station"), pnr=pnr.strip()
        )
        if not user_can_operate_train(request.user, booking.train):
            return Response({"error": {"code": "permission_denied",
                                       "message": "This PNR belongs to a train you are not assigned to.",
                                       "details": {}}}, status=403)
        sim = TrainSimulation.objects.filter(train=booking.train, journey_date=booking.journey_date).first()
        stops = get_route_stops(booking.train)
        passengers = (
            _run_passengers(booking.train, booking.journey_date).filter(booking=booking)
        )
        return Response({
            "booking": booking_summary(booking, sim),
            "run_url": reverse("operations:run_console", args=[booking.train_id, booking.journey_date.isoformat()]),
            "passengers": [passenger_row(p, sim, stops) for p in passengers],
        })
