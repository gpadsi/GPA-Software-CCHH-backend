from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import User, UserRole


class SeedUserRolesTests(TestCase):
    def test_seed_is_idempotent_and_creates_exactly_the_three_confirmed_roles(self):
        call_command("seed_user_roles", stdout=StringIO())

        codes = set(UserRole.objects.values_list("code", flat=True))
        self.assertEqual(codes, {"colaborador", "capital-humano", "admin"})
        self.assertEqual(UserRole.objects.count(), 3)
        ids_after_first_run = dict(UserRole.objects.values_list("code", "pk"))

        call_command("seed_user_roles", stdout=StringIO())

        self.assertEqual(UserRole.objects.count(), 3)
        self.assertEqual(dict(UserRole.objects.values_list("code", "pk")), ids_after_first_run)


class MeViewTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_user_roles", stdout=StringIO())
        cls.user = User.objects.create_user(
            username="me-view-user", email="me-view@example.com",
            password="strong-test-password", role=UserRole.objects.get(code="colaborador"),
        )

    def test_me_requires_authentication(self):
        response = self.client.get(reverse("user-me"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_the_authenticated_users_own_data(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse("user-me"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "me-view-user")
        self.assertEqual(response.data["email"], "me-view@example.com")

    def _me(self, user):
        self.client.force_authenticate(user=user)
        return self.client.get(reverse("user-me")).data

    def test_me_exposes_the_role_and_that_a_colaborador_cannot_manage(self):
        data = self._me(self.user)
        self.assertEqual(dict(data["role"]), {"code": "colaborador", "name": "Colaborador"})
        self.assertFalse(data["can_manage_hr"])

    def test_me_says_capital_humano_and_admin_can_manage(self):
        for code in ("capital-humano", "admin"):
            with self.subTest(role=code):
                usuario = User.objects.create_user(
                    username=f"me-{code}", email=f"me-{code}@example.com",
                    password="strong-test-password", role=UserRole.objects.get(code=code),
                )
                data = self._me(usuario)
                self.assertEqual(data["role"]["code"], code)
                self.assertTrue(data["can_manage_hr"])

    def test_me_for_an_account_without_role_has_null_role_and_cannot_manage(self):
        # Un superusuario sin rol tampoco puede escribir en la API: es_gestion_rrhh
        # exige el rol, no is_superuser. El front debe verlo igual que la API.
        sin_rol = User.objects.create_superuser(
            username="me-sin-rol", email="me-sin-rol@example.com", password="strong-test-password",
        )
        data = self._me(sin_rol)
        self.assertIsNone(data["role"])
        self.assertFalse(data["can_manage_hr"])
