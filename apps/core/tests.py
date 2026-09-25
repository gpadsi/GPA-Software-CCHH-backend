from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.permissions import (
    IsCapitalHumanoOrAdmin,
    IsCapitalHumanoOrAdminOrReadOnly,
    es_gestion_rrhh,
    scope_to_own_unless_management,
)
from apps.employment.models import Empleado
from apps.persons.models import Genero, Persona
from apps.users.models import UserRole


class NamedCatalogSaveTests(TestCase):
    """
    Genero es una NamedCatalog concreta cualquiera — se usa aquí solo para
    probar el save() compartido (autogeneración/truncado/sufijo de code),
    no algo específico de género.
    """

    def test_code_is_auto_generated_from_name_when_not_given(self):
        genero = Genero.objects.create(name="Masculino")
        self.assertEqual(genero.code, "masculino")

    def test_long_name_is_truncated_to_fit_the_code_max_length(self):
        # Regresión: un nombre largo (ej. un título de puesto real de GPA)
        # solía tronar con StringDataRightTruncation antes de truncar el
        # slug ANTES de guardar en vez de después.
        max_length = Genero._meta.get_field("code").max_length
        nombre_largo = "Palabra " * 10  # cabe en name (150), no en code (50)
        genero = Genero.objects.create(name=nombre_largo)
        self.assertLessEqual(len(genero.code), max_length)

    def test_duplicate_name_gets_a_numeric_suffix_instead_of_colliding(self):
        primero = Genero.objects.create(name="Indistinto")
        segundo = Genero.objects.create(name="Indistinto")
        self.assertEqual(primero.code, "indistinto")
        self.assertEqual(segundo.code, "indistinto-1")

    def test_explicit_code_is_never_overwritten(self):
        genero = Genero.objects.create(name="Femenino", code="custom-code")
        self.assertEqual(genero.code, "custom-code")


class RolePermissionUnitTests(TestCase):
    """
    Prueba apps.core.permissions directamente (sin pasar por HTTP) — el
    resto de las apps ya cubren su uso real en cada endpoint; aquí se
    prueba la lógica compartida en aislamiento.
    """

    @classmethod
    def setUpTestData(cls):
        call_command("seed_user_roles", stdout=StringIO())
        user_model = get_user_model()
        cls.admin = user_model.objects.create_user(
            username="perm-admin", email="perm-admin@example.com",
            password="x", role=UserRole.objects.get(code="admin"),
        )
        cls.capital_humano = user_model.objects.create_user(
            username="perm-ch", email="perm-ch@example.com",
            password="x", role=UserRole.objects.get(code="capital-humano"),
        )
        cls.colaborador = user_model.objects.create_user(
            username="perm-colaborador", email="perm-colaborador@example.com",
            password="x", role=UserRole.objects.get(code="colaborador"),
        )
        cls.sin_rol = user_model.objects.create_user(
            username="perm-sin-rol", email="perm-sin-rol@example.com", password="x",
        )
        cls.factory = RequestFactory()

    def test_es_gestion_rrhh_is_true_only_for_admin_and_capital_humano(self):
        self.assertTrue(es_gestion_rrhh(self.admin))
        self.assertTrue(es_gestion_rrhh(self.capital_humano))
        self.assertFalse(es_gestion_rrhh(self.colaborador))
        self.assertFalse(es_gestion_rrhh(self.sin_rol))
        self.assertFalse(es_gestion_rrhh(None))

    def test_is_capital_humano_or_admin_denies_read_and_write_to_everyone_else(self):
        permission = IsCapitalHumanoOrAdmin()
        for method in ("GET", "POST"):
            request = self.factory.generic(method, "/")
            with self.subTest(user="capital_humano", method=method):
                request.user = self.capital_humano
                self.assertTrue(permission.has_permission(request, view=None))
            with self.subTest(user="colaborador", method=method):
                request.user = self.colaborador
                self.assertFalse(permission.has_permission(request, view=None))

    def test_is_capital_humano_or_admin_or_read_only_allows_read_to_anyone_authenticated(self):
        permission = IsCapitalHumanoOrAdminOrReadOnly()
        request = self.factory.get("/")

        request.user = self.colaborador
        self.assertTrue(permission.has_permission(request, view=None))

        request.user = self.capital_humano
        self.assertTrue(permission.has_permission(request, view=None))

    def test_is_capital_humano_or_admin_or_read_only_blocks_write_for_colaborador(self):
        permission = IsCapitalHumanoOrAdminOrReadOnly()
        request = self.factory.post("/")

        request.user = self.colaborador
        self.assertFalse(permission.has_permission(request, view=None))

        request.user = self.capital_humano
        self.assertTrue(permission.has_permission(request, view=None))

    def test_scope_to_own_unless_management(self):
        persona_uno = Persona.objects.create(first_name="Uno", last_name_paternal="Persona")
        persona_dos = Persona.objects.create(first_name="Dos", last_name_paternal="Persona")
        Empleado.objects.create(persona=persona_uno, user=self.colaborador)
        Empleado.objects.create(persona=persona_dos, user=self.capital_humano)

        colaborador_scoped = scope_to_own_unless_management(Empleado.objects.all(), self.colaborador, "user")
        self.assertEqual(list(colaborador_scoped), [Empleado.objects.get(user=self.colaborador)])

        gestor_scoped = scope_to_own_unless_management(Empleado.objects.all(), self.capital_humano, "user")
        self.assertEqual(gestor_scoped.count(), 2)


class GeneroCodeUniquenessConstraintTests(TestCase):
    def test_code_field_is_still_unique_at_the_database_level(self):
        Genero.objects.create(name="Masculino", code="masculino")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Genero.objects.create(name="Otro nombre", code="masculino")


class AttachmentRoleAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_user_roles", stdout=StringIO())
        user_model = get_user_model()
        cls.gestor = user_model.objects.create_user(
            username="attachment-gestor", email="attachment-gestor@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="capital-humano"),
        )
        cls.colaborador = user_model.objects.create_user(
            username="attachment-colaborador", email="attachment-colaborador@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="colaborador"),
        )

    def test_anonymous_is_rejected(self):
        response = self.client.get(reverse("attachment-list-create"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_colaborador_cannot_list_attachments(self):
        # Gate total por ahora: Attachment se engancha a cualquier modelo
        # vía GenericForeignKey, sin forma barata de resolver "¿es mío?".
        self.client.force_authenticate(user=self.colaborador)
        response = self.client.get(reverse("attachment-list-create"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_gestor_can_list_attachments(self):
        self.client.force_authenticate(user=self.gestor)
        response = self.client.get(reverse("attachment-list-create"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
