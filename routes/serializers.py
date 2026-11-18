import math

from rest_framework import serializers


class LocationField(serializers.Field):
    """Accept a place name or a coordinate pair in [longitude, latitude] order."""

    default_error_messages = {
        "invalid": "Provide a place name or [longitude, latitude].",
        "coordinates": "Coordinates must be finite numbers in [longitude, latitude] order: longitude -180 to 180, latitude -90 to 90.",
    }

    def to_internal_value(self, data):
        if isinstance(data, str):
            return serializers.CharField(max_length=300).run_validation(data)
        if not isinstance(data, list) or len(data) != 2:
            self.fail("invalid")
        if any(isinstance(value, bool) for value in data):
            self.fail("coordinates")
        try:
            longitude = serializers.FloatField(min_value=-180, max_value=180).run_validation(data[0])
            latitude = serializers.FloatField(min_value=-90, max_value=90).run_validation(data[1])
        except serializers.ValidationError:
            self.fail("coordinates")
        if not (math.isfinite(longitude) and math.isfinite(latitude)):
            self.fail("coordinates")
        return [longitude, latitude]

    def to_representation(self, value):
        return value


class RouteRequestSerializer(serializers.Serializer):
    start = LocationField(help_text="US place name or [longitude, latitude].")
    finish = LocationField(help_text="US place name or [longitude, latitude].")
