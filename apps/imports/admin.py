from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from apps.core.admin import AuditableAdminMixin
from apps.imports.models import (
    ColaboradorRawRow,
    HorarioRawRow,
    ImportBatch,
    PosicionRawRow,
    RawValueAlias,
)

# RawValueAlias solo debe poder apuntar a catálogos/entidades pensadas para
# resolver texto crudo — no a cualquier modelo del sistema (no tiene sentido
# aliasar hacia un Contrato o una sesión de login).
_ALIAS_ALLOWED_CONTENT_TYPES = Q(app_label="positions", model="puesto") \
    | Q(app_label="locations", model__in=["ubicacion", "nave", "area"]) \
    | Q(app_label="organizations", model="organizationnode") \
    | Q(app_label="persons", model="persona")


@admin.register(ImportBatch)
class ImportBatchAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["source", "original_filename", "created_at", "created_by"]
    list_filter = ["source"]
    search_fields = ["original_filename", "notes"]
    readonly_fields = ["created_by", "created_at"]


class _RawRowAdmin(admin.ModelAdmin):
    list_display = ["import_batch", "row_number"]
    list_filter = ["import_batch"]
    search_fields = ["row_number"]
    readonly_fields = ["import_batch", "row_number", "data"]

    def has_add_permission(self, request):
        # Estas filas las crea el comando de importación, no una persona a
        # mano — esta pantalla es solo para consultar/auditar lo que entró.
        return False


@admin.register(PosicionRawRow)
class PosicionRawRowAdmin(_RawRowAdmin):
    pass


@admin.register(ColaboradorRawRow)
class ColaboradorRawRowAdmin(_RawRowAdmin):
    pass


@admin.register(HorarioRawRow)
class HorarioRawRowAdmin(_RawRowAdmin):
    pass


@admin.register(RawValueAlias)
class RawValueAliasAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["domain", "raw_value_original", "raw_value", "content_type", "object_id"]
    list_filter = ["domain", "content_type"]
    search_fields = ["raw_value", "raw_value_original", "object_id"]
    autocomplete_fields = []

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "content_type":
            kwargs["queryset"] = ContentType.objects.filter(_ALIAS_ALLOWED_CONTENT_TYPES)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
