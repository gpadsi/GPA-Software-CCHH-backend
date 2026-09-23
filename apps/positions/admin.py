from django.contrib import admin

from apps.core.admin import AuditableAdminMixin, NamedCatalogAdmin, catalog_form
from apps.positions.models import (
    AlcanceDePosicion,
    EstatusPosicion,
    Posicion,
    Puesto,
    TipoPosicion,
    TipoRequisicion,
)


@admin.register(AlcanceDePosicion)
class AlcanceDePosicionAdmin(NamedCatalogAdmin):
    form = catalog_form(AlcanceDePosicion)


@admin.register(TipoPosicion)
class TipoPosicionAdmin(NamedCatalogAdmin):
    form = catalog_form(TipoPosicion)


@admin.register(TipoRequisicion)
class TipoRequisicionAdmin(NamedCatalogAdmin):
    form = catalog_form(TipoRequisicion)


@admin.register(EstatusPosicion)
class EstatusPosicionAdmin(NamedCatalogAdmin):
    form = catalog_form(EstatusPosicion)


@admin.register(Puesto)
class PuestoAdmin(NamedCatalogAdmin):
    form = catalog_form(Puesto)


@admin.register(Posicion)
class PosicionAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["__str__", "organization_node", "estatus", "tipo_posicion"]
    list_filter = ["estatus", "alcance", "tipo_posicion", "tipo_requisicion"]
    search_fields = ["puesto__name", "area__name", "headhunter", "solicitante_vacante"]
    autocomplete_fields = ["organization_node", "area", "puesto", "reports_to"]
    fieldsets = (
        ("Ubicación en la estructura", {
            "fields": ("organization_node", "area", "puesto", "reports_to"),
        }),
        ("Clasificación", {
            "fields": ("alcance", "tipo_posicion", "tipo_requisicion", "estatus", "genero_requerido"),
        }),
        ("Reclutamiento", {
            "fields": (
                ("fecha_registro_vacante", "fecha_autorizacion_vacante"),
                "headhunter", "solicitante_vacante",
                ("proyecto_eventual", "fecha_esperada_termino"),
            ),
        }),
    )
