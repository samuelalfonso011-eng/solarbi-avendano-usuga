# Matriz de trazabilidad de requisitos

Fuente de requisitos: `BI_Taller6_Microrred_Kubernetes.docx.pdf` (6 páginas).
Tipo: F = funcional, NF = no funcional, T = técnico, A = académico, S = sustentación.
Prioridad: O = obligatorio, B = bonificación.
Estado: **Cumple** = implementado y verificado; **Parcial** = implementado, con una verificación
pendiente que se indica; **Pendiente** = requiere una acción de los integrantes.

| ID | Sec. / pág. | Requisito | Tipo | Prio. | Componente | Implementación | Verificación | Estado |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | 4.A / p2 | Usuarios y preguntas de negocio | A | O | Documentación | `docs/01_negocio_y_fuente.md` §A.1 | Revisión | Cumple |
| A2 | 4.A / p2 | Diagnóstico de la fuente: estructura, cobertura, calidad, limitaciones | A, T | O | Diagnóstico | `scripts/diagnostico_bronze.py`, `docs/01…` §A.2 | `docs/evidencias/diagnostico_bronze.json` | Cumple |
| B1 | 4.B / p2 | Catálogo: nombre, fórmula, unidad, granularidad, meta, fuente, usuario | A | O | Indicadores | `docs/02_indicadores.md` §B.1 | Revisión | Cumple |
| B2 | 4.B / p2 | Solar, carga, red, disponibilidad y % válidos por inversor, día, mes y periodo | F | O | Gold | `gold.vw_kpi_diario`, `vw_kpi_mensual`, medidas DAX | `test_indicadores_en_rango`, consulta P1 | Cumple |
| B3 | 4.B / p2 | ≥ 2 indicadores propios de un sistema híbrido, justificados | A, F | O | Indicadores | Autosuficiencia, eficiencia de batería, horas SOC bajo, pérdidas (§B.2) | Vistas y medidas | Cumple |
| B4 | 4.B / p2 | Indicador económico en COP con tarifa elegida | F | O | Indicadores | `gold.tarifa`, `costo_red_cop`, `costo_evitado_cop` (§B.3) | `test_tarifa_cargada`; PDF oficial de EPM | Cumple |
| B5 | 4.B / p2 | Análisis crítico: indicador clásico no calculable | A | O | Documentación | §B.4 (*Performance Ratio*) | Revisión | Cumple |
| C1 | 4.C / p2 | Diseño estrella o copo de nieve, justificado | A, T | O | Modelo | `sql/init/02_gold_dimensional.sql`, `docs/03…` §C.1 | DDL aplicado en el clúster | Cumple |
| C2 | 4.C / p2 | Grano de cada hecho; más de un proceso de negocio | A, T | O | Modelo | 3 hechos (§C.2) | `test_grano_y_llaves…` | Cumple |
| C3 | 4.C / p2 | Dimensiones con atributos y jerarquías; una construida | A, T | O | Modelo | `dim_tiempo` (construida), `dim_fecha` (§C.3) | `test_dimensiones` | Cumple |
| C4 | 4.C / p2 | Cómo se modelan los eventos operativos | A | O | Modelo | `fact_evento` + `dim_tipo_evento` (§C.4) | `test_eventos_operativos…` | Cumple |
| C5 | 4.C / p3 | Matriz de bus | A | O | Documentación | §C.5 | Revisión | Cumple |
| C6 | 4.C / p3 | SCD identificada y tipo decidido | A, T | B | Modelo | `dim_inversor` SCD tipo 2 (§C.6) | `test_dimensiones`, consulta P9 | Cumple |
| D1 | 4.D / p3 | Diccionario: descripción, columnas, tipos, llaves, reglas, linaje | A | O | Documentación | `docs/04_diccionario_datos.md` | Revisión | Cumple |
| D2 | 4.D / p3 | Unidades con la evidencia usada | A | O | Documentación | §D.1 | Balance y conciliación | Cumple |
| E1 | 4.E / p3 | ETL que extrae (incluido JSON), limpia, transforma y carga; herramienta justificada; corre en contenedor | F, T | O | ETL | `etl/`, `etl/Dockerfile`, Job | `docs/evidencias/06_etl_job_k8s_corrida1.txt` | Cumple |
| E2 | 4.E / p3 | Reglas de limpieza con conteos antes y después | F, A | O | ETL | `silver.calidad_regla`, §E.2 | `test_filas_fuente_igual…` | Cumple |
| E3 | 4.E / p3 | Dato inválido frente a evento operativo | A, F | O | ETL | Reglas R (rechazan) y E (clasifican), §E.3 | `test_evento_operativo_no_es_dato_invalido` | Cumple |
| E4 | 4.E / p3 | Frecuencia de agregación de Silver, justificada | A | O | ETL | 5 minutos (§E.4) | Revisión | Cumple |
| E5 | 4.E / p3 | Conciliación con la fuente o explicación de diferencias | F, A | O | ETL | `audit.conciliacion`, §E.5 | `test_energia_integrada_concuerda…`, P11 | Cumple |
| E6 | 4.E / p3 | Idempotencia | NF | O | ETL | Transacción única + huella (§E.6) | `test_dos_corridas_dejan_la_misma_huella`; 2 corridas en el clúster | Cumple |
| F1 | 4.F / p3 | DDL en PostgreSQL, administrado desde DBeaver | T | O | Base de datos | `sql/init/`, `docs/06…` §F.1 | DDL aplicado; conexión documentada | Parcial: los integrantes deben abrir la conexión en DBeaver y tomar la captura |
| F2 | 4.F / p3 | Restricciones e índices justificados | T, A | O | Base de datos | §F.2 | DDL | Cumple |
| F3 | 4.F / p3 | Consulta sobre JSON con operadores nativos | F | O | Base de datos | P6, P6b, P6c | `test_consulta_json_nativa`; `09_consultas_negocio.txt` | Cumple |
| F4 | 4.F / p3 | Consultas de negocio con agregaciones, ventanas y comparativos | F | O | Base de datos | `sql/consultas_negocio.sql` (13 consultas) | Ejecutadas en el clúster | Cumple |
| G1 | 4.G / p3 | Conexión a la base (no a archivos) | T | O | Power BI | `PostgreSQL.Database` en cada partición | TMDL validado | Parcial: falta actualizar con la contraseña |
| G2 | 4.G / p3 | Modelo semántico, tabla de fechas propia, medida de inteligencia de tiempo | F | O | Power BI | `Fecha.tmdl`, 11 relaciones, `DATEADD`, `TOTALYTD` | Modelo cargado con la biblioteca de Microsoft | Parcial: DAX sin evaluar con datos |
| G3 | 4.G / p3 | ≥ 3 páginas, navegación, segmentaciones, profundización | F | O | Power BI | 3 páginas PBIR | Esquemas JSON; abierto en Desktop | Parcial: revisar visualmente tras actualizar |
| G4 | 4.G / p3 | Análisis del balance energético | F | O | Power BI | Página 1, medida `Balance kWh` | Ídem | Parcial |
| G5 | 4.G / p3 | Parámetro de escenario (*what-if*) | F | O | Power BI | Tabla `Tarifa` + segmentación | Ídem | Parcial |
| H1 | 4.H / p3 | PostgreSQL como fuente de datos | T | O | Grafana | `provisioning/datasources/postgres.yaml` | API de Grafana tras recrear el pod | Cumple |
| H2 | 4.H / p3 | Series de tiempo y estado actual por inversor | F | O | Grafana | Tablero de 20 paneles | `docs/img/grafana_operacion.png` | Cumple |
| H3 | 4.H / p3 | Variables de tablero | F | O | Grafana | `$inversor` | Captura | Cumple |
| H4 | 4.H / p3 | ≥ 2 reglas de alerta con umbral justificado | F | O | Grafana | 4 reglas (`alerting/reglas.yaml`) | `scripts/alertas.sh` | Cumple |
| H5 | 4.H / p3 | Simular *streaming*; tablero y alerta reaccionan; simulador en el clúster | F, T | O | Simulador | CronJob `simulador` | `docs/evidencias/12_demo_alerta.txt` | Cumple |
| I1 | 4.I / p3 | Diagrama de arquitectura con objetos de Kubernetes | A | O | Documentación | `docs/09…` §I.1 | Revisión | Cumple |
| I2 | 4.I / p4 | Comparativo Power BI vs. Grafana | A | O | Documentación | §I.2 | Revisión | Cumple |
| I3 | 4.I / p4 | Evolución con Modbus o SCADA | A | O | Documentación | §I.3 | Revisión | Cumple |
| J1 | 4.J / p4 | Contexto frente a la Ley 1581 de 2012 | A, NF | O | ETL + docs | Minimización del JSON, `docs/10…` §J.1 | `test_contexto_sin_campos_sensibles` | Cumple |
| J2 | 4.J / p4 | Seguridad de acceso y credenciales en el clúster | NF | O | BD + K8s | Roles, Secret desde `.env` (§J.2) | `kubectl describe secret`; permisos | Cumple |
| K1 | 4.K.1 / p4 | Imagen propia de ETL y simulador; base y tamaño justificados | T | O | Docker | `etl/Dockerfile`, `simulador/Dockerfile` | `docker images` | Cumple |
| K2 | 4.K.1 / p4 | PostgreSQL y Grafana con versión fija | T | O | K8s | `postgres:16.4-alpine`, `grafana/grafana:11.4.0` | Manifiestos | Cumple |
| K3 | 4.K.1 / p4 | `docker-compose.yml` de desarrollo | T | O | Docker | `docker-compose.yml` | Probado: ETL, simulador y Grafana | Cumple |
| K4 | 4.K.2 / p4 | Distribución elegida y justificada; cómo llegan las imágenes | A, T | O | K8s | kind (§K.2) | `05b_up_reaplicado.txt` | Cumple |
| K5 | 4.K.3 / p4 | Namespace propio | T | O | K8s | `namespace.yaml` | `kubectl get` | Cumple |
| K6 | 4.K.3 / p4 | PostgreSQL con almacenamiento persistente | T | O | K8s | StatefulSet + PVC | `10_demo_postgres.txt` | Cumple |
| K7 | 4.K.3 / p4 | Grafana con tablero y fuente al iniciar | T | O | K8s | Deployment + ConfigMaps | `11_demo_grafana.txt` | Cumple |
| K8 | 4.K.3 / p4 | Credenciales fuera del código | NF | O | K8s | Secret creado desde `.env` | `git ls-files` sin `.env` | Cumple |
| K9 | 4.K.3 / p4 | Configuración separada del código | NF | O | K8s | ConfigMap desde `config/microrred.env` | Cambio de umbral sin reconstruir | Cumple |
| K10 | 4.K.3 / p4 | Servicios por nombre, no por IP | T | O | K8s | Service `postgres`; `PGHOST=postgres` | Logs del Job y del CronJob | Cumple |
| K11 | 4.K.3 / p4 | ETL corre una vez y deja evidencia | T | O | K8s | Job + `audit.etl_ejecucion` | `kubectl logs job/…` | Cumple |
| K12 | 4.K.3 / p4 | Simulador periódico | T | O | K8s | CronJob cada minuto | `kubectl get cronjob,job` | Cumple |
| K13 | 4.K.3 / p4 | Sondas de salud en PostgreSQL y Grafana | T | O | K8s | startup, readiness, liveness | `kubectl describe` | Cumple |
| K14 | 4.K.3 / p4 | Solicitudes y límites en cada contenedor | NF | O | K8s | `resources` en todos | `kubectl describe` | Cumple |
| K15 | 4.K.3 / p4 | Acceso desde el anfitrión | T | O | K8s | NodePort + puertos de kind | Pruebas y capturas desde el anfitrión | Cumple |
| K16 | 4.K.3 / p4 | Nombrar y justificar el objeto de cada fila | A | O | Documentación | `docs/11_kubernetes.md` §K.3 | Revisión | Cumple |
| K17 | 4.K.4 / p5 | Levantar con un comando y eliminar con otro | NF | O | Scripts | `scripts/up.sh`, `scripts/down.sh` | `05_up_desde_cero.txt` | Cumple |
| K18 | 4.K.4 / p5 | Borrar pod de PostgreSQL y de Grafana | NF, S | O | K8s | `scripts/demo_resiliencia.sh` | `10_…`, `11_…` | Cumple |
| K19 | 4.K.4 / p5 | Evidencia `kubectl get` y `describe` | A | O | Evidencias | `15_kubectl_get_describe.txt` | Archivo | Cumple |
| K20 | Bonif. / p5 | Escalar y explicar PostgreSQL vs. Grafana | T | B | K8s | `demo_resiliencia.sh escalar` | `13_demo_escalar.txt` | Cumple |
| K21 | Bonif. / p5 | Dominio local con controlador de entrada | T | B | — | No implementado | — | No se hizo |
| K22 | Bonif. / p5 | Kustomize o Helm con ambientes dev y demo | T | B | K8s | `k8s/base`, `k8s/overlays/{dev,demo}` | Render de ambos; demo desplegado | Parcial: el ambiente dev se renderiza pero no se desplegó |
| K23 | Bonif. / p5 | Actualización de la imagen del simulador y reversión | T | B | K8s | `demo_resiliencia.sh rolling` | `14_demo_rolling.txt` | Cumple (un CronJob no tiene `rollout undo`: se revierte a la imagen versionada) |
| R1 | 5 / p5 | README: proyecto, arquitectura, reproducción, requisitos, cita | A | O | Repositorio | `README.md` | Revisión | Cumple |
| R2 | 5 / p5 | Versionados: SQL, ETL, simulador, Dockerfile, compose, manifiestos, tablero, Power BI; formato justificado | T | O | Repositorio | Todo en `taller6/`; PBIP | `git ls-files` | Cumple |
| R3 | 5 / p5 | Sin datos pesados ni contraseñas; plantilla de ejemplo | NF | O | Repositorio | `.gitignore`, `.env.example` | `git ls-files` | Cumple |
| R4 | 5 / p5 | Historial incremental con aportes visibles de todos los integrantes (4) | A | O | Repositorio | Commits incrementales reales | `git log` | **Pendiente**: los commits de esta rama salen casi todos con un solo autor; cada integrante restante debe aportar los suyos |
| R5 | 5 / p5 | `.gitignore` adecuado | T | O | Repositorio | `.gitignore` | Revisión | Cumple |
| N1 | 6 / p5 | Informe PDF con portada, enlace y secciones, capturas y evidencias | A | O | Informe | `docs/informe/` | PDF generado | Parcial: faltan las capturas de Power BI con datos y de DBeaver |
| S1 | 7 / p5 | Flujo completo en vivo, desde cero, con un comando | S | O | Scripts | `docs/12_sustentacion.md` | Ensayo | Pendiente: ensayo de los integrantes |
| S2 | 7 / p5 | Historia con datos y recomendaciones | S | O | Documentación | `docs/12_sustentacion.md` §1 | Revisión | Cumple |
| S3 | 7 / p5 | Los 4 integrantes dominan el proyecto | S | O | — | Guía de preguntas en vivo | — | Pendiente: estudio de los integrantes |
| V1 | 9 / p6 | Verificar integridad y dejar evidencia | T | O | Bronze | `scripts/descargar_datos.py` | `01_descarga_sha256.txt` | Cumple |
| V2 | 9 / p6 | Documentar herramienta y comando de descompresión | A | O | Bronze | README y §A.2 | Revisión | Cumple |
| V3 | 9 / p6 | Inventario: tablas, columnas, filas, periodo | T | O | Bronze | `diagnostico_bronze.py` | JSON de evidencia | Cumple |
| V4 | 9 / p6 | El SQLite es Bronze: no se modifica ni se sube | NF | O | Bronze | Apertura `mode=ro&immutable=1`; `.gitignore` | SHA-256 igual antes y después (`bronze.ingesta`) | Cumple |
| V5 | 9 / p6 | Cita obligatoria en el README | A | O | Repositorio | `README.md` | Revisión | Cumple |

## Dependencias entre componentes

Bronze (descarga) → ETL → Silver → Gold → {Power BI, simulador → `live` → Grafana y alertas}.
PostgreSQL debe estar listo antes del ETL (initContainer `esperar-postgres`); el simulador necesita
Gold cargado (si no, registra "omitida" y termina sin error); Grafana necesita el Service
`postgres` y el Secret.
