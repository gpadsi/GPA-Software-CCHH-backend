# config/settings/prod.py
# Configuración de PRODUCCIÓN. Extiende base.py.
# Uso: DJANGO_SETTINGS_MODULE=config.settings.prod

from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="").split(",")

# --- BD: PostgreSQL en servidor de producción ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("POSTGRES_DB"),
        "USER": config("POSTGRES_USER"),
        "PASSWORD": config("POSTGRES_PASSWORD"),
        "HOST": config("POSTGRES_HOST"),
        "PORT": config("POSTGRES_PORT", default="5432"),
    }
}

# --- Seguridad adicional ---
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

# nginx ya redirige 80→443 (ver nginx/capital_humano.conf), pero Django
# también lo fuerza a nivel de aplicación: no depende de que nadie se acuerde
# de habilitar ese bloque en nginx. SECURE_PROXY_SSL_HEADER (abajo) es lo que
# le permite a Django saber que la conexión SÍ es https aunque le llegue por
# HTTP plano desde el proxy, así que no genera un loop de redirección.
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000  # 1 año
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# --- CORS (producción, solo orígenes autorizados) ---
# Filtrado de vacíos: con CORS_ALLOWED_ORIGINS="" un simple .split(",") deja
# [""] en vez de [], y corsheaders lo rechaza (corsheaders.E013).
CORS_ALLOWED_ORIGINS = [
    o for o in config("CORS_ALLOWED_ORIGINS", default="").split(",") if o
]

# --- CSRF Trusted Origins (requerido Django 4+) ---
CSRF_TRUSTED_ORIGINS = [
    o for o in config(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        default=",".join(CORS_ALLOWED_ORIGINS),
    ).split(",") if o
]

# --- Proxy HTTPS (nginx termina SSL) ---
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CORS_ALLOW_CREDENTIALS = True
