#!/bin/sh
# Crea los roles de aplicacion con las contrasenas que llegan por variables de
# entorno (Secret de Kubernetes / .env de docker-compose). Ninguna contrasena
# vive en el repositorio ni en la imagen. Minimo privilegio por servicio:
#   etl_app    -> duenno de los esquemas; unico que escribe el modelo
#   sim_app    -> solo inserta en live.lectura
#   grafana_ro -> solo lectura de live y de gold
#   bi_lectura -> solo lectura de gold (Power BI / DBeaver); sin acceso a silver
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v etl="$ETL_PASSWORD" -v sim="$SIM_PASSWORD" \
     -v graf="$GRAFANA_DB_PASSWORD" -v bi="$BI_PASSWORD" <<SQL
CREATE ROLE etl_app    LOGIN PASSWORD :'etl';
CREATE ROLE sim_app    LOGIN PASSWORD :'sim';
CREATE ROLE grafana_ro LOGIN PASSWORD :'graf';
CREATE ROLE bi_lectura LOGIN PASSWORD :'bi';
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT CREATE, CONNECT ON DATABASE "$POSTGRES_DB" TO etl_app;
GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO sim_app, grafana_ro, bi_lectura;
SQL
