#!/usr/bin/env python3
"""Captura de pantalla del tablero de Grafana para el informe (evidencia reproducible).

Inicia sesion por la API de Grafana con las credenciales de .env, abre el tablero en
Microsoft Edge sin ventana (protocolo DevTools) y guarda un PNG.

  python scripts/captura_grafana.py docs/img/grafana_operacion.png [--desde now-1h] [--alto 2300]

Requiere: pip install websocket-client ; Microsoft Edge instalado.
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket  # websocket-client

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
RAIZ = Path(__file__).resolve().parents[1]


def leer_env(ruta: Path) -> dict:
    pares = (l.split("=", 1) for l in ruta.read_text(encoding="utf-8").splitlines() if "=" in l and not l.startswith("#"))
    return {k.strip(): v.strip() for k, v in pares}


def sesion_grafana(base: str, usuario: str, clave: str) -> str:
    """Devuelve el valor de la cookie grafana_session."""
    datos = json.dumps({"user": usuario, "password": clave}).encode()
    peticion = urllib.request.Request(f"{base}/login", data=datos, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(peticion, timeout=30) as r:
        for cabecera in r.headers.get_all("Set-Cookie") or []:
            if cabecera.startswith("grafana_session="):
                return cabecera.split(";")[0].split("=", 1)[1]
    raise RuntimeError("Grafana no devolvio la cookie de sesion")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("salida", type=Path)
    ap.add_argument("--base", default="http://localhost:13000")
    ap.add_argument("--ruta", default="/d/microrred-operacion/microrred-hibrida-operacion")
    ap.add_argument("--desde", default="now-1h")
    ap.add_argument("--ancho", type=int, default=1500)
    ap.add_argument("--alto", type=int, default=2300)
    ap.add_argument("--espera", type=float, default=12.0)
    ap.add_argument("--puerto", type=int, default=9333)
    args = ap.parse_args()

    env = leer_env(RAIZ / ".env")
    cookie = sesion_grafana(args.base, env["GF_SECURITY_ADMIN_USER"], env["GF_SECURITY_ADMIN_PASSWORD"])
    url = f"{args.base}{args.ruta}?orgId=1&from={args.desde}&to=now&kiosk"
    if "?" in args.ruta:
        url = f"{args.base}{args.ruta}"

    perfil = tempfile.mkdtemp(prefix="edge-captura-")
    edge = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={args.puerto}",
                             f"--user-data-dir={perfil}", f"--window-size={args.ancho},{args.alto}",
                             "--hide-scrollbars", "--no-first-run", "--disable-gpu", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.puerto}/json", timeout=2) as r:
                    paginas = [p for p in json.load(r) if p.get("type") == "page"]
                if paginas:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError("Edge no abrio el puerto de depuracion")
        ws = websocket.create_connection(paginas[0]["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
        contador = [0]

        def cdp(metodo: str, **params):
            contador[0] += 1
            ws.send(json.dumps({"id": contador[0], "method": metodo, "params": params}))
            while True:
                respuesta = json.loads(ws.recv())
                if respuesta.get("id") == contador[0]:
                    return respuesta.get("result", {})

        cdp("Network.enable")
        cdp("Network.setCookie", name="grafana_session", value=cookie, url=args.base)
        cdp("Emulation.setDeviceMetricsOverride", width=args.ancho, height=args.alto, deviceScaleFactor=1, mobile=False)
        cdp("Page.navigate", url=url)
        time.sleep(args.espera)
        png = cdp("Page.captureScreenshot", format="png")["data"]
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        args.salida.write_bytes(base64.b64decode(png))
        print("captura guardada:", args.salida, f"({args.salida.stat().st_size:,} bytes)")
        ws.close()
    finally:
        edge.terminate()


if __name__ == "__main__":
    main()
