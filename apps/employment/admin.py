from django import forms
from django.contrib import admin

from apps.core.admin import AuditableAdminMixin, NamedCatalogAdmin, catalog_form
from apps.employment.models import CausaBaja, Contrato, Empleado, HistorialSalarial, OrigenBaja


@admin.register(OrigenBaja)
class OrigenBajaAdmin(NamedCatalogAdmin):
    form = catalog_form(OrigenBaja)


class CausaBajaAdminForm(forms.ModelForm):
    class Meta:
        model = CausaBaja
        fields = "__all__"
        widgets = {"code": forms.TextInput(attrs={"readonly": "readonly"})}


@admin.register(CausaBaja)
class CausaBajaAdmin(NamedCatalogAdmin):
    form = CausaBajaAdminForm
    list_display = ["name", "origen_baja", "code", "is_active"]
    list_filter = ["origen_baja", "is_active"]
    fields = ["origen_baja", "name", "code", "is_active"]
    autocomplete_fields = ["origen_baja"]


class HistorialSalarialInline(admin.TabularInline):
    model = HistorialSalarial
    extra = 0
    fields = ["monto", "fecha_vigencia"]


@admin.register(Empleado)
class EmpleadoAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["work_number", "persona", "user", "is_deleted"]
    list_filter = ["is_deleted"]
    search_fields = ["work_number", "persona__first_name", "persona__last_name_paternal", "persona__last_name_maternal"]
    autocomplete_fields = ["persona", "user"]
    fields = ["persona", "user", "work_number"]
    inlines = [HistorialSalarialInline]

    def get_queryset(self, request):
        # Empleado.objects ya no ve lo borrado (SoftDeleteModel) — el admin sí
        # debe seguir viéndolo, para poder auditarlo o deshacerlo a mano.
        return Empleado.all_objects.all()


@admin.register(Contrato)
class ContratoAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["empleado", "posicion", "fecha_ingreso", "fecha_baja", "is_deleted"]
    list_filter = ["origen_baja", "causa_baja", "considerado_para_reingreso", "is_deleted"]
    search_fields = ["empleado__work_number", "empleado__persona__first_name", "empleado__persona__last_name_paternal"]
    autocomplete_fields = ["empleado", "posicion", "origen_baja", "causa_baja"]

    def get_queryset(self, request):
        return Contrato.all_objects.all()
    fieldsets = (
        (None, {"fields": ("empleado", "posicion")}),
        ("Fechas", {"fields": (("fecha_ingreso", "fecha_alta"), ("fecha_reingreso", "fecha_baja"))}),
        ("Baja", {"fields": (
            "origen_baja", "causa_baja", "solicitante_baja",
            "considerado_para_reingreso", "observaciones",
        )}),
    )
