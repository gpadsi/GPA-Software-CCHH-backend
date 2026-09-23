from django.core.management.base import BaseCommand

from apps.organizations.models import Tenant


class Command(BaseCommand):
    help = "Siembra la organización única del sistema (idempotente)."

    def handle(self, *args, **options):
        _, created = Tenant.objects.get_or_create(
            code="GPA",
            defaults={"name": "Grupo GPA"},
        )
        if created:
            self.stdout.write(self.style.SUCCESS('Organización "Grupo GPA" creada.'))
        else:
            self.stdout.write(self.style.SUCCESS('Organización "Grupo GPA" ya existía.'))
