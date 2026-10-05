from django.core.exceptions import NON_FIELD_ERRORS, ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.settings import api_settings

from apps.core.serializers import vacio_como_nulo
from apps.employment.models import CausaBaja, Contrato, Empleado, HistorialSalarial, OrigenBaja


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


class OrigenBajaSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrigenBaja
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class CausaBajaSerializer(serializers.ModelSerializer):
    class Meta:
        model = CausaBaja
        fields = ["id", "origen_baja", "code", "name", "is_active"]
        read_only_fields = fields


class EmpleadoSerializer(FullCleanModelSerializer):
    class Meta:
        model = Empleado
        fields = ["id", "persona", "user", "work_number"]
        read_only_fields = ["id"]

    def validate_work_number(self, value):
        # Único y opcional: sin esto, dos empleados sin número chocarían con "".
        return vacio_como_nulo(value)


class ContratoSerializer(FullCleanModelSerializer):
    class Meta:
        model = Contrato
        fields = [
            "id", "empleado", "posicion",
            "fecha_ingreso", "fecha_alta", "fecha_reingreso", "fecha_baja",
            "origen_baja", "causa_baja",
            "solicitante_baja", "considerado_para_reingreso", "observaciones",
        ]
        read_only_fields = ["id"]


class HistorialSalarialSerializer(FullCleanModelSerializer):
    class Meta:
        model = HistorialSalarial
        fields = ["id", "empleado", "monto", "fecha_vigencia"]
        read_only_fields = ["id"]


class JefeSerializer(serializers.Serializer):
    """
    Salida de Empleado.get_jefe() — todos los campos en None significa que
    no hay jefe resoluble hoy (sin Contrato activo, nivel más alto de la
    organización, o posición de jefe vacante), no un error.
    """
    posicion_id = serializers.UUIDField(allow_null=True)
    puesto = serializers.CharField(allow_null=True)
    empleado_id = serializers.UUIDField(allow_null=True)
    nombre = serializers.CharField(allow_null=True)
