from datetime import date
from io import StringIO
from zipfile import ZipFile

import openpyxl
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.employment.models import Contrato, Empleado
from apps.organizations.models import OrganizationalLevel, OrganizationNode
from apps.persons.models import Persona
from apps.positions.models import EstatusPosicion, Posicion, Puesto, TipoRequisicion
from apps.recruitment.exports import PLANTILLAS_DIR, generar_excel
from apps.recruitment.models import (
    AprobacionRequisicion,
    EstadoRequisicion,
    EtapaAprobacion,
    HorarioACubrir,
    Requisicion,
    TipoContratoOfrecido,
)
from apps.users.models import UserRole


class RecruitmentTestDataMixin:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("seed_tenant", stdout=StringIO())
        call_command("seed_organizational_levels", stdout=StringIO())
        call_command("seed_user_roles", stdout=StringIO())
        # TipoRequisicion no tiene seed propio (en producción lo llena el
        # import de la sábana) -- se crea a mano, igual que EstatusPosicion
        # abajo, antes de que seed_recruitment_catalogs marque cuál lo
        # requiere.
        cls.tipo_nueva = TipoRequisicion.objects.create(name="Nueva Posición")
        cls.tipo_reemplazo = TipoRequisicion.objects.create(name="Reemplazo")
        call_command("seed_recruitment_catalogs", stdout=StringIO())

        empresa_level = OrganizationalLevel.objects.get(code="empresa")
        cls.company_node = OrganizationNode.objects.create(
            level=empresa_level, code="GPA-REC-TEST", name="Empresa de prueba",
        )
        cls.estatus_vacante = EstatusPosicion.objects.create(name="Vacante Activa")
        cls.tipo_nueva.refresh_from_db()
        cls.tipo_reemplazo.refresh_from_db()
        cls.estado_borrador = EstadoRequisicion.objects.get(name="Borrador")
        cls.estado_cubierta = EstadoRequisicion.objects.get(name="Cubierta")

    @classmethod
    def create_posicion(cls, **kwargs):
        posicion = Posicion(
            organization_node=kwargs.pop("organization_node", cls.company_node),
            estatus=kwargs.pop("estatus", cls.estatus_vacante),
            **kwargs,
        )
        posicion.full_clean()
        posicion.save()
        return posicion

    @classmethod
    def create_requisicion(cls, *, posicion=None, tipo=None, estado=None, fecha_solicitud=date(2026, 1, 1), **kwargs):
        requisicion = Requisicion(
            posicion=posicion or cls.create_posicion(),
            tipo=tipo or cls.tipo_reemplazo,
            estado=estado or cls.estado_borrador,
            fecha_solicitud=fecha_solicitud,
            **kwargs,
        )
        requisicion.full_clean()
        requisicion.save()
        return requisicion


class SeedRecruitmentCatalogsTests(TestCase):
    def test_seeds_everything_confirmado_and_is_idempotent(self):
        call_command("seed_tenant", stdout=StringIO())
        call_command("seed_organizational_levels", stdout=StringIO())

        out = StringIO()
        call_command("seed_recruitment_catalogs", stdout=out)
        self.assertEqual(EstadoRequisicion.objects.count(), 8)
        self.assertEqual(EtapaAprobacion.objects.count(), 4)
        self.assertEqual(TipoContratoOfrecido.objects.count(), 2)
        self.assertEqual(HorarioACubrir.objects.count(), 5)

        out2 = StringIO()
        call_command("seed_recruitment_catalogs", stdout=out2)
        self.assertIn("0 valores nuevos", out2.getvalue())

    def test_marks_nueva_posicion_as_requiring_justificacion(self):
        call_command("seed_tenant", stdout=StringIO())
        call_command("seed_organizational_levels", stdout=StringIO())
        TipoRequisicion.objects.create(name="Nueva Posición")
        TipoRequisicion.objects.create(name="Reemplazo")

        call_command("seed_recruitment_catalogs", stdout=StringIO())

        self.assertTrue(TipoRequisicion.objects.get(name="Nueva Posición").requiere_justificacion)
        self.assertFalse(TipoRequisicion.objects.get(name="Reemplazo").requiere_justificacion)


class RequisicionJustificacionTests(RecruitmentTestDataMixin, TestCase):
    def test_nueva_posicion_requires_justificacion(self):
        requisicion = Requisicion(
            posicion=self.create_posicion(), tipo=self.tipo_nueva, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 1, 1),
        )
        with self.assertRaises(ValidationError) as context:
            requisicion.full_clean()
        self.assertIn("justificacion", context.exception.message_dict)

    def test_reemplazo_does_not_require_justificacion(self):
        requisicion = Requisicion(
            posicion=self.create_posicion(), tipo=self.tipo_reemplazo, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 1, 1),
        )
        requisicion.full_clean()
        requisicion.save()
        self.assertEqual(requisicion.justificacion, "")

    def test_nueva_posicion_passes_with_justificacion(self):
        requisicion = Requisicion(
            posicion=self.create_posicion(), tipo=self.tipo_nueva, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 1, 1), justificacion="Crecimiento de la línea de producción.",
        )
        requisicion.full_clean()
        requisicion.save()


class RequisicionUnaAbiertaPorPosicionTests(RecruitmentTestDataMixin, TestCase):
    def test_no_puede_haber_dos_requisiciones_abiertas_para_la_misma_posicion(self):
        posicion = self.create_posicion()
        self.create_requisicion(posicion=posicion, estado=self.estado_borrador)

        segunda = Requisicion(
            posicion=posicion, tipo=self.tipo_reemplazo, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 2, 1),
        )
        with self.assertRaises(ValidationError) as context:
            segunda.full_clean()
        self.assertIn("posicion", context.exception.message_dict)

    def test_si_puede_haber_otra_una_vez_que_la_anterior_ya_es_terminal(self):
        posicion = self.create_posicion()
        self.create_requisicion(posicion=posicion, estado=self.estado_cubierta)

        segunda = Requisicion(
            posicion=posicion, tipo=self.tipo_reemplazo, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 2, 1),
        )
        segunda.full_clean()
        segunda.save()
        self.assertEqual(Requisicion.objects.filter(posicion=posicion).count(), 2)


class RequisicionSoftDeleteTests(RecruitmentTestDataMixin, TestCase):
    def test_delete_does_not_remove_the_row(self):
        requisicion = self.create_requisicion()

        requisicion.delete()

        self.assertFalse(Requisicion.objects.filter(pk=requisicion.pk).exists())
        self.assertTrue(Requisicion.all_objects.get(pk=requisicion.pk).is_deleted)

    def test_a_soft_deleted_requisicion_no_longer_blocks_a_new_one(self):
        posicion = self.create_posicion()
        requisicion = self.create_requisicion(posicion=posicion, estado=self.estado_borrador)
        requisicion.delete()

        nueva = Requisicion(
            posicion=posicion, tipo=self.tipo_reemplazo, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 2, 1),
        )
        nueva.full_clean()
        nueva.save()


class AprobacionRequisicionTests(RecruitmentTestDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.jefe_inmediato = EtapaAprobacion.objects.get(name="Jefe Inmediato")

    def test_requires_quien_aprobo_si_hay_fecha(self):
        aprobacion = AprobacionRequisicion(
            requisicion=self.create_requisicion(), etapa=self.jefe_inmediato, fecha=date(2026, 1, 2),
        )
        with self.assertRaises(ValidationError) as context:
            aprobacion.full_clean()
        self.assertIn("nombre_manual", context.exception.message_dict)

    def test_ok_con_nombre_capturado_a_mano(self):
        aprobacion = AprobacionRequisicion(
            requisicion=self.create_requisicion(), etapa=self.jefe_inmediato,
            fecha=date(2026, 1, 2), nombre_manual="Juan Pérez",
        )
        aprobacion.full_clean()
        aprobacion.save()

    def test_pendiente_sin_fecha_no_exige_nada(self):
        aprobacion = AprobacionRequisicion(requisicion=self.create_requisicion(), etapa=self.jefe_inmediato)
        aprobacion.full_clean()
        aprobacion.save()

    def test_no_puede_haber_dos_filas_para_la_misma_etapa(self):
        requisicion = self.create_requisicion()
        AprobacionRequisicion.objects.create(requisicion=requisicion, etapa=self.jefe_inmediato)

        with self.assertRaises(IntegrityError), transaction.atomic():
            AprobacionRequisicion.objects.create(requisicion=requisicion, etapa=self.jefe_inmediato)

    def test_borrar_una_aprobacion_libera_su_etapa_para_una_nueva(self):
        requisicion = self.create_requisicion()
        original = AprobacionRequisicion.objects.create(requisicion=requisicion, etapa=self.jefe_inmediato)
        original.delete()

        AprobacionRequisicion.objects.create(requisicion=requisicion, etapa=self.jefe_inmediato)


class RecruitmentAPIAuthenticationTests(RecruitmentTestDataMixin, APITestCase):
    def test_all_recruitment_endpoints_require_authentication(self):
        protected_urls = [
            reverse("estadorequisicion-list"),
            reverse("etapaaprobacion-list"),
            reverse("tipocontratoofrecido-list"),
            reverse("horarioacubrir-list"),
            reverse("requisicion-list"),
            reverse("aprobacionrequisicion-list"),
        ]
        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class RecruitmentCatalogAPITests(RecruitmentTestDataMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="recruitment-catalog-user", email="recruitment-catalog@example.com",
            password="strong-test-password",
        )
        self.client.force_authenticate(user=self.user)

    def test_estado_requisicion_is_read_only_for_any_authenticated_user(self):
        list_url = reverse("estadorequisicion-list")
        response = self.client.get(list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 8)

        create_response = self.client.post(list_url, {"name": "Nuevo"}, format="json")
        self.assertEqual(create_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class RequisicionRoleAPITests(RecruitmentTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        user_model = get_user_model()
        cls.gestor = user_model.objects.create_user(
            username="requisicion-gestor", email="requisicion-gestor@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="capital-humano"),
        )
        cls.gerente = user_model.objects.create_user(
            username="requisicion-gerente", email="requisicion-gerente@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="colaborador"),
        )
        cls.otro_colaborador = user_model.objects.create_user(
            username="requisicion-otro", email="requisicion-otro@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="colaborador"),
        )

    def _payload(self, posicion):
        return {
            "posicion": str(posicion.pk),
            "tipo": str(self.tipo_reemplazo.pk),
            "estado": str(self.estado_borrador.pk),
            "fecha_solicitud": "2026-01-01",
        }

    def test_un_colaborador_cualquiera_puede_crear_una_requisicion(self):
        self.client.force_authenticate(user=self.gerente)
        response = self.client.post(reverse("requisicion-list"), self._payload(self.create_posicion()), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Requisicion.objects.get(pk=response.data["id"]).created_by, self.gerente)

    def test_un_colaborador_solo_ve_las_requisiciones_que_el_creo(self):
        propia = Requisicion.objects.create(
            posicion=self.create_posicion(), tipo=self.tipo_reemplazo, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 1, 1), created_by=self.gerente,
        )
        ajena = Requisicion.objects.create(
            posicion=self.create_posicion(), tipo=self.tipo_reemplazo, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 1, 1), created_by=self.otro_colaborador,
        )

        self.client.force_authenticate(user=self.gerente)
        list_response = self.client.get(reverse("requisicion-list"))
        self.assertEqual(list_response.data["count"], 1)
        self.assertEqual(list_response.data["results"][0]["id"], str(propia.pk))

        detail_own = self.client.get(reverse("requisicion-detail", args=[propia.pk]))
        self.assertEqual(detail_own.status_code, status.HTTP_200_OK)

        detail_other = self.client.get(reverse("requisicion-detail", args=[ajena.pk]))
        self.assertEqual(detail_other.status_code, status.HTTP_404_NOT_FOUND)

    def test_un_colaborador_puede_editar_su_propia_requisicion(self):
        propia = Requisicion.objects.create(
            posicion=self.create_posicion(), tipo=self.tipo_reemplazo, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 1, 1), created_by=self.gerente,
        )
        self.client.force_authenticate(user=self.gerente)
        response = self.client.patch(
            reverse("requisicion-detail", args=[propia.pk]), {"area_solicitante": "Mantenimiento"}, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        propia.refresh_from_db()
        self.assertEqual(propia.area_solicitante, "Mantenimiento")

    def test_un_colaborador_no_puede_borrar_ni_su_propia_requisicion(self):
        propia = Requisicion.objects.create(
            posicion=self.create_posicion(), tipo=self.tipo_reemplazo, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 1, 1), created_by=self.gerente,
        )
        self.client.force_authenticate(user=self.gerente)
        response = self.client.delete(reverse("requisicion-detail", args=[propia.pk]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Requisicion.objects.filter(pk=propia.pk).exists())

    def test_gestor_ve_y_administra_todas_las_requisiciones(self):
        Requisicion.objects.create(
            posicion=self.create_posicion(), tipo=self.tipo_reemplazo, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 1, 1), created_by=self.gerente,
        )
        ajena = Requisicion.objects.create(
            posicion=self.create_posicion(), tipo=self.tipo_reemplazo, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 1, 1), created_by=self.otro_colaborador,
        )

        self.client.force_authenticate(user=self.gestor)
        list_response = self.client.get(reverse("requisicion-list"))
        self.assertEqual(list_response.data["count"], 2)

        delete_response = self.client.delete(reverse("requisicion-detail", args=[ajena.pk]))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Requisicion.objects.filter(pk=ajena.pk).exists())

    def test_el_dueno_puede_exportar_su_propia_requisicion_a_excel(self):
        propia = Requisicion.objects.create(
            posicion=self.create_posicion(), tipo=self.tipo_reemplazo, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 1, 1), created_by=self.gerente,
        )
        self.client.force_authenticate(user=self.gerente)
        response = self.client.get(reverse("requisicion-exportar-excel", args=[propia.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_no_se_puede_exportar_la_requisicion_de_otro_colaborador(self):
        ajena = Requisicion.objects.create(
            posicion=self.create_posicion(), tipo=self.tipo_reemplazo, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 1, 1), created_by=self.otro_colaborador,
        )
        self.client.force_authenticate(user=self.gerente)
        response = self.client.get(reverse("requisicion-exportar-excel", args=[ajena.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class AprobacionRequisicionAPIRoleTests(RecruitmentTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.jefe_inmediato = EtapaAprobacion.objects.get(name="Jefe Inmediato")
        cls.gestor = get_user_model().objects.create_user(
            username="aprobacion-gestor", email="aprobacion-gestor@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="capital-humano"),
        )
        cls.colaborador = get_user_model().objects.create_user(
            username="aprobacion-colaborador", email="aprobacion-colaborador@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="colaborador"),
        )

    def test_un_colaborador_no_puede_crear_ni_leer_aprobaciones(self):
        self.client.force_authenticate(user=self.colaborador)
        response = self.client.get(reverse("aprobacionrequisicion-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_gestor_puede_registrar_una_aprobacion(self):
        requisicion = self.create_requisicion()
        self.client.force_authenticate(user=self.gestor)
        response = self.client.post(
            reverse("aprobacionrequisicion-list"),
            {
                "requisicion": str(requisicion.pk), "etapa": str(self.jefe_inmediato.pk),
                "fecha": "2026-01-02", "nombre_manual": "Juan Pérez",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(AprobacionRequisicion.objects.get(pk=response.data["id"]).created_by, self.gestor)


class BackfillRequisicionesVacantesTests(RecruitmentTestDataMixin, TestCase):
    """
    apps.recruitment.management.commands.backfill_requisiciones_vacantes --
    confirmado 2026-10-01: a las Posicion ya vacantes no se les inventa
    justificación, fecha ni tipo -- lo que falta se reporta, no se adivina.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.estatus_pendiente = EstatusPosicion.objects.create(name="Vacante Pendiente de Confirmación")
        cls.estatus_suspendida = EstatusPosicion.objects.create(name="Vacante Suspendida")
        cls.estatus_eliminada = EstatusPosicion.objects.create(name="Vacante Eliminada")

    def test_migra_una_vacante_con_tipo_conocido_y_sin_justificacion_requerida(self):
        posicion = self.create_posicion(
            estatus=self.estatus_vacante, tipo_requisicion=self.tipo_reemplazo,
            fecha_registro_vacante=date(2025, 6, 1),
        )
        out = StringIO()
        call_command("backfill_requisiciones_vacantes", stdout=out)

        requisicion = Requisicion.objects.get(posicion=posicion)
        self.assertEqual(requisicion.tipo, self.tipo_reemplazo)
        self.assertEqual(requisicion.estado.name, "En Reclutamiento")
        self.assertEqual(requisicion.fecha_solicitud, date(2025, 6, 1))
        self.assertIsNone(requisicion.created_by)
        self.assertIn("Requisición(es) migrada(s): 1", out.getvalue())

    def test_mapea_cada_estatus_vacante_al_estado_de_requisicion_correcto(self):
        casos = [
            (self.estatus_vacante, "En Reclutamiento"),
            (self.estatus_pendiente, "Pendiente de Autorización"),
            (self.estatus_suspendida, "Suspendida"),
            (self.estatus_eliminada, "Cancelada"),
        ]
        for estatus, estado_esperado in casos:
            with self.subTest(estatus=estatus.name):
                posicion = self.create_posicion(
                    estatus=estatus, tipo_requisicion=self.tipo_reemplazo,
                    fecha_registro_vacante=date(2025, 6, 1),
                )
                call_command("backfill_requisiciones_vacantes", stdout=StringIO())
                self.assertEqual(Requisicion.objects.get(posicion=posicion).estado.name, estado_esperado)

    def test_omite_una_vacante_sin_tipo_requisicion(self):
        posicion = self.create_posicion(estatus=self.estatus_vacante, fecha_registro_vacante=date(2025, 6, 1))
        out = StringIO()
        call_command("backfill_requisiciones_vacantes", stdout=out)

        self.assertFalse(Requisicion.objects.filter(posicion=posicion).exists())
        self.assertIn("sin Tipo de requisición capturado", out.getvalue())

    def test_omite_una_vacante_de_tipo_nueva_posicion_porque_falta_la_justificacion(self):
        posicion = self.create_posicion(
            estatus=self.estatus_vacante, tipo_requisicion=self.tipo_nueva,
            fecha_registro_vacante=date(2025, 6, 1),
        )
        out = StringIO()
        call_command("backfill_requisiciones_vacantes", stdout=out)

        self.assertFalse(Requisicion.objects.filter(posicion=posicion).exists())
        self.assertIn("no pasó validación", out.getvalue())

    def test_omite_una_vacante_sin_fecha_de_registro(self):
        posicion = self.create_posicion(estatus=self.estatus_vacante, tipo_requisicion=self.tipo_reemplazo)
        out = StringIO()
        call_command("backfill_requisiciones_vacantes", stdout=out)

        self.assertFalse(Requisicion.objects.filter(posicion=posicion).exists())
        self.assertIn("sin fecha de registro de vacante", out.getvalue())

    def test_es_idempotente(self):
        self.create_posicion(
            estatus=self.estatus_vacante, tipo_requisicion=self.tipo_reemplazo,
            fecha_registro_vacante=date(2025, 6, 1),
        )
        call_command("backfill_requisiciones_vacantes", stdout=StringIO())
        self.assertEqual(Requisicion.objects.count(), 1)

        out = StringIO()
        call_command("backfill_requisiciones_vacantes", stdout=out)
        self.assertEqual(Requisicion.objects.count(), 1)
        self.assertIn("Requisición(es) migrada(s): 0", out.getvalue())

    def test_no_toca_una_posicion_que_ya_tiene_una_requisicion(self):
        posicion = self.create_posicion(
            estatus=self.estatus_vacante, tipo_requisicion=self.tipo_reemplazo,
            fecha_registro_vacante=date(2025, 6, 1),
        )
        self.create_requisicion(posicion=posicion, tipo=self.tipo_reemplazo, estado=self.estado_borrador)

        call_command("backfill_requisiciones_vacantes", stdout=StringIO())

        self.assertEqual(Requisicion.objects.filter(posicion=posicion).count(), 1)
        self.assertEqual(Requisicion.objects.get(posicion=posicion).estado, self.estado_borrador)


class GenerarExcelTests(RecruitmentTestDataMixin, TestCase):
    """
    apps.recruitment.exports.generar_excel -- llena la plantilla oficial de
    GPA exacta (confirmado 2026-10-01: mismo archivo, sin rediseñarlo).
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.puesto = Puesto.objects.create(name="Auxiliar de Prueba")
        cls.puesto_jefe = Puesto.objects.create(name="Supervisor de Prueba")
        unidad_level = OrganizationalLevel.objects.get(code="unidad_negocio")
        cls.unidad_node = OrganizationNode.objects.create(
            level=unidad_level, parent=cls.company_node, code="UN-TEST", name="Unidad de prueba",
        )

    def _crear_jefe_activo(self, posicion_jefe):
        persona = Persona(first_name="Ana", last_name_paternal="Jefa")
        persona.full_clean()
        persona.save()
        empleado = Empleado(persona=persona)
        empleado.full_clean()
        empleado.save()
        contrato = Contrato(empleado=empleado, posicion=posicion_jefe, fecha_ingreso=date(2020, 1, 1))
        contrato.full_clean()
        contrato.save()

    def test_genera_excel_de_reemplazo_con_los_datos_correctos(self):
        posicion_jefe = self.create_posicion(organization_node=self.unidad_node, puesto=self.puesto_jefe)
        self._crear_jefe_activo(posicion_jefe)
        posicion = self.create_posicion(
            organization_node=self.unidad_node, puesto=self.puesto, reports_to=posicion_jefe,
        )
        requisicion = self.create_requisicion(
            posicion=posicion, tipo=self.tipo_reemplazo, estado=self.estado_borrador,
            fecha_solicitud=date(2026, 1, 15), area_solicitante="Mantenimiento",
            horario_a_cubrir=HorarioACubrir.objects.get(name="7:00 - 16:00"),
            disposicion_viajar=True,
            tipo_contrato_ofrecido=TipoContratoOfrecido.objects.get(name="Planta"),
        )

        nombre_archivo, buffer = generar_excel(requisicion)

        self.assertTrue(nombre_archivo.endswith(f"_{requisicion.pk}.xlsx"))
        self.assertIn("FO-C0-CH-08", nombre_archivo)
        partes_oficiales = {
            "xl/drawings/_rels/vmlDrawing1.vml.rels",
            "xl/drawings/vmlDrawing1.vml",
            "xl/media/image1.png",
            "xl/media/image2.png",
            "xl/media/image3.png",
            "xl/media/image4.png",
            "xl/printerSettings/printerSettings1.bin",
            "xl/worksheets/_rels/sheet1.xml.rels",
        }
        with ZipFile(PLANTILLAS_DIR / "FO-C0-CH-08_reemplazo_de_personal_v4.xlsx") as original:
            contenido_original = {
                parte: original.read(parte) for parte in partes_oficiales
            }
        with ZipFile(buffer) as exportado:
            self.assertTrue(partes_oficiales.issubset(exportado.namelist()))
            for parte, contenido in contenido_original.items():
                self.assertEqual(exportado.read(parte), contenido)
            hoja_xml = exportado.read("xl/worksheets/sheet1.xml")
            self.assertIn(b'dimension ref="A1:T45"', hoja_xml)
            self.assertIn(b'row r="45"', hoja_xml)

        ws = openpyxl.load_workbook(buffer).active
        self.assertEqual(ws["D1"].value.date(), date(2026, 1, 15))
        self.assertEqual(ws["D1"].number_format, "dd/mm/yyyy")
        self.assertEqual(ws["D4"].value, self.puesto.name)
        self.assertEqual(ws["M4"].value, "Mantenimiento")
        self.assertEqual(ws["D5"].value, self.unidad_node.name)
        self.assertEqual(ws["M5"].value, self.company_node.name)
        self.assertEqual(ws["D6"].value, self.puesto_jefe.name)
        self.assertEqual(ws["M6"].value, "Jefa  Ana")
        self.assertEqual(ws["I9"].value, "X")   # horario "7:00 - 16:00"
        self.assertEqual(ws["O11"].value, "X")  # disposición a viajar: sí
        self.assertIsNone(ws["Q11"].value)       # limpia el "No" premarcado de la plantilla
        self.assertEqual(ws["G17"].value, "X")  # tipo de contrato: Planta

    def test_genera_excel_de_nueva_posicion_usa_la_otra_plantilla_con_la_justificacion(self):
        posicion = self.create_posicion(puesto=self.puesto)
        requisicion = self.create_requisicion(
            posicion=posicion, tipo=self.tipo_nueva, estado=self.estado_borrador,
            justificacion="Crecimiento del área.",
        )
        nombre_archivo, buffer = generar_excel(requisicion)
        self.assertIn("FO-C0-CH-01", nombre_archivo)
        ws = openpyxl.load_workbook(buffer).active
        self.assertEqual(ws["A9"].value, "Crecimiento del área.")

    def test_campos_sin_dato_real_se_dejan_vacios_no_se_inventan(self):
        posicion = self.create_posicion()  # sin puesto, sin reports_to
        requisicion = self.create_requisicion(posicion=posicion)

        _, buffer = generar_excel(requisicion)

        ws = openpyxl.load_workbook(buffer).active
        self.assertIsNone(ws["D4"].value)  # nombre_vacante: sin Puesto capturado
        self.assertIsNone(ws["D6"].value)  # puesto_inmediato_superior: sin reports_to
        self.assertIsNone(ws["M6"].value)  # nombre_jefe_inmediato: sin reports_to
        self.assertIsNone(ws["O11"].value)  # disposición a viajar: sin dato
        self.assertIsNone(ws["Q11"].value)  # no conserva el "No" premarcado de la plantilla
