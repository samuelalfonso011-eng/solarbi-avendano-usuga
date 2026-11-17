-- =====================================================================
-- Capas Bronze (metadatos de procedencia) y Silver (datos limpios)
-- La fuente Bronze es el archivo SQLite inmutable; en PostgreSQL solo se
-- registra su procedencia y cada ejecucion de ingestion.
-- =====================================================================
SET ROLE etl_app;

CREATE SCHEMA bronze;
CREATE SCHEMA silver;
CREATE SCHEMA audit;

CREATE TABLE audit.etl_ejecucion (
    ejecucion_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    inicio_utc        timestamptz NOT NULL DEFAULT now(),
    fin_utc           timestamptz,
    estado            text NOT NULL DEFAULT 'EN_CURSO' CHECK (estado IN ('EN_CURSO','OK','ERROR')),
    version_etl       text NOT NULL,
    parametros        jsonb NOT NULL,
    filas_fuente      bigint,
    filas_silver      bigint,
    filas_gold        bigint,
    huella_resultado  text,
    mensaje           text
);
COMMENT ON TABLE audit.etl_ejecucion IS
  'Bitacora de corridas del ETL. Una huella_resultado identica entre corridas demuestra la idempotencia.';

CREATE TABLE bronze.ingesta (
    ejecucion_id   bigint PRIMARY KEY REFERENCES audit.etl_ejecucion,
    archivo        text NOT NULL,
    bytes          bigint NOT NULL,
    sha256         text,
    doi            text NOT NULL,
    licencia       text NOT NULL,
    inventario     jsonb NOT NULL
);
COMMENT ON TABLE bronze.ingesta IS
  'Procedencia del archivo Bronze leido en cada corrida (el SQLite nunca se modifica).';

-- Efecto de cada regla de calidad: conteos antes y despues, por inversor
CREATE TABLE silver.calidad_regla (
    ejecucion_id    bigint NOT NULL REFERENCES audit.etl_ejecucion,
    orden           smallint NOT NULL,
    regla           text NOT NULL,
    descripcion     text NOT NULL,
    tipo            text NOT NULL CHECK (tipo IN ('RECHAZA_FILA','ANULA_CAMPO','CLASIFICA_EVENTO')),
    inversor_id     smallint NOT NULL,
    filas_antes     bigint NOT NULL,
    filas_afectadas bigint NOT NULL,
    filas_despues   bigint NOT NULL,
    PRIMARY KEY (ejecucion_id, orden, inversor_id)
);

-- Lecturas limpias agregadas a 5 minutos (llaves naturales)
CREATE TABLE silver.medicion_5min (
    inversor_id        smallint NOT NULL CHECK (inversor_id IN (1,2)),
    ts_utc             timestamptz NOT NULL,
    n_lecturas         integer NOT NULL CHECK (n_lecturas >= 0),
    n_validas          integer NOT NULL CHECK (n_validas >= 0),
    seg_observados     real NOT NULL CHECK (seg_observados >= 0 AND seg_observados <= 300.01),
    e_solar_wh         double precision NOT NULL CHECK (e_solar_wh >= 0),
    e_carga_wh         double precision NOT NULL CHECK (e_carga_wh >= 0),
    e_red_wh           double precision NOT NULL CHECK (e_red_wh >= 0),
    e_bat_carga_wh     double precision NOT NULL CHECK (e_bat_carga_wh >= 0),
    e_bat_descarga_wh  double precision NOT NULL CHECK (e_bat_descarga_wh >= 0),
    e_red_a_bat_wh     double precision NOT NULL CHECK (e_red_a_bat_wh >= 0),
    p_solar_max_w      real,
    p_carga_max_w      real,
    p_red_max_w        real,
    soc_prom           real CHECK (soc_prom BETWEEN 0 AND 100),
    soc_min            real,
    soc_max            real,
    soc_fin            real,
    v_bateria_prom     real,
    temp_max_c         real,
    seg_sin_red        real NOT NULL DEFAULT 0,
    seg_salida_apagada real NOT NULL DEFAULT 0,
    seg_bateria_baja   real NOT NULL DEFAULT 0,
    CHECK (n_validas <= n_lecturas),
    PRIMARY KEY (inversor_id, ts_utc)
);
COMMENT ON TABLE silver.medicion_5min IS
  'Grano: un inversor x un intervalo de 5 min con al menos una lectura cruda. Energia integrada desde las lecturas validas (retencion del ultimo valor; los huecos > 10 min no se integran).';

-- Episodios de eventos operativos detectados en la telemetria
CREATE TABLE silver.evento (
    inversor_id   smallint NOT NULL,
    tipo_evento   text NOT NULL,
    inicio_utc    timestamptz NOT NULL,
    fin_utc       timestamptz NOT NULL,
    n_lecturas    integer NOT NULL,
    valor_extremo real,
    detalle       jsonb,
    CHECK (fin_utc >= inicio_utc),
    PRIMARY KEY (inversor_id, tipo_evento, inicio_utc)
);

-- Registros de contexto (JSON) limpios y minimizados (Ley 1581 de 2012)
CREATE TABLE silver.contexto (
    contexto_id     integer PRIMARY KEY,
    registrado_utc  timestamptz NOT NULL,
    inicio_utc      timestamptz NOT NULL,
    fin_utc         timestamptz NOT NULL,
    fuente          text NOT NULL,
    tipo_contexto   text NOT NULL,
    dispositivo     text NOT NULL,
    inversor_id     smallint,
    esfuerzo        text,
    descripcion     text,
    atributos       jsonb NOT NULL,
    CHECK (fin_utc >= inicio_utc)
);
CREATE INDEX contexto_intervalo_idx ON silver.contexto (inicio_utc, fin_utc);

-- Historia de configuracion de cada inversor (origen de la SCD tipo 2)
CREATE TABLE silver.config_inversor (
    inversor_id        smallint NOT NULL,
    valido_desde       date NOT NULL,
    valido_hasta       date NOT NULL,
    prioridad_salida   smallint,
    prioridad_carga    smallint,
    soc_bateria_llena  smallint,
    PRIMARY KEY (inversor_id, valido_desde)
);

-- Contadores acumulados del propio inversor (tabla statistics): base de la conciliacion
CREATE TABLE silver.contador_diario (
    inversor_id      smallint NOT NULL,
    fecha_local      date NOT NULL,
    solar_ini_kwh    double precision,   -- contador al inicio / fin del dia (kWh acumulados)
    solar_fin_kwh    double precision,
    carga_ini_kwh    double precision,
    carga_fin_kwh    double precision,
    red_ini_kwh      double precision,
    red_fin_kwh      double precision,
    n_muestras       integer NOT NULL,
    PRIMARY KEY (inversor_id, fecha_local)
);
COMMENT ON TABLE silver.contador_diario IS
  'Primer y ultimo valor diario (filtrados por mediana) de los contadores acumulados pvgeneratenergytotal, usedenergytotal y loadconsumlinetotal (kWh).';
