#!/usr/bin/env python3
"""Diagnostico de la capa Bronze (SQLite OpenCEM, abierto en solo lectura).

No supone nombres de tablas ni columnas: los descubre con sqlite_master y
PRAGMA table_info. Produce un JSON con:
  - inventario: tablas, columnas, tipos, filas, indices
  - cobertura temporal por tabla e inversor (min, max, dias con datos)
  - nulos por columna
  - duplicados por llave natural (read_ts, inverter)
  - cadencia de muestreo y huecos (analog_measurements)
  - rangos y valores anomalos de las variables fisicas
  - perfil de los registros de contexto JSON (llaves, tipos, fuentes)

Uso:
  python scripts/diagnostico_bronze.py data/bronze/opencem-v1.0.0.sqlite \
         docs/evidencias/diagnostico_bronze.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def iso(ts):
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def q(con, sql, *params):
    return con.execute(sql, params).fetchall()


def inventario(con) -> dict:
    tablas = {}
    for (nombre,) in q(con, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        cols = q(con, f'PRAGMA table_info("{nombre}")')
        columnas = [{"nombre": c[1], "tipo": c[2], "not_null": bool(c[3]), "pk": bool(c[5])} for c in cols]
        partes = ", ".join(f'COUNT("{c["nombre"]}")' for c in columnas)
        fila = q(con, f'SELECT COUNT(*), {partes} FROM "{nombre}"')[0]
        total = fila[0]
        for c, no_nulos in zip(columnas, fila[1:]):
            c["nulos"] = total - no_nulos
            c["pct_nulos"] = round(100 * (total - no_nulos) / total, 4) if total else None
        indices = [{"nombre": i[1], "unico": bool(i[2])} for i in q(con, f'PRAGMA index_list("{nombre}")')]
        tablas[nombre] = {"filas": total, "n_columnas": len(columnas), "columnas": columnas, "indices": indices}
        print(f"  {nombre}: {total:,} filas, {len(columnas)} columnas", flush=True)
    return tablas


def cobertura(con, tablas) -> dict:
    res = {}
    for nombre, t in tablas.items():
        nombres = {c["nombre"] for c in t["columnas"]}
        if {"read_ts", "inverter"} <= nombres:
            filas = q(con, f'''SELECT inverter, COUNT(*), MIN(read_ts), MAX(read_ts),
                                      COUNT(DISTINCT CAST(read_ts/86400 AS INTEGER))
                               FROM "{nombre}" GROUP BY inverter ORDER BY inverter''')
            dup = q(con, f'''SELECT COUNT(*) FROM (SELECT 1 FROM "{nombre}"
                             GROUP BY read_ts, inverter HAVING COUNT(*) > 1)''')[0][0]
            res[nombre] = {"llave_natural": "(read_ts, inverter)", "llaves_duplicadas": dup, "por_inversor": [
                {"inverter": r[0], "filas": r[1], "min_utc": iso(r[2]), "max_utc": iso(r[3]),
                 "dias_utc_con_datos": r[4],
                 "dias_calendario": int((r[3] - r[2]) // 86400) + 1} for r in filas]}
        elif {"start", "end", "recorded"} <= nombres:
            r = q(con, f'SELECT COUNT(*), MIN("start"), MAX("end"), MIN(recorded), MAX(recorded) FROM "{nombre}"')[0]
            res[nombre] = {"filas": r[0], "min_start_utc": iso(r[1]), "max_end_utc": iso(r[2]),
                           "min_recorded_utc": iso(r[3]), "max_recorded_utc": iso(r[4]),
                           "end_menor_que_start": q(con, f'SELECT COUNT(*) FROM "{nombre}" WHERE "end" < "start"')[0][0],
                           "recorded_posterior_a_start": q(con, f'SELECT COUNT(*) FROM "{nombre}" WHERE recorded > "start"')[0][0]}
    return res


def cadencia(con, tabla="analog_measurements") -> dict:
    """Distribucion de los intervalos entre lecturas consecutivas por inversor."""
    res = {}
    for (inv,) in q(con, f'SELECT DISTINCT inverter FROM "{tabla}" ORDER BY 1'):
        bins = Counter()
        huecos = []
        deltas_muestra = []
        previo = None
        n = 0
        for (ts,) in con.execute(f'SELECT read_ts FROM "{tabla}" WHERE inverter=? ORDER BY read_ts', (inv,)):
            if previo is not None:
                d = ts - previo
                n += 1
                if n % 50 == 0:
                    deltas_muestra.append(d)
                clave = ("0-30 s" if d <= 30 else "30-60 s" if d <= 60 else "1-10 min" if d <= 600
                         else "10-60 min" if d <= 3600 else "1-24 h" if d <= 86400 else "> 1 dia")
                bins[clave] += 1
                if d > 3600:
                    huecos.append({"desde_utc": iso(previo), "hasta_utc": iso(ts), "horas": round(d / 3600, 2)})
            previo = ts
        deltas_muestra.sort()
        m = len(deltas_muestra)
        res[str(inv)] = {
            "intervalos": n,
            "mediana_s_aprox": round(deltas_muestra[m // 2], 3) if m else None,
            "p95_s_aprox": round(deltas_muestra[int(m * 0.95)], 3) if m else None,
            "p99_s_aprox": round(deltas_muestra[int(m * 0.99)], 3) if m else None,
            "distribucion": dict(bins),
            "huecos_mayores_1h": sorted(huecos, key=lambda h: -h["horas"]),
            "horas_perdidas_en_huecos_mayores_1h": round(sum(h["horas"] for h in huecos), 1),
        }
    return res


def rangos(con, tablas, tabla="analog_measurements") -> dict:
    """Min, max, promedio y conteos de ceros/negativos de las columnas numericas."""
    res = {}
    numericas = [c["nombre"] for c in tablas[tabla]["columnas"]
                 if c["tipo"] in ("REAL", "INTEGER") and c["nombre"] not in ("read_ts", "inverter")]
    for (inv,) in q(con, f'SELECT DISTINCT inverter FROM "{tabla}" ORDER BY 1'):
        partes = ", ".join(
            f'MIN("{c}"), MAX("{c}"), AVG("{c}"), SUM("{c}" < 0), SUM("{c}" = 0)' for c in numericas)
        fila = q(con, f'SELECT {partes} FROM "{tabla}" WHERE inverter=?', inv)[0]
        res[str(inv)] = {c: {"min": fila[i * 5], "max": fila[i * 5 + 1],
                             "promedio": None if fila[i * 5 + 2] is None else round(fila[i * 5 + 2], 3),
                             "negativos": fila[i * 5 + 3], "ceros": fila[i * 5 + 4]}
                         for i, c in enumerate(numericas)}
    return res


def filas_totalmente_nulas(con, tablas, tabla="analog_measurements") -> dict:
    datos = [c["nombre"] for c in tablas[tabla]["columnas"] if c["nombre"] not in ("read_ts", "inverter")]
    todas = " AND ".join(f'"{c}" IS NULL' for c in datos)
    alguna = " OR ".join(f'"{c}" IS NULL' for c in datos)
    return {str(r[0]): {"filas": r[1], "todas_las_columnas_nulas": r[2], "al_menos_una_nula": r[3]}
            for r in q(con, f'''SELECT inverter, COUNT(*), SUM({todas}), SUM({alguna})
                                FROM "{tabla}" GROUP BY inverter ORDER BY inverter''')}


def perfil_contexto(con, tabla="context") -> dict:
    tipos = Counter()
    llaves = Counter()
    combinaciones = Counter()
    invalidos = 0
    ejemplos = {}
    duraciones = {}
    for id_, recorded, start, end, valor in con.execute(f'SELECT id, recorded, "start", "end", value FROM "{tabla}"'):
        try:
            obj = json.loads(valor)
        except (TypeError, ValueError):
            invalidos += 1
            continue
        if not isinstance(obj, dict):
            tipos[f"<{type(obj).__name__}>"] += 1
            continue
        llaves.update(obj.keys())
        tipo = str(obj.get("context_type", "<sin context_type>"))
        fuente = str(obj.get("source", "<sin source>"))
        tipos[tipo] += 1
        combinaciones[f"{fuente} | {tipo}"] += 1
        ejemplos.setdefault(tipo, {"id": id_, "recorded_utc": iso(recorded), "start_utc": iso(start),
                                   "end_utc": iso(end), "value": obj})
        d = duraciones.setdefault(tipo, [0, 0.0, None, None])
        dur = (end - start) / 3600
        d[0] += 1
        d[1] += dur
        d[2] = dur if d[2] is None else min(d[2], dur)
        d[3] = dur if d[3] is None else max(d[3], dur)
    return {
        "json_invalidos": invalidos,
        "llaves_de_primer_nivel": dict(llaves.most_common()),
        "registros_por_tipo": dict(tipos.most_common()),
        "registros_por_fuente_y_tipo": dict(combinaciones.most_common()),
        "duracion_horas_por_tipo": {k: {"n": v[0], "promedio": round(v[1] / v[0], 3),
                                        "min": round(v[2], 3), "max": round(v[3], 3)} for k, v in duraciones.items()},
        "ejemplo_por_tipo": ejemplos,
    }


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    origen, salida = Path(sys.argv[1]), Path(sys.argv[2])
    con = sqlite3.connect(f"file:{origen.as_posix()}?mode=ro&immutable=1", uri=True)
    t0 = time.time()
    informe = {"archivo": origen.name, "bytes": origen.stat().st_size,
               "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "sqlite_version": sqlite3.sqlite_version}
    pasos = [
        ("inventario", lambda: inventario(con)),
        ("cobertura", lambda: cobertura(con, informe["inventario"])),
        ("cadencia_analog_measurements", lambda: cadencia(con)),
        ("rangos_analog_measurements", lambda: rangos(con, informe["inventario"])),
        ("nulidad_por_fila_analog_measurements", lambda: filas_totalmente_nulas(con, informe["inventario"])),
        ("contexto", lambda: perfil_contexto(con)),
    ]
    for nombre, fn in pasos:
        print(f"[{time.time() - t0:6.0f}s] {nombre}", flush=True)
        informe[nombre] = fn()
    informe["segundos"] = round(time.time() - t0, 1)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(informe, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print("Informe escrito en", salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
