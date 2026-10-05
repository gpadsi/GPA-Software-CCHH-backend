from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets

from apps.core.permissions import IsCapitalHumanoOrAdminOrReadOnly, scope_to_own_unless_management
from apps.core.viewsets import EditableCatalogViewSet
from apps.schedules.models import AsignacionHorario, AsignacionUbicacion, Catorcena, TipoHorario
from apps.schedules.serializers import (
    AsignacionHorarioSerializer,
    AsignacionUbicacionSerializer,
    CatorcenaSerializer,
    TipoHorarioSerializer,
)


def _crud_viewset(
    target_model, target_serializer_class, owner_lookup=None, target_search=(), target_ordering=()
):
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
        search_fields = list(target_search)
        ordering_fields = list(target_ordering)

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
    create=extend_schema(tags=["schedules"]),
    update=extend_schema(tags=["schedules"]),
    partial_update=extend_schema(tags=["schedules"]),
)
class TipoHorarioViewSet(EditableCatalogViewSet):
    queryset = TipoHorario.objects.all()
    serializer_class = TipoHorarioSerializer


# La busqueda y el orden de las asignaciones pasan por el empleado: la
# busqueda se limita ANTES (scope_to_own_unless_management) a lo que la
# cuenta puede ver, asi que un Colaborador solo encuentra lo suyo.
_EMPLEADO_SEARCH = ["empleado__work_number", "empleado__persona__first_name", "empleado__persona__last_name_paternal", "empleado__persona__last_name_maternal"]
_EMPLEADO_ORDERING = ["empleado__persona__last_name_paternal", "empleado__persona__last_name_maternal", "empleado__persona__first_name"]

CatorcenaViewSet = _crud_viewset(
    Catorcena, CatorcenaSerializer,
    target_search=["numero", "anio"],
    target_ordering=["anio", "numero", "fecha_inicio", "fecha_fin"],
)
AsignacionUbicacionViewSet = _crud_viewset(
    AsignacionUbicacion, AsignacionUbicacionSerializer, owner_lookup="empleado__user",
    target_search=[*_EMPLEADO_SEARCH, "area__code", "area__name"],
    target_ordering=[*_EMPLEADO_ORDERING, "area__name", "catorcena__anio", "catorcena__numero", "fecha_referencia"],
)
AsignacionHorarioViewSet = _crud_viewset(
    AsignacionHorario, AsignacionHorarioSerializer, owner_lookup="empleado__user",
    target_search=[*_EMPLEADO_SEARCH, "tipo_horario__code", "tipo_horario__name"],
    target_ordering=[*_EMPLEADO_ORDERING, "tipo_horario__name", "catorcena__anio", "catorcena__numero", "fecha_referencia"],
)
