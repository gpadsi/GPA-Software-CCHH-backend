from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.organizations.models import OrganizationalLevel, OrganizationNode
from apps.positions.models import (
    AlcanceDePosicion,
    EstatusPosicion,
    HistorialReportaA,
    Posicion,
    Puesto,
)
from apps.users.models import UserRole


class PositionsTestDataMixin:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("seed_tenant", stdout=StringIO())
        call_command("seed_organizational_levels", stdout=StringIO())
        call_command("seed_user_roles", stdout=StringIO())

        empresa_level = OrganizationalLevel.objects.get(code="empresa")
        cls.company_node = OrganizationNode.objects.create(
            level=empresa_level, code="GPA-POS-TEST", name="Empresa de prueba",
        )
        cls.estatus_activo = EstatusPosicion.objects.create(name="Colaborador Activo")

    @classmethod
    def create_posicion(cls, *, reports_to=None, **kwargs):
        posicion = Posicion(
            organization_node=kwargs.pop("organization_node", cls.company_node),
            estatus=kwargs.pop("estatus", cls.estatus_activo),
            reports_to=reports_to,
            **kwargs,
        )
        posicion.full_clean()
        posicion.save()
        return posicion


class PosicionValidationTests(PositionsTestDataMixin, TestCase):
    def test_a_posicion_cannot_report_to_itself(self):
        posicion = self.create_posicion()
        posicion.reports_to = posicion

        with self.assertRaises(ValidationError) as context:
            posicion.full_clean()
        self.assertIn("reports_to", context.exception.message_dict)
        self.assertIn("no puede reportar a sí misma", context.exception.message_dict["reports_to"][0])

    def test_a_posicion_cannot_appear_in_its_own_reporting_chain(self):
        top = self.create_posicion()
        middle = self.create_posicion(reports_to=top)
        # Cierra el ciclo saltándose full_clean() a propósito, igual que el
        # equivalente en organizations — así se prueba específicamente la
        # protección contra ciclos, no la validación de un solo paso.
        Posicion.objects.filter(pk=top.pk).update(reports_to=middle)
        top.reports_to = Posicion.objects.get(pk=middle.pk)

        with self.assertRaises(ValidationError) as context:
            top.full_clean()
        self.assertIn("reports_to", context.exception.message_dict)
        self.assertIn("propia cadena de reporte", context.exception.message_dict["reports_to"][0])

    def test_a_valid_reporting_chain_passes(self):
        top = self.create_posicion()
        middle = self.create_posicion(reports_to=top)
        bottom = self.create_posicion(reports_to=middle)
        self.assertEqual(bottom.reports_to_id, middle.pk)
        self.assertEqual(middle.reports_to_id, top.pk)


class HistorialReportaATests(PositionsTestDataMixin, TestCase):
    def test_creating_a_posicion_opens_a_vigente_row_even_without_reports_to(self):
        posicion = self.create_posicion()
        historial = HistorialReportaA.objects.get(posicion=posicion)
        self.assertIsNone(historial.reports_to)
        self.assertIsNone(historial.fecha_fin)

    def test_changing_reports_to_closes_the_previous_row_and_opens_a_new_one(self):
        jefe_uno = self.create_posicion()
        jefe_dos = self.create_posicion()
        posicion = self.create_posicion(reports_to=jefe_uno)

        posicion.reports_to = jefe_dos
        posicion.save()

        self.assertEqual(HistorialReportaA.objects.filter(posicion=posicion).count(), 2)
        cerrado = HistorialReportaA.objects.get(posicion=posicion, fecha_fin__isnull=False)
        vigente = HistorialReportaA.objects.get(posicion=posicion, fecha_fin__isnull=True)
        self.assertEqual(cerrado.reports_to_id, jefe_uno.pk)
        self.assertEqual(vigente.reports_to_id, jefe_dos.pk)

    def test_saving_without_changing_reports_to_does_not_create_a_new_row(self):
        jefe = self.create_posicion()
        posicion = self.create_posicion(reports_to=jefe)
        self.assertEqual(HistorialReportaA.objects.filter(posicion=posicion).count(), 1)

        posicion.supervision_texto = "ALAN ARTEAGA"
        posicion.save()

        self.assertEqual(HistorialReportaA.objects.filter(posicion=posicion).count(), 1)

    def test_only_one_vigente_row_is_allowed_per_posicion(self):
        posicion = self.create_posicion()
        # Ya existe una fila vigente creada por Posicion.save(); forzar una
        # segunda a mano debe chocar contra la restricción de unicidad.
        with self.assertRaises(IntegrityError), transaction.atomic():
            HistorialReportaA.objects.create(posicion=posicion, reports_to=None, fecha_inicio="2020-01-01")


class PositionsAdminConfigurationTests(TestCase):
    def test_historial_reporta_a_cannot_be_added_manually(self):
        from django.contrib import admin
        model_admin = admin.site._registry[HistorialReportaA]
        self.assertFalse(model_admin.has_add_permission(request=None))


class PositionsAPIAuthenticationTests(PositionsTestDataMixin, APITestCase):
    def test_all_positions_endpoints_require_authentication(self):
        protected_urls = [
            reverse("alcancedeposicion-list"),
            reverse("tipoposicion-list"),
            reverse("tiporequisicion-list"),
            reverse("estatusposicion-list"),
            reverse("puesto-list"),
            reverse("posicion-list"),
        ]
        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PosicionRoleAPITests(PositionsTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        user_model = get_user_model()
        cls.gestor = user_model.objects.create_user(
            username="posicion-gestor", email="posicion-gestor@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="capital-humano"),
        )
        cls.colaborador = user_model.objects.create_user(
            username="posicion-colaborador", email="posicion-colaborador@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="colaborador"),
        )
        cls.puesto = Puesto.objects.create(name="Auxiliar de Producción")
        cls.posicion = cls.create_posicion(puesto=cls.puesto)

    def test_puesto_catalog_is_read_only_for_any_authenticated_user(self):
        self.client.force_authenticate(user=self.colaborador)
        response = self.client.get(reverse("puesto-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

        create_response = self.client.post(reverse("puesto-list"), {"name": "Nuevo"}, format="json")
        self.assertEqual(create_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_colaborador_can_read_every_posicion(self):
        # Posicion es estructural (no expone quién la ocupa) — cualquier
        # autenticado la lee completa, aunque solo Capital Humano/Admin
        # pueda escribirla.
        self.client.force_authenticate(user=self.colaborador)
        response = self.client.get(reverse("posicion-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_colaborador_cannot_write_to_posicion(self):
        self.client.force_authenticate(user=self.colaborador)

        create_response = self.client.post(
            reverse("posicion-list"),
            {
                "organization_node": str(self.company_node.pk),
                "estatus": str(self.estatus_activo.pk),
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)

        update_response = self.client.patch(
            reverse("posicion-detail", args=[self.posicion.pk]),
            {"supervision_texto": "Intento de Colaborador"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_gestor_can_create_posicion_with_audit_fields(self):
        self.client.force_authenticate(user=self.gestor)
        response = self.client.post(
            reverse("posicion-list"),
            {
                "organization_node": str(self.company_node.pk),
                "estatus": str(self.estatus_activo.pk),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        posicion = Posicion.objects.get(pk=response.data["id"])
        self.assertEqual(posicion.created_by, self.gestor)
        self.assertEqual(posicion.updated_by, self.gestor)

    def test_gestor_gets_400_when_reports_to_would_create_a_cycle(self):
        self.client.force_authenticate(user=self.gestor)
        response = self.client.patch(
            reverse("posicion-detail", args=[self.posicion.pk]),
            {"reports_to": str(self.posicion.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("reports_to", response.data)
