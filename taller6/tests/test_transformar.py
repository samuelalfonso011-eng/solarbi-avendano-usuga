"""Pruebas unitarias de las transformaciones puras del ETL y del simulador (sin base de datos)."""
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "etl"))
sys.path.insert(0, str(RAIZ / "simulador"))

from microrred_etl import transformar as t  # noqa: E402
import simular  # noqa: E402


def lectura(**cambios):
    """Lectura valida de referencia; `cambios` sobreescribe columnas."""
    base = dict(battvolt=53.0, battcurr=0.0, battsoc=80, linechgcurr=0.0, pv1volt=300.0, pv1power=1000,
                outvolta=230.0, outw_a=600, linevolta=230.0, linepowerw_a=0, temper1=30.0, temper2=35.0,
                temper3=40.0, temper4=120.0)
    base.update(cambios)
    return tuple(base[c] for c in t.CAMPOS)


def correr(filas, **params):
    tr = t.Transformador(t.Parametros(**params))
    for ts, inv, v in filas:
        tr.agregar(ts, inv, v)
    return tr.finalizar()


# ------------------------------------------------------------ reglas de calidad
def test_fila_vacia_se_rechaza():
    assert t.regla_que_rechaza((None,) * len(t.CAMPOS)) == "R1_FILA_VACIA"


def test_campo_critico_nulo_se_rechaza():
    assert t.regla_que_rechaza(lectura(battsoc=None)) == "R2_CAMPO_CRITICO_NULO"
    assert t.regla_que_rechaza(lectura(pv1power=float("nan"))) == "R2_CAMPO_CRITICO_NULO"


@pytest.mark.parametrize("cambio", [dict(battsoc=101), dict(battvolt=21.8), dict(linepowerw_a=-8),
                                    dict(pv1power=9000), dict(battvolt=0.0)])
def test_fuera_de_rango_se_rechaza(cambio):
    assert t.regla_que_rechaza(lectura(**cambio)) == "R3_FUERA_DE_RANGO"


def test_evento_operativo_no_es_dato_invalido():
    # Red ausente, salida apagada y bateria baja son estados reales: la lectura se conserva
    assert t.regla_que_rechaza(lectura(linevolta=0.0, outvolta=0.0, battsoc=6, pv1power=0, outw_a=0)) is None


def test_temperatura_opcional_no_rechaza():
    assert t.regla_que_rechaza(lectura(temper1=None, temper2=None)) is None


def test_lectura_cruzada_rechaza_al_inversor_que_salta():
    normal_1, normal_2 = lectura(battsoc=33, temper1=31.0), lectura(battsoc=90, temper1=44.0)
    filas = [(0.0, 1, normal_1), (0.0, 2, normal_2),
             (12.0, 1, normal_2), (12.0, 2, normal_2),      # el inversor 1 copia al 2
             (24.0, 1, normal_1), (24.0, 2, normal_2)]
    r = correr(filas)
    assert r.afectadas[("R4_LECTURA_CRUZADA", 1)] == 1
    assert r.afectadas[("R4_LECTURA_CRUZADA", 2)] == 0
    assert sum(b[t.N_VAL] for (inv, _), b in r.buckets.items() if inv == 1) == 2


def test_lectura_cruzada_sin_historia_rechaza_ambas():
    igual = lectura()
    r = correr([(0.0, 1, igual), (0.0, 2, igual)])
    assert r.afectadas[("R4_LECTURA_CRUZADA", 1)] == r.afectadas[("R4_LECTURA_CRUZADA", 2)] == 1


def test_llave_duplicada():
    r = correr([(0.0, 1, lectura()), (0.0, 1, lectura())])
    assert r.afectadas[("R5_LLAVE_DUPLICADA", 1)] == 1


def test_conteos_por_regla_cuadran_con_las_filas_leidas():
    filas = [(0.0, 1, lectura()), (10.0, 1, (None,) * len(t.CAMPOS)), (20.0, 1, lectura(battsoc=None)),
             (30.0, 1, lectura(battvolt=10.0)), (40.0, 1, lectura())]
    r = correr(filas)
    rechazadas = sum(n for (regla, _), n in r.afectadas.items() if regla.startswith("R"))
    validas = sum(b[t.N_VAL] for b in r.buckets.values())
    assert r.leidas[1] == 5 == rechazadas + validas


# ------------------------------------------------------------------ integracion
def test_energia_se_integra_con_el_valor_anterior():
    r = correr([(0.0, 1, lectura(pv1power=1200, outw_a=600)), (60.0, 1, lectura())])
    b = r.buckets[(1, 0)]
    assert b[t.SEG] == 60
    assert b[t.E_PV] == pytest.approx(1200 * 60 / 3600)      # 20 Wh
    assert b[t.E_CARGA] == pytest.approx(600 * 60 / 3600)


def test_energia_se_reparte_al_cruzar_el_intervalo():
    r = correr([(270.0, 1, lectura(pv1power=3600)), (330.0, 1, lectura())])
    assert r.buckets[(1, 0)][t.E_PV] == pytest.approx(30.0)    # 30 s a 3 600 W
    assert r.buckets[(1, 300)][t.E_PV] == pytest.approx(30.0)
    assert r.buckets[(1, 0)][t.SEG] == 30 and r.buckets[(1, 300)][t.SEG] == 30


def test_hueco_mayor_al_umbral_no_se_integra_y_genera_evento():
    r = correr([(0.0, 1, lectura()), (601.0, 1, lectura())])
    assert sum(b[t.SEG] for b in r.buckets.values()) == 0
    assert [e[1] for e in r.eventos] == ["SIN_DATOS"]


def test_una_lectura_rechazada_se_puentea_si_el_hueco_es_corto():
    r = correr([(0.0, 1, lectura()), (12.0, 1, lectura(battsoc=None)), (24.0, 1, lectura())])
    assert r.buckets[(1, 0)][t.SEG] == 24
    assert r.buckets[(1, 0)][t.N_LEC] == 3 and r.buckets[(1, 0)][t.N_VAL] == 2


def test_bateria_signos_y_banda_de_reposo():
    filas = [(0.0, 1, lectura(battvolt=50.0, battcurr=10.0)),    # descarga 500 W
             (36.0, 1, lectura(battvolt=50.0, battcurr=-20.0)),  # carga 1 000 W
             (72.0, 1, lectura(battvolt=50.0, battcurr=0.5)),    # reposo -> 0 W
             (108.0, 1, lectura())]
    b = correr(filas).buckets[(1, 0)]
    assert b[t.E_BDIS] == pytest.approx(5.0)
    assert b[t.E_BCH] == pytest.approx(10.0)


def test_temperatura_centinela_se_anula():
    r = correr([(0.0, 1, lectura(temper1=120.0, temper2=41.0, temper3=None, temper4=120.0))])
    assert r.buckets[(1, 0)][t.TEMP] == 41.0
    assert r.afectadas[("A1_TEMPERATURA_CENTINELA", 1)] == 1


def test_fila_silver_acota_y_promedia():
    r = correr([(0.0, 1, lectura(battsoc=80)), (150.0, 1, lectura(battsoc=60)), (300.0, 1, lectura())])
    fila = t.fila_silver((1, 0), r.buckets[(1, 0)])
    assert fila[4] == 300 and fila[14] == pytest.approx(70.0)   # seg_observados, soc_prom


# ---------------------------------------------------------------------- eventos
def test_episodio_de_bateria_baja():
    filas = [(0.0, 1, lectura(battsoc=40)), (60.0, 1, lectura(battsoc=14)), (120.0, 1, lectura(battsoc=9)),
             (180.0, 1, lectura(battsoc=12)), (240.0, 1, lectura(battsoc=30))]
    eventos = [e for e in correr(filas).eventos if e[1] == "BATERIA_BAJA"]
    assert eventos == [(1, "BATERIA_BAJA", 60.0, 240.0, 3, 9, None)]


def test_episodio_corto_se_descarta():
    filas = [(0.0, 1, lectura()), (12.0, 1, lectura(linevolta=0.0)), (24.0, 1, lectura())]
    r = correr(filas)
    assert not [e for e in r.eventos if e[1] == "SIN_RED"] and r.episodios_descartados == 1


def test_alarmas_y_fallas():
    p = t.Parametros()
    filas = [(0.0, 1, "[0,0,0,0]"), (100.0, 1, "[8,0,0,0]"), (150.0, 1, "[null]"), (200.0, 1, "[8,0,0,0]"),
             (300.0, 1, "[0,0,0,0]")]
    assert t.episodios_alarma(filas, p)[0][:5] == (1, "ALARMA_ACTIVA", 100.0, 300.0, 2)
    fallas = t.eventos_falla([(1, "[53,1,2]", 1000.0, 1200.0, 50), (2, "[53,1,2]", 1000.0, 1300.0, 3),
                              (2, "[null]", None, 5.0, 1), (1, "[0,0,0]", None, 5.0, 9)])
    assert len(fallas) == 1 and fallas[0][0] == 1 and fallas[0][5] == 53.0


# --------------------------------------------------------------------- contexto
def test_contexto_minimiza_campos_sensibles():
    valor = json.dumps({"source": "workstation1_log", "context_type": "cpu_compilation_workload",
                        "device": "workstation1", "inverter": 1, "command": "b2 --j 9 test",
                        "directory": ".../boost", "llm_estimated_task_effort": "low",
                        "textual_description": "x", "windows_event": {"event_count": 2, "record_id": "9"}})
    fila, motivo = t.limpiar_contexto(7, 10, 20, 30, valor)
    assert motivo is None and fila[4:9] == ("workstation1_log", "cpu_compilation_workload", "workstation1", 1, "low")
    atributos = json.loads(fila[10])
    assert "command" not in atributos and "directory" not in atributos
    assert atributos["windows_event"] == {"event_count": 2}


def test_contexto_clasifica_registros_sin_tipo_y_rechaza_invalidos():
    fila, _ = t.limpiar_contexto(1, 1, 2, 3, '{"source": "manual entry", "textual_description": "Public Holiday"}')
    assert fila[5] == "calendario_academico" and fila[6] == "instalacion" and fila[7] is None
    assert t.limpiar_contexto(1, 1, 2, 3, "{no es json")[1] == "C1_JSON_INVALIDO"
    assert t.limpiar_contexto(1, 1, 5, 3, "{}")[1] == "C3_INTERVALO_INVERTIDO"


# ----------------------------------------------------------- SCD2 y contadores
def test_versiones_de_configuracion_ignoran_copias_y_dias_sueltos():
    filas = [(1, d, 2, 2, 95, 100) for d in range(10, 15)]
    filas += [(1, 12, 0, 3, 100, 5)]                      # copia minoritaria: pierde frente a la moda
    filas += [(1, 15, 9, 9, 9, 100)]                      # un solo dia: se ignora
    filas += [(1, d, 0, 2, 100, 100) for d in range(16, 20)]
    assert t.versiones_config(filas) == [(1, 10, 15, 2, 2, 95), (1, 16, None, 0, 2, 100)]


def test_contadores():
    assert t.primer_elemento("[223.5,0.0]") == 223.5 and t.primer_elemento(None) is None
    # 852.3 es una copia del otro inversor: queda fuera por estar lejos de la mediana
    assert t.extremos_contador([223.5, 224.0, 852.3, 226.3, 225.1]) == (223.5, 226.3)


# -------------------------------------------------------------------- simulador
def test_simulador_elige_intervalo_historico():
    ahora = datetime(2026, 11, 16, 17, 7, tzinfo=timezone.utc)        # 12:07 en Bogota
    fecha_key, tiempo_key = simular.intervalo_historico(ahora, "America/Bogota", date(2026, 1, 12), 7)
    assert tiempo_key == 12 * 12 + 1
    assert 20260112 <= fecha_key <= 20260118


def test_simulador_escenarios():
    base = {"inversor_id": 2, "p_solar_w": 100.0, "p_carga_w": 700.0, "p_red_w": 600.0,
            "p_bateria_w": 0.0, "soc_pct": 60.0, "red_disponible": True}
    assert simular.aplicar_escenario(base, "normal", 2, 8)["escenario"] == "normal"
    assert simular.aplicar_escenario(base, "bateria_baja", 2, 8)["soc_pct"] == 8
    assert simular.aplicar_escenario(base, "bateria_baja", 1, 8)["soc_pct"] == 60     # otro inversor
    corte = simular.aplicar_escenario(base, "sin_red", 2, 8)
    assert corte["p_red_w"] == 0 and corte["p_bateria_w"] == 600 and corte["red_disponible"] is False
    with pytest.raises(ValueError):
        simular.aplicar_escenario(base, "desconocido", 2, 8)
