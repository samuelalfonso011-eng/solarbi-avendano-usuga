# Power BI — Conexión, modelo y medidas DAX (SolarBI Pascual)

**Estado:** este trabajo se desarrolló en un entorno sin Power BI Desktop
instalado (contenedor Linux en la nube). Las medidas y la configuración que
siguen son **código propuesto, no ejecutado**: están escritas para los nombres
reales de las tablas que sí se crearon y se poblaron en PostgreSQL
(`silver.lectura_5min`, `dwh.fact_energia_dia`, `silver.metricas_calidad`),
listas para pegarse en Power BI Desktop contra esa misma base de datos.

## Conexión

- Origen de datos: **PostgreSQL** (conector nativo `PostgreSQL database`).
- Servidor/puerto/base: los de la instancia PostgreSQL del equipo
  (`localhost:5432`, base `solarbi`), usando variables de entorno, nunca
  credenciales escritas en el `.pbix`/`.pbip`.
- Modo de carga: **Import** (ver respuesta D4 de la Parte A) sobre
  `dwh.fact_energia_dia` y `silver.metricas_calidad`, que ya vienen agregadas
  desde el ETL; no se requiere traer el detalle de 5 minutos a Power BI.
- Tabla de calendario (`dim_fecha`) generada con Power Query o DAX
  (`CALENDAR(MIN(dwh.fact_energia_dia[fecha_key]), MAX(dwh.fact_energia_dia[fecha_key]))`)
  y relacionada 1-a-muchos con `fact_energia_dia[fecha_key]`.

## Parámetro de tarifa

Parámetro de Power Query (`Tarifa_COP_kWh`), tipo decimal, valor inicial
`800` (COP/kWh), basado en el pliego tarifario residencial de referencia de
XM/CREG para el Área Metropolitana (fuente: `https://www.xm.com.co`, tarifa
promedio comercializador; el equipo debe actualizar el valor con la tarifa
vigente a la fecha de entrega y dejar la fuente citada en el repositorio).

## Medidas DAX

```DAX
Energia Total =
SUM ( dwh.fact_energia_dia[energia_kwh] )
```

```DAX
Yield =
DIVIDE (
    [Energia Total],
    5.0,              -- potencia nominal del inversor simulado, en kWp
    BLANK ()
)
```

```DAX
Ahorro Estimado =
[Energia Total] * SELECTEDVALUE ( 'Parametros'[Tarifa_COP_kWh], 800 )
```

```DAX
Porcentaje Datos Validos =
AVERAGE ( dwh.fact_energia_dia[pct_datos_validos] )
```

Notas:
- `Yield` usa `DIVIDE` (no `/`) para evitar errores por división entre cero,
  buena práctica estándar de DAX.
- `Ahorro Estimado` referencia el parámetro de tarifa mediante
  `SELECTEDVALUE`, de forma que cambiarlo en una tabla de parámetros
  actualiza la medida sin tocar el DAX.
- Todas las cifras de la página (tarjetas y gráfico) deben **leerse de estas
  medidas**, nunca de columnas calculadas sueltas ni de Power Query.

## Página propuesta

1. **Tarjeta — Yield** (`[Yield]`, formato `0.00 "kWh/kWp"`).
2. **Gráfico de columnas — Energía diaria** (eje: `dim_fecha[fecha]`, valor:
   `[Energia Total]`).
3. **Tarjeta — Ahorro estimado (COP)** (`[Ahorro Estimado]`, formato moneda
   `$ #,##0`).
4. **Tarjeta pequeña — % Datos Válidos** (`[Porcentaje Datos Validos]`,
   formato porcentaje, con regla de formato condicional roja/amarilla/verde
   igual a los umbrales usados en Grafana, para que ambas herramientas
   cuenten la misma historia).

## Resultado esperado / qué captura tomar

Al conectar Power BI Desktop a la base `solarbi` con las tablas ya cargadas
por `etl/run_etl.py`, la tarjeta de Yield debería mostrar un valor cercano a
**5.8–6.0 kWh/kWp/día** (consistente con los ~29 kWh/día generados por el
inversor de 5 kWp simulado, verificable con
`SELECT energia_kwh FROM dwh.fact_energia_dia;`). El estudiante debe tomar
una captura de la página completa (las 3 tarjetas + el gráfico) para el PDF.
