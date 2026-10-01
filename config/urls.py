"""
Configuración de URLs raíz del proyecto Capital Humano.

Cada app de dominio cuelga de /api/v1/<app>/ (ver config/settings/base.py para
la lista de apps instaladas). Se agregan aquí conforme se van creando.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    path("admin/", admin.site.urls),

    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),

    path("api/v1/", include("apps.users.urls")),
    path("api/v1/core/", include("apps.core.urls")),
    path("api/v1/organizations/", include("apps.organizations.urls")),
    path("api/v1/locations/", include("apps.locations.urls")),
    path("api/v1/persons/", include("apps.persons.urls")),
    path("api/v1/positions/", include("apps.positions.urls")),
    path("api/v1/employment/", include("apps.employment.urls")),
    path("api/v1/schedules/", include("apps.schedules.urls")),
    path("api/v1/recruitment/", include("apps.recruitment.urls")),
]

# Solo desarrollo: sirve CSS/JS del admin y archivos media mediante Django.
if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
