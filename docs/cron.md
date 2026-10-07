# Programación del ETL (Parte B, punto 8)

Expresión cron para ejecutar `etl/run_etl.py` todos los días a medianoche
(hora del servidor):

```
0 0 * * *
```

Lectura: minuto `0`, hora `0`, cualquier día del mes, cualquier mes,
cualquier día de la semana → se dispara una vez al día, a las 00:00.

Entrada de `crontab -e` propuesta (ajustando rutas y entorno virtual si aplica):

```
0 0 * * * cd /ruta/al/repo/solarbi-apellido1-apellido2 && \
  PGHOST=localhost PGPORT=5432 PGDATABASE=solarbi PGUSER=solarbi PGPASSWORD=$(cat .pgpass_secret) \
  /usr/bin/python3 etl/run_etl.py >> logs/etl.log 2>&1
```

En Windows, el equivalente es una tarea del **Programador de tareas** con
desencadenador diario a las 00:00 y acción `python etl\run_etl.py`.

No se implementó como tarea programada real (no lo exige el requisito,
que solo pide escribir la expresión); si se quisiera automatizar en
producción, `run_etl.py` ya es idempotente por diseño (UPSERT), por lo que
reintentos o ejecuciones duplicadas por error del programador no dañan los
datos.
