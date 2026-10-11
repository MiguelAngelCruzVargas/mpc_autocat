"""Alberca residencial: DISEÑO (hidráulico y estructural) y DIBUJO de oficio.

design_pool  -> volumen, recirculación, filtro, bomba, tuberías, drenes de
                fondo antiatrapamiento, y el muro y la losa del vaso con su
                armado. Cada número dice de dónde sale: norma (con artículo)
                o práctica de proyecto (marcada así, para que se pueda
                cambiar sin creer que es ley).
draw_pool_plan / draw_pool_section -> planta y corte longitudinal.

Lo que NO inventa: el nivel freático y el terreno (salen del E.M.S.), ni la
marca de los equipos. Lo que no se tenga va como SUPUESTO en las notas.

Unidades: m, m³, L/s, kg/cm² (f'c, fy), t/m³.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import annotation as ann_mod
import autocad_client as acad
import detalle as dt
import layers
import materials as mat_mod
import rebar
import symbols as sym_mod
import zapatas as zap

# PVC hidráulico cédula 40: diámetro nominal -> diámetro interior (m).
PVC40 = {'1 1/2"': 0.0409, '2"': 0.0525, '2 1/2"': 0.0627, '3"': 0.0779, '4"': 0.1023}

V_SUCCION_MAX = 1.83     # m/s (6 ft/s): ANSI/APSP/ICC-7, salidas de succión
V_RETORNO_MAX = 2.44     # m/s (8 ft/s): ANSI/APSP/ICC-5, tubería de retorno
TASA_FILTRO_ARENA = 49.0  # m³/h·m² (20 gpm/ft²): filtro de arena de alta tasa, NSF/ANSI 50
SEPARACION_DRENES = 0.91  # m (3 ft) entre drenes de fondo: ANSI/APSP/ICC-7

L_ALB = "ALBERCA"
L_ALB_HID = "ALBERCA-HIDRAULICA"
L_ALB_ARM = "ALBERCA-ARMADO"


def _r(v, n=2):
    return round(float(v), n)


def _tubo(q_m3s: float, v_max: float) -> dict[str, Any]:
    for nom, di in PVC40.items():
        v = q_m3s / (math.pi * di ** 2 / 4)
        if v <= v_max:
            return {"nominal": nom, "inner_m": di, "velocity_m_s": _r(v, 2), "limit_m_s": v_max}
    raise ValueError("El gasto pide más de 4\": revisá la recirculación.")


def design_pool(length: float, width: float, shallow: float, deep: float,
                fc: float, soil_unit_weight: Optional[float] = None,
                turnover_hours: float = 6.0, freeboard: float = 0.15,
                k0: float = 0.5, fy: float = 4200.0, cover: float = 0.05,
                wall_thickness: float = 0.20, slab_thickness: float = 0.20,
                returns: int = 3, skimmers: int = 1) -> dict[str, Any]:
    """Diseña una alberca rectangular con fondo en pendiente.

    length/width: espejo de agua interior, m. shallow/deep: tirante en cada
    extremo, m. fc: f'c del vaso, kg/cm² (dato del proyecto, sin default).
    soil_unit_weight: t/m³ del terreno alrededor (E.M.S.); sin él el muro se
    revisa solo con el agua y se avisa.
    turnover_hours: horas para recircular TODO el volumen. 6 h es práctica
    residencial habitual (marcada como tal), no un artículo de norma.
    freeboard: del espejo de agua al remate, m.
    k0: empuje en reposo del terreno (0.5 es el valor de anteproyecto para
    suelo granular; el E.M.S. lo da).
    returns/skimmers: boquillas de retorno y desnatadores [PROY].

    Revisiones: el muro como voladizo empotrado en la losa, cargado por el
    agua (lleno, sin relleno) o por el terreno (vacío), con el factor de
    durabilidad Sd = 1.3 de ACI 350-06 9.2.6 sobre la combinación de ACI
    318 (1.4 fluido, 1.6 tierra); acero mínimo de contracción ACI 350 tabla
    7.12.2.1 según la distancia entre juntas (el vaso sin juntas: su lado
    mayor); recubrimiento 5 cm."""
    if min(length, width, shallow, deep) <= 0:
        raise ValueError("length, width, shallow y deep tienen que ser > 0.")
    if deep < shallow:
        raise ValueError("deep tiene que ser >= shallow.")
    if not fc:
        raise ValueError("fc (kg/cm²) es un dato del proyecto: no se supone.")
    avisos: list[str] = []
    # ---- hidráulica ------------------------------------------------------
    volumen = length * width * (shallow + deep) / 2.0
    q_h = volumen / turnover_hours                     # m³/h
    q = q_h / 3600.0                                   # m³/s
    area_filtro = q_h / TASA_FILTRO_ARENA
    d_filtro = math.sqrt(4 * area_filtro / math.pi)
    # La succión se reparte: drenes de fondo + desnatadores. Se dimensiona
    # cada salida para el gasto TOTAL (si una se tapa, la otra lo toma:
    # ANSI/APSP/ICC-7) y el colector para el total.
    succion = _tubo(q, V_SUCCION_MAX)
    retorno = _tubo(q, V_RETORNO_MAX)
    q_boquilla = q / max(returns, 1)
    # ---- estructura: muro en voladizo ------------------------------------
    H = deep + freeboard
    t = wall_thickness
    d = t - cover - 0.0127 / 2
    gw = 9.81                                          # kN/m³
    m_agua = gw * H ** 3 / 6.0                         # kN·m/m
    sd = 1.3
    mu_agua = 1.4 * sd * m_agua
    mu_tierra = 0.0
    if soil_unit_weight:
        gs = soil_unit_weight * 9.81
        mu_tierra = 1.6 * sd * k0 * gs * H ** 3 / 6.0
    else:
        avisos.append("Sin peso del terreno el muro se revisó solo con el agua: falta el "
                      "caso vacío con relleno (E.M.S.).")
    fc_mpa, fy_mpa = fc * zap.KGCM2_A_MPA, fy * zap.KGCM2_A_MPA
    junta = max(length, width)
    rho_min = 0.003 if junta < 6 else 0.004 if junta < 9 else 0.005
    as_min_cara = rho_min * 1.0 * t * 1e4 / 2.0         # cm²/m por cara
    caras = {}
    for cara, mu in (("interior", mu_agua), ("exterior", mu_tierra)):
        as_f = zap.as_flexion(mu, 1.0, d, fc_mpa, fy_mpa)
        as_req = max(as_f, as_min_cara)
        arm = zap.elegir_armado(as_req, 1.0 + 0.15, t, ("#3", "#4", "#5"))
        arm["count"] = None
        caras[cara] = {"Mu_kNm_m": _r(mu, 2), "As_flexion_cm2_m": _r(as_f, 2), **arm}
    vu = 1.4 * sd * gw * H ** 2 / 2.0
    vc = zap.PHI_CORTANTE * zap.vc_un_sentido(fc_mpa, 1.0, d, caras["interior"]["As_cm2"] / (d * 1e4))
    losa_as = max(rho_min * slab_thickness * 1e4 / 2.0, 0.0)
    losa = zap.elegir_armado(losa_as, 1.0 + 0.15, slab_thickness, ("#3", "#4", "#5"))
    losa["count"] = None
    checks = {
        "flexion_muro": {"ok": True, "faces": caras,
                         "ref": "ACI 318-19 22.2 con Sd=1.3 (ACI 350-06 9.2.6)"},
        "cortante_muro": {"Vu_kN_m": _r(vu), "phiVc_kN_m": _r(vc), "ok": vu <= vc,
                          "ref": "ACI 318-19 22.5.5.1(c) con Sd"},
        "acero_minimo": {"rho": rho_min, "joint_spacing_m": junta, "ok": True,
                         "ref": "ACI 350-06 tabla 7.12.2.1 (contracción y temperatura)"},
        "velocidad_succion": {"ok": succion["velocity_m_s"] <= V_SUCCION_MAX,
                              "value": succion["velocity_m_s"], "limit": V_SUCCION_MAX,
                              "ref": "ANSI/APSP/ICC-7"},
        "velocidad_retorno": {"ok": retorno["velocity_m_s"] <= V_RETORNO_MAX,
                              "value": retorno["velocity_m_s"], "limit": V_RETORNO_MAX,
                              "ref": "ANSI/APSP/ICC-5"},
    }
    if H >= 3.0 and t < 0.30:
        checks["espesor_muro"] = {"ok": False, "ref": "ACI 350-06 14.6.1: >= 300 mm con H >= 3 m"}
    out = {
        "ok": all(c["ok"] for c in checks.values()),
        "length": length, "width": width, "shallow": shallow, "deep": deep,
        "freeboard": freeboard, "wall_height": _r(H, 3),
        "volume_m3": _r(volumen, 2), "surface_m2": _r(length * width, 2),
        "turnover_h": turnover_hours, "flow_m3_h": _r(q_h, 2), "flow_L_s": _r(q * 1000, 2),
        "filter": {"type": "arena alta tasa", "area_m2": _r(area_filtro, 3),
                   "diameter_m": _r(d_filtro, 2), "rate_m3_h_m2": TASA_FILTRO_ARENA,
                   "ref": "NSF/ANSI 50 (tasa de diseño del fabricante)"},
        "suction_pipe": succion, "return_pipe": retorno,
        "main_drains": {"count": 2, "min_separation_m": SEPARACION_DRENES,
                        "ref": "ANSI/APSP/ICC-7: dos drenes, a >= 0.91 m, con rejilla certificada"},
        "returns": {"count": returns, "flow_each_L_s": _r(q_boquilla * 1000, 2), "ref": "[PROY]"},
        "skimmers": {"count": skimmers, "ref": "[PROY]"},
        "pump": {"flow_m3_h": _r(q_h, 2),
                 "note": "Elegir la bomba con su curva para ese gasto y la carga total del "
                         "sistema (filtro + tuberías + accesorios); no se supone potencia."},
        "wall": {"thickness": t, "faces": caras, "cover": cover},
        "slab": {"thickness": slab_thickness, "bars": losa, "cover": cover},
        "fc": fc, "fy": fy, "checks": checks, "warnings": avisos,
        "turnover_ref": "Recirculación del volumen en 6 h: práctica residencial [PROY]",
    }
    return out


# ================================================================ dibujo

def _capas():
    layers.ensure(L_ALB, 7, 50)
    layers.ensure(L_ALB_HID, 152, 25)
    layers.ensure(L_ALB_ARM, 7, 35)
    layers.ensure_text_style()


def _rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def draw_pool_plan(p: dict[str, Any], x0: float, y0: float, upm: float,
                   deck: float = 1.0, equipment_room: Optional[list[float]] = None,
                   title: Optional[str] = None, text_mm: float = 2.0) -> dict[str, Any]:
    """Planta: vaso (con el espesor del muro), andador, remate, escalones de
    acceso, 2 drenes de fondo, desnatador, retornos, marcas de profundidad,
    la pendiente del fondo, la red hasta el cuarto de máquinas y cotas.
    (x0, y0): esquina inferior izquierda del ESPEJO de agua."""
    _capas()
    with acad.lote():
        r = _planta(p, x0, y0, upm, deck, equipment_room, title, text_mm)
    return acad.resolver(r)


def _planta(p, x0, y0, upm, deck, cm, title, text_mm):
    L, W, t = p["length"], p["width"], p["wall"]["thickness"]
    x1, y1 = x0 + L, y0 + W
    h = text_mm * upm
    # Andador (contorno exterior) y muro del vaso achurado.
    dt._poly(_rect(x0 - t - deck, y0 - t - deck, x1 + t + deck, y1 + t + deck), L_ALB, 35,
             closed=True)
    ext = dt._poly(_rect(x0 - t, y0 - t, x1 + t, y1 + t), L_ALB, 50, closed=True)
    inn = dt._poly(_rect(x0, y0, x1, y1), L_ALB, 50, closed=True)
    acad.call("create_hatch", {"boundaryHandle": ext, "islandHandles": [inn], "pattern": "ANSI31",
                               "scale": mat_mod.hatch_scale("ANSI31", 1.2, 0.0, upm),
                               "angleDeg": 0.0, "layer": L_ALB, "lineweight": 9,
                               "colorIndex": 8})
    # Espejo de agua: rayado horizontal tenue.
    acad.call("create_hatch", {"boundaryHandle": inn, "pattern": "LINE",
                               "scale": mat_mod.hatch_scale("LINE", 6.0, 0.0, upm),
                               "angleDeg": 0.0, "layer": L_ALB, "lineweight": 5,
                               "colorIndex": 152})
    # Escalones de acceso en el extremo bajo (x0): 3 de 0.30 a 0.40 de huella.
    for k in range(1, 4):
        xe = x0 + 0.35 * k
        dt._poly([(xe, y0 + W * 0.25), (xe, y0 + W * 0.75)], L_ALB, 25)
    dt._poly(_rect(x0, y0 + W * 0.25, x0 + 1.05, y0 + W * 0.75), L_ALB, 25, closed=True)
    # Drenes de fondo (2, separados), en el punto más hondo (x1).
    xd = x1 - 0.60
    sep = max(1.2, p["main_drains"]["min_separation_m"])
    drenes = [(xd, y0 + W / 2 - sep / 2), (xd, y0 + W / 2 + sep / 2)]
    for cx, cy in drenes:
        dt._poly(_rect(cx - 0.15, cy - 0.15, cx + 0.15, cy + 0.15), L_ALB_HID, 25, closed=True)
        dt._poly([(cx - 0.15, cy), (cx + 0.15, cy)], L_ALB_HID, 13)
    # Desnatador en el muro largo cerca del extremo hondo; retornos en el otro muro.
    sk = (x1 - 1.2, y1)
    dt._poly(_rect(sk[0] - 0.25, y1, sk[0] + 0.25, y1 + t + 0.30), L_ALB_HID, 35, closed=True)
    retornos = [(x0 + L * (k + 1) / (p["returns"]["count"] + 1), y0)
                for k in range(p["returns"]["count"])]
    for rx, ry in retornos:
        dt.dot(rx, ry + 0.05, 0.05, L_ALB_HID, 152)
    # Pendiente del fondo y marcas de profundidad.
    dt.text(f"PROF. {p['shallow']:.2f} m", x0 + 1.25, y0 + W * 0.5 + 0.5 * h, h * 1.2,
            layer=L_ALB)
    dt.text(f"PROF. {p['deep']:.2f} m", x1 - 2.4, y0 + W * 0.5 + 1.3 * h, h * 1.2, layer=L_ALB)
    xa, xb = x0 + L * 0.35, x0 + L * 0.65
    dt._poly([(xa, y0 + W * 0.30), (xb, y0 + W * 0.30)], L_ALB, 18)
    dt._poly([(xb - 0.15, y0 + W * 0.30 + 0.06), (xb, y0 + W * 0.30), (xb - 0.15, y0 + W * 0.30 - 0.06)],
             L_ALB, 18)
    dt.text("PENDIENTE DEL FONDO", xa, y0 + W * 0.30 + 0.6 * h, h, layer=L_ALB)
    # Red: succión (drenes + desnatador) al cuarto de máquinas y retorno.
    if cm:
        ex0, ey0, ex1, ey1 = cm
        dt._poly(_rect(ex0, ey0, ex1, ey1), L_ALB, 50, closed=True)
        dt.text("CUARTO DE MÁQUINAS", ex0 + 0.1, ey1 - 0.15 - h, h, layer=L_ALB)
        ent = ((ex0 + ex1) / 2, ey0)
        layers.ensure("OCULTO", 8, 13, layers.LT_OCULTO)
        cy_c = y1 + t + deck * 0.5
        dt._poly([drenes[1], (drenes[1][0], cy_c), (ent[0], cy_c), ent], L_ALB_HID, 35)
        dt._poly([(sk[0], y1 + t + 0.30), (sk[0], cy_c)], L_ALB_HID, 35)
        cy_r = y0 - t - deck * 0.5
        dt._poly([(ent[0] + 0.3, ey0), (ent[0] + 0.3, cy_c + 0.15)], L_ALB_HID, 25)
        dt._poly([(ent[0] + 0.3, cy_c + 0.15), (x1 + t + deck * 0.5, cy_c + 0.15),
                  (x1 + t + deck * 0.5, cy_r), (retornos[0][0], cy_r)], L_ALB_HID, 25)
        for rx, _ry in retornos:
            dt._poly([(rx, cy_r), (rx, y0)], L_ALB_HID, 25)
    # Cotas.
    dt.chain([x0 - t - deck, x0 - t, x0, x1, x1 + t, x1 + t + deck], "bottom",
             y0 - t - deck, upm)
    dt.chain([y0 - t - deck, y0 - t, y0, y1, y1 + t, y1 + t + deck], "left",
             x0 - t - deck, upm)
    # Llamadas.
    items = [((x0 + 0.5, y0 + W * 0.55), "ESCALONES DE ACCESO h=0.30 (HUELLA 0.35)"),
             (drenes[0], f"2 DRENES DE FONDO ANTIATRAPAMIENTO, SEP. >= {SEPARACION_DRENES:.2f} m "
                         "(ANSI/APSP/ICC-7)"),
             ((sk[0], y1 + t), f"DESNATADOR ({p['skimmers']['count']})"),
             ((retornos[-1][0], y0 + 0.05), f"{p['returns']['count']} BOQUILLAS DE RETORNO"),
             ((x1 + t / 2, y0 + W * 0.2), f"MURO DE CONCRETO e={p['wall']['thickness'] * 100:.0f} cm"),
             ((x1 + t + deck * 0.5, y0 + W * 0.8), f"ANDADOR ANTIDERRAPANTE {deck:.2f} m"),
             ((x1 + t + deck * 0.5, y0 - t - deck * 0.5),
              f"RETORNO PVC {p['return_pipe']['nominal']} CED. 40"),
             ((x1 + t + deck * 0.2, y1 + t + deck * 0.5),
              f"SUCCIÓN PVC {p['suction_pipe']['nominal']} CED. 40")]
    llam = dt.callouts(items, "right", x1 + t + deck + 3 * upm + 0.6, upm,
                       (y0 - t - deck - 0.5, y1 + t + deck + 1.0), text_mm=text_mm, max_chars=44)
    tit = sym_mod.create_view_title(x0 - t - deck - 0.6, y1 + t + deck + (2.6 if cm else 0.8),
                                    title or "PLANTA DE ALBERCA",
                                    scale_text=f"ESC. 1:{round(upm * 1000)}",
                                    height=3.5 * upm, spaced=False)
    caja = [x0 - t - deck - 0.6 - 25 * upm, y0 - t - deck - 25 * upm, llam["box"][2],
            (tit.get("box") or [0, 0, 0, y1 + 3])[3]]
    if cm:
        caja[2] = max(caja[2], cm[2])
        caja[3] = max(caja[3], cm[3] + 0.5)
    return {"box": caja}


def draw_pool_section(p: dict[str, Any], x0: float, y_water: float, upm: float,
                      deck: float = 1.0, title: Optional[str] = None,
                      text_mm: float = 2.0) -> dict[str, Any]:
    """Corte longitudinal: terreno, plantilla, losa de fondo en pendiente,
    muros con su doble parrilla, remate, andador, espejo de agua, dren de
    fondo con su succión, retorno y desnatador, cotas y niveles.
    (x0, y_water): inicio del espejo de agua (extremo bajo) y su nivel."""
    _capas()
    with acad.lote():
        r = _corte(p, x0, y_water, upm, deck, title, text_mm)
    return acad.resolver(r)


def _corte(p, x0, yw, upm, deck, title, text_mm):
    L, t = p["length"], p["wall"]["thickness"]
    ts = p["slab"]["thickness"]
    fb = p["freeboard"]
    yr = yw + fb                                   # remate / andador
    yf0 = yw - p["shallow"]                        # fondo extremo bajo
    yf1 = yw - p["deep"]                           # fondo extremo hondo
    x1 = x0 + L
    h = text_mm * upm
    cov = p["wall"]["cover"]
    e_pl = 0.05
    # Concreto del vaso: un solo polígono (muros + losa en pendiente).
    vaso = [[x0 - t, yf0 - ts], [x1 + t, yf1 - ts], [x1 + t, yr], [x1, yr], [x1, yf1],
            [x0, yf0], [x0, yr], [x0 - t, yr]]
    pieza = mat_mod.draw_material(vaso, "concreto", layer=L_ALB, scale=upm)
    plant = mat_mod.draw_material([[x0 - t, yf0 - ts - e_pl], [x1 + t, yf1 - ts - e_pl],
                                   [x1 + t, yf1 - ts], [x0 - t, yf0 - ts]],
                                  "concreto_pobre", layer=L_ALB, scale=upm, lineweight=35)
    # Andador a los dos lados (firme de 10 cm sobre relleno).
    for a, b in ((x0 - t - deck, x0 - t), (x1 + t, x1 + t + deck)):
        mat_mod.draw_material(_rect(a, yr - 0.10, b, yr), "concreto", layer=L_ALB, scale=upm,
                              lineweight=35)
    # Terreno: franja a lo largo de las caras exteriores y bajo la plantilla.
    corte = [(x0 - t - deck - 0.6, yr - 0.10), (x0 - t, yr - 0.10), (x0 - t, yf0 - ts - e_pl),
             (x1 + t, yf1 - ts - e_pl), (x1 + t, yr - 0.10), (x1 + t + deck + 0.6, yr - 0.10)]
    franja = dt.offset_open(corte, 0.30)
    borde = []
    for a, b in zip(franja, franja[1:]):
        borde += dt.jagged_points(a, b, upm, amp_mm=1.2, step_mm=3.0, seed=11)[:-1]
    borde.append(franja[-1])
    bh = acad.call("create_polyline", {"points": [list(q) for q in corte + list(reversed(borde))],
                                       "closed": True, "layer": L_ALB, "lineweight": 0,
                                       "colorIndex": 8})["handle"]
    mat_mod.apply_hatch(bh, mat_mod.resolve_material("tierra"), L_ALB, upm)
    acad.call("delete_entity", {"handle": bh})
    # Agua.
    agua = dt._poly([(x0, yw), (x1, yw), (x1, yf1), (x0, yf0)], L_ALB_HID, 0, closed=True,
                    color=152)
    acad.call("create_hatch", {"boundaryHandle": agua, "pattern": "LINE",
                               "scale": mat_mod.hatch_scale("LINE", 5.0, 0.0, upm),
                               "angleDeg": 0.0, "layer": L_ALB_HID, "lineweight": 5,
                               "colorIndex": 152})
    dt._poly([(x0, yw), (x1, yw)], L_ALB_HID, 35, color=152)
    for k in range(3):                              # símbolo de nivel de agua
        dt._poly([(x0 + 0.6 + k * 0.08 - 0.1 + k * 0.02, yw - 0.06 - k * 0.05),
                  (x0 + 0.6 + 0.3 - k * 0.1, yw - 0.06 - k * 0.05)], L_ALB_HID, 13, color=152)
    # Escalones de acceso en el extremo bajo.
    esc = []
    yy = yw
    for k in range(3):
        esc += [(x0 + 0.35 * k, yy - 0.30), (x0 + 0.35 * (k + 1), yy - 0.30)]
        yy -= 0.30
    dt._poly([(x0, yw)] + esc + [(x0 + 1.05, yf0 - 0.02)], L_ALB, 35)
    # Armado: doble parrilla en muros (vista en corte: varillas verticales
    # como líneas con gancho a la losa; horizontales de punta) y en la losa.
    fi, fe = p["wall"]["faces"]["interior"], p["wall"]["faces"]["exterior"]
    for xm, sgn in ((x0, -1), (x1, 1)):
        yb = (yf0 if xm == x0 else yf1) - ts
        for cara, arm in (("i", fi), ("e", fe)):
            xb = xm + sgn * (cov + arm["db"] / 2) if cara == "i" else \
                xm + sgn * (t - cov - arm["db"] / 2)
            rebar.create_rebar([[xb, yr - cov], [xb, yb + cov]], arm["db"], end_hook="90",
                               hook_side="left" if (sgn > 0) == (cara == "i") else "right",
                               hook_extension=0.30, layer=L_ALB_ARM, width=arm["db"])
            yy = yb + ts + 0.10
            while yy < yr - 0.08:
                dt.dot(xb - sgn * arm["db"] * 1.1 * (1 if cara == "i" else -1), yy, 0.006,
                       L_ALB_ARM, 7)
                yy += arm["spacing"]
    lb = p["slab"]["bars"]
    for off in (cov + lb["db"] / 2, ts - cov - lb["db"] / 2):
        rebar.create_rebar([[x0 - t + cov, yf0 - ts + off], [x1 + t - cov, yf1 - ts + off]],
                           lb["db"], layer=L_ALB_ARM, width=lb["db"])
    # Dren de fondo y succión; retorno en el muro; desnatador arriba.
    dx = x1 - 0.60
    yfd = yf1 + (yf0 - yf1) * 0.60 / L
    dt._poly(_rect(dx - 0.15, yfd - 0.12, dx + 0.15, yfd), L_ALB_HID, 25, closed=True)
    dt._poly([(dx, yfd - 0.12), (dx, yfd - ts - 0.25), (x1 + t + deck * 0.6, yfd - ts - 0.25),
              (x1 + t + deck * 0.6, yr - 0.10)], L_ALB_HID, 35)
    dt._poly([(x0 - t - deck * 0.6, yr - 0.10), (x0 - t - deck * 0.6, yw - 0.45),
              (x0, yw - 0.45)], L_ALB_HID, 25)
    dt._poly(_rect(x1 - 0.02, yw - 0.20, x1 + t + 0.30, yw + 0.05), L_ALB_HID, 25, closed=True)
    # Cotas y niveles.
    dt.chain([x0 - t, x0, x1, x1 + t], "bottom", yf1 - ts - e_pl - 0.30, upm)
    dt.chain([yf0 - ts - e_pl, yf0 - ts, yf0, yw, yr], "left", x0 - t - deck - 0.6, upm)
    dt.chain([yf1 - ts - e_pl, yf1 - ts, yf1, yw, yr], "right", x1 + t + deck + 0.6, upm,
             total=False)
    sym_mod.create_level_mark(x=x0 - t - deck * 0.5, y=yr, elevation=0.0, prefix="N.P.T.",
                              side="left", height=h)
    sym_mod.create_level_mark(x=x0 + L * 0.5, y=yw, elevation=-fb, prefix="N.A.",
                              side="right", height=h)
    # Llamadas.
    x_ll = x1 + t + deck + 0.6 + 22 * upm
    items = [
        ((x0 + L * 0.4, yw - 0.3), f"ESPEJO DE AGUA, VOLUMEN {p['volume_m3']:.1f} m³"),
        ((x1 + t / 2, yr - 0.4), f"MURO DE CONCRETO f'c={p['fc']:.0f} kg/cm² "
                                 f"e={t * 100:.0f} cm, IMPERMEABLE"),
        ((x1 + cov, yr - 0.7), f"CARA INTERIOR {fi['text']} VERTICAL CON GANCHO A LA LOSA"),
        ((x1 + t - cov, yr - 1.0), f"CARA EXTERIOR {fe['text']}"),
        ((x0 + L * 0.7, yf1 + (yf0 - yf1) * 0.3 - ts / 2), f"LOSA DE FONDO e={ts * 100:.0f} cm, "
                                                          f"DOBLE PARRILLA {lb['text']} A.S."),
        ((x0 + L * 0.5, yf0 + (yf1 - yf0) * 0.5 - ts - e_pl / 2),
         "PLANTILLA f'c=100 kg/cm² e=5 cm"),
        ((dx, yfd - 0.06), "DREN DE FONDO CON REJILLA ANTIATRAPAMIENTO (2 PZAS.)"),
        ((x1 + t + 0.15, yw - 0.07), "DESNATADOR"),
        ((x0 - t - deck * 0.6, yw - 0.45), f"RETORNO PVC {p['return_pipe']['nominal']}"),
        ((x0 + 0.5, yw - 0.45), "ESCALONES DE ACCESO h=0.30"),
        ((x1 + t + deck * 0.5, yr - 0.05), "ANDADOR ANTIDERRAPANTE SOBRE RELLENO COMPACTADO"),
        ((x1 + t + 0.15, yf1 - ts - 0.2), "TERRENO NATURAL (VER E.M.S.: NIVEL FREÁTICO)"),
    ]
    llam = dt.callouts(items, "right", x_ll, upm, (yf1 - ts - 1.0, yr + 0.6), text_mm=text_mm,
                       max_chars=46)
    tit = sym_mod.create_view_title(x0 - t - deck - 0.6 - 25 * upm, yr + 1.2,
                                    title or "CORTE LONGITUDINAL DE ALBERCA",
                                    scale_text=f"ESC. 1:{round(upm * 1000)}",
                                    height=3.5 * upm, spaced=False)
    return {"box": [x0 - t - deck - 0.6 - 30 * upm, yf1 - ts - e_pl - 0.30 - 30 * upm,
                    llam["box"][2], (tit.get("box") or [0, 0, 0, yr + 2])[3]],
            "concrete": pieza["handle"], "lean": plant["handle"]}
