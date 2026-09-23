from django.core.management.base import BaseCommand

from apps.persons.models import Genero, TipoSangre

# Género: confirmado por el usuario (2026-09-22/23) — exactamente estos 3.
GENEROS = ["Masculino", "Femenino", "Indistinto"]

# Tipo de sangre: NO es un dato de negocio de GPA — es un hecho médico fijo
# y universal (como los estados de México), así que sembrarlo aquí no es
# "inventar" nada específico de GPA.
TIPOS_SANGRE = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]

# EstadoCivil y Escolaridad NO se siembran aquí a propósito: en los datos
# reales de GPA "Estado Civil" solo aparecía como letras sueltas (S/C/U/D)
# sin que el usuario confirmara el texto exacto de cada una, y Escolaridad
# nunca tuvo ningún dato real. Las tablas existen, listas para llenarse
# desde el admin en cuanto GPA confirme los valores — no se adivinan aquí.


class Command(BaseCommand):
    help = "Siembra los catálogos de Persona con valores confirmados (idempotente)."

    def handle(self, *args, **options):
        created_generos = 0
        for name in GENEROS:
            _, created = Genero.objects.get_or_create(name=name)
            created_generos += int(created)

        created_sangre = 0
        for name in TIPOS_SANGRE:
            _, created = TipoSangre.objects.get_or_create(name=name)
            created_sangre += int(created)

        self.stdout.write(self.style.SUCCESS(
            f"Género: {created_generos} creados, {len(GENEROS) - created_generos} ya existían. "
            f"Tipo de sangre: {created_sangre} creados, {len(TIPOS_SANGRE) - created_sangre} ya existían. "
            "EstadoCivil y Escolaridad se dejan vacíos a propósito (sin datos confirmados por GPA)."
        ))
