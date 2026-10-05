from django.db.models import CharField, TextField
from rest_framework.filters import OrderingFilter, SearchFilter


def _termina_en_texto(model, path):
    """True si el ultimo campo de `path` (siguiendo relaciones, p. ej. persona__first_name) es de texto."""
    opts = model._meta
    campo = None
    for parte in path.split("__"):
        campo = opts.get_field("pk" if parte == "pk" else parte)
        if hasattr(campo, "path_infos"):
            opts = campo.path_infos[-1].to_opts
    return isinstance(campo, (CharField, TextField))


class AccentInsensitiveSearchFilter(SearchFilter):
    """
    `?search=` que ignora mayusculas Y acentos: "perez" encuentra "Pérez" y
    viceversa -- en espanol la gente no teclea acentos al buscar. Usa la
    extension `unaccent` de PostgreSQL (migracion core.0007), que solo existe
    para texto: un campo numerico (ej. el numero de catorcena) cae a
    `icontains` normal, que Postgres resuelve casteando a texto.

    Solo busca en los campos que la vista declara en `search_fields`; sin
    ellos no hace nada.
    """

    def construct_search(self, field_name, queryset):
        lookup = super().construct_search(field_name, queryset)
        sufijo = "__icontains"
        if lookup.endswith(sufijo):
            campo = lookup[: -len(sufijo)]
            if _termina_en_texto(queryset.model, campo):
                return f"{campo}__unaccent{sufijo}"
        return lookup

    def get_schema_operation_parameters(self, view):
        # El esquema OpenAPI solo anuncia ?search= en las listas que de verdad
        # lo soportan; sin esto aparecia en las 43 y mentia en 33.
        if not getattr(view, "search_fields", None):
            return []
        return super().get_schema_operation_parameters(view)


class SafeOrderingFilter(OrderingFilter):
    """
    `?ordering=` SOLO por los campos que la vista declara en `ordering_fields`.

    El OrderingFilter de DRF, sin `ordering_fields`, deja ordenar por CUALQUIER
    campo del serializer: ordenar por un campo permite inferir su contenido
    aunque no se muestre (ej. quien tiene el sueldo mas alto). Aqui una vista
    que no lo declara simplemente ignora el parametro.

    Agrega `pk` como desempate: ordenar por una columna con valores repetidos
    (apellido, estatus) sin un desempate estable hace que la paginacion
    repita o se salte filas entre una pagina y la siguiente.
    """

    def get_valid_fields(self, queryset, view, context=None):
        if getattr(view, "ordering_fields", self.ordering_fields) is None:
            return []
        return super().get_valid_fields(queryset, view, context or {})

    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        if not ordering:
            return queryset
        if not any(campo.lstrip("-") == "pk" for campo in ordering):
            ordering = [*ordering, "pk"]
        return queryset.order_by(*ordering)

    def get_schema_operation_parameters(self, view):
        # Igual que en la busqueda: solo se anuncia donde hay campos declarados.
        if not getattr(view, "ordering_fields", None):
            return []
        return super().get_schema_operation_parameters(view)
