"""Bajada de cargas y diseño de trabes y losas para estructuras de concreto
de vivienda: losas perimetralmente apoyadas sobre trabes, trabes continuas
sobre columnas.

  panel_edge_loads   reparto de un tablero a sus cuatro bordes por líneas a
                     45° (trapecio en el largo, triángulo en el corto) y la
                     carga uniforme equivalente para momento.
  continuous_beam    viga continua sobre apoyos simples por el método de
                     rigideces: momentos en apoyos y en claros, cortantes,
                     reacciones.
  design_beam        trabe rectangular por ACI 318-19: peralte mínimo
                     (9.3.1.1), flexión (22.2), acero mínimo (9.6.1.2),
                     cortante (22.5.5.1) y estribos (9.7.6.2.2).
  design_two_way_slab  losa maciza perimetralmente apoyada: reparto de
                     Rankine-Grashof, momentos por franja, espesor mínimo
                     (ACI 318-19 8.3.1.2) y acero mínimo / separación
                     máxima (8.6.1.1, 8.7.2.2).

Unidades de entrada: m, kg/m² y kg/m (cargas de SERVICIO), kg/cm². Las
salidas en t, t·m, cm². Nada se supone: f'c, cargas y geometría las pasa
quien proyecta.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import zapatas as zap

KG_A_KN = 0.00980665


def _r(v, n=2):
    return round(float(v), n)


# ------------------------------------------------------------ tableros

def panel_edge_loads(lx: float, ly: float, w: float) -> dict[str, Any]:
    """Reparto de un tablero rectangular (w en kg/m²) a sus bordes por
    líneas a 45°. lx: lado CORTO, ly: lado LARGO (se ordenan solos).

    Devuelve, por tipo de borde, la carga máxima y la UNIFORME EQUIVALENTE
    para momento de un claro simplemente apoyado:
      triangular (lado corto):  w·a/3
      trapecial  (lado largo):  w·a/6·(3 − (a/b)²)
    con a = lado corto, b = lado largo."""
    a, b = sorted((float(lx), float(ly)))
    return {"short": {"length": a, "peak_kg_m": _r(w * a / 2), "equiv_kg_m": _r(w * a / 3)},
            "long": {"length": b, "peak_kg_m": _r(w * a / 2),
                     "equiv_kg_m": _r(w * a / 6 * (3 - (a / b) ** 2))},
            "method": "Líneas de rotura a 45°; carga uniforme equivalente para momento"}


# ------------------------------------------------------------ viga continua

def continuous_beam(spans: list[float], loads: list[float],
                    point_loads: Optional[list[list[tuple[float, float]]]] = None,
                    n_samples: int = 40) -> dict[str, Any]:
    """Viga continua sobre apoyos simples (columnas como articulaciones),
    método de rigideces con un grado de libertad de giro por apoyo.

    spans: claros, m. loads: carga uniforme por claro, kg/m. point_loads
    opcional: por claro, [(distancia desde el apoyo izq., P kg), ...].
    Devuelve los momentos en apoyos (negativos = tensión arriba), el máximo
    positivo de cada claro, cortantes en los paños de apoyo y reacciones,
    en t y t·m."""
    n = len(spans)
    if n == 0 or len(loads) != n:
        raise ValueError("spans y loads tienen que tener el mismo largo (>0).")
    pl = point_loads or [[] for _ in spans]
    # Momentos de empotramiento perfecto (horario +) por claro.
    fem = []
    for L, w, ps in zip(spans, loads, pl):
        mi = -w * L ** 2 / 12.0
        mj = w * L ** 2 / 12.0
        for a, P in ps:
            b = L - a
            mi += -P * a * b ** 2 / L ** 2
            mj += P * a ** 2 * b / L ** 2
        fem.append((mi, mj))
    # K·theta = -FEM ensamblado (EI constante).
    m = n + 1
    K = [[0.0] * m for _ in range(m)]
    F = [0.0] * m
    for i, L in enumerate(spans):
        k = 4.0 / L
        c = 2.0 / L
        K[i][i] += k
        K[i][i + 1] += c
        K[i + 1][i] += c
        K[i + 1][i + 1] += k
        F[i] -= fem[i][0]
        F[i + 1] -= fem[i][1]
    th = _resolver(K, F)
    m_ext = []
    for i, L in enumerate(spans):
        mi = fem[i][0] + 4.0 / L * th[i] + 2.0 / L * th[i + 1]
        mj = fem[i][1] + 2.0 / L * th[i] + 4.0 / L * th[i + 1]
        m_ext.append((mi, mj))
    # Convención de diseño: momento de apoyo negativo (tensión arriba).
    apoyos = [0.0] * m
    for i, (mi, mj) in enumerate(m_ext):
        apoyos[i] = min(apoyos[i], mi) if i else mi
        apoyos[i + 1] = -mj
    apoyos[0] = m_ext[0][0]
    apoyos = [-abs(v) if abs(v) > 1e-9 else 0.0 for v in apoyos]
    apoyos[0] = m_ext[0][0] if abs(m_ext[0][0]) > 1e-9 else 0.0
    claros = []
    reacc = [0.0] * m
    for i, (L, w, ps) in enumerate(zip(spans, loads, pl)):
        ml = m_ext[i][0]          # antihorario visto desde el claro
        mr = m_ext[i][1]
        # Cortante en el extremo izquierdo por equilibrio.
        suma_p = sum(P for _, P in ps)
        mom_p = sum(P * (L - a) for a, P in ps)
        vi = (w * L ** 2 / 2.0 + mom_p - ml - mr) / L
        vj = w * L + suma_p - vi
        reacc[i] += vi
        reacc[i + 1] += vj
        mmax = -1e18
        for k in range(n_samples + 1):
            x = L * k / n_samples
            # Momento flector (positivo = tensión abajo): en el extremo
            # izquierdo vale el momento de extremo (antihorario = negativo).
            mx = ml + vi * x - w * x * x / 2.0 - sum(P * (x - a) for a, P in ps if x > a)
            mmax = max(mmax, mx)
        claros.append({"L": L, "w_kg_m": _r(w, 1), "V_left_t": _r(vi / 1000, 3),
                       "V_right_t": _r(vj / 1000, 3), "M_pos_tm": _r(mmax / 1000, 3),
                       "M_left_tm": _r(-ml / 1000 if i == 0 else -abs(ml) / 1000, 3),
                       "M_right_tm": _r(-abs(mr) / 1000, 3)})
    return {"spans": claros, "reactions_t": [_r(r / 1000, 3) for r in reacc],
            "support_moments_tm": [_r(-abs(v) / 1000, 3) for v in
                                   [m_ext[0][0]] + [m_ext[i][1] for i in range(n)]],
            "method": "Rigideces, EI constante, apoyos articulados (columnas sin rigidez)"}


def _resolver(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        if abs(M[c][c]) < 1e-14:
            raise ValueError("Sistema singular: revisá los claros.")
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


# ------------------------------------------------------------ trabe

ESTRIBOS = {"#2.5": 0.49, "#3": 0.71}


def min_depth_beam(L: float, condition: str) -> float:
    """ACI 318-19 tabla 9.3.1.1 (fy = 420 MPa): simplemente apoyada L/16,
    un extremo continuo L/18.5, ambos continuos L/21, voladizo L/8."""
    div = {"simple": 16.0, "one_end": 18.5, "both": 21.0, "cantilever": 8.0}[condition]
    return L / div


def design_beam(b: float, h: float, m_pos_tm: float, m_neg_tm: float, v_tm: float,
                fc: float, fy: float = 4200.0, cover: float = 0.04,
                stirrup: str = "#3", span: Optional[float] = None,
                condition: Optional[str] = None,
                bars: tuple[str, ...] = ("#4", "#5", "#6", "#8")) -> dict[str, Any]:
    """Trabe rectangular b x h (m). Momentos y cortante YA factorizados, en
    t·m y t. Devuelve las barras inferiores y superiores (con el mínimo de
    9.6.1.2), los estribos (Vc 22.5.5.1(a) con Av >= Av,min; s <= d/2 y
    600 mm, 9.7.6.2.2) y la revisión de peralte mínimo si se da el claro."""
    fc_mpa, fy_mpa = fc * zap.KGCM2_A_MPA, fy * zap.KGCM2_A_MPA
    db_e = zap.VARILLAS[stirrup][0]
    d = h - cover - db_e - 0.0159 / 2
    as_min = max(0.25 * math.sqrt(fc_mpa) / fy_mpa, 1.4 / fy_mpa) * b * d * 1e4   # cm²
    def barras(mu_tm):
        as_f = zap.as_flexion(abs(mu_tm) * 9.80665, b, d, fc_mpa, fy_mpa)
        if not math.isfinite(as_f):
            raise ValueError(f"La sección {b:.2f}x{h:.2f} no da para Mu = {mu_tm:.2f} t·m.")
        req = max(as_f, as_min)
        for nombre in bars:
            a = zap.VARILLAS[nombre][1]
            n = max(2, math.ceil(req / a - 1e-9))
            libre = (b - 2 * cover - 2 * db_e - n * zap.VARILLAS[nombre][0]) / max(n - 1, 1)
            if libre >= max(0.025, zap.VARILLAS[nombre][0]):        # ACI 25.2.1
                return {"count": n, "bar": nombre, "As_cm2": _r(n * a), "As_req_cm2": _r(req),
                        "text": f"{n} {nombre}"}
        raise ValueError(f"No caben las barras para {req:.1f} cm² en b={b:.2f}: ensanchá.")
    inf = barras(m_pos_tm)
    sup = barras(m_neg_tm)
    # Cortante.
    vu = abs(v_tm) * 9.80665                                      # kN
    vc = 0.17 * math.sqrt(fc_mpa) * b * 1000 * d * 1000 / 1000    # kN
    phi = zap.PHI_CORTANTE
    av = 2 * ESTRIBOS[stirrup] * 100                               # mm²
    vs_req = max(vu / phi - vc, 0.0)
    s_max = min(d / 2, 0.60)
    if vs_req > 0:
        s_v = av * fy_mpa * d * 1000 / (vs_req * 1000) / 1000     # m
    else:
        s_v = s_max
    av_min_s = max(0.062 * math.sqrt(fc_mpa) * b * 1000 / fy_mpa, 0.35 * b * 1000 / fy_mpa)
    s_avmin = av / av_min_s / 1000
    # ACI 318-19 9.6.3.1: con Vu <= phi·Vc/2 no hace falta Av,min; queda el
    # estribo constructivo a s_max (d/2, <= 60 cm). Paso de armado: 2.5 cm.
    exento = vu <= 0.5 * phi * vc
    s_obj = s_max if exento else min(s_v, s_max, s_avmin)
    s = math.floor(s_obj / 0.025 + 1e-9) * 0.025
    ok_v = vs_req <= 0.66 * math.sqrt(fc_mpa) * b * 1000 * d * 1000 / 1000   # 22.5.1.2
    out = {"b": b, "h": h, "d": _r(d, 3), "bottom": inf, "top": sup,
           "stirrups": {"bar": stirrup, "spacing": _r(s, 3), "text": f"E{stirrup} @ {s * 100:.0f}",
                        "phiVc_t": _r(phi * vc / 9.80665), "Vu_t": _r(v_tm),
                        "required": not exento,
                        "note": ("Vu <= phi·Vc/2: estribos constructivos (ACI 9.6.3.1)" if exento
                                 else "Av >= Av,min (ACI 9.6.3.3)")},
           "ok": ok_v and s >= 0.05,
           "refs": "ACI 318-19 22.2, 9.6.1.2, 22.5.5.1(a), 9.7.6.2.2"}
    if span and condition:
        hmin = min_depth_beam(span, condition)
        out["min_depth"] = {"h_min": _r(hmin, 3), "ok": h >= hmin - 1e-9,
                            "ref": "ACI 318-19 tabla 9.3.1.1"}
        out["ok"] = out["ok"] and h >= hmin - 1e-9
    return out


# ------------------------------------------------------------ losa

def design_two_way_slab(lx: float, ly: float, w_dead: float, w_live: float, fc: float,
                        h: float, fy: float = 4200.0, cover: float = 0.02,
                        continuous_edges: int = 0, code: str = "NTC",
                        bars: tuple[str, ...] = ("#3", "#4")) -> dict[str, Any]:
    """Losa maciza perimetralmente apoyada en trabes, por franjas:
    reparto de Rankine-Grashof (wx = w·ly⁴/(lx⁴+ly⁴)), momento por franja
    w·l²/8 en el centro (reducido a w·l²/10 y negativo w·l²/10 si el borde
    es continuo), acero mínimo 0.0018·Ag (ACI 318-19 8.6.1.1) y separación
    máxima min(2h, 450 mm) (8.7.2.2). Espesor mínimo con trabes rígidas
    (alfa_fm > 2): ln(0.8 + fy/1400)/(36 + 9β), >= 90 mm (8.3.1.2).
    w en kg/m² de SERVICIO; se factoriza con 'code'."""
    a, b = sorted((lx, ly))
    fd, fl, combo = zap.COMBOS[code]
    wu = fd * w_dead + fl * w_live
    wa = wu * b ** 4 / (a ** 4 + b ** 4)          # al claro corto
    wb = wu - wa
    coef = 10.0 if continuous_edges else 8.0
    fc_mpa, fy_mpa = fc * zap.KGCM2_A_MPA, fy * zap.KGCM2_A_MPA
    d = h - cover - 0.0095
    res = {}
    for nombre, w, l, dd in (("corto", wa, a, d), ("largo", wb, b, d - 0.0095)):
        mu = w * l ** 2 / coef / 1000.0              # t·m/m
        as_f = zap.as_flexion(mu * 9.80665, 1.0, dd, fc_mpa, fy_mpa)
        req = max(as_f, 0.0018 * 1.0 * h * 1e4)
        s_max = min(2 * h, 0.45)
        arm = None
        for barra in bars:
            area = zap.VARILLAS[barra][1]
            s = math.floor(min(area / req, s_max) / 0.025 + 1e-9) * 0.025
            if s >= 0.10:
                arm = {"bar": barra, "spacing": _r(s, 3), "text": f"{barra} @ {s * 100:.0f}",
                       "As_req_cm2_m": _r(req, 2), "Mu_tm_m": _r(mu, 3)}
                break
        res[nombre] = arm
    ln = b - 0.20
    beta = b / a
    hmin = max(ln * (0.8 + fy_mpa / 1400.0) / (36 + 9 * beta), 0.09)
    return {"lx": a, "ly": b, "h": h, "wu_kg_m2": _r(wu, 1), "combo": combo,
            "short": res["corto"], "long": res["largo"],
            "min_thickness": {"h_min": _r(hmin, 3), "ok": h >= hmin - 1e-9,
                              "ref": "ACI 318-19 8.3.1.2 (alfa_fm > 2)"},
            "method": "Franjas con reparto de Rankine-Grashof; As mín. 0.0018Ag, s <= 2h",
            "ok": h >= hmin - 1e-9 and res["corto"] is not None and res["largo"] is not None}


# ------------------------------------------------------------ dintel

def design_lintel(clear_span: float, bearing: float, wall_thickness: float,
                  wall_height_above: float, fc: float, h: float,
                  masonry_unit_weight: float = 1500.0, extra_load_kg_m: float = 0.0,
                  fy: float = 4200.0, code: str = "NTC", stirrup: str = "#2.5",
                  bars: tuple[str, ...] = ("#3", "#4", "#5")) -> dict[str, Any]:
    """Dintel (cerramiento) de concreto sobre un vano de `clear_span` m con
    apoyo `bearing` a cada lado; sección b = wall_thickness x h (m).

    Carga de muro: si el muro sobre el vano es más alto que el triángulo
    equilátero de descarga (h_t = L·raíz(3)/2, con L = claro de cálculo entre
    centros de apoyo), solo pesa ese TRIÁNGULO (efecto arco de la mampostería:
    práctica clásica de muros, 60 grados); si no, pesa todo el muro como carga
    uniforme. extra_load_kg_m: lo que además llega al dintel (losa, trabe)
    SIN efecto arco. Se factoriza con `code` y se diseña con design_beam
    (ACI 318-19) como viga simplemente apoyada.
    El efecto arco solo vale con mampostería trabada y apoyos capaces de
    tomar el empuje: está marcado como práctica, no como norma."""
    if min(clear_span, bearing, wall_thickness, h, fc) <= 0 or wall_height_above < 0:
        raise ValueError("clear_span, bearing, wall_thickness, h y fc > 0; wall_height_above >= 0.")
    L = clear_span + bearing                       # claro de cálculo (centros de apoyo)
    fd, fl, combo = zap.COMBOS[code]
    h_t = L * math.sqrt(3) / 2
    gamma_t = masonry_unit_weight * wall_thickness   # kg/m de muro por metro de altura
    if wall_height_above >= h_t:
        w_peak = gamma_t * h_t                       # kg/m en el centro del triángulo
        m_muro = w_peak * L * L / 12.0               # momento de carga triangular (pico al centro)
        v_muro = w_peak * L / 4.0
        modelo = f"Triángulo de descarga a 60 grados, h_t = {h_t:.2f} m (práctica de mampostería)"
    else:
        w_u = gamma_t * wall_height_above
        m_muro = w_u * L * L / 8.0
        v_muro = w_u * L / 2.0
        modelo = f"Muro completo como carga uniforme ({wall_height_above:.2f} m < h_t = {h_t:.2f} m)"
    peso_propio = 2400.0 * wall_thickness * h
    m_pp = peso_propio * L * L / 8.0
    v_pp = peso_propio * L / 2.0
    m_extra = extra_load_kg_m * L * L / 8.0
    v_extra = extra_load_kg_m * L / 2.0
    # el extra se trata como carga muerta (losa); si es viva, factorizarla aparte
    mu = (fd * (m_muro + m_pp + m_extra)) / 1000.0          # t·m
    vu = (fd * (v_muro + v_pp + v_extra)) / 1000.0           # t
    d = design_beam(wall_thickness, h, mu, 0.0, vu, fc, fy, cover=0.025, stirrup=stirrup,
                    span=L, condition="simple", bars=bars)
    return {"clear_span": clear_span, "bearing": bearing, "design_span": _r(L),
            "section": {"b": wall_thickness, "h": h},
            "load_model": modelo, "combo": combo,
            "Mu_tm": _r(mu, 3), "Vu_t": _r(vu, 3),
            "bottom": d["bottom"], "top": d["top"], "stirrups": d["stirrups"],
            "min_depth": d.get("min_depth"), "ok": d["ok"],
            "notes": ["El apoyo mínimo del dintel lo fija la norma local de mampostería: "
                      f"se usó bearing = {bearing:.2f} m como dato del proyecto.",
                      "El acero superior sale del mínimo (viga simplemente apoyada)."],
            "refs": d["refs"] + "; triángulo de descarga: práctica"}
