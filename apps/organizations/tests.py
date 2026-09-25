from io import StringIO

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.core.admin import AuditableAdminMixin
from apps.organizations.models import (
    Company,
    OrganizationalLevel,
    OrganizationNode,
    Tenant,
)
from apps.users.models import UserRole


# A partir de "unidad_negocio" (nivel 3), el mismo nivel se anida a sí mismo
# indefinidamente — no son 5 niveles fijos distintos (Gerencia/Coordinación/
# Supervisión/Departamento/Área), son instancias repetidas del MISMO nivel,
# distinguidas solo por su nombre y su profundidad.
EXPECTED_LEVELS = [
    (1, "empresa", "Empresa", False),
    (2, "unidad_organizacional", "Unidad Organizacional", False),
    (3, "unidad_negocio", "Unidad de Negocio", True),
]


def run_organizational_seed():
    """Run the seeds without adding command output to the test report."""
    call_command("seed_tenant", stdout=StringIO())
    call_command("seed_organizational_levels", stdout=StringIO())


class SeedTenantTests(TestCase):
    def test_seed_is_idempotent_and_creates_exactly_one_tenant(self):
        call_command("seed_tenant", stdout=StringIO())

        self.assertEqual(Tenant.objects.count(), 1)
        tenant = Tenant.objects.get()
        self.assertEqual(tenant.code, "GPA")
        self.assertEqual(tenant.name, "Grupo GPA")

        call_command("seed_tenant", stdout=StringIO())

        self.assertEqual(Tenant.objects.count(), 1)
        self.assertEqual(Tenant.objects.get().pk, tenant.pk)


class SeedOrganizationalLevelsTests(TestCase):
    def test_seed_is_idempotent_and_creates_the_exact_initial_catalog(self):
        run_organizational_seed()

        levels_after_first_run = list(
            OrganizationalLevel.objects.order_by("numero").values_list(
                "numero", "code", "name", "allows_recursive_nesting"
            )
        )
        level_ids_after_first_run = dict(
            OrganizationalLevel.objects.values_list("code", "pk")
        )
        self.assertEqual(levels_after_first_run, EXPECTED_LEVELS)
        self.assertEqual(OrganizationalLevel.objects.count(), 3)

        run_organizational_seed()

        self.assertEqual(
            list(
                OrganizationalLevel.objects.order_by("numero").values_list(
                    "numero", "code", "name", "allows_recursive_nesting"
                )
            ),
            EXPECTED_LEVELS,
        )
        self.assertEqual(
            dict(OrganizationalLevel.objects.values_list("code", "pk")),
            level_ids_after_first_run,
        )
        self.assertEqual(OrganizationalLevel.objects.count(), 3)


class OrganizationTestDataMixin:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        run_organizational_seed()
        cls.tenant = Tenant.objects.get()
        cls.levels = {
            level.code: level for level in OrganizationalLevel.objects.all()
        }

    @classmethod
    def create_valid_node(
        cls,
        *,
        level_code,
        code,
        name,
        parent=None,
        created_by=None,
        updated_by=None,
    ):
        node = OrganizationNode(
            level=cls.levels[level_code],
            parent=parent,
            code=code,
            name=name,
            created_by=created_by,
            updated_by=updated_by,
        )
        node.full_clean()
        node.save()
        return node

    @classmethod
    def create_recursive_business_unit_chain(cls):
        """
        Reproduce el ejemplo real de GPA: Empresa -> Unidad Organizacional ->
        Unidad de Negocio -> Unidad de Negocio, donde las dos últimas son el
        MISMO nivel anidado, no dos niveles distintos.
        """
        company_node = cls.create_valid_node(
            level_code="empresa",
            code="GPA-AZM",
            name="GPA Azimatronics",
        )
        org_unit = cls.create_valid_node(
            level_code="unidad_organizacional",
            code="GPA-AZM-UO",
            name="Mass Production",
            parent=company_node,
        )
        management = cls.create_valid_node(
            level_code="unidad_negocio",
            code="GPA-AZM-GER",
            name="Gerencia de Operaciones",
            parent=org_unit,
        )
        department = cls.create_valid_node(
            level_code="unidad_negocio",
            code="GPA-AZM-DEP",
            name="Departamento de Producción",
            parent=management,
        )
        return company_node, org_unit, management, department


class OrganizationModelValidationTests(OrganizationTestDataMixin, TestCase):
    def assert_field_validation_error(self, instance, field, message_fragment):
        with self.assertRaises(ValidationError) as context:
            instance.full_clean()
        self.assertIn(field, context.exception.message_dict)
        self.assertIn(
            message_fragment,
            " ".join(context.exception.message_dict[field]),
        )

    def test_tenant_is_auto_assigned_when_not_provided(self):
        node = self.create_valid_node(
            level_code="empresa",
            code="GPA-AUTO-TENANT",
            name="Empresa sin tenant explícito",
        )
        self.assertEqual(node.tenant_id, self.tenant.pk)

    def test_creating_via_the_orm_without_full_clean_still_gets_a_tenant(self):
        # Camino que se salta full_clean() a propósito (igual que algunas
        # pruebas de abajo) — save() debe ser la red de seguridad.
        node = OrganizationNode.objects.create(
            level=self.levels["empresa"],
            code="GPA-ORM-DIRECTO",
            name="Empresa creada sin full_clean",
        )
        self.assertEqual(node.tenant_id, self.tenant.pk)

    def test_parent_and_child_must_belong_to_the_same_tenant(self):
        company_node = self.create_valid_node(
            level_code="empresa",
            code="GPA-ROOT",
            name="Empresa Raíz",
        )
        other_tenant = Tenant.objects.create(code="OTRO", name="Otra organización (prueba)")
        node = OrganizationNode(
            tenant=other_tenant,
            level=self.levels["unidad_organizacional"],
            parent=company_node,
            code="UO-OTRO-TENANT",
            name="Unidad de otra organización",
        )

        self.assert_field_validation_error(node, "parent", "misma organización")

    def test_company_level_node_rejects_a_parent(self):
        existing_company = self.create_valid_node(
            level_code="empresa",
            code="GPA-ROOT",
            name="Empresa Raíz",
        )
        invalid_company = OrganizationNode(
            level=self.levels["empresa"],
            parent=existing_company,
            code="GPA-CHILD-COMPANY",
            name="Empresa con padre",
        )

        self.assert_field_validation_error(
            invalid_company,
            "parent",
            "Empresa no puede tener un nodo padre",
        )

    def test_non_company_level_requires_a_parent(self):
        node = OrganizationNode(
            level=self.levels["unidad_organizacional"],
            code="UO-SIN-PADRE",
            name="Unidad Organizacional sin padre",
        )

        self.assert_field_validation_error(
            node,
            "parent",
            "obligatorio para cualquier nivel distinto de Empresa",
        )

    def test_parent_level_number_must_be_lower_than_child_level(self):
        company_node = self.create_valid_node(
            level_code="empresa",
            code="GPA-ROOT",
            name="Empresa Raíz",
        )
        business_unit = self.create_valid_node(
            level_code="unidad_negocio",
            code="GPA-UN",
            name="Unidad de Negocio directa",
            parent=company_node,
        )

        # Una Unidad Organizacional (nivel 2) no puede colgar de una Unidad de
        # Negocio (nivel 3): el padre debe ser de número MENOR, y aquí es mayor.
        node = OrganizationNode(
            level=self.levels["unidad_organizacional"],
            parent=business_unit,
            code="UO-BAJO-UN",
            name="Unidad Organizacional mal ubicada",
        )

        with self.assertRaises(ValidationError) as context:
            node.full_clean()

        self.assertIn("parent", context.exception.message_dict)
        message = " ".join(context.exception.message_dict["parent"])
        self.assertIn("debe ser de un nivel superior", message)
        self.assertIn("«Unidad de Negocio», nivel 3", message)
        self.assertIn("«Unidad Organizacional», nivel 2", message)

    def test_non_recursive_level_cannot_be_parent_of_itself(self):
        company_node = self.create_valid_node(
            level_code="empresa",
            code="GPA-ROOT",
            name="Empresa Raíz",
        )
        org_unit = self.create_valid_node(
            level_code="unidad_organizacional",
            code="GPA-UO",
            name="Unidad Organizacional",
            parent=company_node,
        )

        node = OrganizationNode(
            level=self.levels["unidad_organizacional"],
            parent=org_unit,
            code="UO-BAJO-UO",
            name="Unidad Organizacional hija de otra",
        )

        self.assert_field_validation_error(
            node,
            "parent",
            "no puede colgar de otro nodo de su mismo nivel",
        )

    def test_recursive_level_can_nest_under_itself_indefinitely(self):
        # Reproduce el ejemplo real: Gerencia de Operaciones -> Departamento
        # de Producción -> Soldadura, las tres "Unidad de Negocio".
        _, _, management, department = self.create_recursive_business_unit_chain()
        welding = self.create_valid_node(
            level_code="unidad_negocio",
            code="GPA-AZM-SOLD",
            name="Soldadura",
            parent=department,
        )

        self.assertEqual(management.level.code, "unidad_negocio")
        self.assertEqual(department.level.code, "unidad_negocio")
        self.assertEqual(welding.level.code, "unidad_negocio")
        self.assertEqual(department.parent_id, management.pk)
        self.assertEqual(welding.parent_id, department.pk)

    def test_node_cannot_appear_in_its_own_ancestry(self):
        _, _, management, department = self.create_recursive_business_unit_chain()
        # Persiste una ascendencia inválida sin ejecutar full_clean() para
        # alcanzar específicamente la protección de ciclos.
        OrganizationNode.objects.filter(pk=management.pk).update(parent=department)
        department.parent = OrganizationNode.objects.get(pk=management.pk)

        self.assert_field_validation_error(
            department,
            "parent",
            "propia ascendencia",
        )

    def test_deleting_a_parent_with_a_child_is_protected(self):
        company_node = self.create_valid_node(
            level_code="empresa",
            code="GPA-ROOT",
            name="Empresa Raíz",
        )
        child = self.create_valid_node(
            level_code="unidad_organizacional",
            code="GPA-UO",
            name="Unidad Organizacional",
            parent=company_node,
        )

        with self.assertRaises(ProtectedError):
            company_node.delete()

        self.assertTrue(OrganizationNode.objects.filter(pk=company_node.pk).exists())
        self.assertTrue(OrganizationNode.objects.filter(pk=child.pk).exists())

    def test_company_accepts_only_an_empresa_node(self):
        company_node, _, _, department = self.create_recursive_business_unit_chain()
        valid_company = Company(
            organization_node=company_node,
            legal_name="Azimatronics, S.A. de C.V.",
            rfc="AZI010203AB1",
            employer_registration="Y54-12345-10-1",
        )
        valid_company.full_clean()
        valid_company.save()

        invalid_company = Company(
            organization_node=department,
            legal_name="Empresa inválida, S.A. de C.V.",
            rfc="INV010203AB1",
            employer_registration="Y54-99999-10-1",
        )
        self.assert_field_validation_error(
            invalid_company,
            "organization_node",
            "nivel Empresa",
        )

    def test_organization_code_is_manual_and_is_never_generated_from_name(self):
        node_without_code = OrganizationNode(
            level=self.levels["empresa"],
            code="",
            name="Nombre que no debe generar código",
        )

        with self.assertRaises(ValidationError) as context:
            node_without_code.full_clean()
        self.assertIn("code", context.exception.message_dict)
        self.assertEqual(node_without_code.code, "")

        # Model.save() must not contain the auto-slug behavior used by DocumentType.
        node_without_code.save()
        node_without_code.refresh_from_db()
        self.assertEqual(node_without_code.code, "")

        manual_node = self.create_valid_node(
            level_code="empresa",
            code="GPA-MANUAL-01",
            name="Nombre distinto al código",
        )
        manual_node.refresh_from_db()
        self.assertEqual(manual_node.code, "GPA-MANUAL-01")


class OrganizationDatabaseConstraintTests(OrganizationTestDataMixin, TestCase):
    def test_sibling_codes_are_unique_within_the_same_parent(self):
        company_node = self.create_valid_node(
            level_code="empresa",
            code="GPA-ROOT",
            name="Empresa Raíz",
        )
        self.create_valid_node(
            level_code="unidad_organizacional",
            code="UO-REPETIDA",
            name="Primera unidad",
            parent=company_node,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationNode.objects.create(
                level=self.levels["unidad_organizacional"],
                parent=company_node,
                code="UO-REPETIDA",
                name="Segunda unidad",
            )

    def test_same_node_code_is_allowed_under_different_parents(self):
        first_company = self.create_valid_node(
            level_code="empresa",
            code="GPA-ONE",
            name="Empresa Uno",
        )
        second_company = self.create_valid_node(
            level_code="empresa",
            code="GPA-TWO",
            name="Empresa Dos",
        )

        first_child = self.create_valid_node(
            level_code="unidad_organizacional",
            code="UO-COMPARTIDO",
            name="Unidad Uno",
            parent=first_company,
        )
        second_child = self.create_valid_node(
            level_code="unidad_organizacional",
            code="UO-COMPARTIDO",
            name="Unidad Dos",
            parent=second_company,
        )

        self.assertNotEqual(first_child.pk, second_child.pk)

    def test_level_number_and_code_are_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationalLevel.objects.create(
                numero=1,
                code="otro_codigo",
                name="Otro nivel",
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationalLevel.objects.create(
                numero=99,
                code="empresa",
                name="Otro nivel",
            )

    def test_company_node_is_one_to_one_and_rfc_is_unique(self):
        first_company_node = self.create_valid_node(
            level_code="empresa",
            code="GPA-ONE",
            name="Empresa Uno",
        )
        second_company_node = self.create_valid_node(
            level_code="empresa",
            code="GPA-TWO",
            name="Empresa Dos",
        )
        Company.objects.create(
            organization_node=first_company_node,
            legal_name="Empresa Uno, S.A. de C.V.",
            rfc="UNO010203AB1",
            employer_registration="REG-UNO",
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Company.objects.create(
                organization_node=first_company_node,
                legal_name="Otra razón social",
                rfc="DOS010203AB1",
                employer_registration="REG-DOS",
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            Company.objects.create(
                organization_node=second_company_node,
                legal_name="Empresa Dos, S.A. de C.V.",
                rfc="UNO010203AB1",
                employer_registration="REG-DOS",
            )


class OrganizationAdminConfigurationTests(TestCase):
    def test_all_phase_one_models_are_registered_with_icons(self):
        models = (
            Tenant,
            OrganizationalLevel,
            OrganizationNode,
            Company,
        )
        expected_icon_keys = {
            "organizations.tenant",
            "organizations.organizationallevel",
            "organizations.organizationnode",
            "organizations.company",
        }

        for model in models:
            with self.subTest(model=model.__name__):
                self.assertIn(model, admin.site._registry)
        self.assertTrue(
            expected_icon_keys.issubset(settings.JAZZMIN_SETTINGS["icons"])
        )

    def test_organization_node_admin_has_required_configuration(self):
        model_admin = admin.site._registry[OrganizationNode]

        self.assertIsInstance(model_admin, AuditableAdminMixin)
        self.assertEqual(
            list(model_admin.list_display),
            ["code", "name", "level", "tenant", "is_active"],
        )
        self.assertEqual(list(model_admin.list_filter), ["level", "is_active"])
        self.assertEqual(list(model_admin.autocomplete_fields), ["parent"])
        self.assertEqual(list(model_admin.readonly_fields), ["tenant"])
        self.assertEqual(
            list(model_admin.fields),
            ["tenant", "level", "parent", "code", "name", "is_active"],
        )

    def test_operational_admins_hide_technical_audit_fields(self):
        technical_fields = {
            "id",
            "created_at",
            "updated_at",
            "deleted_at",
            "is_deleted",
            "created_by",
            "updated_by",
            "deleted_by",
        }
        expected_business_fields = {
            OrganizationNode: {
                "tenant",
                "level",
                "parent",
                "code",
                "name",
                "is_active",
            },
            Company: {
                "organization_node",
                "legal_name",
                "rfc",
                "employer_registration",
            },
        }

        for model, business_fields in expected_business_fields.items():
            with self.subTest(model=model.__name__):
                model_admin = admin.site._registry[model]
                self.assertIsInstance(model_admin, AuditableAdminMixin)
                self.assertEqual(set(model_admin.fields), business_fields)
                self.assertFalse(set(model_admin.fields) & technical_fields)


class OrganizationAPITests(OrganizationTestDataMixin, APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("seed_user_roles", stdout=StringIO())
        capital_humano = UserRole.objects.get(code="capital-humano")

        user_model = get_user_model()
        # Estos dos representan a Capital Humano/Admin (acceso total de
        # lectura y escritura): las pruebas de este bloque son sobre CRUD y
        # auditoría, no sobre el alcance por rol — eso se cubre aparte en
        # OrganizationRolePermissionTests.
        cls.user = user_model.objects.create_user(
            username="organization-api-user",
            email="organization-api@example.com",
            password="strong-test-password",
            role=capital_humano,
        )
        cls.other_user = user_model.objects.create_user(
            username="organization-api-editor",
            email="organization-editor@example.com",
            password="strong-test-password",
            role=capital_humano,
        )

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.user)

    def test_all_organization_endpoints_require_authentication(self):
        self.client.force_authenticate(user=None)
        protected_urls = [
            reverse("tenant-list"),
            reverse("organizationallevel-list"),
            reverse("organizationnode-list"),
            reverse("company-list"),
        ]

        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_tenant_catalog_is_read_only_and_exposes_the_seeded_data(self):
        list_url = reverse("tenant-list")
        detail_url = reverse("tenant-detail", args=[self.tenant.pk])

        list_response = self.client.get(list_url)
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data["count"], 1)

        detail_response = self.client.get(detail_url)
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data["name"], "Grupo GPA")

        create_response = self.client.post(list_url, {}, format="json")
        self.assertEqual(
            create_response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def test_level_catalog_is_read_only_and_exposes_the_seeded_data(self):
        list_url = reverse("organizationallevel-list")
        detail_url = reverse(
            "organizationallevel-detail",
            args=[self.levels["empresa"].pk],
        )

        list_response = self.client.get(list_url)
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data["count"], 3)

        detail_response = self.client.get(detail_url)
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)

        create_response = self.client.post(list_url, {}, format="json")
        self.assertEqual(
            create_response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        for method_name in ("put", "patch", "delete"):
            response = getattr(self.client, method_name)(
                detail_url,
                {},
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_405_METHOD_NOT_ALLOWED,
            )

    def test_organization_node_crud_and_user_audit(self):
        list_url = reverse("organizationnode-list")
        create_response = self.client.post(
            list_url,
            {
                "level": self.levels["empresa"].pk,
                "parent": None,
                "code": "GPA-API",
                "name": "Empresa creada por API",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data["tenant"], self.tenant.pk)

        node = OrganizationNode.objects.get(pk=create_response.data["id"])
        self.assertEqual(node.tenant_id, self.tenant.pk)
        self.assertEqual(node.created_by, self.user)
        self.assertEqual(node.updated_by, self.user)
        self.assertEqual(node.code, "GPA-API")
        detail_url = reverse("organizationnode-detail", args=[node.pk])

        retrieve_response = self.client.get(detail_url)
        self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
        self.assertEqual(retrieve_response.data["name"], "Empresa creada por API")

        list_response = self.client.get(list_url)
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data["count"], 1)

        self.client.force_authenticate(user=self.other_user)
        update_response = self.client.patch(
            detail_url,
            {"name": "Empresa editada por API"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        node.refresh_from_db()
        self.assertEqual(node.name, "Empresa editada por API")
        self.assertEqual(node.created_by, self.user)
        self.assertEqual(node.updated_by, self.other_user)

        delete_response = self.client.delete(detail_url)
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(OrganizationNode.objects.filter(pk=node.pk).exists())

    def test_company_crud_and_user_audit(self):
        company_node = self.create_valid_node(
            level_code="empresa",
            code="GPA-COMPANY-API",
            name="Nodo Empresa API",
        )
        list_url = reverse("company-list")
        create_response = self.client.post(
            list_url,
            {
                "organization_node": str(company_node.pk),
                "legal_name": "Empresa API, S.A. de C.V.",
                "rfc": "EAP010203AB1",
                "employer_registration": "REG-API-01",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        company = Company.objects.get(pk=create_response.data["id"])
        self.assertEqual(company.created_by, self.user)
        self.assertEqual(company.updated_by, self.user)
        detail_url = reverse("company-detail", args=[company.pk])

        retrieve_response = self.client.get(detail_url)
        self.assertEqual(retrieve_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            retrieve_response.data["legal_name"],
            "Empresa API, S.A. de C.V.",
        )

        list_response = self.client.get(list_url)
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data["count"], 1)

        self.client.force_authenticate(user=self.other_user)
        update_response = self.client.patch(
            detail_url,
            {"employer_registration": "REG-API-EDITADO"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        company.refresh_from_db()
        self.assertEqual(company.employer_registration, "REG-API-EDITADO")
        self.assertEqual(company.created_by, self.user)
        self.assertEqual(company.updated_by, self.other_user)

        delete_response = self.client.delete(detail_url)
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Company.objects.filter(pk=company.pk).exists())

    def test_node_api_returns_400_for_an_invalid_numeric_level_order(self):
        company_node = self.create_valid_node(
            level_code="empresa",
            code="GPA-INVALID-ORDER",
            name="Empresa para orden inválido",
        )
        business_unit = self.create_valid_node(
            level_code="unidad_negocio",
            code="UN-PADRE",
            name="Unidad de Negocio padre",
            parent=company_node,
        )

        response = self.client.post(
            reverse("organizationnode-list"),
            {
                "level": self.levels["unidad_organizacional"].pk,
                "parent": str(business_unit.pk),
                "code": "UO-INVALIDA",
                "name": "Unidad Organizacional bajo Unidad de Negocio",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("parent", response.data)
        self.assertIn("debe ser de un nivel superior", str(response.data["parent"]))
        self.assertIn("«Unidad de Negocio», nivel 3", str(response.data["parent"]))
        self.assertIn("«Unidad Organizacional», nivel 2", str(response.data["parent"]))
        self.assertFalse(
            OrganizationNode.objects.filter(code="UO-INVALIDA").exists()
        )

    def test_node_api_rejects_same_level_parent_when_not_recursive(self):
        company_node = self.create_valid_node(
            level_code="empresa",
            code="GPA-NO-RECURSIVO",
            name="Empresa para nivel no recursivo",
        )
        org_unit = self.create_valid_node(
            level_code="unidad_organizacional",
            code="UO-PADRE",
            name="Unidad Organizacional padre",
            parent=company_node,
        )

        response = self.client.post(
            reverse("organizationnode-list"),
            {
                "level": self.levels["unidad_organizacional"].pk,
                "parent": str(org_unit.pk),
                "code": "UO-HIJA-INVALIDA",
                "name": "Unidad Organizacional hija inválida",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("no puede colgar de otro nodo de su mismo nivel", str(response.data["parent"]))

    def test_node_api_accepts_same_level_parent_when_recursive(self):
        company_node = self.create_valid_node(
            level_code="empresa",
            code="GPA-RECURSIVO",
            name="Empresa para nivel recursivo",
        )
        business_unit = self.create_valid_node(
            level_code="unidad_negocio",
            code="UN-PADRE-API",
            name="Gerencia de Operaciones",
            parent=company_node,
        )

        response = self.client.post(
            reverse("organizationnode-list"),
            {
                "level": self.levels["unidad_negocio"].pk,
                "parent": str(business_unit.pk),
                "code": "UN-HIJA-API",
                "name": "Departamento de Producción",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_company_api_returns_400_for_a_non_company_node(self):
        _, _, _, department = self.create_recursive_business_unit_chain()

        response = self.client.post(
            reverse("company-list"),
            {
                "organization_node": str(department.pk),
                "legal_name": "Empresa inválida, S.A. de C.V.",
                "rfc": "INV010203AB1",
                "employer_registration": "REG-INVALIDO",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("organization_node", response.data)
        self.assertIn("nivel Empresa", str(response.data["organization_node"]))
        self.assertFalse(Company.objects.filter(rfc="INV010203AB1").exists())


class OrganizationRolePermissionTests(OrganizationTestDataMixin, APITestCase):
    """
    OrganizationNode/Company son catálogos estructurales, no datos
    personales de nadie en particular: cualquier usuario autenticado los
    lee completos, pero solo Capital Humano/Admin puede escribir en ellos
    (ver apps.core.permissions.IsCapitalHumanoOrAdminOrReadOnly).
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("seed_user_roles", stdout=StringIO())
        user_model = get_user_model()
        cls.colaborador = user_model.objects.create_user(
            username="organization-role-colaborador",
            email="organization-role-colaborador@example.com",
            password="strong-test-password",
            role=UserRole.objects.get(code="colaborador"),
        )
        cls.company_node = cls.create_valid_node(
            level_code="empresa", code="GPA-ROLE-TEST", name="Empresa para pruebas de rol",
        )

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(user=self.colaborador)

    def test_colaborador_can_read_organization_nodes(self):
        response = self.client.get(reverse("organizationnode-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)

    def test_colaborador_cannot_create_organization_node(self):
        response = self.client.post(
            reverse("organizationnode-list"),
            {
                "level": self.levels["unidad_organizacional"].pk,
                "parent": str(self.company_node.pk),
                "code": "UO-COLABORADOR",
                "name": "Creada por un Colaborador",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(OrganizationNode.objects.filter(code="UO-COLABORADOR").exists())

    def test_colaborador_cannot_update_or_delete_organization_node(self):
        detail_url = reverse("organizationnode-detail", args=[self.company_node.pk])

        patch_response = self.client.patch(detail_url, {"name": "Nombre alterado"}, format="json")
        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)

        delete_response = self.client.delete(detail_url)
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN)

        self.company_node.refresh_from_db()
        self.assertEqual(self.company_node.name, "Empresa para pruebas de rol")

    def test_colaborador_cannot_create_company(self):
        response = self.client.post(
            reverse("company-list"),
            {
                "organization_node": str(self.company_node.pk),
                "legal_name": "Intento de Colaborador, S.A. de C.V.",
                "rfc": "COL010203AB1",
                "employer_registration": "REG-COLABORADOR",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Company.objects.filter(rfc="COL010203AB1").exists())
