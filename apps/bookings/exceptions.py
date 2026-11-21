"""Domain errors raised by the allocation engine.

Each error carries a short machine-readable ``code`` that the API returns to the
frontend, plus a human-readable message.
"""


class AllocationError(Exception):
    code = "allocation_error"
    status_code = 400

    def __init__(self, message: str, *, code: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}


class InvalidJourneyError(AllocationError):
    code = "invalid_journey"


class TrainDepartedError(AllocationError):
    code = "segment_departed"
    status_code = 409


class SeatUnavailableError(AllocationError):
    code = "seat_unavailable"
    status_code = 409


class InsufficientSeatsError(AllocationError):
    code = "insufficient_seats"
    status_code = 409


class BoardingActionError(AllocationError):
    code = "boarding_not_allowed"
    status_code = 409


class CancellationError(AllocationError):
    code = "cancellation_not_allowed"
    status_code = 409


class SimulationError(AllocationError):
    code = "simulation_error"
    status_code = 409
