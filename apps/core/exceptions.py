# apps/core/exceptions.py
# Traduce a una respuesta de API legible los errores de base de datos que son
# una regla de negocio y no un fallo del servidor.
from collections import Counter

from django.db.models.deletion import ProtectedError, RestrictedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler, set_rollback

# Cuántos tipos de registro se nombran en el mensaje antes de resumir el resto.
_MAX_TIPOS = 4


def _describir_bloqueos(objetos):
    """«4 Nodos organizacionales, 1 Posición» a partir de lo que impide borrar."""
    cuentas = Counter(type(objeto)._meta for objeto in objetos)
    partes = []
    for opciones, cantidad in cuentas.most_common(_MAX_TIPOS):
        nombre = opciones.verbose_name if cantidad == 1 else opciones.verbose_name_plural
        partes.append(f"{cantidad} {nombre}")
    restantes = len(cuentas) - _MAX_TIPOS
    if restantes > 0:
        partes.append(f"{restantes} tipo(s) de registro más")
    return ", ".join(partes)


def api_exception_handler(exc, context):
    """
    Borrar algo que otro registro todavía usa (FK con on_delete=PROTECT o
    RESTRICT) es un conflicto con el estado actual, no un error del servidor:
    sin esto la API respondía 500 y el front solo podía decir "algo falló".
    Ahora responde 409 con qué lo está usando.
    """
    if isinstance(exc, (ProtectedError, RestrictedError)):
        bloqueos = exc.protected_objects if isinstance(exc, ProtectedError) else exc.restricted_objects
        set_rollback()
        return Response(
            {
                "detail": (
                    "No se puede eliminar porque todavía está en uso por: "
                    f"{_describir_bloqueos(bloqueos)}. Resuelve esos registros primero."
                ),
                "code": "protected",
            },
            status=status.HTTP_409_CONFLICT,
        )
    return exception_handler(exc, context)
