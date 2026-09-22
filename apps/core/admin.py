from django import forms
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from apps.core.models import Attachment, DocumentType


class DocumentTypeAdminForm(forms.ModelForm):
    """
    "Código" se muestra readonly (no se puede escribir a mano) y Django lo va
    generando en vivo, letra por letra, a partir de "Nombre" — vía
    `prepopulated_fields` de abajo. `readonly` (atributo HTML) y no
    `disabled`: readonly bloquea la edición manual pero SÍ manda su valor al
    guardar; `disabled` no lo mandaría y el campo llegaría vacío al servidor.
    """
    class Meta:
        model = DocumentType
        fields = "__all__"
        widgets = {
            "code": forms.TextInput(attrs={"readonly": "readonly"}),
        }

# Tablas puramente técnicas que nunca deberían ser destino de un adjunto
# (nadie le cuelga un archivo a una sesión de login o a un permiso). Como
# todavía no existen las apps de dominio (Persona, Puesto...), sin este
# filtro el selector de "Tipo de objeto" muestra TODO lo que existe en el
# sistema — confuso para quien no sabe que es un detalle interno de Django.
_HIDDEN_CONTENT_TYPES = (
    Q(app_label="admin", model="logentry")
    | Q(app_label="contenttypes", model="contenttype")
    | Q(app_label="sessions", model="session")
    | Q(app_label="token_blacklist")
    | Q(app_label="auth", model__in=["permission", "group"])
    | Q(app_label="core", model__in=["attachment", "documenttype"])
)


class AuditableAdminMixin:
    """
    Para el ModelAdmin de cualquier modelo que herede BaseAuditModel: completa
    created_by/updated_by con el usuario que hace la acción en el admin, igual
    que ya hacen los serializers del lado de la API (ver AttachmentSerializer).

    Sin esto, todo lo creado/editado desde el admin queda con auditoría de
    usuario en NULL — justo lo que BaseAuditModel existe para evitar. Cada
    ModelAdmin de una app de dominio futura debe heredar de este mixin.
    """
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    form = DocumentTypeAdminForm
    list_display = ["name", "code", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["name", "code"]
    # Nombre primero: es lo que alguien realmente piensa al crear un tipo
    # nuevo ("Acta de nacimiento"); el código se genera solo a partir de eso.
    fields = ["name", "code", "is_active"]
    # JS nativo del admin de Django: mientras escribes en "Nombre", va
    # actualizando "Código" en vivo con la versión slugificada. Combinado con
    # el widget readonly de arriba, queda como una vista previa, no como un
    # campo que se pueda tocar.
    prepopulated_fields = {"code": ("name",)}


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ["filename", "document_type", "content_type", "object_id", "uploaded_by", "uploaded_at"]
    list_filter = ["document_type", "content_type"]
    search_fields = ["filename", "object_id"]
    # No seleccionable a mano: se autocompleta con save_model() de abajo.
    # readonly_fields lo saca del formulario (no aparece como algo por elegir)
    # y lo sigue mostrando en la vista de detalle una vez guardado.
    readonly_fields = ["uploaded_by"]

    def has_add_permission(self, request):
        # Nadie debe crear un Attachment desde esta pantalla genérica: exige
        # elegir "Tipo de objeto" e "ID del objeto" a mano, que no tiene
        # sentido para un humano. La creación real ocurrirá desde un inline
        # en la ficha de cada entidad (Persona, Puesto...) o desde la API,
        # donde esos dos valores ya se conocen y se llenan solos. Esta vista
        # se deja solo para listar/buscar/borrar lo que ya existe.
        return False

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "content_type":
            kwargs["queryset"] = ContentType.objects.exclude(_HIDDEN_CONTENT_TYPES)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        # "Subido por" se autocompleta con quien está logueado — no se elige
        # a mano, igual que ocurre del lado de la API.
        if not obj.uploaded_by_id:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)
