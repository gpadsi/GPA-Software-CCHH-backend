# apps/recruitment/management/commands/seed_recruitment_catalogs.py
# Siembra los catalogos confirmados directo de los 3 formularios reales de
# GPA (2026-10-01) -- idempotente, mismo patron que seed_baja_catalogs.
from django.core.management.base import BaseCommand

from apps.positions.models import TipoRequisicion
from apps.recruitment.models import (
    CompetenciaConductual,
    DiasPorLaborar,
    EstadoRequisicion,
    EtapaAprobacion,
    HorarioACubrir,
    RangoEdad,
    RecursoAsignado,
    RolConformidad,
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

# Descriptivo de Puesto (FO-C0-CH-04): valores copiados tal cual del Word
# real, en el orden del formulario.
RANGOS_EDAD = ["18-25 años", "26-35 años", "36-45 años", "46-55 años", "Otro"]

DIAS_POR_LABORAR = ["Lunes a Viernes", "Lunes a Domingo", "Otro"]

COMPETENCIAS = [
    "Integridad",
    "Orientación a resultados",
    "Trabajo en equipo y colaboración",
    "Comunicación clara y efectiva",
    "Adaptabilidad y flexibilidad",
    "Innovación",
    "Liderazgo",
    "Orientación al cliente",
    "Planificación y organización",
    "Seguridad y sustentabilidad",
    "Resolución de conflictos y toma de decisiones",
    "Gestión del tiempo",
]

RECURSOS = [
    "Equipo de cómputo/laptop",
    "Teléfono corporativo",
    "Correo electrónico institucional",
    "Acceso a sistemas internos",
    "Herramientas y/o equipos asignados",
    "Uniforme/EPP",
    "Vehículo asignado",
    "Tarjeta de gasolina",
    "Tarjeta de viáticos",
    "Fondo fijo o caja chica asignada (para manejo de efectivo)",
]

# requiere_persona=True: la conformidad se liga a una Persona concreta (ver
# RolConformidad).
ROLES_CONFORMIDAD = {
    "Colaborador": True,
    "Jefe inmediato": False,
    "Capital Humano": False,
}


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
        for catalogo, nombres in (
            (RangoEdad, RANGOS_EDAD),
            (DiasPorLaborar, DIAS_POR_LABORAR),
            (CompetenciaConductual, COMPETENCIAS),
            (RecursoAsignado, RECURSOS),
        ):
            for name in nombres:
                _, created = catalogo.objects.get_or_create(name=name)
                creados += int(created)
        for name, requiere_persona in ROLES_CONFORMIDAD.items():
            _, created = RolConformidad.objects.get_or_create(name=name, defaults={"requiere_persona": requiere_persona})
            creados += int(created)

        actualizados = TipoRequisicion.objects.filter(
            name="Nueva Posición", requiere_justificacion=False,
        ).update(requiere_justificacion=True)

        self.stdout.write(self.style.SUCCESS(
            f"Catálogos de reclutamiento: {creados} valores nuevos creados. "
            f"TipoRequisicion.requiere_justificacion actualizado en {actualizados} fila(s)."
        ))
