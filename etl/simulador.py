"""
simulador.py — Simulador de telemetría para SolarBI Pascual.

Genera lecturas de un inversor solar de 5 kWp durante 3 días, con una
lectura cada 5 minutos (288 lecturas/día x 3 días = 864 lecturas),
e inyecta anomalías controladas que la capa Silver del ETL debe detectar:

  - Potencia negativa (físicamente inválida para un inversor en generación).
  - Irradiancia faltante (NULL).
  - Filas duplicadas exactas.

Salida: data/bronze/lecturas_bronze.csv (archivo CRUDO; el ETL NO debe
modificar este archivo una vez generado).

Uso:
    python3 etl/simulador.py
"""

import csv
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)  # reproducible: misma salida en cada corrida del simulador

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = BASE_DIR / "data" / "bronze" / "lecturas_bronze.csv"

DISPOSITIVOS = ["INV-01"]  # un inversor de 5 kWp
POTENCIA_NOMINAL_KW = 5.0
DIAS = 3
LECTURAS_POR_DIA = 288  # cada 5 minutos
INTERVALO_MIN = 5

FECHA_INICIO = datetime(2026, 9, 1, 0, 0, 0)


def curva_irradiancia(hora_decimal: float) -> float:
    """Curva solar simplificada tipo campana entre 6:00 y 18:00."""
    if hora_decimal < 6 or hora_decimal > 18:
        return 0.0
    x = (hora_decimal - 12) / 6  # -1 a 1
    base = max(0.0, math.cos(x * math.pi / 2)) ** 1.5
    ruido = random.uniform(-0.05, 0.05)
    return round(max(0.0, (base + ruido) * 950), 1)  # hasta ~950 W/m2


def potencia_desde_irradiancia(irr_wm2: float, temp_c: float) -> float:
    """Potencia AC aproximada a partir de irradiancia y temperatura del módulo."""
    if irr_wm2 <= 0:
        return 0.0
    factor_temp = 1 - max(0, temp_c - 25) * 0.004  # derating térmico simple
    pot = POTENCIA_NOMINAL_KW * (irr_wm2 / 1000) * factor_temp
    pot *= random.uniform(0.97, 1.0)  # pequeñas pérdidas/eficiencia inversor
    return round(max(0.0, pot), 3)


def temperatura_modulo(hora_decimal: float, irr_wm2: float) -> float:
    ambiente = 18 + 8 * max(0, math.sin((hora_decimal - 6) / 12 * math.pi))
    return round(ambiente + irr_wm2 * 0.02 + random.uniform(-1, 1), 1)


def generar_lecturas():
    filas = []
    for dia in range(DIAS):
        for i in range(LECTURAS_POR_DIA):
            ts = FECHA_INICIO + timedelta(days=dia, minutes=i * INTERVALO_MIN)
            hora_decimal = ts.hour + ts.minute / 60
            irr = curva_irradiancia(hora_decimal)
            temp = temperatura_modulo(hora_decimal, irr)
            pot = potencia_desde_irradiancia(irr, temp)
            for disp in DISPOSITIVOS:
                filas.append({
                    "ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "dispositivo_id": disp,
                    "p_ac_kw": pot,
                    "irradiancia_wm2": irr,
                    "temp_modulo_c": temp,
                })
    return filas


def inyectar_anomalias(filas):
    """Inyecta anomalías controladas y reporta cuántas de cada tipo."""
    n = len(filas)
    idx_todos = list(range(n))
    random.shuffle(idx_todos)

    # 1) Potencia negativa: ~1.5% de las filas con generación > 0
    idx_generando = [i for i in idx_todos if filas[i]["p_ac_kw"] > 0]
    n_neg = max(5, int(len(idx_generando) * 0.015))
    for i in idx_generando[:n_neg]:
        filas[i]["p_ac_kw"] = -abs(filas[i]["p_ac_kw"]) - random.uniform(0.1, 0.5)

    # 2) Irradiancia faltante: ~1% de las filas
    n_faltante = max(5, int(n * 0.01))
    for i in idx_todos[n_neg:n_neg + n_faltante]:
        filas[i]["irradiancia_wm2"] = ""  # se serializa como NULL/CSV vacío

    # 3) Filas duplicadas exactas: duplicar ~1% de las filas (se agregan al final)
    n_dup = max(5, int(n * 0.01))
    candidatas = idx_todos[n_neg + n_faltante: n_neg + n_faltante + n_dup]
    duplicadas = [dict(filas[i]) for i in candidatas]

    filas_finales = filas + duplicadas
    random.shuffle(filas_finales)

    resumen = {
        "lecturas_base": n,
        "potencia_negativa_inyectada": n_neg,
        "irradiancia_faltante_inyectada": n_faltante,
        "duplicados_inyectados": n_dup,
        "total_filas_bronze": len(filas_finales),
    }
    return filas_finales, resumen


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    filas = generar_lecturas()
    filas, resumen = inyectar_anomalias(filas)

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["ts", "dispositivo_id", "p_ac_kw", "irradiancia_wm2", "temp_modulo_c"],
        )
        writer.writeheader()
        writer.writerows(filas)

    print("=== Simulador SolarBI Pascual — resumen de ejecución ===")
    for k, v in resumen.items():
        print(f"{k}: {v}")
    print(f"Archivo generado: {OUT_PATH}")


if __name__ == "__main__":
    main()
