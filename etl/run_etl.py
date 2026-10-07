"""
run_etl.py — Único punto de entrada del pipeline ETL de SolarBI Pascual.

Flujo:
    Bronze (CSV crudo) -> reglas de calidad -> Silver (PostgreSQL, UPSERT)
                                             -> Gold / dwh.fact_energia_dia (UPSERT)

Uso:
    python3 etl/run_etl.py

Variables de entorno esperadas (ver .env.example, NUNCA subir el .env real):
    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD

El archivo Bronze (data/bronze/lecturas_bronze.csv) se trata como CRUDO:
este script solo LEE ese archivo, nunca lo modifica ni lo sobreescribe.

Idempotencia: cada fila de Silver se identifica por (ts, dispositivo_id) y
cada fila de Gold por (fecha_key, dispositivo_key). Ambas cargas usan
INSERT ... ON CONFLICT ... DO UPDATE (UPSERT), de modo que ejecutar este
script dos veces sobre el mismo Bronze deja los mismos conteos de filas
(ver sección "Reporte de idempotencia" en la salida).
"""

import csv
import os
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

BASE_DIR = Path(__file__).resolve().parent.parent
BRONZE_PATH = BASE_DIR / "data" / "bronze" / "lecturas_bronze.csv"
SILVER_CSV_PATH = BASE_DIR / "data" / "silver" / "lecturas_silver.csv"

POTENCIA_MAX_KW_PLAUSIBLE = 6.5  # inversor de 5 kWp; margen de sobredimensionamiento razonable


def conectar():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "solarbi"),
        user=os.environ.get("PGUSER", "solarbi"),
        password=os.environ.get("PGPASSWORD", ""),
    )


def leer_bronze():
    with open(BRONZE_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def aplicar_reglas_calidad(filas_bronze):
    """
    Regla 1 — Rango físico válido: p_ac_kw debe ser >= 0 y <= POTENCIA_MAX_KW_PLAUSIBLE.
    Regla 2 — Duplicados: se descartan filas exactamente repetidas (mismo ts+dispositivo+valores).
    Regla 3 — Datos faltantes: ts, dispositivo_id, p_ac_kw o irradiancia_wm2 vacíos.

    Orden de evaluación por fila: faltantes -> rango -> duplicados,
    de modo que cada fila rechazada cuenta en una sola categoría.
    """
    filas_leidas = len(filas_bronze)
    rechazadas_faltantes = 0
    rechazadas_rango = 0
    rechazadas_duplicados = 0
    vistas = set()
    validas = []

    for fila in filas_bronze:
        ts_raw = fila.get("ts", "").strip()
        disp = fila.get("dispositivo_id", "").strip()
        pot_raw = fila.get("p_ac_kw", "").strip()
        irr_raw = fila.get("irradiancia_wm2", "").strip()
        temp_raw = fila.get("temp_modulo_c", "").strip()

        # Regla 3: faltantes (campos obligatorios vacíos)
        if not ts_raw or not disp or not pot_raw or not irr_raw:
            rechazadas_faltantes += 1
            continue

        try:
            pot = float(pot_raw)
            irr = float(irr_raw)
            temp = float(temp_raw) if temp_raw else None
            ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            rechazadas_faltantes += 1
            continue

        # Regla 1: rango físico válido
        if pot < 0 or pot > POTENCIA_MAX_KW_PLAUSIBLE or irr < 0:
            rechazadas_rango += 1
            continue

        # Regla 2: duplicados exactos
        clave_dup = (ts_raw, disp, pot_raw, irr_raw, temp_raw)
        if clave_dup in vistas:
            rechazadas_duplicados += 1
            continue
        vistas.add(clave_dup)

        validas.append({
            "ts": ts,
            "dispositivo_id": disp,
            "p_ac_kw": pot,
            "irradiancia_wm2": irr,
            "temp_modulo_c": temp,
        })

    filas_validas = len(validas)
    porcentaje_datos_validos = round((filas_validas / filas_leidas) * 100, 2) if filas_leidas else 0.0

    metricas = {
        "filas_leidas": filas_leidas,
        "filas_rechazadas_por_rango": rechazadas_rango,
        "filas_rechazadas_por_duplicados": rechazadas_duplicados,
        "filas_rechazadas_por_faltantes": rechazadas_faltantes,
        "filas_validas": filas_validas,
        "porcentaje_datos_validos": porcentaje_datos_validos,
    }
    return validas, metricas


def escribir_silver_csv(filas_validas):
    SILVER_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SILVER_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ts", "dispositivo_id", "p_ac_kw", "irradiancia_wm2", "temp_modulo_c"])
        writer.writeheader()
        for r in filas_validas:
            writer.writerow({**r, "ts": r["ts"].strftime("%Y-%m-%d %H:%M:%S")})


def cargar_silver(conn, filas_validas):
    sql = """
        INSERT INTO silver.lectura_5min (ts, dispositivo_id, p_ac_kw, irradiancia_wm2, temp_modulo_c)
        VALUES %s
        ON CONFLICT (ts, dispositivo_id)
        DO UPDATE SET
            p_ac_kw = EXCLUDED.p_ac_kw,
            irradiancia_wm2 = EXCLUDED.irradiancia_wm2,
            temp_modulo_c = EXCLUDED.temp_modulo_c,
            cargado_en = now();
    """
    valores = [
        (r["ts"], r["dispositivo_id"], r["p_ac_kw"], r["irradiancia_wm2"], r["temp_modulo_c"])
        for r in filas_validas
    ]
    with conn.cursor() as cur:
        execute_values(cur, sql, valores)
    conn.commit()


def registrar_metricas_calidad(conn, metricas):
    sql = """
        INSERT INTO silver.metricas_calidad
            (filas_leidas, filas_rechazadas_por_rango, filas_rechazadas_por_duplicados,
             filas_rechazadas_por_faltantes, filas_validas, porcentaje_datos_validos)
        VALUES (%(filas_leidas)s, %(filas_rechazadas_por_rango)s, %(filas_rechazadas_por_duplicados)s,
                %(filas_rechazadas_por_faltantes)s, %(filas_validas)s, %(porcentaje_datos_validos)s);
    """
    with conn.cursor() as cur:
        cur.execute(sql, metricas)
    conn.commit()


def construir_gold(conn, metricas_globales):
    """
    Agrega silver.lectura_5min por día/dispositivo para construir dwh.fact_energia_dia.
    energia_intervalo_kwh = potencia_kw * (5/60) h; se agrega (SUM) por fecha y dispositivo.
    pct_datos_validos se guarda a nivel de corrida completa (métrica global del Bronze procesado).
    """
    select_sql = """
        SELECT date_trunc('day', ts)::date AS fecha_key,
               dispositivo_id AS dispositivo_key,
               SUM(p_ac_kw * (5.0/60.0)) AS energia_kwh
        FROM silver.lectura_5min
        GROUP BY 1, 2
        ORDER BY 1, 2;
    """
    upsert_sql = """
        INSERT INTO dwh.fact_energia_dia (fecha_key, dispositivo_key, energia_kwh, pct_datos_validos)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (fecha_key, dispositivo_key)
        DO UPDATE SET
            energia_kwh = EXCLUDED.energia_kwh,
            pct_datos_validos = EXCLUDED.pct_datos_validos,
            actualizado_en = now();
    """
    with conn.cursor() as cur:
        cur.execute(select_sql)
        filas = cur.fetchall()
        for fecha_key, dispositivo_key, energia_kwh in filas:
            cur.execute(upsert_sql, (fecha_key, dispositivo_key, round(float(energia_kwh), 3),
                                      metricas_globales["porcentaje_datos_validos"]))
    conn.commit()
    return len(filas)


def contar_filas(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM silver.lectura_5min;")
        n_silver = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM dwh.fact_energia_dia;")
        n_gold = cur.fetchone()[0]
    return n_silver, n_gold


def main():
    print("=== SolarBI Pascual — ETL (Bronze -> Silver -> Gold/PostgreSQL) ===")
    print(f"Leyendo Bronze: {BRONZE_PATH}")
    filas_bronze = leer_bronze()

    filas_validas, metricas = aplicar_reglas_calidad(filas_bronze)
    print("--- Métricas de calidad (Silver) ---")
    for k, v in metricas.items():
        print(f"{k}: {v}")

    escribir_silver_csv(filas_validas)
    print(f"Silver (CSV de respaldo) escrito en: {SILVER_CSV_PATH}")

    conn = conectar()
    try:
        n_silver_antes, n_gold_antes = contar_filas(conn)

        cargar_silver(conn, filas_validas)
        registrar_metricas_calidad(conn, metricas)
        n_filas_gold = construir_gold(conn, metricas)

        n_silver_despues, n_gold_despues = contar_filas(conn)

        print("--- Reporte de idempotencia (conteos en PostgreSQL) ---")
        print(f"silver.lectura_5min: antes={n_silver_antes} -> después={n_silver_despues}")
        print(f"dwh.fact_energia_dia: antes={n_gold_antes} -> después={n_gold_despues} (días x dispositivos agregados: {n_filas_gold})")
        print("Si esta es la segunda corrida sobre el mismo Bronze, 'antes' y 'después' deben coincidir: UPSERT evita duplicados.")
    finally:
        conn.close()

    print("=== ETL finalizado correctamente ===")


if __name__ == "__main__":
    main()
