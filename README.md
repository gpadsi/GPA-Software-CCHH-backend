# Capital Humano

Backend del sistema de Capital Humano. Django + DRF + PostgreSQL + Redis + Celery, en Docker.

## Stack

- **Django 5** + **Django REST Framework** — API REST.
- **PostgreSQL 16** — base de datos.
- **Redis** — broker de Celery + cache de DRF.
- **Celery** — tareas asíncronas (ej. importación masiva de datos desde Excel/CSV).
- **JWT** (`djangorestframework-simplejwt`) — autenticación.
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
2. **Migraciones: solo el rol `web` las aplica.** El rol `celery` espera con `migrate --check` a que el esquema esté al día antes de arrancar.
3. Solo en `web`: `collectstatic` (excepto en dev, donde `runserver` sirve estáticos vía finders), los `seed_*` de catálogos base (incluidos los roles de usuario) y `ensure_superuser`.

`ensure_superuser` crea el superusuario de `DJANGO_SUPERUSER_*` con rol **Admin** (los permisos de la API se deciden por rol, no por `is_superuser`). Si ya existe y no tiene rol, le asigna Admin; no cambia su contraseña. No lo crea si `DJANGO_SUPERUSER_PASSWORD` está vacío, ni fuera de dev si sigue con el valor de ejemplo de `.env.example`.

Las esperas de los pasos 1 y 2 abortan tras `STARTUP_WAIT_TIMEOUT` segundos (300 por defecto) mostrando el último error. Cualquier paso que falle detiene el contenedor con el error en `docker compose logs`.

El rol se fija con la variable `APP_ROLE` (`web` / `celery`) en los `docker-compose.*.yml`. `entrypoint.sh` se copia a la imagen en el build (no entra por el bind mount de dev): tras editarlo hay que reconstruir con `--build`.

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
│   ├── core/            # Modelos y utilidades compartidas: auditoría, catálogos base, adjuntos, permisos por rol
│   ├── users/           # Identidad de acceso: User, roles (Colaborador/Capital Humano/Admin), JWT, /users/me/
│   ├── organizations/   # Estructura organizacional: niveles, nodos del árbol, empresas
│   ├── locations/       # Ubicación física: ubicaciones, naves, áreas
│   ├── persons/         # Datos personales: personas, contacto de urgencia, perfil médico
│   ├── positions/       # Posiciones/plazas, línea de reporte, catálogo de puestos
│   ├── employment/      # Relación laboral: empleados, contratos, historial salarial
│   ├── schedules/       # Catorcenas, tipos de horario, asignaciones de horario/ubicación
│   └── imports/         # Importación masiva de datos desde Excel/CSV
├── nginx/                  # Reverse proxy (solo producción)
├── Dockerfile
├── entrypoint.sh
├── docker-compose.yml       # Base: db + redis + web + celery
├── docker-compose.dev.yml   # Override desarrollo (runserver, hot-reload)
├── docker-compose.prod.yml  # Override producción (+ nginx)
└── requirements.txt
```

Cada app sigue la misma forma: `models.py`, `serializers.py`, `views.py`, `urls.py`, `tests.py`. Las rutas de cada app se montan bajo su propio prefijo en `/api/v1/` (ej. `positions/posiciones/`, `employment/empleados/`) — el esquema completo y navegable vive en `/api/docs/`.

## Pruebas y validaciones

```bash
docker compose exec web python manage.py test          # suite completa
docker compose exec web python manage.py check         # revisiones de Django (incluye advertencias de campos temporalmente opcionales, ver abajo)
docker compose exec web python manage.py makemigrations --check --dry-run   # confirma que no falten migraciones
```

Estos tres comandos son exactamente los que corre el workflow de CI (`.github/workflows/ci.yml`) en cada push y cada pull request a `main`.

Algunos campos del modelo aceptan `NULL` de forma temporal mientras se completa la captura de datos reales de personal — están documentados y listados en `apps/core/checks.py`, y `manage.py check` los recuerda en cada corrida hasta que se resuelvan.
