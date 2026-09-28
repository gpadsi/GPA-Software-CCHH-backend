from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, viewsets

from apps.core.permissions import IsCapitalHumanoOrAdminOrReadOnly, scope_to_own_unless_management
from apps.persons.models import (
    ContactoUrgencia,
    Escolaridad,
    EstadoCivil,
    Genero,
    Persona,
    PerfilMedico,
    TipoSangre,
)
from apps.persons.serializers import (
    ContactoUrgenciaSerializer,
    EscolaridadSerializer,
    EstadoCivilSerializer,
    GeneroSerializer,
    PersonaSerializer,
    PerfilMedicoSerializer,
    TipoSangreSerializer,
)


def _catalog_viewset(target_model, target_serializer_class):
    # Nombres de parámetro distintos a los atributos de clase a propósito:
    # dentro de un cuerpo de clase, "serializer_class = serializer_class" no
    # lee la variable de la función que envuelve (NameError).
    @extend_schema_view(
        list=extend_schema(tags=["persons"]),
        retrieve=extend_schema(tags=["persons"]),
    )
    class _ViewSet(viewsets.ReadOnlyModelViewSet):
        queryset = target_model.objects.all()
        serializer_class = target_serializer_class
        permission_classes = [permissions.IsAuthenticated]

    _ViewSet.__name__ = f"{target_model.__name__}ViewSet"
    return _ViewSet


GeneroViewSet = _catalog_viewset(Genero, GeneroSerializer)
EstadoCivilViewSet = _catalog_viewset(EstadoCivil, EstadoCivilSerializer)
EscolaridadViewSet = _catalog_viewset(Escolaridad, EscolaridadSerializer)
TipoSangreViewSet = _catalog_viewset(TipoSangre, TipoSangreSerializer)


@extend_schema_view(
    list=extend_schema(tags=["persons"]),
    retrieve=extend_schema(tags=["persons"]),
    create=extend_schema(tags=["persons"]),
    update=extend_schema(tags=["persons"]),
    partial_update=extend_schema(tags=["persons"]),
    destroy=extend_schema(tags=["persons"]),
)
class PersonaViewSet(viewsets.ModelViewSet):
    queryset = Persona.objects.order_by("pk")
    serializer_class = PersonaSerializer
    permission_classes = [IsCapitalHumanoOrAdminOrReadOnly]

    def get_queryset(self):
        return scope_to_own_unless_management(super().get_queryset(), self.request.user, "empleado__user")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


@extend_schema_view(
    list=extend_schema(tags=["persons"]),
    retrieve=extend_schema(tags=["persons"]),
    create=extend_schema(tags=["persons"]),
    update=extend_schema(tags=["persons"]),
    partial_update=extend_schema(tags=["persons"]),
    destroy=extend_schema(tags=["persons"]),
)
class ContactoUrgenciaViewSet(viewsets.ModelViewSet):
    queryset = ContactoUrgencia.objects.order_by("pk")
    serializer_class = ContactoUrgenciaSerializer
    permission_classes = [IsCapitalHumanoOrAdminOrReadOnly]
    # DjangoFilterBackend ya está registrado globalmente (config/settings) —
    # esto habilita "?persona=<uuid>" para no traer todos los contactos del
    # sistema solo para mostrar los de una Persona.
    filterset_fields = ["persona"]

    def get_queryset(self):
        return scope_to_own_unless_management(
            super().get_queryset(), self.request.user, "persona__empleado__user"
        )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


@extend_schema_view(
    list=extend_schema(tags=["persons"]),
    retrieve=extend_schema(tags=["persons"]),
    create=extend_schema(tags=["persons"]),
    update=extend_schema(tags=["persons"]),
    partial_update=extend_schema(tags=["persons"]),
    destroy=extend_schema(tags=["persons"]),
)
class PerfilMedicoViewSet(viewsets.ModelViewSet):
    queryset = PerfilMedico.objects.order_by("pk")
    serializer_class = PerfilMedicoSerializer
    permission_classes = [IsCapitalHumanoOrAdminOrReadOnly]
    filterset_fields = ["persona"]

    def get_queryset(self):
        return scope_to_own_unless_management(
            super().get_queryset(), self.request.user, "persona__empleado__user"
        )

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
