# apps/employment/services.py
# Unico camino soportado para dar de alta o reingreso a alguien (confirmado
# con el usuario 2026-09-29, a raiz de la discusion sobre si un Empleado
# deberia depender de tener Contrato): Empleado y su Contrato se guardan
# juntos, en la misma transaccion, siempre pasando por full_clean(). Nunca
# deja un Empleado suelto sin Contrato.
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.employment.models import Contrato, Empleado


def dar_alta_nueva(*, persona, posicion, fecha_ingreso, work_number=None, user=None, **contrato_kwargs):
    """Crea un Empleado nuevo (Persona sin Empleado todavia) junto con su primer Contrato."""
    with transaction.atomic():
        empleado = Empleado(persona=persona, work_number=work_number, user=user)
        empleado.full_clean()
        empleado.save()
        contrato = _crear_contrato(empleado, posicion=posicion, fecha_ingreso=fecha_ingreso, **contrato_kwargs)
    return empleado, contrato


def dar_reingreso(*, empleado, posicion, fecha_ingreso, **contrato_kwargs):
    """Agrega un Contrato nuevo a un Empleado que ya existe (con su Contrato anterior cerrado)."""
    with transaction.atomic():
        # select_for_update: cierra la ventana entre "reviso si ya tiene un
        # Contrato vigente" (el UniqueConstraint de Contrato) e "inserto uno
        # nuevo" para dos reingresos simultaneos del mismo Empleado. La
        # constraint ya garantiza que nunca queden dos vigentes; esto solo
        # evita llegar a esa carrera en primer lugar.
        empleado = Empleado.objects.select_for_update().get(pk=empleado.pk)
        contrato = _crear_contrato(empleado, posicion=posicion, fecha_ingreso=fecha_ingreso, **contrato_kwargs)
    return empleado, contrato


def _crear_contrato(empleado, *, posicion, fecha_ingreso, **kwargs):
    errores = {}
    if kwargs.get("fecha_baja") is not None:
        errores["fecha_baja"] = "Un alta o reingreso no puede crearse ya cerrado."
    if kwargs.get("is_deleted"):
        errores["is_deleted"] = "Un alta o reingreso no puede crearse ya borrado."
    if kwargs.get("deleted_at") is not None or kwargs.get("deleted_by") is not None:
        errores["is_deleted"] = "Un alta o reingreso no puede incluir datos de borrado."
    if errores:
        raise ValidationError(errores)

    contrato = Contrato(empleado=empleado, posicion=posicion, fecha_ingreso=fecha_ingreso, **kwargs)
    contrato.full_clean()
    contrato.save()
    return contrato
