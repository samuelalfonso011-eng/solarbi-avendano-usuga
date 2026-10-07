-- tables.sql — SolarBI Pascual
-- Crea los esquemas y tablas de las capas Silver y Gold en PostgreSQL.
-- La capa Bronze vive como archivo plano (data/bronze/lecturas_bronze.csv)
-- y NO se materializa en PostgreSQL: es el archivo crudo e inmutable.

CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS dwh;

-- =========================================================
-- SILVER: lecturas de 5 minutos ya limpias (reglas de calidad aplicadas)
-- =========================================================
CREATE TABLE IF NOT EXISTS silver.lectura_5min (
    lectura_id        BIGSERIAL PRIMARY KEY,
    ts                TIMESTAMP NOT NULL,
    dispositivo_id    TEXT NOT NULL,
    p_ac_kw           NUMERIC(10,3) NOT NULL,
    irradiancia_wm2   NUMERIC(10,2) NOT NULL,
    temp_modulo_c     NUMERIC(6,2) NOT NULL,
    cargado_en        TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_lectura UNIQUE (ts, dispositivo_id)
);

CREATE INDEX IF NOT EXISTS ix_lectura_5min_ts ON silver.lectura_5min (ts);
CREATE INDEX IF NOT EXISTS ix_lectura_5min_dispositivo ON silver.lectura_5min (dispositivo_id);

-- Tabla de métricas de calidad por corrida del ETL (auditoría de Silver)
CREATE TABLE IF NOT EXISTS silver.metricas_calidad (
    corrida_id                         BIGSERIAL PRIMARY KEY,
    ejecutado_en                       TIMESTAMP NOT NULL DEFAULT now(),
    filas_leidas                       INTEGER NOT NULL,
    filas_rechazadas_por_rango         INTEGER NOT NULL,
    filas_rechazadas_por_duplicados    INTEGER NOT NULL,
    filas_rechazadas_por_faltantes     INTEGER NOT NULL,
    filas_validas                      INTEGER NOT NULL,
    porcentaje_datos_validos           NUMERIC(5,2) NOT NULL
);

-- =========================================================
-- GOLD (dwh): hecho diario de energía por dispositivo
-- =========================================================
CREATE TABLE IF NOT EXISTS dwh.fact_energia_dia (
    fecha_key           DATE NOT NULL,
    dispositivo_key      TEXT NOT NULL,
    energia_kwh          NUMERIC(10,3) NOT NULL,
    pct_datos_validos    NUMERIC(5,2) NOT NULL,
    actualizado_en        TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT pk_fact_energia_dia PRIMARY KEY (fecha_key, dispositivo_key)
);
