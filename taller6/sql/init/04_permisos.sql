-- =====================================================================
-- Permisos por rol (minimo privilegio). Se ejecuta como etl_app, duenno
-- de los objetos. ALTER DEFAULT PRIVILEGES cubre objetos futuros.
-- =====================================================================
SET ROLE etl_app;

-- Power BI / DBeaver: la capa Gold y las tablas de auditoria y calidad.
-- Sin acceso a silver.contexto (detalle de actividad en las estaciones).
GRANT USAGE ON SCHEMA gold, audit, silver TO bi_lectura;
GRANT SELECT ON ALL TABLES IN SCHEMA gold, audit TO bi_lectura;
GRANT SELECT ON silver.calidad_regla TO bi_lectura;
GRANT EXECUTE ON FUNCTION gold.tarifa_vigente(date) TO bi_lectura, grafana_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold GRANT SELECT ON TABLES TO bi_lectura;

-- Grafana: lectura de live, gold y de la bitacora de calidad (paneles de salud del ETL)
GRANT USAGE ON SCHEMA gold, live, audit, silver TO grafana_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA gold, live, audit TO grafana_ro;
GRANT SELECT ON silver.calidad_regla TO grafana_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA gold, live GRANT SELECT ON TABLES TO grafana_ro;

-- Simulador: lee el historico que reproduce y solo inserta en live.lectura
GRANT USAGE ON SCHEMA gold, live TO sim_app;
GRANT SELECT ON gold.fact_energia_5min, gold.dim_inversor, gold.dim_fecha TO sim_app;
GRANT SELECT, INSERT ON live.lectura TO sim_app;
