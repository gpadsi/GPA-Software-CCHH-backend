from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.locations.models import Area, Nave, Ubicacion
from apps.users.models import UserRole


class LocationsTestDataMixin:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("seed_user_roles", stdout=StringIO())


class NaveConstraintTests(LocationsTestDataMixin, TestCase):
    def test_code_must_be_unique_within_the_same_ubicacion(self):
        ubicacion = Ubicacion.objects.create(code="MATRIZ", name="Matriz")
        Nave.objects.create(ubicacion=ubicacion, code="N1")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Nave.objects.create(ubicacion=ubicacion, code="N1")

    def test_same_code_is_allowed_under_a_different_ubicacion(self):
        matriz = Ubicacion.objects.create(code="MATRIZ", name="Matriz")
        ciem = Ubicacion.objects.create(code="CIEM", name="CIEM")
        Nave.objects.create(ubicacion=matriz, code="N1")
        Nave.objects.create(ubicacion=ciem, code="N1")
        self.assertEqual(Nave.objects.filter(code="N1").count(), 2)


class AreaConstraintTests(LocationsTestDataMixin, TestCase):
    def test_code_must_be_unique_within_the_same_nave(self):
        ubicacion = Ubicacion.objects.create(code="MATRIZ", name="Matriz")
        nave = Nave.objects.create(ubicacion=ubicacion, code="N1")
        Area.objects.create(nave=nave, code="PINTURA", name="Pintura")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Area.objects.create(nave=nave, code="PINTURA", name="Pintura otra vez")

    def test_areas_without_a_nave_do_not_collide_on_the_same_code(self):
        # nave=NULL: Postgres no considera NULL igual a NULL para la
        # restricción de unicidad, así que dos Áreas genéricas (sin nave
        # confirmada todavía) pueden compartir código sin chocar — esto es
        # justo lo que permite tener un Área genérica por nombre mientras no
        # se sabe en qué nave está cada Posición real.
        Area.objects.create(nave=None, code="PINTURA", name="Pintura genérica")
        Area.objects.create(nave=None, code="PINTURA", name="Pintura genérica (otra fila)")
        self.assertEqual(Area.objects.filter(nave__isnull=True, code="PINTURA").count(), 2)


class LocationsAPIAuthenticationTests(LocationsTestDataMixin, APITestCase):
    def test_all_locations_endpoints_require_authentication(self):
        protected_urls = [reverse("ubicacion-list"), reverse("nave-list"), reverse("area-list")]
        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class LocationsRoleAPITests(LocationsTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        user_model = get_user_model()
        cls.gestor = user_model.objects.create_user(
            username="locations-gestor", email="locations-gestor@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="capital-humano"),
        )
        cls.colaborador = user_model.objects.create_user(
            username="locations-colaborador", email="locations-colaborador@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="colaborador"),
        )
        cls.ubicacion = Ubicacion.objects.create(code="MATRIZ", name="Matriz")

    def test_colaborador_can_read_ubicaciones(self):
        self.client.force_authenticate(user=self.colaborador)
        response = self.client.get(reverse("ubicacion-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_colaborador_cannot_write_to_ubicaciones(self):
        self.client.force_authenticate(user=self.colaborador)

        create_response = self.client.post(
            reverse("ubicacion-list"), {"code": "NUEVA", "name": "Nueva"}, format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)

        update_response = self.client.patch(
            reverse("ubicacion-detail", args=[self.ubicacion.pk]), {"name": "Alterada"}, format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_gestor_can_create_and_update_with_audit_fields(self):
        self.client.force_authenticate(user=self.gestor)
        create_response = self.client.post(
            reverse("ubicacion-list"), {"code": "CIEM", "name": "CIEM"}, format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        ubicacion = Ubicacion.objects.get(pk=create_response.data["id"])
        self.assertEqual(ubicacion.created_by, self.gestor)
        self.assertEqual(ubicacion.updated_by, self.gestor)
