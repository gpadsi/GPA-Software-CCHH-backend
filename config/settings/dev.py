# config/settings/dev.py
# Configuración de DESARROLLO. Extiende base.py.
# Uso: DJANGO_SETTINGS_MODULE=config.settings.dev

from .base import *  # noqa: F401,F403

DEBUG = True

# Hosts base + extra desde el entorno (DJANGO_ALLOWED_HOSTS, separados por coma).
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"] + [
    h for h in config("DJANGO_ALLOWED_HOSTS", default="").split(",")
    if h and h not in ("localhost", "127.0.0.1", "0.0.0.0")
]

# --- CORS (desarrollo) ---
# Permite requests desde cualquier origen (Flutter web en localhost, Swagger, etc).
# NUNCA usar en producción — en prod.py se restringe a CORS_ALLOWED_ORIGINS.
CORS_ALLOW_ALL_ORIGINS = True

# --- BD: PostgreSQL (sin PostGIS — este proyecto no tiene dominio geoespacial) ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("POSTGRES_DB", default="capital_humano_db"),
        "USER": config("POSTGRES_USER", default="ch_user"),
        "PASSWORD": config("POSTGRES_PASSWORD", default="ch_password"),
        "HOST": config("POSTGRES_HOST", default="localhost"),
        "PORT": config("POSTGRES_PORT", default="5432"),
    }
}
