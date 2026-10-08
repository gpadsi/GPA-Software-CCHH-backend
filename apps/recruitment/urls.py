from rest_framework.routers import DefaultRouter

from apps.recruitment.views import (
    AprobacionRequisicionViewSet,
    CompetenciaConductualViewSet,
    ConformidadDescriptivoViewSet,
    DescriptivoPuestoViewSet,
    DiasPorLaborarViewSet,
    EstadoRequisicionViewSet,
    EtapaAprobacionViewSet,
    HorarioACubrirViewSet,
    PosicionesElegiblesViewSet,
    RangoEdadViewSet,
    RecursoAsignadoViewSet,
    RequisicionViewSet,
    RolConformidadViewSet,
    TipoContratoOfrecidoViewSet,
)

router = DefaultRouter()
# El registro expone el listado y el detalle de contexto por UUID.
router.register("posiciones-elegibles", PosicionesElegiblesViewSet, basename="posiciones-elegibles")
router.register("estados", EstadoRequisicionViewSet)
router.register("etapas-aprobacion", EtapaAprobacionViewSet)
router.register("tipos-contrato-ofrecido", TipoContratoOfrecidoViewSet)
router.register("horarios-a-cubrir", HorarioACubrirViewSet)
router.register("aprobaciones", AprobacionRequisicionViewSet)
router.register("requisiciones", RequisicionViewSet)
router.register("rangos-edad", RangoEdadViewSet)
router.register("dias-por-laborar", DiasPorLaborarViewSet)
router.register("competencias-conductuales", CompetenciaConductualViewSet)
router.register("recursos-asignados", RecursoAsignadoViewSet)
router.register("roles-conformidad", RolConformidadViewSet)
router.register("descriptivos", DescriptivoPuestoViewSet)
router.register("conformidades-descriptivo", ConformidadDescriptivoViewSet)

urlpatterns = router.urls
