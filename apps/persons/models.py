from django.db import models

from apps.core.models import BaseAuditModel, NamedCatalog


class Genero(NamedCatalog):
    """Catálogo cerrado, confirmado con GPA: Masculino, Femenino, Indistinto."""

    class Meta(NamedCatalog.Meta):
        verbose_name = "Género"
        verbose_name_plural = "Géneros"


class EstadoCivil(NamedCatalog):
    class Meta(NamedCatalog.Meta):
        verbose_name = "Estado civil"
        verbose_name_plural = "Estados civiles"


class Escolaridad(NamedCatalog):
    class Meta(NamedCatalog.Meta):
        verbose_name = "Escolaridad"
        verbose_name_plural = "Escolaridades"


class TipoSangre(NamedCatalog):
    class Meta(NamedCatalog.Meta):
        verbose_name = "Tipo de sangre"
        verbose_name_plural = "Tipos de sangre"


class Persona(BaseAuditModel):
    """
    El humano — independiente de si trabaja aquí o no. NO se conecta a User
    ni a Puesto/Posición directamente: eso es responsabilidad de Empleado
    (apps.employment), que representa la relación laboral, no la persona.
    """
    first_name = models.CharField(max_length=100, verbose_name="Nombre(s)")
    last_name_paternal = models.CharField(max_length=100, verbose_name="Apellido paterno")
    last_name_maternal = models.CharField(
        max_length=100, blank=True, verbose_name="Apellido materno",
        help_text="Puede quedar vacío — no todas las personas lo tienen.",
    )

    # TEMPORAL (2026-09-23): null=True/blank=True mientras GPA completa estos
    # datos para todo el personal — ver apps/core/checks.py, que avisa en cada
    # `manage.py check` mientras sigan así. null=True (no solo blank=True) es
    # a propósito: con unique=True, blank="" colisionaría entre sí; NULL no.
    curp = models.CharField(max_length=18, unique=True, null=True, blank=True, verbose_name="CURP")
    nss = models.CharField(max_length=11, unique=True, null=True, blank=True, verbose_name="NSS")
    rfc = models.CharField(max_length=13, unique=True, null=True, blank=True, verbose_name="RFC")

    birth_date = models.DateField(null=True, blank=True, verbose_name="Fecha de nacimiento")
    # Simplificación deliberada: texto libre, no catálogo de estados/países.
    # No se construyó un catálogo geográfico (Country/State) en esta fase
    # porque no estaba en el plan confirmado — si hace falta filtrar/validar
    # por estado más adelante, se agrega entonces como su propio catálogo.
    birth_place_state = models.CharField(
        max_length=100, blank=True, verbose_name="Estado de nacimiento",
    )

    # TEMPORAL (2026-09-24): null=True/blank=True — ver apps/core/checks.py.
    # "Lista Colaboradores" (fuente real para crear Persona) no trae columna
    # de género en absoluto; llega después con la hoja "Posiciones".
    gender = models.ForeignKey(
        Genero, on_delete=models.PROTECT, null=True, blank=True, verbose_name="Género",
    )
    marital_status = models.ForeignKey(
        EstadoCivil, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Estado civil",
    )
    education_level = models.ForeignKey(
        Escolaridad, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Escolaridad",
    )
    has_children = models.BooleanField(default=False, verbose_name="Tiene hijos")

    personal_email = models.EmailField(blank=True, verbose_name="Correo personal")
    phone = models.CharField(max_length=20, blank=True, verbose_name="Teléfono")

    address_line = models.CharField(max_length=255, blank=True, verbose_name="Domicilio")
    # CharField, NUNCA numérico: un código postal con 0 a la izquierda pierde
    # el cero si se guarda como número (visto en datos reales de GPA).
    postal_code = models.CharField(max_length=10, blank=True, verbose_name="Código postal")
    city = models.CharField(max_length=100, blank=True, verbose_name="Ciudad")
    municipality = models.CharField(max_length=100, blank=True, verbose_name="Municipio")
    state = models.CharField(max_length=100, blank=True, verbose_name="Estado")

    def __str__(self):
        # Sin apellido materno (hay personas que no lo tienen) no queda un
        # espacio doble entre los demás.
        partes = (self.last_name_paternal, self.last_name_maternal, self.first_name)
        return " ".join(parte for parte in partes if parte and parte.strip())

    class Meta:
        db_table = "persons_persona"
        ordering = ["last_name_paternal", "last_name_maternal", "first_name"]
        verbose_name = "Persona"
        verbose_name_plural = "Personas"


class ContactoUrgencia(BaseAuditModel):
    persona = models.ForeignKey(
        Persona, on_delete=models.CASCADE, related_name="contactos_urgencia",
        verbose_name="Persona",
    )
    name = models.CharField(max_length=200, verbose_name="Nombre")
    relationship = models.CharField(max_length=100, verbose_name="Parentesco")
    phone = models.CharField(max_length=20, verbose_name="Teléfono")

    def __str__(self):
        return f"{self.name} ({self.relationship})"

    class Meta:
        verbose_name = "Contacto de urgencia"
        verbose_name_plural = "Contactos de urgencia"


class PerfilMedico(BaseAuditModel):
    """
    Separado de Persona a propósito: dato médico sensible, con control de
    acceso más estricto que el resto del expediente.
    """
    persona = models.OneToOneField(
        Persona, on_delete=models.CASCADE, related_name="perfil_medico",
        verbose_name="Persona",
    )
    blood_type = models.ForeignKey(
        TipoSangre, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Tipo de sangre",
    )
    allergies = models.TextField(blank=True, verbose_name="Alergias")

    def __str__(self):
        return f"Perfil médico — {self.persona}"

    class Meta:
        verbose_name = "Perfil médico"
        verbose_name_plural = "Perfiles médicos"
