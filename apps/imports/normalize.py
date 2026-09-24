# apps/imports/normalize.py
# Normalización compartida por todos los comandos de importación: mayúsculas,
# sin espacios extra, sin acentos, sin puntuación — para que "Matriz"/"MATRIZ "
# y "ING."/"ING" se reconozcan como el mismo valor al comparar.
import re
import unicodedata

# Sinónimos/abreviaciones con evidencia real en los datos (no genéricos) —
# por dominio, para no expandir "N" -> "NAVE" en un contexto donde no aplica.
SYNONYMS_BY_DOMAIN = {
    "puesto": {
        "AUX": "AUXILIAR",
        "AUXILIA": "AUXILIAR",
        "AXILIAR": "AUXILIAR",
        "AYUDANTE": "AUXILIAR",
        "ING": "INGENIERO",
        "COORDINADO": "COORDINADOR",
    },
    "nave": {
        "N": "NAVE",
    },
    "ubicacion": {
        "LOGISTIC": "LOGISTICS",
        "CDMX": "CIUDAD DE MEXICO",
    },
}

# Fusiones puntuales confirmadas a mano (no son abreviaciones generalizables,
# aplican a una frase completa específica) — domain -> {variante: canónica}.
WORD_MERGES_BY_DOMAIN = {
    "puesto": {
        "OPERADOR DE SOLDADOR": "OPERADOR DE SOLDADURA",
        "AUXILIAR DE SOLDADOR": "AUXILIAR DE SOLDADURA",
        "OPERADOR DE MAQUINADOS CNC": "OPERADOR DE MAQUINADO CNC",
        "OPERADORE DE MAQUINADOS CNC": "OPERADOR DE MAQUINADO CNC",
        "TECNICO EN MANTENIMIENTO": "TECNICO DE MANTENIMIENTO",
        "INGENIERO DE PROYECTOS": "INGENIERO DE PROYECTO",
        "INGENIERO EN APLICACIONES INTEGRALES": "INGENIERO DE APLICACIONES INTEGRALES",
        "EJECUTIVOS DE CUENTAS POR PAGAR": "EJECUTIVO DE CUENTAS POR PAGAR",
        "COORDINADOR DE ALMACENES": "COORDINADOR DE ALMACEN",
        "INGENIERIA DE SOPORTE": "INGENIERO DE SOPORTE",
        "OPERADOR SOLDADURA": "OPERADOR DE SOLDADURA",
        "AUXILIAR PRODUCCION": "AUXILIAR DE PRODUCCION",
        "AUXILIAR DE PRODUCCCION": "AUXILIAR DE PRODUCCION",
    },
    "ubicacion": {
        "PLANTA CIEM": "CIEM",
        "SUCURSAL CIUDAD DE MEXICO": "CIUDAD DE MEXICO",
    },
}


def normalize_text(value, domain=None):
    if value is None:
        return ""
    text = str(value).strip().upper()
    text = "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    text = re.sub(r"[.,;:_/\"'-]", " ", text)
    text = re.sub(r"(?<=[A-Z])(?=\d)", " ", text)
    text = re.sub(r"(?<=\d)(?=[A-Z])", " ", text)
    text = " ".join(text.split())

    if domain:
        synonyms = SYNONYMS_BY_DOMAIN.get(domain)
        if synonyms:
            text = " ".join(synonyms.get(tok, tok) for tok in text.split())
        merges = WORD_MERGES_BY_DOMAIN.get(domain)
        if merges and text in merges:
            text = merges[text]

    return text


def resolve_against_catalog(raw_value, queryset, domain, alias_model):
    """
    Intenta resolver `raw_value` contra `queryset` (un catálogo NamedCatalog):
    1) alias ya confirmado en RawValueAlias para ese dominio,
    2) coincidencia exacta por nombre normalizado (con sinónimos del dominio).
    Si no hay match, regresa (None, raw_value_normalizado) para que el
    llamador lo reporte como "sin resolver" — nunca crea nada solo.
    """
    normalized = normalize_text(raw_value, domain=domain)
    if not normalized:
        return None, normalized

    alias = alias_model.objects.filter(domain=domain, raw_value=normalized).first()
    if alias is not None:
        return alias.target, normalized

    for obj in queryset:
        if normalize_text(obj.name, domain=domain) == normalized:
            return obj, normalized

    return None, normalized
