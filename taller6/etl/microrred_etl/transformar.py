"""Transformaciones puras Bronze -> Silver (sin E/S: se prueban con pytest).

Flujo de las lecturas del inversor (tabla analog_measurements):

  lectura cruda -> reglas de calidad (rechazan filas o anulan campos)
                -> integracion de energia en intervalos de 5 minutos
                -> deteccion de episodios de eventos operativos

Criterio dato invalido vs. evento operativo real
------------------------------------------------
* Dato invalido: la lectura no describe el sistema fisico (NULL por error
  Modbus, valor fuera del rango fisico, copia de la lectura del otro inversor).
  Se rechaza y se cuenta.
* Evento operativo: la lectura es coherente y describe un estado real, aunque
  sea indeseable (red ausente, salida apagada, bateria baja). Se conserva y se
  registra como episodio en el hecho de eventos.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field

BUCKET_S = 300  # frecuencia de agregacion de la capa Silver: 5 minutos

# Columnas de analog_measurements que usa el ETL, en el orden del SELECT
CAMPOS = ("battvolt", "battcurr", "battsoc", "linechgcurr", "pv1volt", "pv1power",
          "outvolta", "outw_a", "linevolta", "linepowerw_a", "temper1", "temper2",
          "temper3", "temper4")
TEMPERATURAS = ("temper1", "temper2", "temper3", "temper4")
IDX = {c: i for i, c in enumerate(CAMPOS)}
CRITICOS = ("battvolt", "battcurr", "battsoc", "pv1power", "outvolta", "outw_a",
            "linevolta", "linepowerw_a")
# Firma para detectar que la lectura de un inversor es copia de la del otro
FIRMA = ("battvolt", "battcurr", "battsoc", "pv1volt", "pv1power", "outw_a",
         "temper1", "temper2", "linevolta", "outvolta")

# Rangos fisicos admisibles (evidencia en docs/04_diccionario_datos.md)
RANGOS = {
    "battsoc": (0, 100),          # %
    "battvolt": (40.0, 60.0),     # V: banco de 48 V (ajustes del inversor: 43,2 V minimo, 57,6 V carga)
    "battcurr": (-200.0, 200.0),  # A
    "pv1power": (0, 6500),        # W: maximo observado 3 933 W
    "outw_a": (0, 7000),          # W: potencia maxima de linea configurada 6 200 W
    "linepowerw_a": (0, 7500),    # W: no hay venta a la red, no puede ser negativa
    "linevolta": (0.0, 280.0),    # V
    "outvolta": (0.0, 280.0),     # V
}
CENTINELA_TEMP = 120.0  # un canal de temperatura sin sensor reporta 120 (temper4: 100 % de las filas)

REGLAS = [  # (orden, codigo, tipo, descripcion)
    (1, "R1_FILA_VACIA", "RECHAZA_FILA",
     "Todas las variables medidas son NULL (ciclo Modbus fallido)."),
    (2, "R2_CAMPO_CRITICO_NULO", "RECHAZA_FILA",
     "Falta al menos una variable necesaria para el balance (bateria, FV, salida o red)."),
    (3, "R3_FUERA_DE_RANGO", "RECHAZA_FILA",
     "Alguna variable esta fuera de su rango fisico admisible."),
    (4, "R4_LECTURA_CRUZADA", "RECHAZA_FILA",
     "La lectura es identica a la del otro inversor en el mismo instante (copia del registrador)."),
    (5, "R5_LLAVE_DUPLICADA", "RECHAZA_FILA",
     "Llave natural (read_ts, inverter) repetida."),
    (6, "A1_TEMPERATURA_CENTINELA", "ANULA_CAMPO",
     "Temperatura igual al centinela 120 grados C: el campo se anula, la fila se conserva."),
    (7, "A2_BATERIA_EN_REPOSO", "ANULA_CAMPO",
     "Corriente de bateria en la banda de reposo (0 a +0,9 A, sesgo del sensor): se toma como 0 A."),
    (8, "E1_SIN_RED", "CLASIFICA_EVENTO",
     "Tension de red < umbral: evento operativo real (red ausente / modo isla), no se rechaza."),
    (9, "E2_SALIDA_APAGADA", "CLASIFICA_EVENTO",
     "Tension de salida < umbral: evento operativo real (inversor sin salida), no se rechaza."),
    (10, "E3_BATERIA_BAJA", "CLASIFICA_EVENTO",
     "SOC <= umbral de alarma del inversor: evento operativo real, no se rechaza."),
]


@dataclass(frozen=True)
class Parametros:
    gap_max_s: float = 600.0      # un hueco mayor no se integra (umbral data_gap del dataset)
    soc_bajo_pct: float = 15.0    # ajuste batsoclowalarm de ambos inversores
    v_ac_min: float = 100.0       # por debajo, la red o la salida se consideran ausentes
    evento_min_s: float = 60.0    # episodios mas cortos se descartan (parpadeo)
    bat_reposo_a: float = 0.9     # 0..+0,9 A es la lectura de reposo del sensor de bateria


def regla_que_rechaza(valores: tuple) -> str | None:
    """Reglas R1-R3 sobre una lectura. Devuelve el codigo de la regla o None."""
    if all(v is None for v in valores):
        return "R1_FILA_VACIA"
    for c in CRITICOS:
        v = valores[IDX[c]]
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "R2_CAMPO_CRITICO_NULO"
    for c, (lo, hi) in RANGOS.items():
        if not lo <= valores[IDX[c]] <= hi:
            return "R3_FUERA_DE_RANGO"
    return None


def firma(valores: tuple) -> tuple:
    return tuple(valores[IDX[c]] for c in FIRMA)


def _distancia(previa: tuple | None, actual: tuple) -> float | None:
    """Salto de SOC y temperatura respecto a la ultima lectura aceptada del mismo inversor."""
    if previa is None:
        return None
    d = abs(previa[IDX["battsoc"]] - actual[IDX["battsoc"]])
    t0, t1 = previa[IDX["temper1"]], actual[IDX["temper1"]]
    if t0 is not None and t1 is not None:
        d += abs(t0 - t1)
    return d


def culpables_lectura_cruzada(previas: dict, v1: tuple, v2: tuple) -> tuple[int, ...]:
    """Dadas dos lecturas identicas (inversor 1 y 2), decide cual es la copia.

    La copia es la que "salta" respecto a la ultima lectura aceptada de su propio
    inversor. Si no se puede atribuir, se rechazan las dos.
    """
    d1, d2 = _distancia(previas.get(1), v1), _distancia(previas.get(2), v2)
    if d1 is None or d2 is None:
        return (1, 2)
    if d1 > d2 + 1:
        return (1,)
    if d2 > d1 + 1:
        return (2,)
    return (1, 2)


@dataclass
class _Episodio:
    inicio: float
    ultimo: float
    n: int
    extremo: float | None


@dataclass
class Resultado:
    buckets: dict = field(default_factory=dict)        # (inv, ts_bucket) -> acumulador
    eventos: list = field(default_factory=list)        # (inv, tipo, inicio, fin, n, extremo, detalle)
    leidas: Counter = field(default_factory=Counter)   # inv -> filas crudas
    afectadas: Counter = field(default_factory=Counter)  # (regla, inv) -> filas
    episodios_descartados: int = 0


# posiciones del acumulador de un intervalo
(N_LEC, N_VAL, SEG, E_PV, E_CARGA, E_RED, E_BCH, E_BDIS, E_RBAT, P_PV, P_CARGA, P_RED,
 SOC_T, SOC_N, SOC_MIN, SOC_MAX, SOC_FIN, VB_T, TEMP, S_SINRED, S_OFF, S_BAJA) = range(22)


def _nuevo_bucket() -> list:
    return [0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, None, None, None,
            0.0, 0.0, None, None, None, 0.0, None, 0.0, 0.0, 0.0]


def _max(a, b):
    return b if a is None else (a if b is None else max(a, b))


def _min(a, b):
    return b if a is None else (a if b is None else min(a, b))


class Transformador:
    """Consume lecturas ordenadas por (read_ts, inverter) y acumula el resultado."""

    def __init__(self, p: Parametros | None = None):
        self.p = p or Parametros()
        self.r = Resultado()
        self._previa: dict[int, tuple] = {}       # inv -> (ts, valores) ultima aceptada
        self._abiertos: dict[tuple, _Episodio] = {}
        self._grupo_ts: float | None = None
        self._grupo: list = []
        self._ultima_llave: tuple | None = None

    # ------------------------------------------------------------------ entrada
    def agregar(self, ts: float, inv: int, valores: tuple) -> None:
        if self._grupo_ts is not None and ts != self._grupo_ts:
            self._cerrar_grupo()
        self._grupo_ts = ts
        self._grupo.append((ts, inv, valores))

    def finalizar(self) -> Resultado:
        self._cerrar_grupo()
        for (inv, tipo), ep in list(self._abiertos.items()):
            self._cerrar_episodio(inv, tipo, ep.ultimo)
        return self.r

    # ------------------------------------------------------------------ reglas
    def _cerrar_grupo(self) -> None:
        candidatas = []
        for ts, inv, valores in self._grupo:
            self.r.leidas[inv] += 1
            self._bucket(inv, ts)[N_LEC] += 1
            if (ts, inv) == self._ultima_llave:
                self.r.afectadas[("R5_LLAVE_DUPLICADA", inv)] += 1
                continue
            self._ultima_llave = (ts, inv)
            regla = regla_que_rechaza(valores)
            if regla:
                self.r.afectadas[(regla, inv)] += 1
            else:
                candidatas.append((ts, inv, valores))
        self._grupo = []
        if len(candidatas) == 2 and firma(candidatas[0][2]) == firma(candidatas[1][2]):
            previas = {i: pv[1] for i, pv in self._previa.items()}
            por_inv = {inv: v for _, inv, v in candidatas}
            malos = culpables_lectura_cruzada(previas, por_inv.get(1), por_inv.get(2))
            for inv in malos:
                self.r.afectadas[("R4_LECTURA_CRUZADA", inv)] += 1
            candidatas = [c for c in candidatas if c[1] not in malos]
        for ts, inv, valores in candidatas:
            self._aceptar(ts, inv, valores)

    # ------------------------------------------------------------- integracion
    def _bucket(self, inv: int, ts: float) -> list:
        llave = (inv, int(ts // BUCKET_S) * BUCKET_S)
        b = self.r.buckets.get(llave)
        if b is None:
            b = self.r.buckets[llave] = _nuevo_bucket()
        return b

    def _aceptar(self, ts: float, inv: int, v: tuple) -> None:
        p = self.p
        temps = [v[IDX[c]] for c in TEMPERATURAS if v[IDX[c]] is not None]
        if any(t == CENTINELA_TEMP for t in temps):
            self.r.afectadas[("A1_TEMPERATURA_CENTINELA", inv)] += 1
            temps = [t for t in temps if t != CENTINELA_TEMP]
        if 0 <= v[IDX["battcurr"]] <= p.bat_reposo_a:
            self.r.afectadas[("A2_BATERIA_EN_REPOSO", inv)] += 1
            v = v[:IDX["battcurr"]] + (0.0,) + v[IDX["battcurr"] + 1:]
        soc = v[IDX["battsoc"]]
        estados = {
            "SIN_RED": v[IDX["linevolta"]] < p.v_ac_min,
            "SALIDA_APAGADA": v[IDX["outvolta"]] < p.v_ac_min,
            "BATERIA_BAJA": soc <= p.soc_bajo_pct,
        }
        for regla, tipo in (("E1_SIN_RED", "SIN_RED"), ("E2_SALIDA_APAGADA", "SALIDA_APAGADA"),
                            ("E3_BATERIA_BAJA", "BATERIA_BAJA")):
            if estados[tipo]:
                self.r.afectadas[(regla, inv)] += 1

        previa = self._previa.get(inv)
        if previa is not None:
            t0, v0, est0 = previa
            if ts - t0 <= p.gap_max_s:
                self._integrar(inv, t0, ts, v0, est0)
            else:  # hueco de telemetria: no se integra y queda como evento
                self.r.eventos.append((inv, "SIN_DATOS", t0, ts, 0, round((ts - t0) / 3600, 3), None))
        self._episodios(inv, ts, estados, soc)

        b = self._bucket(inv, ts)
        b[N_VAL] += 1
        b[P_PV] = _max(b[P_PV], v[IDX["pv1power"]])
        b[P_CARGA] = _max(b[P_CARGA], v[IDX["outw_a"]])
        b[P_RED] = _max(b[P_RED], v[IDX["linepowerw_a"]])
        b[SOC_N] += soc
        b[SOC_MIN] = _min(b[SOC_MIN], soc)
        b[SOC_MAX] = _max(b[SOC_MAX], soc)
        b[SOC_FIN] = soc
        if temps:
            b[TEMP] = _max(b[TEMP], max(temps))
        self._previa[inv] = (ts, v, estados)

    def _integrar(self, inv: int, t0: float, t1: float, v: tuple, estados: dict) -> None:
        """Reparte entre los intervalos de 5 min la energia de [t0, t1) con el valor en t0."""
        p_pv, p_carga, p_red = v[IDX["pv1power"]], v[IDX["outw_a"]], v[IDX["linepowerw_a"]]
        p_bat = v[IDX["battvolt"]] * v[IDX["battcurr"]]            # + descarga, - carga
        p_rbat = v[IDX["battvolt"]] * (v[IDX["linechgcurr"]] or 0.0)  # carga de bateria desde la red
        soc, vb = v[IDX["battsoc"]], v[IDX["battvolt"]]
        t = t0
        while t < t1:
            fin = min(t1, (int(t // BUCKET_S) + 1) * BUCKET_S)
            dt = fin - t
            b = self._bucket(inv, t)
            h = dt / 3600.0
            b[SEG] += dt
            b[E_PV] += p_pv * h
            b[E_CARGA] += p_carga * h
            b[E_RED] += p_red * h
            if p_bat >= 0:
                b[E_BDIS] += p_bat * h
            else:
                b[E_BCH] += -p_bat * h
            b[E_RBAT] += max(p_rbat, 0.0) * h
            b[SOC_T] += soc * dt
            b[VB_T] += vb * dt
            if estados["SIN_RED"]:
                b[S_SINRED] += dt
            if estados["SALIDA_APAGADA"]:
                b[S_OFF] += dt
            if estados["BATERIA_BAJA"]:
                b[S_BAJA] += dt
            t = fin

    # --------------------------------------------------------------- episodios
    def _episodios(self, inv: int, ts: float, estados: dict, soc: float) -> None:
        for tipo, activo in estados.items():
            llave = (inv, tipo)
            ep = self._abiertos.get(llave)
            if ep is not None and ts - ep.ultimo > self.p.gap_max_s:
                self._cerrar_episodio(inv, tipo, ep.ultimo)
                ep = None
            if activo:
                if ep is None:
                    self._abiertos[llave] = _Episodio(ts, ts, 1, soc)
                else:
                    ep.ultimo, ep.n, ep.extremo = ts, ep.n + 1, min(ep.extremo, soc)
            elif ep is not None:
                self._cerrar_episodio(inv, tipo, ts)

    def _cerrar_episodio(self, inv: int, tipo: str, fin: float) -> None:
        ep = self._abiertos.pop((inv, tipo))
        if fin - ep.inicio < self.p.evento_min_s:
            self.r.episodios_descartados += 1
            return
        self.r.eventos.append((inv, tipo, ep.inicio, fin, ep.n, ep.extremo, None))


def fila_silver(llave: tuple, b: list) -> tuple:
    """Convierte un acumulador en la fila de silver.medicion_5min."""
    inv, ts = llave
    seg = min(b[SEG], float(BUCKET_S))
    if b[SEG] > 0:
        soc_prom, vb = b[SOC_T] / b[SEG], b[VB_T] / b[SEG]
    elif b[N_VAL] > 0:
        soc_prom, vb = b[SOC_N] / b[N_VAL], None
    else:
        soc_prom, vb = None, None
    return (inv, ts, b[N_LEC], b[N_VAL], seg, b[E_PV], b[E_CARGA], b[E_RED], b[E_BCH], b[E_BDIS],
            b[E_RBAT], b[P_PV], b[P_CARGA], b[P_RED], soc_prom, b[SOC_MIN], b[SOC_MAX], b[SOC_FIN],
            vb, b[TEMP], b[S_SINRED], b[S_OFF], b[S_BAJA])


# ----------------------------------------------------------------------------
# Episodios de alarma (tabla status, columna sysalarmflag: arreglo JSON de banderas)
# ----------------------------------------------------------------------------
def episodios_alarma(filas, p: Parametros) -> list:
    """filas: iterable (read_ts, inverter, sysalarmflag) ordenado por inverter, read_ts."""
    eventos, abierto, inv_actual = [], None, None

    def cerrar(fin):
        nonlocal abierto
        if abierto and fin - abierto["inicio"] >= p.evento_min_s:
            eventos.append((inv_actual, "ALARMA_ACTIVA", abierto["inicio"], fin, abierto["n"], None,
                            {"banderas": sorted(abierto["banderas"])[:8]}))
        abierto = None

    for ts, inv, texto in filas:
        if inv != inv_actual:
            if abierto:
                cerrar(abierto["ultimo"])
            inv_actual = inv
        try:
            banderas = json.loads(texto)
        except (TypeError, ValueError):
            continue
        if not isinstance(banderas, list) or any(x is None for x in banderas):
            continue  # lectura invalida del registro de banderas: no cambia el estado
        activo = any(banderas)
        if abierto and ts - abierto["ultimo"] > p.gap_max_s:
            cerrar(abierto["ultimo"])
        if activo:
            if abierto is None:
                abierto = {"inicio": ts, "ultimo": ts, "n": 1, "banderas": {texto}}
            else:
                abierto["ultimo"], abierto["n"] = ts, abierto["n"] + 1
                abierto["banderas"].add(texto)
        elif abierto:
            cerrar(ts)
    if abierto:
        cerrar(abierto["ultimo"])
    return eventos


def eventos_falla(filas) -> list:
    """filas: (inverter, payload_json, hora_calibrada, primera_observacion, n_observaciones).

    Cada payload distinto del registro 00 del historial de fallas es una falla nueva.
    Si el mismo payload aparece en los dos inversores (copia), se asigna al que mas lo observo.
    """
    mejor = {}
    for inv, texto, hora, visto, n in filas:
        if texto not in mejor or n > mejor[texto][4]:
            mejor[texto] = (inv, texto, hora, visto, n)
    eventos, usados = [], set()
    for inv, texto, hora, visto, n in sorted(mejor.values(), key=lambda x: (x[0], x[2] or x[3])):
        try:
            registro = json.loads(texto)
        except (TypeError, ValueError):
            continue
        if not isinstance(registro, list) or not registro or any(x is None for x in registro):
            continue
        if not any(registro):
            continue  # registro vacio del historial
        inicio = hora if hora is not None else visto
        while (inv, inicio) in usados:
            inicio += 0.001
        usados.add((inv, inicio))
        eventos.append((inv, "FALLA_REGISTRADA", inicio, inicio, n, float(registro[0]),
                        {"codigo": registro[0], "hora_calibrada": hora is not None}))
    return eventos


# ----------------------------------------------------------------------------
# Contexto JSON
# ----------------------------------------------------------------------------
# Campos que se eliminan del JSON: comandos, rutas y mensajes de sesion que describen
# la actividad de personas en las estaciones (minimizacion, Ley 1581 de 2012).
SENSIBLES = {"command", "directory", "example_commands_redacted", "command_hints_redacted",
             "metadata", "project", "privacy_note"}
SENSIBLES_ANIDADOS = {"sample_record_ids", "sample_sanitized_message", "sanitized_message", "record_id"}


def categoria_contexto(fuente: str, tipo: str) -> str:
    if fuente in ("workstation1_log", "workstation2_log", "manual_workload_entry", "wsl_bash_history"):
        return "Carga de computo"
    if fuente == "windows_event_log":
        return "Sistema operativo"
    if fuente == "manual entry":
        return "Calendario academico" if tipo == "calendario_academico" else "Anotacion manual"
    if tipo.startswith(("calendar_", "solar_")):
        return "Calendario y sol"
    if tipo in ("battery_charging", "battery_discharging", "pv_generation_active",
                "grid_unavailable_or_islanded", "high_ac_load"):
        return "Estado electrico derivado"
    return "Calidad y metadatos"


def limpiar_contexto(id_, registrado, inicio, fin, valor) -> tuple[tuple | None, str | None]:
    """Devuelve (fila, None) o (None, motivo_de_rechazo)."""
    try:
        obj = json.loads(valor)
    except (TypeError, ValueError):
        return None, "C1_JSON_INVALIDO"
    if not isinstance(obj, dict):
        return None, "C1_JSON_INVALIDO"
    if registrado is None or inicio is None or fin is None:
        return None, "C2_SIN_FECHAS"
    if fin < inicio:
        return None, "C3_INTERVALO_INVERTIDO"
    fuente = str(obj.get("source") or "desconocida")
    tipo = obj.get("context_type")
    if not tipo:  # C4: registros manuales sin tipo -> se clasifican, no se rechazan
        if fuente == "manual entry":
            tipo = "calendario_academico" if "inverter" not in obj else "anotacion_manual"
        else:
            tipo = "sin_clasificar"
    dispositivo = str(obj.get("device") or "instalacion")
    if dispositivo == "installation":
        dispositivo = "instalacion"
    inversor = obj.get("inverter")
    if dispositivo == "instalacion" or inversor not in (1, 2):
        inversor = None
    atributos = {k: v for k, v in obj.items() if k not in SENSIBLES}
    if isinstance(atributos.get("windows_event"), dict):
        atributos["windows_event"] = {k: v for k, v in atributos["windows_event"].items()
                                      if k not in SENSIBLES_ANIDADOS}
    descripcion = obj.get("textual_description") or obj.get("summary")
    return (id_, registrado, inicio, fin, fuente, str(tipo), dispositivo, inversor,
            obj.get("llm_estimated_task_effort"), descripcion,
            json.dumps(atributos, ensure_ascii=False, sort_keys=True)), None


# ----------------------------------------------------------------------------
# Configuracion del inversor -> versiones (SCD tipo 2)
# ----------------------------------------------------------------------------
def versiones_config(filas) -> list:
    """filas: (inverter, dia, prioridad_salida, prioridad_carga, soc_lleno, n).

    Para cada dia se toma la configuracion mas frecuente (moda), lo que descarta las
    lecturas copiadas del otro inversor. Una version nueva empieza cuando la moda
    cambia y se mantiene al menos 2 dias.
    Devuelve (inverter, dia_desde, dia_hasta, salida, carga, soc_lleno) con dias enteros.
    """
    por_dia: dict = {}
    for inv, dia, salida, carga, lleno, n in filas:
        actual = por_dia.get((inv, dia))
        if actual is None or n > actual[1]:
            por_dia[(inv, dia)] = ((salida, carga, lleno), n)
    versiones: list = []
    for inv in sorted({k[0] for k in por_dia}):
        dias = sorted(d for i, d in por_dia if i == inv)
        tramos: list = []
        for d in dias:
            cfg = por_dia[(inv, d)][0]
            if tramos and tramos[-1][2] == cfg:
                tramos[-1][1] = d
            else:
                tramos.append([d, d, cfg])
        estables = [t for t in tramos if t[1] - t[0] >= 1] or tramos[:1]
        fusion: list = []
        for t in estables:
            if fusion and fusion[-1][2] == t[2]:
                fusion[-1][1] = t[1]
            else:
                fusion.append(list(t))
        for i, t in enumerate(fusion):
            hasta = fusion[i + 1][0] - 1 if i + 1 < len(fusion) else None
            versiones.append((inv, t[0], hasta, *t[2]))
    return versiones


def primer_elemento(texto):
    """'[223.5,0.0]' -> 223.5 ; None o invalido -> None."""
    if not texto:
        return None
    try:
        v = json.loads(texto)
    except (TypeError, ValueError):
        return None
    if isinstance(v, list) and v and isinstance(v[0], (int, float)):
        return float(v[0])
    return None


def extremos_contador(valores: list, tolerancia: float = 60.0):
    """Primer y ultimo valor diario de un contador acumulado, sin copias del otro inversor.

    Se descartan los valores a mas de `tolerancia` kWh de la mediana del dia.
    """
    if not valores:
        return None, None
    orden = sorted(valores)
    mediana = orden[len(orden) // 2]
    buenos = [x for x in orden if abs(x - mediana) <= tolerancia]
    return buenos[0], buenos[-1]
