# apps/positions/management/commands/backfill_historial_puesto.py
# HistorialPuesto se agrego 2026-09-29, despues de que las 845 Posiciones
# reales ya existian -- a diferencia de HistorialReportaA (que se agrego
# antes del import grande y se lleno sola via Posicion.save()), estas
# todavia no tienen ninguna fila de historial. Este comando abre la fila
# vigente inicial para las que no tengan ninguna, usando la fecha de
# creacion de la Posicion como fecha_inicio -- es lo mas cercano que se
# tiene a "desde cuando", sin inventar una fecha. Idempotente: una Posicion
# que ya tiene alguna fila (las creadas despues de hoy, via Posicion.save())
# no se toca.
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.positions.models import HistorialPuesto, Posicion


class Command(BaseCommand):
    help = "Abre la fila vigente de HistorialPuesto para Posiciones que todavia no tienen ninguna."

    def handle(self, *args, **options):
        creadas = 0
        fechas_corregidas = 0
        for posicion in Posicion.objects.prefetch_related("historial_puesto"):
            historiales = list(posicion.historial_puesto.all())
            fecha_local = timezone.localdate(posicion.created_at)
            if not historiales:
                _, creada = HistorialPuesto.objects.get_or_create(
                    posicion=posicion,
                    fecha_fin__isnull=True,
                    defaults={"puesto": posicion.puesto, "fecha_inicio": fecha_local},
                )
                creadas += int(creada)
                continue

            # La primera versión del comando usó created_at.date() (UTC).
            # Repara de forma segura las filas iniciales que quedaron un día
            # adelante: solo una fila, todavía vigente y con exactamente la
            # fecha UTC antigua. No reescribe historiales con cambios reales.
            if len(historiales) == 1:
                historial = historiales[0]
                fecha_utc_anterior = posicion.created_at.date()
                if (
                    historial.fecha_fin is None
                    and historial.fecha_inicio == fecha_utc_anterior
                    and historial.fecha_inicio != fecha_local
                ):
                    historial.fecha_inicio = fecha_local
                    historial.save(update_fields=["fecha_inicio", "updated_at"])
                    fechas_corregidas += 1

        self.stdout.write(self.style.SUCCESS(f"HistorialPuesto creado para {creadas} Posicion(es)."))
        if fechas_corregidas:
            self.stdout.write(self.style.SUCCESS(
                f"Fechas iniciales corregidas a zona horaria local: {fechas_corregidas}."
            ))
