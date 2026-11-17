# J. Ética y seguridad

## J.1 La tabla de contexto frente a la Ley 1581 de 2012

**Qué contiene.** `context` (25 178 registros) no describe equipos eléctricos sino **actividad de
personas** sobre dos estaciones de trabajo: comandos de consola y carpetas de trabajo
(`workstation*_log`, `wsl_bash_history`), sesiones remotas e inicios de sesión
(`windows_event_log`: `interactive_or_remote_logon`, `remote_desktop_logon`…), y anotaciones manuales.

**¿Son datos personales?** La Ley 1581 define dato personal como "cualquier información vinculada o
que pueda asociarse a una o varias personas naturales determinadas o determinables" (art. 3, lit. c).
Los autores del dataset ya anonimizaron la fuente (usuarios como `<user>`, rutas recortadas, revisión
de términos sensibles). Aun así, en un laboratorio con dos estaciones y pocos usuarios, el patrón
"quién lanzó qué tarea, a qué hora y desde dónde se conectó" permite **reidentificar** a una persona
con conocimiento local. Por eso el equipo trató el contexto como **dato personal potencial** (dato
privado/semiprivado, no sensible en el sentido del art. 5) y aplicó los principios del art. 4:

| Principio (art. 4) | Cómo se aplica en la solución |
| --- | --- |
| **Finalidad** | El contexto se usa solo para explicar el consumo energético (qué carga explica un pico). No se construyen indicadores por persona ni de productividad. |
| **Libertad / autorización** | La fuente es un dataset público con licencia CC BY 4.0, ya revisado por sus autores. En el campus real se exigiría autorización previa e informada de los usuarios de las estaciones (art. 9) y un aviso de privacidad. |
| **Necesidad y minimización** (acceso y circulación restringida) | El ETL **elimina** del JSON los campos que no se necesitan para el análisis energético y que más facilitan la reidentificación: `command`, `directory`, `example_commands_redacted`, `command_hints_redacted`, `metadata`, `project`, y dentro de `windows_event`: `record_id`, `sample_record_ids`, `sample_sanitized_message`, `sanitized_message`. Hay una prueba automática (`test_contexto_sin_campos_sensibles`). |
| **Seguridad** | La tabla detallada (`silver.contexto`) no es legible por los roles de consumo. Power BI (`bi_lectura`) y Grafana (`grafana_ro`) solo leen la capa Gold; Power BI usa `gold.vw_contexto`, que no expone el JSON. |
| **Transparencia** | El diccionario de datos documenta qué se conserva y qué se elimina. |
| **Temporalidad** | Los datos se conservan mientras dure el análisis académico. En producción se definiría un periodo de retención y borrado para el detalle del contexto. |
| **Confidencialidad** | Las credenciales de los roles se entregan solo a quien las necesita (ver J.2). |

**Derechos de los titulares (art. 8).** En un despliegue real, la institución actuaría como
responsable del tratamiento: tendría que publicar su política, atender consultas y reclamos (conocer,
actualizar, rectificar, suprimir) y registrar la base ante el RNBD si le aplica.

**Qué no se hace.** No se cruzan los registros con identidades, no se publican comandos ni rutas en
los tableros y no se infiere comportamiento individual. El tablero muestra el contexto agregado por
tipo de carga y por estación.

## J.2 Seguridad de acceso

### Base de datos: un rol por servicio, mínimo privilegio

| Rol | Lo usa | Puede | No puede |
| --- | --- | --- | --- |
| `postgres` | administración (DBeaver del docente o del equipo) | todo | — |
| `etl_app` | Job del ETL | dueño de `bronze`, `silver`, `gold`, `audit`, `live` | — |
| `sim_app` | CronJob del simulador | `SELECT` del histórico que reproduce; `INSERT` en `live.lectura` | modificar hechos o dimensiones |
| `grafana_ro` | Grafana | `SELECT` en `gold`, `live`, `audit` y en `silver.calidad_regla` | escribir; leer `silver.contexto` |
| `bi_lectura` | Power BI y DBeaver | `SELECT` en `gold`, `audit` y `silver.calidad_regla` | escribir; leer `silver.contexto` |

Los roles se crean en `sql/init/00_roles.sh` y los permisos en `sql/init/04_permisos.sql`. Se revoca
el acceso por defecto al esquema `public`. Una inyección SQL desde un panel de Grafana no puede
modificar datos porque su rol es de solo lectura.

### Credenciales dentro del clúster

- **Mecanismo elegido: Secret de Kubernetes creado desde un archivo `.env` local** que no se
  versiona. `scripts/up.sh` ejecuta
  `kubectl create secret generic microrred-credenciales --from-env-file=.env`. En Git solo está la
  plantilla `.env.example`; `scripts/generar_env.sh` crea un `.env` con claves aleatorias.
- Los pods reciben cada clave como variable de entorno con `secretKeyRef`, y **solo la que
  necesitan** (el simulador no recibe la clave del ETL ni la de administración).
- Las contraseñas no están en las imágenes, en los manifiestos, en el ConfigMap ni en el repositorio.
  `.gitignore` excluye `.env`.
- **Por qué no otra alternativa.** Un Secret escrito en YAML dentro del repositorio dejaría las
  claves en Git (base64 no es cifrado). Sealed Secrets o External Secrets + un gestor (Vault) serían
  lo correcto en la plataforma institucional, pero añaden un controlador que excede el nivel básico
  pedido.
- **Limitaciones que se declaran.** En un clúster kind los Secrets se guardan en etcd sin cifrado en
  reposo y cualquier usuario con acceso de administrador al clúster puede leerlos. En producción:
  cifrado de etcd, RBAC que limite `get secrets`, y rotación periódica.

### Tableros y red

- **Grafana**: sin acceso anónimo ni registro de usuarios (`GF_AUTH_ANONYMOUS_ENABLED=false`,
  `GF_USERS_ALLOW_SIGN_UP=false`); la clave de administrador viene del Secret; la fuente de datos es
  de solo lectura y no editable desde la interfaz (`editable: false`). Para usuarios finales se
  crearían cuentas con rol *Viewer*.
- **Power BI**: se conecta con `bi_lectura`. La contraseña la guarda Power BI Desktop en el almacén
  de credenciales del usuario, no en el proyecto PBIP versionado.
- **Exposición de puertos**: los NodePort solo se publican en `127.0.0.1` del anfitrión
  (`listenAddress` en la configuración de kind), no en la red local.
- **Tráfico interno**: la conexión Grafana → PostgreSQL usa `sslmode=disable` porque no sale del
  clúster local. En la plataforma institucional se exigiría TLS y una `NetworkPolicy` que solo
  permita llegar a PostgreSQL desde los pods de ETL, simulador y Grafana.
- **Contenedores**: ETL y simulador corren como usuario sin privilegios, con sistema de archivos raíz
  de solo lectura y sin escalamiento de privilegios; el volumen Bronze se monta en solo lectura.
