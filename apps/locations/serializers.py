from django.core.exceptions import NON_FIELD_ERRORS, ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.settings import api_settings

from apps.locations.models import Area, Nave, Ubicacion


def _raise_drf_validation_error(error):
    if hasattr(error, "message_dict"):
        detail = {
            api_settings.NON_FIELD_ERRORS_KEY if field == NON_FIELD_ERRORS else field: messages
            for field, messages in error.message_dict.items()
        }
    else:
        detail = {api_settings.NON_FIELD_ERRORS_KEY: error.messages}
    raise serializers.ValidationError(detail)


class FullCleanModelSerializer(serializers.ModelSerializer):
    def _save_validated_instance(self, instance):
        try:
            instance.full_clean()
        except DjangoValidationError as error:
            _raise_drf_validation_error(error)
        instance.save()
        return instance

    def create(self, validated_data):
        return self._save_validated_instance(self.Meta.model(**validated_data))

    def update(self, instance, validated_data):
        for attribute, value in validated_data.items():
            setattr(instance, attribute, value)
        return self._save_validated_instance(instance)


class UbicacionSerializer(FullCleanModelSerializer):
    class Meta:
        model = Ubicacion
        fields = ["id", "code", "name", "employer_registration", "is_active"]
        read_only_fields = ["id"]


class NaveSerializer(FullCleanModelSerializer):
    class Meta:
        model = Nave
        fields = ["id", "ubicacion", "code", "name", "is_active"]
        read_only_fields = ["id"]


class AreaSerializer(FullCleanModelSerializer):
    class Meta:
        model = Area
        fields = ["id", "nave", "code", "name", "is_active"]
        read_only_fields = ["id"]
