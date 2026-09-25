from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.employment.models import Empleado
from apps.persons.models import ContactoUrgencia, Genero, Persona, PerfilMedico
from apps.users.models import UserRole


class PersonsTestDataMixin:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("seed_user_roles", stdout=StringIO())

    @classmethod
    def create_persona(cls, *, first_name="Nombre", last_name_paternal="Apellido", **kwargs):
        persona = Persona(first_name=first_name, last_name_paternal=last_name_paternal, **kwargs)
        persona.full_clean()
        persona.save()
        return persona

    @classmethod
    def create_empleado_with_user(cls, *, persona=None, username, role_code):
        user_model = get_user_model()
        user = user_model.objects.create_user(
            username=username, email=f"{username}@example.com",
            password="strong-test-password", role=UserRole.objects.get(code=role_code),
        )
        empleado = Empleado(persona=persona or cls.create_persona(), user=user)
        empleado.full_clean()
        empleado.save()
        return user, empleado


class PersonaConstraintTests(PersonsTestDataMixin, TestCase):
    def test_curp_must_be_unique_when_set(self):
        self.create_persona(curp="GOHJ800101HDFNRN01")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Persona.objects.create(
                first_name="Otra", last_name_paternal="Persona", curp="GOHJ800101HDFNRN01",
            )

    def test_multiple_personas_can_have_null_curp(self):
        # Mismo motivo que Empleado.work_number: null=True (no solo
        # blank=True) para que dos personas sin CURP capturado todavía no
        # choquen contra la unicidad.
        self.create_persona()
        self.create_persona()
        self.assertEqual(Persona.objects.filter(curp__isnull=True).count(), 2)


class PersonsAPIAuthenticationTests(PersonsTestDataMixin, APITestCase):
    def test_all_persons_endpoints_require_authentication(self):
        protected_urls = [
            reverse("genero-list"),
            reverse("estadocivil-list"),
            reverse("escolaridad-list"),
            reverse("tiposangre-list"),
            reverse("persona-list"),
            reverse("contactourgencia-list"),
            reverse("perfilmedico-list"),
        ]
        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PersonsCatalogAPITests(PersonsTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Genero.objects.create(name="Masculino")
        user_model = get_user_model()
        cls.user = user_model.objects.create_user(
            username="persons-catalog-user", email="persons-catalog@example.com",
            password="strong-test-password",
        )

    def test_genero_catalog_is_read_only_for_any_authenticated_user(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("genero-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

        create_response = self.client.post(reverse("genero-list"), {"name": "Otro"}, format="json")
        self.assertEqual(create_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class PersonaRoleAPITests(PersonsTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        user_model = get_user_model()
        cls.gestor = user_model.objects.create_user(
            username="persons-gestor", email="persons-gestor@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="capital-humano"),
        )
        cls.colaborador_user, cls.colaborador_empleado = cls.create_empleado_with_user(
            persona=cls.create_persona(first_name="Juan", last_name_paternal="Perez"),
            username="persons-colaborador", role_code="colaborador",
        )
        cls.otra_persona = cls.create_persona(first_name="Otra", last_name_paternal="Persona")

        cls.contacto_propio = ContactoUrgencia.objects.create(
            persona=cls.colaborador_empleado.persona, name="Mamá", relationship="Madre", phone="5512345678",
        )
        cls.contacto_ajeno = ContactoUrgencia.objects.create(
            persona=cls.otra_persona, name="Papá", relationship="Padre", phone="5598765432",
        )
        cls.perfil_propio = PerfilMedico.objects.create(persona=cls.colaborador_empleado.persona, allergies="Ninguna")
        cls.perfil_ajeno = PerfilMedico.objects.create(persona=cls.otra_persona, allergies="Penicilina")

    # --- Persona ---

    def test_gestor_sees_every_persona(self):
        self.client.force_authenticate(user=self.gestor)
        response = self.client.get(reverse("persona-list"))
        self.assertEqual(response.data["count"], 2)

    def test_colaborador_only_sees_own_persona(self):
        self.client.force_authenticate(user=self.colaborador_user)
        response = self.client.get(reverse("persona-list"))
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(self.colaborador_empleado.persona.pk))

    def test_colaborador_gets_404_reading_someone_elses_persona(self):
        self.client.force_authenticate(user=self.colaborador_user)
        response = self.client.get(reverse("persona-detail", args=[self.otra_persona.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_colaborador_cannot_write_to_persona(self):
        self.client.force_authenticate(user=self.colaborador_user)
        response = self.client.patch(
            reverse("persona-detail", args=[self.colaborador_empleado.persona.pk]),
            {"phone": "5500000000"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # --- ContactoUrgencia (dato sensible, propio incluido) ---

    def test_colaborador_only_sees_own_contacto_urgencia(self):
        self.client.force_authenticate(user=self.colaborador_user)
        response = self.client.get(reverse("contactourgencia-list"))
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(self.contacto_propio.pk))

    def test_colaborador_gets_404_reading_someone_elses_contacto_urgencia(self):
        self.client.force_authenticate(user=self.colaborador_user)
        response = self.client.get(reverse("contactourgencia-detail", args=[self.contacto_ajeno.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # --- PerfilMedico (Colaborador SÍ ve el propio, confirmado 2026-09-24) ---

    def test_colaborador_can_read_their_own_perfil_medico(self):
        self.client.force_authenticate(user=self.colaborador_user)
        response = self.client.get(reverse("perfilmedico-detail", args=[self.perfil_propio.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["allergies"], "Ninguna")

    def test_colaborador_gets_404_reading_someone_elses_perfil_medico(self):
        self.client.force_authenticate(user=self.colaborador_user)
        response = self.client.get(reverse("perfilmedico-detail", args=[self.perfil_ajeno.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_colaborador_cannot_write_to_their_own_perfil_medico(self):
        # Solo lectura para Colaborador por ahora (confirmado 2026-09-24) —
        # ni siquiera de su propio perfil médico.
        self.client.force_authenticate(user=self.colaborador_user)
        response = self.client.patch(
            reverse("perfilmedico-detail", args=[self.perfil_propio.pk]),
            {"allergies": "Cambiado por Colaborador"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_gestor_can_create_persona_with_audit_fields(self):
        self.client.force_authenticate(user=self.gestor)
        response = self.client.post(
            reverse("persona-list"),
            {"first_name": "Nueva", "last_name_paternal": "Persona"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        persona = Persona.objects.get(pk=response.data["id"])
        self.assertEqual(persona.created_by, self.gestor)
        self.assertEqual(persona.updated_by, self.gestor)
