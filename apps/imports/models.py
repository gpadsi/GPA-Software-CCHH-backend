# apps/imports/models.py
# Infraestructura de importación (Fase A): guarda cada archivo cargado tal
# como llegó (staging crudo, sin transformar) y el mapeo de valores crudos
# a registros reales (RawValueAlias). NO decide nada de negocio por sí sola
# — eso lo hacen los comandos de importación de cada fuente (Fase B).
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core.models import BaseAuditModel


class ImportBatch(BaseAuditModel):
    """
    Una corrida de carga de un archivo fuente puntual. Agrupa las filas
    crudas que entraron juntas — sirve para saber de qué archivo/momento
    vino cada dato, y para poder comparar una carga contra la siguiente
    cuando llegue la sábana corregida.
    """
    SOURCE_SABANA_POSICIONES = "sabana_posiciones"
    SOURCE_COLABORADORES = "colaboradores"
    SOURCE_HORARIOS = "horarios"
    SOURCE_CHOICES = [
        (SOURCE_SABANA_POSICIONES, "Sábana — Posiciones"),
        (SOURCE_COLABORADORES, "Lista de Colaboradores"),
        (SOURCE_HORARIOS, "Relación de Horarios"),
    ]

    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, verbose_name="Origen")
    original_filename = models.CharField(max_length=255, verbose_name="Archivo original")
    notes = models.TextField(blank=True, verbose_name="Notas")

    def __str__(self):
        return f"{self.get_source_display()} — {self.original_filename} ({self.created_at:%Y-%m-%d %H:%M})"

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Lote de importación"
        verbose_name_plural = "Lotes de importación"


class _RawRow(BaseAuditModel):
    """
    Base abstracta de una fila cruda: tal cual llegó, sin validar ni
    transformar. `data` guarda {encabezado_original: valor_de_la_celda},
    no columnas fijas — así un cambio de encabezados en el Excel de GPA no
    exige una migración aquí, solo se refleja en el JSON.
    """
    import_batch = models.ForeignKey(
        ImportBatch, on_delete=models.CASCADE, related_name="%(class)ss",
        verbose_name="Lote de importación",
    )
    row_number = models.PositiveIntegerField(
        verbose_name="Fila en el Excel", help_text="Número de fila original, para poder ir a verificarla en el archivo fuente.",
    )
    data = models.JSONField(
        verbose_name="Datos crudos",
        help_text="Encabezado original de la columna -> valor tal cual venía en la celda.",
    )

    def __str__(self):
        return f"Lote {self.import_batch_id} — fila {self.row_number}"

    class Meta:
        abstract = True
        ordering = ["import_batch", "row_number"]


class PosicionRawRow(_RawRow):
    class Meta(_RawRow.Meta):
        verbose_name = "Fila cruda — Posiciones"
        verbose_name_plural = "Filas crudas — Posiciones"


class ColaboradorRawRow(_RawRow):
    class Meta(_RawRow.Meta):
        verbose_name = "Fila cruda — Colaboradores"
        verbose_name_plural = "Filas crudas — Colaboradores"


class HorarioRawRow(_RawRow):
    class Meta(_RawRow.Meta):
        verbose_name = "Fila cruda — Horarios"
        verbose_name_plural = "Filas crudas — Horarios"


class RawValueAlias(BaseAuditModel):
    """
    Traduce un valor de texto crudo (typo, mayúsculas, abreviación...) al
    registro real al que corresponde — sin importar de qué modelo se trate
    (Puesto, Ubicacion, Nave, Area, OrganizationNode...). Un solo mecanismo
    para todos los campos con este problema, en vez de una tabla de alias
    por catálogo.

    A propósito NO se llena solo: cuando un import encuentra un valor sin
    alias y sin match exacto contra un catálogo existente, lo reporta como
    "sin resolver" en vez de inventar un alias — alguien lo confirma primero
    (aquí, en el admin, o vía el propio comando de importación una vez
    confirmado en conversación).
    """
    domain = models.CharField(
        max_length=50, verbose_name="Dominio",
        help_text="Qué tipo de dato es, ej. «puesto», «ubicacion», «nave», «area», «organization_node».",
    )
    raw_value = models.CharField(
        max_length=255, verbose_name="Valor crudo (normalizado)",
        help_text="Mayúsculas, sin acentos, sin espacios extra — así se busca al importar.",
    )
    raw_value_original = models.CharField(
        max_length=255, blank=True, verbose_name="Valor crudo (tal cual)",
        help_text="Cómo venía exactamente en el archivo — solo para referencia humana.",
    )

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, verbose_name="Tipo de destino")
    object_id = models.CharField(max_length=40, verbose_name="ID del destino")
    target = GenericForeignKey("content_type", "object_id")

    def __str__(self):
        return f"[{self.domain}] {self.raw_value_original or self.raw_value} → {self.target}"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["domain", "raw_value"], name="unique_raw_value_alias_per_domain"),
        ]
        ordering = ["domain", "raw_value"]
        verbose_name = "Alias de valor crudo"
        verbose_name_plural = "Alias de valores crudos"
