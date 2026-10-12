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


# Los datos generales que salen de la Posición y se muestran como vinculados a
# ella. "Nombre del puesto" no entra: es el título del documento y se puede
# redactar distinto al nombre del Puesto.
CAMPOS_VINCULADOS = ("empresa", "area_departamento", "reporta_a")


def datos_de_posicion(posicion):
    """
    Lo que el sistema sabe HOY de la Posición para los datos generales del
    Descriptivo. Es la única fuente: la usan tanto el borrador al crearse como
    la comparación de cambios, para que no puedan divergir. Nunca se inventa:
    lo que falta (sin Puesto, sin unidad, sin jefe registrado) queda vacío.
    """
    puesto_jefe, _nombre_jefe = _jefe_inmediato(posicion)
    empresa = _empresa_de(posicion.organization_node)
    return {
        "nombre_puesto": posicion.puesto.name if posicion.puesto_id else "",
        "empresa": empresa.name if empresa else "",
        "area_departamento": posicion.organization_node.name,
        "reporta_a": puesto_jefe,
    }


def _sin_espacios_de_mas(texto):
    return " ".join((texto or "").split())


def cambios_de_posicion(descriptivo):
    """
    Datos vinculados de un BORRADOR que ya no coinciden con lo que hoy dice la
    Posición, para que quien lo edita decida cuáles incorporar. Cada cambio:
    campo, etiqueta, valor guardado en la versión y valor actual de la Posición.

    - Una versión aprobada nunca cambia, así que no tiene cambios que mostrar.
    - Si la Posición no sabe el dato (vacío), no se ofrece borrar el de la
      versión: no hay nada que incorporar.
    """
    if descriptivo.esta_congelado:
        return []
    actuales = datos_de_posicion(descriptivo.posicion)
    cambios = []
    for campo in CAMPOS_VINCULADOS:
        actual = actuales[campo]
        guardado = getattr(descriptivo, campo)
        if actual and _sin_espacios_de_mas(actual) != _sin_espacios_de_mas(guardado):
            cambios.append({
                "campo": campo,
                "etiqueta": str(DescriptivoPuesto._meta.get_field(campo).verbose_name),
                "guardado": guardado,
                "actual": actual,
            })
    return cambios


@transaction.atomic
def crear_borrador(posicion, user=None):
    """
    Primer borrador de la Posición, con los datos generales precargados de lo
    que el sistema ya sabe (Puesto, empresa, unidad, a quién reporta). Es una
    copia histórica a propósito: la versión conserva lo que decía al crearse
    aunque la Posición cambie después (ver cambios_de_posicion). "Supervisa a"
    NO se precarga: hoy Posicion.reports_to tiene cobertura incompleta, y un
    conteo parcial parecería un dato real -- se captura a mano.
    """
    descriptivo = DescriptivoPuesto(
        posicion=posicion,
        **datos_de_posicion(posicion),
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
