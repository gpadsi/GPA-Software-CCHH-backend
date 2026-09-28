# apps/imports/management/commands/backfill_contratos_por_nombre.py
# Crea el Contrato de Empleados cuya Nómina en la sábana de Posiciones no
# coincidía con ningún Empleado real, pero cuyo nombre completo ("Nombre")
# SÍ coincide exacto con un Empleado ya existente bajo otro número —
# confirmado a mano el 2026-09-28 cruzando PosicionRawRow.data["Nombre"]
# contra Persona.first_name/last_name_paternal/last_name_maternal (ver
# docs/DATA_GAPS_JUSTIFICATION.md). Mismo criterio que NOMINA_TYPOS en
# import_posiciones.py — cada mapeo de abajo ya fue verificado 1 a 1, nada
# se adivina aquí.
#
# La parte delicada: a diferencia de una Asignación de horario (que solo
# necesita empleado+fecha+tipo), un Contrato necesita apuntar a una Posición
# YA CREADA, y Posicion no guarda de qué fila de la sábana vino. Para
# encontrar la Posición correcta sin adivinar, este comando reconstruye los
# mismos campos que habría calculado import_posiciones.py para esa fila
# (reutilizando sus propios métodos, no una reimplementación aparte) y solo
# actúa cuando esa reconstrucción encuentra EXACTAMENTE una Posición real
# que coincide en todos los campos. Si encuentra 0 o más de 1 coincidencia,
# no toca esa fila — se reporta para revisión manual, nunca se adivina cuál
# es la correcta.
import datetime
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.employment.models import CausaBaja, Contrato, Empleado, OrigenBaja
from apps.imports.management.commands.import_posiciones import (
    Command as ImportPosicionesCommand,
)
from apps.imports.models import PosicionRawRow, RawValueAlias
from apps.imports.normalize import normalize_text, resolve_against_catalog
from apps.locations.models import Area
from apps.organizations.models import OrganizationalLevel, OrganizationNode
from apps.persons.models import Genero
from apps.positions.models import (
    AlcanceDePosicion,
    EstatusPosicion,
    Posicion,
    Puesto,
    TipoPosicion,
    TipoRequisicion,
)

# Nómina tal como viene en la sábana de Posiciones -> número de nómina real
# del Empleado ya existente en el sistema.
NOMBRE_CONFIRMA_EMPLEADO = {
    "ADV034": "ADV0634",
    "ADD0004": "ADV1054",
    "ADD0170": "ADV1072",
    "ADD0064": "ADV1057",
    "ADD0165": "ADV1070",
    "ADD0153": "ADV1069",
    "ADD0087": "ADV1059",
    "ADD0191": "ADV1079",
    "ADV0556": "HOL0005",
    "CUT0476": "HOL0001",
    "ADD0021": "ADV1056",
    "ADD0183": "ADV1075",
    "ADD0119": "ADV1064",
    "ADD0175": "ADV1073",
    "CUT0492": "HOL0002",
    "ADD0116": "ADV1061",
    "ADD0073": "ADV1058",
    "ADD0187": "ADV1077",
    "ADD0190": "ADV1078",
    "AGR0009": "ADV0917",
    "ADD0178": "ADV1074",
    "ADD0185": "ADV1076",
    "ADD0194": "ADV1080",
    "ADD0071": "ADV0674",
    "ADD0117": "ADV1062",
    "ADD0133": "ADV1067",
    "ADD0151": "ADV1068",
    "CUT0472": "HOL0003",
    "ADD0196": "ADV1081",
    "ADV0563": "AZI0190",
    "ADV0867": "AZI0191",
    "AZI0186": "CUT0547",
    "ADD0125": "ADV1065",
    "ADD0127": "ADV1066",
    "ADD0099": "ADV1060",
    "ADV0560": "CEI0045",
    "CUT0461": "HOL0004",
    "CUT0524": "AZI0188",
    "ADD0001": "ADV1053",
    "ADD0167": "ADV1071",
    "ADD0118": "ADV1063",
    "ADD0017": "ADV1055",
}


class _NodoOAreaInesperados(Exception):
    """Señal interna para forzar el rollback completo de transaction.atomic()."""


class Command(BaseCommand):
    help = (
        "Crea el Contrato de los Empleados de NOMBRE_CONFIRMA_EMPLEADO, "
        "encontrando su Posicion real por reconstruccion exacta de campos "
        "(no por adivinanza). No crea nada si la reconstruccion encuentra "
        "0 o mas de 1 Posicion candidata para una fila."
    )

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                self._run(*args, **options)
        except _NodoOAreaInesperados as exc:
            self.stdout.write(self.style.ERROR(str(exc)))
            self.stdout.write(self.style.ERROR(
                "Se deshicieron todos los cambios de esta corrida (incluidos los "
                "Contrato que sí habían coincidido) — nada quedó a medias."
            ))

    def _run(self, *args, **options):
        importer = ImportPosicionesCommand()
        importer.stdout = self.stdout

        un_level = OrganizationalLevel.objects.get(code="unidad_negocio")
        unresolved = defaultdict(set)

        default_unit_by_empresa = {}
        for empresa_node in OrganizationNode.objects.filter(level__numero=1):
            children = list(empresa_node.children.all())
            if len(children) == 1:
                default_unit_by_empresa[empresa_node.pk] = children[0]
            else:
                general = next(
                    (c for c in children if normalize_text(c.name).startswith("GENERAL")),
                    None,
                )
                if general is not None:
                    default_unit_by_empresa[empresa_node.pk] = general

        nombres_organizacion = {
            normalize_text(n)
            for n in OrganizationNode.objects.exclude(level__numero=1).values_list(
                "name", flat=True
            )
        }
        for raw in PosicionRawRow.objects.all():
            for column_name in ("Gerencia", "Coordinación", "Centro de Trabajo"):
                value = importer._clean(raw.data.get(column_name))
                if value:
                    nombres_organizacion.add(normalize_text(value))

        fechas_alta_reingreso = importer._cargar_fechas_alta_reingreso()

        # Red de seguridad: este comando es de solo-lectura sobre el árbol
        # organizacional y las Áreas — si algo intentara crear un nodo o un
        # área nueva (no debería pasar: las 42 filas ya crearon su Posición
        # con éxito en la corrida original), se detiene en vez de continuar
        # en un estado que no se planeó.
        nodos_antes = OrganizationNode.objects.count()
        areas_antes = Area.objects.count()

        creados = 0
        omitidos = []

        for wn_archivo, wn_real in NOMBRE_CONFIRMA_EMPLEADO.items():
            raw_row = self._find_raw_row(wn_archivo)
            if raw_row is None:
                omitidos.append((wn_archivo, "no se encontró su fila cruda en PosicionRawRow"))
                continue

            row, col = self._as_row_and_col(raw_row.data)

            org_node = importer._resolve_org_chain(
                row, col, un_level, unresolved, default_unit_by_empresa
            )
            estatus, _ = resolve_against_catalog(
                importer._get(row, col, "Estatus"), EstatusPosicion.objects.all(), "estatus", RawValueAlias
            )
            puesto, _ = importer._resolve_optional(row, col, "Puesto", Puesto.objects.all(), "puesto", unresolved)
            area = importer._resolve_area(row, col, unresolved, nombres_organizacion)
            alcance, _ = importer._resolve_optional(row, col, "Alcance de Posición", AlcanceDePosicion.objects.all(), "alcance", unresolved)
            tipo_req, _ = importer._resolve_optional(row, col, "Tipo de Requisición", TipoRequisicion.objects.all(), "tipo_requisicion", unresolved)
            tipo_pos, _ = importer._resolve_optional(row, col, "Tipo de Posición", TipoPosicion.objects.all(), "tipo_posicion", unresolved)
            genero_req, _ = importer._resolve_optional(row, col, "Genero", Genero.objects.all(), "genero", unresolved)

            filtros = dict(
                organization_node=org_node,
                puesto=puesto,
                area=area,
                alcance=alcance,
                tipo_requisicion=tipo_req,
                tipo_posicion=tipo_pos,
                genero_requerido=genero_req,
                estatus=estatus,
                fecha_registro_vacante=self._iso_date(raw_row.data.get("Fecha Registro de Vacante")),
                fecha_autorizacion_vacante=self._iso_date(raw_row.data.get("Fecha de Autorización de Vacante")),
                headhunter=importer._clean(raw_row.data.get("Headhunter")) or "",
                solicitante_vacante=importer._clean(raw_row.data.get("Solicitante de Vacante")) or "",
                proyecto_eventual=importer._clean(raw_row.data.get("Proyecto Eventual")) or "",
                fecha_esperada_termino=self._iso_date(raw_row.data.get("Fecha Esperada de Termino")),
                supervision_texto=(importer._clean(raw_row.data.get("Supervisión")) or "")[:200],
            )
            candidatos = list(Posicion.objects.filter(**filtros))
            if len(candidatos) == 0:
                omitidos.append((wn_archivo, "0 Posiciones coinciden con la reconstrucción — no se toca"))
                continue
            if len(candidatos) > 1:
                omitidos.append((wn_archivo, f"{len(candidatos)} Posiciones coinciden — ambiguo, no se toca"))
                continue
            posicion = candidatos[0]

            if Contrato.objects.filter(posicion=posicion).exists():
                omitidos.append((wn_archivo, "esa Posición ya tiene un Contrato"))
                continue

            empleado = Empleado.objects.filter(work_number=wn_real).select_related("persona").first()
            if empleado is None:
                omitidos.append((wn_archivo, f"el empleado real {wn_real} ya no existe"))
                continue

            fecha_ingreso = self._iso_date(raw_row.data.get("Fecha de Ingreso como Colaborador"))
            if fecha_ingreso is None:
                omitidos.append((wn_archivo, "sin Fecha de Ingreso como Colaborador en la fila"))
                continue

            origen_baja, _ = importer._resolve_optional(row, col, "Origen de Baja", OrigenBaja.objects.all(), "origen_baja", unresolved)
            causa_baja = None
            causa_baja_raw = importer._get(row, col, "Causa de Baja")
            if causa_baja_raw and origen_baja is not None:
                causa_baja, causa_norm = resolve_against_catalog(
                    causa_baja_raw, CausaBaja.objects.filter(origen_baja=origen_baja), "causa_baja", RawValueAlias
                )
                if causa_baja is None:
                    unresolved["causa_baja"].add(causa_norm)

            fechas_colaborador = fechas_alta_reingreso.get(wn_real, {})
            contrato = Contrato(
                empleado=empleado,
                posicion=posicion,
                fecha_ingreso=fecha_ingreso,
                fecha_alta=fechas_colaborador.get("fecha_alta"),
                fecha_reingreso=fechas_colaborador.get("fecha_reingreso"),
                fecha_baja=self._iso_date(raw_row.data.get("Fecha de Baja como Colaborador")),
                origen_baja=origen_baja,
                causa_baja=causa_baja,
                solicitante_baja=importer._clean(raw_row.data.get("Solicitante de Baja")) or "",
                observaciones=importer._clean(raw_row.data.get("Observaciones")) or "",
            )
            try:
                contrato.full_clean()
                contrato.save()
                creados += 1
                self.stdout.write(self.style.SUCCESS(f"{wn_archivo} -> {wn_real}: Contrato creado."))
            except ValidationError as exc:
                omitidos.append((wn_archivo, f"Contrato inválido: {exc}"))

        if OrganizationNode.objects.count() != nodos_antes or Area.objects.count() != areas_antes:
            raise _NodoOAreaInesperados(
                "Este comando debía ser de solo-lectura sobre el árbol organizacional "
                "y las Áreas, pero algo creó un registro nuevo. No se confía en los "
                "Contrato de esta corrida."
            )

        self.stdout.write(self.style.SUCCESS(f"\nContratos creados: {creados} / {len(NOMBRE_CONFIRMA_EMPLEADO)}."))
        if omitidos:
            self.stdout.write(self.style.WARNING("Filas NO tocadas (revisar a mano):"))
            for wn, razon in omitidos:
                self.stdout.write(self.style.WARNING(f"  {wn}: {razon}"))
        for domain, values in unresolved.items():
            if values:
                self.stdout.write(self.style.WARNING(f"Sin resolver [{domain}]: {sorted(values)}"))

    @staticmethod
    def _find_raw_row(work_number_archivo):
        for raw in PosicionRawRow.objects.all():
            nomina = raw.data.get("Nomina")
            if nomina and str(nomina).strip().upper() == work_number_archivo:
                return raw
        return None

    @staticmethod
    def _as_row_and_col(data):
        keys = list(data.keys())
        row = [data[k] for k in keys]
        col = {k: i for i, k in enumerate(keys)}
        return row, col

    @staticmethod
    def _iso_date(value):
        if not value:
            return None
        try:
            return datetime.date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
