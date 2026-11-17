# G. Power BI

## G.1 Formato del proyecto: PBIP (TMDL + PBIR)

El proyecto está en `powerbi/MicrorredBI.pbip` en formato **Power BI Project (PBIP)**:

- `MicrorredBI.SemanticModel/definition/*.tmdl`: modelo semántico en **TMDL**, un archivo de texto
  por tabla (columnas, medidas DAX, particiones M), más `relationships.tmdl` y `expressions.tmdl`.
- `MicrorredBI.Report/definition/`: informe en **PBIR**, un JSON por página y por visual.

**Por qué PBIP y no `.pbix`.** Un `.pbix` es un binario comprimido: Git no puede mostrar qué cambió,
dos personas no pueden trabajar a la vez sin pisarse y además lleva los datos importados adentro
(pesado y con información que no debe ir al repositorio). PBIP guarda solo definiciones en texto:
cada medida nueva aparece como una línea en el *diff*, los conflictos se resuelven como en código y
los datos no se versionan (`.gitignore` excluye la caché local `.pbi/`).

## G.2 Conexión

Conexión a la **base de datos PostgreSQL** (capa Gold), nunca a los archivos de origen. Modo
*Import*. Dos parámetros de Power Query: `Servidor` = `localhost:15432` (NodePort del clúster) y
`BaseDatos` = `microrred`. Cada tabla usa `PostgreSQL.Database(Servidor, BaseDatos)`.

Primera apertura (única intervención manual, porque la contraseña no se versiona):

1. Abrir `powerbi/MicrorredBI.pbip` con Power BI Desktop.
2. Pulsar **Actualizar ahora**.
3. En el cuadro de credenciales elegir **Base de datos**, usuario `bi_lectura` y la clave
   `BI_PASSWORD` del archivo `.env`. Cifrado: desactivado (conexión local).

`bi_lectura` solo tiene `SELECT` sobre la capa Gold.

## G.3 Modelo semántico

| Tabla del modelo | Origen | Papel |
| --- | --- | --- |
| `Fecha` | `gold.dim_fecha` | **Tabla de fechas propia** (marcada con `dataCategory: Time`, columna `Fecha` como clave). Jerarquía *Calendario*: Año > Trimestre > Mes > Día |
| `Tiempo` | `gold.dim_tiempo` | Franja horaria. Jerarquía *Franja y hora* |
| `Inversor` | `gold.dim_inversor` | Inversor y versión de configuración (SCD 2) |
| `Tipo de evento`, `Tipo de contexto` | dimensiones | Catálogos |
| `Energia` | `gold.fact_energia_5min` | Hecho principal; columnas numéricas ocultas, se usan medidas |
| `Eventos` | `gold.vw_evento` | Hecho de eventos |
| `Contexto` | `gold.vw_contexto` | Hecho de contexto, sin el JSON |
| `Tarifa` | tabla calculada `GENERATESERIES(600, 1500, 10)` | **Parámetro de escenario (*what-if*)** |
| `Flujo` | tabla calculada desconectada | Ejes del balance energético |

**Relaciones** (11, todas uno-a-muchos, filtro en un solo sentido, de dimensión a hecho):
`Energia`, `Eventos` y `Contexto` → `Fecha`, `Tiempo`, `Inversor`; `Eventos` → `Tipo de evento`;
`Contexto` → `Tipo de contexto`. No hay relaciones entre hechos: se cruzan por las dimensiones
conformadas. La fecha automática de Power BI está desactivada (`__PBI_TimeIntelligenceEnabled = 0`)
para que solo exista la tabla de fechas propia.

**Medidas DAX** (33). Las principales:

```dax
Energía solar kWh = SUM(Energia[e_solar_kwh])

Autosuficiencia % =
VAR RedACarga = [Energía importada de red kWh] - [Red a batería kWh]
VAR Carga = [Energía a la carga kWh]
RETURN IF(NOT ISBLANK(Carga), 1 - DIVIDE(MIN(RedACarga, Carga), Carga))

Disponibilidad del registro % =
DIVIDE(SUM(Energia[seg_observados]), 86400 * [Días del periodo] * [Inversores en contexto])

-- Inteligencia de tiempo
Solar kWh mes anterior = CALCULATE([Energía solar kWh], DATEADD(Fecha[Fecha], -1, MONTH))
Solar variación vs mes anterior % = DIVIDE([Energía solar kWh] - [Solar kWh mes anterior], [Solar kWh mes anterior])
Solar kWh acumulado del año = TOTALYTD([Energía solar kWh], Fecha[Fecha])

-- Escenario
Tarifa COP por kWh = SELECTEDVALUE(Tarifa[Tarifa], 991.29)
Costo de red COP = [Energía importada de red kWh] * [Tarifa COP por kWh]

-- Balance energetico (tabla desconectada Flujo)
Balance kWh = SWITCH(SELECTEDVALUE(Flujo[Flujo]), "Solar", [Energía solar kWh], "Red", ..., "Pérdidas", ...)
```

## G.4 Páginas

| Página | Contenido | Requisito que cubre |
| --- | --- | --- |
| **1. Balance energético** | Tarjetas (solar, carga, red, autosuficiencia, pérdidas); barras "de dónde viene y a dónde va la energía" (origen: solar, red, batería; destino: carga, batería, pérdidas); columnas por periodo con la jerarquía de calendario | Análisis del balance energético; profundización (*drill-down*) año > trimestre > mes > día |
| **2. Operación y calidad** | Disponibilidad, datos válidos, eficiencia de batería, horas con SOC bajo; perfil por franja horaria (profundiza a hora); disponibilidad por mes e inversor; horas por tipo de evento; contexto de las cargas | Indicadores de calidad e híbridos; segundo y tercer proceso de negocio |
| **3. Economía y escenario** | Segmentación de **tarifa** (*what-if*); costo de red, costo evitado, costo sin microrred; variación solar vs. mes anterior; matriz mensual por inversor | Indicador económico, parámetro de escenario, inteligencia de tiempo |

En las tres páginas: **navegador de páginas** (botones) y **segmentaciones** de inversor y mes; la
página 1 añade tipo de día y la 3, la tarifa.

## G.5 Estado de verificación (declarado)

| Qué | Cómo se verificó | Resultado |
| --- | --- | --- |
| Modelo TMDL | Cargado con la biblioteca oficial de Microsoft (`TmdlSerializer` de Analysis Services) | 10 tablas, 11 relaciones, 33 medidas, 2 jerarquías, sin errores |
| Informe PBIR | 47 archivos validados contra los esquemas JSON publicados por Microsoft | 0 inválidos |
| Apertura | Proyecto abierto en Power BI Desktop 2.159 | Carga las tres páginas, segmentaciones, tarjetas y gráficos (`docs/img/powerbi_proyecto_abierto_sin_actualizar.png`) |
| **Actualización de datos** | **Pendiente: requiere escribir la contraseña de `bi_lectura` en Power BI Desktop** | Sin datos hasta pulsar *Actualizar ahora*; las medidas DAX no se han evaluado con datos y las capturas con cifras deben tomarse después de actualizar |

Las cifras que deben verse tras actualizar se pueden contrastar con `gold.vw_kpi_mensual` y con
`docs/evidencias/09_consultas_negocio.txt` (por ejemplo: inversor 2, 4 070 kWh a la carga y
autosuficiencia de 30,9 % en todo el periodo).
