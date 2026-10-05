import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core.permissions import CODE_ADMIN
from apps.users.models import User, UserRole

# Valor de ejemplo de .env.example. Si llega tal cual a un entorno sin DEBUG
# (producción), crear el superusuario con él dejaría una cuenta Admin con
# contraseña pública — se omite la creación en vez de hacerlo.
PLACEHOLDER_PASSWORD = "cambiar_esta_contrasena"


class Command(BaseCommand):
    help = (
        "Crea el superusuario inicial desde DJANGO_SUPERUSER_* con rol Admin, "
        "o le asigna rol Admin si ya existe sin rol (idempotente)."
    )

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME") or "admin"
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL") or "admin@capitalhumano.local"
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD") or ""

        # Los permisos de la API se deciden por user.role (apps.core.permissions),
        # no por is_superuser: un superusuario sin rol es un Colaborador para la API.
        try:
            admin_role = UserRole.objects.get(code=CODE_ADMIN)
        except UserRole.DoesNotExist:
            raise CommandError('No existe el rol "Admin". Corre antes: manage.py seed_user_roles')

        user = User.objects.filter(username=username).first()
        if user is not None:
            if user.is_superuser and user.role_id is None:
                user.role = admin_role
                user.save(update_fields=["role"])
                self.stdout.write(self.style.SUCCESS(
                    f'Superusuario "{username}" ya existía sin rol: se le asignó rol Admin.'
                ))
            else:
                self.stdout.write(self.style.SUCCESS(f'Superusuario "{username}" ya existía.'))
            return

        if not password:
            self.stdout.write(self.style.WARNING(
                "DJANGO_SUPERUSER_PASSWORD vacío: no se crea el superusuario inicial."
            ))
            return
        if password == PLACEHOLDER_PASSWORD and not settings.DEBUG:
            self.stdout.write(self.style.WARNING(
                "DJANGO_SUPERUSER_PASSWORD sigue con el valor de ejemplo de .env.example: "
                "no se crea el superusuario inicial fuera de desarrollo."
            ))
            return

        User.objects.create_superuser(username, email, password, role=admin_role)
        self.stdout.write(self.style.SUCCESS(f'Superusuario "{username}" creado con rol Admin.'))
