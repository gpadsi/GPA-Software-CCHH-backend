from rest_framework.routers import DefaultRouter

from apps.organizations.views import (
    CompanyViewSet,
    OrganizationalLevelViewSet,
    OrganizationNodeViewSet,
    TenantViewSet,
)

router = DefaultRouter()
router.register("tenants", TenantViewSet)
router.register("levels", OrganizationalLevelViewSet)
router.register("nodes", OrganizationNodeViewSet)
router.register("companies", CompanyViewSet)

urlpatterns = router.urls
