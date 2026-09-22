from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.users.models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ["username"]


# Outstanding/Blacklisted tokens: bitácora interna de simplejwt para el
# logout real y la rotación de refresh tokens (ver SIMPLE_JWT en
# config/settings/base.py). Nadie los edita a mano, así que se sacan del
# admin — la función de blacklist sigue funcionando exactamente igual, solo
# deja de aparecer en el menú.
for _model in (OutstandingToken, BlacklistedToken):
    if admin.site.is_registered(_model):
        admin.site.unregister(_model)
