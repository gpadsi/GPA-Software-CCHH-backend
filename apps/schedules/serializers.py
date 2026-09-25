from django.core.exceptions import NON_FIELD_ERRORS, ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.settings import api_settings

from apps.schedules.models import AsignacionHorario, AsignacionUbicacion, Catorcena, TipoHorario


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


class TipoHorarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoHorario
        fields = ["id", "code", "name", "descripcion", "is_active"]
        read_only_fields = fields


class CatorcenaSerializer(FullCleanModelSerializer):
    class Meta:
        model = Catorcena
        fields = ["id", "numero", "anio", "fecha_inicio", "fecha_fin"]
        read_only_fields = ["id"]


class AsignacionUbicacionSerializer(FullCleanModelSerializer):
    class Meta:
        model = AsignacionUbicacion
        fields = ["id", "empleado", "catorcena", "fecha_referencia", "area"]
        read_only_fields = ["id"]


class AsignacionHorarioSerializer(FullCleanModelSerializer):
    class Meta:
        model = AsignacionHorario
        fields = ["id", "empleado", "catorcena", "fecha_referencia", "tipo_horario"]
        read_only_fields = ["id"]
