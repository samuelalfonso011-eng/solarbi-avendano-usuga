#!/bin/sh
# Copia el aprovisionamiento de Grafana de ORIGEN a DESTINO y sustituye los
# marcadores __ALERTA_*__ de las reglas de alerta por los valores del entorno
# (ConfigMap). Se ejecuta antes de iniciar Grafana:
#   - Kubernetes: initContainer del Deployment de Grafana
#   - docker-compose: antes de /run.sh
# Uso: render_provisioning.sh ORIGEN DESTINO
set -eu
origen="$1"
destino="$2"
: "${ALERTA_SOC_BAJO_PCT:?falta ALERTA_SOC_BAJO_PCT}"
: "${ALERTA_SIN_DATOS_S:?falta ALERTA_SIN_DATOS_S}"
: "${ALERTA_RED_ALTA_W:?falta ALERTA_RED_ALTA_W}"

mkdir -p "$destino/datasources" "$destino/dashboards" "$destino/alerting"
cp "$origen"/datasources/*.yaml "$destino/datasources/"
cp "$origen"/dashboards/*.yaml "$destino/dashboards/"
for archivo in "$origen"/alerting/*.yaml; do
  sed -e "s/__ALERTA_SOC_BAJO_PCT__/${ALERTA_SOC_BAJO_PCT}/g" \
      -e "s/__ALERTA_SIN_DATOS_S__/${ALERTA_SIN_DATOS_S}/g" \
      -e "s/__ALERTA_RED_ALTA_W__/${ALERTA_RED_ALTA_W}/g" \
      "$archivo" > "$destino/alerting/$(basename "$archivo")"
done
if grep -q "__ALERTA_" "$destino"/alerting/*.yaml; then
  echo "ERROR: quedaron marcadores sin sustituir" >&2
  exit 1
fi
echo "Aprovisionamiento renderizado en $destino (SOC<${ALERTA_SOC_BAJO_PCT} %, sin datos>${ALERTA_SIN_DATOS_S} s, red>${ALERTA_RED_ALTA_W} W)"
