# apps/imports/normalize.py
# Normalización compartida por todos los comandos de importación: mayúsculas,
# sin espacios extra, sin acentos — para que "Matriz"/"MATRIZ " y
# "Producción"/"PRODUCCION" se reconozcan como el mismo valor al comparar.
import unicodedata


def normalize_text(value):
    if value is None:
        return ""
    text = str(value).strip().upper()
    text = "".join(
        char for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    )
    return " ".join(text.split())


def resolve_against_catalog(raw_value, queryset, domain, alias_model):
    """
    Intenta resolver `raw_value` contra `queryset` (un catálogo NamedCatalog):
    1) alias ya confirmado en RawValueAlias para ese dominio,
    2) coincidencia exacta por nombre normalizado.
    Si no hay match, regresa (None, raw_value_normalizado) para que el
    llamador lo reporte como "sin resolver" — nunca crea nada solo.
    """
    normalized = normalize_text(raw_value)
    if not normalized:
        return None, normalized

    alias = alias_model.objects.filter(domain=domain, raw_value=normalized).first()
    if alias is not None:
        return alias.target, normalized

    for obj in queryset:
        if normalize_text(obj.name) == normalized:
            return obj, normalized

    return None, normalized
