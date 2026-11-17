# K. Despliegue: Docker + Kubernetes

## K.1 Contenedores

| Imagen | Origen | Base | Tamaño | Justificación |
| --- | --- | --- | --- | --- |
| `microrred-etl:1.0.0` | `etl/Dockerfile` | `python:3.12-slim-bookworm` | 207 MB (`docker images`) | El ETL solo usa la biblioteca estándar (`sqlite3`, `json`) y `psycopg`. Sin pandas la imagen no supera la base más ~25 MB. |
| `microrred-simulador:1.0.0` | `simulador/Dockerfile` | `python:3.12-slim-bookworm` | 207 MB | Misma base que el ETL: el nodo comparte las capas, así que la segunda imagen casi no ocupa espacio adicional. |
| `postgres:16.4-alpine` | oficial | — | versión fija | Variante alpine: menor superficie y arranque rápido. |
| `grafana/grafana:11.4.0` | oficial | — | versión fija | Incluye el *plugin* de PostgreSQL y Unified Alerting. |

**Por qué `slim` y no otra base.** La imagen `python:3.12` completa pesa cerca de 1 GB porque trae
compiladores que aquí no se usan. Alpine sería más pequeña, pero `psycopg[binary]` publica ruedas
`manylinux` (glibc): en musl habría que compilar `libpq`, lo que alarga la construcción y obliga a
instalar un compilador. `slim` es el punto medio: glibc, sin herramientas de compilación.

Buenas prácticas aplicadas en los dos `Dockerfile`: versión fija de la base y de las dependencias,
`pip` sin caché, usuario sin privilegios (`USER 10001`), una sola responsabilidad por imagen y
`ENTRYPOINT` explícito. Ninguna imagen contiene datos ni credenciales.

`docker-compose.yml` es el paso previo al clúster: levanta los mismos cuatro servicios con las mismas
imágenes, el mismo DDL (`sql/init/`) y el mismo aprovisionamiento de Grafana.

## K.2 Clúster local

**Distribución elegida: kind** (Kubernetes in Docker), un nodo.

| Opción | Por qué sí / por qué no |
| --- | --- |
| **kind** | El nodo es un contenedor Docker: se crea en ~30 s y se destruye con un comando, lo que hace reproducible el "desde cero". La configuración (puertos y montajes) es un YAML versionado. |
| minikube | Equivalente en funciones, pero añade su propia capa de *drivers* y complementos que este taller no necesita. |
| k3d | También válido; usa k3s (una distribución recortada). Se prefirió Kubernetes "de fábrica" (kubeadm) para que lo aprendido aplique a la plataforma institucional. |
| Kubernetes de Docker Desktop | No se puede crear ni borrar por script, y su estado se mezcla con el de otros proyectos del equipo. |

**Cómo llegan las imágenes propias al clúster.** kind no ve las imágenes del Docker del anfitrión:
el nodo tiene su propio *containerd*. `scripts/up.sh` construye las imágenes y las copia al nodo con
`docker save <imagen> | docker exec -i microrred-control-plane ctr -n k8s.io images import -`
(equivale a `kind load docker-image`, que falló con el almacén de imágenes containerd de Docker
Desktop al intentar importar todas las plataformas). Los manifiestos usan `imagePullPolicy: IfNotPresent`, de modo que el
*kubelet* usa la copia local y no intenta descargarlas de un registro. No hace falta registro
privado ni credenciales de *pull*.

**Cómo llega la capa Bronze.** El SQLite pesa 4,4 GB y no pertenece a ninguna imagen. La carpeta
`data/bronze` del anfitrión se monta en el nodo en solo lectura (`extraMounts` de kind) y el Job
del ETL la lee con un volumen `hostPath` también de solo lectura.

## K.3 Objeto elegido para cada necesidad

| Necesidad | Objeto | Dónde | Por qué este y no la alternativa |
| --- | --- | --- | --- |
| Aislar el proyecto | **Namespace** `microrred-bi` | `k8s/base/namespace.yaml` | Agrupa todos los recursos, evita choques de nombres y permite borrar todo con `kubectl delete namespace`. Usar `default` mezclaría el proyecto con otros. |
| Base que no pierda datos | **StatefulSet** `postgres` + **PersistentVolumeClaim** (`volumeClaimTemplates`) | `postgres.yaml` | El StatefulSet da identidad estable (`postgres-0`) y un PVC propio que se vuelve a montar al recrear el pod. Un Deployment con PVC también funcionaría con una réplica, pero no garantiza identidad ni orden y sugiere que la base escala como una aplicación sin estado. Un `emptyDir` perdería los datos. |
| Grafana siempre disponible, con tablero y fuente al iniciar | **Deployment** `grafana` + **ConfigMaps** de *provisioning* + **initContainer** | `grafana.yaml` | Grafana no guarda estado: todo se reconstruye desde archivos. El Deployment repone el pod y permite *rolling update*. El initContainer escribe los umbrales del ConfigMap en la plantilla de alertas. Un StatefulSet sería innecesario. |
| Credenciales fuera del código | **Secret** `microrred-credenciales` | lo crea `scripts/up.sh` desde `.env` | Las contraseñas no están en imágenes, manifiestos ni Git. Un ConfigMap las dejaría legibles para cualquiera con permiso de lectura de configuración y sin posibilidad de cifrado en reposo ni RBAC diferenciado. |
| Configuración separada del código | **ConfigMap** `microrred-config` | generado desde `config/microrred.env` | Umbrales, intervalos y nombres se inyectan como variables de entorno. Cambiar un valor no exige reconstruir la imagen. |
| Comunicación entre servicios | **Service** `postgres` (ClusterIP *headless*) | `postgres.yaml` | Da un nombre DNS estable (`postgres`); ETL, simulador y Grafana se conectan por nombre. Las IP de los pods cambian en cada reinicio. |
| Carga histórica | **Job** `etl-carga-historica` | `etl-job.yaml` | Corre hasta terminar, reintenta si falla (`backoffLimit`) y queda en `Complete` con sus *logs*. Un Deployment lo reiniciaría sin fin; un Pod suelto no reintenta. |
| Datos nuevos cada cierto tiempo | **CronJob** `simulador` | `simulador-cronjob.yaml` | Kubernetes lleva el calendario; cada pasada es un pod corto. Al leer el ConfigMap en cada arranque, un cambio de escenario aplica al minuto siguiente. Un Deployment con bucle `sleep` también serviría, pero oculta el calendario dentro del código. |
| Saber si un servicio está sano | **startup / readiness / liveness probes** | `postgres.yaml`, `grafana.yaml` | PostgreSQL: `pg_isready`. Grafana: `GET /api/health`. *Readiness* decide si el Service le envía tráfico; *liveness* reinicia el contenedor si se cuelga; *startup* evita reinicios durante el primer arranque. |
| No agotar el anfitrión | **requests y limits** de CPU y memoria | todos los contenedores, incluidos los initContainers | *Requests* reserva lo mínimo para planificar; *limits* impide que un contenedor consuma todo el equipo. |
| Acceso desde el anfitrión | **Service NodePort** (30432, 30300) + `extraPortMappings` de kind | `postgres.yaml`, `grafana.yaml`, `k8s/kind-config.plantilla.yaml` | Power BI y DBeaver se conectan a `localhost:15432` y el navegador a `localhost:13000`, solo en `127.0.0.1`. `kubectl port-forward` sirve para pruebas, pero se cae con el pod y obliga a dejar una terminal abierta. Ingress no se exige y PostgreSQL no es HTTP. |

Suma de recursos solicitados (*requests*) con todo corriendo: 0,4 CPU y 432 Mi de forma permanente
(PostgreSQL + Grafana), más 0,25 CPU / 384 Mi durante el ETL y 0,05 CPU / 48 Mi por pasada del simulador.

## K.4 Reproducibilidad y resiliencia

| Acción | Comando |
| --- | --- |
| Levantar todo desde cero | `bash scripts/up.sh` (PowerShell: `.\scripts\up.ps1`) |
| Eliminar todo | `bash scripts/down.sh` |
| Ambiente dev | `bash scripts/up.sh dev` |

`up.sh` verifica requisitos, descarga y valida Bronze si falta, crea el clúster, construye y carga
las imágenes, crea el Secret, aplica los manifiestos y espera a que PostgreSQL, Grafana y el Job del
ETL terminen correctamente. No hay ningún paso manual ni en la interfaz de Grafana.

Las demostraciones de resiliencia (borrar el pod de PostgreSQL y el de Grafana) y las salidas de
`kubectl get` y `kubectl describe` están en `docs/evidencias/` y se resumen en el informe.

## Bonificaciones implementadas

- **Kustomize con dos ambientes**: `k8s/base` + `k8s/overlays/demo` y `k8s/overlays/dev` (otro
  namespace, menos memoria, simulador cada 2 minutos, NodePorts distintos).
- **Escalado**: `kubectl scale deployment/grafana --replicas=2` funciona porque Grafana no tiene
  estado local relevante. PostgreSQL no se escala igual: dos pods con `replicas: 2` serían dos bases
  independientes, cada una con su PVC y sus propios datos; escalar lecturas exige replicación
  (*streaming replication*) con un primario y réplicas, y normalmente un operador.
- **Rolling update y rollback del simulador**: ver `docs/evidencias/` (cambio de imagen del CronJob
  a la versión 1.0.1 y reversión).

No se implementó el acceso por nombre de dominio con un controlador de entrada (Ingress).
