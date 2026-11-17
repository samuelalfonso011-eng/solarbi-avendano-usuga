"""ETL de la microrred: Bronze (SQLite) -> Silver -> Gold (PostgreSQL).

Uso:  python -m microrred_etl.main
Configuracion por variables de entorno (ConfigMap / Secret):
  SQLITE_PATH, PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD,
  ZONA_HORARIA_SITIO, GAP_MAX_S, SOC_BAJO_PCT, V_AC_MIN, EVENTO_MIN_S, BAT_REPOSO_A,
  BATERIA_KWH, TARIFA_COP_KWH, TARIFA_VIGENTE_DESDE, TARIFA_FUENTE

Idempotencia: toda la carga ocurre en UNA transaccion que reemplaza el contenido
de Silver y Gold de forma determinista. Dos corridas dejan la misma
huella_resultado en audit.etl_ejecucion. Si algo falla, no cambia nada.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
from array import array
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

from . import __version__
from .transformar import (CAMPOS, REGLAS, Parametros, Transformador, episodios_alarma,
                          eventos_falla, extremos_contador, fila_silver, limpiar_contexto,
                          primer_elemento, versiones_config)

log = logging.getLogger("etl")
DOI = "10.5281/zenodo.21436223"
EPOCA = date(1970, 1, 1)


def configuracion() -> dict:
    e = os.environ
    return {
        "sqlite_path": e.get("SQLITE_PATH", "data/bronze/opencem-v1.0.0.sqlite"),
        "zona": e.get("ZONA_HORARIA_SITIO", "Asia/Shanghai"),
        "gap_max_s": float(e.get("GAP_MAX_S", "600")),
        "soc_bajo_pct": float(e.get("SOC_BAJO_PCT", "15")),
        "v_ac_min": float(e.get("V_AC_MIN", "100")),
        "evento_min_s": float(e.get("EVENTO_MIN_S", "60")),
        "bat_reposo_a": float(e.get("BAT_REPOSO_A", "0.9")),
        "bateria_kwh": float(e.get("BATERIA_KWH", "10.24")),
        "tarifa_cop_kwh": float(e["TARIFA_COP_KWH"]),
        "tarifa_vigente_desde": e.get("TARIFA_VIGENTE_DESDE", "2025-01-01"),
        "tarifa_fuente": e.get("TARIFA_FUENTE", "sin fuente declarada"),
        "calcular_sha256": e.get("CALCULAR_SHA256", "1") == "1",
    }


def abrir_bronze(ruta: str) -> sqlite3.Connection:
    """Abre el SQLite en solo lectura e inmutable: la capa Bronze no se modifica."""
    return sqlite3.connect(f"file:{Path(ruta).as_posix()}?mode=ro&immutable=1", uri=True)


def utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc)


def sha256_archivo(ruta: str) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while bloque := f.read(1 << 22):
            h.update(bloque)
    return h.hexdigest()


# ------------------------------------------------------------------ extraccion
def inventario_bronze(con) -> dict:
    inv = {}
    for (tabla,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                "AND name NOT LIKE 'sqlite_%' ORDER BY 1"):
        cols = {c[1] for c in con.execute(f'PRAGMA table_info("{tabla}")')}
        if "read_ts" in cols:
            n, a, b = con.execute(f'SELECT COUNT(*), MIN(read_ts), MAX(read_ts) FROM "{tabla}"').fetchone()
        else:
            n, a, b = con.execute(f'SELECT COUNT(*), MIN("start"), MAX("end") FROM "{tabla}"').fetchone()
        inv[tabla] = {"filas": n, "min_utc": utc(a).isoformat(), "max_utc": utc(b).isoformat()}
    return inv


def transformar_mediciones(con, p: Parametros):
    t = Transformador(p)
    sql = f"SELECT read_ts, inverter, {', '.join(CAMPOS)} FROM analog_measurements ORDER BY read_ts, inverter"
    n = 0
    for fila in con.execute(sql):
        t.agregar(fila[0], fila[1], fila[2:])
        n += 1
        if n % 500_000 == 0:
            log.info("  %s lecturas procesadas", f"{n:,}")
    return t.finalizar()


def filas_calidad(resultado) -> list:
    """Conteos antes/despues de cada regla, por inversor (las reglas se aplican en orden)."""
    filas = []
    for inv in sorted(resultado.leidas):
        restantes = resultado.leidas[inv]
        for orden, regla, tipo, descripcion in REGLAS:
            afectadas = resultado.afectadas.get((regla, inv), 0)
            despues = restantes - afectadas if tipo == "RECHAZA_FILA" else restantes
            filas.append((orden, regla, descripcion, tipo, inv, restantes, afectadas, despues))
            restantes = despues
    return filas


def extraer_contexto(con):
    filas, rechazos = [], Counter()
    sin_tipo = 0
    for fila in con.execute('SELECT id, recorded, "start", "end", value FROM context ORDER BY id'):
        limpia, motivo = limpiar_contexto(*fila)
        if limpia is None:
            rechazos[motivo] += 1
            continue
        if limpia[5] in ("calendario_academico", "anotacion_manual", "sin_clasificar"):
            sin_tipo += 1
        filas.append((limpia[0], utc(limpia[1]), utc(limpia[2]), utc(limpia[3]), *limpia[4:]))
    return filas, rechazos, sin_tipo


def extraer_config(con, desfase_s: int) -> list:
    sql = f"""SELECT inverter, CAST((read_ts + {desfase_s}) / 86400 AS INTEGER) AS dia,
                     outpriority, chgpriority, battfullsoc, COUNT(*)
              FROM settings
              WHERE outpriority IS NOT NULL AND chgpriority IS NOT NULL AND battfullsoc IS NOT NULL
              GROUP BY 1, 2, 3, 4, 5"""
    return versiones_config(con.execute(sql))


def extraer_contadores(con, desfase_s: int) -> list:
    """Primer y ultimo valor diario de los contadores acumulados del inversor."""
    series = defaultdict(lambda: (array("d"), array("d"), array("d")))
    sql = f"""SELECT inverter, CAST((read_ts + {desfase_s}) / 86400 AS INTEGER),
                     pvgeneratenergytotal, usedenergytotal, loadconsumlinetotal
              FROM statistics
              WHERE pvgeneratenergytotal IS NOT NULL OR usedenergytotal IS NOT NULL
                 OR loadconsumlinetotal IS NOT NULL"""
    for inv, dia, pv, carga, red in con.execute(sql):
        s = series[(inv, dia)]
        for arreglo, texto in zip(s, (pv, carga, red)):
            v = primer_elemento(texto)
            if v is not None:
                arreglo.append(v)
    filas = []
    for (inv, dia), s in sorted(series.items()):
        extremos = [extremos_contador(list(a)) for a in s]
        filas.append((inv, EPOCA + timedelta(days=dia), extremos[0][0], extremos[0][1],
                      extremos[1][0], extremos[1][1], extremos[2][0], extremos[2][1],
                      max(len(a) for a in s)))
    return filas


def extraer_eventos_extra(con, p: Parametros) -> list:
    alarmas = episodios_alarma(con.execute(
        "SELECT read_ts, inverter, sysalarmflag FROM status "
        "WHERE sysalarmflag IS NOT NULL ORDER BY inverter, read_ts"), p)
    fallas = eventos_falla(con.execute(
        "SELECT inverter, faulthistoryrecord00, MIN(faulthistoryrecord00_time), MIN(read_ts), COUNT(*) "
        "FROM fault_history WHERE faulthistoryrecord00 IS NOT NULL GROUP BY 1, 2"))
    return alarmas + fallas


# ----------------------------------------------------------------------- carga
def copiar(cur, tabla: str, columnas: list[str], filas) -> int:
    n = 0
    with cur.copy(f"COPY {tabla} ({', '.join(columnas)}) FROM STDIN") as cp:
        for fila in filas:
            cp.write_row(fila)
            n += 1
    return n


COLS_MEDICION = ["inversor_id", "ts_utc", "n_lecturas", "n_validas", "seg_observados", "e_solar_wh",
                 "e_carga_wh", "e_red_wh", "e_bat_carga_wh", "e_bat_descarga_wh", "e_red_a_bat_wh",
                 "p_solar_max_w", "p_carga_max_w", "p_red_max_w", "soc_prom", "soc_min", "soc_max",
                 "soc_fin", "v_bateria_prom", "temp_max_c", "seg_sin_red", "seg_salida_apagada",
                 "seg_bateria_baja"]

HUELLA_SQL = """
SELECT md5(string_agg(h, '|' ORDER BY t)) FROM (
  SELECT 'energia' t, md5(string_agg(f::text, '|' ORDER BY fecha_key, tiempo_key, inversor_key)) h FROM gold.fact_energia_5min f
  UNION ALL SELECT 'evento', md5(string_agg(f::text, '|' ORDER BY evento_id)) FROM gold.fact_evento f
  UNION ALL SELECT 'contexto', md5(string_agg(f::text, '|' ORDER BY contexto_id)) FROM gold.fact_contexto f
  UNION ALL SELECT 'inversor', md5(string_agg(f::text, '|' ORDER BY inversor_key)) FROM gold.dim_inversor f
  UNION ALL SELECT 'fecha', md5(string_agg(f::text, '|' ORDER BY fecha_key)) FROM gold.dim_fecha f
  UNION ALL SELECT 'tipo_contexto', md5(string_agg(f::text, '|' ORDER BY tipo_contexto_key)) FROM gold.dim_tipo_contexto f
) x"""


def ejecutar() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    cfg = configuracion()
    p = Parametros(cfg["gap_max_s"], cfg["soc_bajo_pct"], cfg["v_ac_min"], cfg["evento_min_s"],
                   cfg["bat_reposo_a"])
    t0 = time.time()
    ruta = cfg["sqlite_path"]
    if not Path(ruta).exists():
        log.error("No existe la fuente Bronze: %s", ruta)
        return 2
    desfase = int(datetime(2026, 1, 1, tzinfo=ZoneInfo(cfg["zona"])).utcoffset().total_seconds())

    con_pg = psycopg.connect("", autocommit=True)  # parametros por variables PG*
    parametros = {k: v for k, v in cfg.items() if k != "sqlite_path"}
    ejecucion_id = con_pg.execute(
        "INSERT INTO audit.etl_ejecucion (version_etl, parametros) VALUES (%s, %s) RETURNING ejecucion_id",
        (__version__, json.dumps(parametros))).fetchone()[0]
    log.info("Corrida %s | ETL %s | fuente %s", ejecucion_id, __version__, ruta)
    try:
        con = abrir_bronze(ruta)
        log.info("[1/6] Inventario de Bronze")
        inventario = inventario_bronze(con)
        for tabla, d in inventario.items():
            log.info("  %-20s %12s filas  %s -> %s", tabla, f"{d['filas']:,}", d["min_utc"], d["max_utc"])
        sha = sha256_archivo(ruta) if cfg["calcular_sha256"] else None
        log.info("  sha256 = %s", sha)

        log.info("[2/6] Lecturas: reglas de calidad + agregacion a 5 min")
        res = transformar_mediciones(con, p)
        calidad = filas_calidad(res)
        for orden, regla, _, tipo, inv, antes, afectadas, despues in calidad:
            log.info("  inv %s  %-26s %-16s antes=%10s afectadas=%9s despues=%10s",
                     inv, regla, tipo, f"{antes:,}", f"{afectadas:,}", f"{despues:,}")
        log.info("  episodios descartados por durar < %ss: %s", p.evento_min_s, res.episodios_descartados)

        log.info("[3/6] Eventos de alarma y fallas, configuracion y contadores")
        eventos = res.eventos + extraer_eventos_extra(con, p)
        log.info("  eventos por tipo: %s", dict(Counter(e[1] for e in eventos)))
        config = extraer_config(con, desfase)
        log.info("  versiones de configuracion (SCD2): %s", config)
        contadores = extraer_contadores(con, desfase)

        log.info("[4/6] Contexto JSON")
        contexto, rechazos, sin_tipo = extraer_contexto(con)
        log.info("  leidos=%s cargados=%s rechazados=%s clasificados_sin_tipo=%s",
                 inventario["context"]["filas"], len(contexto), dict(rechazos), sin_tipo)
        con.close()

        log.info("[5/6] Carga transaccional Silver + Gold")
        with con_pg.transaction(), con_pg.cursor() as cur:
            cur.execute("TRUNCATE silver.medicion_5min, silver.evento, silver.contexto, "
                        "silver.config_inversor, silver.contador_diario")
            cur.execute("INSERT INTO bronze.ingesta VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (ejecucion_id, Path(ruta).name, Path(ruta).stat().st_size, sha, DOI,
                         "CC BY 4.0", json.dumps(inventario)))
            cur.executemany(
                "INSERT INTO silver.calidad_regla VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [(ejecucion_id, *f) for f in calidad])
            n_silver = copiar(cur, "silver.medicion_5min", COLS_MEDICION,
                              ((f[0], utc(f[1]), *f[2:]) for f in
                               (fila_silver(k, b) for k, b in sorted(res.buckets.items()))))
            copiar(cur, "silver.evento",
                   ["inversor_id", "tipo_evento", "inicio_utc", "fin_utc", "n_lecturas", "valor_extremo", "detalle"],
                   ((e[0], e[1], utc(e[2]), utc(e[3]), e[4], e[5], None if e[6] is None else json.dumps(e[6]))
                    for e in sorted(eventos, key=lambda e: (e[0], e[1], e[2]))))
            copiar(cur, "silver.contexto",
                   ["contexto_id", "registrado_utc", "inicio_utc", "fin_utc", "fuente", "tipo_contexto",
                    "dispositivo", "inversor_id", "esfuerzo", "descripcion", "atributos"], contexto)
            copiar(cur, "silver.config_inversor",
                   ["inversor_id", "valido_desde", "valido_hasta", "prioridad_salida", "prioridad_carga",
                    "soc_bateria_llena"],
                   ((inv, date(1900, 1, 1) if i == 0 else EPOCA + timedelta(days=d0),
                     date(9999, 12, 31) if d1 is None else EPOCA + timedelta(days=d1), a, b, c)
                    for i, (inv, d0, d1, a, b, c) in _con_indice(config)))
            copiar(cur, "silver.contador_diario",
                   ["inversor_id", "fecha_local", "solar_ini_kwh", "solar_fin_kwh", "carga_ini_kwh",
                    "carga_fin_kwh", "red_ini_kwh", "red_fin_kwh", "n_muestras"], contadores)
            cur.execute("INSERT INTO gold.tarifa VALUES (%s, %s, %s) ON CONFLICT (vigente_desde) "
                        "DO UPDATE SET cop_kwh = EXCLUDED.cop_kwh, fuente = EXCLUDED.fuente",
                        (cfg["tarifa_vigente_desde"], cfg["tarifa_cop_kwh"], cfg["tarifa_fuente"]))
            for nombre, valor in (("etl.zona", cfg["zona"]), ("etl.bateria_kwh", str(cfg["bateria_kwh"])),
                                  ("etl.ejecucion_id", str(ejecucion_id))):
                cur.execute("SELECT set_config(%s, %s, true)", (nombre, valor))
            cur.execute(resources.files("microrred_etl").joinpath("sql/cargar_gold.sql").read_text("utf-8"))
            n_gold = cur.execute("SELECT COUNT(*) FROM gold.fact_energia_5min").fetchone()[0]
            if n_gold != n_silver:
                raise RuntimeError(f"Gold ({n_gold}) no concuerda con Silver ({n_silver})")
            huella = cur.execute(HUELLA_SQL).fetchone()[0]

        log.info("[6/6] Conciliacion y cierre")
        n_fuente = sum(res.leidas.values())
        if n_fuente != inventario["analog_measurements"]["filas"]:
            raise RuntimeError("Las filas leidas no coinciden con el inventario de Bronze")
        for fila in con_pg.execute(
                "SELECT magnitud, SUM(dias_conciliados), round(SUM(kwh_contador)::numeric, 1), "
                "round(SUM(kwh_integrado)::numeric, 1), "
                "round((100 * (SUM(kwh_integrado) - SUM(kwh_contador)) / NULLIF(SUM(kwh_contador), 0))::numeric, 2) "
                "FROM audit.conciliacion WHERE ejecucion_id = %s GROUP BY 1 ORDER BY 1", (ejecucion_id,)):
            log.info("  conciliacion %-6s dias=%s contador=%s kWh  integrado=%s kWh  diferencia=%s %%", *fila)
        con_pg.execute(
            "UPDATE audit.etl_ejecucion SET fin_utc = now(), estado = 'OK', filas_fuente = %s, "
            "filas_silver = %s, filas_gold = %s, huella_resultado = %s, mensaje = %s WHERE ejecucion_id = %s",
            (n_fuente, n_silver, n_gold, huella, f"{time.time() - t0:.0f} s", ejecucion_id))
        log.info("OK corrida=%s filas_fuente=%s filas_silver=%s filas_gold=%s huella=%s duracion=%.0fs",
                 ejecucion_id, f"{n_fuente:,}", f"{n_silver:,}", f"{n_gold:,}", huella, time.time() - t0)
        return 0
    except Exception as exc:  # deja evidencia del fallo y termina con codigo != 0
        log.exception("ETL fallido")
        con_pg.execute("UPDATE audit.etl_ejecucion SET fin_utc = now(), estado = 'ERROR', mensaje = %s "
                       "WHERE ejecucion_id = %s", (str(exc)[:2000], ejecucion_id))
        return 1
    finally:
        con_pg.close()


def _con_indice(config: list):
    """Numera las versiones dentro de cada inversor (la primera empieza en 1900-01-01)."""
    vistos: Counter = Counter()
    for fila in config:
        yield vistos[fila[0]], fila
        vistos[fila[0]] += 1


if __name__ == "__main__":
    sys.exit(ejecutar())
