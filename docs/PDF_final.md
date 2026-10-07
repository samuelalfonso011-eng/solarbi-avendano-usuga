---
title: "SolarBI Pascual"
---

<div class="cover">
<p class="cover-inst">Institución Universitaria Pascual Bravo</p>
<p class="cover-course">Inteligencia de Negocios · Grupo 50 · 2026-II</p>
<p class="cover-label">Trabajo de consulta</p>
<h1 class="cover-title">SolarBI Pascual</h1>
<p class="cover-sub">Power BI y Grafana, gobernanza de datos, automatización ETL e IoT</p>
<div class="cover-names">
<p><strong>Integrante 1:</strong> Samuel Alfonso Avendaño</p>
<p><strong>Integrante 2:</strong> Juan Andres Usuga</p>
</div>
<p class="cover-teacher"><strong>Docente:</strong> Ramiro Grisales Montoya</p>
<p class="cover-date">7 de octubre de 2026</p>
</div>

<div class="pagebreak"></div>

# PARTE A — Consulta teórica

INCLUDE:parte_a_respuestas.md

<div class="pagebreak"></div>

# PARTE B — Práctica

## Paso 1 — Bronze

**Procedimiento:** se ejecutó `python3 etl/simulador.py`, que genera 3 días ×
288 lecturas/día (864 lecturas base) de un inversor de 5 kWp, inyectando
anomalías controladas (potencia negativa, irradiancia faltante, filas
duplicadas). Salida real de la ejecución:

```
=== Simulador SolarBI Pascual — resumen de ejecución ===
lecturas_base: 864
potencia_negativa_inyectada: 6
irradiancia_faltante_inyectada: 8
duplicados_inyectados: 8
total_filas_bronze: 872
Archivo generado: data/bronze/lecturas_bronze.csv
```

*Explicación:* el archivo Bronze resultante (872 filas, incluyendo las
anomalías inyectadas) se trata como crudo e inmutable a partir de este
punto; ninguna etapa posterior lo modifica.

## Paso 2 — Silver

**Procedimiento:** `etl/run_etl.py` leyó el Bronze y aplicó las 3 reglas de
calidad. Salida real:

```
--- Métricas de calidad (Silver) ---
filas_leidas: 872
filas_rechazadas_por_rango: 5
filas_rechazadas_por_duplicados: 7
filas_rechazadas_por_faltantes: 8
filas_validas: 852
porcentaje_datos_validos: 97.71
```

*Explicación:* `porcentaje_datos_validos = filas_validas / filas_leidas ×
100 = 852 / 872 × 100 = 97.71 %`. Las 20 filas rechazadas se reparten en las
tres reglas (rango físico, duplicados, faltantes), cada una contada una sola
vez por fila.

## Paso 3 — PostgreSQL / Gold

**Procedimiento:** se crearon los esquemas con `psql -f sql/tables.sql` y el
ETL cargó `silver.lectura_5min` y agregó `dwh.fact_energia_dia` con UPSERT.
Consulta real ejecutada contra PostgreSQL:

```
SELECT * FROM dwh.fact_energia_dia ORDER BY fecha_key;

 fecha_key  | dispositivo_key | energia_kwh | pct_datos_validos
------------+------------------+-------------+--------------------
 2026-09-01 | INV-01           |      29.299 |              97.71
 2026-09-02 | INV-01           |      29.479 |              97.71
 2026-09-03 | INV-01           |      28.715 |              97.71
```

*Explicación:* la energía diaria se calculó agregando
`p_ac_kw × 5/60` por día y dispositivo sobre las 852 lecturas válidas de
Silver; ~29 kWh/día en un inversor de 5 kWp corresponde a un Yield de
~5.8–5.9 kWh/kWp, un valor físicamente razonable para una planta solar.

## Idempotencia (obligatorio)

**Procedimiento:** se ejecutó `run_etl.py` **dos veces seguidas** sobre el
mismo Bronze. Salida real de ambas corridas:

```
>>> PRIMERA EJECUCIÓN
silver.lectura_5min: antes=0   -> después=852
dwh.fact_energia_dia: antes=0   -> después=3

>>> SEGUNDA EJECUCIÓN
silver.lectura_5min: antes=852 -> después=852
dwh.fact_energia_dia: antes=3   -> después=3
```

*Explicación:* los conteos se mantuvieron exactamente iguales en la segunda
corrida (852 y 3), demostrando idempotencia real gracias al `UPSERT` sobre
las claves `(ts, dispositivo_id)` y `(fecha_key, dispositivo_key)` — no es
una afirmación sin evidencia, son conteos verificados en PostgreSQL.

## Paso 4 — Power BI

**Estado:** no se ejecutó en este entorno (sin Power BI Desktop disponible
en el contenedor Linux donde se desarrolló el proyecto). Se documentó el
código propuesto, completo y ejecutable contra los nombres reales de tabla,
en `powerbi/medidas_dax.md`: conexión PostgreSQL en modo Import, parámetro
de tarifa y las medidas DAX `Energia Total`, `Yield`, `Ahorro Estimado` y
`Porcentaje Datos Validos`.

*Resultado esperado:* con los datos reales ya cargados (ver Paso 3), la
tarjeta de Yield debería mostrar ~5.8–5.9 kWh/kWp y el gráfico de energía
diaria replicar los 3 valores de `fact_energia_dia` de arriba.

*Captura que debe tomar el estudiante:* la página completa de Power BI
Desktop (3 tarjetas + gráfico de columnas) conectada a la base `solarbi`
real, generada siguiendo `powerbi/medidas_dax.md`.

## Paso 5 — Grafana

**Estado:** Grafana OSS no se pudo instalar en este entorno (descarga y
`apt-get` bloqueados por la política de red del contenedor; sin daemon
Docker disponible). Detalle completo del intento y el error real en
`docs/ruta_alternativa_grafana.md`. Se entrega el dashboard propuesto,
listo para importar, en `grafana/dashboard.json` (panel de series de tiempo
con `$__timeFilter`, panel de % de datos válidos con umbrales, y variable
`dispositivo`).

*Captura que debe tomar el estudiante:* al importar `dashboard.json` en una
instancia real de Grafana OSS conectada a la misma base `solarbi`, tomar
captura de ambos paneles con datos reales.

## Paso 6 — Reflexión

Ver `docs/reflexion_final.md` (máx. 10 líneas), incluida íntegra:

INCLUDE:reflexion_final.md

<div class="pagebreak"></div>

# PARTE C — GitHub

## Repositorio

Nombre propuesto: `solarbi-avendano-usuga` (público). Un integrante lo
crea y agrega al otro como colaborador; el colaborador debe aceptar la
invitación antes de entregar. **Enlace:** `[PENDIENTE: URL del repositorio
en GitHub]`.

## Colaboradores

**Captura pendiente:** pantalla de *Settings → Collaborators* mostrando a
los dos integrantes, a tomar una vez creado el repositorio real en GitHub.

## Commits

Mínimo 3 commits descriptivos por persona — propuesta completa en
`docs/commits_propuestos.md`. **Captura pendiente:** historial de commits
(`git log` o la vista de GitHub) mostrando ambos autores, una vez realizados
los commits reales.

## Estructura

```
solarbi-apellido1-apellido2/
├── README.md
├── .gitignore
├── .env.example
├── requirements.txt
├── docs/
│   ├── ruta_alternativa_grafana.md
│   ├── cron.md
│   ├── commits_propuestos.md
│   └── PDF de esta consulta
├── data/
│   ├── bronze/lecturas_bronze.csv
│   └── silver/lecturas_silver.csv
├── etl/
│   ├── simulador.py
│   └── run_etl.py
├── sql/
│   ├── tables.sql
│   └── cargas.sql
├── powerbi/
│   └── medidas_dax.md
└── grafana/
    └── dashboard.json
```

## README

Ver `README.md` completo en el repositorio (nombres, curso, grupo,
descripción, objetivo, arquitectura, tecnologías, instalación,
configuración, ejecución, estructura, proceso ETL, reglas de calidad,
PostgreSQL, Power BI, Grafana, reproducción y tabla de distribución del
trabajo).

<div class="pagebreak"></div>

# REFERENCIAS

1. Microsoft Learn. *What is Power BI.* https://learn.microsoft.com/power-bi/fundamentals/power-bi-overview
2. Microsoft Learn. *Incremental refresh for datasets.* https://learn.microsoft.com/power-bi/connect-data/incremental-refresh-overview
3. Microsoft Learn. *Power BI Projects (PBIP).* https://learn.microsoft.com/power-bi/developer/projects/projects-overview
4. Grafana Labs. *Grafana documentation.* https://grafana.com/docs/grafana/latest/
5. PostgreSQL Global Development Group. *INSERT ... ON CONFLICT.* https://www.postgresql.org/docs/current/sql-insert.html
6. DAMA International. *DAMA-DMBOK: Data Management Body of Knowledge*, 2.ª ed.
7. Congreso de Colombia. *Ley 1581 de 2012.* http://www.secretariasenado.gov.co/senado/basedoc/ley_1581_2012.html
8. MQTT.org / OASIS. *MQTT Version 5.0 Specification.* https://mqtt.org/mqtt-specification/
9. Modbus Organization. *Modbus Application Protocol Specification.* https://modbus.org/specs.php
10. Git. *Git Documentation.* https://git-scm.com/doc
