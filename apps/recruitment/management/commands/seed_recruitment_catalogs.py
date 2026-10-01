# apps/recruitment/management/commands/seed_recruitment_catalogs.py
# Siembra los catalogos confirmados directo de los 3 formularios reales de
# GPA (2026-10-01) -- idempotente, mismo patron que seed_baja_catalogs.
from django.core.management.base import BaseCommand

from apps.positions.models import TipoRequisicion
from apps.recruitment.models import (
    EstadoRequisicion,
    EtapaAprobacion,
    HorarioACubrir,
    TipoContratoOfrecido,
)

# es_terminal=True: una Requisicion en ese estado ya no cuenta como
# "abierta" (ver Requisicion.clean()).
ESTADOS = {
    "Borrador": False,
    "Pendiente de Autorización": False,
    "Autorizada": False,
    "Rechazada": True,
    "En Reclutamiento": False,
    "Suspendida": False,
    "Cubierta": True,
    "Cancelada": True,
}

ETAPAS = [
    "Jefe Inmediato",
    "Gerencia del Área",
    "Dirección General/VP",
    "Capital Humano",
]

TIPOS_CONTRATO = ["Planta", "Temporal"]

HORARIOS = ["8:00 - 17:45", "7:00 - 16:00", "15:00 - 24:00", "23:30 - 07:30", "Otro"]


class Command(BaseCommand):
    help = "Siembra los catálogos de Reclutamiento confirmados contra los formularios reales de GPA (idempotente)."

    def handle(self, *args, **options):
        creados = 0
        for name, es_terminal in ESTADOS.items():
            _, created = EstadoRequisicion.objects.get_or_create(name=name, defaults={"es_terminal": es_terminal})
            creados += int(created)
        for name in ETAPAS:
            _, created = EtapaAprobacion.objects.get_or_create(name=name)
            creados += int(created)
        for name in TIPOS_CONTRATO:
            _, created = TipoContratoOfrecido.objects.get_or_create(name=name)
            creados += int(created)
        for name in HORARIOS:
            _, created = HorarioACubrir.objects.get_or_create(name=name)
            creados += int(created)

        actualizados = TipoRequisicion.objects.filter(
            name="Nueva Posición", requiere_justificacion=False,
        ).update(requiere_justificacion=True)

        self.stdout.write(self.style.SUCCESS(
            f"Catálogos de reclutamiento: {creados} valores nuevos creados. "
            f"TipoRequisicion.requiere_justificacion actualizado en {actualizados} fila(s)."
        ))
