from django.urls import path
from drf_spectacular.utils import extend_schema
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.users.views import MeView

urlpatterns = [
    path(
        "auth/login/",
        extend_schema(tags=["auth"], summary="Login (JWT)")(TokenObtainPairView).as_view(),
        name="token_obtain_pair",
    ),
    path(
        "auth/refresh/",
        extend_schema(tags=["auth"], summary="Renovar access token")(TokenRefreshView).as_view(),
        name="token_refresh",
    ),
    path("users/me/", MeView.as_view(), name="user-me"),
]
