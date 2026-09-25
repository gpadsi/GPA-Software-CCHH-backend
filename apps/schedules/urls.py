from rest_framework.routers import DefaultRouter

from apps.schedules.views import (
    AsignacionHorarioViewSet,
    AsignacionUbicacionViewSet,
    CatorcenaViewSet,
    TipoHorarioViewSet,
)

router = DefaultRouter()
router.register("catorcenas", CatorcenaViewSet)
router.register("tipos-horario", TipoHorarioViewSet)
router.register("asignaciones-ubicacion", AsignacionUbicacionViewSet)
router.register("asignaciones-horario", AsignacionHorarioViewSet)

urlpatterns = router.urls
