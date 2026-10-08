import unicodedata

import django.db.models.deletion
from django.db import migrations, models
from django.utils.text import slugify


def convertir_areas(apps, schema_editor):
    Area = apps.get_model("recruitment", "AreaSolicitante")
    Requisicion = apps.get_model("recruitment", "Requisicion")
    alias = schema_editor.connection.alias
    areas = Area.objects.using(alias)
    for requisicion in Requisicion.objects.using(alias).all().iterator():
        nombre = " ".join(requisicion.area_solicitante.split())
        if not nombre:
            continue
        clave = "".join(
            letra for letra in unicodedata.normalize("NFKD", nombre.casefold())
            if not unicodedata.combining(letra)
        )
        area = areas.filter(nombre_normalizado=clave).first()
        if area is None:
            base = slugify(nombre)[:50] or "area-solicitante"
            code, numero = base, 1
            while areas.filter(code=code).exists():
                sufijo = f"-{numero}"
                code = base[:50 - len(sufijo)] + sufijo
                numero += 1
            area = areas.create(name=nombre, code=code, nombre_normalizado=clave)
        Requisicion.objects.using(alias).filter(pk=requisicion.pk).update(area_solicitante_catalogo_id=area.pk)


def recuperar_textos(apps, schema_editor):
    Requisicion = apps.get_model("recruitment", "Requisicion")
    alias = schema_editor.connection.alias
    for requisicion in Requisicion.objects.using(alias).select_related("area_solicitante_catalogo").iterator():
        nombre = requisicion.area_solicitante_catalogo.name if requisicion.area_solicitante_catalogo_id else ""
        Requisicion.objects.using(alias).filter(pk=requisicion.pk).update(area_solicitante=nombre)


class Migration(migrations.Migration):
    dependencies = [("recruitment", "0003_requisicion_proxies_por_tipo")]

    operations = [
        migrations.CreateModel(
            name="AreaSolicitante",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(blank=True, max_length=50, unique=True, verbose_name="Código",
                    help_text="Identificador interno. Se genera solo a partir del Nombre.")),
                ("name", models.CharField(max_length=150, verbose_name="Nombre")),
                ("is_active", models.BooleanField(default=True, verbose_name="Activo")),
                ("nombre_normalizado", models.CharField(editable=False, max_length=300, unique=True)),
            ],
            options={"ordering": ["name"], "verbose_name": "Área solicitante", "verbose_name_plural": "Áreas solicitantes"},
        ),
        migrations.AddField(
            model_name="requisicion",
            name="area_solicitante_catalogo",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="requisiciones", to="recruitment.areasolicitante", verbose_name="Área solicitante",
                help_text="Departamento del catálogo que pide cubrir la plaza; no es Posicion.area (la nave)."),
        ),
        migrations.RunPython(convertir_areas, recuperar_textos),
        migrations.RemoveField(model_name="requisicion", name="area_solicitante"),
        migrations.RenameField(model_name="requisicion", old_name="area_solicitante_catalogo", new_name="area_solicitante"),
    ]
