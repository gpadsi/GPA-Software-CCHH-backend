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
