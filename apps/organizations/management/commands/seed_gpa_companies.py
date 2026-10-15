from django.core.management.base import BaseCommand

from apps.organizations.models import Company, OrganizationalLevel, OrganizationNode

# Empresas y Unidades de Negocio reales de Grupo GPA, confirmadas por el
# usuario (2026-09-21/22) a partir del Excel de colaboradores actuales +
# una captura de la planeación real de la estructura. Los códigos de Empresa
# reutilizan el mismo prefijo que ya usa GPA en el código de empleado
# (ADV0001, CUT0010, etc.), no son un esquema inventado aquí.
#
# Nombres de las Unidades de Negocio tomados de la hoja «Configuración» de
# la sábana del 2026-10-15: GPA renombró las «General X» y agregó Additronics,
# Tooling e Industrial Services a Advanced Manufacturing. Este comando solo
# crea lo que falta (get_or_create por código); no renombra lo que ya existe,
# porque Capital Humano puede editar las unidades desde el organigrama.
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
        ("GPA-ADV-01.06", "Additronics"),
        ("GPA-ADV-01.07", "Tooling"),
        ("GPA-ADV-01.08", "Industrial Services"),
    ]),
    ("GPA-CUT-01", "GPA Cutting Systems", [
        ("GPA-CUT-01.01", "Cutting Systems"),
    ]),
    ("GPA-ADD-01", "GPA Additronics", [
        ("GPA-ADD-01.01", "Additronics"),
    ]),
    ("GPA-AZI-01", "GPA Azimatronics", [
        ("GPA-AZI-01.01", "Azimatronics"),
    ]),
    ("GPA-CEI-01", "CEI Aerospace Group", [
        ("GPA-CEI-01.01", "CEI"),
    ]),
    ("GPA-TEC-01", "GPA Technical Services", [
        ("GPA-TEC-01.01", "Technical Services"),
    ]),
    ("GPA-HOL-01", "GPA Holding Company", [
        ("GPA-HOL-01.01", "Holding GPA"),
    ]),
    ("GPA-CIM-01", "CIMSA", [
        ("GPA-CIM-01.01", "CIMSA"),
    ]),
    ("GPA-CMX-01", "CIMUX", [
        ("GPA-CMX-01.01", "CIMUX"),
    ]),
    ("GPA-AGR-01", "GPA Agroindustry", [
        ("GPA-AGR-01.01", "Agroindustry"),
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
        company_records_created = 0

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

            # Razón social/RFC/registro patronal AÚN no confirmados por GPA
            # para ninguna de las 12 (ver apps/core/checks.py) — se crea el
            # expediente igual, vacío, para que "Empresas" no aparezca en
            # blanco mientras se espera esa sábana corregida.
            _, company_record_created = Company.objects.get_or_create(organization_node=company_node)
            company_records_created += int(company_record_created)

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
            f"Unidades de Negocio: {units_created} creadas, {total_units - units_created} ya existían. "
            f"Expedientes Company: {company_records_created} creados, "
            f"{total_companies - company_records_created} ya existían (razón social/RFC/registro "
            f"patronal pendientes de GPA)."
        ))
