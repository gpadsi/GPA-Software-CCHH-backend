from django.core.exceptions import NON_FIELD_ERRORS, ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.settings import api_settings

from apps.core.serializers import validar_nombre_sin_repetir
from apps.positions.models import (
    AlcanceDePosicion,
    EstatusPosicion,
    Posicion,
    Puesto,
    TipoPosicion,
    TipoRequisicion,
)


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


class AlcanceDePosicionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AlcanceDePosicion
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class TipoPosicionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoPosicion
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class TipoRequisicionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoRequisicion
        # requiere_justificacion: el front lo usa para marcar la justificación
        # como obligatoria sin esperar a que el servidor la rechace.
        fields = ["id", "code", "name", "is_active", "requiere_justificacion"]
        read_only_fields = fields


class EstatusPosicionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstatusPosicion
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class PuestoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Puesto
        fields = ["id", "code", "name", "is_active", "es_gerencia_de_unidad"]
        # El código se genera solo al crear y ya no cambia: lo usan las
        # importaciones para reconocer el puesto, aunque se renombre.
        read_only_fields = ["id", "code"]

    def validate_name(self, value):
        return validar_nombre_sin_repetir(Puesto, self.instance, value, "un puesto")


class PosicionSerializer(FullCleanModelSerializer):
    # Solo lectura: cómo nombrarla a una persona ("Puesto — Unidad (Área)").
    etiqueta = serializers.CharField(read_only=True)

    class Meta:
        model = Posicion
        fields = [
            "id", "etiqueta", "organization_node", "area", "puesto", "reports_to", "supervision_texto",
            "alcance", "tipo_posicion", "tipo_requisicion", "estatus", "genero_requerido",
            "fecha_registro_vacante", "fecha_autorizacion_vacante",
            "headhunter", "solicitante_vacante",
            "proyecto_eventual", "fecha_esperada_termino",
        ]
        read_only_fields = ["id"]
