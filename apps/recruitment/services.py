# apps/recruitment/services.py
# Operaciones sobre el Descriptivo de Puesto que tocan varias tablas a la
# vez (el borrador y sus listas/casillas) -- viven aquí y no en el modelo
# para que el modelo siga siendo solo reglas de integridad.
from django.db import transaction
from django.utils import timezone

from apps.recruitment.exports import _empresa_de, _jefe_inmediato
from apps.recruitment.models import DescriptivoPuesto, FuncionPuesto, IndicadorDesempeno

# Lo que se copia al crear un borrador desde una versión existente. Lista
# explícita a propósito: así nunca se arrastra auditoría, borrado lógico,
# número de versión ni la fecha de congelado de la versión de origen.
_CAMPOS_COPIABLES = (
    "nombre_puesto", "empresa", "area_departamento", "reporta_a", "supervisa_a",
    "edad", "edad_otro", "disponibilidad_viajar",
    "dias_por_laborar", "dias_por_laborar_otro", "horario", "horario_otro",
    "proposito", "decisiones_operativas", "decisiones_funcionales", "decisiones_estrategicas",
    "relaciones_internas", "relaciones_externas",
    "escolaridad_minima", "experiencia_requerida", "idiomas", "competencias_tecnicas",
    "competencias_otras", "recursos_otro",
)


@transaction.atomic
def crear_borrador(posicion, user=None):
    """
    Primer borrador de la Posición, con los datos generales precargados de lo
    que el sistema ya sabe (Puesto, empresa, unidad, a quién reporta). Todo
    es editable mientras sea borrador. "Supervisa a" NO se precarga: hoy
    Posicion.reports_to tiene cobertura incompleta, y un conteo parcial
    parecería un dato real -- se captura a mano.
    """
    puesto_jefe, _nombre_jefe = _jefe_inmediato(posicion)
    empresa = _empresa_de(posicion.organization_node)
    descriptivo = DescriptivoPuesto(
        posicion=posicion,
        nombre_puesto=posicion.puesto.name if posicion.puesto_id else "",
        empresa=empresa.name if empresa else "",
        area_departamento=posicion.organization_node.name,
        reporta_a=puesto_jefe,
        fecha_elaboracion=timezone.localdate(),
        created_by=user,
        updated_by=user,
    )
    descriptivo.full_clean()
    descriptivo.save()
    return descriptivo


@transaction.atomic
def copiar_version(origen, user=None):
    """
    Abre un borrador nuevo de la misma Posición con el contenido de `origen`
    (típicamente la versión congelada vigente) para editarlo sin tocar la
    original. Falla si la Posición ya tiene un borrador abierto.
    """
    nuevo = DescriptivoPuesto(
        posicion_id=origen.posicion_id,
        fecha_elaboracion=timezone.localdate(),
        created_by=user,
        updated_by=user,
    )
    for campo in _CAMPOS_COPIABLES:
        setattr(nuevo, campo, getattr(origen, campo))
    nuevo.full_clean()
    nuevo.save()

    nuevo.competencias.set(origen.competencias.all())
    nuevo.recursos.set(origen.recursos.all())
    for modelo, relacion in ((FuncionPuesto, origen.funciones), (IndicadorDesempeno, origen.indicadores)):
        for elemento in relacion.all():
            modelo.objects.create(
                descriptivo=nuevo, orden=elemento.orden, texto=elemento.texto,
                created_by=user, updated_by=user,
            )
    return nuevo
