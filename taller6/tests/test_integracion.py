"""Pruebas de integracion contra el PostgreSQL ya cargado (docker-compose o Kubernetes).

  bash scripts/pruebas.sh        # unitarias + integracion

Se omiten solas si no hay base disponible (variables PG* sin definir).
Verifican criterios de aceptacion del taller: conciliacion, idempotencia,
integridad del modelo, calidad de datos, JSON y minimo privilegio.
"""
import os

import pytest

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.skipif("PGHOST" not in os.environ, reason="sin PostgreSQL (definir PG*)")


@pytest.fixture(scope="module")
def con():
    with psycopg.connect("", autocommit=True) as c:
        yield c


def uno(con, sql, *params):
    return con.execute(sql, params or None).fetchone()[0]


# ------------------------------------------------------------------ conciliacion
def test_filas_fuente_igual_a_validas_mas_rechazadas(con):
    fuente, leidas, rechazadas, validas = con.execute("""
        WITH e AS (SELECT MAX(ejecucion_id) id FROM audit.etl_ejecucion WHERE estado = 'OK')
        SELECT (SELECT filas_fuente FROM audit.etl_ejecucion, e WHERE ejecucion_id = e.id),
               (SELECT SUM(filas_antes) FROM silver.calidad_regla, e WHERE ejecucion_id = e.id AND orden = 1),
               (SELECT SUM(filas_afectadas) FROM silver.calidad_regla, e WHERE ejecucion_id = e.id AND tipo = 'RECHAZA_FILA'),
               (SELECT SUM(n_validas) FROM silver.medicion_5min)""").fetchone()
    assert fuente == leidas == rechazadas + validas


def test_lecturas_crudas_de_silver_igual_a_la_fuente(con):
    assert uno(con, "SELECT SUM(n_lecturas) FROM silver.medicion_5min") == uno(
        con, "SELECT filas_fuente FROM audit.etl_ejecucion WHERE estado = 'OK' ORDER BY ejecucion_id DESC LIMIT 1")


def test_gold_conserva_los_totales_de_silver(con):
    silver = con.execute("SELECT COUNT(*), SUM(e_solar_wh), SUM(e_carga_wh), SUM(e_red_wh) FROM silver.medicion_5min").fetchone()
    gold = con.execute("SELECT COUNT(*), SUM(e_solar_kwh) * 1000, SUM(e_carga_kwh) * 1000, SUM(e_red_kwh) * 1000 "
                       "FROM gold.fact_energia_5min").fetchone()
    assert silver[0] == gold[0]
    for s, g in zip(silver[1:], gold[1:]):
        assert g == pytest.approx(s, rel=1e-9)


def test_energia_integrada_concuerda_con_los_contadores_del_inversor(con):
    """Solar y carga integradas por el ETL frente a los contadores acumulados del inversor.

    Total del periodo: diferencia < 2 %. Mes a mes (telemetria casi completa): < 12 %; la
    dispersion mensual viene de la resolucion del contador (0,1 kWh) en meses de poca energia.
    """
    ultima = "(SELECT MAX(ejecucion_id) FROM audit.etl_ejecucion WHERE estado = 'OK')"
    for magnitud, dif in con.execute(f"""
            SELECT magnitud, 100 * (SUM(kwh_integrado) - SUM(kwh_contador)) / SUM(kwh_contador)
            FROM audit.conciliacion WHERE ejecucion_id = {ultima} AND magnitud IN ('solar', 'carga')
            GROUP BY 1""").fetchall():
        assert abs(dif) < 2, (magnitud, dif)
    filas = con.execute(f"""
        SELECT inversor_id, anio_mes, magnitud, diferencia_pct FROM audit.conciliacion
        WHERE ejecucion_id = {ultima} AND magnitud IN ('solar', 'carga') AND cobertura_pct >= 99
          AND dias_conciliados >= 20 AND kwh_contador >= 20""").fetchall()
    assert len(filas) >= 10
    fuera = [f for f in filas if abs(f[3]) >= 12]
    assert not fuera, fuera


# ------------------------------------------------------------------ idempotencia
def test_dos_corridas_dejan_la_misma_huella(con):
    huellas = [f[0] for f in con.execute(
        "SELECT huella_resultado FROM audit.etl_ejecucion WHERE estado = 'OK' ORDER BY ejecucion_id DESC LIMIT 2")]
    if len(huellas) < 2:
        pytest.skip("solo hay una corrida del ETL; ejecutar el ETL otra vez para comprobar la idempotencia")
    assert huellas[0] == huellas[1]


# --------------------------------------------------------------- modelo y calidad
def test_grano_y_llaves_del_hecho_de_energia(con):
    assert uno(con, "SELECT COUNT(*) FROM (SELECT 1 FROM silver.medicion_5min GROUP BY inversor_id, ts_utc HAVING COUNT(*) > 1) t") == 0
    assert uno(con, "SELECT COUNT(*) FROM gold.fact_energia_5min WHERE extract(epoch FROM ts_utc)::bigint % 300 <> 0") == 0


def test_dimensiones(con):
    assert uno(con, "SELECT COUNT(*) FROM gold.dim_tiempo") == 288
    assert uno(con, "SELECT COUNT(*) FROM gold.dim_fecha WHERE es_festivo") > 0
    # SCD2: una sola version vigente por inversor y vigencias sin traslapes
    assert uno(con, "SELECT COUNT(*) FROM (SELECT inversor_id FROM gold.dim_inversor WHERE es_actual GROUP BY 1 HAVING COUNT(*) <> 1) t") == 0
    assert uno(con, """SELECT COUNT(*) FROM gold.dim_inversor a JOIN gold.dim_inversor b
                       ON a.inversor_id = b.inversor_id AND a.inversor_key < b.inversor_key
                      AND a.valido_desde <= b.valido_hasta AND b.valido_desde <= a.valido_hasta""") == 0
    assert uno(con, "SELECT COUNT(*) FROM gold.dim_inversor WHERE inversor_id > 0") >= 4


def test_indicadores_en_rango(con):
    fila = con.execute("""SELECT MIN(disponibilidad_pct), MAX(disponibilidad_pct), MIN(datos_validos_pct),
                                 MAX(datos_validos_pct), MIN(autosuficiencia_pct), MAX(autosuficiencia_pct)
                          FROM gold.vw_kpi_diario""").fetchone()
    assert all(0 <= v <= 100.01 for v in fila)
    assert uno(con, "SELECT COUNT(*) FROM gold.fact_energia_5min WHERE soc_prom NOT BETWEEN 0 AND 100") == 0


def test_eventos_operativos_no_se_pierden_como_datos_invalidos(con):
    tipos = dict(con.execute("""SELECT t.codigo, COUNT(*) FROM gold.fact_evento e
                                JOIN gold.dim_tipo_evento t USING (tipo_evento_key) GROUP BY 1""").fetchall())
    for codigo in ("SIN_RED", "SALIDA_APAGADA", "BATERIA_BAJA", "ALARMA_ACTIVA", "FALLA_REGISTRADA", "SIN_DATOS"):
        assert tipos.get(codigo, 0) > 0, codigo
    assert uno(con, "SELECT MIN(valor_extremo) FROM silver.evento WHERE tipo_evento = 'BATERIA_BAJA'") <= 15


# -------------------------------------------------------------------- JSON y Ley 1581
def test_consulta_json_nativa(con):
    assert uno(con, """SELECT COUNT(*) FROM gold.fact_contexto
                       WHERE atributos @> '{"task_type": "CNN fitting, GPU load"}' AND atributos ? 'model'""") > 1000


def test_contexto_sin_campos_sensibles(con):
    assert uno(con, """SELECT COUNT(*) FROM gold.fact_contexto
                       WHERE atributos ?| ARRAY['command', 'directory', 'example_commands_redacted', 'metadata']""") == 0
    assert uno(con, "SELECT COUNT(*) FROM gold.fact_contexto") == uno(con, "SELECT COUNT(*) FROM silver.contexto") == 25178


def test_tarifa_cargada(con):
    assert uno(con, "SELECT gold.tarifa_vigente(DATE '2026-01-15')") > 0
