#!/usr/bin/env bash
# Muestra el estado de las reglas de alerta de Grafana (API), una linea por regla.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_entorno.sh
cargar_env .env
curl -s -u "$GF_SECURITY_ADMIN_USER:$GF_SECURITY_ADMIN_PASSWORD" \
  "http://localhost:${GRAFANA_PUERTO_LOCAL:-13000}/api/prometheus/grafana/api/v1/rules" | python -c "
import json, sys
for g in json.load(sys.stdin)['data']['groups']:
    for r in g['rules']:
        inst = ', '.join('inv %s=%s' % (a['labels'].get('inversor', '?'), a['state']) for a in r.get('alerts', []))
        print('%-28s estado=%-9s salud=%-6s %s %s' % (r['name'], r['state'], r['health'], inst, r.get('lastError', '')[:120]))
"
