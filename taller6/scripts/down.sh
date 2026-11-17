#!/usr/bin/env bash
# Elimina la solucion.
#   bash scripts/down.sh             # borra el cluster kind completo (incluye los datos de PostgreSQL)
#   bash scripts/down.sh recursos    # borra solo el namespace y deja el cluster
set -euo pipefail
cd "$(dirname "$0")/.."
CLUSTER=microrred
KIND="${KIND:-$(command -v kind || true)}"
[[ -z "$KIND" && -x tools/kind.exe ]] && KIND="tools/kind.exe"
[[ -z "$KIND" && -x tools/kind ]] && KIND="tools/kind"

if [[ "${1:-cluster}" == "recursos" ]]; then
  kubectl --context "kind-$CLUSTER" delete namespace microrred-bi microrred-dev --ignore-not-found
else
  "$KIND" delete cluster --name "$CLUSTER"
fi
echo "Solucion eliminada."
