# A. Negocio y diagnóstico de la fuente

## A.1 Usuarios de la solución y preguntas de negocio

| Usuario (*stakeholder*) | Decisión que toma | Preguntas que necesita responder | Dónde las responde |
| --- | --- | --- | --- |
| **Dirección de infraestructura** | Invertir en más paneles, más batería o gestión de cargas | ¿Cuánta energía aporta el sol y cuánta se compra a la red? ¿En qué franja horaria se compra? ¿Cuánto cuesta y cuánto se evita pagar? ¿Qué inversor (qué carga) es menos autosuficiente? | Power BI: *Balance energético* y *Economía y escenario* |
| **Mantenimiento** | Intervenir un equipo, reducir carga, revisar una falla | ¿Cómo está cada inversor ahora? ¿El SOC está bajo? ¿Hay red? ¿Dejó de llegar telemetría? ¿Qué alarmas y fallas se repiten? | Grafana: tablero *Operación* y alertas |
| **Área de TI** | Aceptar el servicio en la plataforma de contenedores | ¿Se levanta, escala y recupera sin intervención manual? ¿Dónde están las credenciales? ¿Cuántos recursos consume? | Manifiestos de Kubernetes y `docs/11_kubernetes.md` |
| **Usuarios de las estaciones de cómputo** (investigadores) | Programar tareas pesadas | ¿Cuánto consume un entrenamiento en GPU? ¿Conviene lanzarlo en horas de sol? | Power BI: *Operación y calidad*; consulta P6 |
| **Responsable del dato / docente** | Confiar o no en los indicadores | ¿Qué porcentaje de lecturas es válido? ¿Los totales cargados coinciden con la fuente? ¿El proceso es repetible? | `audit.conciliacion`, `silver.calidad_regla`, panel de salud del ETL |

## A.2 Diagnóstico de la fuente

**Fuente.** OpenCEM v1.0.0 (Zenodo, DOI 10.5281/zenodo.21436223), licencia CC BY 4.0. Microrred
fotovoltaica con batería en un campus de Longgang, Shenzhen (China). Dos subsistemas, cada uno con
un inversor híbrido leído por Modbus RTU: el **inversor 1** alimenta estaciones de cómputo y el
**inversor 2**, un aire acondicionado.

**Descarga y verificación** (evidencia: `docs/evidencias/01_descarga_sha256.txt`). Se descargaron
solo los cinco archivos indicados (≈ 312 MB) con `scripts/descargar_datos.py` (descarga reanudable
con cabecera HTTP `Range`). Los cuatro archivos listados en `SHA256SUMS.txt` coinciden. La base se
descomprimió con la biblioteca `zstandard` de Python (`ZstdDecompressor.copy_stream`), equivalente a
`zstd -d opencem-v1.0.0.sqlite.zst`. El SQLite resultante pesa 4 439 408 640 bytes y su SHA-256
(`5fe1f213…2d9fbb`) coincide con el que publican los autores en `documentation/provenance.json`.

### Estructura e inventario

Resultado de `scripts/diagnostico_bronze.py` (`docs/evidencias/diagnostico_bronze.json`):

| Tabla | Filas | Columnas | Periodo (UTC) | Contenido |
| --- | ---: | ---: | --- | --- |
| `analog_measurements` | 2 989 759 | 44 | 2025-07-12 → 2026-07-13 | Medidas instantáneas: batería, FV, salida AC, red |
| `status` | 2 240 052 | 20 | 2025-07-12 → 2026-07-13 | Estados y banderas de alarma |
| `totals` | 2 279 918 | 21 | 2025-07-12 → 2026-07-13 | Potencias agregadas y peticiones del BMS |
| `settings` | 2 284 775 | 176 | 2025-07-12 → 2026-07-13 | Configuración del inversor en cada lectura |
| `statistics` | 2 285 904 | 31 | 2025-07-12 → 2026-07-13 | Contadores de energía diarios y acumulados |
| `fault_history` | 2 129 517 | 66 | 2025-07-12 → 2026-07-13 | Últimos 32 registros de falla y su hora calibrada |
| `specs` | 1 333 174 | 16 | 2025-07-12 → 2026-02-02 | Identidad del equipo (firmware, versión) |
| `context` | 25 178 | 5 | 2024-04-30 → 2026-07-22 | Registros de contexto: intervalo + objeto JSON |

Todas las tablas de telemetría comparten la llave natural `(read_ts, inverter)` con índice único;
`read_ts` es tiempo Unix en segundos con fracción, en UTC. El sitio está en `Asia/Shanghai` (UTC+8,
sin horario de verano): el calendario de negocio se construye en esa zona.

### Cobertura en el tiempo

- **Inversor 1**: 1 610 276 lecturas, del 12-jul-2025 al 13-jul-2026 (366 días de calendario, 335 con datos).
- **Inversor 2**: 1 379 483 lecturas, del 14-jul-2025 al 22-jun-2026; desde mayo de 2026 está
  apagado o sin comunicación (en junio, 28 111 de sus 28 115 filas son totalmente nulas).
- **Cadencia irregular**: mediana 12,6 s, percentil 95 de 60 s y percentil 99 de 111 s. Entre julio y
  septiembre de 2025 el muestreo fue mucho más espaciado (3 400 a 21 000 lecturas por mes frente a
  ~212 000 desde diciembre).
- **Huecos**: 16 huecos de más de una hora en el inversor 1 (938 h perdidas) y 15 en el inversor 2
  (1 093 h). El mayor, común a ambos: 3 al 29 de agosto de 2025 (627,5 h). Otro de 5,5 días
  (inversor 1) y 12,4 días (inversor 2) en noviembre de 2025.
- Resultado en el modelo: disponibilidad media del registro de **87,3 %** (inversor 1) y **69,4 %**
  (inversor 2) sobre los 367 días del periodo; 35 y 102 días sin ningún dato, respectivamente.

### Problemas de calidad detectados

| # | Problema | Evidencia | Tratamiento (regla) |
| --- | --- | --- | --- |
| 1 | Filas con todas las medidas en NULL | 55 614 filas (1,86 %), casi todas del inversor 2 | R1: se rechazan |
| 2 | Filas con alguna variable crítica en NULL (el registrador guarda `NaN` cuando un bloque Modbus falla) | 20 450 filas (0,68 %) | R2: se rechazan |
| 3 | Valores fuera del rango físico (tensión de batería de 0 a 29 V en un banco de 48 V, potencia de red negativa sin posibilidad de vender) | 16 filas | R3: se rechazan |
| 4 | **Lecturas cruzadas**: en el mismo instante los dos inversores reportan exactamente los mismos valores | 40 363 pares; 91 % en mayo de 2026 | R4: se rechaza la lectura del inversor que "salta" respecto a su historia |
| 5 | Sensor de temperatura con valor centinela 120 °C (`temper4`) | 100 % de las filas no nulas | A1: el campo se anula |
| 6 | Sesgo de la corriente de batería en reposo: marca +0,4 a +0,9 A con el inversor apagado y SOC constante | 65 % de las lecturas válidas | A2: se toma como 0 A |
| 7 | Contadores diarios del inversor que se reinician a horas distintas de la medianoche local (reloj interno descalibrado) | inversor 1 a las ~08:00, inversor 2 a las ~10:30 | No se usan los contadores "today"; se usan los acumulados |
| 8 | Contexto sin tipo (`context_type` ausente) | 61 registros manuales | Se clasifican (calendario académico / anotación manual) |
| 9 | Códigos sin catálogo: banderas de alarma, códigos de falla y de prioridad provienen de un mapa de registros propietario que los autores no publican | `sysalarmflag`, `faulthistoryrecord*`, `outpriority`, `chgpriority` | Se conservan como código numérico; no se inventa su significado |

No hay llaves duplicadas, JSON inválido ni intervalos de contexto invertidos (0 casos).

### Limitaciones para el análisis

1. **No hay irradiancia ni potencia nominal instalada.** La fuente no trae piranómetro ni kWp; el
   artículo solo indica "26 paneles" entre los dos arreglos. Impide calcular *Performance Ratio* y
   rendimiento específico (kWh/kWp).
2. **Un año con huecos**: los totales mensuales no son comparables sin normalizar por disponibilidad.
3. **El inversor 2 deja de operar** en mayo de 2026: su serie termina antes.
4. **No hay venta a la red**: toda la energía solar se consume, se almacena o se desaprovecha
   (*curtailment*), y ese desaprovechamiento no se mide.
5. **La batería no se mide bien en reposo** (problema 6): la eficiencia de ida y vuelta del
   inversor 1 sale por encima de 100 % en enero–abril de 2026, lo que indica que el sensor no
   registra la carga de mantenimiento. Ese indicador se interpreta con reserva.
6. **Otro país, otra red**: 230 V / 50 Hz y clima subtropical. Los patrones se usan como caso de
   estudio; la tarifa colombiana se aplica como escenario.
7. **Semántica parcial**: el diccionario del dataset describe muchas columnas solo como "campo
   procesado"; las unidades y los signos se dedujeron con evidencia (ver diccionario de datos).
