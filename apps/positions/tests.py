from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.locations.models import Area, Nave, Ubicacion
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


class BackfillReportsToPorUnidadTests(PositionsTestDataMixin, TestCase):
    """
    apps.positions.management.commands.backfill_reports_to_por_unidad —
    confirmado con el usuario 2026-09-29: la Posición cuyo Puesto tiene
    es_gerencia_de_unidad=True es jefe de las demás Posiciones de su misma
    Unidad de Negocio + Ubicación física.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.otra_unidad = OrganizationNode.objects.create(
            level=cls.company_node.level, code="GPA-POS-TEST-2", name="Otra unidad de prueba",
        )
        cls.gerencia_puesto = Puesto.objects.create(
            name="Gerente de Unidad de Prueba", es_gerencia_de_unidad=True,
        )
        cls.puesto_normal = Puesto.objects.create(name="Auxiliar de prueba")

    @staticmethod
    def _area_en(nombre_ubicacion, con_nave=True):
        ubicacion = Ubicacion.objects.create(code=nombre_ubicacion[:10].upper(), name=nombre_ubicacion)
        if not con_nave:
            return Area.objects.create(code="A1", name="Área sin nave")
        nave = Nave.objects.create(ubicacion=ubicacion, code="N1")
        return Area.objects.create(nave=nave, code="A1", name="Área 1")

    def test_sin_ningun_puesto_marcado_no_hace_nada(self):
        Puesto.objects.filter(pk=self.gerencia_puesto.pk).update(es_gerencia_de_unidad=False)
        area = self._area_en("Planta Uno")
        self.create_posicion(area=area, puesto=self.puesto_normal)

        call_command("backfill_reports_to_por_unidad", stdout=StringIO())

        self.assertEqual(Posicion.objects.filter(reports_to__isnull=False).count(), 0)

    def test_asigna_jefe_solo_a_la_misma_unidad_y_ubicacion(self):
        area_planta_1 = self._area_en("Planta Uno")
        area_planta_2 = self._area_en("Planta Dos")

        jefe = self.create_posicion(area=area_planta_1, puesto=self.gerencia_puesto)
        mismo_alcance = self.create_posicion(area=area_planta_1, puesto=self.puesto_normal)
        otra_ubicacion = self.create_posicion(area=area_planta_2, puesto=self.puesto_normal)
        otra_unidad_misma_ubicacion = self.create_posicion(
            area=area_planta_1, puesto=self.puesto_normal, organization_node=self.otra_unidad,
        )

        call_command("backfill_reports_to_por_unidad", stdout=StringIO())

        mismo_alcance.refresh_from_db()
        otra_ubicacion.refresh_from_db()
        otra_unidad_misma_ubicacion.refresh_from_db()
        self.assertEqual(mismo_alcance.reports_to_id, jefe.pk)
        self.assertIsNone(otra_ubicacion.reports_to_id)
        self.assertIsNone(otra_unidad_misma_ubicacion.reports_to_id)

    def test_el_jefe_puede_ver_a_sus_subordinados_por_la_relacion_inversa(self):
        area = self._area_en("Planta Uno")
        jefe = self.create_posicion(area=area, puesto=self.gerencia_puesto)
        subordinado_1 = self.create_posicion(area=area, puesto=self.puesto_normal)
        subordinado_2 = self.create_posicion(area=area, puesto=self.puesto_normal)

        call_command("backfill_reports_to_por_unidad", stdout=StringIO())

        self.assertCountEqual(jefe.reportes.all(), [subordinado_1, subordinado_2])

    def test_no_sobrescribe_un_reports_to_que_ya_existia(self):
        area = self._area_en("Planta Uno")
        jefe_de_unidad = self.create_posicion(area=area, puesto=self.gerencia_puesto)
        jefe_manual = self.create_posicion(area=area, puesto=self.puesto_normal)
        posicion = self.create_posicion(area=area, puesto=self.puesto_normal, reports_to=jefe_manual)

        call_command("backfill_reports_to_por_unidad", stdout=StringIO())

        posicion.refresh_from_db()
        self.assertEqual(posicion.reports_to_id, jefe_manual.pk)
        self.assertNotEqual(posicion.reports_to_id, jefe_de_unidad.pk)

    def test_dos_candidatos_en_el_mismo_alcance_es_ambiguo_y_no_asigna_nada(self):
        area = self._area_en("Planta Uno")
        self.create_posicion(area=area, puesto=self.gerencia_puesto)
        self.create_posicion(area=area, puesto=self.gerencia_puesto)
        posicion = self.create_posicion(area=area, puesto=self.puesto_normal)

        call_command("backfill_reports_to_por_unidad", stdout=StringIO())

        posicion.refresh_from_db()
        self.assertIsNone(posicion.reports_to_id)

    def test_candidato_sin_nave_no_se_puede_usar_como_jefe(self):
        area_sin_nave = self._area_en("Planta Uno", con_nave=False)
        self.create_posicion(area=area_sin_nave, puesto=self.gerencia_puesto)
        posicion = self.create_posicion(area=area_sin_nave, puesto=self.puesto_normal)

        call_command("backfill_reports_to_por_unidad", stdout=StringIO())

        posicion.refresh_from_db()
        self.assertIsNone(posicion.reports_to_id)

    def test_posicion_sin_area_no_recibe_jefe(self):
        area = self._area_en("Planta Uno")
        self.create_posicion(area=area, puesto=self.gerencia_puesto)
        sin_area = self.create_posicion(puesto=self.puesto_normal)

        call_command("backfill_reports_to_por_unidad", stdout=StringIO())

        sin_area.refresh_from_db()
        self.assertIsNone(sin_area.reports_to_id)

    def test_posicion_sin_puesto_capturado_igual_puede_recibir_jefe(self):
        # Regresión: un filter(puesto__es_gerencia_de_unidad=False) excluiría
        # estas filas solo por el INNER JOIN implícito de Django sobre una FK
        # nula — el comando usa .exclude(...=True) a propósito para que sí
        # se consideren.
        area = self._area_en("Planta Uno")
        jefe = self.create_posicion(area=area, puesto=self.gerencia_puesto)
        sin_puesto = self.create_posicion(area=area, puesto=None)

        call_command("backfill_reports_to_por_unidad", stdout=StringIO())

        sin_puesto.refresh_from_db()
        self.assertEqual(sin_puesto.reports_to_id, jefe.pk)

    def test_la_cabeza_de_unidad_nunca_recibe_jefe_por_esta_regla(self):
        area = self._area_en("Planta Uno")
        jefe = self.create_posicion(area=area, puesto=self.gerencia_puesto)

        call_command("backfill_reports_to_por_unidad", stdout=StringIO())

        jefe.refresh_from_db()
        self.assertIsNone(jefe.reports_to_id)
