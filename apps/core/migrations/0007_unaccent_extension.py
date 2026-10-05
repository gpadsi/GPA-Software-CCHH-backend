from django.contrib.postgres.operations import UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):
    """
    Habilita `unaccent` de PostgreSQL para la busqueda sin acentos
    (apps.core.filters.AccentInsensitiveSearchFilter). Es una extension
    "trusted" desde PostgreSQL 13: no pide superusuario, solo poder crear
    extensiones en la base.
    """

    dependencies = [
        ("core", "0006_alter_documenttype_code_alter_documenttype_is_active_and_more"),
    ]

    operations = [UnaccentExtension()]
