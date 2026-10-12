"""Capítulo de zapatas: DISEÑO por norma y DIBUJO de oficio.

Dos mitades que se usan juntas:

  design_footing(...)  -> dimensiones, armado y CADA revisión con su número
                          y su artículo (ACI 318-19; combinación de cargas
                          ACI o NTC-CADEE). No dibuja nada.
  draw_footing_*(...)  -> el corte, la planta y el cuadro, al nivel de un
                          despacho: excavación con talud, plantilla, parrilla
                          con ganchos, calzos, arranques anclados con su lb,
                          estribos de montaje, junta de colado rugosa y
                          llamadas a los dos lados (dibujo.py).

Lo que NO inventa: la capacidad del suelo (sale del estudio de mecánica de
suelos), el f'c, el desplante ni las cargas. Sin ellos ValueError, igual que
calculate_quantities sin la profundidad real.

Tipos (kind):
  'aislada'    columna al centro (concéntrica)
  'lindero'    columna en un borde (colindancia en un lado)
  'esquina'    columna en la esquina (colindancia en dos lados)
  'corrida'    bajo muro, por metro lineal
  'combinada'  dos columnas sobre una misma zapata

La geometría de la revisión es GENERAL: la columna se ubica dentro de la
zapata con sus distancias a cada borde, y el perímetro de punzonamiento se
recorta solo contra los bordes (4, 3 o 2 lados, alfa_s 40/30/20). Lindero y
esquina no son fórmulas aparte: son la misma revisión con la columna en
otro lugar.

Unidades de entrada: t, t·m, m, kg/cm². Internamente todo va en N y mm
(las fórmulas de ACI 318-19 están en MPa); la salida vuelve a t, m, cm.
"""
from __future__ import annotations

import math
from typing import Any, Optional

T_A_KN = 9.80665
KGCM2_A_MPA = 0.0980665

# Varilla corrugada (NMX-B-506): número -> (diámetro m, área cm², kg/m).
VARILLAS: dict[str, tuple[float, float, float]] = {
    "#2": (0.0064, 0.32, 0.248),
    "#2.5": (0.0079, 0.49, 0.384),
    "#3": (0.0095, 0.71, 0.560),
    "#4": (0.0127, 1.27, 0.994),
    "#5": (0.0159, 1.99, 1.552),
    "#6": (0.0191, 2.87, 2.235),
    "#8": (0.0254, 5.07, 3.973),
    "#10": (0.0318, 7.94, 6.225),
}
FRACCION = {"#2": '1/4"', "#2.5": '5/16"', "#3": '3/8"', "#4": '1/2"', "#5": '5/8"',
            "#6": '3/4"', "#8": '1"', "#10": '1 1/4"'}

KINDS = ("aislada", "lindero", "esquina", "corrida", "combinada")

PHI_FLEXION = 0.90     # ACI 318-19 tabla 21.2.1(a), sección controlada por tensión
PHI_CORTANTE = 0.75    # tabla 21.2.1(b)
PHI_APLAST = 0.65      # tabla 21.2.1(d)

COMBOS = {"ACI": (1.2, 1.6, "ACI 318-19 5.3.1(b): 1.2D + 1.6L"),
          "NTC": (1.3, 1.5, "NTC-CADEE 2023 3.4: 1.3 CM + 1.5 CV")}


def _r(v: float, n: int = 2) -> float:
    return round(float(v), n)


def _arriba(v: float, paso: float = 0.05) -> float:
    return math.ceil(round(v / paso, 6)) * paso


def _abajo(v: float, paso: float = 0.025) -> float:
    return math.floor(round(v / paso, 6)) * paso


def _centrado(lado_min: float, c: float, paso: float = 0.05) -> float:
    """El lado más chico >= lado_min con los dos volados en múltiplos de
    'paso': con la columna centrada, (lado - c)/2 en cm redondos. Si no, la
    cadena de cotas suma distinto que la total (1.08+0.35+1.08 = 2.51 en
    una zapata de 2.50) y el plano se contradice."""
    vuelo = math.ceil(round((lado_min - c) / 2.0 / paso, 6)) * paso
    return round(c + 2.0 * vuelo, 4)


def varilla(nombre: str) -> tuple[float, float, float]:
    n = nombre if nombre.startswith("#") else f"#{nombre}"
    if n not in VARILLAS:
        raise ValueError(f"Varilla {nombre!r}: tiene que ser una de {list(VARILLAS)}.")
    return VARILLAS[n]


def texto_varilla(nombre: str) -> str:
    return f"{nombre} ({FRACCION.get(nombre, '')})"


# ------------------------------------------------------------ fórmulas ACI

def lambda_s(d_m: float) -> float:
    """Factor de tamaño, ACI 318-19 ec. 22.5.5.1.3: sqrt(2/(1+d/254)) <= 1."""
    return min(1.0, math.sqrt(2.0 / (1.0 + d_m * 1000.0 / 254.0)))


def ld_tension(db: float, fc_mpa: float, fy_mpa: float) -> float:
    """Longitud de desarrollo recta en tensión, ACI 318-19 tabla 25.4.2.3
    (separación y recubrimiento no menores a db, psi_t=psi_e=psi_g=1)."""
    k = 2.1 if db <= 0.0191 + 1e-6 else 1.7
    return max(0.30, fy_mpa / (k * math.sqrt(fc_mpa)) * db)


def ldh_tension(db: float, fc_mpa: float, fy_mpa: float) -> float:
    """Desarrollo con gancho estándar, ACI 318-19 ec. 25.4.3.1a, sin
    confinamiento (psi_r=1.6) y psi_o=1.25 (gancho no dentro del núcleo de
    una columna): conservador para el borde de una zapata."""
    psi_c = min(1.0, fc_mpa / 105.0 + 0.6)
    db_mm = db * 1000.0
    ldh = fy_mpa * 1.0 * 1.6 * 1.25 * psi_c / (23.0 * math.sqrt(fc_mpa)) * db_mm ** 1.5
    return max(ldh / 1000.0, 8.0 * db, 0.15)


def ldc_compresion(db: float, fc_mpa: float, fy_mpa: float) -> float:
    """Desarrollo en compresión, ACI 318-19 25.4.9.2 (psi_r=1):
    max(0.24 fy/sqrt(f'c), 0.043 fy)·db, mínimo 200 mm. El gancho NO cuenta
    en compresión (25.4.1.2): el arranque se desarrolla en la parte recta."""
    return max(0.24 * fy_mpa / math.sqrt(fc_mpa) * db, 0.043 * fy_mpa * db, 0.20)


def traslape_compresion(db: float, fy_mpa: float) -> float:
    """Traslape en compresión, ACI 318-19 25.5.5.1: 0.071·fy·db (fy<=420),
    mínimo 300 mm."""
    k = 0.071 if fy_mpa <= 420 else (0.13 * fy_mpa - 24) / fy_mpa
    return max(k * fy_mpa * db, 0.30)


def as_minimo(b: float, h: float, fy_mpa: float) -> float:
    """Acero mínimo de zapata (losa), ACI 318-19 13.3.3 -> 7.6.1.1 /
    24.4.3.2: 0.0018·Ag con fy=420 MPa. En cm²."""
    rho = 0.0018 if fy_mpa <= 420 else max(0.0014, 0.0018 * 420.0 / fy_mpa)
    return rho * b * h * 1e4


def as_flexion(mu_knm: float, b: float, d: float, fc_mpa: float, fy_mpa: float) -> float:
    """Área de acero (cm²) para Mu con bloque rectangular (ACI 22.2)."""
    if mu_knm <= 0:
        return 0.0
    mu = mu_knm * 1e6                       # N·mm
    b_mm, d_mm = b * 1000.0, d * 1000.0
    rn = mu / (PHI_FLEXION * b_mm * d_mm ** 2)
    disc = 1.0 - 2.0 * rn / (0.85 * fc_mpa)
    if disc <= 0:
        return float("inf")
    rho = 0.85 * fc_mpa / fy_mpa * (1.0 - math.sqrt(disc))
    return rho * b_mm * d_mm / 100.0


def vc_un_sentido(fc_mpa: float, b: float, d: float, rho_w: float) -> float:
    """Cortante en una dirección SIN estribos (Av < Av,min), ACI 318-19
    tabla 22.5.5.1(c): 0.66·lambda_s·rho_w^(1/3)·sqrt(f'c)·b·d, con el tope
    0.42·sqrt(f'c)·b·d de 22.5.5.1.1. Devuelve kN."""
    v = 0.66 * lambda_s(d) * max(rho_w, 1e-6) ** (1.0 / 3.0) * math.sqrt(fc_mpa)
    v = min(v, 0.42 * math.sqrt(fc_mpa))
    return v * b * 1000.0 * d * 1000.0 / 1000.0


def vc_punzonamiento(fc_mpa: float, c1: float, c2: float, bo: float, d: float,
                     alfa_s: float) -> tuple[float, str]:
    """Esfuerzo resistente a cortante en dos direcciones, ACI 318-19 tabla
    22.6.5.2: el menor de (a) 0.33, (b) 0.17(1+2/beta), (c) 0.083(2+alfa_s
    d/bo), todos por lambda_s·sqrt(f'c). MPa."""
    beta = max(c1, c2) / max(min(c1, c2), 1e-6)
    ls = lambda_s(d)
    raiz = math.sqrt(fc_mpa)
    cands = {"(a) 0.33λs√f'c": 0.33 * ls * raiz,
             "(b) 0.17(1+2/β)λs√f'c": 0.17 * (1 + 2 / beta) * ls * raiz,
             "(c) 0.083(2+αs·d/bo)λs√f'c": 0.083 * (2 + alfa_s * d / bo) * ls * raiz}
    clave = min(cands, key=cands.get)
    return cands[clave], clave


# ------------------------------------------------------------ armado

def elegir_armado(as_req_cm2: float, ancho: float, h: float,
                  preferidas: tuple[str, ...] = ("#4", "#5", "#6", "#8"),
                  s_min: float = 0.10) -> dict[str, Any]:
    """Varilla y separación para cubrir as_req en 'ancho', respetando la
    separación máxima min(3h, 45 cm) (ACI 318-19 7.7.2.3 / 24.4.3.3) y una
    mínima de obra (s_min) para que el concreto pase. Separación redondeada
    HACIA ABAJO a 2.5 cm: la cuantía real nunca queda por debajo."""
    s_max = min(3.0 * h, 0.45)
    # Primero se busca una separación cómoda de obra (>= 15 cm) subiendo de
    # número; solo si ninguna varilla la da se acepta bajar hasta s_min.
    intentos = [(nombre, 0.15) for nombre in preferidas] + \
               [(nombre, s_min) for nombre in preferidas]
    for nombre, s_lim in intentos:
        db, a, _kg = VARILLAS[nombre]
        n = max(2, math.ceil(as_req_cm2 / a - 1e-9))
        s = _abajo((ancho - 2 * 0.075 - db) / max(n - 1, 1), 0.05)
        s = min(s, _abajo(s_max, 0.05))
        if s >= s_lim - 1e-9:
            n_real = int(math.floor((ancho - 2 * 0.075 - db) / s + 1e-9)) + 1
            return {"bar": nombre, "db": db, "spacing": _r(s, 3), "count": n_real,
                    "As_cm2": _r(n_real * a, 2), "As_req_cm2": _r(as_req_cm2, 2),
                    "s_max": _r(s_max, 3),
                    "text": f"{nombre} @ {s * 100:.0f} cm"}
    raise ValueError(
        f"No hay varilla de {preferidas} que cubra {as_req_cm2:.1f} cm² en "
        f"{ancho:.2f} m con separación >= {s_min * 100:.0f} cm: subí el peralte.")


# ------------------------------------------------------------ diseño

def _geometria_columna(kind: str, B: float, L: float, c1: float, c2: float):
    """Distancias de las caras de la columna a los bordes [izq, der, abajo,
    arriba] según el tipo. Lindero: la colindancia es el borde IZQUIERDO
    (x=0). Esquina: izquierdo y de abajo."""
    if kind == "aislada":
        return [(B - c1) / 2, (B - c1) / 2, (L - c2) / 2, (L - c2) / 2]
    if kind == "lindero":
        return [0.0, B - c1, (L - c2) / 2, (L - c2) / 2]
    if kind == "esquina":
        return [0.0, B - c1, 0.0, L - c2]
    raise ValueError(kind)


def _punzonamiento(B, L, c1, c2, vol, d, qu_kpa, pu_kn, fc_mpa):
    """Perímetro crítico a d/2 de las caras, recortado contra los bordes:
    un lado cuya cara está a menos de d/2 del borde no existe."""
    izq, der, aba, arr = vol
    x0 = -min(izq, d / 2)
    x1 = c1 + min(der, d / 2)
    y0 = -min(aba, d / 2)
    y1 = c2 + min(arr, d / 2)
    lados = 0
    bo = 0.0
    if izq >= d / 2 - 1e-9:
        bo += y1 - y0
        lados += 1
    if der >= d / 2 - 1e-9:
        bo += y1 - y0
        lados += 1
    if aba >= d / 2 - 1e-9:
        bo += x1 - x0
        lados += 1
    if arr >= d / 2 - 1e-9:
        bo += x1 - x0
        lados += 1
    alfa = {4: 40.0, 3: 30.0, 2: 20.0}.get(lados, 20.0)
    area_dentro = (x1 - x0) * (y1 - y0)
    vu = max(pu_kn - qu_kpa * area_dentro, 0.0)
    vc, ec = vc_punzonamiento(fc_mpa, c1, c2, bo, d, alfa)
    phi_vn = PHI_CORTANTE * vc * bo * 1000 * d * 1000 / 1000.0
    return {"bo_m": _r(bo, 3), "sides": lados, "alpha_s": alfa,
            "Vu_t": _r(vu / T_A_KN, 2), "phiVc_t": _r(phi_vn / T_A_KN, 2),
            "vc_MPa": _r(vc, 3), "governs": ec,
            "ok": vu <= phi_vn + 1e-6,
            "ref": "ACI 318-19 22.6.4.1 (sección a d/2), 22.6.5.2, 13.2.7.2"}


def design_footing(kind: str,
                   dead_load: float,
                   live_load: float,
                   allowable_bearing: float,
                   fc: float,
                   depth: float,
                   column: Optional[list[float]] = None,
                   wall_thickness: float = 0.0,
                   wall_material: str = "mamposteria",
                   soil_unit_weight: Optional[float] = None,
                   bearing_is_net: bool = False,
                   fy: float = 4200.0,
                   code: str = "ACI",
                   cover: float = 0.075,
                   lean_concrete: float = 0.05,
                   min_thickness: float = 0.25,
                   width: Optional[float] = None,
                   length: Optional[float] = None,
                   moment_x: float = 0.0,
                   moment_y: float = 0.0,
                   tie_beam: bool = True,
                   pedestal: Optional[list[float]] = None,
                   pedestal_height: float = 0.0,
                   column_bar: str = "#6",
                   column_bar_count: int = 4,
                   bars: tuple[str, ...] = ("#4", "#5", "#6", "#8"),
                   columns: Optional[list[dict[str, Any]]] = None,
                   spacing: float = 0.0,
                   boundary_left: bool = False,
                   overhang_left: Optional[float] = None,
                   aspect: Optional[float] = None,
                   grade_beam_height: float = 0.0,
                   mark: str = "Z-1") -> dict[str, Any]:
    """Diseña una zapata y devuelve TODO lo que el plano tiene que decir.

    kind: 'aislada', 'lindero', 'esquina', 'corrida' o 'combinada'.
    dead_load / live_load: carga muerta y viva de SERVICIO, t (corrida: t/m).
      En 'combinada' van por columna en 'columns' y estos se ignoran (0).
    allowable_bearing: capacidad de carga ADMISIBLE del terreno, t/m², del
      estudio de mecánica de suelos. Bruta salvo bearing_is_net=True.
    fc: f'c del concreto de la zapata, kg/cm². fy: kg/cm² (4200 = grado 42).
    depth: desplante, del nivel de terreno natural al FONDO de la zapata, m.
    column: [c1, c2] de la columna (c1 en X = el sentido del corte), m.
    wall_thickness / wall_material ('concreto' o 'mamposteria'): corrida.
    grade_beam_height: corrida bajo muro de mampostería, peralte de la dala
      de desplante (ancho = el del muro); su armado sale de la NTC de
      mampostería (As >= 0.2 f'c t²/fy, 3 barras mínimo; estribos a
      s <= min(1.5t, 20 cm)).
    soil_unit_weight: t/m³ del relleno sobre la zapata (del E.M.S.);
      obligatorio si la capacidad es bruta.
    code: combinación de cargas, 'ACI' (1.2D+1.6L) o 'NTC' (1.3CM+1.5CV).
    cover: recubrimiento inferior; 7.5 cm para concreto colado contra el
      suelo (ACI 318-19 tabla 20.5.1.3.1).
    width/length: fijar B (X) y/o L (Y) cuando el predio lo limita.
    moment_x/moment_y: momentos de servicio, t·m (alrededor de Y / de X).
    tie_beam: lindero/esquina con contratrabe de liga que toma la
      excentricidad (presión uniforme). False = presión trapecial.
    pedestal: [a1, a2] del dado; el punzonamiento y el aplastamiento se
      revisan en la cara del dado. pedestal_height: su altura, m (va con
      pedestal). Los estribos del dado salen de ACI 318-19 25.7.2.1.
    column_bar / column_bar_count: el armado de la columna; los arranques
      son del mismo número y cantidad (ACI 318-19 16.3.4.1: >= 0.005·Ag).
    columns (combinada): [{"dead":..,"live":..,"size":[c1,c2]}, {...}],
      spacing = distancia entre ejes, m. boundary_left: la columna 1 está
      en colindancia; si no, overhang_left = volado desde su eje.

    Devuelve geometría, armado, arranques, cada revisión con 'ok', su
    número y su referencia, 'specs' (textos listos para el plano) y
    'warnings'. 'ok' global = todas las revisiones cumplen.
    """
    if kind not in KINDS:
        raise ValueError(f"kind tiene que ser uno de {KINDS}.")
    if allowable_bearing is None or allowable_bearing <= 0:
        raise ValueError(
            "allowable_bearing (t/m²) sale del estudio de mecánica de suelos: "
            "no se supone.")
    if not fc or fc <= 0:
        raise ValueError("fc (kg/cm²) es un dato del proyecto: no se supone.")
    if depth is None or depth <= 0:
        raise ValueError("depth (desplante, m) es un dato del proyecto: no se supone.")
    if not bearing_is_net and soil_unit_weight is None:
        raise ValueError(
            "Con capacidad BRUTA hace falta soil_unit_weight (t/m³, del "
            "E.M.S.) para descontar el relleno sobre la zapata; o pasá "
            "bearing_is_net=True si el estudio da la capacidad neta.")
    if code not in COMBOS:
        raise ValueError(f"code tiene que ser uno de {list(COMBOS)}.")
    fc_mpa, fy_mpa = fc * KGCM2_A_MPA, fy * KGCM2_A_MPA
    fd, fl, combo = COMBOS[code]
    avisos: list[str] = []
    if fc < 200:
        avisos.append(f"f'c={fc:g} kg/cm²: menor que el mínimo usual para concreto "
                      "estructural (ACI 318-19 19.2.1.1: 17 MPa ≈ 175 kg/cm²; NTC "
                      "clase 1 pide 250).")
    if cover < 0.075 - 1e-9:
        avisos.append(f"Recubrimiento {cover * 100:.1f} cm: ACI 318-19 tabla "
                      "20.5.1.3.1 pide 7.5 cm para concreto colado contra el suelo.")

    if kind == "corrida":
        return _corrida(dead_load, live_load, allowable_bearing, fc, fc_mpa, fy, fy_mpa,
                        depth, wall_thickness, wall_material, soil_unit_weight,
                        bearing_is_net, fd, fl, combo, cover, lean_concrete,
                        min_thickness, width, bars, avisos, mark, grade_beam_height)
    if kind == "combinada":
        return _combinada(columns, spacing, allowable_bearing, fc, fc_mpa, fy, fy_mpa,
                          depth, soil_unit_weight, bearing_is_net, fd, fl, combo,
                          cover, lean_concrete, min_thickness, width, boundary_left,
                          overhang_left, bars, column_bar, column_bar_count, avisos, mark)

    if not column or len(column) != 2 or min(column) <= 0:
        raise ValueError("column=[c1, c2] (m) es obligatorio para una zapata bajo columna.")
    c1, c2 = float(column[0]), float(column[1])
    a1, a2 = (float(pedestal[0]), float(pedestal[1])) if pedestal else (c1, c2)
    if pedestal and (a1 < c1 or a2 < c2):
        raise ValueError("El dado no puede ser más chico que la columna.")
    if bool(pedestal) != (pedestal_height > 0):
        raise ValueError("pedestal y pedestal_height van los dos o ninguno.")
    P = dead_load + live_load
    Pu = fd * dead_load + fl * live_load
    gamma_c = 2.4

    # ---- 1. área por capacidad de carga (servicio)
    h = max(min_thickness, 0.15 + cover + 0.02)
    def q_efectiva(hh):
        if bearing_is_net:
            return allowable_bearing
        return allowable_bearing - gamma_c * hh - soil_unit_weight * max(depth - hh, 0.0) \
            - (gamma_c - soil_unit_weight) * a1 * a2 * pedestal_height / max(A_ref[0], 1e-6)

    def presiones(B_, L_):
        A = B_ * L_
        ex = moment_x / P if P else 0.0
        ey = moment_y / P if P else 0.0
        if kind in ("lindero", "esquina") and not tie_beam:
            ex += (B_ - a1) / 2.0
            if kind == "esquina":
                ey += (L_ - a2) / 2.0
        qmax = P / A * (1 + 6 * abs(ex) / B_ + 6 * abs(ey) / L_)
        qmin = P / A * (1 - 6 * abs(ex) / B_ - 6 * abs(ey) / L_)
        if qmin < 0 and (abs(ex) > 1e-9) != (abs(ey) > 1e-9):
            e = abs(ex) if abs(ex) > 1e-9 else abs(ey)
            lado = B_ if abs(ex) > 1e-9 else L_
            otro = L_ if abs(ex) > 1e-9 else B_
            qmax = 2 * P / (3 * otro * (lado / 2 - e)) if lado / 2 > e else float("inf")
        return qmax, qmin, ex, ey

    A_ref = [max(a1, a2) ** 2 * 4]
    B = width or 0.0
    L = length or 0.0
    asp = aspect if aspect else (1.5 if kind == "lindero" else 1.0)
    for _ in range(60):
        A_ref[0] = max(B * L, A_ref[0])
        qe = q_efectiva(h)
        if qe <= 0:
            raise ValueError(f"El peso del relleno y la zapata ({allowable_bearing - qe:.1f} t/m²) "
                             "se come la capacidad admisible: revisá el desplante o la capacidad.")
        A_req = P / qe
        if width and length:
            B, L = width, length
        elif width:
            B, L = width, max(_arriba(A_req / width), a2)
        elif length:
            B, L = max(_arriba(A_req / length), a1), length
        elif kind == "lindero":
            # Rectangular, lo largo PARALELO a la colindancia: achica el
            # volado excéntrico (y el momento de la contratrabe).
            B = max(_arriba(math.sqrt(A_req / asp)), a1 + 0.30)
            L = _centrado(max(A_req / B, a2 + 0.30), a2)
        elif kind == "esquina":
            B = L = max(_arriba(math.sqrt(A_req)), max(a1, a2) + 0.30)
        else:
            B = _centrado(max(math.sqrt(A_req), a1 + 0.30), a1)
            L = _centrado(max(A_req / B, a2 + 0.30), a2)
        qmax, qmin, ex, ey = presiones(B, L)
        if qmax <= qe + 1e-6 or (width and length):
            break
        if width and not length:
            L += 0.05
        elif length and not width:
            B += 0.05
        elif kind == "lindero":
            A_req *= 1.05
            B = _arriba(math.sqrt(A_req / asp))
            L = _centrado(A_req / B, a2)
        elif kind == "esquina":
            B = L = B + 0.05
        else:
            B = _centrado(B + 0.05, a1)
            L = _centrado(L + 0.05, a2)
    qmax, qmin, ex, ey = presiones(B, L)
    qe = q_efectiva(h)
    rev: dict[str, dict[str, Any]] = {}
    rev["capacidad"] = {
        "q_max_t_m2": _r(qmax), "q_min_t_m2": _r(qmin), "q_adm_efectiva_t_m2": _r(qe),
        "ok": qmax <= qe + 1e-6,
        "ref": "Presión de servicio vs. capacidad admisible del E.M.S. "
               "(NTC-Cimentaciones 2023 / ACI 318-19 13.3.1.1)"
               + ("" if bearing_is_net else "; capacidad bruta menos zapata y relleno")}
    if qmin < 0:
        avisos.append("La presión mínima sale negativa (tensión en el suelo): la resultante "
                      "cae fuera del núcleo central.")

    # ---- 2. presión factorizada para el diseño estructural (sin peso propio)
    qu = Pu * T_A_KN / (B * L)                         # kPa
    if moment_x or moment_y or (kind != "aislada" and not tie_beam):
        qu_max = qu * qmax / (P / (B * L))             # misma distribución que en servicio
        avisos.append("Con excentricidad se diseña con la presión factorizada MÁXIMA "
                      "uniforme (conservador).")
        qu = qu_max
    vol = _geometria_columna(kind, B, L, a1, a2)

    # ---- 3. peralte y armado: se sube h hasta que todo cumpla
    db_col = VARILLAS[column_bar][0]
    ldc = ldc_compresion(db_col, fc_mpa, fy_mpa)
    for _ in range(80):
        db_guess = 0.0159
        d = h - cover - db_guess                       # al centro de los dos lechos
        dx = h - cover - db_guess / 2                  # lecho inferior (X)
        dy = h - cover - 1.5 * db_guess                # lecho superior (Y)
        pun = _punzonamiento(B, L, a1, a2, vol, d, qu, Pu * T_A_KN, fc_mpa)
        vol_x = max(vol[0], vol[1])
        vol_y = max(vol[2], vol[3])
        mu_x = qu * L * vol_x ** 2 / 2.0               # kN·m, barras en X
        mu_y = qu * B * vol_y ** 2 / 2.0
        as_x = max(as_flexion(mu_x, L, dx, fc_mpa, fy_mpa), as_minimo(L, h, fy_mpa))
        as_y = max(as_flexion(mu_y, B, dy, fc_mpa, fy_mpa), as_minimo(B, h, fy_mpa))
        disponible_arranque = h - cover - 2 * db_guess - db_col
        ok_arranque = disponible_arranque >= ldc - 1e-6
        if pun["ok"] and ok_arranque and math.isfinite(as_x) and math.isfinite(as_y):
            try:
                arm_x = elegir_armado(as_x, L, h, bars)
                arm_y = elegir_armado(as_y, B, h, bars)
            except ValueError:
                h = _r(h + 0.05)
                continue
            vx = qu * L * max(vol_x - dx, 0.0)
            vy = qu * B * max(vol_y - dy, 0.0)
            vcx = PHI_CORTANTE * vc_un_sentido(fc_mpa, L, dx, arm_x["As_cm2"] / (L * dx * 1e4))
            vcy = PHI_CORTANTE * vc_un_sentido(fc_mpa, B, dy, arm_y["As_cm2"] / (B * dy * 1e4))
            if vx <= vcx and vy <= vcy:
                break
        h = _r(h + 0.05)
    else:
        raise ValueError("No cierra ni con 4 m de peralte: revisá cargas y capacidad.")

    # Banda central en zapata rectangular (ACI 318-19 13.3.3.3).
    banda = None
    if abs(B - L) > 1e-6 and kind == "aislada":
        largo, corto = max(B, L), min(B, L)
        beta = largo / corto
        gamma_s = 2.0 / (beta + 1.0)
        arm_corto = arm_y if L < B else arm_x
        banda = {"beta": _r(beta, 3), "gamma_s": _r(gamma_s, 3),
                 "band_width_m": _r(corto, 2),
                 "As_band_cm2": _r(arm_corto["As_req_cm2"] * gamma_s, 2),
                 "ref": "ACI 318-19 13.3.3.3: en la dirección corta, gamma_s·As en "
                        "una banda centrada de ancho igual al lado corto"}
        avisos.append(f"Zapata rectangular: {gamma_s * 100:.0f}% del acero corto va en la "
                      f"banda central de {corto:.2f} m (13.3.3.3).")

    # ---- 4. revisiones finales con el armado elegido
    rev["punzonamiento"] = pun
    rev["cortante_x"] = {"Vu_t": _r(vx / T_A_KN), "phiVc_t": _r(vcx / T_A_KN),
                         "section_m_from_face": _r(dx, 3), "ok": vx <= vcx + 1e-6,
                         "ref": "ACI 318-19 13.2.7.2 (a d de la cara), 22.5.5.1(c)"}
    rev["cortante_y"] = {"Vu_t": _r(vy / T_A_KN), "phiVc_t": _r(vcy / T_A_KN),
                         "section_m_from_face": _r(dy, 3), "ok": vy <= vcy + 1e-6,
                         "ref": "ACI 318-19 13.2.7.2, 22.5.5.1(c)"}
    rev["flexion_x"] = {"Mu_tm": _r(mu_x / T_A_KN), "As_req_cm2": _r(as_x), "As_cm2": arm_x["As_cm2"],
                        "ok": arm_x["As_cm2"] >= as_x - 1e-6,
                        "ref": "ACI 318-19 13.2.7.1 (cara de la columna), 22.2; As,min 7.6.1.1"}
    rev["flexion_y"] = {"Mu_tm": _r(mu_y / T_A_KN), "As_req_cm2": _r(as_y), "As_cm2": arm_y["As_cm2"],
                        "ok": arm_y["As_cm2"] >= as_y - 1e-6,
                        "ref": "ACI 318-19 13.2.7.1, 22.2; As,min 7.6.1.1"}

    # Desarrollo de la parrilla: del paño de la columna al extremo de la barra.
    for eje, arm, vole in (("x", arm_x, vol_x), ("y", arm_y, vol_y)):
        disp = vole - cover
        ld = ld_tension(arm["db"], fc_mpa, fy_mpa)
        ldh = ldh_tension(arm["db"], fc_mpa, fy_mpa)
        rev[f"desarrollo_{eje}"] = {
            "available_m": _r(disp, 3), "ld_recta_m": _r(ld, 3), "ldh_gancho_m": _r(ldh, 3),
            "hook_needed": disp < ld, "ok": disp >= min(ld, ldh) - 1e-6,
            "ref": "ACI 318-19 13.2.8.3, 25.4.2.3 (recta), 25.4.3.1 (gancho)"}
        arm["hook_needed"] = disp < ld

    # Aplastamiento columna-zapata (22.8.3.2): A2 concéntrica dentro de la zapata.
    m = min(vol)
    A1 = a1 * a2
    A2 = (a1 + 2 * m) * (a2 + 2 * m)
    raiz = min(math.sqrt(A2 / A1), 2.0)
    phi_bn = PHI_APLAST * 0.85 * fc_mpa * A1 * 1e6 * raiz / 1000.0     # kN
    rev["aplastamiento"] = {"Pu_t": _r(Pu), "phiBn_t": _r(phi_bn / T_A_KN), "sqrt_A2_A1": _r(raiz, 3),
                            "ok": Pu * T_A_KN <= phi_bn + 1e-6,
                            "ref": "ACI 318-19 22.8.3.2 (A2 concéntrica dentro de la zapata)"}

    # Arranques (16.3.4.1) y su desarrollo en compresión dentro de la zapata.
    as_col = column_bar_count * VARILLAS[column_bar][1]
    as_min_arr = 0.005 * c1 * c2 * 1e4
    n_arr = max(4, column_bar_count, math.ceil(as_min_arr / VARILLAS[column_bar][1]))
    disponible = h - cover - 2 * max(arm_x["db"], arm_y["db"]) - db_col
    lap = traslape_compresion(db_col, fy_mpa)
    pata = max(12 * db_col, 0.15)
    rev["arranques"] = {
        "count": n_arr, "bar": column_bar, "As_cm2": _r(n_arr * VARILLAS[column_bar][1]),
        "As_min_cm2": _r(as_min_arr), "ldc_m": _r(ldc, 3), "available_m": _r(disponible, 3),
        "ok": disponible >= ldc - 1e-6 and n_arr * VARILLAS[column_bar][1] >= as_min_arr - 1e-6,
        "ref": "ACI 318-19 16.3.4.1 (>=0.005Ag, 4 barras), 25.4.9.2 (ldc), "
               "25.4.1.2 (el gancho no cuenta en compresión)"}
    rev["peralte_minimo"] = {"d_m": _r(d, 3), "min_m": 0.15, "ok": d >= 0.15 - 1e-9,
                             "ref": "ACI 318-19 13.3.1.2: d >= 150 mm"}
    if as_col > n_arr * VARILLAS[column_bar][1] + 1e-6:
        avisos.append("Los arranques tienen menos acero que la columna.")

    if kind in ("lindero", "esquina") and tie_beam:
        e_x = (B - a1) / 2.0
        liga = {"x": {"M_servicio_tm": _r(P * e_x), "Mu_tm": _r(Pu * e_x)}}
        if kind == "esquina":
            e_y = (L - a2) / 2.0
            liga["y"] = {"M_servicio_tm": _r(P * e_y), "Mu_tm": _r(Pu * e_y)}
        rev["contratrabe_liga"] = {
            "moments": liga, "ok": True,
            "ref": "La excentricidad columna-zapata la toma una contratrabe de liga "
                   "a la columna interior; la zapata se revisa con presión uniforme"}
        avisos.append("Lindero/esquina con contratrabe de liga: DISEÑAR la contratrabe "
                      f"para Mu = {Pu * e_x:.2f} t·m" +
                      (f" (X) y {Pu * (L - a2) / 2:.2f} t·m (Y)" if kind == "esquina" else "") +
                      "; la zapata sola no toma ese momento.")

    estribo_dado = None
    if pedestal:
        if pedestal_height + h > depth + 1e-6:
            avisos.append("El dado sobresale del terreno natural: revisá el desplante.")
        db_e = VARILLAS["#3"][0]
        s_dado = _abajo(min(16 * db_col, 48 * db_e, min(a1, a2)), 0.05)
        estribo_dado = {"bar": "#3", "spacing": _r(s_dado, 3),
                        "ref": "ACI 318-19 25.7.2.1: s <= 16db, 48de, lado menor"}
        rev["aplastamiento_dado"] = {
            "Pu_t": _r(Pu),
            "phiBn_t": _r(PHI_APLAST * 0.85 * fc_mpa * c1 * c2 * 1e6 *
                          min(math.sqrt((a1 * a2) / (c1 * c2)), 2.0) / 1000.0 / T_A_KN),
            "ok": Pu * T_A_KN <= PHI_APLAST * 0.85 * fc_mpa * c1 * c2 * 1e6 *
            min(math.sqrt((a1 * a2) / (c1 * c2)), 2.0) / 1000.0 + 1e-6,
            "ref": "ACI 318-19 22.8.3.2 (columna sobre el dado)"}
    ok = all(v.get("ok", True) for v in rev.values())
    h_ped = pedestal_height
    out = {
        "ok": ok, "kind": kind, "mark": mark,
        "B": _r(B), "L": _r(L), "h": _r(h), "d": _r(d, 3),
        "column": [c1, c2], "pedestal": [a1, a2] if pedestal else None,
        "pedestal_height": h_ped,
        "column_offsets": [_r(v, 3) for v in vol],
        "depth": depth, "cover": cover, "lean_concrete": lean_concrete,
        "fc": fc, "fy": fy, "code": combo,
        "loads": {"D_t": dead_load, "L_t": live_load, "P_t": _r(P), "Pu_t": _r(Pu),
                  "Mx_tm": moment_x, "My_tm": moment_y},
        "q_u_t_m2": _r(qu / T_A_KN),
        "bars_x": arm_x, "bars_y": arm_y, "band": banda,
        "dowels": {"count": n_arr, "bar": column_bar, "db": db_col,
                   "leg_m": _r(_arriba(pata, 0.05), 2), "lap_m": _r(_arriba(lap, 0.05), 2),
                   "ldc_m": _r(ldc, 3)},
        "mounting_stirrups": {"count": 3, "bar": "#2.5" if db_col <= 0.0191 else "#3"},
        "pedestal_ties": estribo_dado,
        "checks": rev, "warnings": avisos,
    }
    out["specs"] = especificaciones(out)
    return out


def especificaciones(z: dict[str, Any]) -> dict[str, str]:
    """Los textos del plano, salidos del diseño -- nada se escribe a mano."""
    s: dict[str, str] = {}
    s["plantilla"] = (f"PLANTILLA DE CONCRETO POBRE f'c=100 kg/cm² "
                      f"e={z['lean_concrete'] * 100:.0f} cm")
    s["zapata"] = f"ZAPATA {z['mark']} DE CONCRETO f'c={z['fc']:.0f} kg/cm²"
    bx, by = z.get("bars_x"), z.get("bars_y")
    if bx and by:
        gx = " CON GANCHO A 90°" if bx.get("hook_needed", True) else ""
        s["parrilla"] = (f"PARRILLA LECHO INF. {bx['text']} (X) Y {by['text']} (Y)")
        s["parrilla_x"] = f"VARS. {texto_varilla(bx['bar'])} @ {bx['spacing'] * 100:.0f}{gx}"
        s["parrilla_y"] = f"VARS. {texto_varilla(by['bar'])} @ {by['spacing'] * 100:.0f}"
    dw = z.get("dowels")
    if dw:
        s["arranques"] = (f"{dw['count']} ARRANQUES {texto_varilla(dw['bar'])} "
                          f"CON PATA DE {dw['leg_m'] * 100:.0f} cm")
        s["traslape"] = f"TRASLAPE lb = {dw['lap_m']:.2f} m"
    ms = z.get("mounting_stirrups")
    if ms:
        s["montaje"] = (f"{ms['count']} ESTRIBOS DE MONTAJE {ms['bar']} "
                        "PARA FIJAR LOS ARRANQUES")
    s["recubrimiento"] = f"RECUBRIMIENTO LIBRE {z['cover'] * 100:.1f} cm".replace(".0 cm", " cm")
    s["calzos"] = f"CALZOS DE CONCRETO h={z['cover'] * 100:.1f} cm @ 1.00 m MÁX.".replace(".0 cm", " cm")
    s["junta"] = "JUNTA DE COLADO RUGOSA, LIMPIA Y HUMEDECIDA"
    s["acabado"] = "ACABADO RUGOSO (RAYADO)"
    s["fondo"] = "FONDO DE EXCAVACIÓN LIMPIO, NIVELADO Y COMPACTADO"
    s["relleno"] = "RELLENO COMPACTADO EN CAPAS (SEGÚN E.M.S.)"
    s["terreno"] = "TERRENO NATURAL"
    s["talud"] = "TALUD DE EXCAVACIÓN SEGÚN E.M.S."
    return s


# ------------------------------------------------------------ corrida

def dala(t: float, fc: float, fy: float) -> dict[str, Any]:
    """Dala o castillo de mampostería confinada: refuerzo longitudinal
    As >= 0.2·f'c·t²/fy y al menos 3 barras; estribos a s <= min(1.5t, 20 cm)
    con Asc >= 1000·s/(fy·hc) (NTC Mampostería, castillos y dalas, 5.1).
    En kg/cm² y cm, como las escribe la norma."""
    t_cm = t * 100
    as_req = 0.2 * fc * t_cm ** 2 / fy
    for barra in ("#3", "#4"):
        a = VARILLAS[barra][1]
        n = max(3, math.ceil(as_req / a - 1e-9))
        if n <= 4:
            break
    n = max(n, 4)                     # se arma con 4 esquinas
    s = _abajo(min(1.5 * t, 0.20), 0.05)
    # Asc >= 1000 s/(fy hc) con s y hc en mm, fy en MPa -> mm².
    hc_mm = (t - 2 * 0.02) * 1000     # núcleo con 2 cm de recubrimiento
    asc_req = 1000 * s * 1000 / (fy * KGCM2_A_MPA * hc_mm) / 100.0      # cm²
    estribo = "#2" if asc_req <= VARILLAS["#2"][1] else "#2.5"
    return {"bars": n, "bar": barra, "As_cm2": _r(n * VARILLAS[barra][1]),
            "As_req_cm2": _r(as_req), "stirrup": estribo, "spacing": _r(s, 3),
            "text": f"{n} VARS. {barra}, EST. {estribo} @ {s * 100:.0f}",
            "ref": "NTC Mampostería 5.1: As >= 0.2 f'c t²/fy; s <= 1.5t y 20 cm"}


def _corrida(D, Lv, qa, fc, fc_mpa, fy, fy_mpa, depth, t, material, gamma_s, neta,
             fd, fl, combo, cover, lean, hmin, width, bars, avisos, mark, hd=0.0):
    if t <= 0:
        raise ValueError("wall_thickness (m) es obligatorio en una zapata corrida.")
    if material not in ("concreto", "mamposteria"):
        raise ValueError("wall_material tiene que ser 'concreto' o 'mamposteria'.")
    w = D + Lv
    wu = fd * D + fl * Lv
    h = hmin
    for _ in range(80):
        qe = qa if neta else qa - 2.4 * h - gamma_s * max(depth - h, 0.0)
        if qe <= 0:
            raise ValueError("El peso de zapata y relleno se come la capacidad admisible.")
        B = width or _centrado(max(w / qe, t + 0.30), t)
        qu = wu * T_A_KN / B
        vuelo = (B - t) / 2.0
        # Mampostería: momento a la mitad entre el eje y la cara (13.2.7.1(b)).
        brazo = vuelo + (t / 4.0 if material == "mamposteria" else 0.0)
        db = 0.0127
        d = h - cover - db / 2
        mu = qu * brazo ** 2 / 2.0
        as_t = max(as_flexion(mu, 1.0, d, fc_mpa, fy_mpa), as_minimo(1.0, h, fy_mpa))
        try:
            arm = elegir_armado(as_t, 1.0 + 2 * 0.075, h, bars)
        except ValueError:
            h = _r(h + 0.05)
            continue
        arm["count"] = None
        vu = qu * max(vuelo - d, 0.0)
        vc = PHI_CORTANTE * vc_un_sentido(fc_mpa, 1.0, d, arm["As_cm2"] / (d * 1e4))
        if vu <= vc and math.isfinite(as_t) and d >= 0.15:
            break
        h = _r(h + 0.05)
    as_long = as_minimo(B, h, fy_mpa)
    arm_l = elegir_armado(as_long, B, h, ("#3", "#4", "#5"))
    rev = {
        "capacidad": {"q_t_m2": _r(w / B), "q_adm_efectiva_t_m2": _r(qe), "ok": w / B <= qe + 1e-6,
                      "ref": "Presión de servicio vs. capacidad admisible del E.M.S."},
        "cortante": {"Vu_t": _r(vu / T_A_KN), "phiVc_t": _r(vc / T_A_KN), "ok": vu <= vc + 1e-6,
                     "ref": "ACI 318-19 13.2.7.2, 22.5.5.1(c), por metro"},
        "flexion": {"Mu_tm": _r(mu / T_A_KN), "As_req_cm2_m": _r(as_t), "ok": True,
                    "section": "mitad entre eje y cara (muro de mampostería)" if material ==
                    "mamposteria" else "cara del muro",
                    "ref": "ACI 318-19 13.2.7.1"},
        "longitudinal": {"As_cm2": arm_l["As_cm2"], "As_min_cm2": _r(as_long), "ok": True,
                         "ref": "ACI 318-19 24.4.3.2 (contracción y temperatura)"},
        "peralte_minimo": {"d_m": _r(d, 3), "ok": d >= 0.15 - 1e-9, "ref": "ACI 318-19 13.3.1.2"},
    }
    out = {"ok": all(v["ok"] for v in rev.values()), "kind": "corrida", "mark": mark,
           "B": _r(B), "L": 1.0, "h": _r(h), "d": _r(d, 3), "wall_thickness": t,
           "wall_material": material, "depth": depth, "cover": cover, "lean_concrete": lean,
           "fc": fc, "fy": fy, "code": combo,
           "loads": {"D_t_m": D, "L_t_m": Lv, "w_t_m": _r(w), "wu_t_m": _r(wu)},
           "bars_x": arm, "bars_y": arm_l, "dowels": None, "mounting_stirrups": None,
           "column_offsets": [_r((B - t) / 2, 3)] * 2, "column": [t, 1.0],
           "grade_beam": ({"height": hd, "width": t, **dala(t, fc, fy)} if hd > 0 else None),
           "checks": rev, "warnings": avisos}
    out["specs"] = especificaciones(out)
    out["specs"]["parrilla"] = (f"TRANSVERSAL {arm['text']}, LONGITUDINAL "
                                f"{arm_l['count']} VARS. {arm_l['bar']}")
    return out


# ------------------------------------------------------------ combinada

def _combinada(columns, s, qa, fc, fc_mpa, fy, fy_mpa, depth, gamma_s, neta, fd, fl, combo,
               cover, lean, hmin, width, boundary_left, overhang_left, bars,
               column_bar, column_bar_count, avisos, mark):
    if not columns or len(columns) != 2:
        raise ValueError("combinada: columns = [col1, col2] con dead, live y size.")
    if s <= 0:
        raise ValueError("combinada: spacing (distancia entre ejes, m) es obligatoria.")
    if not boundary_left and overhang_left is None:
        raise ValueError("combinada: boundary_left=True (col. 1 en colindancia) o "
                         "overhang_left = volado desde el eje de la col. 1.")
    P1 = columns[0]["dead"] + columns[0]["live"]
    P2 = columns[1]["dead"] + columns[1]["live"]
    Pu1 = fd * columns[0]["dead"] + fl * columns[0]["live"]
    Pu2 = fd * columns[1]["dead"] + fl * columns[1]["live"]
    c1a, c2a = columns[0]["size"]
    c1b, c2b = columns[1]["size"]
    xr = P2 * s / (P1 + P2)                      # resultante desde el eje de col. 1
    a = c1a / 2 if boundary_left else float(overhang_left)
    Lx = _arriba(2 * (xr + a))
    if Lx < a + s + c1b / 2:
        Lx = _arriba(a + s + c1b / 2)
        avisos.append("El largo por resultante no alcanzaba a cubrir la col. 2: la "
                      "presión ya no es uniforme, revisá la excentricidad.")
    h = hmin
    for _ in range(80):
        qe = qa if neta else qa - 2.4 * h - gamma_s * max(depth - h, 0.0)
        By = width or max(_arriba((P1 + P2) / (qe * Lx)), max(c2a, c2b) + 0.30)
        wu = (Pu1 + Pu2) * T_A_KN / Lx              # kN/m a lo largo
        x1, x2 = a, a + s
        # Diagramas a lo largo (cargas de columna repartidas en su ancho).
        n = 400
        V = []
        M = []
        for i in range(n + 1):
            x = Lx * i / n
            v = wu * x
            m = wu * x * x / 2
            for xc, cw, pu in ((x1, c1a, Pu1), (x2, c1b, Pu2)):
                lo, hi = xc - cw / 2, xc + cw / 2
                f = min(max((x - lo) / cw, 0.0), 1.0)
                p = pu * T_A_KN * f
                v -= p
                if x > lo:
                    xx = min(x, hi)
                    centro = (lo + xx) / 2
                    m -= p * (x - centro)
            V.append((x, v))
            M.append((x, m))
        m_neg = min(mm for _, mm in M)               # tensión arriba (entre columnas)
        m_pos = max(mm for _, mm in M)               # tensión abajo (volados)
        db = 0.0159
        d = h - cover - db
        pun1 = _punzonamiento(Lx, By, c1a, c2a,
                              [x1 - c1a / 2, Lx - x1 - c1a / 2, (By - c2a) / 2, (By - c2a) / 2],
                              d, (Pu1 + Pu2) * T_A_KN / (Lx * By), Pu1 * T_A_KN, fc_mpa)
        pun2 = _punzonamiento(Lx, By, c1b, c2b,
                              [x2 - c1b / 2, Lx - x2 - c1b / 2, (By - c2b) / 2, (By - c2b) / 2],
                              d, (Pu1 + Pu2) * T_A_KN / (Lx * By), Pu2 * T_A_KN, fc_mpa)
        caras = [x1 - c1a / 2 - d, x1 + c1a / 2 + d, x2 - c1b / 2 - d, x2 + c1b / 2 + d]
        vu = max(abs(v) for x, v in V if any(abs(x - c) < Lx / n for c in caras) or False) \
            if caras else 0.0
        as_sup = max(as_flexion(-m_neg, By, d, fc_mpa, fy_mpa), as_minimo(By, h, fy_mpa))
        as_inf = max(as_flexion(m_pos, By, d, fc_mpa, fy_mpa), as_minimo(By, h, fy_mpa))
        if not (math.isfinite(as_sup) and math.isfinite(as_inf)):
            h = _r(h + 0.05)
            continue
        try:
            arm_sup = elegir_armado(as_sup, By, h, bars)
            arm_inf = elegir_armado(as_inf, By, h, bars)
        except ValueError:
            h = _r(h + 0.05)
            continue
        vc = PHI_CORTANTE * vc_un_sentido(fc_mpa, By, d, arm_sup["As_cm2"] / (By * d * 1e4))
        # Los arranques de las dos columnas se desarrollan en compresión
        # dentro de la zapata (ACI 318-19 25.4.9.2): sin esto salía una
        # combinada de 35 cm con arranques #6 que piden 38 cm de desarrollo.
        db_c = VARILLAS[column_bar][0]
        ldc_c = ldc_compresion(db_c, fc_mpa, fy_mpa)
        ok_arr = h - cover - 2 * db - db_c >= ldc_c - 1e-6
        if pun1["ok"] and pun2["ok"] and vu <= vc and d >= 0.15 and ok_arr:
            break
        h = _r(h + 0.05)
    # Transversal: bandas bajo cada columna de ancho c + d (d/2 por lado).
    bandas = []
    for nombre, pu, c1, c2 in (("col1", Pu1, c1a, c2a), ("col2", Pu2, c1b, c2b)):
        ancho = c1 + d
        vuelo = (By - c2) / 2
        mu = pu * T_A_KN / By * vuelo ** 2 / 2
        as_b = max(as_flexion(mu, ancho, d - 0.016, fc_mpa, fy_mpa), as_minimo(ancho, h, fy_mpa))
        bandas.append({"column": nombre, "width_m": _r(ancho, 2), "Mu_tm": _r(mu / T_A_KN),
                       "As_req_cm2": _r(as_b), **elegir_armado(as_b, ancho + 0.15, h, bars)})
    # Fuera de las bandas: el mínimo de contracción y temperatura por metro
    # (ACI 318-19 24.4.3.2), y en el lecho superior transversal barras de
    # montaje a la separación máxima, para sostener la parrilla de arriba.
    trans_min = elegir_armado(as_minimo(1.0, h, fy_mpa), 1.0 + 0.15, h, bars)
    trans_min["count"] = None
    s_mont = _abajo(min(3 * h, 0.45), 0.05)
    montaje = {"bar": "#3", "db": VARILLAS["#3"][0], "spacing": s_mont,
               "text": f"#3 @ {s_mont * 100:.0f} cm",
               "ref": "Montaje del lecho superior a s <= 3h y 45 cm (ACI 318-19 7.7.2.3)"}
    rev = {
        "capacidad": {"q_t_m2": _r((P1 + P2) / (Lx * By)), "q_adm_efectiva_t_m2": _r(qe),
                      "ok": (P1 + P2) / (Lx * By) <= qe + 1e-6,
                      "ref": "Resultante al centroide: presión uniforme"},
        "punzonamiento_col1": pun1, "punzonamiento_col2": pun2,
        "cortante": {"Vu_t": _r(vu / T_A_KN), "phiVc_t": _r(vc / T_A_KN), "ok": vu <= vc + 1e-6,
                     "ref": "ACI 318-19 22.5.5.1(c), a d de las caras"},
        "flexion_superior": {"Mu_tm": _r(-m_neg / T_A_KN), "As_req_cm2": _r(as_sup), "ok": True,
                             "ref": "Entre columnas, tensión ARRIBA (ACI 318-19 22.2)"},
        "flexion_inferior": {"Mu_tm": _r(m_pos / T_A_KN), "As_req_cm2": _r(as_inf), "ok": True,
                             "ref": "Volados y bajo columnas, tensión ABAJO"},
        "peralte_minimo": {"d_m": _r(d, 3), "ok": d >= 0.15 - 1e-9, "ref": "ACI 318-19 13.3.1.2"},
        "arranques": {"count": max(4, column_bar_count), "bar": column_bar,
                      "ldc_m": _r(ldc_c, 3), "available_m": _r(h - cover - 2 * db - db_c, 3),
                      "As_cm2": _r(max(4, column_bar_count) * VARILLAS[column_bar][1]),
                      "As_min_cm2": 0.0, "ok": ok_arr,
                      "ref": "ACI 318-19 25.4.9.2 (ldc), 25.4.1.2"},
    }
    db_col = VARILLAS[column_bar][0]
    out = {"ok": all(v.get("ok", True) for v in rev.values()), "kind": "combinada", "mark": mark,
           "B": _r(Lx), "L": _r(By), "h": _r(h), "d": _r(d, 3),
           "columns": [{"x": _r(x1, 3), "size": [c1a, c2a], "Pu_t": _r(Pu1)},
                       {"x": _r(x2, 3), "size": [c1b, c2b], "Pu_t": _r(Pu2)}],
           "depth": depth, "cover": cover, "lean_concrete": lean, "fc": fc, "fy": fy,
           "code": combo,
           "bars_top": arm_sup, "bars_bottom": arm_inf, "bars_x": arm_inf,
           "bars_y": bandas[0], "transverse_bands": bandas,
           "transverse_min": trans_min, "top_transverse": montaje,
           "boundary_left": bool(boundary_left), "cover_top": 0.05,
           "dowels": {"count": max(4, column_bar_count), "bar": column_bar, "db": db_col,
                      "leg_m": _r(_arriba(max(12 * db_col, 0.15)), 2),
                      "lap_m": _r(_arriba(traslape_compresion(db_col, fy_mpa)), 2),
                      "ldc_m": _r(ldc_compresion(db_col, fc_mpa, fy_mpa), 3)},
           "mounting_stirrups": {"count": 3, "bar": "#2.5"},
           "checks": rev, "warnings": avisos}
    out["specs"] = especificaciones(out)
    out["specs"]["parrilla"] = (f"LECHO INF. {arm_inf['text']}, LECHO SUP. {arm_sup['text']} "
                                "(LONGITUDINAL)")
    return out


# ------------------------------------------------------------ cuantificación

def cantidades(z: dict[str, Any], working_space: float = 0.30, slope: float = 0.5,
               count: int = 1, group: str = "CIMENTACIÓN") -> dict[str, Any]:
    """Volúmenes de obra de la zapata TAL COMO SE DIBUJA (la misma geometría
    que usa el corte): excavación como prismoide con su talud, plantilla,
    concreto, relleno por diferencia, cimbra de fronteras y acero por varilla
    con sus ganchos. Formato de calculate_quantities, para
    create_quantities_table.

    count: cuántas zapatas iguales lleva el proyecto."""
    if z["kind"] == "corrida":
        return _cantidades_corrida(z, working_space, slope, count, group)
    B, L, h, Df, e = z["B"], z["L"], z["h"], z["depth"], z["lean_concrete"]
    cov = z["cover"]
    colind = [o < 1e-6 for o in z.get("column_offsets", [1, 1, 1, 1])]
    H = Df + e
    ex = [0.0 if c else working_space for c in colind]       # holgura por lado
    ta = [0.0 if c else slope * H for c in colind]           # talud por lado
    b1, l1 = B + ex[0] + ex[1], L + ex[2] + ex[3]
    b2, l2 = b1 + ta[0] + ta[1], l1 + ta[2] + ta[3]
    A1, A2 = b1 * l1, b2 * l2
    Am = ((b1 + b2) / 2) * ((l1 + l2) / 2)
    v_exc = H / 6.0 * (A1 + 4 * Am + A2)
    v_pl = B * L * e
    v_zap = B * L * h
    c1, c2 = z["column"] if z.get("column") else (0.0, 0.0)
    hp = z.get("pedestal_height") or 0.0
    a1, a2 = z.get("pedestal") or (c1, c2)
    v_dado = a1 * a2 * hp
    v_col = c1 * c2 * max(Df - h - hp, 0.0)
    v_rel = v_exc - v_pl - v_zap - v_dado - v_col
    cimbra = 2 * (B + L) * h
    items: list[dict[str, Any]] = []

    def it(tipo, label, campo, valor, unidad, **extra):
        items.append({"type": tipo, "label": label, campo: _r(valor * count, 2),
                      "unit": unidad, "group": group, **extra})

    m = z["mark"]
    it("earthwork", f"Excavación {m} con talud {slope:g}:1 (prismoide)", "volume", v_exc, "m3",
       mode="excavation")
    it("concrete_volume", f"Plantilla concreto pobre f'c=100, e={e * 100:.0f} cm", "volume",
       v_pl, "m3")
    it("formwork", f"Cimbra de fronteras {m}", "areaTotal", cimbra, "m2")
    it("concrete_volume", f"Concreto f'c={z['fc']:.0f} kg/cm² zapata {m}", "volume", v_zap, "m3")
    if hp > 0:
        it("formwork", f"Cimbra del dado {m}", "areaTotal", 2 * (a1 + a2) * hp, "m2")
        it("concrete_volume", f"Concreto f'c={z['fc']:.0f} kg/cm² dado {a1 * 100:.0f}x"
           f"{a2 * 100:.0f}x{hp * 100:.0f}", "volume", v_dado, "m3")
    kg = 0.0
    for clave, largo_util in (("bars_x", B), ("bars_y", L)):
        arm = z[clave]
        db, _a, kgm = VARILLAS[arm["bar"]]
        n = max(2, int(round((L if clave == "bars_x" else B) - 2 * cov - db) / arm["spacing"])) \
            if False else max(2, int(round(((L if clave == "bars_x" else B) - 2 * cov - db)
                                           / arm["spacing"])) + 1)
        gancho = min(max(12 * db, 0.15), h - 2 * cov)
        largo = largo_util - 2 * cov + 2 * gancho
        peso = n * largo * kgm
        kg += peso
        it("steel_weight", f"Parrilla {arm['bar']} @ {arm['spacing'] * 100:.0f} "
           f"({'X' if clave == 'bars_x' else 'Y'}): {n} vars. de {largo:.2f} m", "weight",
           peso, "kg")
    dw = z.get("dowels")
    if dw:
        db, _a, kgm = VARILLAS[dw["bar"]]
        largo = dw["lap_m"] + hp + (h - cov - 0.05) + dw["leg_m"]
        it("steel_weight", f"Arranques {dw['count']} {dw['bar']} de {largo:.2f} m", "weight",
           dw["count"] * largo * kgm, "kg")
        ms = z.get("mounting_stirrups")
        if ms and c1:
            dbe, _a, kge = VARILLAS[ms["bar"]]
            per = 2 * (c1 - 0.08) + 2 * (c2 - 0.08) + 2 * max(6 * dbe, 0.075)
            it("steel_weight", f"Estribos de montaje {ms['count']} {ms['bar']}", "weight",
               ms["count"] * per * kge, "kg")
        tie = z.get("pedestal_ties")
        if tie and hp > 0:
            dbe, _a, kge = VARILLAS[tie["bar"]]
            n_t = int((hp - 0.10) / tie["spacing"] + 1e-9) + 1
            per = 2 * (a1 - 0.08) + 2 * (a2 - 0.08) + 2 * max(6 * dbe, 0.075)
            it("steel_weight", f"Estribos del dado {n_t} {tie['bar']} @ {tie['spacing'] * 100:.0f}",
               "weight", n_t * per * kge, "kg")
    it("earthwork", "Relleno compactado (excavación menos lo colado)", "volume",
       v_rel, "m3", mode="backfill")
    tot: dict[str, float] = {}
    for i in items:
        if i["type"] == "earthwork":
            k = "excavacion_m3" if i.get("mode") == "excavation" else "relleno_m3"
            tot[k] = tot.get(k, 0.0) + i["volume"]
        elif i["type"] == "concrete_volume":
            # La plantilla es concreto pobre: no se suma al estructural.
            k = "concreto_pobre_m3" if "Plantilla" in i["label"] else "concreto_m3"
            tot[k] = tot.get(k, 0.0) + i["volume"]
        elif i["type"] == "steel_weight":
            tot["acero_kg"] = tot.get("acero_kg", 0.0) + i["weight"]
        elif i["type"] == "formwork":
            tot["cimbra_m2"] = tot.get("cimbra_m2", 0.0) + i["areaTotal"]
    return {"items": items, "totals": {k: _r(v, 2) for k, v in tot.items()},
            "count": count}


def _totales(items: list[dict[str, Any]]) -> dict[str, float]:
    tot: dict[str, float] = {}
    for i in items:
        if i["type"] == "earthwork":
            k = "excavacion_m3" if i.get("mode") == "excavation" else "relleno_m3"
            tot[k] = tot.get(k, 0.0) + i["volume"]
        elif i["type"] == "concrete_volume":
            k = "concreto_pobre_m3" if "Plantilla" in i["label"] else "concreto_m3"
            tot[k] = tot.get(k, 0.0) + i["volume"]
        elif i["type"] == "steel_weight":
            tot["acero_kg"] = tot.get("acero_kg", 0.0) + i["weight"]
        elif i["type"] == "formwork":
            tot["cimbra_m2"] = tot.get("cimbra_m2", 0.0) + i["areaTotal"]
    return {k: _r(v, 2) for k, v in tot.items()}


def _cantidades_corrida(z, working_space, slope, metros, group):
    """Zapata corrida POR METRO LINEAL (metros = longitud a cuantificar;
    1 da el rendimiento por metro, que es como se presupuesta)."""
    B, h, Df, e, t = z["B"], z["h"], z["depth"], z["lean_concrete"], z["wall_thickness"]
    cov = z["cover"]
    H = Df + e
    b1 = B + 2 * working_space
    b2 = b1 + 2 * slope * H
    v_exc = (b1 + b2) / 2 * H
    gb = z.get("grade_beam")
    hd = gb["height"] if gb else 0.0
    v_dala = t * hd
    v_muro = t * max(Df - h - hd, 0.0)
    v_rel = v_exc - B * e - B * h - v_dala - v_muro
    items: list[dict[str, Any]] = []
    m = z["mark"]
    sufijo = " (por metro)" if metros == 1 else f" ({metros:g} m)"

    def it(tipo, label, campo, valor, unidad, **extra):
        items.append({"type": tipo, "label": label + sufijo, campo: _r(valor * metros, 2),
                      "unit": unidad, "group": group, **extra})

    it("earthwork", f"Excavación {m} con talud {slope:g}:1", "volume", v_exc, "m3",
       mode="excavation")
    it("concrete_volume", f"Plantilla concreto pobre f'c=100, e={e * 100:.0f} cm", "volume",
       B * e, "m3")
    it("formwork", f"Cimbra de fronteras {m}", "areaTotal", 2 * h, "m2")
    it("concrete_volume", f"Concreto f'c={z['fc']:.0f} kg/cm² zapata {m}", "volume", B * h, "m3")
    bx, by = z["bars_x"], z["bars_y"]
    db, _a, kgm = VARILLAS[bx["bar"]]
    gancho = min(max(12 * db, 0.15), h - 2 * cov)
    it("steel_weight", f"Transversal {bx['text']} de {B - 2 * cov + 2 * gancho:.2f} m", "weight",
       (1.0 / bx["spacing"]) * (B - 2 * cov + 2 * gancho) * kgm, "kg")
    it("steel_weight", f"Longitudinal {by['count']} {by['bar']}", "weight",
       by["count"] * VARILLAS[by["bar"]][2], "kg")
    if gb:
        it("formwork", f"Cimbra de la dala {t * 100:.0f}x{hd * 100:.0f}", "areaTotal", 2 * hd, "m2")
        it("concrete_volume", f"Concreto dala de desplante {t * 100:.0f}x{hd * 100:.0f}",
           "volume", v_dala, "m3")
        it("steel_weight", f"Dala: {gb['bars']} {gb['bar']}", "weight",
           gb["bars"] * VARILLAS[gb["bar"]][2], "kg")
        dbe, _a, kge = VARILLAS[gb["stirrup"]]
        per = 2 * (t - 0.05) + 2 * (hd - 0.05) + 2 * max(6 * dbe, 0.075)
        it("steel_weight", f"Dala: estribos {gb['stirrup']} @ {gb['spacing'] * 100:.0f}", "weight",
           (1.0 / gb["spacing"]) * per * kge, "kg")
    it("earthwork", "Relleno compactado (excavación menos lo colado)", "volume", v_rel, "m3",
       mode="backfill")
    return {"items": items, "totals": _totales(items), "count": metros}
