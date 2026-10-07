# SolarBI Pascual

Power BI y Grafana, gobernanza de datos, automatización ETL e IoT — trabajo de
consulta de **Inteligencia de Negocios, Grupo 50, 2026-II**, Institución
Universitaria Pascual Bravo.

- **Integrante 1:** Samuel Alfonso Avendaño
- **Integrante 2:** Juana Andres Usuga Serna 
- **Docente:** Ramiro Grisales Montoya
- **Enfoque del grupo:** Calidad y desempeño (KPIs: % de datos válidos, yield,
  Performance Ratio, ahorro, disponibilidad, alarmas, energía)

## Descripción

SolarBI Pascual es una solución de punta a punta para telemetría de una
planta solar simulada (un inversor de 5 kWp), que compara **Power BI** y
**Grafana OSS** como herramientas de visualización sobre el mismo origen de
datos en **PostgreSQL**, con una capa de calidad de datos (Bronze → Silver →
Gold) y gobierno de datos documentado.

## Objetivo

Construir y documentar un flujo ETL reproducible e idempotente que alimente,
con los mismos datos, un tablero en Power BI y un dashboard en Grafana OSS,
evaluando cuál herramienta resuelve mejor cada necesidad (operativa,
analítica o estratégica) del caso SolarBI.

## Arquitectura

```
Simulador (etl/simulador.py)
        |
        v
  BRONZE (data/bronze/lecturas_bronze.csv, archivo crudo e inmutable)
        |
        v
  Reglas de calidad (rango físico, duplicados, faltantes)
        |
        v
  SILVER (silver.lectura_5min en PostgreSQL + data/silver/lecturas_silver.csv)
        |
        v
  GOLD / dwh.fact_energia_dia (PostgreSQL, agregado diario por dispositivo)
        |
        +----------------------+
        v                      v
    Power BI               Grafana OSS
  (medidas DAX:          (series de tiempo,
   Yield, Ahorro,         % datos válidos,
   Energía Total)         variable $dispositivo)
```

## Tecnologías

- **Python 3** (simulador y ETL, sin frameworks externos salvo `psycopg2`).
- **PostgreSQL 16** (capas Silver y Gold).
- **Power BI Desktop** (conector PostgreSQL, modo Import, medidas DAX).
- **Grafana OSS** (data source PostgreSQL, variables de dashboard, `$__timeFilter`).
- **Git/GitHub** para control de versiones y evidencia de colaboración.

## Instalación

Requisitos: Python 3.10+, PostgreSQL 14+ accesible, Power BI Desktop (Windows)
y Grafana OSS (instalador o Docker) en el equipo donde se tomen las capturas
finales.

```bash
git clone https://github.com/<usuario>/solarbi-apellido1-apellido2.git
cd solarbi-apellido1-apellido2
pip install -r requirements.txt   # psycopg2-binary
```

## Configuración

Copiar `.env.example` a `.env` (NO se sube al repositorio, ver `.gitignore`)
y completar las credenciales reales de PostgreSQL:

```
PGHOST=localhost
PGPORT=5432
PGDATABASE=solarbi
PGUSER=solarbi
PGPASSWORD=<tu_password_local>
```

Crear las tablas antes de la primera ejecución:

```bash
psql -h $PGHOST -U $PGUSER -d $PGDATABASE -f sql/tables.sql
```

## Ejecución

```bash
python3 etl/simulador.py   # genera data/bronze/lecturas_bronze.csv (864+ filas)
python3 etl/run_etl.py     # Bronze -> Silver -> Gold, un solo comando
python3 etl/run_etl.py     # segunda corrida: demuestra idempotencia (mismos conteos)
```

Power BI: conectar a PostgreSQL (ver `powerbi/medidas_dax.md`) y pegar las
medidas DAX documentadas allí.

Grafana: importar `grafana/dashboard.json` con PostgreSQL como data source
(ver `docs/ruta_alternativa_grafana.md` sobre el estado de esta evidencia en
el entorno donde se desarrolló el proyecto).

## Estructura del proyecto

```
solarbi-apellido1-apellido2/
├── README.md
├── .gitignore
├── requirements.txt
├── docs/
│   ├── ruta_alternativa_grafana.md
│   └── cron.md
├── data/
│   ├── bronze/lecturas_bronze.csv     (crudo, no se modifica)
│   └── silver/lecturas_silver.csv     (respaldo de las filas válidas)
├── etl/
│   ├── simulador.py
│   └── run_etl.py                      (único punto de entrada)
├── sql/
│   ├── tables.sql
│   └── cargas.sql
├── powerbi/
│   └── medidas_dax.md
└── grafana/
    └── dashboard.json
```

## Proceso ETL

1. **Bronze:** `simulador.py` genera 3 días × 288 lecturas/día (864 filas
   base) de un inversor de 5 kWp, con potencia, irradiancia y temperatura de
   módulo, e inyecta anomalías (potencia negativa, irradiancia faltante,
   duplicados). El CSV resultante es crudo y no se modifica nunca.
2. **Silver:** `run_etl.py` aplica 3 reglas de calidad (rango físico válido,
   duplicados, datos faltantes) y calcula `filas_leidas`,
   `filas_rechazadas_por_*`, `filas_validas` y `porcentaje_datos_validos`,
   que se guardan en `silver.metricas_calidad` para auditoría.
3. **Gold:** agrega `silver.lectura_5min` por día y dispositivo
   (`energia_intervalo_kwh = potencia_kw × 5/60`) y hace `UPSERT` sobre
   `dwh.fact_energia_dia` usando la clave `(fecha_key, dispositivo_key)`.

## Reglas de calidad

| Regla | Qué detecta |
|---|---|
| Rango físico válido | `p_ac_kw < 0` o mayor al máximo plausible del inversor; `irradiancia_wm2 < 0` |
| Duplicados | Filas exactamente repetidas (mismo timestamp, dispositivo y valores) |
| Datos faltantes | `ts`, `dispositivo_id`, `p_ac_kw` o `irradiancia_wm2` vacíos |

## PostgreSQL

Esquemas `silver` (lecturas limpias + métricas de calidad) y `dwh`
(`fact_energia_dia`). Ver `sql/tables.sql` y `sql/cargas.sql`.

## Power BI

Ver `powerbi/medidas_dax.md`: conexión, parámetro de tarifa y las medidas
DAX `Energia Total`, `Yield`, `Ahorro Estimado` y `Porcentaje Datos Validos`.

## Grafana

Ver `grafana/dashboard.json` (dashboard propuesto) y
`docs/ruta_alternativa_grafana.md` (estado real de esta evidencia).

## Instrucciones de reproducción

1. `psql -f sql/tables.sql` sobre una base PostgreSQL vacía.
2. `python3 etl/simulador.py`.
3. `python3 etl/run_etl.py` (ejecutar dos veces para verificar idempotencia).
4. Conectar Power BI y Grafana a la misma base y construir los tableros
   descritos arriba.

## Tabla de distribución del trabajo

| Integrante | Aportes |
|---|---|
| Samuel Alfonso Avendaño | `[PENDIENTE: detallar aportes]` |
| `[PENDIENTE: nombre completo integrante 2]` | `[PENDIENTE: detallar aportes]` |

*(Completar esta tabla con el reparto real de tareas y los commits de cada
quien antes de entregar — ver punto "Commits" más abajo.)*
