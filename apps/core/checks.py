from django.apps import apps as django_apps
from django.core.checks import Warning, register

# Campos que hoy permiten NULL de forma TEMPORAL porque la "sábana de datos"
# real de GPA todavía no los trae completos para todo el personal (decisión
# 2026-09-23, a partir de un ejemplo real que no los traía). Mientras sigan
# así, `manage.py check` avisa en cada corrida — dev, prod, y cada arranque
# del servidor. Cuando GPA confirme que el dato ya existe para todos los
# registros: quita null=True/blank=True del campo, corre
# makemigrations/migrate, y borra su entrada de esta lista. Si la lista queda
# vacía, este archivo ya no hace nada — bórralo también.
_TEMPORARILY_OPTIONAL_FIELDS = [
    ("persons", "Persona", "curp"),
    ("persons", "Persona", "nss"),
    ("persons", "Persona", "rfc"),
    ("persons", "Persona", "birth_date"),
    ("persons", "Persona", "gender"),
    ("employment", "Empleado", "work_number"),
    ("positions", "Posicion", "puesto"),
    ("positions", "Posicion", "area"),
]


@register()
def check_temporarily_optional_fields(app_configs, **kwargs):
    warnings = []
    for app_label, model_name, field_name in _TEMPORARILY_OPTIONAL_FIELDS:
        model = django_apps.get_model(app_label, model_name)
        field = model._meta.get_field(field_name)
        if not field.null:
            continue
        warnings.append(Warning(
            f"{model_name}.{field_name} sigue aceptando NULL de forma temporal.",
            hint=(
                "Pendiente de que GPA confirme que este dato ya está disponible "
                "para todo el personal. Cuando eso pase: quita null=True/"
                "blank=True, migra, y borra esta entrada de "
                "apps/core/checks.py::_TEMPORARILY_OPTIONAL_FIELDS."
            ),
            id=f"core.W_{app_label}_{model_name}_{field_name}",
        ))
    return warnings
