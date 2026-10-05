from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, viewsets

from apps.core.permissions import IsCapitalHumanoOrAdminOrReadOnly
from apps.locations.models import Area, Nave, Ubicacion
from apps.locations.serializers import AreaSerializer, NaveSerializer, UbicacionSerializer


def _crud_viewset(target_model, target_serializer_class, target_search=(), target_ordering=()):
    # Nombres de parámetro distintos a los atributos de clase a propósito:
    # dentro de un cuerpo de clase, "serializer_class = serializer_class"
    # NO lee la variable de la función que envuelve (NameError) — el cuerpo
    # de una clase no cierra sobre el scope de la función como sí lo hace
    # una función anidada normal.
    @extend_schema_view(
        list=extend_schema(tags=["locations"]),
        retrieve=extend_schema(tags=["locations"]),
        create=extend_schema(tags=["locations"]),
        update=extend_schema(tags=["locations"]),
        partial_update=extend_schema(tags=["locations"]),
        destroy=extend_schema(tags=["locations"]),
    )
    class _ViewSet(viewsets.ModelViewSet):
        queryset = target_model.objects.order_by("pk")
        serializer_class = target_serializer_class
        permission_classes = [IsCapitalHumanoOrAdminOrReadOnly]
        search_fields = list(target_search)
        ordering_fields = list(target_ordering)

        def perform_create(self, serializer):
            serializer.save(created_by=self.request.user, updated_by=self.request.user)

        def perform_update(self, serializer):
            serializer.save(updated_by=self.request.user)

    _ViewSet.__name__ = f"{target_model.__name__}ViewSet"
    return _ViewSet


UbicacionViewSet = _crud_viewset(
    Ubicacion, UbicacionSerializer,
    target_search=["code", "name", "employer_registration"],
    target_ordering=["code", "name", "employer_registration", "is_active"],
)
NaveViewSet = _crud_viewset(
    Nave, NaveSerializer,
    target_search=["code", "name", "ubicacion__code", "ubicacion__name"],
    target_ordering=["code", "name", "ubicacion__name", "is_active"],
)
AreaViewSet = _crud_viewset(
    Area, AreaSerializer,
    target_search=["code", "name", "nave__code", "nave__name", "nave__ubicacion__name"],
    target_ordering=["code", "name", "nave__name", "nave__ubicacion__name", "is_active"],
)
