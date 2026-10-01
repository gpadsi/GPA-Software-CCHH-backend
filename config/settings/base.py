# config/settings/base.py
# Configuración común a todos los entornos (dev, prod).

from datetime import timedelta
from pathlib import Path

from decouple import config

# BASE_DIR apunta a la raíz del proyecto (2 niveles arriba de settings/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# --- Seguridad ---
SECRET_KEY = config("DJANGO_SECRET_KEY", default="django-insecure-dev-key-cambiar-en-prod")

# --- Apps ---
DJANGO_APPS = [
    "jazzmin",                 # ANTES de django.contrib.admin (reemplaza templates admin)
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",                              # Django REST Framework
    "rest_framework_simplejwt.token_blacklist",    # Logout real: invalida refresh tokens
    "django_filters",                              # Filtrado en API
    "drf_spectacular",                             # Documentación OpenAPI 3.0
    "corsheaders",                                 # CORS headers para el frontend Flutter
]

LOCAL_APPS = [
    "apps.core",
    "apps.users",
    "apps.organizations",
    "apps.locations",
    "apps.persons",
    "apps.positions",
    "apps.employment",
    "apps.schedules",
    "apps.imports",
    "apps.recruitment",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# --- Middleware ---
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",        # ← ANTES de CommonMiddleware (requerido)
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# --- URLs y Templates ---
ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Validación de passwords ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Custom User Model ---
# IMPORTANTE: definido ANTES de la primera migración (retroceder esto después
# de que exista una BD real es doloroso). apps.users.User extiende AbstractUser.
AUTH_USER_MODEL = "users.User"

# --- Internacionalización ---
LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True

# --- Archivos estáticos ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Archivos de media (uploads de usuarios) ---
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# --- PK por defecto ---
# BigAutoField para catálogos/tablas auxiliares sin UUID explícito.
# Las entidades operativas usan UUID definido manualmente en BaseAuditModel.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- DRF ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# --- drf-spectacular (OpenAPI 3.0) ---
# TAGS y x-tagGroups se van agregando aquí conforme se creen las apps de
# dominio (mismo patrón que se usó de referencia: cada app de negocio suma su
# propio tag con descripción, en vez de dejar que Swagger las agrupe solo).
SPECTACULAR_SETTINGS = {
    "TITLE": "Capital Humano API",
    "DESCRIPTION": "API REST del sistema de Capital Humano.",
    "VERSION": "0.1.0",
    "CONTACT": {"name": "Capital Humano"},
    "LICENSE": {"name": "Privado"},
    "TAGS": [
        {
            "name": "auth",
            "description": "**Autenticación y sesión** — Obtención y renovación de tokens JWT.",
        },
        {
            "name": "users",
            "description": "**Usuarios** — Cuenta de acceso al sistema y perfil autenticado.",
        },
        {
            "name": "core",
            "description": "**Utilidades del sistema** — Archivos adjuntos genéricos, reutilizables por cualquier entidad.",
        },
        {
            "name": "organizations",
            "description": "**Estructura organizacional** — Niveles, nodos y empresas de Grupo GPA.",
        },
        {
            "name": "locations",
            "description": "**Ubicaciones físicas** — Sitios, naves y áreas; dimensión física, independiente del organigrama.",
        },
        {
            "name": "persons",
            "description": "**Personas** — Datos personales, contactos de urgencia y perfil médico, independientes de la relación laboral.",
        },
        {
            "name": "positions",
            "description": "**Posiciones** — Plazas (vacantes u ocupadas) dentro de la estructura, con su ciclo de reclutamiento.",
        },
        {
            "name": "employment",
            "description": "**Empleo** — Relación laboral: Empleado, historial de contratos y bajas, historial salarial.",
        },
        {
            "name": "schedules",
            "description": "**Horarios y catorcenas** — Periodo de nómina, tipos de horario, y su asignación por Empleado a lo largo del tiempo.",
        },
    ],
    "SORT_OPERATIONS": False,
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_GENERATE_CHOICE_DESCRIPTION": True,
    "SWAGGER_UI_SETTINGS": {
        "persistAuthorization": True,
        "filter": True,
        "defaultModelsExpandDepth": 2,
        "defaultModelExpandDepth": 2,
    },
    "SECURITY": [{"BearerAuth": []}],
    "COMPONENTS": {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        }
    },
}

# --- JWT ---
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# --- Celery ---
CELERY_BROKER_URL = config("REDIS_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"

# --- Cache ---
# Redis db 1 (Celery usa db 0), para que el throttle/cache de DRF tenga un
# contador único compartido entre los workers de Gunicorn, no uno por proceso.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": config("REDIS_URL", default="redis://localhost:6379/0").rsplit("/", 1)[0] + "/1",
    }
}

# --- Jazzmin (admin branding) ---
JAZZMIN_SETTINGS = {
    "site_title": "Capital Humano Admin",
    "site_header": "Capital Humano",
    "site_brand": "Capital Humano",
    "welcome_sign": "Bienvenido al panel de administración de Capital Humano",
    "copyright": "Capital Humano",
    # "users.User" y no "auth.User": AUTH_USER_MODEL está swapeado a nuestro
    # modelo custom, y Jazzmin no puede resolver permisos/búsqueda contra el
    # modelo auth.User original (nunca se registra una tabla para él).
    "search_model": ["users.User"],
    "topmenu_links": [
        {"name": "Inicio", "url": "admin:index", "permissions": ["users.view_user"]},
        {"name": "API Docs", "url": "/api/docs/", "new_window": True},
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    # Orden de las secciones en el sidebar — se va ampliando conforme se
    # agreguen apps de dominio (Persona, Puesto, ...).
    "order_with_respect_to": [
        "users", "persons", "employment", "schedules", "positions", "locations",
        "organizations", "core", "imports", "auth",
    ],
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.group": "fas fa-users",
        "users.user": "fas fa-user",
        "users.userrole": "fas fa-user-tag",
        "organizations": "fas fa-sitemap",
        "organizations.tenant": "fas fa-building-flag",
        "organizations.organizationallevel": "fas fa-layer-group",
        "organizations.organizationnode": "fas fa-sitemap",
        "organizations.company": "fas fa-industry",
        "core.attachment": "fas fa-paperclip",
        "core.documenttype": "fas fa-tags",
        "locations.ubicacion": "fas fa-map-marker-alt",
        "locations.nave": "fas fa-warehouse",
        "locations.area": "fas fa-th-large",
        "persons.persona": "fas fa-id-card",
        "persons.contactourgencia": "fas fa-phone-volume",
        "persons.perfilmedico": "fas fa-notes-medical",
        "persons.genero": "fas fa-venus-mars",
        "persons.estadocivil": "fas fa-ring",
        "persons.escolaridad": "fas fa-graduation-cap",
        "persons.tiposangre": "fas fa-tint",
        "positions.posicion": "fas fa-briefcase",
        "positions.puesto": "fas fa-id-badge",
        "positions.alcancedeposicion": "fas fa-bullseye",
        "positions.tipoposicion": "fas fa-clipboard-list",
        "positions.tiporequisicion": "fas fa-file-signature",
        "positions.estatusposicion": "fas fa-toggle-on",
        "positions.historialreportaa": "fas fa-history",
        "employment.empleado": "fas fa-user-tie",
        "employment.contrato": "fas fa-file-contract",
        "employment.historialsalarial": "fas fa-money-check-alt",
        "employment.origenbaja": "fas fa-sign-out-alt",
        "employment.causabaja": "fas fa-list-ul",
        "imports.importbatch": "fas fa-file-import",
        "imports.posicionrawrow": "fas fa-table",
        "imports.colaboradorrawrow": "fas fa-table",
        "imports.horariorawrow": "fas fa-table",
        "imports.rawvaluealias": "fas fa-random",
        "schedules.catorcena": "fas fa-calendar-week",
        "schedules.tipohorario": "fas fa-clock",
        "schedules.asignacionubicacion": "fas fa-map-marked-alt",
        "schedules.asignacionhorario": "fas fa-business-time",
    },
    "default_icon_parents": "fas fa-chevron-circle-right",
    "default_icon_children": "fas fa-circle",
    "related_modal_active": False,
    "use_google_fonts_cdn": True,
    "show_ui_builder": False,
    "changeform_format": "horizontal_tabs",
    # Recuerda la posición de scroll del menú lateral entre una página y otra
    # (Django admin recarga la página completa en cada navegación).
    "custom_js": "core/js/sidebar-scroll.js",
}
