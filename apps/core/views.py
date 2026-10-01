from django.contrib.contenttypes.models import ContentType
from django.http import FileResponse, Http404
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework import generics, permissions
from rest_framework.parsers import FormParser, MultiPartParser

from apps.core.models import Attachment
from apps.core.permissions import IsCapitalHumanoOrAdmin
from apps.core.serializers import AttachmentSerializer


@extend_schema(
    tags=["core"],
    summary="Listar / subir archivos adjuntos",
    description=(
        "**GET:** lista los adjuntos. Filtrar con `?model_name=<modelo>&object_id=<id>` "
        "para los adjuntos de un objeto específico.\n\n"
        "**POST:** sube un archivo (multipart/form-data)."
    ),
    parameters=[
        OpenApiParameter(
            name="model_name", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY,
            required=False, description="Nombre del modelo destino en minúsculas.",
        ),
        OpenApiParameter(
            name="object_id", type=OpenApiTypes.STR, location=OpenApiParameter.QUERY,
            required=False, description="PK del objeto destino (UUID o entero como string).",
        ),
    ],
)
class AttachmentListCreateView(generics.ListCreateAPIView):
    serializer_class = AttachmentSerializer
    # Solo Capital Humano/Admin por ahora: Attachment se engancha a CUALQUIER
    # modelo vía GenericForeignKey, así que no hay forma barata de resolver
    # aquí "¿es mío?" para dejarle lectura propia a un Colaborador como en
    # Persona/Empleado/etc. Revisar cuando haya un caso de uso real de
    # autoservicio de archivos.
    permission_classes = [IsCapitalHumanoOrAdmin]

    def get_parsers(self):
        if getattr(self, "request", None) and self.request.method == "POST":
            return [MultiPartParser(), FormParser()]
        return super().get_parsers()

    def get_queryset(self):
        qs = Attachment.objects.select_related("content_type", "uploaded_by").order_by("-uploaded_at")
        params = self.request.query_params
        model_name = params.get("model_name")
        object_id = params.get("object_id")
        if model_name:
            try:
                ct = ContentType.objects.get(model=model_name.lower())
                qs = qs.filter(content_type=ct)
            except ContentType.DoesNotExist:
                return Attachment.objects.none()
        if object_id:
            qs = qs.filter(object_id=object_id)
        return qs


@extend_schema(
    tags=["core"],
    summary="Borrar archivo adjunto",
    description="Elimina el registro `Attachment` y su archivo asociado.",
)
class AttachmentDestroyView(generics.DestroyAPIView):
    permission_classes = [IsCapitalHumanoOrAdmin]
    queryset = Attachment.objects.all()
    # DELETE no usa un serializer para el body, pero drf-spectacular necesita
    # uno para poder generar el schema de esta vista sin marcarla como error.
    serializer_class = AttachmentSerializer


@extend_schema(
    tags=["core"],
    summary="Descargar archivo adjunto",
    description=(
        "Descarga el archivo real pasando por el mismo permiso que el resto "
        "de Attachment. Es el único camino soportado para bajar un adjunto — "
        "nunca la ruta directa a /media/, que en producción nginx serviría "
        "sin revisar ningún permiso (ver AttachmentSerializer.get_file_url)."
    ),
)
class AttachmentDownloadView(generics.RetrieveAPIView):
    permission_classes = [IsCapitalHumanoOrAdmin]
    queryset = Attachment.objects.all()
    # No se usa para serializar la respuesta (esta vista regresa el archivo
    # crudo) -- drf-spectacular necesita uno igual, mismo motivo que arriba.
    serializer_class = AttachmentSerializer

    def retrieve(self, request, *args, **kwargs):
        attachment = self.get_object()
        if not attachment.file:
            raise Http404
        return FileResponse(
            attachment.file.open("rb"),
            as_attachment=True,
            filename=attachment.filename or attachment.file.name.rsplit("/", 1)[-1],
        )
