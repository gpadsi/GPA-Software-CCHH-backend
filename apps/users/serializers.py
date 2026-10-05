from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.permissions import es_gestion_rrhh
from apps.users.models import User, UserRole


class UserRoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserRole
        fields = ["code", "name"]
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    # null mientras la cuenta no tenga rol asignado (ej. un superusuario recién
    # creado): esa cuenta tampoco puede escribir nada en la API.
    role = UserRoleSerializer(read_only=True, allow_null=True)
    can_manage_hr = serializers.SerializerMethodField(
        help_text=(
            "true si la cuenta puede crear, editar y borrar datos de Capital Humano "
            "(roles Capital Humano y Admin). Es la misma regla que aplica la API, "
            "así el front no la repite."
        ),
    )

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "is_active", "role", "can_manage_hr"]
        read_only_fields = fields

    @extend_schema_field(serializers.BooleanField())
    def get_can_manage_hr(self, user):
        return es_gestion_rrhh(user)
