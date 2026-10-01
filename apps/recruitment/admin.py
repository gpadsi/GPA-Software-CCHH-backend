from django.contrib import admin

from apps.core.admin import AuditableAdminMixin, NamedCatalogAdmin, catalog_form
from apps.recruitment.models import (
    AprobacionRequisicion,
    EstadoRequisicion,
    EtapaAprobacion,
    HorarioACubrir,
    Requisicion,
    TipoContratoOfrecido,
)


@admin.register(EstadoRequisicion)
class EstadoRequisicionAdmin(NamedCatalogAdmin):
    form = catalog_form(EstadoRequisicion)
    list_display = ["name", "code", "is_active", "es_terminal"]
    list_filter = ["is_active", "es_terminal"]
    fields = ["name", "code", "is_active", "es_terminal"]


@admin.register(EtapaAprobacion)
class EtapaAprobacionAdmin(NamedCatalogAdmin):
    form = catalog_form(EtapaAprobacion)


@admin.register(TipoContratoOfrecido)
class TipoContratoOfrecidoAdmin(NamedCatalogAdmin):
    form = catalog_form(TipoContratoOfrecido)


@admin.register(HorarioACubrir)
class HorarioACubrirAdmin(NamedCatalogAdmin):
    form = catalog_form(HorarioACubrir)


class AprobacionRequisicionInline(admin.TabularInline):
    model = AprobacionRequisicion
    extra = 0
    fields = ["etapa", "fecha", "usuario", "nombre_manual"]


@admin.register(Requisicion)
class RequisicionAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["posicion", "tipo", "estado", "fecha_solicitud", "is_deleted"]
    list_filter = ["tipo", "estado", "is_deleted"]
    search_fields = ["posicion__puesto__name", "area_solicitante"]
    autocomplete_fields = ["posicion", "tipo", "estado", "horario_a_cubrir", "tipo_contrato_ofrecido"]
    inlines = [AprobacionRequisicionInline]

    def get_queryset(self, request):
        # Requisicion.objects ya no ve lo borrado (SoftDeleteModel) — el
        # admin sí debe seguir viéndolo, para auditarlo o deshacerlo.
        return Requisicion.all_objects.all()
