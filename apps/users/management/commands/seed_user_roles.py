from django.core.management.base import BaseCommand

from apps.users.models import UserRole

# Confirmado con el usuario (2026-09-22/23): exactamente estos 3, ni uno más.
# "Jefe" NO va aquí — se resuelve desde el organigrama, no es un rol de
# cuenta (ver docstring de UserRole). El código (slug) que genera cada
# nombre debe coincidir con los fijos en apps.core.permissions
# (CODE_CAPITAL_HUMANO="capital-humano", CODE_ADMIN="admin").
ROLES = ["Colaborador", "Capital Humano", "Admin"]


class Command(BaseCommand):
    help = "Siembra los 3 roles de usuario confirmados (idempotente)."

    def handle(self, *args, **options):
        created = 0
        for name in ROLES:
            _, was_created = UserRole.objects.get_or_create(name=name)
            created += int(was_created)

        self.stdout.write(self.style.SUCCESS(
            f"UserRole: {created} creados, {len(ROLES) - created} ya existían."
        ))
