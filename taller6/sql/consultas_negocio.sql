-- =====================================================================
-- Consultas que responden preguntas de negocio (seccion F del taller).
-- Ejecutar desde DBeaver con el rol bi_lectura (solo lectura de gold).
--   bash scripts/psql.sh k8s -f - < sql/consultas_negocio.sql
-- =====================================================================

-- P1. De donde viene y a donde va la energia de cada inversor, mes a mes? (agregaciones)
SELECT anio_mes, inversor_id,
       round(e_solar_kwh::numeric, 1)        AS solar_kwh,
       round(e_red_kwh::numeric, 1)          AS red_kwh,
       round(e_bat_descarga_kwh::numeric, 1) AS bateria_desc_kwh,
       round(e_carga_kwh::numeric, 1)        AS carga_kwh,
       round(e_bat_carga_kwh::numeric, 1)    AS bateria_carga_kwh,
       round(perdidas_kwh::numeric, 1)       AS perdidas_kwh,
       autosuficiencia_pct, disponibilidad_pct
FROM gold.vw_kpi_mensual
ORDER BY inversor_id, anio_mes;

-- P2. Como cambio la generacion solar frente al mes anterior? (LAG: comparativo entre periodos)
-- La energia se normaliza por disponibilidad para no comparar meses con huecos contra meses completos.
WITH m AS (
    SELECT anio_mes, inversor_id, e_solar_kwh, disponibilidad_pct,
           e_solar_kwh / NULLIF(disponibilidad_pct / 100, 0) / dias AS solar_kwh_dia_equiv
    FROM gold.vw_kpi_mensual
    WHERE disponibilidad_pct >= 50
)
SELECT anio_mes, inversor_id,
       round(e_solar_kwh::numeric, 1)         AS solar_kwh,
       round(solar_kwh_dia_equiv::numeric, 2) AS kwh_dia_equivalente,
       round((LAG(solar_kwh_dia_equiv) OVER w)::numeric, 2) AS mes_anterior,
       round((100 * (solar_kwh_dia_equiv / NULLIF(LAG(solar_kwh_dia_equiv) OVER w, 0) - 1))::numeric, 1) AS variacion_pct
FROM m
WINDOW w AS (PARTITION BY inversor_id ORDER BY anio_mes)
ORDER BY inversor_id, anio_mes;

-- P3. Cuales fueron los 5 dias de mayor compra a la red de cada inversor? (RANK)
SELECT * FROM (
    SELECT inversor_id, fecha, tipo_dia,
           round(e_red_kwh::numeric, 2)   AS red_kwh,
           round(e_carga_kwh::numeric, 2) AS carga_kwh,
           costo_red_cop,
           RANK() OVER (PARTITION BY inversor_id ORDER BY e_red_kwh DESC) AS puesto
    FROM gold.vw_kpi_diario
) t
WHERE puesto <= 5
ORDER BY inversor_id, puesto;

-- P4. En que franja horaria se compra energia y en cual sobra sol? (dimension construida dim_tiempo)
SELECT i.inversor_id, t.orden_franja, t.franja_horaria,
       round(SUM(h.e_solar_kwh)::numeric, 1) AS solar_kwh,
       round(SUM(h.e_red_kwh)::numeric, 1)   AS red_kwh,
       round(SUM(h.e_carga_kwh)::numeric, 1) AS carga_kwh,
       round((100 * SUM(h.e_red_kwh) / SUM(SUM(h.e_red_kwh)) OVER (PARTITION BY i.inversor_id))::numeric, 1) AS pct_de_la_compra
FROM gold.fact_energia_5min h
JOIN gold.dim_tiempo t USING (tiempo_key)
JOIN gold.dim_inversor i USING (inversor_key)
GROUP BY i.inversor_id, t.orden_franja, t.franja_horaria
ORDER BY i.inversor_id, t.orden_franja;

-- P5. Cual es la tendencia de la autosuficiencia? (promedio movil de 7 dias con marco de ventana)
SELECT fecha, inversor_id, autosuficiencia_pct,
       round(AVG(autosuficiencia_pct) OVER (PARTITION BY inversor_id ORDER BY fecha
                                            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 1) AS media_movil_7d
FROM gold.vw_kpi_diario
WHERE fecha BETWEEN DATE '2026-01-01' AND DATE '2026-01-31' AND disponibilidad_pct >= 90
ORDER BY inversor_id, fecha;

-- P6. Cuanto consume una estacion mientras entrena un modelo en GPU? (JSON con operadores nativos)
--   @>   contiene            ->> extrae texto        ?  existe la llave
-- Las estaciones de computo cuelgan del inversor 1. Se cruza cada intervalo de 5 min con los
-- registros de contexto vigentes en ese instante.
WITH gpu AS (
    SELECT c.inicio_utc, c.fin_utc,
           c.atributos ->> 'model'            AS modelo,
           (c.atributos ->> 'epochs')::int    AS epocas
    FROM gold.fact_contexto c
    WHERE c.atributos @> '{"task_type": "CNN fitting, GPU load"}'
      AND c.atributos ? 'model'
), marcado AS (
    SELECT h.ts_utc, h.e_carga_kwh, h.seg_observados,
           EXISTS (SELECT 1 FROM gpu g
                   WHERE g.inicio_utc < h.ts_utc + interval '5 minutes' AND g.fin_utc > h.ts_utc) AS con_gpu
    FROM gold.fact_energia_5min h
    JOIN gold.dim_inversor i USING (inversor_key)
    WHERE i.inversor_id = 1
      AND h.ts_utc BETWEEN (SELECT MIN(inicio_utc) FROM gpu) AND (SELECT MAX(fin_utc) FROM gpu)
      AND h.seg_observados > 0
)
SELECT CASE WHEN con_gpu THEN 'Entrenando en GPU' ELSE 'Sin entrenamiento' END AS situacion,
       COUNT(*)                                                                  AS intervalos_5min,
       round((SUM(e_carga_kwh) * 3600000 / SUM(seg_observados))::numeric, 0)     AS potencia_media_w
FROM marcado
GROUP BY con_gpu
ORDER BY con_gpu DESC;

-- P6b. Que modelos se entrenaron y con que configuracion? (jsonb ->> y agregacion)
SELECT atributos ->> 'model' AS modelo, atributos ->> 'optim' AS optimizador,
       COUNT(*) AS corridas,
       round(AVG((atributos ->> 'epochs')::int), 1)     AS epocas_promedio,
       round(AVG((atributos ->> 'batch_size')::int), 0) AS lote_promedio,
       round(SUM(duracion_min)::numeric / 60, 1)        AS horas
FROM gold.fact_contexto
WHERE atributos @> '{"task_type": "CNN fitting, GPU load"}'
GROUP BY 1, 2
ORDER BY corridas DESC
LIMIT 10;

-- P6c. Que eventos de Windows reportaron errores? (jsonb_path_exists sobre un objeto anidado)
SELECT t.tipo_contexto, COUNT(*) AS registros,
       SUM((c.atributos #>> '{windows_event,event_count}')::int) AS eventos_agregados
FROM gold.fact_contexto c
JOIN gold.dim_tipo_contexto t USING (tipo_contexto_key)
WHERE jsonb_path_exists(c.atributos, '$.windows_event.levels.Error')
GROUP BY 1
ORDER BY 2 DESC;

-- P7. Cuantas horas al mes estuvo cada inversor en bateria baja, sin red o sin salida? (hecho de eventos)
SELECT f.anio_mes, i.inversor_id, t.nombre AS evento,
       COUNT(*)                                          AS episodios,
       round((SUM(e.duracion_min) / 60)::numeric, 1)     AS horas,
       round(MIN(e.valor_extremo)::numeric, 0)           AS soc_minimo
FROM gold.fact_evento e
JOIN gold.dim_tipo_evento t USING (tipo_evento_key)
JOIN gold.dim_inversor i USING (inversor_key)
JOIN gold.dim_fecha f USING (fecha_key)
WHERE t.codigo IN ('BATERIA_BAJA', 'SIN_RED', 'SALIDA_APAGADA')
GROUP BY f.anio_mes, i.inversor_id, t.nombre
ORDER BY i.inversor_id, f.anio_mes, evento;

-- P8. Se consume distinto en dia laboral, fin de semana y festivo del campus?
SELECT inversor_id, tipo_dia, COUNT(*) AS dias,
       round(AVG(e_carga_kwh)::numeric, 2) AS carga_kwh_dia,
       round(AVG(e_red_kwh)::numeric, 2)   AS red_kwh_dia,
       round(AVG(e_solar_kwh)::numeric, 2) AS solar_kwh_dia
FROM gold.vw_kpi_diario
WHERE disponibilidad_pct >= 90
GROUP BY inversor_id, tipo_dia
ORDER BY inversor_id, tipo_dia;

-- P9. Cambio el comportamiento tras modificar la prioridad de carga? (SCD tipo 2 en dim_inversor)
SELECT i.inversor_id, i.inversor_key, i.prioridad_salida, i.prioridad_carga, i.soc_bateria_llena,
       i.valido_desde, i.valido_hasta,
       COUNT(DISTINCT h.fecha_key)                                           AS dias_con_datos,
       round((SUM(h.e_red_kwh) / COUNT(DISTINCT h.fecha_key))::numeric, 2)   AS red_kwh_dia,
       round((SUM(h.e_red_a_bat_kwh) / COUNT(DISTINCT h.fecha_key))::numeric, 2) AS red_a_bateria_kwh_dia,
       round((100 * (1 - SUM(h.e_red_kwh - h.e_red_a_bat_kwh) / SUM(h.e_carga_kwh)))::numeric, 1) AS autosuficiencia_pct
FROM gold.fact_energia_5min h
JOIN gold.dim_inversor i USING (inversor_key)
GROUP BY i.inversor_id, i.inversor_key, i.prioridad_salida, i.prioridad_carga, i.soc_bateria_llena,
         i.valido_desde, i.valido_hasta
ORDER BY i.inversor_id, i.valido_desde;

-- P10. Que umbral de importacion de red es "anormal"? (percentiles: justifica la alerta de Grafana)
SELECT i.inversor_id,
       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY h.p_red_max_w)::numeric, 0) AS p50_w,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY h.p_red_max_w)::numeric, 0) AS p95_w,
       round(percentile_cont(0.99) WITHIN GROUP (ORDER BY h.p_red_max_w)::numeric, 0) AS p99_w,
       MAX(h.p_red_max_w) AS maximo_w
FROM gold.fact_energia_5min h
JOIN gold.dim_inversor i USING (inversor_key)
WHERE h.p_red_max_w IS NOT NULL
GROUP BY i.inversor_id;

-- P11. Conciliacion: la energia cargada coincide con los contadores del inversor?
SELECT inversor_id, magnitud, SUM(dias_conciliados) AS dias,
       round(SUM(kwh_contador)::numeric, 1)  AS kwh_contador_inversor,
       round(SUM(kwh_integrado)::numeric, 1) AS kwh_integrado_etl,
       round((100 * (SUM(kwh_integrado) - SUM(kwh_contador)) / SUM(kwh_contador))::numeric, 2) AS diferencia_pct
FROM audit.conciliacion
WHERE ejecucion_id = (SELECT MAX(ejecucion_id) FROM audit.etl_ejecucion WHERE estado = 'OK')
GROUP BY inversor_id, magnitud
ORDER BY magnitud, inversor_id;
