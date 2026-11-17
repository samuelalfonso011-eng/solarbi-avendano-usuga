"""Simulador de llegada de datos (streaming) para el tablero operativo.

No inventa valores: REPRODUCE intervalos historicos reales de gold.fact_energia_5min
re-fechados al instante actual. Cada ejecucion inserta una lectura por inversor en
live.lectura. Corre como CronJob (una pasada por minuto) o en bucle (docker-compose).

Como se elige el intervalo historico:
  dia  = SIM_DIA_BASE + (dia de hoy mod SIM_DIAS_CICLO)
  hora = hora local actual en SIM_ZONA_OPERACION, truncada a 5 minutos

Escenarios (SIM_ESCENARIO, cambiable desde el ConfigMap sin reconstruir la imagen):
  normal        reproduce el historico tal cual
  bateria_baja  fuerza el SOC del inversor SIM_INVERSOR_ESCENARIO a SIM_SOC_FORZADO
  sin_red       simula un corte de red en ese inversor (la bateria asume la carga)

Idempotente: la llave (inversor_id, ts) con ON CONFLICT DO NOTHING evita duplicados
si el CronJob se reintenta dentro del mismo minuto.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg

SQL_HISTORICO = """
SELECT i.inversor_id, h.ts_utc, h.seg_observados,
       h.e_solar_kwh, h.e_carga_kwh, h.e_red_kwh, h.e_bat_descarga_kwh - h.e_bat_carga_kwh,
       h.soc_prom, h.seg_sin_red
FROM gold.fact_energia_5min h
JOIN gold.dim_inversor i USING (inversor_key)
WHERE h.fecha_key = %s AND h.tiempo_key <= %s AND h.seg_observados > 0 AND h.soc_prom IS NOT NULL
  AND i.inversor_id = %s
ORDER BY h.tiempo_key DESC
LIMIT 1
"""
SQL_INSERTAR = """
INSERT INTO live.lectura (ts, inversor_id, p_solar_w, p_carga_w, p_red_w, p_bateria_w, soc_pct,
                          red_disponible, escenario, ts_origen)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (inversor_id, ts) DO NOTHING
"""


def intervalo_historico(ahora_utc: datetime, zona: str, dia_base: date, dias_ciclo: int) -> tuple[int, int]:
    """(fecha_key, tiempo_key) del intervalo historico que corresponde al instante actual."""
    local = ahora_utc.astimezone(ZoneInfo(zona))
    dia = dia_base + timedelta(days=local.date().toordinal() % dias_ciclo)
    return int(dia.strftime("%Y%m%d")), local.hour * 12 + local.minute // 5


def aplicar_escenario(lectura: dict, escenario: str, inversor_objetivo: int, soc_forzado: float) -> dict:
    """Devuelve la lectura con el escenario aplicado (solo al inversor objetivo)."""
    if escenario == "normal" or lectura["inversor_id"] != inversor_objetivo:
        return {**lectura, "escenario": "normal"}
    if escenario == "bateria_baja":
        return {**lectura, "soc_pct": min(lectura["soc_pct"], soc_forzado), "escenario": escenario}
    if escenario == "sin_red":
        deficit = max(lectura["p_carga_w"] - lectura["p_solar_w"], 0.0)
        return {**lectura, "p_red_w": 0.0, "p_bateria_w": deficit, "red_disponible": False,
                "escenario": escenario}
    raise ValueError(f"SIM_ESCENARIO desconocido: {escenario}")


def a_lectura(fila) -> dict:
    inv, ts_origen, seg, e_solar, e_carga, e_red, e_bat, soc, seg_sin_red = fila
    a_w = 3_600_000.0 / seg  # kWh del intervalo -> potencia media en W
    return {"inversor_id": inv, "ts_origen": ts_origen,
            "p_solar_w": round(e_solar * a_w, 1), "p_carga_w": round(e_carga * a_w, 1),
            "p_red_w": round(e_red * a_w, 1), "p_bateria_w": round(e_bat * a_w, 1),
            "soc_pct": round(float(soc), 1), "red_disponible": seg_sin_red < seg / 2}


def pasada(con, cfg: dict) -> list[dict]:
    ahora = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    fecha_key, tiempo_key = intervalo_historico(ahora, cfg["zona"], cfg["dia_base"], cfg["dias_ciclo"])
    insertadas = []
    for inversor in (1, 2):
        fila = con.execute(SQL_HISTORICO, (fecha_key, tiempo_key, inversor)).fetchone()
        if fila is None:
            print(json.dumps({"ts": ahora.isoformat(), "inversor_id": inversor, "omitida":
                              f"sin historico para fecha_key={fecha_key} tiempo_key<={tiempo_key}"}))
            continue
        l = aplicar_escenario(a_lectura(fila), cfg["escenario"], cfg["inversor_escenario"], cfg["soc_forzado"])
        cur = con.execute(SQL_INSERTAR, (ahora, l["inversor_id"], l["p_solar_w"], l["p_carga_w"], l["p_red_w"],
                                         l["p_bateria_w"], l["soc_pct"], l["red_disponible"], l["escenario"],
                                         l["ts_origen"]))
        l.update(ts=ahora.isoformat(), ts_origen=l["ts_origen"].isoformat(), nueva=cur.rowcount == 1)
        print(json.dumps(l))
        insertadas.append(l)
    con.commit()
    return insertadas


def configuracion() -> dict:
    e = os.environ
    return {"escenario": e.get("SIM_ESCENARIO", "normal"),
            "inversor_escenario": int(e.get("SIM_INVERSOR_ESCENARIO", "2")),
            "soc_forzado": float(e.get("SIM_SOC_FORZADO", "8")),
            "dia_base": date.fromisoformat(e.get("SIM_DIA_BASE", "2026-01-12")),
            "dias_ciclo": int(e.get("SIM_DIAS_CICLO", "7")),
            "zona": e.get("SIM_ZONA_OPERACION", "America/Bogota"),
            "intervalo_s": int(e.get("SIM_INTERVALO_S", "60")),
            "modo": e.get("SIM_MODO", "una_vez")}


def main() -> int:
    cfg = configuracion()
    with psycopg.connect("") as con:  # parametros por variables PG*
        if cfg["modo"] == "una_vez":
            return 0 if pasada(con, cfg) else 1
        while True:  # modo continuo (docker-compose)
            pasada(con, cfg)
            sys.stdout.flush()
            time.sleep(cfg["intervalo_s"])


if __name__ == "__main__":
    sys.exit(main())
