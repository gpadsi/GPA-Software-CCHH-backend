from django.core.management.base import BaseCommand

from apps.employment.models import CausaBaja, OrigenBaja

# Confirmado con GPA (xlsx "SEGUIMIENTO A PERSONAL GPA"): Causa depende de
# Origen, no es un catálogo plano compartido.
ORIGENES_Y_CAUSAS = {
    "Renuncia": [
        "Mejor oferta económica", "Desarrollo profesional",
        "Motivos personales o familiares", "Inconformidad con liderazgo",
        "Ambiente laboral", "Condiciones de trabajo", "Ubicación y traslado",
        "Emprendimiento", "Cambio de residencia", "Estudios", "Salud",
        "No especificado",
    ],
    "Despido": [
        "Bajo desempeño", "Incumplimiento de objetivos", "Faltas o indisciplina",
        "Violación de políticas o valores", "Reestructura o eliminación de puesto",
    ],
    "Abandono": ["Ausentismo prolongado", "No localizable"],
    "Terminación de Contrato": ["Fin de contrato o proyecto", "Periodo de Prueba No Aprobado"],
    "Mutuo Acuerdo": ["Jubilación", "Separación consensuada", "Cambio de empresa", "Cambio de área/puesto"],
}


class Command(BaseCommand):
    help = "Siembra Origen/Causa de baja confirmados con GPA (idempotente)."

    def handle(self, *args, **options):
        origenes_creados = 0
        causas_creadas = 0
        for origen_name, causas in ORIGENES_Y_CAUSAS.items():
            origen, created = OrigenBaja.objects.get_or_create(name=origen_name)
            origenes_creados += int(created)
            for causa_name in causas:
                _, causa_created = CausaBaja.objects.get_or_create(
                    origen_baja=origen, name=causa_name,
                )
                causas_creadas += int(causa_created)

        total_origenes = len(ORIGENES_Y_CAUSAS)
        total_causas = sum(len(c) for c in ORIGENES_Y_CAUSAS.values())
        self.stdout.write(self.style.SUCCESS(
            f"Origen de baja: {origenes_creados} creados, {total_origenes - origenes_creados} ya existían. "
            f"Causa de baja: {causas_creadas} creadas, {total_causas - causas_creadas} ya existían."
        ))
