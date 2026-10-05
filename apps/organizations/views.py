from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import permissions, viewsets

from apps.core.permissions import IsCapitalHumanoOrAdminOrReadOnly
from apps.organizations.models import (
    Company,
    OrganizationalLevel,
    OrganizationNode,
    Tenant,
)
from apps.organizations.serializers import (
    CompanySerializer,
    OrganizationalLevelSerializer,
    OrganizationNodeSerializer,
    TenantSerializer,
)


@extend_schema_view(
    list=extend_schema(tags=["organizations"]),
    retrieve=extend_schema(tags=["organizations"]),
)
class TenantViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Tenant.objects.all()
    serializer_class = TenantSerializer
    permission_classes = [permissions.IsAuthenticated]


@extend_schema_view(
    list=extend_schema(tags=["organizations"]),
    retrieve=extend_schema(tags=["organizations"]),
)
class OrganizationalLevelViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = OrganizationalLevel.objects.all()
    serializer_class = OrganizationalLevelSerializer
    permission_classes = [permissions.IsAuthenticated]


@extend_schema_view(
    list=extend_schema(tags=["organizations"]),
    retrieve=extend_schema(tags=["organizations"]),
    create=extend_schema(tags=["organizations"]),
    update=extend_schema(tags=["organizations"]),
    partial_update=extend_schema(tags=["organizations"]),
    destroy=extend_schema(tags=["organizations"]),
)
class OrganizationNodeViewSet(viewsets.ModelViewSet):
    queryset = OrganizationNode.objects.order_by("pk")
    serializer_class = OrganizationNodeSerializer
    permission_classes = [IsCapitalHumanoOrAdminOrReadOnly]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


@extend_schema_view(
    list=extend_schema(tags=["organizations"]),
    retrieve=extend_schema(tags=["organizations"]),
    create=extend_schema(tags=["organizations"]),
    update=extend_schema(tags=["organizations"]),
    partial_update=extend_schema(tags=["organizations"]),
    destroy=extend_schema(tags=["organizations"]),
)
class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.order_by("pk")
    serializer_class = CompanySerializer
    permission_classes = [IsCapitalHumanoOrAdminOrReadOnly]
    search_fields = ["organization_node__name", "legal_name", "rfc", "employer_registration"]
    ordering_fields = ["organization_node__name", "legal_name", "rfc", "employer_registration"]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
