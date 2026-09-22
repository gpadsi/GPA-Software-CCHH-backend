# apps/users/models.py
# Identidad de acceso al sistema (login), separada a propósito del dominio de
# RRHH (Persona/Empleado): un User es "puede iniciar sesión", no "es
# colaborador". La relación entre ambos se define más adelante, cuando el
# módulo de personas exista.
import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Usuario del sistema. Extiende AbstractUser para conservar el sistema de
    auth de Django (permisos, grupos, hashing de password, etc).
    UUID como PK, consistente con el resto de las entidades del proyecto.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)

    def __str__(self):
        return self.username

    class Meta:
        db_table = "users"
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"
