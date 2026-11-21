"""Public endpoints: station lookup, train search, PNR status."""
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.api.presenters import search_result_dict, station_dict
from apps.api.serializers import SearchQuerySerializer
from apps.bookings.models import Booking
from apps.bookings.services.status import JourneyState, booking_journey_state
from apps.railway.services import search_trains, suggest_stations


class PublicThrottle(AnonRateThrottle):
    rate = "120/minute"


class StationListView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [PublicThrottle]

    def get(self, request):
        stations = suggest_stations(request.query_params.get("q", ""), limit=15)
        return Response({"results": [station_dict(s) for s in stations]})


class TrainSearchView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [PublicThrottle]

    def get(self, request):
        qp = request.query_params
        s = SearchQuerySerializer(data={
            "from_code": qp.get("from", ""), "to_code": qp.get("to", ""), "date": qp.get("date"),
            "coach_class": qp.get("class", ""), "passengers": qp.get("passengers") or 1,
        })
        s.is_valid(raise_exception=True)
        d = s.validated_data
        results = search_trains(d["from_code"], d["to_code"], d["date"], d.get("coach_class") or None, d["passengers"])
        return Response({
            "query": {**d, "date": d["date"].isoformat()},
            "count": len(results),
            "results": [search_result_dict(r) for r in results],
        })


class PNRStatusView(APIView):
    """Public PNR enquiry. Shows seat status but never passenger names."""

    permission_classes = [AllowAny]
    throttle_classes = [PublicThrottle]

    def get(self, request, pnr):
        booking = get_object_or_404(
            Booking.objects.select_related("train", "from_stop__station", "to_stop__station"), pnr=pnr
        )
        state = booking_journey_state(booking)
        return Response({
            "pnr": booking.pnr,
            "train": f"{booking.train.number} {booking.train.name}",
            "journey_date": booking.journey_date.isoformat(),
            "from": booking.from_stop.station.name,
            "to": booking.to_stop.station.name,
            "class": booking.coach_class,
            "booking_status": booking.get_status_display(),
            "journey_state": JourneyState.LABELS[state][0],
            "passengers": [
                {
                    "number": i,
                    "coach": p.seat.coach.coach_number,
                    "seat": p.seat.seat_number,
                    "berth": p.seat.berth_type,
                    "status": "CNF" if p.status == "CONFIRMED" else "CAN",
                    "boarding": p.boarding.get_status_display() if hasattr(p, "boarding") else "Pending",
                }
                for i, p in enumerate(booking.passengers.select_related("seat__coach", "boarding"), start=1)
            ],
        })
