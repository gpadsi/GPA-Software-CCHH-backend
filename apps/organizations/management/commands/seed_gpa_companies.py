from django.core.management.base import BaseCommand

from apps.organizations.models import OrganizationalLevel, OrganizationNode

# Empresas y Unidades de Negocio reales de Grupo GPA, confirmadas por el
# usuario (2026-09-21/22) a partir del Excel de colaboradores actuales +
# una captura de la planeación real de la estructura. Los códigos de Empresa
# reutilizan el mismo prefijo que ya usa GPA en el código de empleado
# (ADV0001, CUT0010, etc.), no son un esquema inventado aquí.
#
# GT Steel y Sound Traffic SOLO se siembran como Empresa: no hay ninguna
# Unidad de Negocio confirmada para ellas todavía. No se les inventa una
# "General GT Steel" / "General Sound Traffic" aunque el patrón de las demás
# empresas lo sugiera — eso hay que confirmarlo, no asumirlo.
COMPANIES = [
    ("GPA-ADV-01", "GPA Advanced Manufacturing", [
        ("GPA-ADV-01.01", "General Advanced"),
        ("GPA-ADV-01.02", "Proyectos Especiales"),
        ("GPA-ADV-01.03", "Mass Production"),
        ("GPA-ADV-01.04", "Sistemas de Corte"),
        ("GPA-ADV-01.05", "Parque de Innovación y Mentefactura"),
    ]),
    ("GPA-CUT-01", "GPA Cutting Systems", [
        ("GPA-CUT-01.01", "General Cutting"),
    ]),
    ("GPA-ADD-01", "GPA Additronics", [
        ("GPA-ADD-01.01", "General Additronics"),
    ]),
    ("GPA-AZI-01", "GPA Azimatronics", [
        ("GPA-AZI-01.01", "General Azimatronics"),
    ]),
    ("GPA-CEI-01", "CEI Aerospace Group", [
        ("GPA-CEI-01.01", "General CEI"),
    ]),
    ("GPA-TEC-01", "GPA Technical Services", [
        ("GPA-TEC-01.01", "General Technical"),
    ]),
    ("GPA-HOL-01", "GPA Holding Company", [
        ("GPA-HOL-01.01", "General Holding"),
    ]),
    ("GPA-CIM-01", "CIMSA", [
        ("GPA-CIM-01.01", "General CIMSA"),
    ]),
    ("GPA-CMX-01", "CIMUX", [
        ("GPA-CMX-01.01", "General CIMUX"),
    ]),
    ("GPA-AGR-01", "GPA Agroindustry", [
        ("GPA-AGR-01.01", "General Agroindustry"),
    ]),
    ("GPA-GTS-01", "GT Steel", []),
    ("GPA-SOU-01", "Sound Traffic", []),
]


class Command(BaseCommand):
    help = "Siembra las Empresas y Unidades de Negocio reales de Grupo GPA (idempotente)."

    def handle(self, *args, **options):
        empresa_level = OrganizationalLevel.objects.get(code="empresa")
        unidad_negocio_level = OrganizationalLevel.objects.get(code="unidad_negocio")

        companies_created = 0
        units_created = 0

        for company_code, company_name, units in COMPANIES:
            company_node, created = OrganizationNode.objects.get_or_create(
                code=company_code,
                defaults={
                    "level": empresa_level,
                    "name": company_name,
                    "parent": None,
                },
            )
            companies_created += int(created)

            for unit_code, unit_name in units:
                _, unit_created = OrganizationNode.objects.get_or_create(
                    code=unit_code,
                    defaults={
                        "level": unidad_negocio_level,
                        "name": unit_name,
                        "parent": company_node,
                    },
                )
                units_created += int(unit_created)

        total_companies = len(COMPANIES)
        total_units = sum(len(units) for _, _, units in COMPANIES)
        self.stdout.write(self.style.SUCCESS(
            f"Empresas: {companies_created} creadas, {total_companies - companies_created} ya existían. "
            f"Unidades de Negocio: {units_created} creadas, {total_units - units_created} ya existían."
        ))
