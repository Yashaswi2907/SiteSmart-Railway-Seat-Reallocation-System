"""Administrator analytics and allocation-inspection endpoints."""
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.adminpanel.services import dashboard_stats, seat_matrix
from apps.api.permissions import IsPortalAdmin
from apps.bookings.exceptions import TrainDepartedError
from apps.bookings.services.availability import build_journey_context, check_seat_availability, seat_segment_timeline
from apps.railway.models import Seat

from .common import get_train, int_param, journey_params
from .operations import _parse_date


class AdminStatsView(APIView):
    permission_classes = [IsPortalAdmin]

    def get(self, request):
        stats = dashboard_stats()
        stats["recent_activity"] = [
            {"when": a.created_at.isoformat(), "action": a.get_action_display(), "category": a.category,
             "description": a.description, "actor": a.actor.display_name if a.actor else "System"}
            for a in stats["recent_activity"]
        ]
        return Response(stats)


class AllocationCheckView(APIView):
    """Explain whether a specific seat can take a specific journey — the viva 'what-if' tool."""

    permission_classes = [IsPortalAdmin]

    def get(self, request):
        train = get_train(int_param(request, "train", required=True))
        params = journey_params(request)
        seat = get_object_or_404(Seat.objects.select_related("coach__train"),
                                 pk=int_param(request, "seat", required=True), coach__train=train)
        position_ok, position_msg = True, ""
        try:
            ctx = build_journey_context(train, params["date"], params["from_code"], params["to_code"],
                                        enforce_schedule=False)
        except TrainDepartedError as exc:
            position_ok, position_msg = False, exc.message
            ctx = build_journey_context(train, params["date"], params["from_code"], params["to_code"],
                                        enforce_schedule=False, enforce_position=False)
        check = check_seat_availability(seat, ctx.journey_date, ctx.from_index, ctx.to_index, stops=ctx.stops)
        bookable = check.available and position_ok
        return Response({
            "seat": f"{seat.coach.coach_number}-{seat.seat_number}",
            "journey": f"{ctx.from_stop.station.code} → {ctx.to_stop.station.code}",
            "requested_segments": [f"{ctx.stops[i].station.code}→{ctx.stops[i + 1].station.code}"
                                   for i in ctx.segments],
            "requested_indices": list(ctx.segments),
            "occupancy_ok": check.available,
            "position_ok": position_ok,
            "bookable": bookable,
            "verdict": ("Allowed — every requested segment is free and still ahead of the train."
                        if bookable else (check.reason if not check.available else position_msg)),
            "conflicts": check.conflicts,
            "timeline": seat_segment_timeline(seat, ctx.journey_date, ctx.stops, ctx.min_boardable),
        })


class SeatMatrixView(APIView):
    permission_classes = [IsPortalAdmin]

    def get(self, request):
        train = get_train(int_param(request, "train", required=True))
        date = _parse_date(request.query_params.get("date", ""))
        return Response(seat_matrix(train, date, int_param(request, "coach")))
