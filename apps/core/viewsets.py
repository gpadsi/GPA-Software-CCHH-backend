# apps/core/viewsets.py
from rest_framework import mixins, viewsets

from apps.core.permissions import IsCapitalHumanoOrAdminOrReadOnly


class EditableCatalogViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Catálogo que todos leen y solo Capital Humano/Admin crea y edita. NO se
    borra: otros registros apuntan a cada valor (una Posición a su Puesto, una
    Asignación a su Tipo de horario) y un catálogo que desaparece rompe ese
    historial. Lo que ya no se usa se desmarca con `is_active`.
    """

    permission_classes = [IsCapitalHumanoOrAdminOrReadOnly]
