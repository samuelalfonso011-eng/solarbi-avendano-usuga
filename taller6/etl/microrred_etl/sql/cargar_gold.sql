-- =====================================================================
-- Silver -> Gold. Se ejecuta dentro de la transaccion del ETL.
-- Parametros (set_config local a la transaccion):
--   etl.zona          zona horaria del sitio (Asia/Shanghai)
--   etl.bateria_kwh   capacidad nominal del banco de baterias
--   etl.ejecucion_id  corrida actual
-- Carga completa y determinista: mismas entradas => mismas llaves y mismos valores.
-- =====================================================================
TRUNCATE gold.fact_energia_5min, gold.fact_evento, gold.fact_contexto,
         gold.dim_fecha, gold.dim_tiempo, gold.dim_inversor,
         gold.dim_tipo_evento, gold.dim_tipo_contexto RESTART IDENTITY CASCADE;

-- ---------------- dim_fecha ----------------
INSERT INTO gold.dim_fecha
SELECT to_char(d, 'YYYYMMDD')::int, d::date,
       extract(year FROM d), extract(quarter FROM d), extract(month FROM d),
       (ARRAY['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto',
              'Septiembre','Octubre','Noviembre','Diciembre'])[extract(month FROM d)::int],
       to_char(d, 'YYYY-MM'), extract(week FROM d), extract(day FROM d),
       extract(isodow FROM d),
       (ARRAY['Lunes','Martes','Miercoles','Jueves','Viernes','Sabado','Domingo'])[extract(isodow FROM d)::int],
       extract(isodow FROM d) >= 6, false,
       CASE WHEN extract(isodow FROM d) >= 6 THEN 'Fin de semana' ELSE 'Laboral' END
FROM generate_series(
       (SELECT LEAST((SELECT MIN(ts_utc) FROM silver.medicion_5min),
                     (SELECT MIN(inicio_utc) FROM silver.contexto))
               AT TIME ZONE current_setting('etl.zona'))::date,
       (SELECT GREATEST((SELECT MAX(ts_utc) FROM silver.medicion_5min),
                        (SELECT MAX(fin_utc) FROM silver.contexto))
               AT TIME ZONE current_setting('etl.zona'))::date,
       interval '1 day') AS d;

-- Festivos del campus: provienen de las anotaciones manuales del contexto
UPDATE gold.dim_fecha f
SET es_festivo = true, tipo_dia = 'Festivo'
FROM silver.contexto c
WHERE c.fuente = 'manual entry' AND c.descripcion ILIKE '%holiday%'
  AND f.fecha >= (c.inicio_utc AT TIME ZONE current_setting('etl.zona'))::date
  AND f.fecha <  GREATEST((c.fin_utc AT TIME ZONE current_setting('etl.zona'))::date,
                          (c.inicio_utc AT TIME ZONE current_setting('etl.zona'))::date + 1);

-- ---------------- dim_tiempo (288 intervalos de 5 min) ----------------
INSERT INTO gold.dim_tiempo
SELECT k, k / 12, (k % 12) * 5, to_char(k / 12, 'FM00') || ':' || to_char((k % 12) * 5, 'FM00'),
       CASE WHEN k / 12 < 6  THEN 'Madrugada'
            WHEN k / 12 < 10 THEN 'Manana'
            WHEN k / 12 < 15 THEN 'Mediodia solar'
            WHEN k / 12 < 18 THEN 'Tarde'
            ELSE 'Noche' END,
       CASE WHEN k / 12 < 6 THEN 1 WHEN k / 12 < 10 THEN 2 WHEN k / 12 < 15 THEN 3
            WHEN k / 12 < 18 THEN 4 ELSE 5 END,
       CASE WHEN k / 12 BETWEEN 6 AND 17 THEN 'Diurno' ELSE 'Nocturno' END,
       CASE WHEN k / 12 BETWEEN 8 AND 17 THEN 'Laboral' ELSE 'No laboral' END
FROM generate_series(0, 287) AS k;

-- ---------------- dim_inversor (SCD tipo 2) ----------------
INSERT INTO gold.dim_inversor VALUES
  (0, 0, 'Instalacion completa', 'No aplica', NULL, NULL, NULL, NULL, DATE '1900-01-01', DATE '9999-12-31', true);

INSERT INTO gold.dim_inversor
SELECT row_number() OVER (ORDER BY inversor_id, valido_desde),
       inversor_id,
       'Inversor ' || inversor_id,
       CASE inversor_id WHEN 1 THEN 'Estaciones de computo (GPU/CPU)'
                        ELSE 'Climatizacion (aire acondicionado)' END,
       prioridad_salida, prioridad_carga, soc_bateria_llena,
       current_setting('etl.bateria_kwh')::numeric,
       valido_desde, valido_hasta,
       valido_hasta = DATE '9999-12-31'
FROM silver.config_inversor;

-- ---------------- dim_tipo_evento ----------------
INSERT INTO gold.dim_tipo_evento VALUES
 (1, 'SIN_RED',          'Red ausente / modo isla',      'Red',        'Advertencia', 'Telemetria: tension de red < 100 V', false),
 (2, 'SALIDA_APAGADA',   'Salida del inversor apagada',  'Salida',     'Critica',     'Telemetria: tension de salida < 100 V', false),
 (3, 'BATERIA_BAJA',     'Bateria baja',                 'Bateria',    'Advertencia', 'Telemetria: SOC <= umbral de alarma del inversor', false),
 (4, 'ALARMA_ACTIVA',    'Alarma activa del inversor',   'Alarma',     'Advertencia', 'Tabla status: sysalarmflag con algun bit activo', false),
 (5, 'FALLA_REGISTRADA', 'Falla en el historial',        'Falla',      'Critica',     'Tabla fault_history: registro 00 nuevo', false),
 (6, 'SIN_DATOS',        'Hueco de telemetria',          'Telemetria', 'Informativa', 'Mas de 10 min sin lecturas validas', true);

-- ---------------- dim_tipo_contexto ----------------
INSERT INTO gold.dim_tipo_contexto
SELECT row_number() OVER (ORDER BY fuente, tipo_contexto, dispositivo),
       fuente, tipo_contexto, dispositivo,
       CASE
         WHEN fuente IN ('workstation1_log','workstation2_log','manual_workload_entry','wsl_bash_history')
              THEN 'Carga de computo'
         WHEN fuente = 'windows_event_log' THEN 'Sistema operativo'
         WHEN fuente = 'manual entry' AND tipo_contexto = 'calendario_academico' THEN 'Calendario academico'
         WHEN fuente = 'manual entry' THEN 'Anotacion manual'
         WHEN tipo_contexto LIKE 'calendar\_%' OR tipo_contexto LIKE 'solar\_%' THEN 'Calendario y sol'
         WHEN tipo_contexto IN ('battery_charging','battery_discharging','pv_generation_active',
                                'grid_unavailable_or_islanded','high_ac_load') THEN 'Estado electrico derivado'
         ELSE 'Calidad y metadatos'
       END
FROM (SELECT DISTINCT fuente, tipo_contexto, dispositivo FROM silver.contexto) t;

-- ---------------- fact_energia_5min ----------------
INSERT INTO gold.fact_energia_5min
SELECT to_char(l.loc, 'YYYYMMDD')::int,
       (extract(hour FROM l.loc) * 12 + extract(minute FROM l.loc) / 5)::smallint,
       i.inversor_key, m.ts_utc,
       m.e_solar_wh / 1000, m.e_carga_wh / 1000, m.e_red_wh / 1000,
       m.e_bat_carga_wh / 1000, m.e_bat_descarga_wh / 1000, m.e_red_a_bat_wh / 1000,
       m.p_solar_max_w, m.p_carga_max_w, m.p_red_max_w,
       m.soc_prom, m.soc_min, m.soc_fin, m.temp_max_c,
       m.seg_observados, m.seg_sin_red, m.seg_salida_apagada, m.seg_bateria_baja,
       m.n_lecturas, m.n_validas
FROM silver.medicion_5min m
CROSS JOIN LATERAL (SELECT m.ts_utc AT TIME ZONE current_setting('etl.zona') AS loc) l
JOIN gold.dim_inversor i
  ON i.inversor_id = m.inversor_id AND l.loc::date BETWEEN i.valido_desde AND i.valido_hasta;

-- ---------------- fact_evento ----------------
INSERT INTO gold.fact_evento (fecha_key, tiempo_key, inversor_key, tipo_evento_key, inicio_utc,
                              fin_utc, duracion_min, n_lecturas, valor_extremo, detalle)
SELECT to_char(l.loc, 'YYYYMMDD')::int,
       (extract(hour FROM l.loc) * 12 + floor(extract(minute FROM l.loc) / 5))::smallint,
       i.inversor_key, t.tipo_evento_key, e.inicio_utc, e.fin_utc,
       extract(epoch FROM (e.fin_utc - e.inicio_utc)) / 60, e.n_lecturas, e.valor_extremo, e.detalle
FROM silver.evento e
CROSS JOIN LATERAL (SELECT e.inicio_utc AT TIME ZONE current_setting('etl.zona') AS loc) l
JOIN gold.dim_tipo_evento t ON t.codigo = e.tipo_evento
JOIN gold.dim_inversor i
  ON i.inversor_id = e.inversor_id AND l.loc::date BETWEEN i.valido_desde AND i.valido_hasta
JOIN gold.dim_fecha f ON f.fecha = l.loc::date
ORDER BY e.inicio_utc, e.inversor_id, e.tipo_evento;

-- ---------------- fact_contexto ----------------
INSERT INTO gold.fact_contexto
SELECT c.contexto_id, to_char(l.loc, 'YYYYMMDD')::int,
       (extract(hour FROM l.loc) * 12 + floor(extract(minute FROM l.loc) / 5))::smallint,
       i.inversor_key, t.tipo_contexto_key, c.inicio_utc, c.fin_utc,
       extract(epoch FROM (c.fin_utc - c.inicio_utc)) / 60, c.esfuerzo, c.atributos
FROM silver.contexto c
CROSS JOIN LATERAL (SELECT c.inicio_utc AT TIME ZONE current_setting('etl.zona') AS loc) l
JOIN gold.dim_tipo_contexto t USING (fuente, tipo_contexto, dispositivo)
JOIN gold.dim_inversor i
  ON i.inversor_id = COALESCE(c.inversor_id, 0) AND l.loc::date BETWEEN i.valido_desde AND i.valido_hasta;

-- ---------------- Conciliacion contra los contadores del inversor ----------------
-- El inversor lleva contadores acumulados de energia (tabla statistics). Para cada dia se
-- compara el avance del contador (ultimo - primer valor del dia) con la energia que el ETL
-- integro ese mismo dia, y se resume por inversor y mes. Solo entran los dias "conciliables":
-- contador presente, creciente y sin reinicio (0 <= avance < 100 kWh).
INSERT INTO audit.conciliacion
WITH dia AS (
    SELECT c.inversor_id, c.fecha_local, to_char(c.fecha_local, 'YYYY-MM') AS anio_mes, v.magnitud,
           v.fin - v.ini AS kwh_contador
    FROM silver.contador_diario c
    CROSS JOIN LATERAL (VALUES ('solar', c.solar_ini_kwh, c.solar_fin_kwh),
                               ('carga', c.carga_ini_kwh, c.carga_fin_kwh),
                               ('red',   c.red_ini_kwh,   c.red_fin_kwh)) AS v(magnitud, ini, fin)
    WHERE v.fin - v.ini >= 0 AND v.fin - v.ini < 100
), integrado AS (
    SELECT i.inversor_id, f.fecha AS fecha_local,
           SUM(h.e_solar_kwh) AS solar, SUM(h.e_carga_kwh) AS carga,
           SUM(h.e_red_kwh - h.e_red_a_bat_kwh) AS red, SUM(h.seg_observados) AS seg
    FROM gold.fact_energia_5min h
    JOIN gold.dim_inversor i USING (inversor_key)
    JOIN gold.dim_fecha f USING (fecha_key)
    GROUP BY 1, 2
)
SELECT current_setting('etl.ejecucion_id')::bigint, d.inversor_id, d.anio_mes, d.magnitud,
       COUNT(*),
       SUM(d.kwh_contador),
       SUM(COALESCE(CASE d.magnitud WHEN 'solar' THEN g.solar WHEN 'carga' THEN g.carga ELSE g.red END, 0)),
       round((100 * SUM(COALESCE(g.seg, 0)) / (COUNT(*) * 86400.0))::numeric, 2),
       round((100 * (SUM(COALESCE(CASE d.magnitud WHEN 'solar' THEN g.solar WHEN 'carga' THEN g.carga ELSE g.red END, 0))
                     - SUM(d.kwh_contador)) / NULLIF(SUM(d.kwh_contador), 0))::numeric, 2)
FROM dia d
LEFT JOIN integrado g USING (inversor_id, fecha_local)
GROUP BY d.inversor_id, d.anio_mes, d.magnitud;
