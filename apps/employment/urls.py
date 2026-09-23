from rest_framework.routers import DefaultRouter

from apps.employment.views import (
    CausaBajaViewSet,
    ContratoViewSet,
    EmpleadoViewSet,
    HistorialSalarialViewSet,
    OrigenBajaViewSet,
)

router = DefaultRouter()
router.register("origenes-baja", OrigenBajaViewSet)
router.register("causas-baja", CausaBajaViewSet)
router.register("empleados", EmpleadoViewSet)
router.register("contratos", ContratoViewSet)
router.register("historial-salarial", HistorialSalarialViewSet)

urlpatterns = router.urls
