# apps/users/models.py
# Identidad de acceso al sistema (login), separada a propósito del dominio de
# RRHH (Persona/Empleado): un User es "puede iniciar sesión", no "es
# colaborador". El vínculo real vive en apps.employment.Empleado.user.
import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.models import NamedCatalog


class UserRole(NamedCatalog):
    """
    Qué puede hacer esta cuenta en general: Colaborador / Capital Humano /
    Admin (confirmado con el usuario 2026-09-22/23). "Jefe" NO es un valor
    de este catálogo — esa capacidad se resuelve sola desde el organigrama
    (apps.positions.Posicion.reports_to), no se asigna como rol.
    """

    class Meta(NamedCatalog.Meta):
        verbose_name = "Rol de usuario"
        verbose_name_plural = "Roles de usuario"


class User(AbstractUser):
    """
    Usuario del sistema. Extiende AbstractUser para conservar el sistema de
    auth de Django (permisos, grupos, hashing de password, etc).
    UUID como PK, consistente con el resto de las entidades del proyecto.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    role = models.ForeignKey(
        UserRole, null=True, blank=True, on_delete=models.PROTECT,
        related_name="users", verbose_name="Rol",
        help_text="Qué puede hacer en general. La capacidad de aprobar solicitudes de reportes se resuelve aparte, por el organigrama.",
    )

    def __str__(self):
        return self.username

    class Meta:
        db_table = "users"
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
