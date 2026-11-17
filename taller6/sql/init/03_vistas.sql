-- =====================================================================
-- Vistas de consumo (Power BI, Grafana, DBeaver)
-- =====================================================================
SET ROLE etl_app;

-- Tarifa vigente para una fecha
CREATE FUNCTION gold.tarifa_vigente(p_fecha date) RETURNS numeric
LANGUAGE sql STABLE AS $$
    SELECT cop_kwh FROM gold.tarifa WHERE vigente_desde <= p_fecha
    ORDER BY vigente_desde DESC LIMIT 1
$$;

-- KPI por dia e inversor. El andamio fecha x inversor conserva los dias SIN datos,
-- de modo que la disponibilidad castiga los huecos de telemetria.
CREATE VIEW gold.vw_kpi_diario AS
WITH periodo AS (
    SELECT MIN(fecha_key) AS desde, MAX(fecha_key) AS hasta FROM gold.fact_energia_5min
), andamio AS (
    SELECT f.fecha_key, f.fecha, f.anio_mes, f.tipo_dia, i.inversor_id
    FROM gold.dim_fecha f
    CROSS JOIN (SELECT DISTINCT inversor_id FROM gold.dim_inversor WHERE inversor_id > 0) i
    JOIN periodo p ON f.fecha_key BETWEEN p.desde AND p.hasta
), diario AS (
    SELECT h.fecha_key, i.inversor_id,
           SUM(h.e_solar_kwh)        AS e_solar_kwh,
           SUM(h.e_carga_kwh)        AS e_carga_kwh,
           SUM(h.e_red_kwh)          AS e_red_kwh,
           SUM(h.e_bat_carga_kwh)    AS e_bat_carga_kwh,
           SUM(h.e_bat_descarga_kwh) AS e_bat_descarga_kwh,
           SUM(h.e_red_a_bat_kwh)    AS e_red_a_bat_kwh,
           MAX(h.p_solar_max_w)      AS p_solar_max_w,
           MAX(h.p_carga_max_w)      AS p_carga_max_w,
           MIN(h.soc_min)            AS soc_min,
           SUM(h.seg_observados)     AS seg_observados,
           SUM(h.seg_sin_red)        AS seg_sin_red,
           SUM(h.seg_salida_apagada) AS seg_salida_apagada,
           SUM(h.seg_bateria_baja)   AS seg_bateria_baja,
           SUM(h.n_lecturas)         AS n_lecturas,
           SUM(h.n_validas)          AS n_validas
    FROM gold.fact_energia_5min h
    JOIN gold.dim_inversor i USING (inversor_key)
    GROUP BY h.fecha_key, i.inversor_id
)
SELECT a.fecha_key, a.fecha, a.anio_mes, a.tipo_dia, a.inversor_id,
       COALESCE(d.e_solar_kwh, 0)        AS e_solar_kwh,
       COALESCE(d.e_carga_kwh, 0)        AS e_carga_kwh,
       COALESCE(d.e_red_kwh, 0)          AS e_red_kwh,
       COALESCE(d.e_bat_carga_kwh, 0)    AS e_bat_carga_kwh,
       COALESCE(d.e_bat_descarga_kwh, 0) AS e_bat_descarga_kwh,
       COALESCE(d.e_red_a_bat_kwh, 0)    AS e_red_a_bat_kwh,
       d.p_solar_max_w, d.p_carga_max_w, d.soc_min,
       ROUND((100 * COALESCE(d.seg_observados, 0) / 86400)::numeric, 2)           AS disponibilidad_pct,
       ROUND((100.0 * d.n_validas / NULLIF(d.n_lecturas, 0))::numeric, 2)         AS datos_validos_pct,
       -- Autosuficiencia: fraccion de la carga que NO se compro a la red
       ROUND((100 * (1 - LEAST(d.e_red_kwh - d.e_red_a_bat_kwh, d.e_carga_kwh)
                          / NULLIF(d.e_carga_kwh, 0)))::numeric, 2)               AS autosuficiencia_pct,
       ROUND((COALESCE(d.seg_bateria_baja, 0) / 3600)::numeric, 2)                AS horas_soc_bajo,
       ROUND((COALESCE(d.seg_sin_red, 0) / 3600)::numeric, 2)                     AS horas_sin_red,
       ROUND((COALESCE(d.seg_salida_apagada, 0) / 3600)::numeric, 2)              AS horas_salida_apagada,
       -- Perdidas de conversion: lo que entra menos lo que sale
       COALESCE(d.e_solar_kwh + d.e_red_kwh + d.e_bat_descarga_kwh
                - d.e_bat_carga_kwh - d.e_carga_kwh, 0)                           AS perdidas_kwh,
       ROUND((COALESCE(d.e_red_kwh, 0) * gold.tarifa_vigente(a.fecha))::numeric, 0) AS costo_red_cop,
       ROUND((GREATEST(COALESCE(d.e_carga_kwh - (d.e_red_kwh - d.e_red_a_bat_kwh), 0), 0)
              * gold.tarifa_vigente(a.fecha))::numeric, 0)                        AS costo_evitado_cop,
       COALESCE(d.n_lecturas, 0) AS n_lecturas,
       COALESCE(d.n_validas, 0)  AS n_validas
FROM andamio a
LEFT JOIN diario d USING (fecha_key, inversor_id);

CREATE VIEW gold.vw_kpi_mensual AS
SELECT anio_mes, inversor_id,
       COUNT(*)                                   AS dias,
       SUM(e_solar_kwh)                           AS e_solar_kwh,
       SUM(e_carga_kwh)                           AS e_carga_kwh,
       SUM(e_red_kwh)                             AS e_red_kwh,
       SUM(e_bat_carga_kwh)                       AS e_bat_carga_kwh,
       SUM(e_bat_descarga_kwh)                    AS e_bat_descarga_kwh,
       ROUND(AVG(disponibilidad_pct), 2)          AS disponibilidad_pct,
       ROUND((100.0 * SUM(n_validas) / NULLIF(SUM(n_lecturas), 0))::numeric, 2) AS datos_validos_pct,
       ROUND((100 * (1 - LEAST(SUM(e_red_kwh - e_red_a_bat_kwh), SUM(e_carga_kwh))
                          / NULLIF(SUM(e_carga_kwh), 0)))::numeric, 2)          AS autosuficiencia_pct,
       -- Eficiencia de ida y vuelta de la bateria (solo tiene sentido en periodos largos)
       ROUND((100 * SUM(e_bat_descarga_kwh) / NULLIF(SUM(e_bat_carga_kwh), 0))::numeric, 2) AS eficiencia_bateria_pct,
       SUM(horas_soc_bajo)                        AS horas_soc_bajo,
       SUM(horas_sin_red)                         AS horas_sin_red,
       SUM(perdidas_kwh)                          AS perdidas_kwh,
       SUM(costo_red_cop)                         AS costo_red_cop,
       SUM(costo_evitado_cop)                     AS costo_evitado_cop
FROM gold.vw_kpi_diario
GROUP BY anio_mes, inversor_id;

-- Balance energetico en formato largo: de donde viene y a donde va la energia
CREATE VIEW gold.vw_balance_energetico AS
SELECT k.fecha_key, k.inversor_id, v.sentido, v.flujo, v.orden, v.kwh
FROM gold.vw_kpi_diario k
CROSS JOIN LATERAL (VALUES
    ('Origen',  'Solar',              1, k.e_solar_kwh),
    ('Origen',  'Red',                2, k.e_red_kwh),
    ('Origen',  'Bateria (descarga)', 3, k.e_bat_descarga_kwh),
    ('Destino', 'Carga',              4, k.e_carga_kwh),
    ('Destino', 'Bateria (carga)',    5, k.e_bat_carga_kwh),
    ('Destino', 'Perdidas',           6, GREATEST(k.perdidas_kwh, 0))
) AS v(sentido, flujo, orden, kwh);

-- Hecho de contexto sin el JSON (Power BI no necesita el detalle; minimizacion de datos)
CREATE VIEW gold.vw_contexto AS
SELECT contexto_id, fecha_key, tiempo_key, inversor_key, tipo_contexto_key,
       inicio_utc, fin_utc, duracion_min, esfuerzo
FROM gold.fact_contexto;

CREATE VIEW gold.vw_evento AS
SELECT evento_id, fecha_key, tiempo_key, inversor_key, tipo_evento_key,
       inicio_utc, fin_utc, duracion_min, n_lecturas, valor_extremo
FROM gold.fact_evento;

-- Estado actual por inversor (Grafana): ultima lectura y su antiguedad
CREATE VIEW live.vw_estado_actual AS
SELECT DISTINCT ON (inversor_id)
       inversor_id, ts, p_solar_w, p_carga_w, p_red_w, p_bateria_w, soc_pct,
       red_disponible, escenario,
       EXTRACT(EPOCH FROM (now() - ts))::int AS segundos_desde_ultima_lectura
FROM live.lectura
ORDER BY inversor_id, ts DESC;
