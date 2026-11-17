# F. Base de datos

## F.1 DDL y administración

El DDL está en `sql/init/` y PostgreSQL lo ejecuta solo en el primer arranque (carpeta
`/docker-entrypoint-initdb.d`, montada desde un ConfigMap):

| Archivo | Contenido |
| --- | --- |
| `00_roles.sh` | Roles de aplicación con las contraseñas del Secret |
| `01_bronze_silver.sql` | Esquemas `bronze`, `silver`, `audit` |
| `02_gold_dimensional.sql` | Esquema `gold` (dimensiones y hechos), `audit.conciliacion`, esquema `live` |
| `03_vistas.sql` | Vistas de KPI y de consumo |
| `04_permisos.sql` | Permisos por rol |

**Administración desde DBeaver.** Conexión PostgreSQL a `localhost`, puerto `15432`, base
`microrred`. Para consulta: usuario `bi_lectura`; para administración: `postgres`. Las contraseñas
están en `.env` (`BI_PASSWORD`, `POSTGRES_PASSWORD`). Desde DBeaver se revisa el diagrama ER del
esquema `gold`, se ejecuta `sql/consultas_negocio.sql` y se inspeccionan los planes con `EXPLAIN`.

Tamaño real: la base completa pesa 120 MB; `fact_energia_5min` con sus índices, 36 MB.

## F.2 Restricciones e índices

**Restricciones.** PK en todas las tablas; FK de cada hecho hacia sus dimensiones; `UNIQUE` en las
llaves naturales (`dim_fecha.fecha`, `dim_inversor(inversor_id, valido_desde)`, `dim_tipo_evento.codigo`);
`CHECK` para dominios (energías ≥ 0, SOC entre 0 y 100, `n_validas ≤ n_lecturas`, segundos
observados ≤ 300, `fin ≥ inicio`, severidad en una lista cerrada, `inversor_id` en (1, 2)).
Las restricciones son la última barrera de calidad: una carga que las viole revierte la transacción.

**Índices**, justificados por el tipo de consulta y el volumen (179 mil filas en el hecho principal;
se proyectan unos 190 mil por año para dos inversores):

| Índice | Tipo | Consulta que atiende |
| --- | --- | --- |
| PK `fact_energia_5min (fecha_key, tiempo_key, inversor_key)` | B-tree | Rangos de fechas (filtros de Power BI), el filtro más frecuente |
| `fact_energia_inversor_fecha_idx (inversor_key, fecha_key)` | B-tree | Serie de un inversor en un rango; lo usa el simulador para buscar el intervalo que reproduce |
| `fact_energia_ts_idx (ts_utc)` | B-tree | Ventanas de tiempo y el cruce por intervalo con el contexto (P6) |
| `fact_evento_fecha_idx (fecha_key, tipo_evento_key)` | B-tree | Eventos por periodo y tipo |
| `fact_contexto_fecha_idx`, `fact_contexto_intervalo_idx (inicio_utc, fin_utc)` | B-tree | Contexto vigente en un instante |
| `fact_contexto_atributos_gin` | **GIN `jsonb_path_ops`** | Operadores `@>` y `@?` sobre el JSON; más compacto que el GIN por defecto |
| `lectura_ts_idx (ts DESC)` en `live.lectura` | B-tree | "Última lectura" y ventanas recientes de Grafana |

**Lo que se descartó.** Particionar por mes y usar índices BRIN solo se justifica con decenas de
millones de filas; con 179 mil, un B-tree cabe en memoria y particionar complicaría las llaves. Si la
telemetría se guardara cruda (3 millones de filas por año, o Modbus en directo), sí convendría
particionar por tiempo o usar TimescaleDB.

## F.3 Consulta sobre el JSON con operadores nativos

Archivo `sql/consultas_negocio.sql`, consultas P6, P6b y P6c. Operadores usados: `@>` (contiene),
`?` (existe la llave), `->>` y `#>>` (extraer texto), `jsonb_path_exists` (ruta JSONPath).

```sql
-- P6. Cuanto consume una estacion mientras entrena un modelo en GPU?
WITH gpu AS (
    SELECT c.inicio_utc, c.fin_utc
    FROM gold.fact_contexto c
    WHERE c.atributos @> '{"task_type": "CNN fitting, GPU load"}'   -- contiene
      AND c.atributos ? 'model'                                     -- existe la llave
)
SELECT ... potencia media de la carga con y sin entrenamiento ...
```

| Situación | Intervalos de 5 min | Potencia media de la carga |
| --- | ---: | ---: |
| Entrenando en GPU | 5 921 | 347 W |
| Sin entrenamiento | 7 806 | 291 W |

Un entrenamiento añade en promedio **56 W (+19 %)** a la carga del inversor 1 durante el periodo
con registros de GPU (noviembre de 2025 a enero de 2026).

## F.4 Consultas que responden preguntas de negocio

Resultados completos en `docs/evidencias/09_consultas_negocio.txt` (ejecutadas dentro del clúster).

| # | Pregunta | Técnica SQL | Hallazgo |
| --- | --- | --- | --- |
| P1 | ¿De dónde viene y a dónde va la energía, mes a mes? | Agregaciones sobre la vista mensual | Inversor 2: 4 070 kWh a la carga, 3 208 kWh comprados, 1 375 kWh solares |
| P2 | ¿Cómo cambió la generación solar frente al mes anterior? | `LAG() OVER (PARTITION BY … ORDER BY …)`, normalizada por disponibilidad | Comparativo entre periodos sin el sesgo de los huecos |
| P3 | ¿Cuáles fueron los 5 días de mayor compra a la red? | `RANK() OVER (PARTITION BY inversor …)` | Inversor 2: 38,1 kWh el 22-ene-2026 (37 769 COP en un día) |
| P4 | ¿En qué franja horaria se compra energía? | `SUM() OVER (PARTITION BY …)` para el % del total + dimensión de tiempo | Noche + madrugada concentran el 84,6 % (inv. 1) y el 82,7 % (inv. 2) de la compra; al mediodía solar casi no se compra (0,3 % y 3,7 %) |
| P5 | ¿Cuál es la tendencia de la autosuficiencia? | Promedio móvil: `ROWS BETWEEN 6 PRECEDING AND CURRENT ROW` | Suaviza la variación diaria por nubosidad |
| P6 | ¿Cuánto consume un entrenamiento en GPU? | JSON nativo + `EXISTS` por intervalo | +56 W (+19 %) |
| P7 | ¿Cuántas horas al mes en batería baja, sin red o sin salida? | Hecho de eventos + dimensiones | Batería baja del inversor 2 concentrada en febrero y marzo de 2026 |
| P8 | ¿Se consume distinto en día laboral, fin de semana y festivo? | Agregación por `tipo_dia` | La climatización (inv. 2) consume **más en festivos** (20,9 kWh/día) que en días laborales (15,4): la carga no sigue el calendario académico |
| P9 | ¿Cambió el comportamiento tras modificar la prioridad de carga? | SCD tipo 2 | Compra a la red del inversor 2: de 12,90 a 8,48 kWh/día |
| P10 | ¿Qué importación de red es anormal? | `percentile_cont … WITHIN GROUP` | P99 = 1 392 W y 2 397 W: sustenta el umbral de 3 000 W de la alerta |
| P11 | ¿La energía cargada coincide con los contadores? | Conciliación | Carga −0,45 %, solar +1,29 % |
