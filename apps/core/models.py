# apps/core/models.py
# Kernel compartido del proyecto. El resto de las apps depende de core;
# core no depende de ninguna otra app (base del grafo de dependencias).
import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class NamedCatalog(models.Model):
    """
    Base abstracta para catálogos simples: código + nombre + activo. El
    código se autogenera desde el nombre en save() si no se da explícito —
    mismo patrón que apps.core.DocumentType, ya probado (admin con
    prepopulated_fields + widget readonly). Un catálogo con campos extra
    (ej. una FK a otro catálogo, como CausaBaja -> OrigenBaja) hereda de aquí
    y agrega lo que necesite, sin repetir code/name/is_active/save().
    """
    code = models.SlugField(
        max_length=50,
        unique=True,
        blank=True,
        verbose_name="Código",
        help_text="Identificador interno. Se genera solo a partir del Nombre.",
    )
    name = models.CharField(max_length=150, verbose_name="Nombre")
    is_active = models.BooleanField(default=True, verbose_name="Activo")

    def save(self, *args, **kwargs):
        if not self.code:
            max_length = self._meta.get_field("code").max_length
            # Trunca ANTES de generar el slug completo: un nombre largo (ej.
            # un título de puesto largo) no debe tronar al guardar solo
            # porque el código autogenerado se pasa del límite de la columna.
            base_code = slugify(self.name)[:max_length]
            code, counter = base_code, 1
            while type(self).objects.filter(code=code).exclude(pk=self.pk).exists():
                suffix = f"-{counter}"
                code = base_code[: max_length - len(suffix)] + suffix
                counter += 1
            self.code = code
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        abstract = True
        ordering = ["name"]


class BaseAuditModel(models.Model):
    """
    Modelo base abstracto. Toda entidad OPERATIVA del sistema hereda de aquí
    (los catálogos de valores controlados son tablas aparte, sin enum, y no
    necesariamente heredan de este modelo si son solo id/código/etiqueta).

    - UUID como PK: evita enumeración y facilita federación futura.
    - Soft delete: is_deleted/deleted_at/deleted_by — nada se borra de verdad
      por default, así que el historial nunca desaparece por accidente.
    - Auditoría de usuario: created_by/updated_by/deleted_by, con
      related_name dinámico por modelo para no chocar entre apps.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    is_deleted = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_created_by",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_updated_by",
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_deleted_by",
    )

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        # Borrado en bloque (ej. "Delete selected" del admin) también se
        # marca — sin esto, solo el borrado de un objeto a la vez pasaría por
        # el delete() de abajo.
        return super().update(is_deleted=True, deleted_at=timezone.now())


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)


class SoftDeleteAllManager(models.Manager):
    def get_queryset(self):
        # Incluye los registros marcados, pero conserva el QuerySet cuyo
        # delete() hace borrado suave. Esto importa en el admin: sus vistas
        # usan all_objects para mostrar el historial y delete_selected llama
        # queryset.delete() sobre ese mismo manager.
        return SoftDeleteQuerySet(self.model, using=self._db)


class SoftDeleteModel(BaseAuditModel):
    """
    BaseAuditModel ya trae is_deleted/deleted_at/deleted_by pero, por sí
    solos, no borran nada distinto — esta variante sí los usa. `objects` (el
    manager normal) deja de ver lo marcado; `all_objects` lo sigue viendo,
    para el admin y para que una ForeignKey hacia un registro ya marcado
    (ej. Contrato.empleado) lo siga resolviendo en vez de romperse
    (`base_manager_name` lo deja explícito: sin esto Django usaría `objects`
    también ahí, y una FK hacia un registro marcado dejaría de resolver).

    No es el default de BaseAuditModel a propósito — cambiar el
    comportamiento de borrado de todo el proyecto de golpe, sin revisarlo
    modelo por modelo, es más riesgo del que pide este cambio. Úsalo donde
    de verdad importe conservar el historial ante un borrado (hoy: Empleado,
    Contrato).
    """
    objects = SoftDeleteManager()
    all_objects = SoftDeleteAllManager()

    def delete(self, *args, **kwargs):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    class Meta(BaseAuditModel.Meta):
        abstract = True
        base_manager_name = "all_objects"


class DocumentType(models.Model):
    """
    Catálogo de tipos de documento (expediente de persona, de puesto, etc.).
    Tabla y no enum, a propósito: se agrega un tipo nuevo con un registro
    (ver el management command `seed_document_types`), sin tocar código ni
    correr una migración.
    """
    code = models.SlugField(
        max_length=50,
        unique=True,
        blank=True,
        verbose_name="Código",
        help_text="Identificador interno, sin espacios. Déjalo vacío: se genera solo a partir del Nombre.",
    )
    name = models.CharField(
        max_length=150,
        verbose_name="Nombre",
        help_text="Nombre tal como se va a mostrar, ej. «Acta de nacimiento» o «INE».",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo",
        help_text="Desactívalo para retirar este tipo sin borrar el historial de archivos que ya lo usan.",
    )

    def save(self, *args, **kwargs):
        if not self.code:
            # Guiones, no guiones bajos: es lo mismo que produce el JS de
            # Django (prepopulated_fields) en el admin. Si aquí se generara
            # distinto a lo que ve la mayoría de la gente al llenar el
            # formulario, "acta-de-nacimiento" (admin) y "acta_de_nacimiento"
            # (API/consola) terminarían siendo dos códigos distintos para lo
            # mismo.
            base_code = slugify(self.name)
            code, counter = base_code, 1
            while DocumentType.objects.filter(code=code).exclude(pk=self.pk).exists():
                code = f"{base_code}_{counter}"
                counter += 1
            self.code = code
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "document_types"
        ordering = ["name"]
        verbose_name = "Tipo de documento"
        verbose_name_plural = "Tipos de documento"


def _attachment_upload_path(instance, filename):
    """Organiza los archivos por tipo de modelo: media/attachments/<model>/<filename>."""
    model_name = instance.content_type.model if instance.content_type_id else "misc"
    return f"attachments/{model_name}/{filename}"


class Attachment(models.Model):
    """
    Archivo adjunto genérico, vinculable a cualquier modelo del proyecto vía
    GenericForeignKey — no se ata a una sola entidad (expediente de persona,
    documento de puesto, contrato, etc. pueden usar el mismo mecanismo).
    """
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name="Tipo de objeto",
    )
    # CharField(40): soporta tanto UUID (36 chars) como PKs enteros como string.
    object_id = models.CharField(max_length=40, db_index=True, verbose_name="ID del objeto")
    content_object = GenericForeignKey("content_type", "object_id")

    # Qué CLASE de documento es (Acta de nacimiento, INE, ...) — distinto de
    # content_type/object_id, que dicen A QUÉ REGISTRO se engancha el archivo.
    document_type = models.ForeignKey(
        "core.DocumentType",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attachments",
        verbose_name="Tipo de documento",
    )

    file = models.FileField(upload_to=_attachment_upload_path, verbose_name="Archivo")
    filename = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Nombre del archivo",
        help_text="Se auto-completa con el nombre del archivo subido.",
    )

    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="Subido el")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_attachments",
        verbose_name="Subido por",
    )

    def save(self, *args, **kwargs):
        if self.file and not self.filename:
            self.filename = self.file.name.split("/")[-1]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.filename or str(self.file)

    class Meta:
        db_table = "attachments"
        ordering = ["-uploaded_at"]
        verbose_name = "Archivo adjunto"
        verbose_name_plural = "Archivos adjuntos"
