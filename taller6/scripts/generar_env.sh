#!/usr/bin/env bash
# Genera .env con contrasenas aleatorias (solo si no existe). Nunca se versiona.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .env ]]; then
  echo ".env ya existe: no se modifica"
  exit 0
fi
clave() { python -c "import secrets; print(secrets.token_urlsafe(24))"; }
umask 077
cat > .env <<EOF
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$(clave)
ETL_PASSWORD=$(clave)
SIM_PASSWORD=$(clave)
GRAFANA_DB_PASSWORD=$(clave)
BI_PASSWORD=$(clave)
GF_SECURITY_ADMIN_USER=admin
GF_SECURITY_ADMIN_PASSWORD=$(clave)
EOF
echo ".env generado con claves aleatorias (no se versiona)"
