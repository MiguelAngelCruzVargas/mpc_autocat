"""Portico y barda, segunda parte: alzado estructural, corte del fronton, pilastra y
corte de la barda, planta de cimentacion."""
from __future__ import annotations

import math
from typing import Any

import annotation as ann
import autocad_client as acad
import detalle as dt
import layers
import materials
import portico_arco as pa
import prim
import rebar
import zapatas as zap
from portico_detalles import LAYER_ARMADO, LW_ARMADO, _r3, y_nucleo_top
from portico_dibujo import (L_BLK, L_CON, L_EJE, L_OCU, L_TXT, _arco_cad, _capas, _db, _rect, _arco_sobre)


def _marca(x, y, texto, h, layer=L_TXT):
    """Globo con la marca de un elemento (P-1, TC-1...)."""
    r = 0.9 * h
    prim.circle((x, y), r, layer, 25)
    dt.text(texto, x, y - 0.35 * h, 0.8 * h, layer, justify="center")


# ----------------------------------------------------------- alzado estructural

def alzado_estructural(d: dict[str, Any], x: float, y: float, upm: float) -> dict[str, Any]:
    """El esqueleto: nucleos de pilastra (P-1), trabe curva (TC-1), castillos (K-1) y
    dala de remate (DR-1) del fronton, con sus marcas. (x, y) = centro del claro."""
    _capas()
    g, v, fr = d["geometria"], d["viga"], d["fronton"]
    S, P, core = g["S"], d["pilastra_terminada"], d["nucleo"]
    Lh, xo = S / 2.0, S / 2.0 + P
    R, h, yc = g["R"], g["beam_h"], y + g["yc"]
    th = 2.0 * upm
    t = fr["espesor"]
    y_cor = y + y_nucleo_top(g, d)
    with acad.lote():
        prim.line((x - xo - 1.0, y), (x + xo + 1.0, y), L_CON, 50)
        # contorno terminado, fino
        for lado in (-1, 1):
            xi, xe = x + lado * Lh, x + lado * xo
            xa, xb = sorted((xi, xe))
            _rect(xa, y, xb, y + g["top_ends_h"] - 0.20, L_OCU, 13)
        prim.poly([(x + dx_, y + pa.y_top(g, dx_)) for dx_ in [-xo + 0.05 + (2 * xo - 0.1) * k / 60 for k in range(61)]],
                  L_OCU, False, 13)
        # nucleos P-1
        for lado in (-1, 1):
            xm = x + lado * (Lh + P / 2)
            _rect(xm - core / 2, y, xm + core / 2, y_cor, L_CON, 50)
        # trabe curva TC-1
        Lb = Lh + (P - core) / 2.0                                # la trabe llega a la cara del nucleo
        a_i = _arco_sobre(x, yc, R, x - Lb, x + Lb, 70)
        a_e = _arco_sobre(x, yc, R + h, x - Lb, x + Lb, 70)
        prim.poly(a_i + list(reversed(a_e)), L_CON, True, 50)
        # castillos K-1
        for xx in fr["castillos_x"]:
            y0_ = yc + math.sqrt((R + h) ** 2 - xx ** 2)
            y1_ = y + pa.y_top(g, xx) - t
            _rect(x + xx - t / 2, y0_, x + xx + t / 2, y1_, L_CON, 50)
        # dala de remate DR-1 (de pilastra a pilastra, siguiendo la cornisa)
        xs_d = [-(Lh + P / 2) + (2 * Lh + P) * k / 70 for k in range(71)]
        a_d0 = [(x + dx_, y + pa.y_top(g, dx_) - t) for dx_ in xs_d]
        a_d1 = [(x + dx_, y + pa.y_top(g, dx_)) for dx_ in xs_d]
        prim.poly(a_d0 + list(reversed(a_d1)), L_CON, True, 50)
        prim.line((x, y - 0.4), (x, y + g["top_crown_h"] + 0.5), L_EJE, 13)
        for lado in (-1, 1):
            xe = x + lado * (Lh + P / 2)
            prim.line((xe, y - 0.4), (xe, y + g["top_ends_h"] + 0.5), L_EJE, 13)
    h_m = 1.4 * 2.0 * th
    xk = fr["castillos_x"][0]
    yk = (yc + math.sqrt((R + h) ** 2 - xk ** 2) + y + pa.y_top(g, xk) - t) / 2.0
    xm = x + Lh + P / 2
    _marca(x + xm - x, y + 1.6, "P-1", h_m)
    _marca(x - (Lh + P / 2), y + 1.6, "P-1", h_m)
    _marca(x, yc + R + h / 2 - 0.0, "TC-1", h_m)
    _marca(x + xk - t / 2 - 1.1 * h_m, yk, "K-1", h_m)
    ymd = y + pa.y_top(g, 0.0) - t / 2.0
    _marca(x, ymd - 1.15 * h_m - 0.20, "DR-1", h_m)
    ann.create_dimension_chain(positions=[x - xo, x - Lh, x + Lh, x + xo], side="bottom", reference=y,
                               total=True, scale=upm)
    ann.create_dimension_chain(positions=[y, y + g["spring_h"], y + g["crown_h"], y + g["top_ends_h"],
                                          y + g["top_crown_h"]], side="right", reference=x + xo + 0.25, scale=upm)
    items = [((x - Lh - P / 2, y + 3.0), f"P-1  NÚCLEO {core * 100:.0f}x{core * 100:.0f}  {d['pilastra']['bars']['text']}"),
             ((x - 1.2, yc + R + h * 0.5 + 0.2), f"TC-1  {v['b'] * 100:.0f}x{v['h'] * 100:.0f}  "
                                                  f"{v['zona_apoyos']['top']['text']} SUP. / {v['zona_apoyos']['bottom']['text']} INF."),
             ((x + xk, yk), f"K-1  {t * 100:.0f}x{t * 100:.0f}  {fr['castillo']['text']}"),
             ((x - 1.0, ymd), f"DR-1  {t * 100:.0f}x{t * 100:.0f}  {fr['dala_remate']['text']}")]
    dt.callouts(items, "left", x - xo - 0.35, upm, text_mm=2.0, max_chars=34)
    return {"box": [x - xo - 85 * upm, y - 0.4 - 36 * upm, x + xo + 22 * upm, y + g["top_crown_h"] + 0.5]}


# ----------------------------------------------------------- corte del fronton (C-C)

def corte_fronton(d: dict[str, Any], x: float, y: float, upm: float, fc: float = 250.0) -> dict[str, Any]:
    """Corte radial en la clave (A-A): la trabe TC-1 embebida en el frontón de doble hoja de block,
    el relieve de mortero del aro de acento (0.36 m, 5 cm a cada cara), la dala de remate DR-1 y
    la teja. (x, y) = esquina inferior izquierda a la altura del intrados en la clave."""
    _capas()
    g, v, fr = d["geometria"], d["viga"], d["fronton"]
    bb, h = v["b"], v["h"]
    tf = fr["espesor"]
    th = 2.0 * upm
    ap, rel, aro = 0.02, 0.05, 0.36
    xw = x + rel + ap                                   # cara del muro (concreto de la trabe)
    y_t0, y_t1 = y + ap, y + ap + h                     # trabe
    y_f0 = y_t1                                         # el frontón arranca sobre la trabe
    H_f = g["top_crown_h"] - 0.07 - g["crown_h"] - h - 2 * ap - tf
    y_d0 = y_f0 + H_f                                   # dala de remate
    ancho = bb + 2 * (rel + ap)
    with acad.lote():
        for xb in (xw, xw + tf / 2):
            materials.draw_material([(xb, y_f0), (xb + tf / 2, y_f0), (xb + tf / 2, y_f0 + H_f), (xb, y_f0 + H_f)],
                                    "block", layer=L_BLK, scale=upm)
        # aplanado del muro y relieves del aro (de la cara del intrados hacia arriba, 0.36 m)
        prim.poly([(xw - ap, y_f0), (xw + tf + ap, y_f0), (xw + tf + ap, y_d0), (xw - ap, y_d0)], L_CON, True, 25)
        for xr in (xw - ap - rel, xw + tf + ap):
            prim.poly([(xr, y), (xr + rel, y), (xr + rel, y + aro), (xr, y + aro)], L_CON, True, 25)
        prim.poly([(xw - ap, y), (xw + tf + ap, y), (xw + tf + ap, y_t1), (xw - ap, y_t1)], L_CON, True, 13)
        # teja sobre la dala
        yb = y_d0 + tf
        prim.poly([(xw - 0.06, yb), (xw + tf + 0.06, yb), (xw + tf + 0.06, yb + 0.07), (xw - 0.06, yb + 0.07)],
                  L_CON, True, 35)
    s1 = rebar.create_column_section(
        x=xw, y=y_t0, width=bb, depth=h, bars_top_bottom=max(0, v["zona_apoyos"]["top"]["count"] - 2),
        bars_left_right=0, bar_diameter=_db(v["zona_apoyos"]["bottom"]["bar"]), cover=0.04,
        stirrup_diameter=_db(v["zona_apoyos"]["stirrups"]["bar"]))
    cast = fr["castillo"]
    s2 = rebar.create_column_section(
        x=xw, y=y_d0, width=tf, depth=tf, bars_top_bottom=0, bars_left_right=0,
        bar_diameter=_db(cast["bar"]), cover=0.02, stirrup_diameter=0.0064)
    ann.create_dimension_chain(positions=[y, y_t0, y_t1, y_d0, y_d0 + tf, y_d0 + tf + 0.07],
                               side="right", reference=xw + tf + ap + rel + 0.05, scale=upm)
    ann.create_dimension_chain(positions=[x, xw, xw + tf, xw + tf + ap + rel], side="bottom", reference=y, scale=upm)
    items = [((xw + bb / 2, y_t1 - 0.06), f"TC-1 {v['b'] * 100:.0f}x{v['h'] * 100:.0f}: {v['zona_apoyos']['top']['text']} SUP."),
             ((xw + bb / 2, y_t0 + 0.06), f"{v['zona_apoyos']['bottom']['text']} INF."),
             ((xw + tf / 2, y_f0 + H_f / 2), f"FRONTÓN: 2 HOJAS DE BLOCK 10x20x40 (e = {tf * 100:.0f} cm), CELDAS RELLENAS"),
             ((xw + tf / 2, y_d0 + tf / 2), f"DR-1 {tf * 100:.0f}x{tf * 100:.0f}: {fr['dala_remate']['text']}"),
             ((xw + tf / 2, y_d0 + tf + 0.04), "TEJA DE BARRO SOBRE MORTERO"),
             ((x + rel / 2, y + aro * 0.5), "RELIEVE DE MORTERO DEL ARO (5 cm)")]
    dt.callouts(items, "left", x, upm, text_mm=2.0, max_chars=36)
    return {"box": [x - 90 * upm, y - 20 * upm, xw + tf + 24 * upm, y_d0 + tf + 0.07 + 8 * upm],
            "H_fronton": _r3(H_f)}


# ----------------------------------------------------------- pilastra de barda

def pilastra_barda(f: dict[str, Any], x: float, y_piso: float, upm: float, depth: float) -> dict[str, Any]:
    """P-2: elevacion con sus estribos y arranques, y su seccion (nucleo 20x20 + forro de block 10)."""
    _capas()
    p, zc = f["pilastra"], f["cimentacion"]
    core, P = f["nucleo"], f["pilastra_terminada"]
    th = 2.0 * upm
    y_zap_sup = y_piso - depth + zc["h"] + 0.05
    y_top = y_piso + f["pilaster_h"]
    H = y_top - y_zap_sup
    db, db_e = _db(p["bars"]["bar"]), _db(p["stirrups"]["bar"])
    pata = max(zap.ldh_tension(db, 250 * zap.KGCM2_A_MPA, 4200 * zap.KGCM2_A_MPA), 0.20)
    xe = x - core / 2
    el = rebar.create_rebar_elevation(
        x=xe, y=y_zap_sup, width=core, height=H, stirrup_spacing=p["stirrups"]["spacing"], bars_interior=0,
        bar_diameter=db, stirrup_diameter=db_e, cover=0.02, depth=core, orientation="vertical",
        confinement_length=p["stirrups"]["conf_length"], confinement_spacing=p["stirrups"]["conf_spacing"])
    with acad.lote():
        prim.line((x - 0.7, y_zap_sup), (x + 0.7, y_zap_sup), L_CON, 35)
        prim.line((x - 0.7, y_piso), (x + 0.7, y_piso), L_CON, 25)
        for xb in (xe + 0.02 + db / 2, xe + core - 0.02 - db / 2):
            lado = 1 if xb > x else -1
            yy = y_zap_sup - zc["h"] + 0.075 + db / 2 + 0.02
            prim.poly([(xb, y_zap_sup + 0.05), (xb, yy), (xb + lado * pata, yy)], LAYER_ARMADO, False, LW_ARMADO)
        prim.line((x, y_zap_sup - 0.5), (x, y_top + 0.4), L_EJE, 13)
    xs = x + P / 2 + 30 * upm
    ys = y_piso + 0.4
    with acad.lote():
        t = 0.10
        for (a0, b0, a1, b1) in ((xs, ys, xs + t, ys + P), (xs + P - t, ys, xs + P, ys + P),
                                 (xs + t, ys, xs + P - t, ys + t), (xs + t, ys + P - t, xs + P - t, ys + P)):
            materials.draw_material([(a0, b0), (a1, b0), (a1, b1), (a0, b1)], "block", layer=L_BLK, scale=upm)
        prim.poly([(xs, ys), (xs + P, ys), (xs + P, ys + P), (xs, ys + P)], L_CON, True, 25)
    sec = rebar.create_column_section(x=xs + t, y=ys + t, width=core, depth=core, bar_diameter=db,
                                      cover=0.02, stirrup_diameter=db_e)
    ann.create_dimension_chain(positions=[xs, xs + t, xs + t + core, xs + P], side="bottom", reference=ys, scale=upm)
    dt.text("CORTE C-C (P-2)", xs, ys + P + 3 * th, 1.2 * th, L_TXT)
    items = [((xe + 0.02, y_top - 0.30), f"{p['bars']['text']}"),
             ((xe + core / 2, y_top - 0.8), f"EST. {p['stirrups']['bar']} @ {p['stirrups']['spacing'] * 100:.0f} cm"),
             ((xe + core - 0.03, y_top - 0.10), f"@ {p['stirrups']['conf_spacing'] * 100:.0f} cm EN {p['stirrups']['conf_length']:.2f} m"),
             ((xe + core / 2, y_zap_sup + 0.10), f"PATAS DE {pata * 100:.0f} cm EN LA ZAPATA")]
    dt.callouts(items, "left", xe - 0.05, upm, text_mm=2.0)
    ann.create_dimension_chain(positions=[y_zap_sup, y_piso, y_piso + f["wall_h"], y_piso + f["total_h"], y_top],
                               side="right", reference=xe + core + 0.02, scale=upm)
    return {"box": [x - 70 * upm, y_zap_sup - 0.6, xs + P + 18 * upm, y_top + 0.6], "section": sec, "elevation": el,
            "height_m": _r3(H), "pata_m": _r3(pata)}


# ----------------------------------------------------------- planta de cimentacion

def planta_cimentacion(d: dict[str, Any], f: dict[str, Any], x: float, y: float, upm: float, bays: int = 2):
    """Zapatas Z-1 bajo las pilastras del porton, cimiento corrido ZC-1 bajo la barda y
    pilastras P-2, con ejes y cotas. (x, y) = centro del claro."""
    _capas()
    g = d["geometria"]
    z, zc = d["zapata"], f["cimentacion"]
    B, Lz, Bc = z["B"], z["L"], zc["B"]
    Lax = g["L_ejes"] / 2.0
    sp = f["spacing"]
    th = 2.0 * upm
    P1, c1 = d["pilastra_terminada"], d["nucleo"]
    P2, c2 = f["pilastra_terminada"], f["nucleo"]
    xo_ = g["S"] / 2.0 + P1
    der = [x + xo_ + P2 / 2 + sp * (k - 1) for k in range(1, bays + 1)]
    izq = [x - xo_ - P2 / 2 - sp * (k - 1) for k in range(1, bays + 1)]
    with acad.lote():
        for xc in (x - Lax, x + Lax):
            _rect(xc - B / 2, y - Lz / 2, xc + B / 2, y + Lz / 2, L_CON, 50)
            _rect(xc - P1 / 2, y - d["pilastra_prof"] / 2, xc + P1 / 2, y + d["pilastra_prof"] / 2, L_OCU, 13)
            _rect(xc - c1 / 2, y - c1 / 2, xc + c1 / 2, y + c1 / 2, L_CON, 35)
        lg = d.get("liga")
        if lg:
            _rect(x - Lax + B / 2, y - lg["b"] / 2, x + Lax - B / 2, y + lg["b"] / 2, L_CON, 35)
            prim.line((x - Lax + B / 2, y), (x + Lax - B / 2, y), L_OCU, 13)
        # cimiento corrido
        x_ext_r = der[-1] + P2 / 2 + 0.4
        x_ext_l = izq[-1] - P2 / 2 - 0.4
        for a, b in ((x + Lax + B / 2, x_ext_r), (x_ext_l, x - Lax - B / 2)):
            _rect(a, y - Bc / 2, b, y + Bc / 2, L_CON, 35)
        for xc in der + izq:
            _rect(xc - P2 / 2, y - P2 / 2, xc + P2 / 2, y + P2 / 2, L_OCU, 13)
            _rect(xc - c2 / 2, y - c2 / 2, xc + c2 / 2, y + c2 / 2, L_CON, 35)
        for xe in [x - Lax, x + Lax] + der + izq:
            prim.line((xe, y - Lz / 2 - 0.5), (xe, y + Lz / 2 + 0.5), L_EJE, 13)
    pos = sorted(set(izq + [x - Lax, x + Lax] + der))
    ann.create_dimension_chain(positions=pos, side="bottom", reference=y - Lz / 2 - 0.05, total=True, scale=upm)
    ann.create_dimension_chain(positions=[x - Lax - B / 2, x - Lax + B / 2], side="top", reference=y + Lz / 2 + 0.05,
                               scale=upm)
    ann.create_dimension_chain(positions=[y - Lz / 2, y + Lz / 2], side="left", reference=x - Lax - B / 2 - 0.05, scale=upm)
    ann.create_dimension_chain(positions=[y - Bc / 2, y + Bc / 2], side="right", reference=x_ext_r + 0.05, scale=upm)
    dt.text(f"Z-1   {B:.2f} x {Lz:.2f} x {z['h']:.2f}   {z['bars_x']['text']} A.D.", x - Lax - B / 2 + 0.1, y + Lz / 2 - 0.25, th, L_TXT)
    if d.get("liga"):
        lg = d["liga"]
        dt.text(f"TL-1  {lg['b'] * 100:.0f}x{lg['h'] * 100:.0f}  {lg['bars']['count']} {lg['bars']['bar']}, E{lg['stirrup']} @ {lg['stirrup_spacing'] * 100:.0f}",
                x - 1.4, y + lg["b"] / 2 + 0.12, th, L_TXT)
    dt.text(f"ZC-1   B = {Bc:.2f}   h = {zc['h']:.2f}   TRANSV. {zc['bars_x']['text']}", x_ext_l + 0.1, y + Bc / 2 + 0.15, th, L_TXT)
    dt.text(f"P-2   NÚCLEO {c2 * 100:.0f}x{c2 * 100:.0f}   {f['pilastra']['bars']['text']}", der[-1] - 1.0, y - Bc / 2 - 0.35, th, L_TXT)
    return {"box": [x_ext_l - 0.6, y - Lz / 2 - 0.6 - 24 * upm, x_ext_r + 0.6, y + Lz / 2 + 0.7]}
