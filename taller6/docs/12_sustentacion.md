# Guía de sustentación

Herramientas: terminal con `kubectl`, DBeaver, Power BI, Grafana, GitHub y el PDF.

## 1. Historia con datos (*data storytelling*)

**Problema.** El campus tiene dos inversores híbridos que generan 3 millones de lecturas al año y
nadie las convierte en decisiones.

**Hallazgos** (cifras del modelo, periodo 12-jul-2025 a 13-jul-2026):

1. **La microrred compra de noche lo que no guarda de día.** Entre el 83 % y el 85 % de la energía
   comprada a la red se consume en la noche y la madrugada; al mediodía solar casi no se compra
   (0,3 % y 3,7 %). La autosuficiencia del año es de solo 28,9 % (cómputo) y 30,9 % (climatización).
2. **El sol alcanza para el día, no para las 24 horas.** El inversor 2 entregó 4 070 kWh a su carga
   y generó 1 375 kWh solares: aun con batería perfecta, el sol cubriría un tercio.
3. **El inversor pequeño desperdicia la quinta parte de lo que recibe.** El inversor 1 atiende una
   carga media de ~245 W y pierde 576 kWh al año (≈ 20 % de sus entradas) en consumo propio; el
   inversor 2 pierde ≈ 8 %.
4. **Las cargas no siguen el calendario.** La climatización consume más en festivos (20,9 kWh/día)
   que en días laborales (15,4 kWh/día): hay equipos encendidos sin gente.
5. **Un entrenamiento en GPU añade 56 W (+19 %)** a la carga de cómputo.
6. **La calidad del registro es el primer riesgo.** 96,1 % de las lecturas son válidas, pero la
   disponibilidad es de 87,3 % y 69,4 %: hubo un hueco de 26 días en agosto de 2025 y el inversor 2
   quedó fuera de servicio desde mayo de 2026 sin que nadie fuera alertado.
7. **Con la tarifa oficial de EPM (991,29 COP/kWh)** la energía comprada costaría 4,63 millones de
   pesos al año y la microrred evita 1,89 millones.

**Recomendaciones a la dirección de infraestructura.**

| # | Recomendación | Sustento |
| --- | --- | --- |
| 1 | **Gestión de cargas antes que más paneles**: apagar o programar la climatización en festivos y noches; mover tareas de cómputo aplazables al mediodía solar | Hallazgos 1, 4 y 5: cuesta poco y ataca el 83 % de la compra |
| 2 | **Más batería antes que más paneles**, solo después de medir el recorte solar | Hallazgo 1: sobra sol al mediodía y falta de noche; sin venta a la red, más paneles se recortarían |
| 3 | **Revisar el dimensionamiento del inversor 1** (o unificar cargas en un solo inversor) | Hallazgo 3 |
| 4 | **Monitoreo con alertas en operación real** y responsable asignado | Hallazgo 6: el tablero de Grafana con la alerta de telemetría atrasada habría avisado en 5 minutos |
| 5 | **Instalar un piranómetro y registrar la potencia nominal** | Sin ellos no se puede calcular el *Performance Ratio* ni saber si los paneles rinden lo debido |
| 6 | **Revisar la medición de corriente de batería** | El sesgo en reposo impide confiar en la eficiencia de la batería del inversor 1 |

## 2. Guion de la demostración (≈ 15 minutos)

| Paso | Qué se muestra | Comando o herramienta |
| --- | --- | --- |
| 1 | Se parte de cero | `bash scripts/down.sh` ; `kubectl config get-contexts` |
| 2 | **Un solo comando** levanta todo (≈ 6–8 min con las imágenes ya descargadas) | `bash scripts/up.sh` |
| 3 | Mientras carga: problema, fuente, checksum, diagnóstico y reglas de calidad | PDF, `docs/evidencias/01_descarga_sha256.txt` |
| 4 | Objetos del clúster | `kubectl -n microrred-bi get all,cm,secret,pvc` |
| 5 | Evidencia del ETL: reglas, conciliación, huella | `kubectl -n microrred-bi logs job/etl-carga-historica --tail=40` |
| 6 | Modelo dimensional y consultas (ventana, JSON) | DBeaver → `localhost:15432`, `sql/consultas_negocio.sql` |
| 7 | Tablero operativo con datos llegando | Navegador → `http://localhost:13000` |
| 8 | **La alerta reacciona** | `kubectl -n microrred-bi set env cronjob/simulador SIM_ESCENARIO=bateria_baja` (≈ 2 min) y revertir con `SIM_ESCENARIO-` |
| 9 | **Se borra el pod de PostgreSQL: los datos siguen** | `bash scripts/demo_resiliencia.sh postgres` |
| 10 | **Se borra el pod de Grafana: vuelve con su tablero** | `bash scripts/demo_resiliencia.sh grafana` |
| 11 | Tablero analítico: balance, calidad, escenario de tarifa | Power BI → `powerbi/MicrorredBI.pbip` |
| 12 | Hallazgos y recomendaciones | PDF |
| 13 | Repositorio e historial | GitHub |

## 3. Lo que el docente puede pedir en vivo

| Petición | Cómo se resuelve |
| --- | --- |
| **Una nueva medida DAX** | Power BI → *Nueva medida*. Ejemplo: `Fracción nocturna de la compra % = DIVIDE(CALCULATE([Energía importada de red kWh], Tiempo[Periodo solar] = "Nocturno"), [Energía importada de red kWh])`. Al guardar, aparece como texto en `Energia.tmdl` |
| **Un nuevo panel** | Para explorar: en Grafana, *Add visualization* con una consulta sobre `live.lectura`. Para que cuente: se exporta el JSON a `grafana/dashboards/microrred_operacion.json` y se ejecuta `bash scripts/aplicar_config.sh` (el panel creado solo en la interfaz se pierde al reiniciar el pod, a propósito) |
| **Modificar una consulta** | DBeaver, sobre `sql/consultas_negocio.sql`. Ejemplo: cambiar el promedio móvil de 7 a 14 días → `ROWS BETWEEN 13 PRECEDING AND CURRENT ROW` |
| **Cambiar un umbral sin reconstruir la imagen** | Editar `ALERTA_SOC_BAJO_PCT` en `config/microrred.env` y ejecutar `bash scripts/aplicar_config.sh`: cambia el ConfigMap y el Deployment de Grafana se reinicia solo con el nuevo umbral. Para el simulador o el ETL: `SOC_BAJO_PCT`, `SIM_ESCENARIO`, etc., en el mismo archivo |
| **Eliminar un pod** | `kubectl -n microrred-bi delete pod postgres-0` → el StatefulSet lo recrea y monta el mismo PVC. `kubectl -n microrred-bi delete pod -l app=grafana` → el Deployment lo recrea con el aprovisionamiento |
| **Volver a ejecutar el ETL** | `bash scripts/etl_reejecutar.sh` → misma huella (idempotente) |
| **Escalar** | `kubectl -n microrred-bi scale deployment/grafana --replicas=2`. PostgreSQL no se escala así: serían dos bases distintas |
| **Ver un Secret** | `kubectl -n microrred-bi get secret microrred-credenciales -o yaml` muestra base64, que no es cifrado: por eso no se versiona |
| **¿Por qué el Job no se vuelve a ejecutar solo?** | Un Job terminado es inmutable; `up.sh` lo borra y lo crea de nuevo |

## 4. Preguntas de comprensión probables

- **¿Qué pasa si se borra el PVC?** Se pierden los datos; PostgreSQL arrancaría vacío, volvería a
  ejecutar el DDL y habría que relanzar el Job. Por eso el PVC no se borra al borrar el pod.
- **¿Por qué `IfNotPresent`?** Las imágenes propias no están en ningún registro: se copian al nodo.
  Con `Always` el *kubelet* intentaría descargarlas y fallaría.
- **¿Diferencia entre *readiness* y *liveness*?** *Readiness* saca al pod del Service mientras no
  esté listo; *liveness* reinicia el contenedor si deja de responder.
- **¿Por qué la disponibilidad no es 100 % si el ETL no falló?** Porque mide la fuente: huecos de
  telemetría de más de 10 minutos, no fallos del ETL.
- **¿Por qué 5 minutos?** Sección E.4.
- **¿Por qué los datos de China con tarifa de Medellín?** Es un escenario: cuánto costaría esta
  misma operación con la tarifa local.
