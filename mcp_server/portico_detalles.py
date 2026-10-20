"""Detalles del portico y la barda: corte y armado de la trabe curva, pilastras,
cimentacion. Complementa portico_dibujo (alzados y plantas). Todo sale de los
dicts de portico_arco; ningun numero se escribe a mano.
"""
from __future__ import annotations

import math
from typing import Any

import annotation as ann
import autocad_client as acad
import detalle as dt
import materials
import prim
import rebar
import zapatas as zap
from portico_dibujo import (L_BLK, L_CON, L_EJE, L_OCU, L_REJA, L_TXT, _arco_cad, _capas, _db, _rect)

LAYER_ARMADO = rebar.LAYER_REBAR
LW_ARMADO = rebar.LW_REBAR


def y_nucleo_top(g: dict[str, Any], d: dict[str, Any]) -> float:
    """Cota (sobre el piso) a la que termina el nucleo de la pilastra: llega al bloque del
    capitel, por encima de la dala de remate del fronton."""
    return g["top_ends_h"]


def _r3(v) -> float:
    return round(float(v), 3)


# ----------------------------------------------------------- corte de la trabe

def corte_trabe(d: dict[str, Any], x: float, y: float, upm: float, fc: float = 250.0) -> dict[str, Any]:
    """Seccion radial de la trabe curva TC-1 con su forro de block y su armado.
    (x, y) = esquina inferior izquierda del contorno terminado."""
    _capas()
    v = d["viga"]
    b, h = v["b"], v["h"]
    t, ap = 0.10, 0.02
    ap_bot, ap_top = v["zona_apoyos"]["bottom"], v["zona_apoyos"]["top"]
    est_b = v["zona_apoyos"]["stirrups"]["bar"]
    xc, yc = x + ap + t, y + ap
    with acad.lote():
        for xb in (x + ap, xc + b):
            materials.draw_material([(xb, yc), (xb + t, yc), (xb + t, yc + h), (xb, yc + h)], "block",
                                    layer=L_BLK, scale=upm)
        xw = x + 2 * (ap + t) + b
        prim.poly([(x, y), (xw, y), (xw, y + h + 2 * ap), (x, y + h + 2 * ap)], L_CON, True, 25)
    sec = rebar.create_column_section(
        x=xc, y=yc, width=b, depth=h, bars_top_bottom=max(0, ap_top["count"] - 2), bars_left_right=0,
        bar_diameter=_db(ap_bot["bar"]), cover=0.04, stirrup_diameter=_db(est_b))
    ann.create_dimension_chain(positions=[x, x + ap, xc, xc + b, xc + b + t, xw], side="bottom",
                               reference=y, scale=upm)
    ann.create_dimension_chain(positions=[y, yc, yc + h, y + h + 2 * ap], side="right", reference=xw, scale=upm)
    items = [((xc + b / 2, yc + h - 0.06), f"LECHO SUP. {ap_top['text']}"),
             ((xc + b / 2, yc + 0.06), f"LECHO INF. {ap_bot['text']}"),
             ((xc + b - 0.04, yc + h / 2), f"EST. {est_b} (VER ARMADO)"),
             ((xc + b + t / 2, yc + h * 0.78), "BLOCK HUECO 10x20x40"),
             ((xc + b / 2, yc + h * 0.30), f"CONCRETO f'c = {fc:.0f} kg/cm²")]
    dt.callouts(items, "left", x, upm)
    return {"box": [x - 75 * upm, y - 22 * upm, xw + 18 * upm, y + h + 2 * ap + 8 * upm], "section": sec}


# ----------------------------------------------------------- armado de la trabe curva

def _arco_pts(cx, cy, r, x0, x1, n=60):
    out = []
    for k in range(n + 1):
        xx = x0 + (x1 - x0) * k / n
        out.append((xx, cy + math.sqrt(max(r * r - (xx - cx) ** 2, 0.0))))
    return out


def armado_trabe(d: dict[str, Any], x: float, y: float, upm: float, fc: float = 250.0,
                 fy: float = 4200.0) -> dict[str, Any]:
    """TC-1 desarrollada: contorno, lechos con su gancho dentro del nucleo de la
    pilastra y estribos radiales (separacion de apoyos en cada extremo, la del
    centro en el resto). (x, y) = centro del claro a nivel de piso. Devuelve el
    numero REAL de estribos y la longitud desarrollada de cada lecho."""
    _capas()
    g, v = d["geometria"], d["viga"]
    h, Lh, P, core = v["h"], g["S"] / 2.0, d["pilastra_terminada"], d["nucleo"]
    R, yc = g["R"], y + g["yc"]
    th = 2.0 * upm
    cov = 0.04 + _db(v["zona_apoyos"]["stirrups"]["bar"])
    db_b, db_t = _db(v["zona_apoyos"]["bottom"]["bar"]), _db(v["zona_apoyos"]["top"]["bar"])
    r_inf, r_sup = R + cov + db_b / 2.0, R + h - cov - db_t / 2.0
    ldh = zap.ldh_tension(db_t, fc * zap.KGCM2_A_MPA, fy * zap.KGCM2_A_MPA)
    gancho = max(ldh, 12 * db_t)
    xcore0, xcore1 = Lh + (P - core) / 2.0, Lh + (P + core) / 2.0
    x_fin = xcore1 - 0.04 - db_t
    s_ap, s_ce = v["zona_apoyos"]["stirrups"]["spacing"], v["zona_centro"]["stirrups"]["spacing"]
    z_ap = v["zona_apoyos"]["stirrups"]["zone_length"]
    Rc = R + h / 2.0
    Lb = xcore0                                                    # la trabe llega a la cara del nucleo
    phi0 = math.asin(Lb / Rc)
    largo = 2 * Rc * phi0
    ini, s = [], 0.05
    while s <= z_ap + 1e-9:
        ini.append(round(s, 4))
        s += s_ap
    centro, s = [], ini[-1] + s_ce
    while s < largo - z_ap - 1e-9:
        centro.append(round(s, 4))
        s += s_ce
    fin = [round(largo - s_, 4) for s_ in ini]
    pos = sorted(set(ini + centro + fin))
    with acad.lote():
        a_i, a_e = _arco_pts(x, yc, R, x - Lb, x + Lb), _arco_pts(x, yc, R + h, x - Lb, x + Lb)
        prim.poly(a_i + list(reversed(a_e)), L_CON, True, 35)
        for lado in (-1, 1):
            xa, xb = sorted((x + lado * xcore0, x + lado * xcore1))
            _rect(xa, y + g["spring_h"] - 1.2, xb, y + g["spring_h"] + 0.70, L_OCU, 13)
        for r_b, db_, larg_g in ((r_inf, db_b, 12 * db_b), (r_sup, db_t, gancho)):
            pts = _arco_pts(x, yc, r_b, x - x_fin, x + x_fin, 80)
            gi = [(pts[0][0], pts[0][1] - larg_g), pts[0]]
            gd = [pts[-1], (pts[-1][0], pts[-1][1] - larg_g)]
            prim.poly(gi + pts[1:-1] + gd, LAYER_ARMADO, False, LW_ARMADO)
        for s_ in pos:
            ph = -phi0 + s_ / Rc
            p0 = (x + (R + cov * 0.5) * math.sin(ph), yc + (R + cov * 0.5) * math.cos(ph))
            p1 = (x + (R + h - cov * 0.5) * math.sin(ph), yc + (R + h - cov * 0.5) * math.cos(ph))
            prim.line(p0, p1, LAYER_ARMADO, 18)
        prim.line((x, yc + R - 0.35), (x, yc + R + h + 0.35), L_TXT, 35)
        dt.text("A", x - 0.09, yc + R - 0.35 - 0.20, 2.5 * th, L_TXT)
        dt.text("A", x - 0.09, yc + R + h + 0.40, 2.5 * th, L_TXT)
    base_y = y + g["spring_h"] - 1.25
    ann.create_dimension_chain(positions=[x - Lh, x + Lh], side="bottom", reference=base_y, scale=upm)
    items = [((x - 0.8, yc + math.sqrt(r_sup ** 2 - 0.64)), f"LECHO SUP. {v['zona_apoyos']['top']['text']}"),
             ((x + 0.5, yc + math.sqrt(r_inf ** 2 - 0.25)), f"LECHO INF. {v['zona_apoyos']['bottom']['text']}")]
    dt.callouts(items, "left", x - Lh - 0.9, upm)
    notas = [f"EST. {v['zona_apoyos']['stirrups']['bar']} @ {s_ap * 100:.0f} cm EN {z_ap:.2f} m DE CADA EXTREMO Y",
             f"@ {s_ce * 100:.0f} cm EN EL CENTRO: {len(pos)} PIEZAS EN TOTAL.",
             f"LECHOS ANCLADOS EN EL NUCLEO DE LA PILASTRA CON GANCHO DE {gancho * 100:.0f} cm.",
             f"LONGITUD DEL EJE DEL ARCO: {largo:.2f} m."]
    y_n = base_y - 16 * upm
    for i, tx in enumerate(notas):
        dt.text(tx, x - Lh, y_n - i * 3.2 * th, th, L_TXT)
    box = [x - Lh - 60 * upm, y_n - 4 * 3.2 * th, x + Lh + 18 * upm, yc + R + h + 0.9]
    ang_i, ang_s = math.asin(x_fin / r_inf), math.asin(x_fin / r_sup)
    return {"box": box, "stirrups": len(pos), "stirrup_positions_m": pos, "arc_length_m": _r3(largo),
            "hook_m": _r3(gancho),
            "bar_len_inf_m": _r3(2 * r_inf * ang_i + 2 * 12 * db_b),
            "bar_len_sup_m": _r3(2 * r_sup * ang_s + 2 * gancho)}


# ----------------------------------------------------------- pilastra del porton (P-1)

def armado_pilastra(d: dict[str, Any], x: float, y_piso: float, upm: float, fc: float = 250.0,
                    fy: float = 4200.0, nombre: str = "P-1") -> dict[str, Any]:
    """Elevacion de la pilastra (nucleo) desde la cara superior de la zapata hasta el remate,
    con los estribos y la zona de confinamiento, y su seccion a la derecha."""
    _capas()
    g, p, z = d["geometria"], d["pilastra"], d["zapata"]
    core = d["nucleo"]
    y_zap_sup = y_piso - (z["depth"] - z["h"] - 0.05 + 0.05) + 0.0 - 0.0
    y_zap_sup = y_piso - z["depth"] + z["h"] + 0.05             # cara superior de la zapata (sobre plantilla)
    y_top = y_piso + y_nucleo_top(g, d)
    H = y_top - y_zap_sup
    db = _db(p["bars"]["bar"])
    db_e = _db(p["stirrups"]["bar"])
    th = 2.0 * upm
    ldh = zap.ldh_tension(db, fc * zap.KGCM2_A_MPA, fy * zap.KGCM2_A_MPA)
    gancho_pie = max(ldh, 0.20)
    n_int = max(0, p["bars"]["count"] // 4 - 1)                 # barras intermedias por cara
    xe = x - core / 2
    el = rebar.create_rebar_elevation(
        x=xe, y=y_zap_sup, width=core, height=H, stirrup_spacing=p["stirrups"]["spacing"],
        bars_interior=n_int, bar_diameter=db, stirrup_diameter=db_e, cover=0.04, depth=core,
        orientation="vertical", extend_start=0.0, extend_end=0.0,
        confinement_length=p["stirrups"]["conf_length"], confinement_spacing=p["stirrups"]["conf_spacing"])
    with acad.lote():
        # cara superior de la zapata y N.T.N.
        prim.line((x - 0.9, y_zap_sup), (x + 0.9, y_zap_sup), L_CON, 35)
        prim.line((x - 0.9, y_piso), (x + 0.9, y_piso), L_CON, 25)
        # patas de las barras dentro de la zapata
        for xb in (xe + 0.04 + db / 2, xe + core - 0.04 - db / 2):
            lado = 1 if xb > x else -1
            prim.poly([(xb, y_zap_sup + 0.05), (xb, y_zap_sup - z["h"] + 0.075 + db / 2 + 0.02),
                       (xb + lado * gancho_pie, y_zap_sup - z["h"] + 0.075 + db / 2 + 0.02)],
                      LAYER_ARMADO, False, LW_ARMADO)
        prim.line((x - 0.9, y_zap_sup - z["h"] - 0.05), (x + 0.9, y_zap_sup - z["h"] - 0.05), L_OCU, 13)
        # eje
        prim.line((x, y_zap_sup - 0.6), (x, y_top + 0.4), L_EJE, 13)
    # corte B-B a la derecha: caja de block 90 x 60 con el nucleo de concreto al centro
    xs = x + core / 2 + 32 * upm
    t = 0.10
    P, Pd = d["pilastra_terminada"], d["pilastra_prof"]
    ys = y_piso + 1.0
    with acad.lote():
        for (a0, b0, a1, b1) in ((xs, ys, xs + t, ys + Pd), (xs + P - t, ys, xs + P, ys + Pd),
                                 (xs + t, ys, xs + P - t, ys + t), (xs + t, ys + Pd - t, xs + P - t, ys + Pd)):
            materials.draw_material([(a0, b0), (a1, b0), (a1, b1), (a0, b1)], "block", layer=L_BLK, scale=upm)
        prim.poly([(xs, ys), (xs + P, ys), (xs + P, ys + Pd), (xs, ys + Pd)], L_CON, True, 25)
    xcn, ycn = xs + (P - core) / 2.0, ys + (Pd - core) / 2.0
    sec = rebar.create_column_section(
        x=xcn, y=ycn, width=core, depth=core,
        bars_top_bottom=n_int, bars_left_right=n_int, bar_diameter=db, cover=0.04, stirrup_diameter=db_e)
    ann.create_dimension_chain(positions=[xs, xcn, xcn + core, xs + P], side="bottom",
                               reference=ys, scale=upm)
    dt.text(f"CORTE B-B ({nombre})", xs, ys + Pd + 3 * th, 1.2 * th, L_TXT)
    items = [((xe + 0.04, y_top - 0.40), f"{p['bars']['text']} (ρ = {p['rho'] * 100:.2f} %)"),
             ((xe + core / 2, y_top - 1.0), f"EST. {p['stirrups']['bar']} @ {p['stirrups']['spacing'] * 100:.0f} cm"),
             ((xe + core - 0.05, y_top - 0.20),
              f"@ {p['stirrups']['conf_spacing'] * 100:.0f} cm EN {p['stirrups']['conf_length']:.2f} m DE CADA EXTREMO"),
             ((xe + core / 2, y_zap_sup + 0.10), f"PATAS DE {gancho_pie * 100:.0f} cm EN LA ZAPATA")]
    dt.callouts(items, "left", xe - 0.05, upm, text_mm=2.0)
    ann.create_dimension_chain(positions=[y_zap_sup, y_piso, y_piso + g["spring_h"], y_top], side="right",
                               reference=xe + core + 0.02, scale=upm)
    box = [x - 75 * upm - 1.0, y_zap_sup - 0.9, xs + P + 18 * upm, y_top + 0.8]
    return {"box": box, "elevation": el, "section": sec, "height_m": _r3(H), "pata_m": _r3(gancho_pie),
            "bar_len_m": _r3(H + 0.04 + gancho_pie - 0.04 + z["h"] - 0.075)}
