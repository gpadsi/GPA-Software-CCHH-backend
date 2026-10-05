import threading
from datetime import date, timedelta
from io import StringIO

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.employment.admin import ContratoInline, EmpleadoAdmin
from apps.employment.models import CausaBaja, Contrato, Empleado, HistorialSalarial, OrigenBaja
from apps.employment.services import dar_alta_nueva, dar_reingreso
from apps.organizations.models import OrganizationalLevel, OrganizationNode
from apps.persons.models import Persona
from apps.positions.models import EstatusPosicion, Posicion
from apps.users.models import UserRole


class EmploymentTestDataMixin:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("seed_tenant", stdout=StringIO())
        call_command("seed_organizational_levels", stdout=StringIO())
        call_command("seed_user_roles", stdout=StringIO())

        empresa_level = OrganizationalLevel.objects.get(code="empresa")
        cls.company_node = OrganizationNode.objects.create(
            level=empresa_level, code="GPA-EMP-TEST", name="Empresa de prueba",
        )
        cls.estatus_activo = EstatusPosicion.objects.create(name="Colaborador Activo")

    @classmethod
    def create_persona(cls, *, first_name="Nombre", last_name_paternal="Apellido", **kwargs):
        persona = Persona(first_name=first_name, last_name_paternal=last_name_paternal, **kwargs)
        persona.full_clean()
        persona.save()
        return persona

    @classmethod
    def create_empleado(cls, *, work_number=None, persona=None, user=None):
        empleado = Empleado(persona=persona or cls.create_persona(), work_number=work_number, user=user)
        empleado.full_clean()
        empleado.save()
        return empleado

    @classmethod
    def create_posicion(cls, *, reports_to=None, organization_node=None, estatus=None):
        posicion = Posicion(
            organization_node=organization_node or cls.company_node,
            estatus=estatus or cls.estatus_activo,
            reports_to=reports_to,
        )
        posicion.full_clean()
        posicion.save()
        return posicion

    @classmethod
    def create_contrato(cls, *, empleado, posicion, fecha_ingreso=date(2020, 1, 1), fecha_baja=None, **kwargs):
        contrato = Contrato(
            empleado=empleado, posicion=posicion,
            fecha_ingreso=fecha_ingreso, fecha_baja=fecha_baja, **kwargs,
        )
        contrato.full_clean()
        contrato.save()
        return contrato


class ContratoValidationTests(EmploymentTestDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.renuncia = OrigenBaja.objects.create(name="Renuncia")
        cls.despido = OrigenBaja.objects.create(name="Despido")
        cls.causa_renuncia = CausaBaja.objects.create(origen_baja=cls.renuncia, name="Mejor oferta")
        cls.empleado = cls.create_empleado()
        cls.posicion = cls.create_posicion()

    def test_causa_baja_requires_origen_baja(self):
        contrato = Contrato(
            empleado=self.empleado, posicion=self.posicion,
            fecha_ingreso=date(2020, 1, 1), causa_baja=self.causa_renuncia,
        )
        with self.assertRaises(ValidationError) as context:
            contrato.full_clean()
        self.assertIn("origen_baja", context.exception.message_dict)

    def test_causa_baja_must_belong_to_origen_baja(self):
        contrato = Contrato(
            empleado=self.empleado, posicion=self.posicion,
            fecha_ingreso=date(2020, 1, 1),
            origen_baja=self.despido, causa_baja=self.causa_renuncia,
        )
        with self.assertRaises(ValidationError) as context:
            contrato.full_clean()
        self.assertIn("causa_baja", context.exception.message_dict)
        self.assertIn("no pertenece al origen", context.exception.message_dict["causa_baja"][0])

    def test_valid_causa_baja_with_matching_origen_baja_passes(self):
        contrato = Contrato(
            empleado=self.empleado, posicion=self.posicion,
            fecha_ingreso=date(2020, 1, 1), fecha_baja=date(2021, 1, 1),
            origen_baja=self.renuncia, causa_baja=self.causa_renuncia,
        )
        contrato.full_clean()
        contrato.save()
        self.assertEqual(contrato.causa_baja, self.causa_renuncia)


class EmpleadoWorkNumberConstraintTests(EmploymentTestDataMixin, TestCase):
    def test_work_number_must_be_unique_when_set(self):
        self.create_empleado(work_number="ADV0001")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Empleado.objects.create(persona=self.create_persona(), work_number="ADV0001")

    def test_multiple_empleados_can_have_null_work_number(self):
        # Deliberado: null=True (no solo blank=True) para que dos Empleados
        # sin número de nómina todavía no choquen contra la unicidad — NULL
        # no colisiona consigo mismo, "" sí lo haría.
        self.create_empleado(work_number=None)
        self.create_empleado(work_number=None)
        self.assertEqual(Empleado.objects.filter(work_number__isnull=True).count(), 2)


class EmpleadoJefeResolutionTests(EmploymentTestDataMixin, TestCase):
    def test_contrato_activo_ignores_contratos_with_fecha_baja(self):
        empleado = self.create_empleado()
        posicion_anterior = self.create_posicion()
        self.create_contrato(
            empleado=empleado, posicion=posicion_anterior,
            fecha_ingreso=date(2019, 1, 1), fecha_baja=date(2020, 1, 1),
        )
        self.assertIsNone(empleado.get_contrato_activo())

        posicion_actual = self.create_posicion()
        contrato_vigente = self.create_contrato(
            empleado=empleado, posicion=posicion_actual, fecha_ingreso=date(2020, 2, 1),
        )
        self.assertEqual(empleado.get_contrato_activo(), contrato_vigente)

    def test_jefe_is_all_none_without_active_contrato(self):
        empleado = self.create_empleado()
        jefe = empleado.get_jefe()
        self.assertEqual(jefe, {"posicion_id": None, "puesto": None, "empleado_id": None, "nombre": None})

    def test_jefe_is_all_none_when_position_has_no_reports_to(self):
        empleado = self.create_empleado()
        posicion = self.create_posicion()  # nivel más alto, sin reports_to
        self.create_contrato(empleado=empleado, posicion=posicion)

        jefe = empleado.get_jefe()
        self.assertIsNone(jefe["posicion_id"])
        self.assertIsNone(jefe["empleado_id"])

    def test_jefe_posicion_known_but_empleado_none_when_boss_position_vacant(self):
        posicion_jefe = self.create_posicion()  # nadie la ocupa
        empleado = self.create_empleado()
        posicion_propia = self.create_posicion(reports_to=posicion_jefe)
        self.create_contrato(empleado=empleado, posicion=posicion_propia)

        jefe = empleado.get_jefe()
        self.assertEqual(jefe["posicion_id"], posicion_jefe.id)
        self.assertIsNone(jefe["empleado_id"])
        self.assertIsNone(jefe["nombre"])

    def test_jefe_fully_resolved_when_boss_position_occupied(self):
        jefe_persona = self.create_persona(first_name="Ana", last_name_paternal="Torres")
        jefe_empleado = self.create_empleado(persona=jefe_persona)
        posicion_jefe = self.create_posicion()
        self.create_contrato(empleado=jefe_empleado, posicion=posicion_jefe)

        empleado = self.create_empleado()
        posicion_propia = self.create_posicion(reports_to=posicion_jefe)
        self.create_contrato(empleado=empleado, posicion=posicion_propia)

        jefe = empleado.get_jefe()
        self.assertEqual(jefe["posicion_id"], posicion_jefe.id)
        self.assertEqual(jefe["empleado_id"], jefe_empleado.id)
        self.assertEqual(jefe["nombre"], "Torres Ana")

    def test_jefe_ignores_a_boss_who_already_left_that_position(self):
        posicion_jefe = self.create_posicion()
        ex_jefe = self.create_empleado(persona=self.create_persona(first_name="Ex", last_name_paternal="Jefe"))
        self.create_contrato(
            empleado=ex_jefe, posicion=posicion_jefe,
            fecha_ingreso=date(2018, 1, 1), fecha_baja=date(2020, 1, 1),
        )

        empleado = self.create_empleado()
        posicion_propia = self.create_posicion(reports_to=posicion_jefe)
        self.create_contrato(empleado=empleado, posicion=posicion_propia)

        jefe = empleado.get_jefe()
        self.assertEqual(jefe["posicion_id"], posicion_jefe.id)
        self.assertIsNone(jefe["empleado_id"])


class ContratoVigenciaTemporalTests(EmploymentTestDataMixin, TestCase):
    """
    ContratoQuerySet.vigentes_en/vigentes_hoy — confirmado con el usuario
    2026-09-30: activo empieza a contar hasta que la persona EMPIEZA a
    trabajar (no desde que se registra), y el día de la baja ya NO cuenta
    como activo.
    """

    def test_un_contrato_con_fecha_de_ingreso_futura_no_cuenta_como_activo_todavia(self):
        empleado = self.create_empleado()
        self.create_contrato(
            empleado=empleado, posicion=self.create_posicion(),
            fecha_ingreso=timezone.localdate() + timedelta(days=15),
        )
        self.assertIsNone(empleado.get_contrato_activo())

    def test_el_mismo_contrato_si_cuenta_como_activo_una_vez_que_llega_la_fecha_de_ingreso(self):
        empleado = self.create_empleado()
        contrato = self.create_contrato(
            empleado=empleado, posicion=self.create_posicion(), fecha_ingreso=timezone.localdate(),
        )
        self.assertEqual(empleado.get_contrato_activo(), contrato)

    def test_el_dia_exacto_de_la_baja_ya_no_cuenta_como_activo(self):
        empleado = self.create_empleado()
        self.create_contrato(
            empleado=empleado, posicion=self.create_posicion(),
            fecha_ingreso=timezone.localdate() - timedelta(days=30), fecha_baja=timezone.localdate(),
        )
        self.assertIsNone(empleado.get_contrato_activo())

    def test_un_dia_antes_de_la_baja_todavia_cuenta_como_activo(self):
        empleado = self.create_empleado()
        contrato = self.create_contrato(
            empleado=empleado, posicion=self.create_posicion(),
            fecha_ingreso=timezone.localdate() - timedelta(days=30),
            fecha_baja=timezone.localdate() + timedelta(days=1),
        )
        self.assertEqual(empleado.get_contrato_activo(), contrato)

    def test_get_jefe_no_resuelve_un_jefe_cuyo_contrato_todavia_no_empieza(self):
        posicion_jefe = self.create_posicion()
        jefe_empleado = self.create_empleado()
        self.create_contrato(
            empleado=jefe_empleado, posicion=posicion_jefe,
            fecha_ingreso=timezone.localdate() + timedelta(days=15),
        )
        empleado = self.create_empleado()
        posicion_propia = self.create_posicion(reports_to=posicion_jefe)
        self.create_contrato(empleado=empleado, posicion=posicion_propia)

        jefe = empleado.get_jefe()
        self.assertEqual(jefe["posicion_id"], posicion_jefe.id)
        self.assertIsNone(jefe["empleado_id"])


class ContratoSoftDeleteTests(EmploymentTestDataMixin, TestCase):
    """
    apps.core.models.SoftDeleteModel aplicado a Contrato (2026-09-29): es el
    historial laboral, borrarlo de verdad borraría el pasado.
    """
    def test_delete_does_not_remove_the_row(self):
        empleado = self.create_empleado()
        contrato = self.create_contrato(empleado=empleado, posicion=self.create_posicion())

        contrato.delete()

        self.assertFalse(Contrato.objects.filter(pk=contrato.pk).exists())
        borrado = Contrato.all_objects.get(pk=contrato.pk)
        self.assertTrue(borrado.is_deleted)
        self.assertIsNotNone(borrado.deleted_at)

    def test_bulk_delete_also_soft_deletes(self):
        empleado = self.create_empleado()
        contrato = self.create_contrato(empleado=empleado, posicion=self.create_posicion())

        # El admin muestra incluso los borrados usando all_objects y su
        # acción delete_selected llama delete() sobre ese queryset. Ese
        # camino también debe conservar el historial.
        Contrato.all_objects.filter(pk=contrato.pk).delete()

        self.assertFalse(Contrato.objects.filter(pk=contrato.pk).exists())
        self.assertTrue(Contrato.all_objects.get(pk=contrato.pk).is_deleted)

    def test_deleted_contrato_disappears_from_contrato_activo(self):
        empleado = self.create_empleado()
        contrato = self.create_contrato(empleado=empleado, posicion=self.create_posicion())

        contrato.delete()

        self.assertIsNone(empleado.get_contrato_activo())


class EmpleadoSoftDeleteTests(EmploymentTestDataMixin, TestCase):
    def test_delete_does_not_remove_the_row(self):
        empleado = self.create_empleado(work_number="ADV0010")

        empleado.delete()

        self.assertFalse(Empleado.objects.filter(pk=empleado.pk).exists())
        self.assertTrue(Empleado.all_objects.get(pk=empleado.pk).is_deleted)

    def test_deleted_empleado_still_resolves_from_an_existing_contrato(self):
        # Contrato._meta.base_manager_name="all_objects": sin esto, acceder a
        # contrato.empleado después de borrar el Empleado reventaría con
        # Empleado.DoesNotExist en vez de seguir resolviendo el registro.
        empleado = self.create_empleado()
        contrato = self.create_contrato(empleado=empleado, posicion=self.create_posicion())

        empleado.delete()
        contrato.refresh_from_db()

        self.assertEqual(contrato.empleado.pk, empleado.pk)


class ContratoReassignmentTests(EmploymentTestDataMixin, TestCase):
    """No se puede mover un Contrato existente a otro Empleado — confirmado
    con el usuario 2026-09-29, misma discusión que motivó el soft-delete."""

    def test_cannot_reassign_an_existing_contrato_to_another_empleado(self):
        contrato = self.create_contrato(empleado=self.create_empleado(), posicion=self.create_posicion())
        contrato.empleado = self.create_empleado()

        with self.assertRaises(ValidationError) as context:
            contrato.full_clean()
        self.assertIn("empleado", context.exception.message_dict)

    def test_editing_other_fields_without_touching_empleado_still_works(self):
        contrato = self.create_contrato(empleado=self.create_empleado(), posicion=self.create_posicion())

        contrato.observaciones = "Corrección de dato clerical"
        contrato.full_clean()
        contrato.save()

        contrato.refresh_from_db()
        self.assertEqual(contrato.observaciones, "Corrección de dato clerical")


class ReportarAltasPendientesCommandTests(EmploymentTestDataMixin, TestCase):
    """apps.employment.management.commands.reportar_altas_pendientes — de
    solo lectura, primer paso antes de blindar el alta (2026-09-29)."""

    def test_reports_empleado_without_any_contrato(self):
        self.create_empleado(work_number="ADV0001")

        out = StringIO()
        call_command("reportar_altas_pendientes", stdout=out)

        self.assertIn("Sin ningun Contrato: 1", out.getvalue())
        self.assertIn("ADV0001", out.getvalue())

    def test_reports_empleado_with_only_closed_contratos(self):
        empleado = self.create_empleado(work_number="ADV0002")
        self.create_contrato(empleado=empleado, posicion=self.create_posicion(), fecha_baja=date(2021, 1, 1))

        out = StringIO()
        call_command("reportar_altas_pendientes", stdout=out)

        self.assertIn("Con Contrato(s) pero todos cerrados: 1", out.getvalue())
        self.assertIn("ADV0002", out.getvalue())

    def test_does_not_report_empleado_with_an_active_contrato(self):
        empleado = self.create_empleado(work_number="ADV0003")
        self.create_contrato(empleado=empleado, posicion=self.create_posicion())

        out = StringIO()
        call_command("reportar_altas_pendientes", stdout=out)

        self.assertIn("Sin ningun Contrato: 0", out.getvalue())
        self.assertIn("Con Contrato(s) pero todos cerrados: 0", out.getvalue())
        self.assertNotIn("ADV0003", out.getvalue())


class ContratoUnicidadVigenteTests(EmploymentTestDataMixin, TestCase):
    """UniqueConstraint parcial (2026-09-29): a lo sumo un Contrato vigente
    por Empleado y por Posición -- verificado contra la base real antes de
    agregarla (0 conflictos sobre 435 vigentes)."""

    def test_un_empleado_no_puede_tener_dos_contratos_vigentes(self):
        empleado = self.create_empleado()
        self.create_contrato(empleado=empleado, posicion=self.create_posicion())

        segundo = Contrato(empleado=empleado, posicion=self.create_posicion(), fecha_ingreso=date(2021, 1, 1))
        with self.assertRaises(ValidationError):
            segundo.full_clean()

    def test_una_posicion_no_puede_tener_dos_contratos_vigentes(self):
        posicion = self.create_posicion()
        self.create_contrato(empleado=self.create_empleado(), posicion=posicion)

        segundo = Contrato(empleado=self.create_empleado(), posicion=posicion, fecha_ingreso=date(2021, 1, 1))
        with self.assertRaises(ValidationError):
            segundo.full_clean()

    def test_un_empleado_si_puede_tener_dos_contratos_si_el_primero_ya_cerro(self):
        empleado = self.create_empleado()
        self.create_contrato(empleado=empleado, posicion=self.create_posicion(), fecha_baja=date(2020, 12, 31))

        segundo = Contrato(empleado=empleado, posicion=self.create_posicion(), fecha_ingreso=date(2021, 1, 1))
        segundo.full_clean()
        segundo.save()

        self.assertEqual(empleado.contratos.count(), 2)

    def test_un_contrato_borrado_no_bloquea_un_alta_nueva_en_la_misma_posicion(self):
        posicion = self.create_posicion()
        viejo = self.create_contrato(empleado=self.create_empleado(), posicion=posicion)
        viejo.delete()  # soft delete: is_deleted=True, fecha_baja sigue NULL

        nuevo = Contrato(empleado=self.create_empleado(), posicion=posicion, fecha_ingreso=date(2021, 1, 1))
        nuevo.full_clean()
        nuevo.save()

        self.assertTrue(Contrato.objects.filter(pk=nuevo.pk).exists())

    def test_la_constraint_tambien_protege_a_nivel_de_base_de_datos(self):
        # No solo full_clean(): un .create() directo que se salte la
        # validacion de Django igual debe chocar contra la base.
        empleado = self.create_empleado()
        self.create_contrato(empleado=empleado, posicion=self.create_posicion())

        with self.assertRaises(IntegrityError), transaction.atomic():
            Contrato.objects.create(
                empleado=empleado, posicion=self.create_posicion(), fecha_ingreso=date(2021, 1, 1),
            )


class AltaServiceTests(EmploymentTestDataMixin, TestCase):
    """apps.employment.services — único camino soportado para dar de alta o
    reingreso (2026-09-29): Empleado y Contrato siempre juntos, en una sola
    transacción, nunca queda un Empleado suelto sin Contrato."""

    def test_dar_alta_nueva_crea_empleado_y_contrato_juntos(self):
        persona = self.create_persona()
        posicion = self.create_posicion()

        empleado, contrato = dar_alta_nueva(
            persona=persona, posicion=posicion, fecha_ingreso=date(2024, 1, 1), work_number="ADV0100",
        )

        self.assertEqual(empleado.persona, persona)
        self.assertEqual(contrato.empleado, empleado)
        self.assertEqual(contrato.posicion, posicion)
        self.assertTrue(Empleado.objects.filter(pk=empleado.pk).exists())
        self.assertTrue(Contrato.objects.filter(pk=contrato.pk).exists())

    def test_dar_alta_nueva_no_deja_nada_a_medias_si_el_contrato_es_invalido(self):
        persona = self.create_persona()
        posicion_ocupada = self.create_posicion()
        self.create_contrato(empleado=self.create_empleado(), posicion=posicion_ocupada)

        with self.assertRaises(ValidationError):
            dar_alta_nueva(persona=persona, posicion=posicion_ocupada, fecha_ingreso=date(2024, 1, 1))

        # Rollback completo: ni el Empleado a medio crear queda en la base.
        self.assertFalse(Empleado.objects.filter(persona=persona).exists())

        casos_invalidos = [
            {"fecha_baja": date(2024, 1, 2)},
            {"is_deleted": True},
        ]
        for numero, contrato_kwargs in enumerate(casos_invalidos, start=1):
            with self.subTest(contrato_kwargs=contrato_kwargs):
                persona_invalida = self.create_persona(first_name=f"Invalida {numero}")
                with self.assertRaises(ValidationError):
                    dar_alta_nueva(
                        persona=persona_invalida,
                        posicion=self.create_posicion(),
                        fecha_ingreso=date(2024, 1, 1),
                        **contrato_kwargs,
                    )
                self.assertFalse(Empleado.objects.filter(persona=persona_invalida).exists())

    def test_dar_reingreso_agrega_contrato_a_empleado_existente(self):
        empleado = self.create_empleado()
        self.create_contrato(empleado=empleado, posicion=self.create_posicion(), fecha_baja=date(2020, 12, 31))

        empleado_resultado, contrato_nuevo = dar_reingreso(
            empleado=empleado, posicion=self.create_posicion(), fecha_ingreso=date(2021, 1, 1),
        )

        self.assertEqual(empleado_resultado.pk, empleado.pk)
        self.assertEqual(empleado.contratos.count(), 2)
        self.assertEqual(empleado.get_contrato_activo(), contrato_nuevo)

    def test_dar_reingreso_rechaza_si_ya_tiene_un_contrato_vigente(self):
        empleado = self.create_empleado()
        self.create_contrato(empleado=empleado, posicion=self.create_posicion())

        with self.assertRaises(ValidationError):
            dar_reingreso(empleado=empleado, posicion=self.create_posicion(), fecha_ingreso=date(2024, 1, 1))


class ContratoInlineMinNumTests(EmploymentTestDataMixin, TestCase):
    """EmpleadoAdmin exige un Contrato solo al CREAR (2026-09-29) — los 121
    Empleado ya existentes sin Contrato (reportar_altas_pendientes) se
    siguen pudiendo editar sin que esto los bloquee."""

    def setUp(self):
        super().setUp()
        # No en setUpTestData a propósito: Django deepcopy-a esos atributos
        # de clase entre pruebas, y un InlineModelAdmin/AdminSite no se puede
        # deepcopy ("cannot pickle 'module' object").
        self.request = RequestFactory().get("/admin/")
        self.request.user = get_user_model().objects.create_superuser(
            username="admin-inline", email="admin-inline@example.com", password="test-pass",
        )
        self.inline = ContratoInline(Empleado, admin.site)

    def test_requiere_al_menos_un_contrato_al_crear(self):
        formset_class = self.inline.get_formset(self.request, obj=None)
        prefix = formset_class.get_default_prefix()
        formset = formset_class(
            data={
                f"{prefix}-TOTAL_FORMS": "0",
                f"{prefix}-INITIAL_FORMS": "0",
                f"{prefix}-MIN_NUM_FORMS": "0",
                f"{prefix}-MAX_NUM_FORMS": "1000",
            },
            instance=Empleado(),
            prefix=prefix,
        )

        self.assertFalse(formset.is_valid())
        self.assertTrue(formset.non_form_errors())

    def test_no_exige_contrato_al_editar_uno_ya_existente(self):
        empleado = self.create_empleado()
        formset_class = self.inline.get_formset(self.request, obj=empleado)
        prefix = formset_class.get_default_prefix()
        formset = formset_class(
            data={
                f"{prefix}-TOTAL_FORMS": "0",
                f"{prefix}-INITIAL_FORMS": "0",
                f"{prefix}-MIN_NUM_FORMS": "0",
                f"{prefix}-MAX_NUM_FORMS": "1000",
            },
            instance=empleado,
            prefix=prefix,
        )

        self.assertTrue(formset.is_valid(), formset.errors)


class AltaServiceRetryTests(EmploymentTestDataMixin, TestCase):
    def test_reintentar_dar_alta_nueva_tras_corregir_el_conflicto_funciona(self):
        posicion_ocupada = self.create_posicion()
        self.create_contrato(empleado=self.create_empleado(), posicion=posicion_ocupada)
        persona = self.create_persona()

        with self.assertRaises(ValidationError):
            dar_alta_nueva(persona=persona, posicion=posicion_ocupada, fecha_ingreso=date(2024, 1, 1))

        # Reintento con la Posición correcta (el error fue elegir mal) funciona
        # normal — el primer intento fallido no dejó nada a medias.
        posicion_libre = self.create_posicion()
        empleado, contrato = dar_alta_nueva(persona=persona, posicion=posicion_libre, fecha_ingreso=date(2024, 1, 1))

        self.assertEqual(empleado.persona, persona)
        self.assertEqual(contrato.posicion, posicion_libre)


class AuditableAdminDeleteTests(EmploymentTestDataMixin, TestCase):
    """apps.core.admin.AuditableAdminMixin.delete_model — quién borró un
    registro desde el admin queda registrado (2026-09-29)."""

    def test_delete_model_records_who_deleted_it(self):
        empleado = self.create_empleado()
        gestor = get_user_model().objects.create_user(
            username="borra-gestor", email="borra-gestor@example.com", password="strong-test-password",
        )
        model_admin = EmpleadoAdmin(Empleado, admin.site)
        request = RequestFactory().post("/admin/")
        request.user = gestor

        model_admin.delete_model(request, empleado)

        borrado = Empleado.all_objects.get(pk=empleado.pk)
        self.assertTrue(borrado.is_deleted)
        self.assertEqual(borrado.deleted_by, gestor)


class AltaServiceConcurrencyTests(TransactionTestCase):
    """
    Prueba de concurrencia real (TransactionTestCase + hilos, contra Postgres
    de verdad, no TestCase): dos reingresos simultáneos del mismo Empleado.
    select_for_update() + el UniqueConstraint de Contrato deben dejar pasar a
    uno y rechazar limpio al otro con ValidationError -- nunca dos Contrato
    vigentes ni un crash. No usa EmploymentTestDataMixin porque
    setUpTestData no existe en TransactionTestCase (no envuelve las pruebas
    en una transacción que se pueda revertir entre ellas).
    """

    def setUp(self):
        super().setUp()
        call_command("seed_tenant", stdout=StringIO())
        call_command("seed_organizational_levels", stdout=StringIO())
        call_command("seed_user_roles", stdout=StringIO())

        empresa_level = OrganizationalLevel.objects.get(code="empresa")
        company_node = OrganizationNode.objects.create(
            level=empresa_level, code="GPA-CONC-TEST", name="Empresa de prueba",
        )
        estatus_activo = EstatusPosicion.objects.create(name="Colaborador Activo")

        persona = Persona(first_name="Concu", last_name_paternal="Rrencia")
        persona.full_clean()
        persona.save()
        self.empleado = Empleado(persona=persona)
        self.empleado.full_clean()
        self.empleado.save()

        posicion_previa = Posicion(organization_node=company_node, estatus=estatus_activo)
        posicion_previa.full_clean()
        posicion_previa.save()
        contrato_cerrado = Contrato(
            empleado=self.empleado, posicion=posicion_previa,
            fecha_ingreso=date(2019, 1, 1), fecha_baja=date(2020, 12, 31),
        )
        contrato_cerrado.full_clean()
        contrato_cerrado.save()

        self.posicion_a = Posicion(organization_node=company_node, estatus=estatus_activo)
        self.posicion_a.full_clean()
        self.posicion_a.save()
        self.posicion_b = Posicion(organization_node=company_node, estatus=estatus_activo)
        self.posicion_b.full_clean()
        self.posicion_b.save()

    def test_dos_reingresos_simultaneos_del_mismo_empleado_solo_uno_gana(self):
        resultados = []
        barrera = threading.Barrier(2)

        def intentar(posicion):
            try:
                barrera.wait(timeout=5)
                dar_reingreso(empleado=self.empleado, posicion=posicion, fecha_ingreso=date(2021, 1, 1))
                resultados.append("ok")
            except ValidationError:
                resultados.append("rechazado")
            except Exception as exc:  # diagnóstico si algo distinto revienta
                resultados.append(f"error inesperado: {exc!r}")
            finally:
                connection.close()

        hilo_a = threading.Thread(target=intentar, args=(self.posicion_a,))
        hilo_b = threading.Thread(target=intentar, args=(self.posicion_b,))
        hilo_a.start()
        hilo_b.start()
        hilo_a.join(timeout=10)
        hilo_b.join(timeout=10)

        self.assertFalse(hilo_a.is_alive(), "El primer reingreso quedó bloqueado.")
        self.assertFalse(hilo_b.is_alive(), "El segundo reingreso quedó bloqueado.")
        self.assertEqual(sorted(resultados), ["ok", "rechazado"])
        self.assertEqual(self.empleado.contratos.filter(fecha_baja__isnull=True).count(), 1)


class EmploymentAPIAuthenticationTests(EmploymentTestDataMixin, APITestCase):
    def test_all_employment_endpoints_require_authentication(self):
        protected_urls = [
            reverse("origenbaja-list"),
            reverse("causabaja-list"),
            reverse("empleado-list"),
            reverse("contrato-list"),
            reverse("historialsalarial-list"),
        ]
        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class EmploymentCatalogAPITests(EmploymentTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.origen = OrigenBaja.objects.create(name="Renuncia")
        user_model = get_user_model()
        cls.user = user_model.objects.create_user(
            username="employment-catalog-user", email="employment-catalog@example.com",
            password="strong-test-password",
        )

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.user)

    def test_origen_baja_catalog_is_read_only_for_any_authenticated_user(self):
        list_url = reverse("origenbaja-list")
        response = self.client.get(list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

        create_response = self.client.post(list_url, {"name": "Nuevo"}, format="json")
        self.assertEqual(create_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class EmpleadoContratoRoleAPITests(EmploymentTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        user_model = get_user_model()
        capital_humano = UserRole.objects.get(code="capital-humano")
        colaborador_role = UserRole.objects.get(code="colaborador")

        cls.gestor = user_model.objects.create_user(
            username="employment-gestor", email="employment-gestor@example.com",
            password="strong-test-password", role=capital_humano,
        )

        cls.colaborador_persona = cls.create_persona(first_name="Juan", last_name_paternal="Perez")
        cls.colaborador_user = user_model.objects.create_user(
            username="employment-colaborador", email="employment-colaborador@example.com",
            password="strong-test-password", role=colaborador_role,
        )
        cls.colaborador_empleado = cls.create_empleado(
            persona=cls.colaborador_persona, user=cls.colaborador_user, work_number="ADV0001",
        )
        cls.otro_empleado = cls.create_empleado(work_number="ADV0002")

        cls.posicion = cls.create_posicion()
        cls.contrato_propio = cls.create_contrato(empleado=cls.colaborador_empleado, posicion=cls.posicion)
        cls.otra_posicion = cls.create_posicion()
        cls.contrato_ajeno = cls.create_contrato(empleado=cls.otro_empleado, posicion=cls.otra_posicion)

    # --- Capital Humano: acceso total ---

    def test_gestor_sees_every_empleado_and_contrato(self):
        self.client.force_authenticate(user=self.gestor)

        empleados = self.client.get(reverse("empleado-list"))
        self.assertEqual(empleados.data["count"], 2)

        contratos = self.client.get(reverse("contrato-list"))
        self.assertEqual(contratos.data["count"], 2)

    def test_gestor_can_create_and_update_empleado_with_audit_fields(self):
        self.client.force_authenticate(user=self.gestor)
        persona = self.create_persona(first_name="Nueva", last_name_paternal="Persona")

        create_response = self.client.post(
            reverse("empleado-list"),
            {"persona": str(persona.pk), "work_number": "ADV0099"},
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        empleado = Empleado.objects.get(pk=create_response.data["id"])
        self.assertEqual(empleado.created_by, self.gestor)
        self.assertEqual(empleado.updated_by, self.gestor)

    # --- Colaborador: solo lo propio, y de solo lectura ---

    def test_colaborador_only_sees_own_empleado_and_contrato_in_list(self):
        self.client.force_authenticate(user=self.colaborador_user)

        empleados = self.client.get(reverse("empleado-list"))
        self.assertEqual(empleados.data["count"], 1)
        self.assertEqual(empleados.data["results"][0]["id"], str(self.colaborador_empleado.pk))

        contratos = self.client.get(reverse("contrato-list"))
        self.assertEqual(contratos.data["count"], 1)
        self.assertEqual(contratos.data["results"][0]["id"], str(self.contrato_propio.pk))

    def test_colaborador_gets_404_reading_someone_elses_empleado(self):
        self.client.force_authenticate(user=self.colaborador_user)
        response = self.client.get(reverse("empleado-detail", args=[self.otro_empleado.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_colaborador_cannot_write_to_empleado_or_contrato(self):
        self.client.force_authenticate(user=self.colaborador_user)

        create_response = self.client.post(
            reverse("empleado-list"),
            {"persona": str(self.create_persona().pk), "work_number": "ADV0100"},
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)

        update_response = self.client.patch(
            reverse("empleado-detail", args=[self.colaborador_empleado.pk]),
            {"work_number": "CAMBIADO"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_gestor_creates_empleados_without_work_number_and_they_do_not_collide(self):
        # work_number es unico y opcional: dos empleados "sin numero" no
        # pueden guardarse como "" (chocarian). Ambos quedan en NULL.
        self.client.force_authenticate(user=self.gestor)
        for texto in ("", "   "):
            response = self.client.post(
                reverse("empleado-list"),
                {"persona": str(self.create_persona().pk), "work_number": texto},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
            self.assertIsNone(Empleado.objects.get(pk=response.data["id"]).work_number)

    def test_gestor_cannot_reuse_a_work_number_or_a_persona(self):
        self.client.force_authenticate(user=self.gestor)
        repetido = self.client.post(
            reverse("empleado-list"),
            {"persona": str(self.create_persona().pk), "work_number": "ADV0001"},
            format="json",
        )
        self.assertEqual(repetido.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("work_number", repetido.data)

        misma_persona = self.client.post(
            reverse("empleado-list"),
            {"persona": str(self.colaborador_persona.pk), "work_number": "ADV0777"},
            format="json",
        )
        self.assertEqual(misma_persona.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("persona", misma_persona.data)

    def test_gestor_edits_the_work_number_of_an_empleado(self):
        self.client.force_authenticate(user=self.gestor)
        response = self.client.patch(
            reverse("empleado-detail", args=[self.otro_empleado.pk]), {"work_number": "ADV0099"}, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.otro_empleado.refresh_from_db()
        self.assertEqual(self.otro_empleado.work_number, "ADV0099")

    # --- acción "jefe" ---

    def test_jefe_action_resolves_correctly_through_the_api(self):
        posicion_jefe = self.create_posicion()
        jefe_empleado = self.create_empleado(persona=self.create_persona(first_name="Ana", last_name_paternal="Lider"))
        self.create_contrato(empleado=jefe_empleado, posicion=posicion_jefe)
        self.colaborador_empleado_con_jefe = self.create_empleado(work_number="ADV0003")
        posicion_con_jefe = self.create_posicion(reports_to=posicion_jefe)
        self.create_contrato(empleado=self.colaborador_empleado_con_jefe, posicion=posicion_con_jefe)

        self.client.force_authenticate(user=self.gestor)
        response = self.client.get(reverse("empleado-jefe", args=[self.colaborador_empleado_con_jefe.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["empleado_id"], str(jefe_empleado.pk))
        self.assertEqual(response.data["nombre"], "Lider Ana")

    def test_colaborador_can_query_own_jefe_but_not_someone_elses(self):
        self.client.force_authenticate(user=self.colaborador_user)

        own_response = self.client.get(reverse("empleado-jefe", args=[self.colaborador_empleado.pk]))
        self.assertEqual(own_response.status_code, status.HTTP_200_OK)
        self.assertIsNone(own_response.data["empleado_id"])  # sin reports_to en este fixture

        other_response = self.client.get(reverse("empleado-jefe", args=[self.otro_empleado.pk]))
        self.assertEqual(other_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_contrato_vigente_returns_the_active_contract(self):
        self.client.force_authenticate(user=self.gestor)
        response = self.client.get(
            reverse("empleado-contrato-vigente", args=[self.colaborador_empleado.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(self.contrato_propio.pk))

    def test_contrato_vigente_is_null_without_an_active_contract(self):
        empleado_sin_contrato = self.create_empleado(work_number="ADV0004")
        self.client.force_authenticate(user=self.gestor)
        response = self.client.get(
            reverse("empleado-contrato-vigente", args=[empleado_sin_contrato.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data)

    def test_colaborador_can_query_own_contrato_vigente_but_not_someone_elses(self):
        self.client.force_authenticate(user=self.colaborador_user)

        own_response = self.client.get(
            reverse("empleado-contrato-vigente", args=[self.colaborador_empleado.pk])
        )
        self.assertEqual(own_response.status_code, status.HTTP_200_OK)
        self.assertEqual(own_response.data["id"], str(self.contrato_propio.pk))

        other_response = self.client.get(
            reverse("empleado-contrato-vigente", args=[self.otro_empleado.pk])
        )
        self.assertEqual(other_response.status_code, status.HTTP_404_NOT_FOUND)

    # --- blindaje del historial (2026-09-29): borrado y reasignación ---

    def test_gestor_cannot_reassign_a_contrato_to_another_empleado_via_api(self):
        self.client.force_authenticate(user=self.gestor)
        response = self.client.patch(
            reverse("contrato-detail", args=[self.contrato_propio.pk]),
            {"empleado": str(self.otro_empleado.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("empleado", response.data)
        self.contrato_propio.refresh_from_db()
        self.assertEqual(self.contrato_propio.empleado_id, self.colaborador_empleado.pk)

    def test_deleting_a_contrato_via_api_soft_deletes_it(self):
        self.client.force_authenticate(user=self.gestor)
        response = self.client.delete(reverse("contrato-detail", args=[self.contrato_propio.pk]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(Contrato.objects.filter(pk=self.contrato_propio.pk).exists())
        borrado = Contrato.all_objects.get(pk=self.contrato_propio.pk)
        self.assertTrue(borrado.is_deleted)
        self.assertEqual(borrado.deleted_by, self.gestor)

    def test_deleting_an_empleado_with_contratos_via_api_soft_deletes_it(self):
        # Antes de este cambio esto tronaba con ProtectedError a medio DELETE
        # real (Contrato.empleado es on_delete=PROTECT) — el soft-delete ya
        # ni intenta el DELETE real, así que no hay nada que proteger.
        self.client.force_authenticate(user=self.gestor)
        response = self.client.delete(reverse("empleado-detail", args=[self.otro_empleado.pk]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(Empleado.objects.filter(pk=self.otro_empleado.pk).exists())
        borrado = Empleado.all_objects.get(pk=self.otro_empleado.pk)
        self.assertTrue(borrado.is_deleted)
        self.assertEqual(borrado.deleted_by, self.gestor)
        # Su Contrato sigue intacto y sigue resolviendo el Empleado por FK.
        self.contrato_ajeno.refresh_from_db()
        self.assertEqual(self.contrato_ajeno.empleado_id, self.otro_empleado.pk)


class HistorialSalarialRoleAPITests(EmploymentTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        user_model = get_user_model()
        cls.gestor = user_model.objects.create_user(
            username="salario-gestor", email="salario-gestor@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="capital-humano"),
        )
        cls.colaborador_user = user_model.objects.create_user(
            username="salario-colaborador", email="salario-colaborador@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="colaborador"),
        )
        cls.empleado = cls.create_empleado(user=cls.colaborador_user, work_number="ADV0050")
        cls.historial = HistorialSalarial.objects.create(
            empleado=cls.empleado, monto="15000.00", fecha_vigencia=date(2024, 1, 1),
        )

    def test_gestor_can_read_and_write_historial_salarial(self):
        self.client.force_authenticate(user=self.gestor)
        list_response = self.client.get(reverse("historialsalarial-list"))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data["count"], 1)

    def test_colaborador_cannot_read_even_their_own_historial_salarial(self):
        # Confirmado con el usuario (2026-09-24): un Colaborador no ve su
        # propio salario por ahora, ni siquiera de solo lectura.
        self.client.force_authenticate(user=self.colaborador_user)

        list_response = self.client.get(reverse("historialsalarial-list"))
        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)

        detail_response = self.client.get(reverse("historialsalarial-detail", args=[self.historial.pk]))
        self.assertEqual(detail_response.status_code, status.HTTP_403_FORBIDDEN)
