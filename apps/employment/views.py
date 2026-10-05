from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.permissions import (
    IsCapitalHumanoOrAdmin,
    IsCapitalHumanoOrAdminOrReadOnly,
    scope_to_own_unless_management,
)
from apps.employment.models import CausaBaja, Contrato, Empleado, HistorialSalarial, OrigenBaja
from apps.employment.serializers import (
    CausaBajaSerializer,
    ContratoSerializer,
    EmpleadoSerializer,
    HistorialSalarialSerializer,
    JefeSerializer,
    OrigenBajaSerializer,
)

# Nombres de parámetro distintos a los atributos de clase en ambas fábricas
# de abajo, a propósito: dentro de un cuerpo de clase,
# "serializer_class = serializer_class" NO lee la variable de la función
# que envuelve (NameError) — el cuerpo de una clase no cierra sobre el
# scope de la función como sí lo hace una función anidada normal.


def _catalog_viewset(target_model, target_serializer_class):
    @extend_schema_view(
        list=extend_schema(tags=["employment"]),
        retrieve=extend_schema(tags=["employment"]),
    )
    class _ViewSet(viewsets.ReadOnlyModelViewSet):
        queryset = target_model.objects.all()
        serializer_class = target_serializer_class
        permission_classes = [permissions.IsAuthenticated]

    _ViewSet.__name__ = f"{target_model.__name__}ViewSet"
    return _ViewSet


def _crud_viewset(target_model, target_serializer_class, permission_classes=None, owner_lookup=None):
    resolved_permission_classes = permission_classes or [IsCapitalHumanoOrAdminOrReadOnly]

    @extend_schema_view(
        list=extend_schema(tags=["employment"]),
        retrieve=extend_schema(tags=["employment"]),
        create=extend_schema(tags=["employment"]),
        update=extend_schema(tags=["employment"]),
        partial_update=extend_schema(tags=["employment"]),
        destroy=extend_schema(tags=["employment"]),
    )
    class _ViewSet(viewsets.ModelViewSet):
        queryset = target_model.objects.order_by("pk")
        serializer_class = target_serializer_class
        permission_classes = resolved_permission_classes

        def get_queryset(self):
            queryset = super().get_queryset()
            if owner_lookup is None:
                return queryset
            return scope_to_own_unless_management(queryset, self.request.user, owner_lookup)

        def perform_create(self, serializer):
            serializer.save(created_by=self.request.user, updated_by=self.request.user)

        def perform_update(self, serializer):
            serializer.save(updated_by=self.request.user)

        def perform_destroy(self, instance):
            # Sin efecto en HistorialSalarial (borrado físico normal); en
            # Contrato (SoftDeleteModel) deja registrado quién lo borró.
            instance.deleted_by = self.request.user
            instance.delete()

    _ViewSet.__name__ = f"{target_model.__name__}ViewSet"
    return _ViewSet


OrigenBajaViewSet = _catalog_viewset(OrigenBaja, OrigenBajaSerializer)
CausaBajaViewSet = _catalog_viewset(CausaBaja, CausaBajaSerializer)
ContratoViewSet = _crud_viewset(Contrato, ContratoSerializer, owner_lookup="empleado__user")
# Colaborador no ve su propio salario por ahora (confirmado con el usuario
# 2026-09-24, puede cambiar más adelante) — gate total, sin excepción de
# "propio registro" como en Empleado/Contrato.
HistorialSalarialViewSet = _crud_viewset(
    HistorialSalarial, HistorialSalarialSerializer, permission_classes=[IsCapitalHumanoOrAdmin]
)


@extend_schema_view(
    list=extend_schema(tags=["employment"]),
    retrieve=extend_schema(tags=["employment"]),
    create=extend_schema(tags=["employment"]),
    update=extend_schema(tags=["employment"]),
    partial_update=extend_schema(tags=["employment"]),
    destroy=extend_schema(tags=["employment"]),
)
class EmpleadoViewSet(viewsets.ModelViewSet):
    queryset = Empleado.objects.order_by("pk")
    serializer_class = EmpleadoSerializer
    permission_classes = [IsCapitalHumanoOrAdminOrReadOnly]
    search_fields = [
        "work_number", "persona__first_name", "persona__last_name_paternal", "persona__last_name_maternal",
    ]
    ordering_fields = ["work_number", "persona__last_name_paternal", "persona__last_name_maternal", "persona__first_name"]

    def get_queryset(self):
        return scope_to_own_unless_management(super().get_queryset(), self.request.user, "user")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_destroy(self, instance):
        instance.deleted_by = self.request.user
        instance.delete()

    @extend_schema(
        tags=["employment"],
        summary="Jefe inmediato",
        description=(
            "Resuelve el jefe inmediato de este Empleado desde el organigrama "
            "(Contrato activo -> Posición -> reports_to -> quién la ocupa hoy). "
            "Un Colaborador solo puede consultar la suya propia — la misma "
            "restricción de queryset que list/retrieve. Todos los campos en "
            "null significa que no hay jefe resoluble hoy, no un error."
        ),
        responses=JefeSerializer,
    )
    @action(detail=True, methods=["get"])
    def jefe(self, request, pk=None):
        empleado = self.get_object()
        return Response(JefeSerializer(empleado.get_jefe()).data)

    @extend_schema(
        tags=["employment"],
        summary="Contrato vigente",
        description=(
            "El Contrato activo (sin fecha_baja) más reciente de este "
            "Empleado — reutiliza Empleado.get_contrato_activo(). "
            "Responde `null` (200) si no tiene ninguno, nunca un error."
        ),
        responses=ContratoSerializer,
    )
    @action(detail=True, methods=["get"], url_path="contrato-vigente")
    def contrato_vigente(self, request, pk=None):
        empleado = self.get_object()
        contrato = empleado.get_contrato_activo()
        if contrato is None:
            return Response(None)
        return Response(ContratoSerializer(contrato).data)
