# apps/schedules/models.py
# GPA organiza el tiempo por catorcena, no por fecha suelta — Catorcena es un
# concepto propio del sistema a propósito (no un rango de fechas libre)
# porque se va a reutilizar en más módulos además de horarios/ubicación.
#
# AsignacionUbicacion/AsignacionHorario existen porque un campo fijo
# (Posicion.area, o un futuro Empleado.horario) no alcanza para representar
# la realidad: la misma persona puede estar en un sitio/horario una catorcena
# y en otro la siguiente — a veces incluso varios vigentes a la vez. Se
# atan a Empleado (no a Contrato): la decisión original fue Contrato, pero
# se revirtió el 2026-09-24 al ver el caso real — Empleado existe desde que
# se importa Colaboradores, con o sin Contrato/Posición formal todavía, y
# horario/ubicación son operativos del día a día de la persona, no parte de
# la definición del puesto.
from django.db import models

from apps.core.models import BaseAuditModel, NamedCatalog


class Catorcena(BaseAuditModel):
    """
    Periodo de nómina de GPA (14 días). Deliberadamente NO se siembra un
    calendario aquí: las fechas de corte reales de GPA no están confirmadas
    todavía — esta tabla existe vacía hasta que se confirme el calendario
    real (ver management command de importación de horarios, pendiente por
    esa misma razón).
    """
    numero = models.PositiveSmallIntegerField(verbose_name="Número de catorcena")
    anio = models.PositiveSmallIntegerField(verbose_name="Año")
    fecha_inicio = models.DateField(verbose_name="Fecha de inicio")
    fecha_fin = models.DateField(verbose_name="Fecha de fin")

    def __str__(self):
        return f"Catorcena {self.numero}/{self.anio} ({self.fecha_inicio} – {self.fecha_fin})"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["numero", "anio"], name="unique_catorcena_numero_anio"),
        ]
        ordering = ["anio", "numero"]
        verbose_name = "Catorcena"
        verbose_name_plural = "Catorcenas"


class TipoHorario(NamedCatalog):
    """
    Código de horario de GPA (H01, H02...). `descripcion` guarda el texto tal
    como GPA lo maneja — algunos códigos agrupan varios rangos horarios
    separados por "/" porque representan una rotación entre catorcenas, no
    un horario único; esta tabla no lo desglosa todavía porque no tenemos el
    detalle de qué rango le tocó a quién en cada catorcena específica.
    """
    descripcion = models.CharField(
        max_length=255, blank=True, verbose_name="Horario",
        help_text="Texto tal como lo maneja GPA, ej. «07:00 - 16:00» o varios rangos separados por «/».",
    )

    class Meta(NamedCatalog.Meta):
        verbose_name = "Tipo de horario"
        verbose_name_plural = "Tipos de horario"


class AsignacionUbicacion(BaseAuditModel):
    empleado = models.ForeignKey(
        "employment.Empleado", on_delete=models.CASCADE,
        related_name="asignaciones_ubicacion", verbose_name="Empleado",
    )
    # TEMPORAL (2026-09-24): null=True/blank=True — ver apps/core/checks.py.
    # No existe todavía el calendario real de catorcenas de GPA; mientras
    # tanto se guarda `fecha_referencia` (un dato real que sí tenemos, ej.
    # fecha de registro en sistema) y esta FK se rellena después con un
    # backfill una vez que el calendario se confirme.
    catorcena = models.ForeignKey(
        Catorcena, on_delete=models.PROTECT, null=True, blank=True,
        related_name="asignaciones_ubicacion", verbose_name="Catorcena",
    )
    fecha_referencia = models.DateField(
        verbose_name="Fecha de referencia",
        help_text="Fecha real conocida (ej. de registro en sistema) mientras no se resuelve la catorcena exacta.",
    )
    area = models.ForeignKey(
        "locations.Area", on_delete=models.PROTECT,
        related_name="asignaciones_ubicacion", verbose_name="Área",
    )

    def __str__(self):
        periodo = self.catorcena or self.fecha_referencia
        return f"{self.empleado} — {self.area} ({periodo})"

    class Meta:
        ordering = ["-fecha_referencia"]
        verbose_name = "Asignación de ubicación"
        verbose_name_plural = "Asignaciones de ubicación"


class AsignacionHorario(BaseAuditModel):
    empleado = models.ForeignKey(
        "employment.Empleado", on_delete=models.CASCADE,
        related_name="asignaciones_horario", verbose_name="Empleado",
    )
    # TEMPORAL (2026-09-24): mismo motivo que AsignacionUbicacion.catorcena.
    catorcena = models.ForeignKey(
        Catorcena, on_delete=models.PROTECT, null=True, blank=True,
        related_name="asignaciones_horario", verbose_name="Catorcena",
    )
    fecha_referencia = models.DateField(
        verbose_name="Fecha de referencia",
        help_text="Fecha real conocida (ej. de registro en sistema) mientras no se resuelve la catorcena exacta.",
    )
    tipo_horario = models.ForeignKey(
        TipoHorario, on_delete=models.PROTECT,
        related_name="asignaciones", verbose_name="Tipo de horario",
    )

    def __str__(self):
        periodo = self.catorcena or self.fecha_referencia
        return f"{self.empleado} — {self.tipo_horario} ({periodo})"

    class Meta:
        ordering = ["-fecha_referencia"]
        verbose_name = "Asignación de horario"
        verbose_name_plural = "Asignaciones de horario"
