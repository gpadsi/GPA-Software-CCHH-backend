from django.core.management.base import BaseCommand

from apps.positions.models import AlcanceDePosicion, EstatusPosicion, TipoPosicion, TipoRequisicion

# Todos confirmados con datos reales de GPA (xlsx "SEGUIMIENTO A PERSONAL GPA").
ALCANCES = ["Operativo", "Ingeniería", "Administración", "Desarrollo de Negocios"]
TIPOS_POSICION = ["Fija", "Eventual", "Reemplazo"]
TIPOS_REQUISICION = ["Reemplazo", "Nueva Posición"]
ESTATUS = [
    "Colaborador Activo",
    "Colaborador Baja",
    "Trainee Activo",
    "Trainee Baja",
    "Vacante Pendiente de Confirmación",
    "Vacante Activa",
    "Vacante Suspendida",
    "Vacante Eliminada",
]


class Command(BaseCommand):
    help = "Siembra los catálogos de Posición confirmados con GPA (idempotente)."

    def _seed(self, model, names):
        created = 0
        for name in names:
            _, was_created = model.objects.get_or_create(name=name)
            created += int(was_created)
        return created, len(names) - created

    def handle(self, *args, **options):
        results = [
            ("Alcance de posición", *self._seed(AlcanceDePosicion, ALCANCES)),
            ("Tipo de posición", *self._seed(TipoPosicion, TIPOS_POSICION)),
            ("Tipo de requisición", *self._seed(TipoRequisicion, TIPOS_REQUISICION)),
            ("Estatus de posición", *self._seed(EstatusPosicion, ESTATUS)),
        ]
        summary = " | ".join(f"{name}: {c} creados, {e} ya existían" for name, c, e in results)
        self.stdout.write(self.style.SUCCESS(summary))
        self.stdout.write(self.style.WARNING(
            "Puesto se deja sin sembrar: los 241 valores reales de GPA están sin normalizar."
        ))
