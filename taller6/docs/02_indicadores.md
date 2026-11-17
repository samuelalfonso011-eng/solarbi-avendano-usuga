# B. Catálogo de indicadores

Todos los indicadores se calculan sobre `gold.fact_energia_5min` (grano: inversor × 5 minutos) y se
pueden agregar por **inversor, día, mes y periodo**. Están disponibles en SQL (`gold.vw_kpi_diario`,
`gold.vw_kpi_mensual`) y como medidas DAX en Power BI.

## B.1 Catálogo

| # | Indicador | Fórmula | Unidad | Granularidad | Meta / umbral | Fuente | Usuario |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **Energía solar generada** | Σ `pv1power` × Δt | kWh | 5 min → día, mes, periodo; inversor | Mayor es mejor; referencia: mes anterior | `analog_measurements.pv1power` | Dirección |
| 2 | **Energía entregada a la carga** | Σ `outw_a` × Δt | kWh | ídem | Seguimiento | `outw_a` | Dirección, usuarios |
| 3 | **Energía importada de la red** | Σ `linepowerw_a` × Δt | kWh | ídem | Menor es mejor | `linepowerw_a` | Dirección |
| 4 | **Disponibilidad del registro** | segundos observados / segundos del periodo | % | día, mes, periodo; inversor | ≥ 95 % | huecos entre lecturas válidas | Mantenimiento, responsable del dato |
| 5 | **Datos válidos** | lecturas que pasan las reglas / lecturas crudas | % | ídem | ≥ 98 % | reglas R1–R5 | Responsable del dato |
| 6 | **Autosuficiencia** (*self-sufficiency*) — híbrido | 1 − (E_red − E_red→batería) / E_carga | % | día, mes, periodo; inversor | ≥ 50 % | derivado | Dirección |
| 7 | **Eficiencia de ida y vuelta de la batería** — híbrido | E_descarga / E_carga de batería | % | mes, periodo | 85–95 % (litio) | `battvolt` × `battcurr` | Mantenimiento |
| 8 | **Horas con SOC bajo** — híbrido | Σ tiempo con SOC ≤ 15 % | h | día, mes; inversor | 0 h | `battsoc` | Mantenimiento |
| 9 | **Pérdidas de conversión** — híbrido | E_solar + E_red + E_desc − E_carga_bat − E_carga | kWh y % de las entradas | mes, periodo | ≤ 10 % | balance | Dirección, mantenimiento |
| 10 | **Ciclos equivalentes de batería** — híbrido | E_descarga / capacidad nominal (10,24 kWh) | ciclos | mes, periodo | Seguimiento de vida útil | derivado | Mantenimiento |
| 11 | **Horas sin red / sin salida** | Σ tiempo con tensión < 100 V | h | día, mes | 0 h | `linevolta`, `outvolta` | Mantenimiento |
| 12 | **Costo de la energía comprada** — económico | E_red × tarifa | COP | día, mes, periodo | Menor es mejor | E_red + tarifa | Dirección |
| 13 | **Costo evitado** — económico | max(E_carga − (E_red − E_red→batería), 0) × tarifa | COP | ídem | Mayor es mejor | derivado + tarifa | Dirección |
| 14 | Energía solar vs. mes anterior | (E_solar − E_solar mes anterior) / E_solar mes anterior | % | mes | > 0 | inteligencia de tiempo | Dirección |

Δt es el tiempo hasta la siguiente lectura válida, con tope de 10 minutos (ver sección E).

## B.2 Indicadores propios de un sistema híbrido (no pedidos en el enunciado)

1. **Autosuficiencia.** Una planta fotovoltaica conectada a red se evalúa por lo que genera; un
   sistema híbrido, por cuánta de su carga logra atender **sin comprar**. Es el indicador que
   conecta sol, batería y red en una sola cifra y el que la dirección necesita para decidir si
   ampliar paneles o batería. Resultado del periodo: **28,9 %** (inversor 1) y **30,9 %** (inversor 2).
2. **Eficiencia de ida y vuelta de la batería.** Solo existe si hay almacenamiento. Cada kWh que
   pasa por la batería pierde una parte; si la eficiencia cae, la batería envejece o se usa mal.
   Inversor 2: 93–101 % en los meses de operación normal (coherente con litio). Inversor 1: valores mayores a 100 % en
   enero–abril de 2026, que revelan un problema de medición (ver limitación 5 del diagnóstico).
3. **Horas con SOC bajo.** Mide el riesgo de quedar sin respaldo. El umbral de 15 % no es arbitrario:
   es el ajuste `batsoclowalarm` de ambos inversores; a 5 % (`batstopsoc`) el inversor corta la
   salida. Total del periodo: 24,4 h (inversor 1) y 97,4 h (inversor 2).
4. **Pérdidas de conversión.** En un híbrido la energía cruza varias etapas (FV→DC, DC→AC,
   AC→batería→AC). El balance deja ver el consumo propio del inversor: **576 kWh** en el inversor 1
   (≈ 20 % de lo que entra) frente a 449 kWh en el inversor 2 (≈ 8 %). El inversor 1 atiende una
   carga pequeña (≈ 245 W de media) y su consumo fijo pesa mucho más.

## B.3 Indicador económico y tarifa elegida

**Tarifa: 991,29 COP/kWh.** Fuente: EPM, *Tarifas y Costo de Energía Eléctrica – Mercado Regulado –
octubre de 2026*, fila **"Oficial y Exentos de Contribución"**, Nivel de tensión I, activos de
propiedad de EPM (igual al costo unitario CU de ese nivel).

Justificación: la Institución Universitaria Pascual Bravo es una entidad oficial de educación en
Medellín, atendida por EPM en baja tensión; las entidades oficiales educativas no pagan la
contribución del 20 % que sí pagan comercio e industria (1 189,54 COP/kWh). Es una tarifa plana, sin
discriminación horaria, por lo que el costo depende solo de los kWh comprados.

La tarifa es un parámetro (`TARIFA_COP_KWH` en `config/microrred.env`, tabla `gold.tarifa`) y en
Power BI se puede variar con el parámetro de escenario. Con 991,29 COP/kWh, en el periodo:

| Inversor | Costo de la energía comprada | Costo evitado |
| --- | ---: | ---: |
| 1 (cómputo) | 1 446 379 COP | 554 823 COP |
| 2 (climatización) | 3 180 406 COP | 1 340 010 COP |

Los datos son de un sitio en China; el indicador responde "cuánto costaría y cuánto ahorraría esta
microrred con la tarifa de Medellín".

## B.4 Análisis crítico: el indicador clásico que no se puede calcular

**El *Performance Ratio* (PR, IEC 61724)** no se puede calcular:

PR = (E_AC / P_nominal) / (H_POA / G_STC)

Faltan sus dos insumos: la **irradiación en el plano del arreglo** (no hay piranómetro ni celda de
referencia en la fuente) y la **potencia nominal instalada** (kWp), que ni el dataset ni el artículo
declaran. Por la misma razón tampoco se puede calcular el **rendimiento específico** (kWh/kWp).

Qué haríamos al respecto:

1. **Conseguir la potencia nominal**: pedir a los autores la ficha de los paneles (26 módulos) o
   leerla en sitio. Mientras tanto se reporta la **potencia pico observada** (3 902 W y 3 933 W) y se
   declara como aproximación, no como kWp.
2. **Conseguir la irradiancia**: (a) instalar un piranómetro o una celda de referencia; (b) usar
   irradiancia satelital (NASA POWER, ERA5) para las coordenadas que trae el contexto
   (22,693° N, 114,211° E), sabiendo que su resolución espacial es gruesa; (c) estimarla con las
   imágenes de cielo del propio dataset, que quedaron fuera del alcance del taller.
3. **Advertir un sesgo adicional**: sin venta a la red, cuando la batería está llena y la carga es
   baja el inversor recorta la generación. Un PR calculado sobre esa energía subestimaría la planta;
   habría que calcularlo solo en intervalos sin recorte.
4. **Mientras tanto**: comparar cada inversor contra sí mismo (mes contra mes, normalizado por
   disponibilidad) y contra su pico observado, sin presentarlo como PR.

## B.5 Umbrales de las alertas de Grafana

| Alerta | Umbral | Justificación |
| --- | --- | --- |
| SOC de batería bajo | < 15 % | Ajuste de alarma del propio inversor (`batsoclowalarm` = 15). |
| Telemetría atrasada | > 300 s sin lecturas | Cinco ciclos del simulador (uno por minuto); equivale a perder disponibilidad del registro. |
| Red eléctrica ausente | red no disponible | Evento operativo: el inversor queda en modo isla. |
| Importación de red alta | > 3 000 W promedio en 5 min | Por encima del percentil 99 histórico de ambos inversores (1 392 W y 2 397 W; consulta P10). |
