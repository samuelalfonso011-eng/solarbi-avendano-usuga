# Ruta alternativa — Grafana OSS (Parte B, Paso 5)

**Estado:** Grafana OSS **no se pudo instalar** en el entorno donde se desarrolló
esta práctica. Se documenta aquí, con honestidad, el intento realizado, el error
encontrado y la causa probable, tal como exige el punto 11 del prompt maestro del
trabajo. Esta sección reemplaza evidencia de instalación real y, según la rúbrica,
**obtiene menor puntaje** que una instalación funcional.

## Procedimiento intentado

1. Verificar binarios disponibles: `which grafana-server grafana` → no instalado.
2. Intentar descarga directa del paquete oficial:
   `curl -o grafana.deb https://dl.grafana.com/oss/release/grafana_11.3.0_amd64.deb`
3. Intentar `sudo apt-get update` para instalar desde el repositorio oficial de
   Grafana Labs (`apt.grafana.com`) siguiendo la guía oficial de instalación en
   Debian/Ubuntu.
4. Se consideró Docker (`docker run -d -p 3000:3000 grafana/grafana-oss`), pero el
   entorno no tiene un daemon de Docker activo (`docker ps` falla con
   *"failed to connect to the docker API... no such file or directory"*).

## Error encontrado

- La descarga desde `dl.grafana.com` fue rechazada por la política de red del
  entorno de desarrollo (egress restringido a un listado de dominios permitidos:
  gestores de paquetes de Python/Node y GitHub, principalmente). El proxy de salida
  respondió con un rechazo de tipo `connect_rejected` (CONNECT denegado por política
  de organización) al intentar alcanzar `dl.grafana.com:443`.
- `sudo apt-get update` (necesario para instalar desde el repositorio oficial de
  Grafana) no completó: los mirrors de `apt` tampoco están en la lista de dominios
  permitidos de este entorno sandbox.
- El daemon de Docker no está disponible en este entorno (no hay `dockerd` corriendo),
  por lo que tampoco fue posible usar la imagen oficial `grafana/grafana-oss`.

## Causa probable

El entorno de ejecución usado para este desarrollo es un contenedor en la nube con
una lista blanca de salida a internet (solo npm, PyPI, GitHub y similares) por
razones de seguridad. Grafana Labs y los mirrors de `apt` no están en esa lista, y
no hay un daemon de contenedores disponible para usar la imagen Docker oficial.

## Solución intentada / recomendación para el entregable final

Dado que la pareja **sí** dispone de un computador personal sin esas restricciones,
la recomendación es instalar Grafana OSS allí siguiendo la guía oficial
(`https://grafana.com/docs/grafana/latest/setup-grafana/installation/`), usando el
paquete `.deb`/`.msi` o Docker Desktop, y:

1. Agregar PostgreSQL como *data source* (host, puerto 5432, base `solarbi`,
   usuario de solo lectura).
2. Importar el dashboard propuesto en `grafana/dashboard.json` (incluido en este
   repositorio, con el panel de series de tiempo, el panel de % de datos válidos y
   la variable `dispositivo`) usando *Dashboards → New → Import*.
3. Tomar las capturas reales del dashboard funcionando para el PDF final.

## Uso de play.grafana.org como referencia

Mientras tanto, para ilustrar cómo se vería el resultado, se usó
`https://play.grafana.org` (instancia pública de demostración de Grafana Labs) como
referencia visual de paneles de series de tiempo y *stat panels* con umbrales,
equivalentes en estructura a los que se proponen en `grafana/dashboard.json`. Esta
instancia **no contiene datos de SolarBI**; solo sirve como referencia de la
interfaz y el tipo de panel.
