# Capital Humano

Backend del sistema de Capital Humano. Django + DRF + PostgreSQL + Redis + Celery, en Docker.

## Stack

- **Django 5** + **Django REST Framework** — API REST.
- **PostgreSQL 16** (sin PostGIS — este proyecto no tiene dominio geoespacial).
- **Redis** — broker de Celery + cache de DRF.
- **Celery** — tareas asíncronas (ej. importación masiva de datos desde Excel/CSV).
- **JWT** (`djangorestframework-simplejwt`) — autenticación.
- **drf-spectacular** — documentación OpenAPI 3.0 (Swagger / ReDoc).
- **Docker Compose** — orquestación de contenedores (`db`, `redis`, `web`, `celery`, y `nginx` en producción).

## Arranque en desarrollo

```bash
cp .env.example .env    # ajustar valores si hace falta, los defaults ya sirven para local
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

- API: `http://localhost:8000/api/v1/`
- Admin: `http://localhost:8000/admin/` (usuario/clave definidos en `.env`)
- Swagger UI: `http://localhost:8000/api/docs/`
- ReDoc: `http://localhost:8000/api/redoc/`

Bajar el stack (conserva los datos en el volumen `postgres_data`):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

## Arranque en producción (servidor dedicado)

```bash
cp .env.example .env    # editar: SECRET_KEY real, contraseñas fuertes, dominios, DJANGO_SETTINGS_MODULE=config.settings.prod
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Requiere HTTPS habilitado en `nginx/capital_humano.conf` — `config.settings.prod` fuerza cookies seguras (el login no funciona sin TLS).

## Cómo arranca cada contenedor (`entrypoint.sh`)

1. Espera a que PostgreSQL responda (`pg_isready`).
2. **Migraciones: solo el rol `web` las aplica.** El rol `celery` espera con `migrate --check` a que el esquema esté al día antes de arrancar — evita que dos procesos corran `migrate` a la vez sobre una BD vacía.
3. Solo en `web`: `collectstatic` (excepto en dev, donde `runserver` sirve estáticos vía finders) y verificación/creación del superusuario inicial.

El rol se fija con la variable `APP_ROLE` (`web` / `celery`) en los `docker-compose.*.yml`.

## Estructura del proyecto

```
capital-humano/
├── config/
│   ├── settings/
│   │   ├── base.py        # Configuración común (apps, DRF, Celery, Spectacular)
│   │   ├── dev.py         # Entorno local (DEBUG=True)
│   │   └── prod.py        # Producción (CORS, HTTPS)
│   ├── urls.py
│   └── celery.py
├── apps/
│   ├── core/               # BaseAuditModel, Attachment genérico, paginación
│   └── users/              # Identidad de acceso (User, JWT, /users/me/)
├── nginx/                  # Reverse proxy (solo producción)
├── Dockerfile
├── entrypoint.sh
├── docker-compose.yml       # Base: db + redis + web + celery
├── docker-compose.dev.yml   # Override desarrollo (runserver, hot-reload)
├── docker-compose.prod.yml  # Override producción (+ nginx)
└── requirements.txt
```

## Decisiones de arquitectura

- **`BaseAuditModel`** (`apps/core/models.py`): toda entidad operativa hereda UUID como PK, `created_at/updated_at`, soft delete (`is_deleted/deleted_at/deleted_by`) y auditoría de usuario (`created_by/updated_by/deleted_by`).
- **Sin PostGIS**: motor de BD plano (`django.db.backends.postgresql`); no hay dominio geoespacial en este proyecto.
- **Sin enumeradores**: los valores controlados (estatus, catálogos, tipos) viven en tablas propias, no en `TextChoices`/enums de base de datos — se pueden filtrar y extender sin migración.
- **Arquitectura hexagonal solo donde rinde**: cada app aísla su lógica de negocio en una capa de servicios; puertos-y-adaptadores estrictos se reservan para los módulos con reglas de negocio complejas que necesiten probarse sin tocar la BD (ej. cálculo de nómina, resolución de jerarquía/permisos).
- **`users` vs. el futuro módulo de personas**: `User` es "puede iniciar sesión"; el modelo de RRHH (Persona/Empleado/Contrato) es un dominio aparte que se conectará con `User` más adelante.
