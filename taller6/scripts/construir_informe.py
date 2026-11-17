#!/usr/bin/env python3
"""Arma el informe PDF a partir de la documentacion en Markdown y de las evidencias.

  python scripts/construir_informe.py

Markdown -> HTML (biblioteca markdown) -> PDF (Microsoft Edge sin ventana).
Los diagramas Mermaid se dibujan en el navegador. Requiere: pip install markdown
"""
from __future__ import annotations

import html
import re
import subprocess
from datetime import date
from pathlib import Path

import markdown

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / "docs"
SALIDA = DOCS / "informe"
NOMBRE = "BI_Taller6_Avendano_Usuga"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
REPO = "https://github.com/samuelalfonso011-eng/solarbi-avendano-usuga"

SECCIONES = ["01_negocio_y_fuente.md", "02_indicadores.md", "03_modelo_dimensional.md",
             "04_diccionario_datos.md", "05_etl_calidad.md", "06_base_datos.md", "07_powerbi.md",
             "08_grafana.md", "09_arquitectura_analisis.md", "10_etica_seguridad.md",
             "11_kubernetes.md", "12_sustentacion.md", "00_matriz_trazabilidad.md"]

# (titulo, archivo, patron de inicio o None, lineas maximas)
EVIDENCIAS = [
    ("Verificación de integridad (SHA-256) y descompresión", "01_descarga_sha256.txt", None, 20),
    ("Levantamiento desde cero con un solo comando: resumen final", "05_up_desde_cero.txt", r"\[7/8\]", 60),
    ("Job del ETL en el clúster: reglas, conciliación y huella (corrida 1)", "06_etl_job_k8s_corrida1.txt", r"\[2/6\]", 45),
    ("Job del ETL en el clúster: segunda corrida (idempotencia)", "07_etl_job_k8s_corrida2.txt", r"\[6/6\]", 8),
    ("Pruebas automáticas", "08_pruebas.txt", None, 50),
    ("Se elimina el pod de PostgreSQL: los datos siguen ahí", "10_demo_postgres.txt", None, 30),
    ("Se elimina el pod de Grafana: vuelve con su tablero", "11_demo_grafana.txt", None, 30),
    ("La alerta reacciona a datos nuevos", "12_demo_alerta.txt", None, 40),
    ("Bonificación: escalar Grafana", "13_demo_escalar.txt", None, 30),
    ("Bonificación: actualización de imagen del simulador y reversión", "14_demo_rolling.txt", None, 20),
    ("kubectl get all, configmap, secret, pvc", "15_kubectl_get_describe.txt", r"kubectl get all", 60),
    ("kubectl describe statefulset/postgres", "15_kubectl_get_describe.txt", r"describe statefulset/postgres", 75),
    ("kubectl describe deployment/grafana", "15_kubectl_get_describe.txt", r"describe deployment/grafana", 85),
    ("kubectl describe job/etl-carga-historica", "15_kubectl_get_describe.txt", r"describe job/etl-carga-historica", 60),
    ("kubectl describe cronjob/simulador", "15_kubectl_get_describe.txt", r"describe cronjob/simulador", 55),
    ("kubectl describe pvc y secret", "15_kubectl_get_describe.txt", r"describe pvc/datos-postgres-0", 45),
]

CSS = """
@page { size: A4; margin: 16mm 14mm 16mm 14mm; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 9.6pt; line-height: 1.38; color: #1c1c1c; }
h1 { font-size: 17pt; color: #0b3d5c; border-bottom: 2px solid #0b3d5c; padding-bottom: 3px; page-break-before: always; }
h2 { font-size: 12.5pt; color: #0b3d5c; margin-top: 16px; }
h3 { font-size: 10.5pt; color: #333; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 8.3pt; }
th, td { border: 1px solid #b9c4cc; padding: 3px 5px; vertical-align: top; text-align: left; }
th { background: #e6eef3; }
tr { page-break-inside: avoid; }
code { font-family: Consolas, monospace; font-size: 8.4pt; background: #f1f3f4; padding: 0 2px; }
pre { background: #f6f8fa; border: 1px solid #d0d7de; padding: 6px; font-size: 7.2pt; line-height: 1.25;
      white-space: pre-wrap; word-break: break-all; }
pre code { background: none; padding: 0; font-size: inherit; }
pre.mermaid { background: #fff; border: none; text-align: center; page-break-inside: avoid; }
img { max-width: 100%; border: 1px solid #b9c4cc; }
.portada { text-align: center; padding-top: 70mm; }
.portada h1 { page-break-before: avoid; border: none; font-size: 22pt; }
.portada p { font-size: 12pt; margin: 6px; }
.nota { font-size: 8.5pt; color: #555; }
"""


def md_a_html(texto: str) -> str:
    h = markdown.markdown(texto, extensions=["tables", "fenced_code", "sane_lists"])
    # bloques ```mermaid -> <pre class="mermaid"> para que el navegador los dibuje
    h = re.sub(r'<pre><code class="language-mermaid">(.*?)</code></pre>',
               lambda m: f'<pre class="mermaid">{m.group(1)}</pre>', h, flags=re.S)
    return h.replace('src="img/', 'src="../img/')


def recorte(archivo: str, patron: str | None, maximo: int) -> str:
    lineas = (DOCS / "evidencias" / archivo).read_text(encoding="utf-8", errors="replace").splitlines()
    inicio = 0
    if patron:
        inicio = next((i for i, l in enumerate(lineas) if re.search(patron, l)), 0)
    sel = [re.sub(r"\x1b\[[0-9;]*m", "", l)[:190] for l in lineas[inicio:inicio + maximo]]
    return "\n".join(sel)


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    partes = [f"""<div class="portada">
<p>INSTITUCIÓN UNIVERSITARIA PASCUAL BRAVO</p>
<p>Departamento de Sistemas Digitales · Inteligencia de Negocios · Semestre 2026-II</p>
<h1>Taller 6 · Solución de BI contenerizada y orquestada para el monitoreo energético de una microrred híbrida (solar + batería + red)</h1>
<p><b>Integrantes:</b> Samuel Alfonso Avendaño · Juan Andrés Usuga Serna</p>
<p><b>Docente:</b> Ramiro Grisales Montoya</p>
<p><b>Repositorio:</b> <a href="{REPO}">{REPO}</a> (carpeta <code>taller6/</code>)</p>
<p>{date.today().strftime('%d/%m/%Y')}</p>
<p class="nota">Datos: OpenCEM v1.0.0, DOI 10.5281/zenodo.21436223, licencia CC BY 4.0</p>
</div>"""]
    for archivo in SECCIONES:
        partes.append(md_a_html((DOCS / archivo).read_text(encoding="utf-8")))
    partes.append("<h1>Anexo: evidencias del clúster y de la ejecución</h1>"
                  "<p>Salidas reales de los comandos, guardadas en <code>docs/evidencias/</code>. "
                  "Se muestran recortadas; los archivos completos están en el repositorio.</p>")
    for titulo, archivo, patron, maximo in EVIDENCIAS:
        partes.append(f"<h3>{html.escape(titulo)}</h3><p class='nota'><code>docs/evidencias/{archivo}</code></p>"
                      f"<pre>{html.escape(recorte(archivo, patron, maximo))}</pre>")
    partes.append("<h3>Tablero de Grafana: reglas de alerta aprovisionadas</h3>"
                  "<img src='../img/grafana_reglas_alerta.png'>"
                  "<h3>Proyecto de Power BI abierto en Power BI Desktop (antes de actualizar los datos)</h3>"
                  "<img src='../img/powerbi_proyecto_abierto_sin_actualizar.png'>")
    documento = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{NOMBRE}</title>
<style>{CSS}</style></head><body>{''.join(partes)}
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.esm.min.mjs';
mermaid.initialize({{ startOnLoad: true, theme: 'neutral', flowchart: {{ useMaxWidth: true }} }});
</script></body></html>"""
    ruta_html = SALIDA / f"{NOMBRE}.html"
    ruta_html.write_text(documento, encoding="utf-8")
    ruta_pdf = SALIDA / f"{NOMBRE}.pdf"
    subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--virtual-time-budget=30000", f"--print-to-pdf={ruta_pdf}", ruta_html.as_uri()],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    print(f"PDF generado: {ruta_pdf} ({ruta_pdf.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
