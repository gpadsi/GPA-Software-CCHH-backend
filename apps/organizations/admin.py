from django.contrib import admin

from apps.core.admin import AuditableAdminMixin
from apps.organizations.models import (
    Company,
    OrganizationalLevel,
    OrganizationNode,
    Tenant,
)


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["code", "name"]
    search_fields = ["code", "name"]


@admin.register(OrganizationalLevel)
class OrganizationalLevelAdmin(admin.ModelAdmin):
    list_display = ["numero", "name", "code", "allows_recursive_nesting"]
    list_filter = ["allows_recursive_nesting"]
    search_fields = ["code", "name"]
    fields = ["numero", "code", "name", "allows_recursive_nesting"]


@admin.register(OrganizationNode)
class OrganizationNodeAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["code", "name", "level", "tenant", "is_active"]
    list_filter = ["level", "is_active"]
    autocomplete_fields = ["parent"]
    search_fields = ["code", "name"]
    # "tenant" se muestra pero no se elige: se autoasigna en OrganizationNode.save().
    readonly_fields = ["tenant"]
    fields = ["tenant", "level", "parent", "code", "name", "is_active"]


@admin.register(Company)
class CompanyAdmin(AuditableAdminMixin, admin.ModelAdmin):
    list_display = ["legal_name", "rfc", "organization_node"]
    search_fields = ["legal_name", "rfc", "employer_registration"]
    fields = ["organization_node", "legal_name", "rfc", "employer_registration"]
