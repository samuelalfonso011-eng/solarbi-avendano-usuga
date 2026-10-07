# Auditoría final contra la rúbrica (FASE 6)

| Requisito | ¿Cumple? | Evidencia |
|---|---|---|
| 19 preguntas | ✅ Sí | docs/parte_a_respuestas.md |
| Máximo 120 palabras por respuesta | ✅ Sí (verificado por script, todas ≤120) | docs/parte_a_respuestas.md |
| Fuentes por pregunta | ✅ Sí, cada respuesta cita su fuente | docs/parte_a_respuestas.md |
| Mínimo 5 fuentes | ✅ Sí, 10 fuentes listadas | PDF_final.md, sección Referencias |
| ETL Bronze/Silver/Gold | ✅ Sí, ejecutado realmente | etl/simulador.py, etl/run_etl.py |
| 3 reglas de calidad | ✅ Sí (rango, duplicados, faltantes) | run_etl.py, salida real en PDF |
| Métricas de calidad | ✅ Sí, calculadas y en PostgreSQL | silver.metricas_calidad |
| PostgreSQL | ✅ Sí, esquemas silver/dwh reales | sql/tables.sql, ejecutado |
| Idempotencia | ✅ Sí, demostrada con conteos antes/después | PDF_final Parte B |
| UPSERT | ✅ Sí, ON CONFLICT DO UPDATE | run_etl.py, sql/cargas.sql |
| Power BI | ⚠️ Parcial — no ejecutado (sin Power BI Desktop en el entorno) | powerbi/medidas_dax.md (código propuesto) |
| Medidas DAX | ⚠️ Propuestas, no ejecutadas en Power BI real | powerbi/medidas_dax.md |
| Yield | ⚠️ Medida DAX propuesta; valor esperado calculado desde datos reales | powerbi/medidas_dax.md |
| Ahorro | ⚠️ Medida DAX propuesta con parámetro de tarifa | powerbi/medidas_dax.md |
| Grafana | ❌ No instalado (red del entorno bloqueó la descarga; sin Docker) | docs/ruta_alternativa_grafana.md |
| $__timeFilter | ⚠️ Incluido en el JSON propuesto, no verificado en vivo | grafana/dashboard.json |
| Variable por dispositivo | ⚠️ Incluida en el JSON propuesto, no verificada en vivo | grafana/dashboard.json |
| JSON Grafana | ✅ Sí, archivo entregado y validado como JSON | grafana/dashboard.json |
| GitHub | ⚠️ Pendiente — repo aún no creado en GitHub.com | README.md, docs/commits_propuestos.md |
| README | ✅ Sí, completo | README.md |
| .gitignore | ✅ Sí, cubre .env, credenciales, .pbix, etc. | .gitignore |
| 3 commits por integrante | ⚠️ Pendiente — mensajes propuestos, faltan commits reales | docs/commits_propuestos.md |
| Evidencias | ⚠️ Parcial — Bronze/Silver/PostgreSQL con salida real; Power BI/Grafana/GitHub pendientes de captura real | docs/PDF_final.pdf |
| PDF máximo 18 páginas | ✅ Sí, 10 páginas | docs/PDF_final.pdf |
| Sin credenciales | ✅ Sí, solo variables de entorno de ejemplo | .env.example, .gitignore |

## Pendientes antes de entregar

1. **Nombre completo del integrante 2** (reemplazar `[PENDIENTE]` en portada,
   README y nombre del repo/PDF).
2. **Crear el repositorio real en GitHub**, nombrarlo
   `solarbi-apellido1-apellido2`, agregar al segundo integrante como
   colaborador y esperar que acepte.
3. **Hacer los commits reales** (mínimo 3 por persona, usando los mensajes
   propuestos en `docs/commits_propuestos.md` como guía, no copiados
   literalmente si no reflejan el trabajo real de cada quien).
4. **Instalar Power BI Desktop y Grafana OSS en un computador sin las
   restricciones de red de este entorno**, conectarlos a la misma base
   PostgreSQL (se puede recrear con `sql/tables.sql` + `etl/run_etl.py`, o
   migrar los datos ya generados), tomar las capturas reales y pegarlas en
   el PDF reemplazando las secciones "Resultado esperado / Estado: no
   ejecutado".
5. **Confirmar con el docente** la fecha límite exacta y el valor del
   trabajo (el documento de requisitos los deja en blanco).
6. **Renombrar el PDF final** a
   `NombreCompleto1_NombreCompleto2_Consulta_BI_G50.pdf` antes de subirlo a
   Classroom, e incluir el enlace al repositorio en el comentario de la
   entrega.
