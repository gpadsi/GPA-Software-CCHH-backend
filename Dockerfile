# Dockerfile — Capital Humano
# Imagen base: Python 3.12 sobre Debian Bookworm slim.
# Sin GDAL/GEOS/PostGIS: este proyecto no tiene dominio geoespacial.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# postgresql-client: pg_isready (healthcheck en entrypoint) + manage.py dbshell.
# psycopg2-binary ya trae embebidas las librerías cliente de libpq, así que no
# hace falta libpq-dev aquí.
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencias Python — capa separada para aprovechar la cache de Docker.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código fuente
COPY . .

# Directorios que Django escribe en runtime (deben existir en la imagen)
RUN mkdir -p staticfiles media

# Entrypoint: espera BD + aplica migraciones + collectstatic + superusuario
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

# Producción: Gunicorn WSGI server.
# Dev: sobreescrito en docker-compose.dev.yml → runserver (hot-reload).
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
