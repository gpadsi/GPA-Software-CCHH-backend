from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions

from apps.users.serializers import UserSerializer


@extend_schema(
    tags=["users"],
    summary="Usuario autenticado",
    description="Retorna los datos del usuario dueño del token JWT enviado.",
)
class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user
