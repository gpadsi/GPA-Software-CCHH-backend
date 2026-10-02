from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from apps.core.admin import AuditableAdminMixin, NamedCatalogAdmin, catalog_form
from apps.recruitment.models import (
    AprobacionRequisicion,
    CompetenciaConductual,
    ConformidadDescriptivo,
    DescriptivoPuesto,
    DiasPorLaborar,
    EstadoRequisicion,
    EtapaAprobacion,
    FuncionPuesto,
    HorarioACubrir,
    IndicadorDesempeno,
    RangoEdad,
    RecursoAsignado,
    Requisicion,
    RolConformidad,
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


@admin.register(RangoEdad)
class RangoEdadAdmin(NamedCatalogAdmin):
    form = catalog_form(RangoEdad)


@admin.register(DiasPorLaborar)
class DiasPorLaborarAdmin(NamedCatalogAdmin):
    form = catalog_form(DiasPorLaborar)


@admin.register(CompetenciaConductual)
class CompetenciaConductualAdmin(NamedCatalogAdmin):
    form = catalog_form(CompetenciaConductual)


@admin.register(RecursoAsignado)
class RecursoAsignadoAdmin(NamedCatalogAdmin):
    form = catalog_form(RecursoAsignado)


@admin.register(RolConformidad)
class RolConformidadAdmin(NamedCatalogAdmin):
    form = catalog_form(RolConformidad)
    list_display = ["name", "code", "is_active", "requiere_persona"]
    list_filter = ["is_active", "requiere_persona"]
    fields = ["name", "code", "is_active", "requiere_persona"]


class _ListaDeBorradorInline(admin.TabularInline):
    """Funciones e indicadores solo se editan mientras el Descriptivo es borrador."""
    extra = 0
    fields = ["orden", "texto"]

    def _congelado(self, obj):
        return obj is not None and obj.esta_congelado

    def has_add_permission(self, request, obj=None):
        return not self._congelado(obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return not self._congelado(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return not self._congelado(obj) and super().has_delete_permission(request, obj)


class FuncionPuestoInline(_ListaDeBorradorInline):
    model = FuncionPuesto


class IndicadorDesempenoInline(_ListaDeBorradorInline):
    model = IndicadorDesempeno


class ConformidadDescriptivoInline(admin.TabularInline):
    model = ConformidadDescriptivo
    extra = 0
    fields = ["rol", "persona", "fecha", "usuario", "nombre_manual"]

    def has_add_permission(self, request, obj=None):
        # Solo se da conformidad sobre una versión ya congelada.
        return obj is not None and obj.esta_congelado and super().has_add_permission(request, obj)


@admin.register(DescriptivoPuesto)
class DescriptivoPuestoAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["posicion", "version", "nombre_puesto", "fecha_elaboracion", "congelado_en", "is_deleted"]
    list_filter = ["is_deleted"]
    search_fields = ["nombre_puesto", "posicion__puesto__name"]
    autocomplete_fields = ["posicion", "edad", "dias_por_laborar", "horario"]
    filter_horizontal = ["competencias", "recursos"]
    readonly_fields = ["version", "congelado_en"]
    inlines = [FuncionPuestoInline, IndicadorDesempenoInline, ConformidadDescriptivoInline]
    actions = ["congelar_versiones"]

    def get_queryset(self, request):
        return DescriptivoPuesto.all_objects.all()

    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.esta_congelado:
            # Una versión congelada es solo lectura -- el modelo igual lo
            # impide, esto evita que el admin truene en vez de avisar.
            return [campo.name for campo in obj._meta.fields if campo.name != "id"] + ["competencias", "recursos"]
        return base

    @admin.action(description="Congelar las versiones seleccionadas (quedan inmutables)")
    def congelar_versiones(self, request, queryset):
        for descriptivo in queryset:
            try:
                descriptivo.congelar(user=request.user)
            except ValidationError as error:
                self.message_user(request, f"{descriptivo}: {' '.join(error.messages)}", level=messages.WARNING)
            else:
                self.message_user(request, f"{descriptivo}: congelada.")
