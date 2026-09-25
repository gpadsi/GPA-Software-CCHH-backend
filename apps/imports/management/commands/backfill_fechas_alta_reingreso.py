# apps/imports/management/commands/backfill_fechas_alta_reingreso.py
# Llena Contrato.fecha_alta/fecha_reingreso en los Contrato YA existentes,
# sin recrear ni borrar nada — a diferencia de import_posiciones (que no es
# idempotente y por eso requeriría limpiar Posicion/Contrato antes de
# volver a correrlo), esto es un UPDATE puntual sobre lo que ya está
# importado. Reutiliza la misma lectura de ColaboradorRawRow que
# import_posiciones usa para Contratos nuevos — ver ese comando para el
# porqué de leer de ahí en vez de un archivo aparte.
from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.employment.models import Contrato
from apps.imports.management.commands.import_posiciones import Command as ImportPosicionesCommand


class Command(BaseCommand):
    help = (
        "Backfill puntual: llena fecha_alta/fecha_reingreso en los Contrato "
        "que ya existen, a partir del ColaboradorRawRow más reciente ya "
        "importado. No crea ni borra Contrato ni Posicion."
    )

    def handle(self, *args, **options):
        fechas = ImportPosicionesCommand._cargar_fechas_alta_reingreso()
        if not fechas:
            self.stdout.write(self.style.WARNING(
                "No hay ningún ColaboradorRawRow importado todavía — nada que hacer."
            ))
            return

        actualizados = 0
        sin_dato = 0
        sin_work_number = 0

        candidatos = Contrato.objects.select_related("empleado").filter(
            Q(fecha_alta__isnull=True) | Q(fecha_reingreso__isnull=True)
        )
        for contrato in candidatos:
            work_number = contrato.empleado.work_number
            if not work_number:
                sin_work_number += 1
                continue

            datos = fechas.get(work_number.strip().upper())
            if not datos or (datos["fecha_alta"] is None and datos["fecha_reingreso"] is None):
                sin_dato += 1
                continue

            cambios = []
            if contrato.fecha_alta is None and datos["fecha_alta"] is not None:
                contrato.fecha_alta = datos["fecha_alta"]
                cambios.append("fecha_alta")
            if contrato.fecha_reingreso is None and datos["fecha_reingreso"] is not None:
                contrato.fecha_reingreso = datos["fecha_reingreso"]
                cambios.append("fecha_reingreso")

            if cambios:
                contrato.save(update_fields=[*cambios, "updated_at"])
                actualizados += 1

        self.stdout.write(self.style.SUCCESS(
            f"Contratos actualizados: {actualizados}. Sin dato en Colaboradores: {sin_dato}. "
            f"Sin work_number (Empleado incompleto): {sin_work_number}."
        ))
