# apps/employment/management/commands/reportar_altas_pendientes.py
# Solo lectura: lista Empleados sin ningun Contrato y Empleados cuyo(s)
# Contrato ya estan todos cerrados -- confirmado con el usuario 2026-09-29
# como paso 1 antes de blindar el alta (Empleado+Contrato atomico, mas
# adelante): primero hay que saber cuantos pendientes hay y quienes son.
# No inventa ni asigna nada.
from django.core.management.base import BaseCommand

from apps.employment.models import Empleado


class Command(BaseCommand):
    help = (
        "Lista Empleados sin ningun Contrato y Empleados cuyo(s) Contrato "
        "ya estan todos cerrados. No modifica nada, solo reporta."
    )

    def handle(self, *args, **options):
        sin_contrato = Empleado.objects.filter(contratos__isnull=True).order_by("work_number")

        # Dos pasos, no un solo .exclude() encadenado: un
        # contratos__fecha_baja__isnull=True dentro de un exclude() sobre una
        # FK nula puede colar de vuelta a los que no tienen ningun Contrato
        # (mismo tipo de trampa de JOIN que en backfill_reports_to_por_unidad.py).
        con_algun_contrato = Empleado.objects.filter(contratos__isnull=False).distinct()
        con_vigente = Empleado.objects.filter(
            contratos__isnull=False, contratos__fecha_baja__isnull=True
        ).distinct()
        con_todo_cerrado = con_algun_contrato.exclude(
            pk__in=con_vigente.values("pk")
        ).order_by("work_number")

        self.stdout.write(self.style.WARNING(f"Sin ningun Contrato: {sin_contrato.count()}"))
        for empleado in sin_contrato:
            self.stdout.write(f"  {empleado.work_number or '(sin nomina)'} - {empleado.persona}")

        self.stdout.write(self.style.WARNING(f"\nCon Contrato(s) pero todos cerrados: {con_todo_cerrado.count()}"))
        for empleado in con_todo_cerrado:
            ultima_baja = empleado.contratos.order_by("-fecha_baja").first()
            fecha = ultima_baja.fecha_baja if ultima_baja else "?"
            self.stdout.write(f"  {empleado.work_number or '(sin nomina)'} - {empleado.persona} (ultima baja: {fecha})")

        total_pendientes = sin_contrato.count() + con_todo_cerrado.count()
        self.stdout.write(self.style.SUCCESS(
            f"\nTotal pendientes de conciliar: {total_pendientes} de {Empleado.objects.count()} Empleados."
        ))
