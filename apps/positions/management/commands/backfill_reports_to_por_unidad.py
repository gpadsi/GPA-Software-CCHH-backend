# apps/positions/management/commands/backfill_reports_to_por_unidad.py
# Resuelve Posicion.reports_to (hoy 845 de 845 vacío) para las Posiciones
# que comparten Unidad de Negocio (organization_node) y Ubicación física
# (Área -> Nave -> Ubicación) con una Posición cuyo Puesto está marcado
# como Puesto.es_gerencia_de_unidad=True — confirmado con el usuario
# 2026-09-29: esa Posición es automáticamente el jefe de todas las demás
# de su mismo alcance.
#
# A PROPÓSITO no se dispara por texto ("¿el Puesto dice 'Gerente'?"): los
# 9 Puesto reales con "Gerente" en el nombre hoy son roles funcionales
# distintos (Capital Humano, Mantenimiento, Seguridad...), no un "jefe de
# toda la unidad" genérico — marcar el Puesto correcto es una decisión
# manual de RH en el admin (ver Puesto.es_gerencia_de_unidad), no algo
# que este comando adivine. Con los datos de hoy (ningún Puesto marcado)
# este comando no asigna nada — queda listo para cuando GPA confirme cuál
# Puesto sí representa ese rol.
#
# Nunca sobrescribe un reports_to que ya tenga valor, y nunca adivina
# cuando un alcance (unidad, ubicación) tiene 0 o 2+ candidatos a jefe —
# se reporta para revisión manual, mismo criterio que
# backfill_contratos_por_nombre.py.
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.positions.models import Posicion


class Command(BaseCommand):
    help = (
        "Resuelve Posicion.reports_to: la Posicion cuyo Puesto tiene "
        "es_gerencia_de_unidad=True es jefe de las demas Posiciones de su "
        "misma Unidad de Negocio y Ubicacion fisica."
    )

    def handle(self, *args, **options):
        base_qs = Posicion.objects.select_related(
            "puesto", "organization_node", "area", "area__nave", "area__nave__ubicacion",
        )

        candidatos = defaultdict(list)
        sin_ubicacion_fisica = []
        for posicion in base_qs.filter(puesto__es_gerencia_de_unidad=True):
            ubicacion = self._ubicacion_fisica(posicion)
            if ubicacion is None:
                sin_ubicacion_fisica.append(posicion)
                continue
            candidatos[(posicion.organization_node_id, ubicacion.pk)].append(posicion)

        if not candidatos and not sin_ubicacion_fisica:
            self.stdout.write(self.style.WARNING(
                "Ningún Puesto tiene es_gerencia_de_unidad=True todavía — nada que resolver."
            ))
            return

        jefe_por_alcance = {}
        ambiguos = {}
        for alcance, lista in candidatos.items():
            if len(lista) == 1:
                jefe_por_alcance[alcance] = lista[0]
            else:
                ambiguos[alcance] = lista

        asignadas = 0
        ya_tenian_reports_to = 0
        sin_alcance_resuelto = 0
        invalidas = []

        # Nunca toca una Posicion cuyo Puesto SÍ es gerencia de unidad — esa
        # es una cabeza (o candidata a serlo), no una subordinada de esta
        # regla. .exclude() (no .filter(...=False)) para no perder de la
        # cuenta a las Posiciones sin Puesto capturado todavía (puesto=None):
        # un filter(puesto__es_gerencia_de_unidad=False) las excluiría solas
        # por el INNER JOIN implícito de Django en una FK nula.
        with transaction.atomic():
            for posicion in base_qs.exclude(puesto__es_gerencia_de_unidad=True):
                if posicion.reports_to_id:
                    ya_tenian_reports_to += 1
                    continue
                ubicacion = self._ubicacion_fisica(posicion)
                if ubicacion is None:
                    sin_alcance_resuelto += 1
                    continue
                jefe = jefe_por_alcance.get((posicion.organization_node_id, ubicacion.pk))
                if jefe is None:
                    sin_alcance_resuelto += 1
                    continue
                posicion.reports_to = jefe
                try:
                    posicion.full_clean()
                    posicion.save()
                    asignadas += 1
                except ValidationError as exc:
                    invalidas.append((posicion, exc))

        self.stdout.write(self.style.SUCCESS(f"Posiciones con reports_to asignado: {asignadas}."))
        self.stdout.write(self.style.WARNING(
            f"Ya tenían reports_to (sin tocar): {ya_tenian_reports_to}. "
            f"Sin unidad+ubicación con jefe resuelto: {sin_alcance_resuelto}."
        ))
        if sin_ubicacion_fisica:
            self.stdout.write(self.style.WARNING(
                f"{len(sin_ubicacion_fisica)} candidato(s) a gerencia de unidad sin "
                f"Área→Nave→Ubicación completa — no se pudieron usar como jefe de nadie:"
            ))
            for p in sin_ubicacion_fisica:
                self.stdout.write(self.style.WARNING(f"  {p} (unidad: {p.organization_node})"))
        if ambiguos:
            self.stdout.write(self.style.WARNING(
                f"{len(ambiguos)} alcance(s) con MÁS DE UN candidato a gerencia de unidad "
                f"— ambiguo, no se asignó nadie a ese alcance:"
            ))
            for lista in ambiguos.values():
                nombres = ", ".join(f"{p} ({p.area})" for p in lista)
                self.stdout.write(self.style.WARNING(f"  {lista[0].organization_node}: {nombres}"))
        if invalidas:
            self.stdout.write(self.style.ERROR(f"{len(invalidas)} Posición(es) rechazadas al validar:"))
            for p, exc in invalidas:
                self.stdout.write(self.style.ERROR(f"  {p}: {exc}"))

    @staticmethod
    def _ubicacion_fisica(posicion):
        """La Ubicación real de una Posición, o None si su Área no tiene Nave asignada todavía."""
        if posicion.area_id and posicion.area.nave_id:
            return posicion.area.nave.ubicacion
        return None
