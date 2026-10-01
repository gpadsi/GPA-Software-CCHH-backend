from django.http import FileResponse
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, viewsets
from rest_framework.decorators import action

from apps.core.permissions import IsCapitalHumanoOrAdmin, IsOwnerOrGestionRRHH, scope_to_own_unless_management
from apps.recruitment.exports import generar_excel
from apps.recruitment.models import (
    AprobacionRequisicion,
    EstadoRequisicion,
    EtapaAprobacion,
    HorarioACubrir,
    Requisicion,
    TipoContratoOfrecido,
)
from apps.recruitment.serializers import (
    AprobacionRequisicionSerializer,
    EstadoRequisicionSerializer,
    EtapaAprobacionSerializer,
    HorarioACubrirSerializer,
    RequisicionSerializer,
    TipoContratoOfrecidoSerializer,
)


def _catalog_viewset(target_model, target_serializer_class):
    @extend_schema_view(
        list=extend_schema(tags=["recruitment"]),
        retrieve=extend_schema(tags=["recruitment"]),
    )
    class _ViewSet(viewsets.ReadOnlyModelViewSet):
        queryset = target_model.objects.all()
        serializer_class = target_serializer_class
        permission_classes = [permissions.IsAuthenticated]

    _ViewSet.__name__ = f"{target_model.__name__}ViewSet"
    return _ViewSet


EstadoRequisicionViewSet = _catalog_viewset(EstadoRequisicion, EstadoRequisicionSerializer)
EtapaAprobacionViewSet = _catalog_viewset(EtapaAprobacion, EtapaAprobacionSerializer)
TipoContratoOfrecidoViewSet = _catalog_viewset(TipoContratoOfrecido, TipoContratoOfrecidoSerializer)
HorarioACubrirViewSet = _catalog_viewset(HorarioACubrir, HorarioACubrirSerializer)


@extend_schema_view(
    list=extend_schema(tags=["recruitment"]),
    retrieve=extend_schema(tags=["recruitment"]),
    create=extend_schema(tags=["recruitment"]),
    update=extend_schema(tags=["recruitment"]),
    partial_update=extend_schema(tags=["recruitment"]),
    destroy=extend_schema(tags=["recruitment"]),
)
class RequisicionViewSet(viewsets.ModelViewSet):
    """
    Cualquier usuario autenticado puede crear una Requisición y leer/editar
    la suya (confirmado 2026-10-01 — ver IsOwnerOrGestionRRHH). Capital
    Humano/Admin ve y administra todas; borrar (soft-delete) queda
    reservado a ellos.
    """
    queryset = Requisicion.objects.order_by("-fecha_solicitud")
    serializer_class = RequisicionSerializer
    permission_classes = [IsOwnerOrGestionRRHH]

    def get_queryset(self):
        return scope_to_own_unless_management(super().get_queryset(), self.request.user, "created_by")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_destroy(self, instance):
        instance.deleted_by = self.request.user
        instance.delete()

    @extend_schema(
        tags=["recruitment"],
        summary="Exportar a Excel (formato oficial)",
        description=(
            "Descarga la Requisición llena en el mismo archivo .xlsx oficial de "
            "GPA (Requisición o Reemplazo de Personal, según el tipo) -- nunca "
            "cambia el diseño, solo llena las celdas de respuesta que el "
            "formulario real ya trae en blanco. Las zonas de firma quedan en "
            "blanco a propósito, para imprimir y firmar a mano."
        ),
    )
    @action(detail=True, methods=["get"], url_path="exportar-excel")
    def exportar_excel(self, request, pk=None):
        requisicion = self.get_object()
        nombre_archivo, buffer = generar_excel(requisicion)
        return FileResponse(
            buffer, as_attachment=True, filename=nombre_archivo,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


@extend_schema_view(
    list=extend_schema(tags=["recruitment"]),
    retrieve=extend_schema(tags=["recruitment"]),
    create=extend_schema(tags=["recruitment"]),
    update=extend_schema(tags=["recruitment"]),
    partial_update=extend_schema(tags=["recruitment"]),
    destroy=extend_schema(tags=["recruitment"]),
)
class AprobacionRequisicionViewSet(viewsets.ModelViewSet):
    """
    Solo Capital Humano/Admin administra las aprobaciones -- confirmado
    2026-10-01: no se auto-resuelve "jefe inmediato" desde el organigrama
    ni cada responsable tiene su propia bandeja; Capital Humano es quien
    registra cada firma (digital o física) en el sistema.
    """
    queryset = AprobacionRequisicion.objects.order_by("etapa__name")
    serializer_class = AprobacionRequisicionSerializer
    permission_classes = [IsCapitalHumanoOrAdmin]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_destroy(self, instance):
        instance.deleted_by = self.request.user
        instance.delete()
