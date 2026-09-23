from django.core.exceptions import NON_FIELD_ERRORS, ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.settings import api_settings

from apps.organizations.models import (
    Company,
    OrganizationalLevel,
    OrganizationNode,
    Tenant,
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


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "code", "name"]
        read_only_fields = fields


class OrganizationalLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationalLevel
        fields = ["id", "numero", "code", "name", "allows_recursive_nesting"]
        read_only_fields = fields


class OrganizationNodeSerializer(FullCleanModelSerializer):
    class Meta:
        model = OrganizationNode
        fields = ["id", "tenant", "level", "parent", "code", "name", "is_active"]
        # "tenant" nunca viene del cliente: OrganizationNode.save() lo autoasigna.
        read_only_fields = ["id", "tenant"]


class CompanySerializer(FullCleanModelSerializer):
    class Meta:
        model = Company
        fields = ["id", "organization_node", "legal_name", "rfc", "employer_registration"]
        read_only_fields = ["id"]
