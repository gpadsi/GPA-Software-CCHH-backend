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

from apps.organizations.models import OrganizationalLevel, OrganizationNode
from apps.positions.models import EstatusPosicion, Posicion, TipoRequisicion
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
