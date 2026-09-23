from django.contrib import admin

from apps.core.admin import AuditableAdminMixin
from apps.locations.models import Area, Nave, Ubicacion


@admin.register(Ubicacion)
class UbicacionAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["code", "name", "employer_registration", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["code", "name", "employer_registration"]
    fields = ["code", "name", "employer_registration", "is_active"]


@admin.register(Nave)
class NaveAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["code", "ubicacion", "name", "is_active"]
    list_filter = ["ubicacion", "is_active"]
    search_fields = ["code", "name"]
    autocomplete_fields = ["ubicacion"]
    fields = ["ubicacion", "code", "name", "is_active"]


@admin.register(Area)
class AreaAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["name", "nave", "code", "is_active"]
    list_filter = ["nave__ubicacion", "is_active"]
    search_fields = ["code", "name"]
    autocomplete_fields = ["nave"]
    fields = ["nave", "code", "name", "is_active"]
