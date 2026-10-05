from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
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


SUPERUSER_ENV = {
    "DJANGO_SUPERUSER_USERNAME": "boot-admin",
    "DJANGO_SUPERUSER_EMAIL": "boot-admin@example.com",
    "DJANGO_SUPERUSER_PASSWORD": "strong-test-password",
}


class EnsureSuperuserTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_user_roles", stdout=StringIO())
        cls.admin_role = UserRole.objects.get(code="admin")

    def run_command(self, **env):
        with mock.patch.dict("os.environ", {**SUPERUSER_ENV, **env}):
            call_command("ensure_superuser", stdout=StringIO())

    def test_creates_the_superuser_with_admin_role_and_is_idempotent(self):
        self.run_command()
        self.run_command()

        user = User.objects.get(username="boot-admin")
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.email, "boot-admin@example.com")
        self.assertEqual(user.role, self.admin_role)
        self.assertTrue(user.check_password("strong-test-password"))
        self.assertEqual(User.objects.filter(username="boot-admin").count(), 1)

    def test_password_with_quotes_is_stored_literally(self):
        self.run_command(DJANGO_SUPERUSER_PASSWORD="it's \"quoted\"\\")
        self.assertTrue(User.objects.get(username="boot-admin").check_password("it's \"quoted\"\\"))

    def test_assigns_admin_role_to_an_existing_superuser_without_role(self):
        User.objects.create_superuser("boot-admin", "boot-admin@example.com", "old-password")

        self.run_command(DJANGO_SUPERUSER_PASSWORD="new-password")

        user = User.objects.get(username="boot-admin")
        self.assertEqual(user.role, self.admin_role)
        self.assertTrue(user.check_password("old-password"))

    def test_does_not_touch_an_existing_user_that_already_has_a_role(self):
        colaborador = UserRole.objects.get(code="colaborador")
        User.objects.create_superuser("boot-admin", "boot-admin@example.com", "pw", role=colaborador)

        self.run_command()

        self.assertEqual(User.objects.get(username="boot-admin").role, colaborador)

    def test_skips_creation_without_password(self):
        self.run_command(DJANGO_SUPERUSER_PASSWORD="")
        self.assertFalse(User.objects.filter(username="boot-admin").exists())

    @override_settings(DEBUG=False)
    def test_skips_creation_with_the_example_password_outside_development(self):
        self.run_command(DJANGO_SUPERUSER_PASSWORD="cambiar_esta_contrasena")
        self.assertFalse(User.objects.filter(username="boot-admin").exists())

    @override_settings(DEBUG=True)
    def test_allows_the_example_password_in_development(self):
        self.run_command(DJANGO_SUPERUSER_PASSWORD="cambiar_esta_contrasena")
        self.assertTrue(User.objects.filter(username="boot-admin").exists())

    def test_fails_loudly_when_roles_are_not_seeded(self):
        UserRole.objects.all().delete()
        with self.assertRaises(CommandError):
            self.run_command()


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
