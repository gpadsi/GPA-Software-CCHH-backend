from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, viewsets

from apps.core.permissions import IsCapitalHumanoOrAdminOrReadOnly
from apps.positions.models import (
    AlcanceDePosicion,
    EstatusPosicion,
    Posicion,
    Puesto,
    TipoPosicion,
    TipoRequisicion,
)
from apps.positions.serializers import (
    AlcanceDePosicionSerializer,
    EstatusPosicionSerializer,
    PosicionSerializer,
    PuestoSerializer,
    TipoPosicionSerializer,
    TipoRequisicionSerializer,
)


def _catalog_viewset(target_model, target_serializer_class):
    # Nombres de parámetro distintos a los atributos de clase a propósito:
    # dentro de un cuerpo de clase, "serializer_class = serializer_class" no
    # lee la variable de la función que envuelve (NameError).
    @extend_schema_view(
        list=extend_schema(tags=["positions"]),
        retrieve=extend_schema(tags=["positions"]),
    )
    class _ViewSet(viewsets.ReadOnlyModelViewSet):
        queryset = target_model.objects.all()
        serializer_class = target_serializer_class
        permission_classes = [permissions.IsAuthenticated]

    _ViewSet.__name__ = f"{target_model.__name__}ViewSet"
    return _ViewSet


AlcanceDePosicionViewSet = _catalog_viewset(AlcanceDePosicion, AlcanceDePosicionSerializer)
TipoPosicionViewSet = _catalog_viewset(TipoPosicion, TipoPosicionSerializer)
TipoRequisicionViewSet = _catalog_viewset(TipoRequisicion, TipoRequisicionSerializer)
EstatusPosicionViewSet = _catalog_viewset(EstatusPosicion, EstatusPosicionSerializer)
PuestoViewSet = _catalog_viewset(Puesto, PuestoSerializer)


@extend_schema_view(
    list=extend_schema(tags=["positions"]),
    retrieve=extend_schema(tags=["positions"]),
    create=extend_schema(tags=["positions"]),
    update=extend_schema(tags=["positions"]),
    partial_update=extend_schema(tags=["positions"]),
    destroy=extend_schema(tags=["positions"]),
)
class PosicionViewSet(viewsets.ModelViewSet):
    queryset = Posicion.objects.order_by("pk")
    serializer_class = PosicionSerializer
    permission_classes = [IsCapitalHumanoOrAdminOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
