"""Carga nombres reales de la sábana, sin vincular el catálogo a su ubicación.

Se ejecuta a mano después de importar la sábana: en una instalación nueva
locations.Area aún está vacía, por lo que no se agrega al entrypoint.
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.locations.models import Area
from apps.recruitment.models import AreaSolicitante, normalizar_nombre_area

# La sábana marca con «CONFIDENCIAL», tanto en el puesto como en el área, las
# vacantes cuyo puesto real aún no se conoce. No son un departamento: Capital
# Humano las registra a mano cuando el dato se sepa, por eso no se copian.
AREAS_RESERVADAS = frozenset({"confidencial"})


class Command(BaseCommand):
    help = "Copia las áreas activas de la sábana al catálogo de áreas solicitantes (idempotente)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Muestra los cambios sin escribirlos.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        areas = Area.objects.filter(is_active=True, is_deleted=False).annotate(
            numero_posiciones=Count("posiciones"),
        )
        # La frecuencia manda; después se prefiere escritura natural y orden
        # alfabético. Solo se copian nombres, nunca referencias a las filas.
        variantes = sorted(areas, key=lambda area: (
            -area.numero_posiciones, area.name.isupper(),
            " ".join(area.name.split()).casefold(), " ".join(area.name.split()),
        ))
        elegidas = {}
        for area in variantes:
            normalizado = normalizar_nombre_area(area.name)
            if normalizado:
                elegidas.setdefault(normalizado, area)

        existentes = set(AreaSolicitante.objects.values_list("nombre_normalizado", flat=True))
        creadas = omitidas = reservadas = 0
        for normalizado, area in sorted(elegidas.items()):
            nombre = " ".join(area.name.split())
            if normalizado in AREAS_RESERVADAS:
                reservadas += 1
                self.stdout.write(f"Reservada, no se copia: {nombre} ({area.numero_posiciones} posiciones).")
                continue
            created = normalizado not in existentes
            if created and not dry_run:
                _, created = AreaSolicitante.objects.get_or_create(
                    nombre_normalizado=normalizado, defaults={"name": nombre},
                )
            if created:
                creadas += 1
                accion = "Crearía" if dry_run else "Creada"
            else:
                omitidas += 1
                accion = "Omitiría" if dry_run else "Omitida"
            self.stdout.write(f"{accion}: {nombre} ({area.numero_posiciones} posiciones).")

        resumen = (
            f"Simulación: {creadas} áreas se crearían; {omitidas} se omitirían."
            if dry_run else f"Áreas solicitantes: {creadas} creadas; {omitidas} omitidas."
        )
        self.stdout.write(self.style.SUCCESS(resumen))
        if reservadas:
            self.stdout.write(f"Reservadas (se registran a mano cuando se sepa el dato): {reservadas}.")
