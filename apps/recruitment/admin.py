import io
import zipfile

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import FileResponse

from apps.core.admin import AuditableAdminMixin, NamedCatalogAdmin, catalog_form
from apps.positions.models import TipoRequisicion
from apps.recruitment.exports import generar_excel
from apps.recruitment.exports_word import generar_word
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
    RequisicionNuevaPosicion,
    RequisicionReemplazo,
    RolConformidad,
    TipoContratoOfrecido,
)


_MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _descargar_oficiales(modeladmin, request, queryset, generar, mime, nombre_zip):
    """
    Respuesta de una accion del admin que baja los archivos oficiales (los
    mismos que entregan los endpoints exportar-excel / exportar-word): uno
    solo si se selecciono uno, un ZIP si se seleccionaron varios. Lo que no
    se pueda generar se avisa y se omite, no truena la pantalla. Devuelve
    None si ninguno se pudo generar (el admin vuelve a la lista con los avisos).
    """
    archivos = []
    for objeto in queryset:
        try:
            archivos.append(generar(objeto))
        except (ValueError, RuntimeError) as error:
            modeladmin.message_user(request, f"{objeto}: {error}", level=messages.ERROR)
    if not archivos:
        return None
    if len(archivos) == 1:
        nombre, buffer = archivos[0]
        return FileResponse(buffer, as_attachment=True, filename=nombre, content_type=mime)
    comprimido = io.BytesIO()
    # Los .xlsx/.docx ya vienen comprimidos: no se vuelven a comprimir.
    with zipfile.ZipFile(comprimido, "w", zipfile.ZIP_STORED) as paquete:
        for nombre, buffer in archivos:
            paquete.writestr(nombre, buffer.getvalue())
    comprimido.seek(0)
    return FileResponse(comprimido, as_attachment=True, filename=nombre_zip, content_type="application/zip")


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


class _RequisicionAdminBase(AuditableAdminMixin, admin.ModelAdmin):
    search_fields = ["posicion__puesto__name", "area_solicitante"]
    inlines = [AprobacionRequisicionInline]
    actions = ["descargar_excel_oficial"]

    def get_queryset(self, request):
        # Requisicion.objects ya no ve lo borrado (SoftDeleteModel) — el
        # admin sí debe seguir viéndolo, para auditarlo o deshacerlo.
        return self.model.all_objects.all()

    @admin.action(description="Descargar Excel oficial (uno, o un ZIP si seleccionas varias)", permissions=["view"])
    def descargar_excel_oficial(self, request, queryset):
        return _descargar_oficiales(
            self, request, queryset, generar_excel, _MIME_XLSX, "requisiciones_excel.zip",
        )


@admin.register(Requisicion)
class RequisicionAdmin(_RequisicionAdminBase):
    """Todas las Requisiciones, de cualquier tipo (para auditar). Cada tipo tiene además su propia lista."""
    list_display = ["posicion", "tipo", "estado", "fecha_solicitud", "is_deleted"]
    list_filter = ["tipo", "estado", "is_deleted"]
    autocomplete_fields = ["posicion", "tipo", "estado", "horario_a_cubrir", "tipo_contrato_ofrecido"]


class _RequisicionPorTipoAdmin(_RequisicionAdminBase):
    """
    Lista de un solo tipo de Requisición (Reemplazo o Nueva Posición), con su
    formulario oficial. El tipo lo da la lista: se pone solo al crear y no se
    puede cambiar desde aquí (cambiarlo movería la Requisición a la otra
    lista y a otro formulario; para eso está la lista "Requisiciones").
    """
    codigo_tipo = None  # TipoRequisicion.code
    list_display = ["posicion", "estado", "fecha_solicitud", "is_deleted"]
    list_filter = ["estado", "is_deleted"]
    autocomplete_fields = ["posicion", "estado", "horario_a_cubrir", "tipo_contrato_ofrecido"]
    readonly_fields = ["tipo"]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(tipo__code=self.codigo_tipo)

    def has_add_permission(self, request):
        # Sin el tipo en el catálogo (base nueva sin la sábana importada) no hay con qué crearla.
        return super().has_add_permission(request) and TipoRequisicion.objects.filter(code=self.codigo_tipo).exists()

    def get_form(self, request, obj=None, **kwargs):
        formulario = super().get_form(request, obj, **kwargs)
        tipo = TipoRequisicion.objects.filter(code=self.codigo_tipo).first()

        class _FormularioConTipo(formulario):
            def __init__(self, *args, **kw):
                super().__init__(*args, **kw)
                # Antes de validar: Requisicion.clean() necesita el tipo para
                # exigir la justificación de Nueva Posición.
                if self.instance.tipo_id is None:
                    self.instance.tipo = tipo

        return _FormularioConTipo


@admin.register(RequisicionReemplazo)
class RequisicionReemplazoAdmin(_RequisicionPorTipoAdmin):
    codigo_tipo = "reemplazo"


@admin.register(RequisicionNuevaPosicion)
class RequisicionNuevaPosicionAdmin(_RequisicionPorTipoAdmin):
    codigo_tipo = "nueva-posicion"


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
    actions = ["congelar_versiones", "descargar_word_oficial"]

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

    @admin.action(description="Descargar Word oficial (uno, o un ZIP si seleccionas varios)", permissions=["view"])
    def descargar_word_oficial(self, request, queryset):
        return _descargar_oficiales(
            self, request, queryset, generar_word, _MIME_DOCX, "descriptivos_word.zip",
        )
