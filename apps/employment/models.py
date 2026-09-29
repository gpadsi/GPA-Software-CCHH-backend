from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseAuditModel, NamedCatalog, SoftDeleteModel
from apps.persons.models import Persona
from apps.positions.models import Posicion


class OrigenBaja(NamedCatalog):
    """Confirmado con GPA, 5 valores exactos: Renuncia, Despido, Abandono, Terminación de Contrato, Mutuo Acuerdo."""

    class Meta(NamedCatalog.Meta):
        verbose_name = "Origen de baja"
        verbose_name_plural = "Orígenes de baja"


class CausaBaja(NamedCatalog):
    """
    Depende de OrigenBaja — no es un catálogo plano. Cada origen tiene sus
    propias causas (Renuncia: 12, Despido: 5, Abandono: 2, Terminación de
    Contrato: 2, Mutuo Acuerdo: 4 — todas confirmadas con GPA). La UI debe
    filtrar las causas visibles según el origen ya elegido.
    """
    origen_baja = models.ForeignKey(
        OrigenBaja, on_delete=models.PROTECT, related_name="causas",
        verbose_name="Origen de baja",
    )

    class Meta(NamedCatalog.Meta):
        constraints = [
            models.UniqueConstraint(fields=["origen_baja", "code"], name="unique_causa_baja_code_per_origen"),
        ]
        verbose_name = "Causa de baja"
        verbose_name_plural = "Causas de baja"


class Empleado(SoftDeleteModel):
    """
    La relación laboral. `user` es OPCIONAL a propósito: no todo Empleado
    tiene o necesita cuenta de acceso al sistema. El rol de sistema
    (Colaborador/Capital Humano/Admin) vive en User, no aquí — "ser jefe de
    alguien" no es un rol, se resuelve vía Posicion.reports_to.

    SoftDeleteModel (no BaseAuditModel directo): un Empleado nunca se borra
    de verdad — es el expediente laboral completo, y su Contrato depende de
    que siga existiendo.
    """
    persona = models.OneToOneField(
        Persona, on_delete=models.PROTECT, related_name="empleado",
        verbose_name="Persona",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="empleado", verbose_name="Usuario del sistema",
        help_text="Opcional — no todo empleado necesita una cuenta de acceso.",
    )
    # TEMPORAL (2026-09-23): null=True/blank=True — ver apps/core/checks.py,
    # mismo motivo que Persona.curp/nss/rfc.
    work_number = models.CharField(max_length=30, unique=True, null=True, blank=True, verbose_name="Número de nómina")

    def get_contrato_activo(self):
        """El Contrato vigente (sin fecha_baja) más reciente, si hay alguno."""
        return self.contratos.filter(fecha_baja__isnull=True).first()

    def get_jefe(self):
        """
        Resuelve el jefe inmediato desde el organigrama, siempre al vuelo (no
        se guarda en ningún lado): Contrato activo -> su Posición -> a qué
        Posición reporta esa -> quién la ocupa hoy con un Contrato activo.
        Cualquiera de esos eslabones puede faltar (sin Contrato activo, sin
        reports_to por ser el nivel más alto, o posición de jefe vacante) —
        en esos casos se regresan los campos correspondientes en None, nunca
        se inventa un jefe.
        """
        contrato_activo = self.get_contrato_activo()
        posicion_actual = contrato_activo.posicion if contrato_activo else None
        posicion_jefe = posicion_actual.reports_to if posicion_actual else None

        contrato_jefe = None
        if posicion_jefe is not None:
            contrato_jefe = Contrato.objects.filter(
                posicion=posicion_jefe, fecha_baja__isnull=True
            ).first()
        empleado_jefe = contrato_jefe.empleado if contrato_jefe else None

        return {
            "posicion_id": posicion_jefe.id if posicion_jefe else None,
            "puesto": posicion_jefe.puesto.name if (posicion_jefe and posicion_jefe.puesto) else None,
            "empleado_id": empleado_jefe.id if empleado_jefe else None,
            "nombre": str(empleado_jefe.persona) if empleado_jefe else None,
        }

    def __str__(self):
        return f"{self.work_number} — {self.persona}"

    class Meta(SoftDeleteModel.Meta):
        verbose_name = "Empleado"
        verbose_name_plural = "Empleados"


class Contrato(SoftDeleteModel):
    """
    Historial: qué Posición ocupó un Empleado, desde cuándo, hasta cuándo.
    ingreso/alta/reingreso son tres fechas independientes, NINGUNA se deriva
    de las otras (confirmado explícitamente por el usuario).

    SoftDeleteModel: es el historial laboral en sí — borrarlo de verdad
    borraría el pasado, no solo el presente.
    """
    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, related_name="contratos", verbose_name="Empleado")
    posicion = models.ForeignKey(Posicion, on_delete=models.PROTECT, related_name="contratos", verbose_name="Posición")

    fecha_ingreso = models.DateField(verbose_name="Fecha de ingreso")
    fecha_alta = models.DateField(null=True, blank=True, verbose_name="Fecha de alta")
    fecha_reingreso = models.DateField(null=True, blank=True, verbose_name="Fecha de reingreso")
    fecha_baja = models.DateField(null=True, blank=True, verbose_name="Fecha de baja")

    origen_baja = models.ForeignKey(
        OrigenBaja, null=True, blank=True, on_delete=models.PROTECT,
        verbose_name="Origen de baja",
    )
    causa_baja = models.ForeignKey(
        CausaBaja, null=True, blank=True, on_delete=models.PROTECT,
        verbose_name="Causa de baja",
    )

    solicitante_baja = models.CharField(
        max_length=150, blank=True, verbose_name="Solicitante de baja",
        help_text="Quién levantó/solicitó la baja — mismo patrón que Posicion.solicitante_vacante.",
    )
    considerado_para_reingreso = models.BooleanField(
        null=True, blank=True, default=None, verbose_name="Considerado para reingreso",
        help_text="Sin marcar mientras no se sepa — no forzar 'No' cuando el dato no se ha capturado.",
    )
    observaciones = models.TextField(blank=True, verbose_name="Observaciones")

    def clean(self):
        super().clean()
        if self.pk:
            empleado_original_id = (
                type(self).all_objects.filter(pk=self.pk).values_list("empleado_id", flat=True).first()
            )
            if empleado_original_id is not None and empleado_original_id != self.empleado_id:
                raise ValidationError({
                    "empleado": (
                        "Un Contrato no se puede reasignar a otro Empleado — "
                        "corrige el registro si está mal, o da de baja este y crea uno nuevo."
                    )
                })
        if self.causa_baja_id and not self.origen_baja_id:
            raise ValidationError({"origen_baja": "Si capturas una causa de baja, el origen de baja es obligatorio."})
        if self.causa_baja_id and self.origen_baja_id and self.causa_baja.origen_baja_id != self.origen_baja_id:
            raise ValidationError({
                "causa_baja": (
                    f"«{self.causa_baja.name}» no pertenece al origen «{self.origen_baja.name}» — "
                    f"elige una causa de ese origen."
                )
            })

    def __str__(self):
        return f"{self.empleado} — {self.posicion} (desde {self.fecha_ingreso})"

    class Meta(SoftDeleteModel.Meta):
        ordering = ["-fecha_ingreso"]
        verbose_name = "Contrato"
        verbose_name_plural = "Contratos"


class HistorialSalarial(BaseAuditModel):
    """
    Historial de compensación con vigencia — estructura confirmada como
    necesaria, pero SIN datos todavía: es información delicada que GPA no
    ha confirmado cuándo va a compartir. Nace vacía a propósito.
    """
    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, related_name="historial_salarial", verbose_name="Empleado")
    monto = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto")
    fecha_vigencia = models.DateField(verbose_name="Vigente desde")

    def __str__(self):
        return f"{self.empleado} — ${self.monto} (desde {self.fecha_vigencia})"

    class Meta:
        ordering = ["-fecha_vigencia"]
        verbose_name = "Historial salarial"
        verbose_name_plural = "Historial salarial"
