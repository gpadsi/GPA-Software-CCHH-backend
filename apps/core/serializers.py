from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.models import Attachment


def vacio_como_nulo(value):
    """
    Un dato opcional y UNICO (RFC, número de nómina) que llega vacío se guarda
    como NULL, no como "": dos registros con "" chocarían entre sí en la
    restricción de unicidad aunque ambos estén simplemente «pendientes».
    """
    return value.strip() or None if value else None


def validar_nombre_sin_repetir(modelo, instancia, nombre, descripcion):
    """
    Impide dar de alta (o renombrar a) un valor de catálogo que ya existe con
    el mismo nombre, sin distinguir mayúsculas. El nombre no es único en la
    base a propósito (hay datos reales con variantes que RH normaliza poco a
    poco), así que esto solo se revisa al crear o al cambiar el nombre: editar
    otro campo de un valor ya repetido no debe quedar bloqueado.
    """
    if instancia is not None and instancia.name == nombre:
        return nombre
    repetidos = modelo.objects.filter(name__iexact=nombre)
    if instancia is not None:
        repetidos = repetidos.exclude(pk=instancia.pk)
    if repetidos.exists():
        raise serializers.ValidationError(f"Ya existe {descripcion} con ese nombre.")
    return nombre


class AttachmentSerializer(serializers.ModelSerializer):
    # WRITE-ONLY: nombre del modelo destino (ej. "persona", "puesto", ...)
    model_name = serializers.CharField(
        write_only=True,
        help_text="Nombre del modelo destino en minúsculas.",
    )
    # READ-ONLY: nombre del modelo resuelto en respuestas GET
    model_name_display = serializers.CharField(source="content_type.model", read_only=True)
    file_url = serializers.SerializerMethodField()
    uploaded_by_username = serializers.CharField(
        source="uploaded_by.username", read_only=True, allow_null=True
    )
    document_type_name = serializers.CharField(
        source="document_type.name", read_only=True, allow_null=True
    )

    class Meta:
        model = Attachment
        fields = [
            "id", "file", "filename", "file_url",
            "model_name", "model_name_display",
            "object_id",
            "document_type", "document_type_name",
            "uploaded_at", "uploaded_by_username",
        ]
        read_only_fields = [
            "id", "filename", "file_url",
            "model_name_display",
            "document_type_name",
            "uploaded_at", "uploaded_by_username",
        ]
        extra_kwargs = {"file": {"write_only": True}}

    def validate(self, data):
        """Convierte model_name → ContentType FK antes de guardar."""
        model_name = data.pop("model_name")
        try:
            ct = ContentType.objects.get(model=model_name.lower())
        except ContentType.DoesNotExist:
            raise serializers.ValidationError(
                {"model_name": f"Modelo '{model_name}' no reconocido."}
            )
        data["content_type"] = ct
        return data

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_file_url(self, obj):
        """
        URL de descarga protegida (pasa por AttachmentDownloadView, mismo
        permiso que el resto de Attachment) -- NUNCA la ruta directa a
        /media/, que en producción nginx serviría sin revisar nada.
        """
        if not obj.file:
            return None
        path = reverse("attachment-download", kwargs={"pk": obj.pk})
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path

    def create(self, validated_data):
        """Asigna uploaded_by desde request.user al crear."""
        validated_data["uploaded_by"] = self.context["request"].user
        return super().create(validated_data)
