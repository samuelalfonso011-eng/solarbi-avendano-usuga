#!/usr/bin/env bash
# Ejecuta el ETL desde el anfitrion contra el PostgreSQL publicado en localhost
# (docker-compose o NodePort de Kubernetes, puerto 15432). Util para desarrollo.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_entorno.sh
cargar_env config/microrred.env
cargar_env .env
export PGHOST=localhost PGPORT="${PG_PUERTO_LOCAL:-15432}" PGUSER=etl_app PGPASSWORD="$ETL_PASSWORD"
export SQLITE_PATH="$PWD/data/bronze/opencem-v1.0.0.sqlite"
cd etl && python -m microrred_etl.main
