from datetime import datetime, timezone as datetime_timezone
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.locations.models import Area, Nave, Ubicacion
from apps.organizations.models import OrganizationalLevel, OrganizationNode
from apps.positions.models import (
    AlcanceDePosicion,
    EstatusPosicion,
    HistorialPuesto,
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


class HistorialPuestoTests(PositionsTestDataMixin, TestCase):
    def test_creating_a_posicion_opens_a_vigente_row_even_without_puesto(self):
        posicion = self.create_posicion()
        historial = HistorialPuesto.objects.get(posicion=posicion)
        self.assertIsNone(historial.puesto)
        self.assertIsNone(historial.fecha_fin)

    def test_changing_puesto_closes_the_previous_row_and_opens_a_new_one(self):
        puesto_uno = Puesto.objects.create(name="Puesto uno")
        puesto_dos = Puesto.objects.create(name="Puesto dos")
        posicion = self.create_posicion(puesto=puesto_uno)

        posicion.puesto = puesto_dos
        posicion.save()

        self.assertEqual(HistorialPuesto.objects.filter(posicion=posicion).count(), 2)
        cerrado = HistorialPuesto.objects.get(posicion=posicion, fecha_fin__isnull=False)
        vigente = HistorialPuesto.objects.get(posicion=posicion, fecha_fin__isnull=True)
        self.assertEqual(cerrado.puesto_id, puesto_uno.pk)
        self.assertEqual(vigente.puesto_id, puesto_dos.pk)

        # Si crear el historial nuevo falla, tampoco debe persistir el
        # cambio del campo vigente ni cerrarse la fila anterior.
        posicion_rollback = self.create_posicion(puesto=puesto_uno)
        posicion_rollback.puesto = puesto_dos
        with patch(
            "apps.positions.models.HistorialPuesto.objects.create",
            side_effect=RuntimeError("fallo simulado del historial"),
        ):
            with self.assertRaises(RuntimeError):
                posicion_rollback.save()
        posicion_rollback.refresh_from_db()
        vigente_rollback = HistorialPuesto.objects.get(
            posicion=posicion_rollback, fecha_fin__isnull=True,
        )
        self.assertEqual(posicion_rollback.puesto_id, puesto_uno.pk)
        self.assertEqual(vigente_rollback.puesto_id, puesto_uno.pk)

    def test_saving_without_changing_puesto_does_not_create_a_new_row(self):
        puesto = Puesto.objects.create(name="Puesto fijo")
        puesto_no_persistido = Puesto.objects.create(name="Puesto solo en memoria")
        posicion = self.create_posicion(puesto=puesto)
        self.assertEqual(HistorialPuesto.objects.filter(posicion=posicion).count(), 1)

        posicion.puesto = puesto_no_persistido
        posicion.supervision_texto = "ALAN ARTEAGA"
        posicion.save(update_fields=["supervision_texto"])

        posicion.refresh_from_db()
        self.assertEqual(posicion.puesto_id, puesto.pk)
        self.assertEqual(HistorialPuesto.objects.filter(posicion=posicion).count(), 1)
        self.assertEqual(HistorialPuesto.objects.get(posicion=posicion).puesto_id, puesto.pk)

    def test_only_one_vigente_row_is_allowed_per_posicion(self):
        posicion = self.create_posicion()
        with self.assertRaises(IntegrityError), transaction.atomic():
            HistorialPuesto.objects.create(posicion=posicion, puesto=None, fecha_inicio="2020-01-01")


class BackfillHistorialPuestoTests(PositionsTestDataMixin, TestCase):
    """apps.positions.management.commands.backfill_historial_puesto — abre
    la fila vigente para Posiciones que ya existían antes de HistorialPuesto."""

    def test_opens_a_vigente_row_for_posiciones_without_any_historial(self):
        puesto = Puesto.objects.create(name="Puesto real")
        posicion = self.create_posicion(puesto=puesto)
        # Simula una Posición creada ANTES de que existiera HistorialPuesto.
        HistorialPuesto.objects.filter(posicion=posicion).delete()

        call_command("backfill_historial_puesto", stdout=StringIO())

        historial = HistorialPuesto.objects.get(posicion=posicion)
        self.assertEqual(historial.puesto_id, puesto.pk)
        self.assertIsNone(historial.fecha_fin)
        self.assertEqual(historial.fecha_inicio, timezone.localdate(posicion.created_at))

    def test_does_not_duplicate_an_existing_historial_row(self):
        posicion = self.create_posicion()  # ya trae su HistorialPuesto por Posicion.save()
        instante_utc = datetime(2026, 9, 24, 4, 30, tzinfo=datetime_timezone.utc)
        Posicion.objects.filter(pk=posicion.pk).update(created_at=instante_utc)
        posicion.refresh_from_db()
        historial = HistorialPuesto.objects.get(posicion=posicion)
        historial.fecha_inicio = instante_utc.date()  # comportamiento UTC anterior
        historial.save(update_fields=["fecha_inicio"])

        call_command("backfill_historial_puesto", stdout=StringIO())

        self.assertEqual(HistorialPuesto.objects.filter(posicion=posicion).count(), 1)
        historial.refresh_from_db()
        self.assertEqual(historial.fecha_inicio, timezone.localdate(instante_utc))


class PositionsAdminConfigurationTests(TestCase):
    def test_historial_reporta_a_cannot_be_added_manually(self):
        from django.contrib import admin
        model_admin = admin.site._registry[HistorialReportaA]
        self.assertFalse(model_admin.has_add_permission(request=None))

    def test_historial_puesto_cannot_be_added_manually(self):
        from django.contrib import admin
        model_admin = admin.site._registry[HistorialPuesto]
        self.assertFalse(model_admin.has_add_permission(request=None))
        self.assertFalse(model_admin.has_delete_permission(request=None))


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

    def test_colaborador_reads_the_puesto_catalog_but_cannot_write_it(self):
        self.client.force_authenticate(user=self.colaborador)
        response = self.client.get(reverse("puesto-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

        create_response = self.client.post(reverse("puesto-list"), {"name": "Nuevo"}, format="json")
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        update_response = self.client.patch(
            reverse("puesto-detail", args=[self.puesto.pk]), {"name": "Cambiado"}, format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)
        self.puesto.refresh_from_db()
        self.assertEqual(self.puesto.name, "Auxiliar de Producción")

    def test_gestor_creates_a_puesto_with_a_generated_code_and_edits_it_keeping_the_code(self):
        self.client.force_authenticate(user=self.gestor)
        create_response = self.client.post(
            reverse("puesto-list"), {"name": "Jefe de Almacén", "es_gerencia_de_unidad": False}, format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data["code"], "jefe-de-almacen")
        self.assertTrue(create_response.data["is_active"])
        self.assertFalse(create_response.data["es_gerencia_de_unidad"])

        url = reverse("puesto-detail", args=[create_response.data["id"]])
        # `code` es de solo lectura: mandarlo no lo cambia, y renombrar tampoco.
        update_response = self.client.patch(
            url, {"name": "Jefe de Almacén General", "code": "otro-codigo", "is_active": False}, format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data["code"], "jefe-de-almacen")
        self.assertEqual(update_response.data["name"], "Jefe de Almacén General")
        self.assertFalse(update_response.data["is_active"])

    def test_gestor_can_mark_a_puesto_as_gerencia_de_unidad(self):
        self.client.force_authenticate(user=self.gestor)
        response = self.client.patch(
            reverse("puesto-detail", args=[self.puesto.pk]), {"es_gerencia_de_unidad": True}, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.puesto.refresh_from_db()
        self.assertTrue(self.puesto.es_gerencia_de_unidad)

    def test_puesto_name_cannot_repeat_ignoring_case_on_create_or_rename(self):
        self.client.force_authenticate(user=self.gestor)
        create_response = self.client.post(
            reverse("puesto-list"), {"name": "  auxiliar de producción  "}, format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", create_response.data)

        otro = Puesto.objects.create(name="Operador")
        rename_response = self.client.patch(
            reverse("puesto-detail", args=[otro.pk]), {"name": "AUXILIAR DE PRODUCCIÓN"}, format="json",
        )
        self.assertEqual(rename_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(Puesto.objects.count(), 2)

    def test_editing_another_field_of_an_already_repeated_puesto_is_not_blocked(self):
        # Los datos reales traen variantes repetidas: solo se revisa el
        # nombre cuando alguien lo cambia, no al desactivar el puesto.
        repetido = Puesto.objects.create(name="auxiliar de producción")
        self.client.force_authenticate(user=self.gestor)
        response = self.client.patch(
            reverse("puesto-detail", args=[repetido.pk]), {"is_active": False}, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_puesto_cannot_be_deleted_through_the_api(self):
        self.client.force_authenticate(user=self.gestor)
        response = self.client.delete(reverse("puesto-detail", args=[self.puesto.pk]))
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(Puesto.objects.filter(pk=self.puesto.pk).exists())

    def test_posicion_etiqueta_nombra_puesto_unidad_y_area(self):
        self.client.force_authenticate(user=self.colaborador)
        datos = self.client.get(reverse("posicion-detail", args=[self.posicion.pk])).data
        self.assertEqual(datos["etiqueta"], "Auxiliar de Producción — Empresa de prueba")

        sin_puesto = self.create_posicion()
        datos = self.client.get(reverse("posicion-detail", args=[sin_puesto.pk])).data
        self.assertEqual(datos["etiqueta"], "Sin puesto — Empresa de prueba")

    def test_la_etiqueta_no_se_puede_escribir_y_la_lista_no_hace_una_consulta_por_fila(self):
        self.client.force_authenticate(user=self.gestor)
        self.client.patch(reverse("posicion-detail", args=[self.posicion.pk]), {"etiqueta": "x"}, format="json")
        self.posicion.refresh_from_db()
        self.assertEqual(self.posicion.etiqueta, "Auxiliar de Producción — Empresa de prueba")

        for _ in range(5):
            self.create_posicion(puesto=self.puesto)
        with CaptureQueriesContext(connection) as consultas:
            self.client.get(reverse("posicion-list"))
        # Con select_related, 6 filas no cuestan más consultas que 1.
        self.assertLess(len(consultas), 12)

    def test_tipos_de_requisicion_dicen_cual_exige_justificacion(self):
        from apps.positions.models import TipoRequisicion
        TipoRequisicion.objects.create(name="Reemplazo")
        TipoRequisicion.objects.create(name="Nueva Posición", requiere_justificacion=True)
        self.client.force_authenticate(user=self.colaborador)
        filas = {r["name"]: r["requiere_justificacion"] for r in self.client.get(reverse("tiporequisicion-list")).data["results"]}
        self.assertEqual(filas, {"Reemplazo": False, "Nueva Posición": True})

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
