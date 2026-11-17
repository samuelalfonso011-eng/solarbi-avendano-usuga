#!/usr/bin/env bash
# Pruebas unitarias + de integracion contra el PostgreSQL publicado en localhost:15432.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_entorno.sh
cargar_env .env
export PGHOST=localhost PGPORT="${PG_PUERTO_LOCAL:-15432}" PGDATABASE=microrred PGUSER=etl_app PGPASSWORD="$ETL_PASSWORD"
python -m pytest tests -v "$@"
