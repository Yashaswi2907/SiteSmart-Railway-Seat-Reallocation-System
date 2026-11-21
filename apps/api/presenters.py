"""Small functions that turn model objects into JSON-friendly dicts."""
from __future__ import annotations

from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import BoardingStatus, Booking
from apps.bookings.services.boarding import verification_eligibility
from apps.bookings.services.status import JourneyState, booking_journey_state


def station_dict(station) -> dict:
    return {"code": station.code, "name": station.name, "city": station.city, "state": station.state}


def stop_dict(stop) -> dict:
    return {
        "id": stop.pk,
        "index": stop.sequence,
        "code": stop.station.code,
        "name": stop.station.name,
        "arrival": stop.arrival_time.strftime("%H:%M") if stop.arrival_time else None,
        "departure": stop.departure_time.strftime("%H:%M") if stop.departure_time else None,
        "day_offset": stop.day_offset,
        "distance_km": stop.distance_km,
    }


def search_result_dict(r: dict) -> dict:
    return {
        "train_id": r["train_id"],
        "number": r["number"],
        "name": r["name"],
        "train_type": r["train_type"],
        "running_days": r["running_days"],
        "runs_on_date": r["runs_on_date"],
        "from": stop_dict(r["from_stop"]),
        "to": stop_dict(r["to_stop"]),
        "duration": r["duration"],
        "duration_minutes": r["duration_minutes"],
        "distance_km": r["distance_km"],
        "departed": r["departed"],
        "departed_message": r["departed_message"],
        "simulation_status": r["simulation_status"],
        "classes": r["classes"],
    }


def passenger_row(p, simulation, stops) -> dict:
    booking = p.booking
    boarding = getattr(p, "boarding", None)
    status = boarding.status if boarding else BoardingStatus.Status.PENDING
    can_verify, reason = verification_eligibility(p, simulation)
    current = simulation.current_index if simulation else -1
    return {
        "id": p.pk,
        "pnr": booking.pnr,
        "name": p.name,
        "age": p.age,
        "gender": p.gender,
        "coach": p.seat.coach.coach_number,
        "coach_id": p.seat.coach_id,
        "seat_number": p.seat.seat_number,
        "berth": p.seat.berth_type,
        "from_code": stops[booking.from_index].station.code,
        "from_name": stops[booking.from_index].station.name,
        "to_code": stops[booking.to_index].station.code,
        "to_name": stops[booking.to_index].station.name,
        "from_index": booking.from_index,
        "to_index": booking.to_index,
        "boarding_status": status,
        "boarding_label": boarding.get_status_display() if boarding else "Pending verification",
        "verified_by": boarding.verified_by.display_name if boarding and boarding.verified_by else None,
        "verified_at": timezone.localtime(boarding.verified_at).strftime("%d %b, %H:%M")
        if boarding and boarding.verified_at else None,
        "is_reallocated": p.is_reallocated_seat,
        "can_verify": can_verify,
        "verify_block_reason": reason,
        "boards_here": booking.from_index == current and simulation is not None and simulation.is_running,
        "deboards_next": simulation is not None and simulation.is_running
        and booking.to_index == current + 1,
    }


def booking_summary(booking: Booking, simulation=None) -> dict:
    state = booking_journey_state(booking, simulation)
    label, tone = JourneyState.LABELS[state]
    return {
        "pnr": booking.pnr,
        "train_number": booking.train.number,
        "train_name": booking.train.name,
        "journey_date": booking.journey_date.isoformat(),
        "from_code": booking.from_stop.station.code,
        "from_name": booking.from_stop.station.name,
        "to_code": booking.to_stop.station.code,
        "to_name": booking.to_stop.station.name,
        "coach_class": booking.coach_class,
        "status": booking.status,
        "journey_state": state,
        "journey_state_label": label,
        "is_reallocated": booking.is_reallocated,
        "total_fare": str(booking.total_fare),
        "detail_url": reverse("bookings:booking_detail", args=[booking.pnr]),
    }
