#!/bin/sh
# entrypoint.sh — Capital Humano
# Se ejecuta en TODOS los contenedores (web + celery) antes del CMD.
# La variable APP_ROLE diferencia qué pasos extra corre cada uno.
#   web    → migrate + collectstatic + superusuario + gunicorn/runserver
#   celery → espera a que web aplique las migraciones + celery worker
#
# IMPORTANTE: las migraciones las aplica EXCLUSIVAMENTE el rol web. celery solo
# ESPERA (migrate --check) a que el esquema esté al día antes de arrancar. Esto
# evita la condición de carrera de dos procesos corriendo `migrate` a la vez
# sobre una BD vacía (patrón adoptado de CIAgro, donde ese bug sí ocurrió).
set -e

# ── 1. Esperar a que PostgreSQL esté listo ──────────────────────────────────
echo "==> [Capital Humano] Esperando base de datos en ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}..."
until pg_isready \
    -h "${POSTGRES_HOST:-db}" \
    -p "${POSTGRES_PORT:-5432}" \
    -U "${POSTGRES_USER:-ch_user}" \
    -q; do
    sleep 2
done
echo "    Base de datos lista."

# ── 2. Migraciones — SÓLO el rol web las aplica ─────────────────────────────
if [ "${APP_ROLE:-web}" = "web" ]; then
    echo "==> [web] Aplicando migraciones..."
    python manage.py migrate --no-input
else
    echo "==> [${APP_ROLE:-?}] Esperando a que web aplique las migraciones..."
    until python manage.py migrate --check >/dev/null 2>&1; do
        sleep 2
    done
    echo "    Esquema al día."
fi

# ── 3. Pasos exclusivos del servicio web ────────────────────────────────────
if [ "${APP_ROLE:-web}" = "web" ]; then

    case "${DJANGO_SETTINGS_MODULE}" in
        *.dev)
            echo "==> [dev] Omito collectstatic (runserver sirve estáticos vía finders)."
            ;;
        *)
            echo "==> Recolectando archivos estáticos..."
            python manage.py collectstatic --no-input
            ;;
    esac

    echo "==> Sembrando catálogo de tipos de documento..."
    python manage.py seed_document_types 2>/dev/null || true

    echo "==> Sembrando organización (Tenant)..."
    python manage.py seed_tenant 2>/dev/null || true

    echo "==> Sembrando niveles organizacionales..."
    python manage.py seed_organizational_levels 2>/dev/null || true

    echo "==> Sembrando empresas y unidades de negocio de Grupo GPA..."
    python manage.py seed_gpa_companies 2>/dev/null || true

    echo "==> Sembrando catálogos de Persona..."
    python manage.py seed_persons_catalogs 2>/dev/null || true

    echo "==> Sembrando catálogos de Posición..."
    python manage.py seed_position_catalogs 2>/dev/null || true

    echo "==> Sembrando catálogos de Origen/Causa de baja..."
    python manage.py seed_baja_catalogs 2>/dev/null || true

    echo "==> Verificando superusuario inicial..."
    python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
username = '${DJANGO_SUPERUSER_USERNAME:-admin}'
user = User.objects.filter(username=username).first()
if user is None:
    User.objects.create_superuser(
        username,
        '${DJANGO_SUPERUSER_EMAIL:-admin@capitalhumano.local}',
        '${DJANGO_SUPERUSER_PASSWORD:-admin}'
    )
    print(f'  Superusuario creado: {username}')
else:
    print(f'  Superusuario ya existe: {username}')
" 2>/dev/null || true

fi

# ── 4. Ejecutar el comando pasado al contenedor (CMD) ───────────────────────
echo "==> Iniciando: $*"
exec "$@"
