from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, viewsets

from apps.employment.models import CausaBaja, Contrato, Empleado, HistorialSalarial, OrigenBaja
from apps.employment.serializers import (
    CausaBajaSerializer,
    ContratoSerializer,
    EmpleadoSerializer,
    HistorialSalarialSerializer,
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


def _crud_viewset(target_model, target_serializer_class):
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
        permission_classes = [permissions.IsAuthenticated]

        def perform_create(self, serializer):
            serializer.save(created_by=self.request.user, updated_by=self.request.user)

        def perform_update(self, serializer):
            serializer.save(updated_by=self.request.user)

    _ViewSet.__name__ = f"{target_model.__name__}ViewSet"
    return _ViewSet


OrigenBajaViewSet = _catalog_viewset(OrigenBaja, OrigenBajaSerializer)
CausaBajaViewSet = _catalog_viewset(CausaBaja, CausaBajaSerializer)
EmpleadoViewSet = _crud_viewset(Empleado, EmpleadoSerializer)
ContratoViewSet = _crud_viewset(Contrato, ContratoSerializer)
HistorialSalarialViewSet = _crud_viewset(HistorialSalarial, HistorialSalarialSerializer)
