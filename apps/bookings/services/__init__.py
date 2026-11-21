"""Seat reallocation engine.

Public entry points (one module per responsibility):

* availability.check_seat_availability / get_available_seats / find_eligible_seats
* reservation.reserve_seats
* release.release_seat_segments
* boarding.mark_passenger_boarded / process_no_show
* cancellation.cancel_booking
* apps.operations.services.simulation.advance_simulation (station movement)
"""
