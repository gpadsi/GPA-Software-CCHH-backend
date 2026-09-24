# apps/imports/management/commands/seed_normalized_puesto_nave_ubicacion.py
# Siembra los catálogos Puesto, Ubicacion, Nave y Area a partir de los
# valores reales de la sábana, agrupando variantes (typos, abreviaciones,
# mayúsculas/acentos) confirmadas con el usuario 2026-09-24. No toca
# Posicion aquí — eso se resuelve re-corriendo import_posiciones después,
# ahora que estos catálogos y sus alias ya existen.
#
# Area.nave queda temporal (ver apps/core/checks.py): en los datos reales
# Área casi siempre viene capturada pero Nave casi nunca, así que las Areas
# que se siembran aquí nacen sin Nave asignada — se completa después.
import re
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError

from apps.imports.models import RawValueAlias
from apps.imports.normalize import normalize_text
from apps.locations.models import Area, Nave, Ubicacion
from apps.organizations.models import OrganizationNode
from apps.positions.models import Puesto

HEADER_ROW_INDEX = 3

CONNECTOR_WORDS = {"DE", "DEL", "LA", "EL", "Y", "EN", "A", "PARA", "CON", "LOS", "LAS"}

# Combinaciones de Ubicación (2-3 sitios en una sola celda) -> se resuelven
# al primer sitio nombrado, documentado como supuesto (confirmado con el
# usuario: "asume conforme los datos que ya existen").
UBICACION_COMBINADAS = {
    "MATRIZ LOGISTICS CIEM": "MATRIZ",
    "MATRZ LOGISTICS CIEM": "MATRIZ",  # typo real en la sábana: falta la "I" en MATRIZ
    "MATRIZ LOGISTICS": "MATRIZ",
    "MATRIZ LOGISTIC": "MATRIZ",
}


def to_title_es(text):
    words = text.split()
    out = []
    for i, w in enumerate(words):
        if i > 0 and w.upper() in CONNECTOR_WORDS:
            out.append(w.lower())
        else:
            out.append(w.capitalize())
    return " ".join(out)


class Command(BaseCommand):
    help = "Siembra Puesto/Ubicacion/Nave normalizados a partir de la sábana, con sus alias de variantes."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--sheet", default="Posiciones")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"No existe el archivo: {path}")
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:
            raise CommandError(f"No se pudo abrir {path}: {exc}")
        ws = wb[options["sheet"]]
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        header = [h.strip() if isinstance(h, str) else h for h in rows[HEADER_ROW_INDEX]]
        col = {name: i for i, name in enumerate(header) if name}
        data_rows = rows[HEADER_ROW_INDEX + 1:]

        self._seed_puesto(data_rows, col)
        self._seed_ubicacion_y_nave(data_rows, col)
        self._seed_area(data_rows, col)

    # ---------------------------------------------------------------- Puesto
    def _seed_puesto(self, data_rows, col):
        counter = Counter()
        for row in data_rows:
            v = row[col["Puesto"]]
            if v is not None and str(v).strip():
                counter[str(v).strip()] += 1

        groups = defaultdict(list)
        for raw, cnt in counter.items():
            groups[normalize_text(raw, domain="puesto")].append((raw, cnt))

        ct = ContentType.objects.get_for_model(Puesto)
        created_puestos = 0
        created_aliases = 0
        for canon_val, variants in groups.items():
            representative = max(variants, key=lambda x: x[1])[0]
            display_name = to_title_es(representative) if representative.isupper() else representative
            puesto, was_created = Puesto.objects.get_or_create(name=display_name)
            created_puestos += int(was_created)
            for raw, _cnt in variants:
                raw_norm = normalize_text(raw, domain="puesto")
                if raw_norm == normalize_text(puesto.name, domain="puesto"):
                    continue
                _, alias_created = RawValueAlias.objects.get_or_create(
                    domain="puesto", raw_value=raw_norm,
                    defaults={
                        "raw_value_original": raw,
                        "content_type": ct,
                        "object_id": str(puesto.pk),
                    },
                )
                created_aliases += int(alias_created)

        self.stdout.write(self.style.SUCCESS(
            f"Puesto: {len(counter)} valores crudos -> {len(groups)} normalizados. "
            f"Creados: {created_puestos} Puesto, {created_aliases} alias."
        ))

    # ------------------------------------------------------ Ubicación y Nave
    def _seed_ubicacion_y_nave(self, data_rows, col):
        ubicacion_counter = Counter()
        nave_by_ubicacion = defaultdict(Counter)

        for row in data_rows:
            ubi_raw = row[col["Ubicación"]]
            ubi_raw = str(ubi_raw).strip() if ubi_raw else None
            if ubi_raw:
                ubicacion_counter[ubi_raw] += 1

            nave_raw = row[col["Nave"]]
            nave_raw = str(nave_raw).strip() if nave_raw else None
            if nave_raw and ubi_raw:
                nave_by_ubicacion[ubi_raw][nave_raw] += 1

        # --- Ubicación ---
        ubi_groups = defaultdict(list)
        for raw, cnt in ubicacion_counter.items():
            canon_val = normalize_text(raw, domain="ubicacion")
            canon_val = UBICACION_COMBINADAS.get(canon_val, canon_val)
            ubi_groups[canon_val].append((raw, cnt))

        ct_ubi = ContentType.objects.get_for_model(Ubicacion)
        ubicacion_por_canon = {}
        created_ubi = created_ubi_alias = 0
        for canon_val, variants in ubi_groups.items():
            representative = max(variants, key=lambda x: x[1])[0]
            code = re.sub(r"\s+", "-", canon_val).upper()[:30]
            display_name = to_title_es(canon_val) if canon_val.isupper() else representative
            ubicacion, was_created = Ubicacion.objects.get_or_create(code=code, defaults={"name": display_name})
            created_ubi += int(was_created)
            ubicacion_por_canon[canon_val] = ubicacion
            for raw, _cnt in variants:
                raw_norm = normalize_text(raw, domain="ubicacion")
                if raw_norm == canon_val:
                    continue
                _, alias_created = RawValueAlias.objects.get_or_create(
                    domain="ubicacion", raw_value=raw_norm,
                    defaults={"raw_value_original": raw, "content_type": ct_ubi, "object_id": str(ubicacion.pk)},
                )
                created_ubi_alias += int(alias_created)

        self.stdout.write(self.style.SUCCESS(
            f"Ubicacion: {len(ubicacion_counter)} valores crudos -> {len(ubi_groups)} normalizados. "
            f"Creados: {created_ubi} Ubicacion, {created_ubi_alias} alias."
        ))

        # --- Nave: solo patrón "NAVE <n>" real; lo demás (Matriz/Logistics
        # como si fueran Nave) se reporta, no se crea como nave inventada.
        ct_nave = ContentType.objects.get_for_model(Nave)
        created_nave = created_nave_alias = 0
        omitidos = []
        for ubi_raw, nave_counter_for_ubi in nave_by_ubicacion.items():
            ubi_canon = UBICACION_COMBINADAS.get(normalize_text(ubi_raw, domain="ubicacion"), normalize_text(ubi_raw, domain="ubicacion"))
            ubicacion = ubicacion_por_canon.get(ubi_canon)
            if ubicacion is None:
                continue

            nave_groups = defaultdict(list)
            for raw, cnt in nave_counter_for_ubi.items():
                nave_groups[normalize_text(raw, domain="nave")].append((raw, cnt))

            for canon_val, variants in nave_groups.items():
                if not re.fullmatch(r"NAVE \d+", canon_val):
                    omitidos.append((ubi_raw, variants))
                    continue
                representative = max(variants, key=lambda x: x[1])[0]
                code = canon_val.replace(" ", "-")
                nave, was_created = Nave.objects.get_or_create(
                    ubicacion=ubicacion, code=code, defaults={"name": to_title_es(canon_val)},
                )
                created_nave += int(was_created)
                for raw, _cnt in variants:
                    raw_norm = normalize_text(raw, domain="nave")
                    if raw_norm == canon_val:
                        continue
                    _, alias_created = RawValueAlias.objects.get_or_create(
                        domain="nave", raw_value=raw_norm,
                        defaults={"raw_value_original": raw, "content_type": ct_nave, "object_id": str(nave.pk)},
                    )
                    created_nave_alias += int(alias_created)

        self.stdout.write(self.style.SUCCESS(f"Nave: creadas {created_nave}, {created_nave_alias} alias."))
        if omitidos:
            self.stdout.write(self.style.WARNING(
                f"Nave: {len(omitidos)} valores omitidos por no parecer una nave real "
                f"(probablemente Ubicación mal capturada en la columna Nave): "
                f"{[(u, v) for u, v in omitidos]}"
            ))

    # -------------------------------------------------------------- Área
    def _seed_area(self, data_rows, col):
        """
        Área se siembra SIN Nave (nave=None, temporal) — solo para los
        valores que NO son eco de una Unidad de Negocio o de un nombre ya
        usado en Gerencia/Coordinación/Centro de Trabajo. Esos ecos (confirmados
        2026-09-24: 203 + 134 de 834 filas) no se crean como Área — repetir
        "MASS PRODUCTION" como si fuera un Área física sería inventar algo
        que los propios datos ya contradicen.
        """
        nombres_organizacion = {
            normalize_text(n) for n in OrganizationNode.objects.exclude(level__numero=1).values_list("name", flat=True)
        }

        area_counter = Counter()
        for row in data_rows:
            v = row[col["Área"]]
            if v is not None and str(v).strip():
                area_counter[str(v).strip()] += 1

        groups = defaultdict(list)
        eco_count = 0
        for raw, cnt in area_counter.items():
            canon_val = normalize_text(raw, domain="area")
            if canon_val in nombres_organizacion:
                eco_count += cnt
                continue
            groups[canon_val].append((raw, cnt))

        ct_area = ContentType.objects.get_for_model(Area)
        created_area = created_area_alias = 0
        for canon_val, variants in groups.items():
            representative = max(variants, key=lambda x: x[1])[0]
            code = re.sub(r"\s+", "-", canon_val).upper()[:30]
            display_name = to_title_es(canon_val) if canon_val.isupper() else representative
            area, was_created = Area.objects.get_or_create(nave=None, code=code, defaults={"name": display_name})
            created_area += int(was_created)
            for raw, _cnt in variants:
                raw_norm = normalize_text(raw, domain="area")
                if raw_norm == canon_val:
                    continue
                _, alias_created = RawValueAlias.objects.get_or_create(
                    domain="area", raw_value=raw_norm,
                    defaults={"raw_value_original": raw, "content_type": ct_area, "object_id": str(area.pk)},
                )
                created_area_alias += int(alias_created)

        self.stdout.write(self.style.SUCCESS(
            f"Área: {sum(area_counter.values())} filas -> {eco_count} son eco de Unidad de Negocio/organigrama "
            f"(no se crean), {len(groups)} áreas reales sembradas ({created_area} nuevas, {created_area_alias} alias), "
            f"todas sin Nave asignada todavía."
        ))
