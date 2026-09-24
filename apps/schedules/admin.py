from django.contrib import admin

from apps.core.admin import AuditableAdminMixin, NamedCatalogAdmin, catalog_form
from apps.schedules.models import AsignacionHorario, AsignacionUbicacion, Catorcena, TipoHorario


@admin.register(Catorcena)
class CatorcenaAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["numero", "anio", "fecha_inicio", "fecha_fin"]
    list_filter = ["anio"]
    search_fields = ["numero", "anio"]
    fields = ["numero", "anio", "fecha_inicio", "fecha_fin"]


@admin.register(TipoHorario)
class TipoHorarioAdmin(NamedCatalogAdmin):
    form = catalog_form(TipoHorario)
    list_display = ["name", "code", "descripcion", "is_active"]
    fields = ["name", "code", "descripcion", "is_active"]


@admin.register(AsignacionUbicacion)
class AsignacionUbicacionAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["empleado", "area", "fecha_referencia", "catorcena"]
    list_filter = ["catorcena"]
    autocomplete_fields = ["empleado", "area", "catorcena"]
    fields = ["empleado", "catorcena", "fecha_referencia", "area"]


@admin.register(AsignacionHorario)
class AsignacionHorarioAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["empleado", "tipo_horario", "fecha_referencia", "catorcena"]
    list_filter = ["catorcena", "tipo_horario"]
    autocomplete_fields = ["empleado", "tipo_horario", "catorcena"]
    fields = ["empleado", "catorcena", "fecha_referencia", "tipo_horario"]
