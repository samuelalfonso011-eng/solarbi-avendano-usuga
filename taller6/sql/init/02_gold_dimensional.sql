-- =====================================================================
-- Capa Gold: modelo dimensional (esquema en estrella, constelacion de 3 hechos)
--   fact_energia_5min  : flujo de energia        (grano: inversor x intervalo de 5 min)
--   fact_evento        : eventos operativos      (grano: un episodio por inversor)
--   fact_contexto      : contexto de las cargas  (grano: un registro de contexto)
-- Dimensiones conformadas: dim_fecha, dim_tiempo, dim_inversor (SCD tipo 2)
-- =====================================================================
SET ROLE etl_app;
CREATE SCHEMA gold;

-- ---------- Dimension fecha (construida, calendario local del sitio) ----------
CREATE TABLE gold.dim_fecha (
    fecha_key     integer PRIMARY KEY,              -- AAAAMMDD
    fecha         date NOT NULL UNIQUE,
    anio          smallint NOT NULL,
    trimestre     smallint NOT NULL CHECK (trimestre BETWEEN 1 AND 4),
    mes           smallint NOT NULL CHECK (mes BETWEEN 1 AND 12),
    nombre_mes    text NOT NULL,
    anio_mes      text NOT NULL,                    -- 'AAAA-MM'
    semana_iso    smallint NOT NULL,
    dia_mes       smallint NOT NULL,
    dia_semana    smallint NOT NULL CHECK (dia_semana BETWEEN 1 AND 7),   -- 1 = lunes
    nombre_dia    text NOT NULL,
    es_fin_semana boolean NOT NULL,
    es_festivo    boolean NOT NULL DEFAULT false,   -- derivado del contexto (calendario del campus)
    tipo_dia      text NOT NULL                     -- Laboral | Fin de semana | Festivo
);

-- ---------- Dimension tiempo (construida por el equipo: no existe en la fuente) ----------
CREATE TABLE gold.dim_tiempo (
    tiempo_key      smallint PRIMARY KEY CHECK (tiempo_key BETWEEN 0 AND 287),  -- intervalo de 5 min del dia
    hora            smallint NOT NULL CHECK (hora BETWEEN 0 AND 23),
    minuto          smallint NOT NULL,
    etiqueta        text NOT NULL,                  -- 'HH:MM'
    franja_horaria  text NOT NULL,                  -- Madrugada | Manana | Mediodia solar | Tarde | Noche
    orden_franja    smallint NOT NULL,
    periodo_solar   text NOT NULL,                  -- Diurno | Nocturno
    turno           text NOT NULL                   -- Laboral (08-18) | No laboral
);

-- ---------- Dimension inversor (SCD tipo 2 sobre la configuracion) ----------
CREATE TABLE gold.dim_inversor (
    inversor_key       smallint PRIMARY KEY,
    inversor_id        smallint NOT NULL,           -- llave natural (1, 2); 0 = toda la instalacion
    nombre             text NOT NULL,
    carga_principal    text NOT NULL,
    prioridad_salida   smallint,
    prioridad_carga    smallint,
    soc_bateria_llena  smallint,
    capacidad_bateria_kwh numeric(6,2),
    valido_desde       date NOT NULL,
    valido_hasta       date NOT NULL,
    es_actual          boolean NOT NULL,
    UNIQUE (inversor_id, valido_desde),
    CHECK (valido_hasta >= valido_desde)
);

-- ---------- Dimension tipo de evento ----------
CREATE TABLE gold.dim_tipo_evento (
    tipo_evento_key smallint PRIMARY KEY,
    codigo          text NOT NULL UNIQUE,
    nombre          text NOT NULL,
    categoria       text NOT NULL,                  -- Red | Bateria | Salida | Alarma | Falla | Telemetria
    severidad       text NOT NULL CHECK (severidad IN ('Informativa','Advertencia','Critica')),
    origen          text NOT NULL,                  -- como se detecta en la fuente
    es_dato_invalido boolean NOT NULL               -- false: evento real de operacion
);

-- ---------- Dimension tipo de contexto ----------
CREATE TABLE gold.dim_tipo_contexto (
    tipo_contexto_key smallint PRIMARY KEY,
    fuente            text NOT NULL,
    tipo_contexto     text NOT NULL,
    dispositivo       text NOT NULL,
    categoria         text NOT NULL,                -- Carga de computo | Sistema operativo | ...
    UNIQUE (fuente, tipo_contexto, dispositivo)
);

-- ---------- Tarifa (parametro externo, COP/kWh) ----------
CREATE TABLE gold.tarifa (
    vigente_desde date PRIMARY KEY,
    cop_kwh       numeric(10,2) NOT NULL CHECK (cop_kwh > 0),
    fuente        text NOT NULL
);

-- ---------- Hecho 1: flujo de energia ----------
CREATE TABLE gold.fact_energia_5min (
    fecha_key          integer  NOT NULL REFERENCES gold.dim_fecha,
    tiempo_key         smallint NOT NULL REFERENCES gold.dim_tiempo,
    inversor_key       smallint NOT NULL REFERENCES gold.dim_inversor,
    ts_utc             timestamptz NOT NULL,
    e_solar_kwh        double precision NOT NULL,
    e_carga_kwh        double precision NOT NULL,
    e_red_kwh          double precision NOT NULL,
    e_bat_carga_kwh    double precision NOT NULL,
    e_bat_descarga_kwh double precision NOT NULL,
    e_red_a_bat_kwh    double precision NOT NULL,
    p_solar_max_w      real,
    p_carga_max_w      real,
    p_red_max_w        real,
    soc_prom           real,
    soc_min            real,
    soc_fin            real,
    temp_max_c         real,
    seg_observados     real NOT NULL,
    seg_sin_red        real NOT NULL,
    seg_salida_apagada real NOT NULL,
    seg_bateria_baja   real NOT NULL,
    n_lecturas         integer NOT NULL,
    n_validas          integer NOT NULL,
    PRIMARY KEY (fecha_key, tiempo_key, inversor_key)
);
-- Consultas tipicas: rangos de fechas por inversor (Power BI) y ventanas de tiempo (Grafana).
-- ~190 mil filas/anio: bastan B-tree; la PK ya cubre fecha->tiempo->inversor.
CREATE INDEX fact_energia_inversor_fecha_idx ON gold.fact_energia_5min (inversor_key, fecha_key);
CREATE INDEX fact_energia_ts_idx ON gold.fact_energia_5min (ts_utc);

-- ---------- Hecho 2: eventos operativos ----------
CREATE TABLE gold.fact_evento (
    evento_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha_key        integer  NOT NULL REFERENCES gold.dim_fecha,
    tiempo_key       smallint NOT NULL REFERENCES gold.dim_tiempo,
    inversor_key     smallint NOT NULL REFERENCES gold.dim_inversor,
    tipo_evento_key  smallint NOT NULL REFERENCES gold.dim_tipo_evento,
    inicio_utc       timestamptz NOT NULL,
    fin_utc          timestamptz NOT NULL,
    duracion_min     double precision NOT NULL CHECK (duracion_min >= 0),
    n_lecturas       integer NOT NULL,
    valor_extremo    real,
    detalle          jsonb,
    UNIQUE (inversor_key, tipo_evento_key, inicio_utc)
);
CREATE INDEX fact_evento_fecha_idx ON gold.fact_evento (fecha_key, tipo_evento_key);

-- ---------- Hecho 3: contexto de las cargas ----------
CREATE TABLE gold.fact_contexto (
    contexto_id       integer PRIMARY KEY,
    fecha_key         integer  NOT NULL REFERENCES gold.dim_fecha,
    tiempo_key        smallint NOT NULL REFERENCES gold.dim_tiempo,
    inversor_key      smallint NOT NULL REFERENCES gold.dim_inversor,
    tipo_contexto_key smallint NOT NULL REFERENCES gold.dim_tipo_contexto,
    inicio_utc        timestamptz NOT NULL,
    fin_utc           timestamptz NOT NULL,
    duracion_min      double precision NOT NULL CHECK (duracion_min >= 0),
    esfuerzo          text,
    atributos         jsonb NOT NULL
);
CREATE INDEX fact_contexto_fecha_idx ON gold.fact_contexto (fecha_key, tipo_contexto_key);
CREATE INDEX fact_contexto_intervalo_idx ON gold.fact_contexto (inicio_utc, fin_utc);
-- GIN jsonb_path_ops: acelera @> y @? sobre el JSON (consultas nativas de la seccion F)
CREATE INDEX fact_contexto_atributos_gin ON gold.fact_contexto USING gin (atributos jsonb_path_ops);

-- ---------- Conciliacion contra los contadores del inversor ----------
CREATE TABLE audit.conciliacion (
    ejecucion_id      bigint NOT NULL REFERENCES audit.etl_ejecucion,
    inversor_id       smallint NOT NULL,
    anio_mes          text NOT NULL,
    magnitud          text NOT NULL,                -- solar | carga | red
    dias_conciliados  integer NOT NULL,             -- dias con contador valido (sin reinicio)
    kwh_contador      double precision,             -- avance del contador acumulado del inversor
    kwh_integrado     double precision NOT NULL,    -- energia integrada por el ETL
    cobertura_pct     double precision NOT NULL,    -- % del tiempo de esos dias con telemetria observada
    diferencia_pct    double precision,
    PRIMARY KEY (ejecucion_id, inversor_id, anio_mes, magnitud)
);

-- ---------- Datos casi en tiempo real (simulador) ----------
CREATE SCHEMA live;
CREATE TABLE live.lectura (
    ts            timestamptz NOT NULL,
    inversor_id   smallint NOT NULL CHECK (inversor_id IN (1,2)),
    p_solar_w     real NOT NULL,
    p_carga_w     real NOT NULL,
    p_red_w       real NOT NULL,
    p_bateria_w   real NOT NULL,            -- + descarga, - carga
    soc_pct       real NOT NULL CHECK (soc_pct BETWEEN 0 AND 100),
    red_disponible boolean NOT NULL,
    escenario     text NOT NULL,            -- normal | bateria_baja | sin_red
    ts_origen     timestamptz NOT NULL,     -- intervalo historico real que se reproduce
    insertado_utc timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (inversor_id, ts)
);
CREATE INDEX lectura_ts_idx ON live.lectura (ts DESC);
COMMENT ON TABLE live.lectura IS
  'Lecturas que escribe el simulador (CronJob): reproduce intervalos historicos reales re-fechados a "ahora". Nunca se mezcla con los hechos historicos.';
