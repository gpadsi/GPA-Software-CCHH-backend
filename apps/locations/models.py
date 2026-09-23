from django.db import models

from apps.core.models import BaseAuditModel


class Ubicacion(BaseAuditModel):
    """
    Sitio físico (Matriz, Logistics, CIEM, Sucursal Monterrey...). Jerarquía
    física de 3 niveles SIEMPRE fijos (Ubicacion -> Nave -> Area), confirmada
    por el usuario — a diferencia de la estructura organizacional, aquí NO
    se necesita un árbol genérico recursivo: la profundidad nunca cambia.

    El registro patronal del IMSS vive AQUÍ, no en Company: el IMSS liga el
    registro patronal a un centro de trabajo físico, y ya vimos en datos
    reales que una misma Empresa puede tener varios registros patronales
    distintos (uno por sitio).
    """
    code = models.CharField(max_length=30, unique=True, verbose_name="Código")
    name = models.CharField(max_length=150, verbose_name="Nombre")
    employer_registration = models.CharField(
        max_length=100, blank=True, verbose_name="Registro patronal del IMSS",
    )
    is_active = models.BooleanField(default=True, verbose_name="Activo")

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]
        verbose_name = "Ubicación"
        verbose_name_plural = "Ubicaciones"


class Nave(BaseAuditModel):
    ubicacion = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT, related_name="naves",
        verbose_name="Ubicación",
    )
    code = models.CharField(max_length=30, verbose_name="Código")
    name = models.CharField(max_length=150, blank=True, verbose_name="Nombre")
    is_active = models.BooleanField(default=True, verbose_name="Activo")

    def __str__(self):
        return f"{self.ubicacion.name} — {self.code}"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ubicacion", "code"], name="unique_nave_code_per_ubicacion"),
        ]
        ordering = ["ubicacion", "code"]
        verbose_name = "Nave"
        verbose_name_plural = "Naves"


class Area(BaseAuditModel):
    nave = models.ForeignKey(
        Nave, on_delete=models.PROTECT, related_name="areas",
        verbose_name="Nave",
    )
    code = models.CharField(max_length=30, verbose_name="Código")
    name = models.CharField(max_length=150, verbose_name="Nombre")
    is_active = models.BooleanField(default=True, verbose_name="Activo")

    def __str__(self):
        return f"{self.nave} — {self.name}"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["nave", "code"], name="unique_area_code_per_nave"),
        ]
        ordering = ["nave", "name"]
        verbose_name = "Área"
        verbose_name_plural = "Áreas"
