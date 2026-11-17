# Imagen del ETL (Bronze SQLite -> Silver -> Gold en PostgreSQL)
#
# Base: python:3.12-slim-bookworm (~125 MB). Se descarto:
#   - python:3.12 completa (~1 GB): trae compiladores que el ETL no usa.
#   - alpine: psycopg[binary] publica ruedas manylinux (glibc); en musl habria que compilar.
# El ETL solo depende de la biblioteca estandar (sqlite3, json) y de psycopg: no se
# usa pandas, por eso la imagen final queda en torno a 150 MB.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY microrred_etl/ ./microrred_etl/

# Usuario sin privilegios: el contenedor solo lee Bronze y escribe por red en PostgreSQL
RUN useradd --uid 10001 --no-create-home etl
USER 10001

ENTRYPOINT ["python", "-m", "microrred_etl.main"]
