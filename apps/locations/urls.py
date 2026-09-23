from rest_framework.routers import DefaultRouter

from apps.locations.views import AreaViewSet, NaveViewSet, UbicacionViewSet

router = DefaultRouter()
router.register("ubicaciones", UbicacionViewSet)
router.register("naves", NaveViewSet)
router.register("areas", AreaViewSet)

urlpatterns = router.urls
