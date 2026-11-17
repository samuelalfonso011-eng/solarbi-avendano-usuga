#!/usr/bin/env bash
# Levanta la solucion completa desde cero sobre un cluster local de Kubernetes (kind).
#
#   bash scripts/up.sh            # ambiente demo (por defecto)
#   bash scripts/up.sh dev        # ambiente dev
#
# Pasos: 1) requisitos  2) datos Bronze  3) cluster  4) imagenes  5) Secret
#        6) kubectl apply -k  7) espera a que todo este sano  8) resumen
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_entorno.sh

AMBIENTE="${1:-demo}"
CLUSTER=microrred
NS=$([[ "$AMBIENTE" == "dev" ]] && echo microrred-dev || echo microrred-bi)
IMAGENES_PROPIAS=(microrred-etl:1.0.0 microrred-simulador:1.0.0)
IMAGENES_OFICIALES=(postgres:16.4-alpine grafana/grafana:11.4.0)
paso() { printf '\n\033[1;36m[%s] %s\033[0m\n' "$1" "$2"; }

paso 1/8 "Requisitos del anfitrion"
KIND="${KIND:-$(command -v kind || true)}"
[[ -z "$KIND" && -x tools/kind.exe ]] && KIND="tools/kind.exe"
[[ -z "$KIND" && -x tools/kind ]] && KIND="tools/kind"
for herramienta in docker kubectl python; do
  command -v "$herramienta" >/dev/null || { echo "Falta $herramienta en el PATH"; exit 1; }
done
[[ -n "$KIND" ]] || { echo "Falta kind: instalar (winget install Kubernetes.kind) o copiar el binario a tools/"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker no esta en ejecucion: abrir Docker Desktop"; exit 1; }
echo "docker $(docker version --format '{{.Server.Version}}') | $("$KIND" version | cut -d' ' -f1-2) | kubectl $(kubectl version --client -o json | python -c 'import json,sys; print(json.load(sys.stdin)["clientVersion"]["gitVersion"])')"

paso 2/8 "Capa Bronze (descarga verificada, solo si falta)"
if [[ ! -f data/bronze/opencem-v1.0.0.sqlite ]]; then
  python -m pip install -q zstandard
  python scripts/descargar_datos.py --destino data/bronze
fi
ls -l data/bronze/opencem-v1.0.0.sqlite | awk '{print $5, "bytes", $NF}'

paso 3/8 "Cluster kind '$CLUSTER'"
if "$KIND" get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  echo "ya existe"
else
  ruta_bronze="$(cd data/bronze && pwd)"
  command -v cygpath >/dev/null && ruta_bronze="$(cygpath -m "$ruta_bronze")"
  sed "s|__BRONZE_DIR__|$ruta_bronze|" k8s/kind-config.plantilla.yaml > k8s/kind-config.generado.yaml
  "$KIND" create cluster --config k8s/kind-config.generado.yaml --wait 120s
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null
kubectl get nodes

paso 4/8 "Imagenes: construir las propias y cargarlas al nodo"
docker build -q --provenance=false -t microrred-etl:1.0.0 etl
docker build -q --provenance=false -t microrred-simulador:1.0.0 simulador
for imagen in "${IMAGENES_OFICIALES[@]}"; do
  docker image inspect "$imagen" >/dev/null 2>&1 || docker pull -q "$imagen"
done
# kind no usa el registro local de Docker: las imagenes se copian al containerd del nodo.
# Se importa solo la plataforma del nodo: "kind load docker-image" usa --all-platforms y
# falla con el almacen de imagenes containerd de Docker Desktop (capas de otras
# plataformas ausentes en imagenes multi-arquitectura).
for imagen in "${IMAGENES_PROPIAS[@]}" "${IMAGENES_OFICIALES[@]}"; do
  docker save "$imagen" | docker exec --privileged -i "$CLUSTER-control-plane"     ctr --namespace=k8s.io images import --digests --snapshotter=overlayfs - >/dev/null
  echo "cargada en el nodo: $imagen"
done
docker exec "$CLUSTER-control-plane" crictl images | grep -E "microrred|postgres|grafana"

paso 5/8 "Namespace y Secret con las credenciales (desde .env, no versionado)"
bash scripts/generar_env.sh
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NS" create secret generic microrred-credenciales --from-env-file=.env \
  --dry-run=client -o yaml | kubectl apply -f -

paso 6/8 "Manifiestos (kustomize: k8s/overlays/$AMBIENTE)"
# Un Job terminado es inmutable: se elimina para poder volver a aplicar el manifiesto
kubectl -n "$NS" delete job etl-carga-historica --ignore-not-found >/dev/null
kubectl kustomize --load-restrictor LoadRestrictionsNone "k8s/overlays/$AMBIENTE" | kubectl apply -f -

paso 7/8 "Espera: PostgreSQL, Grafana y carga historica"
kubectl -n "$NS" rollout status statefulset/postgres --timeout=300s
kubectl -n "$NS" rollout status deployment/grafana --timeout=300s
echo "ETL en curso (Job etl-carga-historica)..."
estado_job=""
for _ in $(seq 1 300); do   # hasta 25 min; termina en cuanto el Job queda Complete o Failed
  estado_job="$(kubectl -n "$NS" get job etl-carga-historica     -o jsonpath='{range .status.conditions[?(@.status=="True")]}{.type}{" "}{end}')"
  [[ "$estado_job" == *Complete* || "$estado_job" == *Failed* ]] && break
  sleep 5
done
if [[ "$estado_job" != *Complete* ]]; then
  kubectl -n "$NS" logs job/etl-carga-historica --tail=40 || true
  echo "El ETL no termino correctamente (estado: ${estado_job:-sin terminar})"; exit 1
fi
kubectl -n "$NS" logs job/etl-carga-historica --tail=6

paso 8/8 "Resumen"
kubectl -n "$NS" get statefulset,deployment,job,cronjob,pvc,service
cargar_env .env
cat <<FIN

Solucion arriba en el namespace $NS.
  Grafana    : http://localhost:13000   (usuario: $GF_SECURITY_ADMIN_USER, clave: GF_SECURITY_ADMIN_PASSWORD en .env)
  PostgreSQL : localhost:15432  base microrred  usuario bi_lectura (clave: BI_PASSWORD en .env)
  Eliminar   : bash scripts/down.sh
FIN
