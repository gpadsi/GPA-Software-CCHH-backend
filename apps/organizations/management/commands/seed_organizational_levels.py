from django.core.management.base import BaseCommand

from apps.organizations.models import OrganizationalLevel


# A partir de "Unidad de Negocio", el mismo nivel se anida a sí mismo tantas
# veces como haga falta (Gerencia de Operaciones -> Departamento de
# Producción -> Soldadura... son todas instancias de "Unidad de Negocio",
# distinguidas solo por su nombre y su profundidad, no por un nivel fijo
# distinto cada una). Por eso el catálogo tiene 3 niveles, no 8.
DEFAULT_ORGANIZATIONAL_LEVELS = [
    (1, "empresa", "Empresa", False),
    (2, "unidad_organizacional", "Unidad Organizacional", False),
    (3, "unidad_negocio", "Unidad de Negocio", True),
]


class Command(BaseCommand):
    help = "Siembra los niveles organizacionales iniciales (idempotente)."

    def handle(self, *args, **options):
        created_levels = 0
        for numero, code, name, allows_recursive_nesting in DEFAULT_ORGANIZATIONAL_LEVELS:
            _, was_created = OrganizationalLevel.objects.get_or_create(
                code=code,
                defaults={
                    "numero": numero,
                    "name": name,
                    "allows_recursive_nesting": allows_recursive_nesting,
                },
            )
            created_levels += int(was_created)

        level_total = len(DEFAULT_ORGANIZATIONAL_LEVELS)
        self.stdout.write(self.style.SUCCESS(
            "Niveles organizacionales: "
            f"{created_levels} creados, {level_total - created_levels} ya existían."
        ))
