from django.contrib import admin

from apps.core.admin import AuditableAdminMixin, NamedCatalogAdmin, catalog_form
from apps.persons.models import (
    ContactoUrgencia,
    Escolaridad,
    EstadoCivil,
    Genero,
    Persona,
    PerfilMedico,
    TipoSangre,
)

@admin.register(Genero)
class GeneroAdmin(NamedCatalogAdmin):
    form = catalog_form(Genero)


@admin.register(EstadoCivil)
class EstadoCivilAdmin(NamedCatalogAdmin):
    form = catalog_form(EstadoCivil)


@admin.register(Escolaridad)
class EscolaridadAdmin(NamedCatalogAdmin):
    form = catalog_form(Escolaridad)


@admin.register(TipoSangre)
class TipoSangreAdmin(NamedCatalogAdmin):
    form = catalog_form(TipoSangre)


class ContactoUrgenciaInline(admin.TabularInline):
    model = ContactoUrgencia
    extra = 0
    fields = ["name", "relationship", "phone"]


class PerfilMedicoInline(admin.StackedInline):
    model = PerfilMedico
    extra = 0
    max_num = 1
    fields = ["blood_type", "allergies"]


@admin.register(Persona)
class PersonaAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["__str__", "curp", "nss", "gender", "is_deleted"]
    list_filter = ["gender", "marital_status", "is_deleted"]
    search_fields = ["first_name", "last_name_paternal", "last_name_maternal", "curp", "nss", "rfc"]
    inlines = [ContactoUrgenciaInline, PerfilMedicoInline]
    fieldsets = (
        ("Identidad", {
            "fields": (
                ("first_name", "last_name_paternal", "last_name_maternal"),
                ("curp", "nss", "rfc"),
                ("birth_date", "birth_place_state"),
                ("gender", "marital_status", "education_level", "has_children"),
            ),
        }),
        ("Contacto", {
            "fields": ("personal_email", "phone"),
        }),
        ("Domicilio", {
            "fields": (
                "address_line",
                ("postal_code", "city", "municipality", "state"),
            ),
        }),
    )
