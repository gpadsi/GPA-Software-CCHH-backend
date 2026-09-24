# apps/imports/management/commands/import_posiciones.py
# Importa la hoja "Posiciones" de la sábana de GPA: crea/actualiza Posicion,
# crea Contrato para quien ya tenga Empleado (por Nómina), y hace backfill
# de Persona.gender/birth_date cuando siguen vacíos.
#
# Supervisión se deja SIN interpretar a propósito (confirmado 2026-09-24):
# la columna mezcla nombres de persona con nombres de unidad, y GPA la irá
# corrigiendo con archivos futuros — el texto crudo queda en PosicionRawRow,
# no se usa para el árbol organizacional ni para reports_to.
#
# La cadena organizacional NO trata todos los niveles igual:
# - Empresa y Unidad de Negocio deben YA existir (catálogo confirmado a mano
#   con GPA) — si no coinciden, la fila se reporta sin resolver, no se
#   inventa una Unidad de Negocio nueva.
# - Gerencia/Coordinación/Centro de Trabajo SÍ se crean sobre la marcha si
#   no existen — son datos reales de GPA (no inventados), y ya se estableció
#   este mismo criterio para el ejemplo manual que se cargó antes.
import datetime
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.employment.models import CausaBaja, Contrato, Empleado, OrigenBaja
from apps.imports.models import ImportBatch, PosicionRawRow, RawValueAlias
from apps.imports.normalize import normalize_text, resolve_against_catalog
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

HEADER_ROW_INDEX = 3  # fila 4 del Excel (0-indexed)
REQUIRED_COLUMNS = ["Nomina", "Empresa", "Estatus"]
DEEP_LEVEL_COLUMNS = [("Gerencia", "gerencia"), ("Coordinación", "coordinacion"), ("Centro de Trabajo", "centro_trabajo")]


class Command(BaseCommand):
    help = (
        "Importa la hoja 'Posiciones' de la sábana de GPA: crea Posicion, "
        "crea Contrato para Empleados ya existentes, y hace backfill de Persona."
    )

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--sheet", default="Posiciones")
        parser.add_argument("--limit", type=int, default=None, help="Solo procesar las primeras N filas (para probar).")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"No existe el archivo: {path}")

        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:
            raise CommandError(f"No se pudo abrir {path}: {exc}")

        sheet_name = options["sheet"]
        if sheet_name not in wb.sheetnames:
            raise CommandError(f"La hoja «{sheet_name}» no existe. Hojas disponibles: {wb.sheetnames}")

        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        header = [h.strip() if isinstance(h, str) else h for h in rows[HEADER_ROW_INDEX]]
        col = {name: i for i, name in enumerate(header) if name}
        missing = [c for c in REQUIRED_COLUMNS if c not in col]
        if missing:
            raise CommandError(f"Faltan columnas esperadas: {missing}")

        batch = ImportBatch.objects.create(
            source=ImportBatch.SOURCE_SABANA_POSICIONES, original_filename=path.name,
        )

        un_level = OrganizationalLevel.objects.get(code="unidad_negocio")
        stats = Counter()
        unresolved = defaultdict(set)

        # Foto fija ANTES de importar: la Unidad de Negocio "de respaldo" de
        # cada Empresa — si solo tiene una confirmada, es esa; si tiene
        # varias (como Advanced Manufacturing), es la que se llama "General
        # X", que ya existe justo para los casos que no encajan en ninguna
        # unidad específica. Fija y no un conteo en vivo — si se recalculara
        # fila por fila, los nodos de Centro de Trabajo que se van creando
        # durante esta misma corrida (ver más abajo) la alterarían.
        default_unit_by_empresa = {}
        for empresa_node in OrganizationNode.objects.filter(level__numero=1):
            children = list(empresa_node.children.all())
            if len(children) == 1:
                default_unit_by_empresa[empresa_node.pk] = children[0]
            else:
                general = next((c for c in children if normalize_text(c.name).startswith("GENERAL")), None)
                if general is not None:
                    default_unit_by_empresa[empresa_node.pk] = general

        data_rows = rows[HEADER_ROW_INDEX + 1:]
        if options["limit"]:
            data_rows = data_rows[: options["limit"]]

        for i, row in enumerate(data_rows, start=HEADER_ROW_INDEX + 2):
            if all(v is None for v in row):
                continue

            data = {header[j]: self._cell_to_str(v) for j, v in enumerate(row) if header[j]}
            PosicionRawRow.objects.create(import_batch=batch, row_number=i, data=data)
            stats["filas"] += 1

            org_node = self._resolve_org_chain(row, col, un_level, unresolved, default_unit_by_empresa)
            if org_node is None:
                stats["sin_organization_node"] += 1
                continue

            estatus_raw = self._get(row, col, "Estatus")
            estatus, estatus_norm = resolve_against_catalog(estatus_raw, EstatusPosicion.objects.all(), "estatus", RawValueAlias)
            if estatus is None:
                unresolved["estatus"].add(estatus_norm)
                stats["sin_estatus"] += 1
                continue

            puesto, _ = self._resolve_optional(row, col, "Puesto", Puesto.objects.all(), "puesto", unresolved)
            alcance, _ = self._resolve_optional(row, col, "Alcance de Posición", AlcanceDePosicion.objects.all(), "alcance", unresolved)
            tipo_req, _ = self._resolve_optional(row, col, "Tipo de Requisición", TipoRequisicion.objects.all(), "tipo_requisicion", unresolved)
            tipo_pos, _ = self._resolve_optional(row, col, "Tipo de Posición", TipoPosicion.objects.all(), "tipo_posicion", unresolved)
            genero_req, _ = self._resolve_optional(row, col, "Genero", Genero.objects.all(), "genero", unresolved)

            posicion = Posicion(
                organization_node=org_node,
                puesto=puesto,
                alcance=alcance,
                tipo_requisicion=tipo_req,
                tipo_posicion=tipo_pos,
                genero_requerido=genero_req,
                estatus=estatus,
                fecha_registro_vacante=self._to_date(self._get(row, col, "Fecha Registro de Vacante")),
                fecha_autorizacion_vacante=self._to_date(self._get(row, col, "Fecha de Autorización de Vacante")),
                headhunter=self._clean(self._get(row, col, "Headhunter")) or "",
                solicitante_vacante=self._clean(self._get(row, col, "Solicitante de Vacante")) or "",
                proyecto_eventual=self._clean(self._get(row, col, "Proyecto Eventual")) or "",
                fecha_esperada_termino=self._to_date(self._get(row, col, "Fecha Esperada de Termino")),
            )
            try:
                posicion.full_clean()
                posicion.save()
            except ValidationError as exc:
                stats["posicion_error"] += 1
                self.stdout.write(self.style.ERROR(f"Fila {i}: Posicion inválida: {exc}"))
                continue
            stats["posiciones_creadas"] += 1

            nomina = self._get(row, col, "Nomina")
            empleado = None
            if nomina:
                work_number = str(nomina).strip().upper()
                empleado = Empleado.objects.filter(work_number=work_number).select_related("persona").first()
                if empleado is None:
                    stats["empleado_no_encontrado"] += 1
                else:
                    self._backfill_persona(empleado.persona, row, col, unresolved)

            fecha_ingreso = self._to_date(self._get(row, col, "Fecha de Ingreso como Colaborador"))
            if empleado is not None and fecha_ingreso is not None:
                origen_baja, _ = self._resolve_optional(row, col, "Origen de Baja", OrigenBaja.objects.all(), "origen_baja", unresolved)
                causa_baja = None
                causa_baja_raw = self._get(row, col, "Causa de Baja")
                if causa_baja_raw and origen_baja is not None:
                    causa_baja, causa_norm = resolve_against_catalog(
                        causa_baja_raw, CausaBaja.objects.filter(origen_baja=origen_baja), "causa_baja", RawValueAlias,
                    )
                    if causa_baja is None:
                        unresolved["causa_baja"].add(causa_norm)

                contrato = Contrato(
                    empleado=empleado,
                    posicion=posicion,
                    fecha_ingreso=fecha_ingreso,
                    fecha_baja=self._to_date(self._get(row, col, "Fecha de Baja como Colaborador")),
                    origen_baja=origen_baja,
                    causa_baja=causa_baja,
                    solicitante_baja=self._clean(self._get(row, col, "Solicitante de Baja")) or "",
                    observaciones=self._clean(self._get(row, col, "Observaciones")) or "",
                )
                try:
                    contrato.full_clean()
                    contrato.save()
                    stats["contratos_creados"] += 1
                except ValidationError as exc:
                    stats["contrato_error"] += 1
                    self.stdout.write(self.style.ERROR(f"Fila {i} ({work_number}): Contrato inválido: {exc}"))

        self._report(stats, unresolved)

    def _resolve_org_chain(self, row, col, un_level, unresolved, default_unit_by_empresa):
        empresa_name = self._clean(self._get(row, col, "Empresa"))
        if not empresa_name:
            return None
        empresa_node = self._find_by_name(OrganizationNode.objects.filter(level__numero=1), empresa_name)
        if empresa_node is None:
            unresolved["empresa"].add(normalize_text(empresa_name))
            return None
        current = empresa_node

        un_name = self._clean(self._get(row, col, "Unidad de Negocio"))
        # Artefacto ya confirmado (mismo patrón visto en "Lista Colaboradores"):
        # cuando Unidad de Negocio repite el nombre de la Empresa (con o sin
        # el prefijo "GPA "), no es una unidad real — se trata como "sin
        # especificar".
        empresa_core = normalize_text(empresa_name).removeprefix("GPA ")
        if un_name and normalize_text(un_name) in {normalize_text(empresa_name), empresa_core}:
            un_name = None

        deep_values = [self._clean(self._get(row, col, col_name)) for col_name, _ in DEEP_LEVEL_COLUMNS]
        tiene_nivel_profundo = any(deep_values)

        if un_name:
            un_node = self._find_by_name(current.children.all(), un_name)
            if un_node is None:
                # Regla confirmada 2026-09-24: si el texto no coincide con
                # ninguna Unidad de Negocio confirmada, se asume la unidad
                # "General [Empresa]" de esa misma empresa (o la única que
                # tenga, si nada más existe) — es justo el respaldo que ya
                # existe para esto, en vez de inventar a qué unidad
                # específica corresponde un texto ambiguo.
                un_node = default_unit_by_empresa.get(empresa_node.pk)
                if un_node is None:
                    unresolved["unidad_negocio"].add(f"{empresa_name} > {normalize_text(un_name)}")
                    return None
            current = un_node
        elif tiene_nivel_profundo:
            # Sin Unidad de Negocio pero SÍ con Gerencia/Coordinación/Centro
            # de Trabajo: se asume el mismo respaldo de arriba, para no
            # colgar el nivel profundo directo de la Empresa (eso mezclaría
            # dos profundidades distintas en el mismo nivel del árbol).
            un_node = default_unit_by_empresa.get(empresa_node.pk)
            if un_node is None:
                unresolved["falta_unidad_negocio_con_nivel_profundo"].add(
                    f"{empresa_name} > {' / '.join(v for v in deep_values if v)}"
                )
                return None
            current = un_node

        for column_name, _key in DEEP_LEVEL_COLUMNS:
            value = self._clean(self._get(row, col, column_name))
            if not value:
                continue
            child = self._find_by_name(current.children.all(), value)
            if child is None:
                next_seq = current.children.count() + 1
                code = f"{current.code}.{next_seq:02d}"
                child = OrganizationNode(code=code, name=value, level=un_level, parent=current)
                child.full_clean()
                child.save()
            current = child
        return current

    def _resolve_optional(self, row, col, column_name, queryset, domain, unresolved):
        raw = self._get(row, col, column_name)
        if not raw:
            return None, None
        obj, normalized = resolve_against_catalog(raw, queryset, domain, RawValueAlias)
        if obj is None:
            unresolved[domain].add(normalized)
        return obj, normalized

    def _backfill_persona(self, persona, row, col, unresolved):
        changed = False
        if persona.gender_id is None:
            genero_raw = self._get(row, col, "Genero")
            if genero_raw:
                genero, normalized = resolve_against_catalog(genero_raw, Genero.objects.all(), "genero", RawValueAlias)
                if genero is not None:
                    persona.gender = genero
                    changed = True
                else:
                    unresolved["genero"].add(normalized)
        if persona.birth_date is None:
            bd = self._to_date(self._get(row, col, "Fecha de Nacimiento"))
            if bd is not None:
                persona.birth_date = bd
                changed = True
        if changed:
            persona.full_clean()
            persona.save()

    def _report(self, stats, unresolved):
        self.stdout.write(self.style.SUCCESS(
            f"Filas procesadas: {stats['filas']}. Posiciones creadas: {stats['posiciones_creadas']}. "
            f"Contratos creados: {stats['contratos_creados']}."
        ))
        self.stdout.write(self.style.WARNING(
            f"Sin organization_node (Empresa/Unidad de Negocio no reconocida): {stats['sin_organization_node']}. "
            f"Sin Estatus resuelto: {stats['sin_estatus']}. Empleado no encontrado: {stats['empleado_no_encontrado']}. "
            f"Errores de validación en Posicion: {stats['posicion_error']}. Errores en Contrato: {stats['contrato_error']}."
        ))
        for domain, values in unresolved.items():
            if values:
                self.stdout.write(self.style.WARNING(f"Sin resolver [{domain}] ({len(values)}): {sorted(values)[:30]}"))

    @staticmethod
    def _find_by_name(queryset, name):
        target = normalize_text(name)
        for obj in queryset:
            if normalize_text(obj.name) == target:
                return obj
        return None

    @staticmethod
    def _get(row, col, name):
        idx = col.get(name)
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    @staticmethod
    def _clean(value):
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _cell_to_str(value):
        if value is None:
            return None
        if isinstance(value, (datetime.datetime, datetime.date)):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _to_date(value):
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        return None
