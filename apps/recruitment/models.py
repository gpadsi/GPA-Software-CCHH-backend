# apps/recruitment/models.py
# Basado en 3 documentos reales de GPA (2026-10-01): FO-C0-CH-01
# (Requisicion de Personal), FO-C0-CH-08 (Reemplazo de Personal -- casi
# identico al anterior, solo omite la justificacion) y FO-C0-CH-04
# (Descriptivo de Puesto, todavia no construido en esta app). Las
# plantillas oficiales viven en apps/recruitment/plantillas_oficiales/.
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import NamedCatalog, SoftDeleteModel
from apps.positions.models import Posicion, TipoRequisicion


class EstadoRequisicion(NamedCatalog):
    """
    Ciclo de vida de una Requisicion, independiente de Posicion.estatus --
    confirmado 2026-10-01: una Posicion puede seguir ocupada mientras ya se
    tramita su reemplazo, asi que el estado del tramite no puede vivir en
    la Posicion. es_terminal marca cuando una Requisicion ya no cuenta
    como "abierta" (ver Requisicion.clean()), para no comparar nombres a
    mano en el codigo.
    """
    es_terminal = models.BooleanField(
        default=False, verbose_name="Es un estado final",
        help_text="Una Posición no puede tener dos Requisición abiertas (no terminales) a la vez.",
    )

    class Meta(NamedCatalog.Meta):
        verbose_name = "Estado de requisición"
        verbose_name_plural = "Estados de requisición"


class EtapaAprobacion(NamedCatalog):
    """
    Las 4 firmas del formulario real: Jefe Inmediato, Gerencia del Área,
    Dirección General/VP, Capital Humano. Sin orden estricto entre ellas
    -- confirmado 2026-10-01: si Capital Humano levanta la Requisición
    directamente, puede no haber pasado antes por un Jefe Inmediato.
    """
    class Meta(NamedCatalog.Meta):
        verbose_name = "Etapa de aprobación"
        verbose_name_plural = "Etapas de aprobación"


class TipoContratoOfrecido(NamedCatalog):
    """Confirmado en el formulario real: Planta, Temporal."""

    class Meta(NamedCatalog.Meta):
        verbose_name = "Tipo de contrato ofrecido"
        verbose_name_plural = "Tipos de contrato ofrecido"


class HorarioACubrir(NamedCatalog):
    """Las 5 opciones fijas del formulario real: 8:00-17:45, 7:00-16:00, 15:00-24:00, 23:30-07:30, Otro."""

    class Meta(NamedCatalog.Meta):
        verbose_name = "Horario a cubrir"
        verbose_name_plural = "Horarios a cubrir"


class Requisicion(SoftDeleteModel):
    """
    El trámite de "necesitamos cubrir esta Posición". Confirmado
    2026-10-01 que es un expediente propio, no un campo más de Posicion:
    una misma Posición puede tener varias Requisicion en su vida (se
    cubre, años después alguien se va, se abre otra) -- por eso `tipo` es
    propio de cada Requisicion y NO lee Posicion.tipo_requisicion.

    Cualquier usuario autenticado puede crear una -- no solo Capital
    Humano/Admin: un Gerente o Director sigue siendo rol "Colaborador" en
    este sistema (no existe un rol de gerencia aparte), y el filtro real
    de legitimidad es el flujo de aprobación, no el permiso de creación.
    `created_by` (heredado) ya registra quién la levantó.

    SoftDeleteModel: es un expediente de reclutamiento, mismo criterio que
    Contrato -- borrarlo de verdad borraría el trámite, no solo el estado actual.
    """
    posicion = models.ForeignKey(
        Posicion, on_delete=models.PROTECT, related_name="requisiciones", verbose_name="Posición",
    )
    tipo = models.ForeignKey(
        TipoRequisicion, on_delete=models.PROTECT, verbose_name="Tipo",
        help_text="Reemplazo o Nueva Posición -- propio de esta Requisición, no de la Posición.",
    )
    estado = models.ForeignKey(EstadoRequisicion, on_delete=models.PROTECT, verbose_name="Estado")

    fecha_solicitud = models.DateField(verbose_name="Fecha de solicitud")
    fecha_a_cubrir_vacante = models.DateField(null=True, blank=True, verbose_name="Fecha a cubrir la vacante")
    fecha_entrega_a_capital_humano = models.DateField(
        null=True, blank=True, verbose_name="Fecha de entrega a Capital Humano",
    )

    area_solicitante = models.CharField(
        max_length=150, blank=True, verbose_name="Área solicitante",
        help_text="El departamento que pide cubrir la plaza -- NO es Posicion.area (esa es la ubicación física).",
    )
    justificacion = models.TextField(
        blank=True, verbose_name="Justificación de la requisición",
        help_text="Obligatoria solo si TipoRequisicion.requiere_justificacion está marcado para el Tipo elegido.",
    )

    horario_a_cubrir = models.ForeignKey(
        HorarioACubrir, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Horario a cubrir",
    )
    idiomas_requeridos = models.CharField(max_length=150, blank=True, verbose_name="Idiomas")
    disposicion_viajar = models.BooleanField(
        null=True, blank=True, default=None, verbose_name="Disposición para viajar",
        help_text="Sin marcar mientras no se sepa -- no forzar 'No' cuando el dato no se ha capturado.",
    )

    nivel_tabulador = models.CharField(max_length=50, blank=True, verbose_name="Nivel de tabulador")
    sueldo_mensual_compuesto = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Sueldo mensual compuesto",
    )
    sueldo_mensual_bruto = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Sueldo mensual bruto",
    )
    sueldo_mensual_neto = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Sueldo mensual neto",
    )
    tipo_contrato_ofrecido = models.ForeignKey(
        TipoContratoOfrecido, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Tipo de contrato",
    )

    motivo_suspension = models.TextField(blank=True, verbose_name="Motivo de suspensión")
    fecha_suspension = models.DateField(null=True, blank=True, verbose_name="Fecha de suspensión")
    autorizado_por_suspension = models.CharField(max_length=150, blank=True, verbose_name="Autorizado por (suspensión)")

    def clean(self):
        super().clean()
        if self.tipo_id and self.tipo.requiere_justificacion and not self.justificacion.strip():
            raise ValidationError({"justificacion": "Este tipo de Requisición exige justificación."})

        if self.estado_id and not self.estado.es_terminal:
            abiertas = Requisicion.objects.filter(
                posicion_id=self.posicion_id, estado__es_terminal=False,
            ).exclude(pk=self.pk)
            if abiertas.exists():
                raise ValidationError({
                    "posicion": "Esta Posición ya tiene una Requisición abierta -- ciérrala antes de abrir otra."
                })

    def __str__(self):
        return f"{self.posicion} — {self.tipo} ({self.estado})"

    class Meta(SoftDeleteModel.Meta):
        ordering = ["-fecha_solicitud"]
        verbose_name = "Requisición"
        verbose_name_plural = "Requisiciones"


class AprobacionRequisicion(SoftDeleteModel):
    """
    Una de las 4 firmas de una Requisición. Cubre los dos casos reales
    (confirmado 2026-10-01): si se aceptó dentro del sistema, `usuario`
    identifica a quién; si fue firma física, `nombre_manual` se captura a
    mano y el documento firmado se adjunta vía Attachment (genérico, ya
    apunta aquí por content_type/object_id -- sin campo nuevo para eso).
    """
    requisicion = models.ForeignKey(
        Requisicion, on_delete=models.CASCADE, related_name="aprobaciones", verbose_name="Requisición",
    )
    etapa = models.ForeignKey(EtapaAprobacion, on_delete=models.PROTECT, verbose_name="Etapa")

    fecha = models.DateField(null=True, blank=True, verbose_name="Fecha de aprobación", help_text="Vacío = pendiente.")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="aprobaciones_requisicion", verbose_name="Usuario que aprobó",
        help_text="Si se aceptó dentro del sistema.",
    )
    nombre_manual = models.CharField(
        max_length=150, blank=True, verbose_name="Nombre capturado a mano",
        help_text="Si la firma fue física, fuera del sistema.",
    )

    def clean(self):
        super().clean()
        if self.fecha and not self.usuario_id and not self.nombre_manual.strip():
            raise ValidationError({
                "nombre_manual": "Si ya hay fecha de aprobación, indica quién aprobó (usuario o nombre a mano)."
            })

    def __str__(self):
        quien = self.usuario or self.nombre_manual or "(pendiente)"
        return f"{self.requisicion} — {self.etapa}: {quien}"

    class Meta(SoftDeleteModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["requisicion", "etapa"],
                condition=models.Q(is_deleted=False),
                name="unique_etapa_por_requisicion",
            ),
        ]
        ordering = ["etapa__name"]
        verbose_name = "Aprobación de requisición"
        verbose_name_plural = "Aprobaciones de requisición"
