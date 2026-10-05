from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.employment.models import Empleado
from apps.locations.models import Area
from apps.persons.models import Persona
from apps.schedules.models import AsignacionHorario, AsignacionUbicacion, Catorcena, TipoHorario
from apps.users.models import UserRole


class SchedulesTestDataMixin:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("seed_user_roles", stdout=StringIO())
        cls.area = Area.objects.create(nave=None, code="PINTURA", name="Pintura")
        cls.tipo_horario = TipoHorario.objects.create(name="H01", descripcion="07:00 - 16:00")

    @classmethod
    def create_empleado_with_user(cls, *, username, role_code):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            username=username, email=f"{username}@example.com",
            password="strong-test-password", role=UserRole.objects.get(code=role_code),
        )
        persona = Persona.objects.create(first_name="Nombre", last_name_paternal="Apellido")
        empleado = Empleado(persona=persona, user=user)
        empleado.full_clean()
        empleado.save()
        return user, empleado

    @classmethod
    def create_empleado(cls):
        persona = Persona.objects.create(first_name="Otro", last_name_paternal="Empleado")
        empleado = Empleado(persona=persona)
        empleado.full_clean()
        empleado.save()
        return empleado


class CatorcenaConstraintTests(SchedulesTestDataMixin, TestCase):
    def test_numero_and_anio_combination_must_be_unique(self):
        Catorcena.objects.create(numero=1, anio=2026, fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 1, 14))

        with self.assertRaises(IntegrityError), transaction.atomic():
            Catorcena.objects.create(
                numero=1, anio=2026, fecha_inicio=date(2026, 1, 15), fecha_fin=date(2026, 1, 28),
            )

    def test_same_numero_is_allowed_in_a_different_anio(self):
        Catorcena.objects.create(numero=1, anio=2026, fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 1, 14))
        Catorcena.objects.create(numero=1, anio=2027, fecha_inicio=date(2027, 1, 1), fecha_fin=date(2027, 1, 14))
        self.assertEqual(Catorcena.objects.filter(numero=1).count(), 2)


class SchedulesAPIAuthenticationTests(SchedulesTestDataMixin, APITestCase):
    def test_all_schedules_endpoints_require_authentication(self):
        protected_urls = [
            reverse("catorcena-list"),
            reverse("tipohorario-list"),
            reverse("asignacionubicacion-list"),
            reverse("asignacionhorario-list"),
        ]
        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class SchedulesRoleAPITests(SchedulesTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        user_model = get_user_model()
        cls.gestor = user_model.objects.create_user(
            username="schedules-gestor", email="schedules-gestor@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="capital-humano"),
        )
        cls.colaborador_user, cls.colaborador_empleado = cls.create_empleado_with_user(
            username="schedules-colaborador", role_code="colaborador",
        )
        cls.otro_empleado = cls.create_empleado()

        cls.asignacion_ubicacion_propia = AsignacionUbicacion.objects.create(
            empleado=cls.colaborador_empleado, fecha_referencia=date(2026, 1, 1), area=cls.area,
        )
        cls.asignacion_ubicacion_ajena = AsignacionUbicacion.objects.create(
            empleado=cls.otro_empleado, fecha_referencia=date(2026, 1, 1), area=cls.area,
        )
        cls.asignacion_horario_propia = AsignacionHorario.objects.create(
            empleado=cls.colaborador_empleado, fecha_referencia=date(2026, 1, 1), tipo_horario=cls.tipo_horario,
        )
        cls.asignacion_horario_ajena = AsignacionHorario.objects.create(
            empleado=cls.otro_empleado, fecha_referencia=date(2026, 1, 1), tipo_horario=cls.tipo_horario,
        )

    def test_colaborador_reads_the_tipo_horario_catalog_but_cannot_write_it(self):
        self.client.force_authenticate(user=self.colaborador_user)
        response = self.client.get(reverse("tipohorario-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        create_response = self.client.post(reverse("tipohorario-list"), {"name": "H99"}, format="json")
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        update_response = self.client.patch(
            reverse("tipohorario-detail", args=[self.tipo_horario.pk]), {"descripcion": "x"}, format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_gestor_creates_and_edits_a_tipo_horario_but_cannot_delete_it(self):
        self.client.force_authenticate(user=self.gestor)
        create_response = self.client.post(
            reverse("tipohorario-list"), {"name": "H02", "descripcion": "08:00 - 17:00"}, format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data["code"], "h02")
        self.assertEqual(create_response.data["descripcion"], "08:00 - 17:00")

        url = reverse("tipohorario-detail", args=[create_response.data["id"]])
        update_response = self.client.patch(
            url, {"descripcion": "08:00 - 16:00", "is_active": False}, format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data["descripcion"], "08:00 - 16:00")
        self.assertFalse(update_response.data["is_active"])

        self.assertEqual(self.client.delete(url).status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(TipoHorario.objects.filter(pk=create_response.data["id"]).exists())

    def test_tipo_horario_name_cannot_repeat_ignoring_case(self):
        self.client.force_authenticate(user=self.gestor)
        response = self.client.post(reverse("tipohorario-list"), {"name": "h01"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data)
        self.assertEqual(TipoHorario.objects.count(), 1)

    def test_colaborador_can_read_every_catorcena_but_cannot_write(self):
        Catorcena.objects.create(numero=1, anio=2026, fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 1, 14))
        self.client.force_authenticate(user=self.colaborador_user)

        list_response = self.client.get(reverse("catorcena-list"))
        self.assertEqual(list_response.data["count"], 1)

        create_response = self.client.post(
            reverse("catorcena-list"),
            {"numero": 2, "anio": 2026, "fecha_inicio": "2026-01-15", "fecha_fin": "2026-01-28"},
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_colaborador_only_sees_own_asignacion_ubicacion(self):
        self.client.force_authenticate(user=self.colaborador_user)
        response = self.client.get(reverse("asignacionubicacion-list"))
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(self.asignacion_ubicacion_propia.pk))

    def test_colaborador_gets_404_reading_someone_elses_asignacion_ubicacion(self):
        self.client.force_authenticate(user=self.colaborador_user)
        response = self.client.get(reverse("asignacionubicacion-detail", args=[self.asignacion_ubicacion_ajena.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_colaborador_only_sees_own_asignacion_horario(self):
        self.client.force_authenticate(user=self.colaborador_user)
        response = self.client.get(reverse("asignacionhorario-list"))
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(self.asignacion_horario_propia.pk))

    def test_colaborador_cannot_write_to_asignaciones(self):
        self.client.force_authenticate(user=self.colaborador_user)

        response = self.client.patch(
            reverse("asignacionubicacion-detail", args=[self.asignacion_ubicacion_propia.pk]),
            {"area": str(self.area.pk)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_gestor_sees_and_can_write_every_asignacion_with_audit_fields(self):
        self.client.force_authenticate(user=self.gestor)

        list_response = self.client.get(reverse("asignacionubicacion-list"))
        self.assertEqual(list_response.data["count"], 2)

        create_response = self.client.post(
            reverse("asignacionhorario-list"),
            {
                "empleado": str(self.otro_empleado.pk),
                "fecha_referencia": "2026-02-01",
                "tipo_horario": str(self.tipo_horario.pk),
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        asignacion = AsignacionHorario.objects.get(pk=create_response.data["id"])
        self.assertEqual(asignacion.created_by, self.gestor)
        self.assertEqual(asignacion.updated_by, self.gestor)
