from rest_framework.routers import DefaultRouter

from apps.persons.views import (
    ContactoUrgenciaViewSet,
    EscolaridadViewSet,
    EstadoCivilViewSet,
    GeneroViewSet,
    PersonaViewSet,
    PerfilMedicoViewSet,
    TipoSangreViewSet,
)

router = DefaultRouter()
router.register("generos", GeneroViewSet)
router.register("estados-civiles", EstadoCivilViewSet)
router.register("escolaridades", EscolaridadViewSet)
router.register("tipos-sangre", TipoSangreViewSet)
router.register("personas", PersonaViewSet)
router.register("contactos-urgencia", ContactoUrgenciaViewSet)
router.register("perfiles-medicos", PerfilMedicoViewSet)

urlpatterns = router.urls
