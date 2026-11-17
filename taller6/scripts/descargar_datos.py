#!/usr/bin/env python3
"""Descarga verificable y reanudable del registro OpenCEM v1.0.0 (Zenodo).

Solo descarga los archivos que el taller necesita (~310 MB); las imagenes de
cielo (opencem-v1.0.0-sky-*.tar.zst) quedan fuera del alcance.

Pasos:
  1. Descarga con reanudacion (cabecera HTTP Range) a <destino>/<archivo>.part
  2. Verificacion SHA-256 contra opencem-v1.0.0-SHA256SUMS.txt
  3. Descompresion reproducible del .sqlite.zst (python-zstandard, streaming)
  4. Escritura de un manifiesto JSON de procedencia (bronze_manifest.json)

Uso:
  python scripts/descargar_datos.py [--destino data/bronze]

Es idempotente: un archivo ya descargado y verificado no se vuelve a bajar.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RECORD_ID = "21436223"
DOI = "10.5281/zenodo.21436223"
BASE_URL = f"https://zenodo.org/api/records/{RECORD_ID}/files"
SUMS = "opencem-v1.0.0-SHA256SUMS.txt"
ARCHIVOS = [
    SUMS,
    "README.md",
    "LICENSE-DATA.txt",
    "opencem-v1.0.0-support.zip",
    "opencem-v1.0.0.sqlite.zst",
]
SQLITE_ZST = "opencem-v1.0.0.sqlite.zst"
SQLITE = "opencem-v1.0.0.sqlite"
BLOQUE = 1 << 20
USER_AGENT = "taller6-bi-descarga/1.0 (python-urllib)"


def sha256_de(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        while bloque := f.read(BLOQUE):
            h.update(bloque)
    return h.hexdigest()


def descargar(nombre: str, destino: Path, reintentos: int = 8) -> Path:
    """Descarga `nombre` reanudando desde el .part si existe."""
    final = destino / nombre
    if final.exists():
        return final
    parcial = destino / (nombre + ".part")
    url = f"{BASE_URL}/{nombre}/content"
    for intento in range(1, reintentos + 1):
        ya = parcial.stat().st_size if parcial.exists() else 0
        peticion = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if ya:
            peticion.add_header("Range", f"bytes={ya}-")
        try:
            with urllib.request.urlopen(peticion, timeout=60) as resp:
                if ya and resp.status != 206:
                    ya = 0  # el servidor ignoro Range: se empieza de cero
                modo = "ab" if ya else "wb"
                total = ya + int(resp.headers.get("Content-Length", 0))
                with parcial.open(modo) as f:
                    while bloque := resp.read(BLOQUE):
                        f.write(bloque)
            if total and parcial.stat().st_size != total:
                raise IOError("descarga incompleta")
            os.replace(parcial, final)
            print(f"  descargado {nombre} ({final.stat().st_size:,} bytes)")
            return final
        except urllib.error.HTTPError as e:
            if e.code == 416:  # el .part ya estaba completo
                os.replace(parcial, final)
                return final
            print(f"  intento {intento}: HTTP {e.code}", file=sys.stderr)
        except (urllib.error.URLError, IOError, TimeoutError) as e:
            print(f"  intento {intento}: {e}", file=sys.stderr)
        time.sleep(min(30, 2 ** intento))
    raise SystemExit(f"No fue posible descargar {nombre}")


def leer_sumas(ruta: Path) -> dict[str, str]:
    sumas = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        partes = linea.split()
        if len(partes) >= 2:
            sumas[partes[-1].lstrip("*").split("/")[-1]] = partes[0].lower()
    return sumas


def descomprimir(origen: Path, destino: Path) -> None:
    import zstandard  # dependencia unica de este script

    temporal = destino.with_suffix(destino.suffix + ".tmp")
    with origen.open("rb") as fin, temporal.open("wb") as fout:
        zstandard.ZstdDecompressor().copy_stream(fin, fout, read_size=BLOQUE, write_size=BLOQUE)
    os.replace(temporal, destino)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--destino", default="data/bronze", type=Path)
    args = ap.parse_args()
    destino: Path = args.destino
    destino.mkdir(parents=True, exist_ok=True)

    print("1) Descarga")
    for nombre in ARCHIVOS:
        descargar(nombre, destino)

    print("2) Verificacion SHA-256")
    sumas = leer_sumas(destino / SUMS)
    evidencia = []
    ok = True
    for nombre in ARCHIVOS:
        if nombre == SUMS:
            continue
        calculada = sha256_de(destino / nombre)
        esperada = sumas.get(nombre)
        estado = "SIN_REFERENCIA" if esperada is None else ("OK" if esperada == calculada else "FALLA")
        ok &= estado != "FALLA"
        evidencia.append({"archivo": nombre, "bytes": (destino / nombre).stat().st_size,
                          "sha256_calculada": calculada, "sha256_esperada": esperada, "estado": estado})
        print(f"  {estado:15} {calculada}  {nombre}")
    if not ok:
        print("ERROR: al menos un archivo no coincide con su SHA-256", file=sys.stderr)
        return 1

    print("3) Descompresion")
    sqlite = destino / SQLITE
    if sqlite.exists():
        print(f"  ya existe {sqlite.name}")
    else:
        descomprimir(destino / SQLITE_ZST, sqlite)
    sha_sqlite = sha256_de(sqlite)
    estado_sqlite = "SIN_REFERENCIA"
    if SQLITE in sumas:
        estado_sqlite = "OK" if sumas[SQLITE] == sha_sqlite else "FALLA"
    print(f"  {estado_sqlite:15} {sha_sqlite}  {SQLITE} ({sqlite.stat().st_size:,} bytes)")
    try:
        os.chmod(sqlite, 0o444)  # Bronze es inmutable
    except OSError:
        pass

    manifiesto = {
        "fuente": "OpenCEM v1.0.0", "doi": DOI,
        "url": f"https://zenodo.org/records/{RECORD_ID}", "licencia": "CC BY 4.0",
        "descargado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "herramienta_descompresion": "python-zstandard (ZstdDecompressor.copy_stream)",
        "archivos": evidencia,
        "sqlite": {"archivo": SQLITE, "bytes": sqlite.stat().st_size,
                   "sha256": sha_sqlite, "estado": estado_sqlite},
    }
    (destino / "bronze_manifest.json").write_text(json.dumps(manifiesto, indent=2), encoding="utf-8")
    print("4) Manifiesto escrito en", destino / "bronze_manifest.json")
    return 1 if estado_sqlite == "FALLA" else 0


if __name__ == "__main__":
    sys.exit(main())
