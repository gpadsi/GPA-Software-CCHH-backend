from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseAuditModel

# La especificación no fija los ``max_length`` de esta fase. Los valores de
# abajo son límites técnicos conservadores, no validaciones de formato de
# negocio; quedan pendientes de ajustar si GPA confirma límites distintos.


class Tenant(models.Model):
    """
    La organización dueña de todo el sistema — hoy y siempre "Grupo GPA".
    Es el primer eslabón real de la cadena (Tenant → Empresa → ...), no un
    dato de configuración invisible: se ve y se administra desde el admin.
    Solo existe una fila; por eso el campo correspondiente en OrganizationNode
    se autoasigna solo, nadie lo elige a mano (ver OrganizationNode.save()).
    """
    id = models.AutoField(primary_key=True)
    code = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Código",
        help_text="Identificador corto, ej. «GPA».",
    )
    name = models.CharField(
        max_length=150,
        verbose_name="Nombre",
        help_text="Nombre completo, ej. «Grupo GPA».",
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["code"]
        verbose_name = "Organización (Tenant)"
        verbose_name_plural = "Organización (Tenant)"


class OrganizationalLevel(models.Model):
    numero = models.PositiveSmallIntegerField(
        unique=True,
        verbose_name="Número",
        help_text="Orden del nivel en la estructura, ej. «1» para Empresa.",
    )
    code = models.SlugField(
        max_length=50,
        unique=True,
        verbose_name="Código",
        help_text="Identificador interno sin espacios, ej. «unidad_negocio».",
    )
    name = models.CharField(
        max_length=150,
        verbose_name="Nombre",
        help_text="Nombre del nivel en español, ej. «Unidad de Negocio».",
    )
    allows_recursive_nesting = models.BooleanField(
        default=False,
        verbose_name="Se anida a sí mismo",
        help_text=(
            "Actívalo SOLO para el nivel que puede colgar de otro nodo de su "
            "propio mismo nivel, indefinidamente (ej. una Unidad de Negocio "
            "dentro de otra Unidad de Negocio: Gerencia de Operaciones → "
            "Departamento de Producción → Soldadura, todas el mismo nivel, "
            "solo cambia el nombre). Para el resto de los niveles, déjalo "
            "desmarcado."
        ),
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["numero"]
        verbose_name = "Nivel organizacional"
        verbose_name_plural = "Niveles organizacionales"


class OrganizationNode(BaseAuditModel):
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        # blank=True (no null=True): a nivel de base de datos sigue siendo
        # obligatorio, pero full_clean() valida clean_fields() ANTES que
        # clean() — sin esto, rechazaría el campo vacío antes de que clean()
        # alcance a autoasignarlo.
        blank=True,
        verbose_name="Organización",
        help_text="Se asigna sola — hoy solo existe «Grupo GPA».",
    )
    level = models.ForeignKey(
        OrganizationalLevel,
        on_delete=models.PROTECT,
        verbose_name="Nivel organizacional",
        help_text=(
            "Nivel que ocupa el nodo. Debe ser de un número mayor al del nodo "
            "padre elegido abajo — salvo en un nivel marcado como \"se anida a "
            "sí mismo\" (ej. Unidad de Negocio), que sí puede colgar de otro "
            "nodo de su mismo nivel."
        ),
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        verbose_name="Nodo padre",
        help_text=(
            "Nodo del que depende. Su nivel debe ser numéricamente menor al del "
            "nivel elegido arriba (o el mismo, si ese nivel se puede anidar a sí "
            "mismo); una Empresa no lleva padre."
        ),
    )
    code = models.CharField(
        max_length=50,
        verbose_name="Código",
        help_text="Identificador de negocio capturado manualmente, ej. «GPA-AZM-01».",
    )
    name = models.CharField(
        max_length=200,
        verbose_name="Nombre",
        help_text="Nombre del nodo en español, ej. «Gerencia de Operaciones».",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo",
        help_text="Indica si el nodo sigue vigente, ej. desmárcalo al cerrar un departamento.",
    )

    def clean(self):
        super().clean()

        # Solo existe una Tenant; nadie la elige a mano (igual que
        # uploaded_by en Attachment). Se asigna aquí, ANTES de validar más
        # abajo, porque la validación de "mismo tenant que el padre" necesita
        # que ya tenga valor.
        if not self.tenant_id:
            self.tenant = Tenant.objects.get()

        # La validación de obligatoriedad del campo level queda a cargo del
        # propio ForeignKey; este guard evita ocultar ese mensaje si falta.
        if not self.level_id:
            return

        parent = self.parent if self.parent_id else None

        if self.level.numero == 1 and parent is not None:
            raise ValidationError({
                "parent": "Un nodo de nivel Empresa no puede tener un nodo padre."
            })

        if self.level.numero != 1 and parent is None:
            raise ValidationError({
                "parent": "El nodo padre es obligatorio para cualquier nivel distinto de Empresa."
            })

        if parent is not None:
            if parent.tenant_id != self.tenant_id:
                raise ValidationError({
                    "parent": "El nodo padre y el nodo hijo deben pertenecer a la misma organización."
                })

            if parent.level_id == self.level_id:
                if not self.level.allows_recursive_nesting:
                    raise ValidationError({
                        "parent": (
                            f"El nivel «{self.level.name}» no puede colgar de otro "
                            f"nodo de su mismo nivel."
                        )
                    })
            elif parent.level.numero >= self.level.numero:
                raise ValidationError({
                    "parent": (
                        f"El nodo padre («{parent.level.name}», nivel {parent.level.numero}) debe "
                        f"ser de un nivel superior al del nodo hijo («{self.level.name}», nivel "
                        f"{self.level.numero})."
                    )
                })

        ancestor = parent
        visited_ancestor_ids = set()
        while ancestor is not None:
            if ancestor.pk == self.pk:
                raise ValidationError({
                    "parent": "Un nodo no puede aparecer en su propia ascendencia."
                })
            if ancestor.pk in visited_ancestor_ids:
                break
            visited_ancestor_ids.add(ancestor.pk)
            ancestor = ancestor.parent

    def save(self, *args, **kwargs):
        # Red de seguridad para creaciones directas (.objects.create(), shell,
        # comandos) que no pasan por full_clean(): la asignación de arriba
        # solo corre dentro de clean().
        if not self.tenant_id:
            self.tenant = Tenant.objects.get()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} — {self.name}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "code"],
                name="unique_organization_node_code_per_parent",
            )
        ]
        verbose_name = "Nodo organizacional"
        verbose_name_plural = "Nodos organizacionales"


class Company(BaseAuditModel):
    organization_node = models.OneToOneField(
        OrganizationNode,
        on_delete=models.PROTECT,
        verbose_name="Nodo organizacional",
        help_text="Nodo de nivel Empresa al que corresponde, ej. «GPA Azimatronics».",
    )
    # TEMPORAL (2026-09-25): null=True/blank=True — ver apps/core/checks.py.
    # GPA no nos ha compartido razón social/registro patronal de ninguna de
    # las 12 empresas reales todavía; se dejan vacíos en vez de inventar un
    # texto, hasta que llegue la sábana corregida con ese dato.
    legal_name = models.CharField(
        max_length=255,
        null=True, blank=True,
        verbose_name="Razón social",
        help_text="Razón social completa, ej. «Azimatronics, S.A. de C.V.».",
    )
    rfc = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        verbose_name="RFC",
        help_text="RFC de la empresa, ej. «AZI010203AB1»; puede dejarse vacío por ahora.",
    )
    employer_registration = models.CharField(
        max_length=100,
        null=True, blank=True,
        verbose_name="Registro patronal",
        help_text="Registro patronal en texto libre, ej. «Y54-12345-10-1».",
    )

    def clean(self):
        super().clean()
        if (
            self.organization_node_id
            and self.organization_node.level.numero != 1
        ):
            raise ValidationError({
                "organization_node": (
                    "Una empresa solo puede vincularse con un nodo organizacional "
                    "de nivel Empresa."
                )
            })

    def __str__(self):
        # legal_name puede estar vacío todavía (ver TEMPORAL arriba) — cae al
        # nombre del nodo organizacional en vez de mostrar un "None" feo.
        return self.legal_name or self.organization_node.name

    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"
