# Reflexión final (Parte B, paso 6) — máx. 10 líneas

Power BI resolvió mejor el reporte de negocio: medidas DAX centralizadas
(Yield, Ahorro) dan una sola cifra confiable y fácil de presentar. Grafana
resolvió mejor la vigilancia casi en tiempo real, con `$__timeFilter` y
variables de dashboard listas para explorar cualquier dispositivo sin tocar
consultas. Lo más difícil fue demostrar idempotencia real con UPSERT y
PostgreSQL corriendo en el mismo entorno que el ETL, y no poder instalar
Grafana OSS en el entorno de desarrollo por restricciones de red (ver ruta
alternativa documentada). Para el **operador de planta** usaríamos
**Grafana**, por su refresco rápido y alertas. Para un **directivo**
usaríamos **Power BI**, porque traduce la operación a KPIs de negocio
(ahorro en COP, yield) en un reporte pulido y fácil de compartir.
