# E. ETL y calidad de datos

## E.1 Proceso y herramienta

```
Bronze (SQLite, solo lectura)                Silver (PostgreSQL)                  Gold (PostgreSQL)
analog_measurements ─ reglas R1–R5, A1–A2 ─▶ silver.medicion_5min ─────────────▶ fact_energia_5min
        │                └ estados E1–E3 ──▶ silver.evento ────────────────────▶ fact_evento
status, fault_history ─ episodios ─────────▶ silver.evento
context (JSON) ─ limpieza y minimización ──▶ silver.contexto ──────────────────▶ fact_contexto
settings ─ moda diaria ────────────────────▶ silver.config_inversor ───────────▶ dim_inversor (SCD 2)
statistics ─ contadores acumulados ────────▶ silver.contador_diario ───────────▶ audit.conciliacion
```

**Herramienta: Python 3.12 con la biblioteca estándar (`sqlite3`, `json`) y `psycopg` 3.**
Código en `etl/microrred_etl/`.

| Criterio | Decisión |
| --- | --- |
| Corre en contenedor | Imagen de 207 MB basada en `python:3.12-slim`; se ejecuta como Job de Kubernetes. |
| Volumen | 3 millones de lecturas se leen en *streaming* fila a fila: memoria acotada y sin pandas. Corrida completa: ~100 s en el anfitrión y ~175 s dentro del clúster. |
| Carga | `COPY` de PostgreSQL para Silver; `INSERT … SELECT` en SQL para Gold (`sql/cargar_gold.sql`). |
| Probable | Las transformaciones son funciones puras (`transformar.py`) con 29 pruebas unitarias. |
| Por qué no una herramienta gráfica (Pentaho, NiFi) | Añaden un servidor y cientos de MB para un flujo lineal; el código en Git es más fácil de revisar, probar y versionar. |
| Por qué no dbt | Sirve para la parte SQL (Silver → Gold), pero la integración de energía a partir de lecturas irregulares es más clara en Python. |

## E.2 Reglas de limpieza y su efecto

Las reglas se aplican en orden; cada una recibe lo que dejó la anterior. Conteos reales de la última
corrida (tabla `silver.calidad_regla`, 2 989 759 lecturas en la fuente):

| Orden | Regla | Tipo | Qué hace | Inv. 1: antes → afectadas → después | Inv. 2: antes → afectadas → después |
| ---: | --- | --- | --- | --- | --- |
| 1 | R1 Fila vacía | Rechaza fila | Todas las medidas en NULL (ciclo Modbus fallido) | 1 610 276 → 1 → 1 610 275 | 1 379 483 → 55 613 → 1 323 870 |
| 2 | R2 Campo crítico nulo | Rechaza fila | Falta batería, FV, salida o red | 1 610 275 → 7 348 → 1 602 927 | 1 323 870 → 13 102 → 1 310 768 |
| 3 | R3 Fuera de rango | Rechaza fila | SOC ∉ [0, 100], batería ∉ [40, 60] V, potencias negativas o imposibles | 1 602 927 → 10 → 1 602 917 | 1 310 768 → 6 → 1 310 762 |
| 4 | R4 Lectura cruzada | Rechaza fila | Lectura idéntica a la del otro inversor en el mismo instante | 1 602 917 → 40 215 → 1 562 702 | 1 310 762 → 270 → 1 310 492 |
| 5 | R5 Llave duplicada | Rechaza fila | (`read_ts`, `inverter`) repetida | 1 562 702 → 0 → 1 562 702 | 1 310 492 → 0 → 1 310 492 |
| 6 | A1 Temperatura centinela | Anula campo | Temperatura = 120 °C se toma como ausente | 1 561 769 filas con el campo anulado | 1 309 229 |
| 7 | A2 Batería en reposo | Anula campo | Corriente de batería entre 0 y +0,9 A se toma como 0 A | 1 016 061 | 928 274 |
| 8 | E1 Sin red | Clasifica evento | `linevolta` < 100 V: se conserva y se marca | 254 764 lecturas marcadas | 58 616 |
| 9 | E2 Salida apagada | Clasifica evento | `outvolta` < 100 V | 2 | 114 110 |
| 10 | E3 Batería baja | Clasifica evento | SOC ≤ 15 % | 1 823 | 27 534 |

**Resultado:** 2 873 194 lecturas válidas de 2 989 759 (**96,1 %**; 97,05 % en el inversor 1 y 95,00 %
en el inversor 2). Se rechazaron 116 565 (3,9 %).

**Contexto JSON** (25 178 registros): 0 con JSON inválido, 0 sin fechas, 0 con intervalo invertido;
61 sin tipo se clasificaron; a todos se les retiraron los campos sensibles (sección J). Se cargaron
los 25 178.

**Detalle de R4 (lectura cruzada).** El registrador consulta el inversor 1 y luego el 2 y escribe
ambos con la misma marca de tiempo; cuando una consulta falla, a veces deja en un inversor los
valores del otro. Se detecta comparando diez variables (batería, FV, salida, temperaturas, tensiones).
Para decidir cuál de las dos es la copia se compara cada una con la última lectura aceptada de su
propio inversor: la copia es la que "salta" en SOC y temperatura. Si no se puede atribuir, se
rechazan las dos.

**Detalle de A2 (batería en reposo).** Con el inversor totalmente apagado (sin salida, sin red, sin
sol) y el SOC constante durante semanas, la corriente de batería marca +0,4 a +0,6 A. No puede ser
una descarga real: a 53 V serían ~19 kWh al mes, más que la capacidad del banco. Las lecturas se
acumulan en la banda 0,4–0,9 A (cientos de miles) y casi no hay entre 0 y 0,3 A. Se trata la banda
0 a +0,9 A como reposo. Limitación: descargas reales menores a ~48 W se ignoran.

## E.3 Dato inválido frente a evento operativo real

| | Dato inválido | Evento operativo real |
| --- | --- | --- |
| Criterio | La lectura **no describe el sistema físico**: no se pudo leer (NULL), es físicamente imposible, o pertenece al otro inversor | La lectura es **coherente** y describe un estado real, aunque sea indeseable |
| Ejemplo | Batería a 0 V con SOC 87 %; potencia de red negativa cuando no se puede vender; fila completa en NULL | Red a 0 V con el inversor atendiendo la carga desde batería (modo isla); salida a 0 V con batería en 53 V; SOC en 6 % |
| Cómo se distingue | Las demás variables de la misma lectura son incoherentes o están ausentes | Las demás variables son coherentes con el estado (por ejemplo, con red ausente la potencia de red es 0 y la batería descarga) |
| Tratamiento | Se rechaza y se cuenta (R1–R5) | Se conserva, entra al hecho de energía y abre un episodio en el hecho de eventos (E1–E3) |

Un cero no es un dato malo: el inversor 2 con todo en cero y la batería en 53 V durante mayo de
2026 es un **apagado real** (403 h de "salida apagada"), no un error. En cambio, las filas en NULL
del mismo inversor son fallas de comunicación.

## E.4 Frecuencia de agregación de la capa Silver: 5 minutos

La fuente es irregular: una lectura cada ~12,6 s (mediana), pero con el 5 % de los intervalos por
encima de 60 s y meses enteros a una lectura cada 2 a 6 minutos.

| | Qué se gana con 5 minutos | Qué se pierde |
| --- | --- | --- |
| Volumen | De 2,99 millones de lecturas a 178 968 filas (factor 16,7): Power BI importa el hecho completo y las consultas responden en milisegundos | — |
| Regularidad | Malla uniforme: los periodos densos y los escasos quedan comparables; habilita la dimensión de tiempo de 288 intervalos | — |
| Detalle | — | Transitorios de menos de 5 minutos (arranque de un compresor). **Mitigación**: se guardan las potencias máximas y el SOC mínimo del intervalo |
| Energía | **No se pierde**: la energía se integra lectura a lectura *antes* de agregar, así que el total no depende de la malla | — |
| Eventos | — | La hora exacta de un evento dentro del intervalo. **Mitigación**: los episodios se detectan sobre las lecturas crudas y guardan inicio y fin al segundo |

Por qué no 1 minuto: en los meses escasos la mayoría de los intervalos quedarían vacíos y el hecho
tendría cinco veces más filas sin aportar información. Por qué no 15 o 60 minutos: se perdería el
perfil intradiario que explica la compra nocturna y la rampa solar.

**Integración.** Cada lectura válida "vale" hasta la siguiente lectura válida del mismo inversor
(retención del último valor) y su energía se reparte entre los intervalos de 5 minutos que cruza.
Si el hueco supera **10 minutos** no se integra: queda como tiempo no observado y como evento
"hueco de telemetría". El umbral de 10 minutos es el que usan los autores del dataset para definir
un `data_gap`.

## E.5 Conciliación (*reconciliation*)

Evidencia: `docs/evidencias/07_etl_job_k8s_corrida2.txt`, tabla `audit.conciliacion`, consulta P11
y pruebas de integración.

**1. Conteo de filas.** Filas leídas = filas válidas + filas rechazadas, y coinciden con el
inventario de Bronze: 2 989 759 = 2 873 194 + 116 565. La suma de `n_lecturas` en Silver también
es 2 989 759. Gold tiene las mismas 178 968 filas y los mismos totales de energía que Silver.

**2. Energía contra los contadores del propio inversor.** El inversor lleva contadores acumulados
de energía (tabla `statistics`), independientes de las potencias instantáneas que integra el ETL.
Se comparan día a día, en los 498 días-inversor con contador válido:

| Magnitud | Contador del inversor | Integrado por el ETL | Diferencia |
| --- | ---: | ---: | ---: |
| Energía a la carga | 4 430,5 kWh | 4 410,6 kWh | **−0,45 %** |
| Energía solar | 1 791,1 kWh | 1 814,1 kWh | **+1,29 %** |
| Energía de red | 2 305,0 kWh | 2 970,5 kWh | +28,87 % |

**Explicación de las diferencias.**

- *Carga y solar* coinciden dentro de la resolución del contador (0,1 kWh por lectura). Por inversor
  la diferencia va de −2,5 % a +5,4 %; mes a mes, en los meses con telemetría completa, queda por
  debajo de 12 % y la mayor dispersión está en los meses de poca energía del inversor 1.
- *Red*: el contador `loadconsumlinetotal` mide solo la energía de la red **consumida por la carga**.
  La potencia de entrada de red que integra el ETL (`linepowerw_a`) incluye además el consumo
  propio del inversor y las pérdidas de conversión (el residuo de ~100 W del balance). La
  diferencia (665 kWh) es del mismo orden que las pérdidas calculadas (1 025 kWh entre los dos
  inversores). No es un error de carga: son dos magnitudes distintas, y se usa la de entrada de red
  porque es la que se factura.
- Los días con huecos no desbalancean la comparación porque se concilia día a día y solo con lo
  observado; los días sin contador válido (reinicios o lecturas nulas) quedan fuera de la comparación.

## E.6 Idempotencia

El ETL reemplaza el contenido de Silver y Gold dentro de **una sola transacción** y de forma
determinista (mismas llaves, mismo orden). Si falla, no cambia nada. Al final calcula una huella
MD5 de los tres hechos y de las dimensiones.

| Corrida | Dónde | Filas fuente | Filas Gold | Huella |
| --- | --- | ---: | ---: | --- |
| 1 | Job en Kubernetes | 2 989 759 | 178 968 | `542622b6dbba4c989722d9e477f13576` |
| 2 | Job en Kubernetes (segunda ejecución) | 2 989 759 | 178 968 | `542622b6dbba4c989722d9e477f13576` |

La misma huella se obtuvo ejecutando el ETL desde el anfitrión con Python 3.13
(`docs/evidencias/03_etl_corrida1.txt` y `04_etl_corrida2.txt`). Lo único que crece entre corridas
es la bitácora (`audit.etl_ejecucion`, `silver.calidad_regla`, `audit.conciliacion`), a propósito.
El simulador también es idempotente: `ON CONFLICT (inversor_id, ts) DO NOTHING`.
