from rest_framework.routers import DefaultRouter

from apps.recruitment.views import (
    AprobacionRequisicionViewSet,
    EstadoRequisicionViewSet,
    EtapaAprobacionViewSet,
    HorarioACubrirViewSet,
    RequisicionViewSet,
    TipoContratoOfrecidoViewSet,
)

router = DefaultRouter()
router.register("estados", EstadoRequisicionViewSet)
router.register("etapas-aprobacion", EtapaAprobacionViewSet)
router.register("tipos-contrato-ofrecido", TipoContratoOfrecidoViewSet)
router.register("horarios-a-cubrir", HorarioACubrirViewSet)
router.register("aprobaciones", AprobacionRequisicionViewSet)
router.register("requisiciones", RequisicionViewSet)

urlpatterns = router.urls
