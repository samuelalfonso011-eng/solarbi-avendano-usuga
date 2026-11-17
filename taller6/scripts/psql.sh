#!/usr/bin/env bash
# psql dentro del contenedor/pod de PostgreSQL (no requiere cliente en el anfitrion).
#   bash scripts/psql.sh compose -c "SELECT 1"      |  bash scripts/psql.sh k8s -f - < archivo.sql
set -euo pipefail
cd "$(dirname "$0")/.."
destino="$1"; shift
if [[ "$destino" == "compose" ]]; then
  docker compose exec -T postgres psql -U postgres -d microrred -v ON_ERROR_STOP=1 "$@"
else
  kubectl -n "${NAMESPACE:-microrred-bi}" exec -i postgres-0 -- psql -U postgres -d microrred -v ON_ERROR_STOP=1 "$@"
fi
