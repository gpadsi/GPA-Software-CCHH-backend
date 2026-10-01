# apps/recruitment/management/commands/backfill_requisiciones_vacantes.py
# Crea una Requisicion "migrada" para las Posicion ya vacantes que traen
# los datos minimos reales para hacerlo SIN inventar nada: tipo_requisicion
# capturado y, si ese tipo exige justificacion (Nueva Posicion), una
# justificacion real -- que hoy no existe en ningun lado de la sabana, asi
# que esas quedan fuera a proposito, no se les escribe un texto generico.
# Idempotente: una Posicion que ya tiene alguna Requisicion (de esta
# corrida o de cualquier otra) no se vuelve a tocar.
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from apps.positions.models import Posicion
from apps.recruitment.models import EstadoRequisicion, Requisicion

# Traduce un valor YA CONFIRMADO de EstatusPosicion al estado equivalente
# de Requisicion -- no es una suposicion, es la misma informacion que ya
# estaba en la sabana, solo que ahora vive en un catalogo distinto.
MAPEO_ESTATUS_A_ESTADO = {
    "Vacante Activa": "En Reclutamiento",
    "Vacante Pendiente de Confirmación": "Pendiente de Autorización",
    "Vacante Suspendida": "Suspendida",
    "Vacante Eliminada": "Cancelada",
}


class Command(BaseCommand):
    help = (
        "Crea una Requisicion migrada para las Posicion ya vacantes que tienen "
        "los datos minimos reales (tipo_requisicion, y justificacion si el tipo "
        "la exige) -- nunca inventa nada; lo que falta se reporta, no se adivina."
    )

    def handle(self, *args, **options):
        migradas = 0
        omitidas = []

        vacantes = Posicion.objects.filter(
            estatus__name__startswith="Vacante", requisiciones__isnull=True,
        ).select_related("estatus", "tipo_requisicion")

        for posicion in vacantes:
            if posicion.tipo_requisicion_id is None:
                omitidas.append((posicion, "sin Tipo de requisición capturado"))
                continue

            nombre_estado = MAPEO_ESTATUS_A_ESTADO.get(posicion.estatus.name)
            estado = EstadoRequisicion.objects.filter(name=nombre_estado).first() if nombre_estado else None
            if estado is None:
                omitidas.append((posicion, f"sin mapeo de estado para estatus '{posicion.estatus.name}'"))
                continue

            if posicion.fecha_registro_vacante is None:
                omitidas.append((posicion, "sin fecha de registro de vacante"))
                continue

            requisicion = Requisicion(
                posicion=posicion,
                tipo=posicion.tipo_requisicion,
                estado=estado,
                fecha_solicitud=posicion.fecha_registro_vacante,
            )
            try:
                requisicion.full_clean()
                requisicion.save()
                migradas += 1
            except ValidationError as exc:
                omitidas.append((posicion, f"no pasó validación: {exc}"))

        self.stdout.write(self.style.SUCCESS(f"Requisición(es) migrada(s): {migradas}."))
        if omitidas:
            self.stdout.write(self.style.WARNING(
                f"{len(omitidas)} Posición(es) vacante(s) NO migradas (revisar a mano):"
            ))
            for posicion, razon in omitidas:
                self.stdout.write(self.style.WARNING(f"  {posicion} [{posicion.estatus}]: {razon}"))
