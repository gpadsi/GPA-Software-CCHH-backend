from rest_framework.routers import DefaultRouter

from apps.positions.views import (
    AlcanceDePosicionViewSet,
    EstatusPosicionViewSet,
    PosicionViewSet,
    PuestoViewSet,
    TipoPosicionViewSet,
    TipoRequisicionViewSet,
)

router = DefaultRouter()
router.register("alcances", AlcanceDePosicionViewSet)
router.register("tipos-posicion", TipoPosicionViewSet)
router.register("tipos-requisicion", TipoRequisicionViewSet)
router.register("estatus", EstatusPosicionViewSet)
router.register("puestos", PuestoViewSet)
router.register("posiciones", PosicionViewSet)

urlpatterns = router.urls
