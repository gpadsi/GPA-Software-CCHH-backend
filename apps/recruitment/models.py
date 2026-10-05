# apps/recruitment/models.py
# Basado en 3 documentos reales de GPA (2026-10-01): FO-C0-CH-01
# (Requisicion de Personal), FO-C0-CH-08 (Reemplazo de Personal -- casi
# identico al anterior, solo omite la justificacion) y FO-C0-CH-04
# (Descriptivo de Puesto, modelado al final de este archivo). Las
# plantillas oficiales viven en apps/recruitment/plantillas_oficiales/.
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Max
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from django.utils import timezone

from apps.core.models import BaseAuditModel, NamedCatalog, SoftDeleteModel
from apps.persons.models import Persona
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


class RequisicionReemplazo(Requisicion):
    """
    Solo para el admin de Django (modelo proxy, no crea tabla): las
    Requisiciones de tipo Reemplazo en su propia lista, igual que su
    formulario oficial (FO-C0-CH-08). Es la misma tabla que Requisicion.
    """

    class Meta:
        proxy = True
        verbose_name = "Requisición de Reemplazo"
        verbose_name_plural = "Requisiciones de Reemplazo"


class RequisicionNuevaPosicion(Requisicion):
    """
    Solo para el admin de Django (modelo proxy, no crea tabla): las
    Requisiciones de tipo Nueva Posición en su propia lista, igual que su
    formulario oficial (FO-C0-CH-01). Es la misma tabla que Requisicion.
    """

    class Meta:
        proxy = True
        verbose_name = "Requisición de Nueva Posición"
        verbose_name_plural = "Requisiciones de Nueva Posición"


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


# ---------------------------------------------------------------------------
# Descriptivo de Puesto (FO-C0-CH-04) -- Entrega 2
# ---------------------------------------------------------------------------

class RangoEdad(NamedCatalog):
    """Opciones de "Edad" del formulario real: 18-25, 26-35, 36-45, 46-55, Otro."""

    class Meta(NamedCatalog.Meta):
        verbose_name = "Rango de edad"
        verbose_name_plural = "Rangos de edad"


class DiasPorLaborar(NamedCatalog):
    """Opciones de "Días por laborar" del formulario real: Lunes a Viernes, Lunes a Domingo, Otro."""

    class Meta(NamedCatalog.Meta):
        verbose_name = "Días por laborar"
        verbose_name_plural = "Días por laborar"


class CompetenciaConductual(NamedCatalog):
    """Las 12 casillas de COMPETENCIAS del formulario real."""

    class Meta(NamedCatalog.Meta):
        verbose_name = "Competencia conductual"
        verbose_name_plural = "Competencias conductuales"


class RecursoAsignado(NamedCatalog):
    """Las 10 casillas de RECURSOS NECESARIOS del formulario real."""

    class Meta(NamedCatalog.Meta):
        verbose_name = "Recurso asignado"
        verbose_name_plural = "Recursos asignados"


class RolConformidad(NamedCatalog):
    """
    Las 3 firmas de "Nombre y Firma de conformidad": Colaborador, Jefe
    inmediato, Capital Humano. requiere_persona marca cuando la conformidad
    debe ligarse a una Persona específica (el Colaborador: la misma Posición
    la ocupan personas distintas con los años, y cada una firma la versión
    que conoció) -- misma idea que EstadoRequisicion.es_terminal: una marca
    en el catálogo en vez de comparar nombres a mano en el código.
    """
    requiere_persona = models.BooleanField(
        default=False, verbose_name="Requiere una persona específica",
        help_text="La conformidad se registra a nombre de una Persona (ej. el Colaborador que ocupa la Posición).",
    )

    class Meta(NamedCatalog.Meta):
        verbose_name = "Rol de conformidad"
        verbose_name_plural = "Roles de conformidad"


_MSJ_CONGELADA = (
    "Esta versión del Descriptivo ya está congelada y no se puede modificar -- "
    "crea una versión nueva a partir de ella."
)


class DescriptivoPuesto(SoftDeleteModel):
    """
    Descriptivo de Puesto (FO-C0-CH-04) de una Posición. Confirmado
    2026-10-01: ligado a la Posición (la plaza específica con su área,
    empresa y jefe), no al Puesto (catálogo de título reutilizable).

    Versionado: cada Posición puede tener varias versiones a lo largo del
    tiempo. Mientras `congelado_en` esté vacío es un borrador editable
    (solo uno a la vez por Posición). Al congelarlo queda inmutable --
    contenido, funciones, indicadores y casillas -- y la versión vigente es
    la congelada más reciente. Para cambiar algo se crea un borrador nuevo
    copiando una versión (ver apps.recruitment.services). Las
    conformidades (firmas) se registran DESPUÉS de congelar, ligadas a esa
    versión, así que no cuentan como contenido congelado.

    Los datos generales (nombre, empresa, área, reporta a, supervisa a)
    son texto propio de la versión, precargado desde la Posición al crear
    el borrador y editable -- así una versión antigua conserva lo que
    decía cuando se aprobó aunque la Posición cambie después.
    """
    posicion = models.ForeignKey(
        Posicion, on_delete=models.PROTECT, related_name="descriptivos", verbose_name="Posición",
    )
    version = models.PositiveIntegerField(
        default=0, editable=False, verbose_name="Versión",
        help_text="Se asigna sola al crear: 1, 2, 3... por Posición.",
    )
    congelado_en = models.DateTimeField(
        null=True, blank=True, editable=False, verbose_name="Congelado el",
        help_text="Vacío = borrador editable. Con fecha = versión aprobada, inmutable.",
    )

    # DATOS GENERALES DEL PUESTO
    nombre_puesto = models.CharField(max_length=150, blank=True, verbose_name="Nombre del puesto")
    empresa = models.CharField(max_length=150, blank=True, verbose_name="Empresa")
    area_departamento = models.CharField(max_length=150, blank=True, verbose_name="Área / Departamento")
    reporta_a = models.CharField(max_length=150, blank=True, verbose_name="Reporta a")
    supervisa_a = models.TextField(
        blank=True, verbose_name="Supervisa a", help_text="Puestos y número de personas a cargo, si aplica.",
    )
    fecha_elaboracion = models.DateField(verbose_name="Fecha de elaboración / actualización")

    # CONDICIONES DEL PUESTO
    edad = models.ForeignKey(RangoEdad, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Edad")
    edad_otro = models.CharField(max_length=100, blank=True, verbose_name="Edad (otro)")
    disponibilidad_viajar = models.BooleanField(
        null=True, blank=True, default=None, verbose_name="Disponibilidad para viajar",
        help_text="Sin marcar mientras no se sepa -- no forzar 'No'.",
    )
    dias_por_laborar = models.ForeignKey(
        DiasPorLaborar, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Días por laborar",
    )
    dias_por_laborar_otro = models.CharField(max_length=100, blank=True, verbose_name="Días por laborar (otro)")
    horario = models.ForeignKey(
        HorarioACubrir, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="Horario por cubrir",
    )
    horario_otro = models.CharField(max_length=100, blank=True, verbose_name="Horario (otro)")

    # PROPÓSITO / AUTORIDAD / RELACIONES / PERFIL (texto libre del formulario)
    proposito = models.TextField(blank=True, verbose_name="Propósito del puesto")
    decisiones_operativas = models.TextField(blank=True, verbose_name="Decisiones operativas")
    decisiones_funcionales = models.TextField(blank=True, verbose_name="Decisiones funcionales")
    decisiones_estrategicas = models.TextField(blank=True, verbose_name="Decisiones estratégicas")
    relaciones_internas = models.TextField(blank=True, verbose_name="Relaciones internas")
    relaciones_externas = models.TextField(blank=True, verbose_name="Relaciones externas")
    escolaridad_minima = models.TextField(blank=True, verbose_name="Escolaridad mínima")
    experiencia_requerida = models.TextField(blank=True, verbose_name="Experiencia requerida")
    idiomas = models.TextField(blank=True, verbose_name="Idiomas")
    competencias_tecnicas = models.TextField(blank=True, verbose_name="Competencias y/o habilidades técnicas")

    # COMPETENCIAS / RECURSOS (casillas del formulario)
    # related_name="+" a propósito: sin acceso inverso desde el catálogo, así
    # el único camino para cambiar estas casillas es por el Descriptivo y el
    # bloqueo de versión congelada (señal de abajo) las cubre todas.
    competencias = models.ManyToManyField(
        CompetenciaConductual, blank=True, related_name="+", verbose_name="Competencias",
    )
    competencias_otras = models.CharField(max_length=255, blank=True, verbose_name="Otras competencias")
    recursos = models.ManyToManyField(
        RecursoAsignado, blank=True, related_name="+", verbose_name="Recursos necesarios",
    )
    recursos_otro = models.CharField(max_length=255, blank=True, verbose_name="Otros recursos")

    @property
    def esta_congelado(self):
        return self.congelado_en is not None

    def _congelado_en_bd(self):
        # Se consulta la base, no el objeto en memoria: un objeto viejo en
        # memoria no debe poder pasar por encima de un congelado reciente.
        if self._state.adding:
            return False
        return type(self).all_objects.filter(pk=self.pk, congelado_en__isnull=False).exists()

    def clean(self):
        super().clean()
        if self._congelado_en_bd():
            raise ValidationError(_MSJ_CONGELADA)
        if self.congelado_en is None:
            otros_borradores = DescriptivoPuesto.objects.filter(
                posicion_id=self.posicion_id, congelado_en__isnull=True,
            ).exclude(pk=self.pk)
            if otros_borradores.exists():
                raise ValidationError({
                    "posicion": "Esta Posición ya tiene un borrador de Descriptivo abierto -- "
                                "termínalo (congélalo) o bórralo antes de abrir otro."
                })

    def save(self, *args, **kwargs):
        if self._congelado_en_bd():
            raise ValidationError(_MSJ_CONGELADA)
        if self._state.adding and not self.version:
            ultima = DescriptivoPuesto.objects.filter(posicion_id=self.posicion_id).aggregate(m=Max("version"))["m"]
            self.version = (ultima or 0) + 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self._congelado_en_bd():
            raise ValidationError(
                "Una versión congelada no se borra -- queda como historial. "
                "Crea una versión nueva si hay que corregir algo."
            )
        super().delete(*args, **kwargs)

    def congelar(self, user=None):
        """Aprueba el borrador: desde aquí es inmutable. Las conformidades se registran después."""
        if self.congelado_en is not None or self._congelado_en_bd():
            raise ValidationError("Esta versión del Descriptivo ya estaba congelada.")
        self.congelado_en = timezone.now()
        if user is not None:
            self.updated_by = user
        self.save()

    @classmethod
    def vigente_de(cls, posicion):
        """La versión congelada más reciente de la Posición, o None si todavía no hay ninguna."""
        return cls.objects.filter(posicion=posicion, congelado_en__isnull=False).order_by("-version").first()

    def __str__(self):
        estado = "congelada" if self.congelado_en else "borrador"
        return f"{self.posicion} — Descriptivo v{self.version} ({estado})"

    class Meta(SoftDeleteModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["posicion", "version"], condition=models.Q(is_deleted=False),
                name="unique_version_descriptivo_por_posicion",
            ),
            models.UniqueConstraint(
                fields=["posicion"], condition=models.Q(is_deleted=False, congelado_en__isnull=True),
                name="unique_borrador_descriptivo_por_posicion",
            ),
        ]
        ordering = ["posicion", "-version"]
        verbose_name = "Descriptivo de puesto"
        verbose_name_plural = "Descriptivos de puesto"


@receiver(m2m_changed, sender=DescriptivoPuesto.competencias.through)
@receiver(m2m_changed, sender=DescriptivoPuesto.recursos.through)
def _bloquear_casillas_de_version_congelada(sender, instance, action, **kwargs):
    # related_name="+" garantiza que `instance` siempre es el Descriptivo.
    if action in ("pre_add", "pre_remove", "pre_clear") and instance._congelado_en_bd():
        raise ValidationError(_MSJ_CONGELADA)


class _ElementoOrdenadoDeDescriptivo(BaseAuditModel):
    """
    Base abstracta de las listas numeradas del formulario (Responsabilidad
    1..N, Indicador 1..N). Borrado físico a propósito: solo se editan
    mientras el Descriptivo es borrador; una versión congelada ya las
    conserva, y cambiar una lista = crear una versión nueva.
    """
    orden = models.PositiveSmallIntegerField(verbose_name="Número")
    texto = models.TextField(verbose_name="Texto")

    def _validar_editable(self):
        if self.descriptivo_id and DescriptivoPuesto.all_objects.filter(
            pk=self.descriptivo_id, congelado_en__isnull=False,
        ).exists():
            raise ValidationError(_MSJ_CONGELADA)

    def clean(self):
        super().clean()
        self._validar_editable()

    def save(self, *args, **kwargs):
        self._validar_editable()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._validar_editable()
        super().delete(*args, **kwargs)

    class Meta:
        abstract = True
        ordering = ["orden"]


class FuncionPuesto(_ElementoOrdenadoDeDescriptivo):
    """Una fila "Responsabilidad N" de FUNCIONES Y RESPONSABILIDADES. El formulario trae 5; aquí no hay tope."""
    descriptivo = models.ForeignKey(
        DescriptivoPuesto, on_delete=models.CASCADE, related_name="funciones", verbose_name="Descriptivo",
    )

    def __str__(self):
        return f"{self.descriptivo} — Responsabilidad {self.orden}"

    class Meta(_ElementoOrdenadoDeDescriptivo.Meta):
        constraints = [
            models.UniqueConstraint(fields=["descriptivo", "orden"], name="unique_orden_funcion_por_descriptivo"),
        ]
        verbose_name = "Función del puesto"
        verbose_name_plural = "Funciones del puesto"


class IndicadorDesempeno(_ElementoOrdenadoDeDescriptivo):
    """Una fila "Indicador N" de INDICADORES DE DESEMPEÑO. El formulario trae 3; aquí no hay tope."""
    descriptivo = models.ForeignKey(
        DescriptivoPuesto, on_delete=models.CASCADE, related_name="indicadores", verbose_name="Descriptivo",
    )

    def __str__(self):
        return f"{self.descriptivo} — Indicador {self.orden}"

    class Meta(_ElementoOrdenadoDeDescriptivo.Meta):
        constraints = [
            models.UniqueConstraint(fields=["descriptivo", "orden"], name="unique_orden_indicador_por_descriptivo"),
        ]
        verbose_name = "Indicador de desempeño"
        verbose_name_plural = "Indicadores de desempeño"


class ConformidadDescriptivo(SoftDeleteModel):
    """
    Una firma de "Nombre y Firma de conformidad" de una versión congelada.
    Mismo criterio híbrido que AprobacionRequisicion: `usuario` si aceptó
    dentro del sistema, `nombre_manual` si firmó en papel (y el documento
    firmado se adjunta vía Attachment). Para roles con requiere_persona
    (Colaborador) se liga además a la Persona concreta: varias personas
    pueden ocupar la misma Posición con los años y cada una firma la versión
    que conoció.
    """
    descriptivo = models.ForeignKey(
        DescriptivoPuesto, on_delete=models.PROTECT, related_name="conformidades", verbose_name="Descriptivo",
    )
    rol = models.ForeignKey(RolConformidad, on_delete=models.PROTECT, verbose_name="Rol")
    persona = models.ForeignKey(
        Persona, null=True, blank=True, on_delete=models.PROTECT,
        related_name="conformidades_descriptivo", verbose_name="Persona",
    )
    fecha = models.DateField(null=True, blank=True, verbose_name="Fecha de conformidad", help_text="Vacío = pendiente.")
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="conformidades_descriptivo", verbose_name="Usuario que aceptó",
        help_text="Si aceptó dentro del sistema.",
    )
    nombre_manual = models.CharField(
        max_length=150, blank=True, verbose_name="Nombre capturado a mano",
        help_text="Si la firma fue física, fuera del sistema.",
    )

    def clean(self):
        super().clean()
        if self.descriptivo_id and not self.descriptivo.esta_congelado:
            raise ValidationError({
                "descriptivo": "Solo se registra conformidad sobre una versión congelada -- congélala primero."
            })
        if self.rol_id and self.rol.requiere_persona and not self.persona_id:
            raise ValidationError({"persona": "Este rol exige indicar la persona que da su conformidad."})
        if self.fecha and not (self.usuario_id or self.persona_id or self.nombre_manual.strip()):
            raise ValidationError({
                "nombre_manual": "Si ya hay fecha de conformidad, indica quién la dio (usuario, persona o nombre a mano)."
            })

    def __str__(self):
        quien = self.persona or self.usuario or self.nombre_manual or "(pendiente)"
        return f"{self.descriptivo} — {self.rol}: {quien}"

    class Meta(SoftDeleteModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["descriptivo", "rol", "persona"],
                condition=models.Q(is_deleted=False, persona__isnull=False),
                name="unique_conformidad_por_persona_y_rol",
            ),
            models.UniqueConstraint(
                fields=["descriptivo", "rol"],
                condition=models.Q(is_deleted=False, persona__isnull=True),
                name="unique_conformidad_sin_persona_por_rol",
            ),
        ]
        ordering = ["rol__name"]
        verbose_name = "Conformidad de descriptivo"
        verbose_name_plural = "Conformidades de descriptivo"
