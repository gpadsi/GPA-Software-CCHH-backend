from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, viewsets

from apps.core.permissions import IsCapitalHumanoOrAdminOrReadOnly, scope_to_own_unless_management
from apps.schedules.models import AsignacionHorario, AsignacionUbicacion, Catorcena, TipoHorario
from apps.schedules.serializers import (
    AsignacionHorarioSerializer,
    AsignacionUbicacionSerializer,
    CatorcenaSerializer,
    TipoHorarioSerializer,
)


def _crud_viewset(target_model, target_serializer_class, owner_lookup=None):
    # Nombres de parámetro distintos a los atributos de clase a propósito:
    # dentro de un cuerpo de clase, "serializer_class = serializer_class" no
    # lee la variable de la función que envuelve (NameError).
    @extend_schema_view(
        list=extend_schema(tags=["schedules"]),
        retrieve=extend_schema(tags=["schedules"]),
        create=extend_schema(tags=["schedules"]),
        update=extend_schema(tags=["schedules"]),
        partial_update=extend_schema(tags=["schedules"]),
        destroy=extend_schema(tags=["schedules"]),
    )
    class _ViewSet(viewsets.ModelViewSet):
        queryset = target_model.objects.order_by("pk")
        serializer_class = target_serializer_class
        permission_classes = [IsCapitalHumanoOrAdminOrReadOnly]

        def get_queryset(self):
            queryset = super().get_queryset()
            if owner_lookup is None:
                return queryset
            return scope_to_own_unless_management(queryset, self.request.user, owner_lookup)

        def perform_create(self, serializer):
            serializer.save(created_by=self.request.user, updated_by=self.request.user)

        def perform_update(self, serializer):
            serializer.save(updated_by=self.request.user)

    _ViewSet.__name__ = f"{target_model.__name__}ViewSet"
    return _ViewSet


@extend_schema_view(
    list=extend_schema(tags=["schedules"]),
    retrieve=extend_schema(tags=["schedules"]),
)
class TipoHorarioViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TipoHorario.objects.all()
    serializer_class = TipoHorarioSerializer
    permission_classes = [permissions.IsAuthenticated]


CatorcenaViewSet = _crud_viewset(Catorcena, CatorcenaSerializer)
AsignacionUbicacionViewSet = _crud_viewset(AsignacionUbicacion, AsignacionUbicacionSerializer, owner_lookup="empleado__user")
AsignacionHorarioViewSet = _crud_viewset(AsignacionHorario, AsignacionHorarioSerializer, owner_lookup="empleado__user")
