-- cargas.sql — SolarBI Pascual
-- Sentencias de referencia para las cargas UPSERT que ejecuta etl/run_etl.py.
-- Se documentan aquí para que el SQL quede trazable y auditable fuera del
-- código Python; run_etl.py ejecuta el equivalente parametrizado con psycopg2.

-- =========================================================
-- Carga/actualización de silver.lectura_5min (idempotente)
-- Clave: (ts, dispositivo_id)
-- =========================================================
INSERT INTO silver.lectura_5min (ts, dispositivo_id, p_ac_kw, irradiancia_wm2, temp_modulo_c)
VALUES (%(ts)s, %(dispositivo_id)s, %(p_ac_kw)s, %(irradiancia_wm2)s, %(temp_modulo_c)s)
ON CONFLICT (ts, dispositivo_id)
DO UPDATE SET
    p_ac_kw         = EXCLUDED.p_ac_kw,
    irradiancia_wm2 = EXCLUDED.irradiancia_wm2,
    temp_modulo_c   = EXCLUDED.temp_modulo_c,
    cargado_en      = now();

-- =========================================================
-- Carga/actualización de dwh.fact_energia_dia (idempotente)
-- Clave: (fecha_key, dispositivo_key)
-- energia_kwh se recalcula agregando silver.lectura_5min del día
-- =========================================================
INSERT INTO dwh.fact_energia_dia (fecha_key, dispositivo_key, energia_kwh, pct_datos_validos)
VALUES (%(fecha_key)s, %(dispositivo_key)s, %(energia_kwh)s, %(pct_datos_validos)s)
ON CONFLICT (fecha_key, dispositivo_key)
DO UPDATE SET
    energia_kwh       = EXCLUDED.energia_kwh,
    pct_datos_validos = EXCLUDED.pct_datos_validos,
    actualizado_en     = now();

-- =========================================================
-- Consulta de agregación diaria (la usa run_etl.py para construir Gold)
-- energia_intervalo_kwh = potencia_kw * (5/60) h  →  se suma por día/dispositivo
-- =========================================================
SELECT
    date_trunc('day', ts)::date       AS fecha_key,
    dispositivo_id                    AS dispositivo_key,
    SUM(p_ac_kw * (5.0/60.0))         AS energia_kwh
FROM silver.lectura_5min
WHERE date_trunc('day', ts)::date = %(fecha)s
GROUP BY 1, 2;

-- =========================================================
-- Verificación rápida de idempotencia (conteos antes/después de 2da corrida)
-- =========================================================
SELECT 'silver.lectura_5min' AS tabla, COUNT(*) AS filas FROM silver.lectura_5min
UNION ALL
SELECT 'dwh.fact_energia_dia', COUNT(*) FROM dwh.fact_energia_dia;
