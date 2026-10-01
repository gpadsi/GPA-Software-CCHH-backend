from django.core.exceptions import NON_FIELD_ERRORS, ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.settings import api_settings

from apps.recruitment.models import (
    AprobacionRequisicion,
    EstadoRequisicion,
    EtapaAprobacion,
    HorarioACubrir,
    Requisicion,
    TipoContratoOfrecido,
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


class EstadoRequisicionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoRequisicion
        fields = ["id", "code", "name", "is_active", "es_terminal"]
        read_only_fields = fields


class EtapaAprobacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = EtapaAprobacion
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class TipoContratoOfrecidoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoContratoOfrecido
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class HorarioACubrirSerializer(serializers.ModelSerializer):
    class Meta:
        model = HorarioACubrir
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class AprobacionRequisicionSerializer(FullCleanModelSerializer):
    class Meta:
        model = AprobacionRequisicion
        fields = ["id", "requisicion", "etapa", "fecha", "usuario", "nombre_manual"]
        read_only_fields = ["id"]


class RequisicionSerializer(FullCleanModelSerializer):
    aprobaciones = AprobacionRequisicionSerializer(many=True, read_only=True)

    class Meta:
        model = Requisicion
        fields = [
            "id", "posicion", "tipo", "estado",
            "fecha_solicitud", "fecha_a_cubrir_vacante", "fecha_entrega_a_capital_humano",
            "area_solicitante", "justificacion",
            "horario_a_cubrir", "idiomas_requeridos", "disposicion_viajar",
            "nivel_tabulador", "sueldo_mensual_compuesto", "sueldo_mensual_bruto", "sueldo_mensual_neto",
            "tipo_contrato_ofrecido",
            "motivo_suspension", "fecha_suspension", "autorizado_por_suspension",
            "aprobaciones",
        ]
        read_only_fields = ["id"]
