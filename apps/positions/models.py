from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseAuditModel, NamedCatalog
from apps.locations.models import Area
from apps.organizations.models import OrganizationNode
from apps.persons.models import Genero


class AlcanceDePosicion(NamedCatalog):
    """Confirmado con datos reales de GPA: Operativo, Ingeniería, Administración, Desarrollo de Negocios."""

    class Meta(NamedCatalog.Meta):
        verbose_name = "Alcance de posición"
        verbose_name_plural = "Alcances de posición"


class TipoPosicion(NamedCatalog):
    """Confirmado: Fija, Eventual, Reemplazo."""

    class Meta(NamedCatalog.Meta):
        verbose_name = "Tipo de posición"
        verbose_name_plural = "Tipos de posición"


class TipoRequisicion(NamedCatalog):
    """Confirmado: Reemplazo, Nueva Posición."""

    class Meta(NamedCatalog.Meta):
        verbose_name = "Tipo de requisición"
        verbose_name_plural = "Tipos de requisición"


class EstatusPosicion(NamedCatalog):
    """
    Confirmado con GPA, 8 valores exactos: Colaborador Activo/Baja, Trainee
    Activo/Baja, Vacante Pendiente de Confirmación/Activa/Suspendida/Eliminada.
    Una Posición puede existir SIN nadie ocupándola — por eso este catálogo
    vive en Posicion, no en Empleado.
    """

    class Meta(NamedCatalog.Meta):
        verbose_name = "Estatus de posición"
        verbose_name_plural = "Estatus de posición"


class Puesto(NamedCatalog):
    """
    Catálogo de títulos de puesto. Se deja SIN sembrar a propósito: los
    datos reales de GPA traen 241 valores en texto libre con inconsistencias
    (mayúsculas/minúsculas, abreviaciones tipo "Jr"/"Junior", hasta un
    "(Ninguno)" literal) — normalizar eso es trabajo de RH con la lista
    real, no algo que deba inventarse aquí.
    """

    class Meta(NamedCatalog.Meta):
        verbose_name = "Puesto"
        verbose_name_plural = "Puestos"


class Posicion(BaseAuditModel):
    """
    Una posición/plaza dentro de la estructura — puede estar vacante,
    en proceso de reclutamiento, o ocupada. Tiene DOS relaciones separadas
    a propósito: a quién reporta (estructura organizacional) y dónde está
    físicamente sentada (Ubicación/Nave/Área) — son dos dimensiones
    distintas que pueden no coincidir.
    """
    organization_node = models.ForeignKey(
        OrganizationNode, on_delete=models.PROTECT, related_name="posiciones",
        verbose_name="Unidad organizacional",
        help_text="A qué Unidad de Negocio/Empresa pertenece esta posición.",
    )
    # TEMPORAL (2026-09-23): null=True/blank=True en area y puesto — ver
    # apps/core/checks.py. Se queda on_delete=PROTECT (no cambia): eso solo
    # evita borrar un Area/Puesto todavía en uso, es independiente de que el
    # campo admita quedar vacío mientras no se ha asignado.
    area = models.ForeignKey(
        Area, on_delete=models.PROTECT, related_name="posiciones",
        null=True, blank=True,
        verbose_name="Área",
        help_text="Dónde está sentada físicamente (Ubicación → Nave → Área).",
    )
    puesto = models.ForeignKey(
        Puesto, on_delete=models.PROTECT, null=True, blank=True, verbose_name="Puesto",
    )
    reports_to = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT,
        related_name="reportes", verbose_name="Reporta a",
        help_text="La posición de la que depende — de aquí se resuelve el jefe inmediato.",
    )

    alcance = models.ForeignKey(
        AlcanceDePosicion, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Alcance de posición",
    )
    tipo_posicion = models.ForeignKey(
        TipoPosicion, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Tipo de posición",
    )
    tipo_requisicion = models.ForeignKey(
        TipoRequisicion, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Tipo de requisición",
    )
    estatus = models.ForeignKey(EstatusPosicion, on_delete=models.PROTECT, verbose_name="Estatus")
    genero_requerido = models.ForeignKey(
        Genero, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Género requerido",
        help_text="Requisito de la vacante, no el género de quien la ocupe.",
    )

    # Reclutamiento — ciclo de vida de la vacante, independiente de si ya
    # tiene a alguien asignado (eso vive en apps.employment.Contrato).
    fecha_registro_vacante = models.DateField(null=True, blank=True, verbose_name="Fecha de registro de vacante")
    fecha_autorizacion_vacante = models.DateField(null=True, blank=True, verbose_name="Fecha de autorización de vacante")
    headhunter = models.CharField(max_length=150, blank=True, verbose_name="Headhunter")
    solicitante_vacante = models.CharField(max_length=150, blank=True, verbose_name="Solicitante de vacante")
    proyecto_eventual = models.CharField(max_length=150, blank=True, verbose_name="Proyecto eventual")
    fecha_esperada_termino = models.DateField(null=True, blank=True, verbose_name="Fecha esperada de término")

    def clean(self):
        super().clean()
        if self.reports_to_id and self.reports_to_id == self.pk:
            raise ValidationError({"reports_to": "Una posición no puede reportar a sí misma."})

        ancestor = self.reports_to
        visited = set()
        while ancestor is not None:
            if ancestor.pk == self.pk:
                raise ValidationError({"reports_to": "Una posición no puede aparecer en su propia cadena de reporte."})
            if ancestor.pk in visited:
                break
            visited.add(ancestor.pk)
            ancestor = ancestor.reports_to

    def __str__(self):
        return f"{self.puesto} — {self.area}"

    class Meta:
        verbose_name = "Posición"
        verbose_name_plural = "Posiciones"
