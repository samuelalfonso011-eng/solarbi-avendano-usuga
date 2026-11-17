#!/usr/bin/env bash
# Demostraciones de la seccion K.4 y de la seccion H (alerta que reacciona).
#   bash scripts/demo_resiliencia.sh [postgres|grafana|alerta|escalar|rolling|evidencia|todo]
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_entorno.sh
cargar_env .env
NS="${NAMESPACE:-microrred-bi}"
GRAFANA="http://localhost:${GRAFANA_PUERTO_LOCAL:-13000}"
AUTH="$GF_SECURITY_ADMIN_USER:$GF_SECURITY_ADMIN_PASSWORD"
titulo() { printf '\n========== %s ==========\n' "$1"; }
sql() { kubectl -n "$NS" exec -i postgres-0 -- psql -U postgres -d microrred -At -c "$1"; }
conteos() {
  sql "SELECT 'fact_energia_5min=' || (SELECT COUNT(*) FROM gold.fact_energia_5min) ||
              ' fact_evento=' || (SELECT COUNT(*) FROM gold.fact_evento) ||
              ' fact_contexto=' || (SELECT COUNT(*) FROM gold.fact_contexto) ||
              ' huella=' || (SELECT huella_resultado FROM audit.etl_ejecucion WHERE estado='OK' ORDER BY ejecucion_id DESC LIMIT 1)"
}

demo_postgres() {
  titulo "1. Se elimina el pod de PostgreSQL: los datos siguen ahi"
  echo "ANTES  : $(conteos)"
  kubectl -n "$NS" get pod postgres-0 -o custom-columns=POD:.metadata.name,UID:.metadata.uid,INICIO:.status.startTime
  kubectl -n "$NS" get pvc
  kubectl -n "$NS" delete pod postgres-0
  kubectl -n "$NS" rollout status statefulset/postgres --timeout=180s
  kubectl -n "$NS" get pod postgres-0 -o custom-columns=POD:.metadata.name,UID:.metadata.uid,INICIO:.status.startTime
  kubectl -n "$NS" get pvc
  echo "DESPUES: $(conteos)"
}

demo_grafana() {
  titulo "2. Se elimina el pod de Grafana: vuelve con su tablero, fuente y alertas"
  kubectl -n "$NS" get pod -l app=grafana -o custom-columns=POD:.metadata.name,INICIO:.status.startTime
  kubectl -n "$NS" delete pod -l app=grafana
  kubectl -n "$NS" rollout status deployment/grafana --timeout=180s
  kubectl -n "$NS" get pod -l app=grafana -o custom-columns=POD:.metadata.name,INICIO:.status.startTime
  for _ in $(seq 1 30); do curl -sf "$GRAFANA/api/health" >/dev/null && break; sleep 2; done
  echo "Tableros : $(curl -s -u "$AUTH" "$GRAFANA/api/search?type=dash-db" | python -c "import json,sys; print([(d['folderTitle'], d['title']) for d in json.load(sys.stdin)])")"
  echo "Fuentes  : $(curl -s -u "$AUTH" "$GRAFANA/api/datasources" | python -c "import json,sys; print([(d['name'], d['type'], d['readOnly']) for d in json.load(sys.stdin)])")"
  echo "Alertas  : $(curl -s -u "$AUTH" "$GRAFANA/api/v1/provisioning/alert-rules" | python -c "import json,sys; print([r['title'] for r in json.load(sys.stdin)])")"
}

demo_alerta() {
  titulo "3. Llegan datos nuevos con bateria baja: la alerta reacciona"
  echo "--- estado inicial"; bash scripts/alertas.sh
  sql "SELECT 'ultima lectura: inv ' || inversor_id || ' soc=' || soc_pct || ' escenario=' || escenario FROM live.vw_estado_actual ORDER BY 1"
  echo "--- se cambia el escenario del simulador (variable de entorno, sin reconstruir la imagen)"
  kubectl -n "$NS" set env cronjob/simulador SIM_ESCENARIO=bateria_baja
  for i in $(seq 1 16); do
    sleep 20
    linea="$(bash scripts/alertas.sh | grep 'SOC de bateria bajo')"
    echo "t+$((i * 20))s  $linea"
    [[ "$linea" == *"estado=firing"* ]] && break
  done
  sql "SELECT 'ultima lectura: inv ' || inversor_id || ' soc=' || soc_pct || ' escenario=' || escenario FROM live.vw_estado_actual ORDER BY 1"
  echo "--- se vuelve al escenario normal (valor del ConfigMap)"
  kubectl -n "$NS" set env cronjob/simulador SIM_ESCENARIO-
  for i in $(seq 1 16); do
    sleep 20
    linea="$(bash scripts/alertas.sh | grep 'SOC de bateria bajo')"
    echo "t+$((i * 20))s  $linea"
    [[ "$linea" == *"estado=inactive"* ]] && break
  done
}

demo_escalar() {
  titulo "4. Bonificacion: escalar Grafana a 2 replicas y volver a 1"
  kubectl -n "$NS" scale deployment/grafana --replicas=2
  kubectl -n "$NS" rollout status deployment/grafana --timeout=180s
  kubectl -n "$NS" get pods -l app=grafana -o wide
  kubectl -n "$NS" get endpoints grafana
  kubectl -n "$NS" scale deployment/grafana --replicas=1
  kubectl -n "$NS" rollout status deployment/grafana --timeout=180s
  kubectl -n "$NS" get deployment grafana
}

demo_rolling() {
  titulo "5. Bonificacion: actualizar la imagen del simulador (1.0.0 -> 1.0.1) y revertir"
  docker build -q --provenance=false --build-arg VERSION=1.0.1 -t microrred-simulador:1.0.1 simulador
  docker save microrred-simulador:1.0.1 | docker exec --privileged -i microrred-control-plane \
    ctr --namespace=k8s.io images import --digests --snapshotter=overlayfs - >/dev/null
  imagen() { kubectl -n "$NS" get cronjob simulador -o jsonpath='{.spec.jobTemplate.spec.template.spec.containers[0].image}'; }
  ultimo_pod() { kubectl -n "$NS" get pods -l app=simulador --sort-by=.metadata.creationTimestamp \
                   -o custom-columns=POD:.metadata.name,IMAGEN:.spec.containers[0].image,ESTADO:.status.phase --no-headers | tail -1; }
  echo "imagen del CronJob antes : $(imagen)"
  kubectl -n "$NS" set image cronjob/simulador simulador=microrred-simulador:1.0.1
  echo "imagen del CronJob ahora : $(imagen)"; sleep 75
  echo "ultima pasada            : $(ultimo_pod)"
  sql "SELECT 'lecturas en los ultimos 3 min: ' || COUNT(*) FROM live.lectura WHERE ts > now() - interval '3 minutes'"
  echo "--- reversion (un CronJob no guarda historial de rollout: se vuelve a la imagen versionada en Git)"
  kubectl -n "$NS" set image cronjob/simulador simulador=microrred-simulador:1.0.0
  echo "imagen del CronJob final : $(imagen)"; sleep 75
  echo "ultima pasada            : $(ultimo_pod)"
}

evidencia() {
  titulo "kubectl get all,configmap,secret,pvc -n $NS"
  kubectl -n "$NS" get all,configmap,secret,pvc
  titulo "kubectl get pv ; kubectl get nodes -o wide"
  kubectl get pv
  kubectl get nodes -o wide
  for objeto in statefulset/postgres deployment/grafana job/etl-carga-historica cronjob/simulador \
                service/postgres service/postgres-externo service/grafana pvc/datos-postgres-0 secret/microrred-credenciales; do
    titulo "kubectl describe $objeto -n $NS"
    kubectl -n "$NS" describe "$objeto"
  done
}

case "${1:-todo}" in
  postgres) demo_postgres ;;
  grafana) demo_grafana ;;
  alerta) demo_alerta ;;
  escalar) demo_escalar ;;
  rolling) demo_rolling ;;
  evidencia) evidencia ;;
  todo) demo_postgres; demo_grafana; demo_alerta; demo_escalar; demo_rolling ;;
  *) echo "uso: $0 [postgres|grafana|alerta|escalar|rolling|evidencia|todo]"; exit 2 ;;
esac
