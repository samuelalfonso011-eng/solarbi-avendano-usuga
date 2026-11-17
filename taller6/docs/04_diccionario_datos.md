# D. Diccionario de datos

Convenciones: PK = llave primaria, FK = llave foránea. "Origen" es el linaje (*data lineage*):
tabla y columna de la fuente SQLite, o la regla con la que se deriva. Las horas se guardan en UTC
(`timestamptz`); las llaves de fecha y tiempo se calculan en la hora local del sitio (`Asia/Shanghai`).

## D.1 Unidades y signos de las variables físicas, con su evidencia

| Variable de la fuente | Unidad | Signo / significado | Evidencia usada para deducirlo |
| --- | --- | --- | --- |
| `read_ts` | s (Unix, UTC) | Instante en que se escribió la lectura | README del dataset ("fractional Unix seconds in UTC") y diccionario de columnas |
| `pv1power` | W | Potencia del arreglo FV, ≥ 0 | Diccionario ("PV input-channel 1 active power"); coincide con `pv1volt` × `pv1curr` (error medio 1,1–1,5 % según la validación de los autores); es 0 de noche |
| `outw_a` | W | Potencia activa entregada a la carga | Diccionario (W); `outw_a` ≤ `outva_a` (potencia aparente); su integral coincide con el contador `usedenergytotal` (−0,45 %) |
| `linepowerw_a` | W | **Potencia importada de la red**, ≥ 0 | Coincide con `linevolta` × `linecurra`; es 0 cuando `linevolta` = 0; cierra el balance FV + batería + red − carga con un residuo constante de ~100 W (consumo propio). El artículo confirma que no se puede vender energía |
| `gridpowerw_a` | W | **No se usa**: vale ~60 W casi constante y no cierra el balance | Balance con `gridpowerw_a` da residuos de −64 a −311 W |
| `battvolt` | V | Tensión del banco (48 V nominal) | Diccionario; rango observado 43–57,6 V; ajustes `battlowvolt` = 43,2 y `cvvolt` = 57,6 |
| `battcurr` | A | **Positiva = descarga, negativa = carga** | Diccionario ("positive denotes discharge"); con corriente negativa, `battchgpower` ≈ `battvolt` × |`battcurr`| |
| `battsoc` | % | Estado de carga, 0–100 | Diccionario; rango observado 6–100 |
| `linechgcurr` | A | Corriente de carga de batería desde la red | Diccionario (A); solo es > 0 cuando hay potencia de red |
| `linevolta`, `outvolta` | V | Tensión de red y de salida (230 V nominal) | Diccionario; 0 cuando la red o la salida están ausentes |
| `temper1`…`temper4` | °C | Temperaturas internas; `temper4` = 120 es un centinela | Diccionario; nota de calidad de los propios autores en el contexto (`telemetry_quality_note`) |
| `pvgeneratenergytotal`, `usedenergytotal`, `loadconsumlinetotal` | kWh | Contadores acumulados (primer elemento del arreglo JSON) | Avanzan de forma monótona; su avance diario coincide con la energía integrada (solar +1,29 %, carga −0,45 %) |
| Capacidad de batería | 10,24 kWh | Supuesto declarado | `settings.battpackrateah` = 200 Ah (inversor 1) × 51,2 V (16 celdas LFP; `cvvolt` = 57,6 V = 16 × 3,6 V). El inversor 2 reporta 0 Ah: se asume el mismo banco |

## D.2 Capa Gold

### `gold.fact_energia_5min` — flujo de energía
Grano: un inversor × un intervalo de 5 minutos. PK (`fecha_key`, `tiempo_key`, `inversor_key`).

| Columna | Tipo | Llave | Descripción | Origen y regla de transformación |
| --- | --- | --- | --- | --- |
| `fecha_key` | integer | PK, FK → `dim_fecha` | Fecha local AAAAMMDD | `read_ts` truncado a 5 min, convertido a `Asia/Shanghai` |
| `tiempo_key` | smallint | PK, FK → `dim_tiempo` | Intervalo del día (0–287) | hora × 12 + minuto / 5 de la hora local |
| `inversor_key` | smallint | PK, FK → `dim_inversor` | Versión del inversor vigente en la fecha | `inverter` + vigencia SCD 2 |
| `ts_utc` | timestamptz | — | Inicio del intervalo en UTC | `floor(read_ts / 300) × 300` |
| `e_solar_kwh` | double | — | Energía FV generada | Σ `pv1power` × Δt / 3,6·10⁶ |
| `e_carga_kwh` | double | — | Energía entregada a la carga | Σ `outw_a` × Δt |
| `e_red_kwh` | double | — | Energía importada de la red | Σ `linepowerw_a` × Δt |
| `e_bat_carga_kwh` | double | — | Energía que entra a la batería | Σ max(−`battvolt` × `battcurr`, 0) × Δt |
| `e_bat_descarga_kwh` | double | — | Energía que sale de la batería | Σ max(`battvolt` × `battcurr`, 0) × Δt, con la banda de reposo (regla A2) en 0 |
| `e_red_a_bat_kwh` | double | — | Parte de la energía de red usada para cargar la batería | Σ `battvolt` × `linechgcurr` × Δt |
| `p_solar_max_w`, `p_carga_max_w`, `p_red_max_w` | real | — | Potencia máxima del intervalo | MAX de `pv1power`, `outw_a`, `linepowerw_a` |
| `soc_prom`, `soc_min`, `soc_fin` | real | — | SOC promedio (ponderado por tiempo), mínimo y último | `battsoc` |
| `temp_max_c` | real | — | Temperatura interna máxima | MAX(`temper1`…`temper3`) sin el centinela 120 |
| `seg_observados` | real | — | Segundos del intervalo cubiertos por lecturas válidas (0–300) | Σ Δt con Δt ≤ 600 s |
| `seg_sin_red`, `seg_salida_apagada`, `seg_bateria_baja` | real | — | Segundos en cada estado operativo | `linevolta` < 100; `outvolta` < 100; `battsoc` ≤ 15 |
| `n_lecturas`, `n_validas` | integer | — | Lecturas crudas y lecturas que pasaron las reglas | conteo por intervalo |

### `gold.fact_evento` — eventos operativos
Grano: un episodio. PK `evento_id`; único (`inversor_key`, `tipo_evento_key`, `inicio_utc`).

| Columna | Tipo | Llave | Descripción | Origen |
| --- | --- | --- | --- | --- |
| `evento_id` | bigint | PK | Identificador | generado en orden determinista |
| `fecha_key`, `tiempo_key` | integer, smallint | FK | Fecha e intervalo local del inicio | `inicio_utc` |
| `inversor_key` | smallint | FK | Inversor (versión vigente) | `inverter` |
| `tipo_evento_key` | smallint | FK → `dim_tipo_evento` | Tipo de evento | regla que lo detectó |
| `inicio_utc`, `fin_utc` | timestamptz | — | Inicio y fin del episodio | primera y última lectura del estado; para fallas, `faulthistoryrecord00_time` |
| `duracion_min` | double | — | Duración | `fin_utc` − `inicio_utc` |
| `n_lecturas` | integer | — | Lecturas dentro del episodio | conteo |
| `valor_extremo` | real | — | SOC mínimo del episodio; código de la falla; horas del hueco | `battsoc`; primer elemento de `faulthistoryrecord00` |
| `detalle` | jsonb | — | Banderas de alarma o código de falla | `status.sysalarmflag`, `fault_history` |

### `gold.fact_contexto` — contexto de las cargas
Grano: un registro de contexto. PK `contexto_id` (el `id` de la fuente).

| Columna | Tipo | Llave | Descripción | Origen |
| --- | --- | --- | --- | --- |
| `contexto_id` | integer | PK | Identificador de la fuente | `context.id` |
| `fecha_key`, `tiempo_key` | integer, smallint | FK | Fecha e intervalo local del inicio | `context.start` |
| `inversor_key` | smallint | FK | Inversor; 0 si aplica a toda la instalación | `value.inverter`; 0 cuando `device` = `installation` |
| `tipo_contexto_key` | smallint | FK → `dim_tipo_contexto` | Fuente + tipo + dispositivo | `value.source`, `value.context_type`, `value.device` |
| `inicio_utc`, `fin_utc` | timestamptz | — | Intervalo al que aplica | `context.start`, `context.end` |
| `duracion_min` | double | — | Duración | `end` − `start` |
| `esfuerzo` | text | — | Esfuerzo estimado de la tarea | `value.llm_estimated_task_effort` |
| `atributos` | jsonb | — | JSON original **sin los campos sensibles** (ver sección J) | `context.value` minimizado |

### Dimensiones

| Tabla | Columna | Tipo | Llave | Descripción / origen |
| --- | --- | --- | --- | --- |
| `dim_fecha` | `fecha_key` | integer | PK | AAAAMMDD |
| | `fecha` | date | único | Calendario generado entre la primera y la última fecha de los datos |
| | `anio`, `trimestre`, `mes`, `nombre_mes`, `anio_mes`, `semana_iso`, `dia_mes`, `dia_semana`, `nombre_dia` | varios | — | Derivados de `fecha` |
| | `es_fin_semana` | boolean | — | Sábado o domingo |
| | `es_festivo` | boolean | — | Fecha cubierta por una anotación manual del contexto cuya descripción contiene "Holiday" |
| | `tipo_dia` | text | — | Laboral / Fin de semana / Festivo |
| `dim_tiempo` | `tiempo_key` | smallint | PK | 0–287 |
| | `hora`, `minuto`, `etiqueta` | varios | — | Derivados del intervalo |
| | `franja_horaria`, `orden_franja` | text, smallint | — | Madrugada 00–06, Mañana 06–10, Mediodía solar 10–15, Tarde 15–18, Noche 18–24 |
| | `periodo_solar` | text | — | Diurno 06–18 / Nocturno |
| | `turno` | text | — | Laboral 08–18 / No laboral |
| `dim_inversor` | `inversor_key` | smallint | PK | Llave sustituta de la versión |
| | `inversor_id` | smallint | natural | `inverter` (1, 2); 0 = instalación completa |
| | `nombre`, `carga_principal` | text | — | Carga principal según el artículo de los autores |
| | `prioridad_salida`, `prioridad_carga`, `soc_bateria_llena` | smallint | — | `settings.outpriority`, `chgpriority`, `battfullsoc` (moda diaria) |
| | `capacidad_bateria_kwh` | numeric | — | Parámetro `BATERIA_KWH` (ver D.1) |
| | `valido_desde`, `valido_hasta`, `es_actual` | date, date, boolean | — | Vigencia SCD tipo 2 |
| `dim_tipo_evento` | `tipo_evento_key` | smallint | PK | — |
| | `codigo`, `nombre`, `categoria`, `severidad`, `origen`, `es_dato_invalido` | text, boolean | — | Catálogo definido por el equipo |
| `dim_tipo_contexto` | `tipo_contexto_key` | smallint | PK | — |
| | `fuente`, `tipo_contexto`, `dispositivo` | text | único | `value.source`, `value.context_type`, `value.device` |
| | `categoria` | text | — | Agrupación del equipo (carga de cómputo, sistema operativo, calendario y sol…) |
| `gold.tarifa` | `vigente_desde` | date | PK | Parámetro `TARIFA_VIGENTE_DESDE` |
| | `cop_kwh`, `fuente` | numeric, text | — | Parámetros `TARIFA_COP_KWH` y `TARIFA_FUENTE` |

## D.3 Capas Silver, Bronze, auditoría y tiempo real

| Tabla | Grano / contenido | Llave |
| --- | --- | --- |
| `silver.medicion_5min` | Igual que el hecho de energía, con llaves naturales (`inversor_id`, `ts_utc`) y energías en Wh | PK (`inversor_id`, `ts_utc`) |
| `silver.evento` | Episodios con llaves naturales | PK (`inversor_id`, `tipo_evento`, `inicio_utc`) |
| `silver.contexto` | Contexto limpio y minimizado | PK `contexto_id` |
| `silver.config_inversor` | Versiones de configuración por inversor | PK (`inversor_id`, `valido_desde`) |
| `silver.contador_diario` | Primer y último valor diario de los contadores acumulados | PK (`inversor_id`, `fecha_local`) |
| `silver.calidad_regla` | Filas antes, afectadas y después por regla, inversor y corrida | PK (`ejecucion_id`, `orden`, `inversor_id`) |
| `bronze.ingesta` | Procedencia del archivo leído: nombre, bytes, SHA-256, DOI, licencia, inventario | PK `ejecucion_id` |
| `audit.etl_ejecucion` | Bitácora de corridas: estado, parámetros, conteos, huella del resultado | PK `ejecucion_id` |
| `audit.conciliacion` | Energía integrada frente a contadores del inversor, por mes | PK (`ejecucion_id`, `inversor_id`, `anio_mes`, `magnitud`) |
| `live.lectura` | Lecturas del simulador (una por inversor y minuto), con el intervalo histórico que reproducen | PK (`inversor_id`, `ts`) |
