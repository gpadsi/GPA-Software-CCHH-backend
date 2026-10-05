#!/bin/sh
# entrypoint.sh — Capital Humano
# Se ejecuta en TODOS los contenedores (web + celery) antes del CMD.
# La variable APP_ROLE diferencia qué pasos extra corre cada uno.
#   web    → migrate + collectstatic + catálogos + superusuario + gunicorn/runserver
#   celery → espera a que web aplique las migraciones + celery worker
#
# IMPORTANTE: las migraciones las aplica EXCLUSIVAMENTE el rol web. celery solo
# ESPERA (migrate --check) a que el esquema esté al día antes de arrancar. Esto
# evita la condición de carrera de dos procesos corriendo `migrate` a la vez
# sobre una BD vacía (patrón adoptado de CIAgro, donde ese bug sí ocurrió).
#
# Cualquier paso que falle detiene el arranque con su error visible en
# `docker compose logs`: un contenedor que no arranca es preferible a uno que
# arranca con catálogos o roles a medias.
set -e

# `docker stop` manda SIGTERM a este script (PID 1) mientras espera en los
# bucles de abajo; sin trap, sh lo ignora y Docker lo mata a los 10 s.
trap 'exit 143' TERM INT

WAIT_TIMEOUT="${STARTUP_WAIT_TIMEOUT:-300}"

# wait_for <descripción> <comando...>
# Reintenta el comando cada 2 s. Si pasan WAIT_TIMEOUT segundos sin éxito,
# muestra la última salida del comando y aborta en lugar de esperar para siempre.
wait_for() {
    description="$1"
    shift
    elapsed=0
    while ! output=$("$@" 2>&1); do
        if [ "$elapsed" -ge "$WAIT_TIMEOUT" ]; then
            echo "!! Timeout de ${WAIT_TIMEOUT}s esperando: ${description}. Última salida:" >&2
            echo "$output" >&2
            exit 1
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
}

# ── 1. Esperar a que PostgreSQL esté listo ──────────────────────────────────
echo "==> [Capital Humano] Esperando base de datos en ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}..."
wait_for "PostgreSQL" pg_isready \
    -h "${POSTGRES_HOST:-db}" \
    -p "${POSTGRES_PORT:-5432}" \
    -U "${POSTGRES_USER:-ch_user}"
echo "    Base de datos lista."

# ── 2. Migraciones — SÓLO el rol web las aplica ─────────────────────────────
if [ "${APP_ROLE:-web}" = "web" ]; then
    echo "==> [web] Aplicando migraciones..."
    python manage.py migrate --no-input
else
    echo "==> [${APP_ROLE:-?}] Esperando a que web aplique las migraciones..."
    wait_for "migraciones aplicadas por web" python manage.py migrate --check
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

    # Catálogos base, todos idempotentes. El orden importa:
    # seed_gpa_companies necesita los niveles organizacionales,
    # seed_recruitment_catalogs usa TipoRequisicion de seed_position_catalogs, y
    # ensure_superuser (abajo) necesita los roles de usuario.
    # --skip-checks: `migrate` ya imprimió los warnings del system check una vez.
    for seed in \
        seed_document_types \
        seed_tenant \
        seed_organizational_levels \
        seed_gpa_companies \
        seed_user_roles \
        seed_persons_catalogs \
        seed_position_catalogs \
        seed_recruitment_catalogs \
        seed_baja_catalogs
    do
        echo "==> ${seed}"
        python manage.py "$seed" --skip-checks
    done

    echo "==> Verificando superusuario inicial..."
    python manage.py ensure_superuser --skip-checks

fi

# ── 4. Ejecutar el comando pasado al contenedor (CMD) ───────────────────────
echo "==> Iniciando: $*"
exec "$@"
