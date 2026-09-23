from django.core.exceptions import NON_FIELD_ERRORS, ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.settings import api_settings

from apps.persons.models import (
    ContactoUrgencia,
    Escolaridad,
    EstadoCivil,
    Genero,
    Persona,
    PerfilMedico,
    TipoSangre,
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
    """Ejecuta las reglas de ``Model.clean()`` antes de persistir cambios."""

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


class GeneroSerializer(serializers.ModelSerializer):
    class Meta:
        model = Genero
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class EstadoCivilSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstadoCivil
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class EscolaridadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Escolaridad
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class TipoSangreSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoSangre
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class ContactoUrgenciaSerializer(FullCleanModelSerializer):
    class Meta:
        model = ContactoUrgencia
        fields = ["id", "persona", "name", "relationship", "phone"]
        read_only_fields = ["id"]


class PerfilMedicoSerializer(FullCleanModelSerializer):
    class Meta:
        model = PerfilMedico
        fields = ["id", "persona", "blood_type", "allergies"]
        read_only_fields = ["id"]


class PersonaSerializer(FullCleanModelSerializer):
    class Meta:
        model = Persona
        fields = [
            "id", "first_name", "last_name_paternal", "last_name_maternal",
            "curp", "nss", "rfc", "birth_date", "birth_place_state",
            "gender", "marital_status", "education_level", "has_children",
            "personal_email", "phone",
            "address_line", "postal_code", "city", "municipality", "state",
        ]
        read_only_fields = ["id"]
