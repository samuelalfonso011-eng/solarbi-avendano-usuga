# Imagen del simulador de streaming (un solo script + psycopg).
# Misma base que el ETL (python:3.12-slim-bookworm) para compartir capas en el nodo:
# la segunda imagen casi no ocupa espacio adicional.
FROM python:3.12-slim-bookworm

ARG VERSION=1.0.0
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SIM_VERSION=${VERSION}

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY simular.py .

RUN useradd --uid 10001 --no-create-home sim
USER 10001

ENTRYPOINT ["python", "simular.py"]
