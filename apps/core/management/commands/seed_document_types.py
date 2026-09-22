from django.core.management.base import BaseCommand

from apps.core.models import DocumentType

# Catálogo inicial tomado directamente de la lista de documentos de
# expediente (Inventarios de expedientes / Lety y Laura). "Descripción de
# puesto" es el único que no cuelga de una persona sino de un puesto — el
# propio modelo Attachment ya lo permite vía content_type/object_id.
# Códigos con guion, no guion bajo: es el mismo formato que genera el JS del
# admin (prepopulated_fields) al escribir el Nombre — un mismo tipo de
# documento debe llegar al mismo código sin importar por dónde se haya creado.
DEFAULT_DOCUMENT_TYPES = [
    ("acta-de-nacimiento", "Acta de nacimiento"),
    ("ine", "INE"),
    ("curp", "CURP"),
    ("constancia-de-situacion-fiscal", "Constancia de situación fiscal"),
    ("alta-de-imss", "Alta de IMSS"),
    ("carta-de-no-antecedentes", "Carta de no antecedentes"),
    ("curriculum", "Currículum"),
    ("solicitud-de-empleo", "Solicitud de empleo"),
    ("contrato", "Contrato"),
    ("constancias-de-estudios", "Constancias de estudios"),
    ("estudios-medicos", "Estudios médicos"),
    ("licencia", "Licencia (cuando aplique)"),
    ("comprobante-de-domicilio", "Comprobante de domicilio"),
    ("estado-de-cuenta-bancario", "Estado de cuenta bancario"),
    ("descripcion-de-puesto", "Descripción de puesto"),
]


class Command(BaseCommand):
    help = "Siembra el catálogo base de tipos de documento (idempotente)."

    def handle(self, *args, **options):
        created = 0
        for code, name in DEFAULT_DOCUMENT_TYPES:
            _, was_created = DocumentType.objects.get_or_create(
                code=code, defaults={"name": name}
            )
            created += int(was_created)
        total = len(DEFAULT_DOCUMENT_TYPES)
        self.stdout.write(self.style.SUCCESS(
            f"Tipos de documento: {created} creados, {total - created} ya existían."
        ))
