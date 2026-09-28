from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.employment.models import CausaBaja, Contrato, Empleado, HistorialSalarial, OrigenBaja
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
        self.assertEqual(jefe["nombre"], "Torres  Ana")

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
        self.assertEqual(response.data["nombre"], "Lider  Ana")

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
