"""Uniform JSON error envelope: ``{"error": {"code", "message", "details"}}``."""
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from apps.bookings.exceptions import AllocationError


def _first_message(detail) -> str:
    if isinstance(detail, list) and detail:
        return _first_message(detail[0])
    if isinstance(detail, dict) and detail:
        key, value = next(iter(detail.items()))
        msg = _first_message(value)
        return msg if key in ("non_field_errors", "detail") else f"{key.replace('_', ' ').capitalize()}: {msg}"
    return str(detail)


def api_exception_handler(exc, context):
    if isinstance(exc, AllocationError):
        return Response(
            {"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            status=exc.status_code,
        )
    if isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied(str(exc) or None)
    response = exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, exceptions.ValidationError):
        payload = {"code": "validation_error", "message": _first_message(exc.detail), "details": exc.detail}
    else:
        code = getattr(exc, "default_code", "error")
        detail = response.data.get("detail", "") if isinstance(response.data, dict) else response.data
        payload = {"code": code, "message": str(detail), "details": {}}
        if response.status_code == status.HTTP_403_FORBIDDEN and "CSRF" in str(detail):
            payload["message"] = "Your session expired. Refresh the page and try again."
    response.data = {"error": payload}
    return response
