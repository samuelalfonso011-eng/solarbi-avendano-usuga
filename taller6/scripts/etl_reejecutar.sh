#!/usr/bin/env bash
# Vuelve a ejecutar la carga historica en el cluster (demuestra la idempotencia).
set -euo pipefail
cd "$(dirname "$0")/.."
NS="${NAMESPACE:-microrred-bi}"
AMBIENTE=$([[ "$NS" == "microrred-dev" ]] && echo dev || echo demo)
kubectl -n "$NS" delete job etl-carga-historica --ignore-not-found
kubectl kustomize --load-restrictor LoadRestrictionsNone "k8s/overlays/$AMBIENTE" | kubectl apply -f - | grep -E "job|configured" || true
kubectl -n "$NS" wait --for=condition=complete job/etl-carga-historica --timeout=900s
kubectl -n "$NS" logs job/etl-carga-historica --tail=5
