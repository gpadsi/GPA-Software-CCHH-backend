import django_filters
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.core.permissions import (
    IsCapitalHumanoOrAdmin,
    IsCapitalHumanoOrAdminOrReadOnly,
    IsOwnerOrGestionRRHH,
    scope_to_own_unless_management,
)
from apps.positions.models import Posicion
from apps.recruitment.exports import generar_excel
from apps.recruitment.exports_word import generar_word
from apps.recruitment.models import (
    AprobacionRequisicion,
    CompetenciaConductual,
    ConformidadDescriptivo,
    DescriptivoPuesto,
    DiasPorLaborar,
    EstadoRequisicion,
    EtapaAprobacion,
    HorarioACubrir,
    RangoEdad,
    RecursoAsignado,
    Requisicion,
    RolConformidad,
    TipoContratoOfrecido,
)
from apps.recruitment.serializers import (
    AprobacionRequisicionSerializer,
    CompetenciaConductualSerializer,
    ConformidadDescriptivoSerializer,
    CrearBorradorSerializer,
    DescriptivoPuestoSerializer,
    DiasPorLaborarSerializer,
    EstadoRequisicionSerializer,
    EtapaAprobacionSerializer,
    HorarioACubrirSerializer,
    RangoEdadSerializer,
    RecursoAsignadoSerializer,
    RequisicionSerializer,
    RolConformidadSerializer,
    TipoContratoOfrecidoSerializer,
    _raise_drf_validation_error,
)
from apps.recruitment.services import copiar_version, crear_borrador as crear_borrador_desde_posicion


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
RangoEdadViewSet = _catalog_viewset(RangoEdad, RangoEdadSerializer)
DiasPorLaborarViewSet = _catalog_viewset(DiasPorLaborar, DiasPorLaborarSerializer)
CompetenciaConductualViewSet = _catalog_viewset(CompetenciaConductual, CompetenciaConductualSerializer)
RecursoAsignadoViewSet = _catalog_viewset(RecursoAsignado, RecursoAsignadoSerializer)
RolConformidadViewSet = _catalog_viewset(RolConformidad, RolConformidadSerializer)


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


class DescriptivoPuestoFilter(django_filters.FilterSet):
    # congelado=true -> versiones aprobadas; congelado=false -> borradores.
    congelado = django_filters.BooleanFilter(field_name="congelado_en", lookup_expr="isnull", exclude=True)

    class Meta:
        model = DescriptivoPuesto
        fields = ["posicion", "congelado"]


@extend_schema_view(
    list=extend_schema(tags=["recruitment"]),
    retrieve=extend_schema(tags=["recruitment"]),
    create=extend_schema(tags=["recruitment"]),
    update=extend_schema(tags=["recruitment"]),
    partial_update=extend_schema(tags=["recruitment"]),
    destroy=extend_schema(tags=["recruitment"]),
)
class DescriptivoPuestoViewSet(viewsets.ModelViewSet):
    """
    Descriptivo de Puesto versionado (FO-C0-CH-04). Lo lee cualquier usuario
    autenticado (describe la plaza, no a una persona -- mismo criterio que
    Posición/Puesto); solo Capital Humano/Admin lo escribe. Se edita
    mientras es borrador; al congelarlo ("congelar") ya no se modifica ni se
    borra -- para cambiar algo se copia a un borrador nuevo ("copiar").
    """
    queryset = DescriptivoPuesto.objects.select_related("posicion", "edad", "dias_por_laborar", "horario").prefetch_related(
        "funciones", "indicadores", "competencias", "recursos", "conformidades",
    ).order_by("posicion", "-version")
    serializer_class = DescriptivoPuestoSerializer
    permission_classes = [IsCapitalHumanoOrAdminOrReadOnly]
    filterset_class = DescriptivoPuestoFilter

    def _serializar(self, descriptivo):
        # Se vuelve a leer: las acciones devuelven el estado final con sus listas.
        return self.get_serializer(self.get_queryset().get(pk=descriptivo.pk)).data

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_destroy(self, instance):
        instance.deleted_by = self.request.user
        try:
            instance.delete()
        except DjangoValidationError as error:
            _raise_drf_validation_error(error)

    @extend_schema(
        tags=["recruitment"],
        request=CrearBorradorSerializer,
        responses={201: DescriptivoPuestoSerializer},
        summary="Crear borrador desde la Posición",
        description=(
            "Abre un borrador nuevo con los datos generales precargados de lo que "
            "el sistema ya sabe (Puesto, empresa, unidad, a quién reporta). Falla si "
            "la Posición ya tiene un borrador abierto."
        ),
    )
    @action(detail=False, methods=["post"], url_path="crear-borrador")
    def crear_borrador(self, request):
        entrada = CrearBorradorSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            descriptivo = crear_borrador_desde_posicion(entrada.validated_data["posicion"], user=request.user)
        except DjangoValidationError as error:
            _raise_drf_validation_error(error)
        return Response(self._serializar(descriptivo), status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["recruitment"], request=None, responses={201: DescriptivoPuestoSerializer},
        summary="Copiar esta versión a un borrador nuevo",
        description="Abre un borrador con el contenido de esta versión para editarlo sin tocar la original.",
    )
    @action(detail=True, methods=["post"])
    def copiar(self, request, pk=None):
        try:
            nuevo = copiar_version(self.get_object(), user=request.user)
        except DjangoValidationError as error:
            _raise_drf_validation_error(error)
        return Response(self._serializar(nuevo), status=status.HTTP_201_CREATED)

    @extend_schema(
        tags=["recruitment"], request=None, responses={200: DescriptivoPuestoSerializer},
        summary="Congelar (aprobar) el borrador",
        description="Desde aquí la versión es inmutable. Las conformidades se registran después, sobre esta versión.",
    )
    @action(detail=True, methods=["post"])
    def congelar(self, request, pk=None):
        descriptivo = self.get_object()
        try:
            descriptivo.congelar(user=request.user)
        except DjangoValidationError as error:
            _raise_drf_validation_error(error)
        return Response(self._serializar(descriptivo))

    @extend_schema(
        tags=["recruitment"],
        summary="Exportar a Word (formato oficial)",
        description=(
            "Descarga el Descriptivo (borrador o versión congelada) en el mismo "
            "archivo .docx oficial de GPA (FO-C0-CH-04) -- nunca cambia el diseño, "
            "solo llena los campos y casillas que el formulario ya trae. Lo que no "
            "tiene dato queda como la plantilla; las firmas quedan en blanco a "
            "propósito, para imprimir y firmar a mano."
        ),
    )
    @action(detail=True, methods=["get"], url_path="exportar-word")
    def exportar_word(self, request, pk=None):
        nombre_archivo, buffer = generar_word(self.get_object())
        return FileResponse(
            buffer, as_attachment=True, filename=nombre_archivo,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    @extend_schema(
        tags=["recruitment"],
        parameters=[OpenApiParameter("posicion", str, required=True, description="Id de la Posición")],
        responses={200: DescriptivoPuestoSerializer},
        summary="Versión vigente de una Posición",
        description="La versión congelada más reciente. 404 si la Posición todavía no tiene ninguna.",
    )
    @action(detail=False, methods=["get"])
    def vigente(self, request):
        posicion_id = request.query_params.get("posicion")
        if not posicion_id:
            raise NotFound("Indica la Posición: ?posicion=<id>.")
        try:
            posicion = Posicion.objects.get(pk=posicion_id)
        except (Posicion.DoesNotExist, DjangoValidationError, ValueError):
            raise NotFound("La Posición indicada no existe.")
        descriptivo = DescriptivoPuesto.vigente_de(posicion)
        if descriptivo is None:
            raise NotFound("Esta Posición todavía no tiene un Descriptivo congelado.")
        return Response(self._serializar(descriptivo))


@extend_schema_view(
    list=extend_schema(tags=["recruitment"]),
    retrieve=extend_schema(tags=["recruitment"]),
    create=extend_schema(tags=["recruitment"]),
    update=extend_schema(tags=["recruitment"]),
    partial_update=extend_schema(tags=["recruitment"]),
    destroy=extend_schema(tags=["recruitment"]),
)
class ConformidadDescriptivoViewSet(viewsets.ModelViewSet):
    """
    Solo Capital Humano/Admin registra las conformidades (mismo criterio que
    las aprobaciones de la Requisición): ellos capturan cada firma, digital
    o física. El Colaborador todavía no puede aceptar por sí mismo desde su
    cuenta -- hoy es solo lectura en todo el sistema.
    """
    queryset = ConformidadDescriptivo.objects.order_by("rol__name")
    serializer_class = ConformidadDescriptivoSerializer
    permission_classes = [IsCapitalHumanoOrAdmin]
    filterset_fields = ["descriptivo"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_destroy(self, instance):
        instance.deleted_by = self.request.user
        instance.delete()
