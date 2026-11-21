"""Helpers shared by the API views."""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.api.serializers import JourneyParamsSerializer
from apps.bookings.services.boarding import user_can_operate_train
from apps.railway.models import Train


def journey_params(request) -> dict:
    qp = request.query_params
    s = JourneyParamsSerializer(data={"from_code": qp.get("from"), "to_code": qp.get("to"), "date": qp.get("date")})
    s.is_valid(raise_exception=True)
    data = s.validated_data
    data["from_code"] = data["from_code"].upper()
    data["to_code"] = data["to_code"].upper()
    return data


def get_train(train_id: int) -> Train:
    return get_object_or_404(Train.objects.select_related("route"), pk=train_id)


def get_operable_train(request, train_id: int) -> Train:
    train = get_train(train_id)
    if not user_can_operate_train(request.user, train):
        raise PermissionDenied("You are not assigned to this train.")
    return train


def int_param(request, name: str, default=None, *, required: bool = False):
    raw = request.query_params.get(name)
    if raw in (None, ""):
        if required:
            raise ValidationError({name: "This parameter is required."})
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValidationError({name: "Must be a whole number."}) from None
