from django.contrib import admin

from apps.core.admin import AuditableAdminMixin, NamedCatalogAdmin, catalog_form
from apps.positions.models import (
    AlcanceDePosicion,
    EstatusPosicion,
    HistorialReportaA,
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
    list_display = ["name", "code", "is_active", "es_gerencia_de_unidad"]
    list_filter = ["is_active", "es_gerencia_de_unidad"]
    fields = ["name", "code", "is_active", "es_gerencia_de_unidad"]


@admin.register(Posicion)
class PosicionAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["__str__", "organization_node", "estatus", "tipo_posicion"]
    list_filter = ["estatus", "alcance", "tipo_posicion", "tipo_requisicion"]
    search_fields = ["puesto__name", "area__name", "headhunter", "solicitante_vacante"]
    autocomplete_fields = ["organization_node", "area", "puesto", "reports_to"]
    fieldsets = (
        ("Ubicación en la estructura", {
            "fields": ("organization_node", "area", "puesto", "reports_to", "supervision_texto"),
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


@admin.register(HistorialReportaA)
class HistorialReportaAAdmin(admin.ModelAdmin):
    list_display = ["posicion", "reports_to", "fecha_inicio", "fecha_fin"]
    list_filter = ["fecha_fin"]
    search_fields = ["posicion__puesto__name", "reports_to__puesto__name"]
    autocomplete_fields = ["posicion", "reports_to"]
    fields = ["posicion", "reports_to", "fecha_inicio", "fecha_fin"]
    readonly_fields = ["posicion", "reports_to", "fecha_inicio", "fecha_fin"]

    def has_add_permission(self, request):
        # Se llena solo desde Posicion.save() — nadie lo captura a mano.
        return False
