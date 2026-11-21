"""Input validation for API requests (outputs are built by small presenter functions)."""
from django.conf import settings
from rest_framework import serializers

from apps.railway.constants import TravelClass


class JourneyParamsSerializer(serializers.Serializer):
    from_code = serializers.CharField(max_length=5)
    to_code = serializers.CharField(max_length=5)
    date = serializers.DateField()


class SearchQuerySerializer(serializers.Serializer):
    from_code = serializers.CharField(max_length=5)
    to_code = serializers.CharField(max_length=5)
    date = serializers.DateField()
    coach_class = serializers.ChoiceField(choices=TravelClass.choices, required=False, allow_blank=True)
    passengers = serializers.IntegerField(min_value=1, required=False, default=1)

    def validate_passengers(self, value):
        limit = settings.SITESMART["MAX_PASSENGERS_PER_BOOKING"]
        if value > limit:
            raise serializers.ValidationError(f"At most {limit} passengers per booking.")
        return value

    def validate(self, attrs):
        attrs["from_code"] = attrs["from_code"].upper()
        attrs["to_code"] = attrs["to_code"].upper()
        if attrs["from_code"] == attrs["to_code"]:
            raise serializers.ValidationError("Origin and destination must be different stations.")
        return attrs


class PassengerInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    age = serializers.IntegerField(min_value=1, max_value=120)
    gender = serializers.ChoiceField(choices=[("M", "Male"), ("F", "Female"), ("O", "Other")])
    berth_preference = serializers.CharField(max_length=2, required=False, allow_blank=True, default="")


class BookingCreateSerializer(serializers.Serializer):
    train_id = serializers.IntegerField()
    journey_date = serializers.DateField()
    from_code = serializers.CharField(max_length=5)
    to_code = serializers.CharField(max_length=5)
    coach_class = serializers.ChoiceField(choices=TravelClass.choices)
    passengers = PassengerInputSerializer(many=True)
    seat_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    contact_phone = serializers.RegexField(r"^([6-9]\d{9})?$", required=False, allow_blank=True,
                                           error_messages={"invalid": "Enter a 10-digit mobile number."})

    def validate_passengers(self, value):
        limit = settings.SITESMART["MAX_PASSENGERS_PER_BOOKING"]
        if not value:
            raise serializers.ValidationError("Add at least one passenger.")
        if len(value) > limit:
            raise serializers.ValidationError(f"At most {limit} passengers per booking.")
        return value


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class VerifySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[("BOARDED", "Boarded"), ("NOT_BOARDED", "Did not board")])
    remarks = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class SimulationControlSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["start", "pause", "resume", "step", "next_station", "auto_on", "auto_off"]
    )
    interval = serializers.IntegerField(min_value=5, max_value=600, required=False)
