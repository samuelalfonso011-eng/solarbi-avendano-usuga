#!/usr/bin/env bash
# Aplica un cambio de configuracion (config/microrred.env, tablero o reglas de Grafana)
# SIN reconstruir imagenes y sin volver a ejecutar la carga historica.
#   bash scripts/aplicar_config.sh [demo|dev]
# El ConfigMap cambia de nombre (sufijo con hash): Grafana se reinicia solo y la
# siguiente pasada del simulador ya usa los valores nuevos.
set -euo pipefail
cd "$(dirname "$0")/.."
AMBIENTE="${1:-demo}"
NS=$([[ "$AMBIENTE" == "dev" ]] && echo microrred-dev || echo microrred-bi)
kubectl kustomize --load-restrictor LoadRestrictionsNone "k8s/overlays/$AMBIENTE" \
  | kubectl apply -f - -l 'app!=etl'      # el Job del ETL es inmutable y no se toca
kubectl -n "$NS" rollout status deployment/grafana --timeout=180s
