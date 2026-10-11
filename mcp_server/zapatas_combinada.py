"""Dibujo de la zapata COMBINADA (dos columnas): corte longitudinal y planta.

Lo que la distingue de una aislada y tiene que verse: el lecho SUPERIOR
entre columnas (ahí la tensión está arriba) con sus ganchos hacia abajo, el
inferior en los volados, las bandas transversales bajo cada columna (más
densas) y el mínimo fuera de ellas, y los arranques de las dos columnas.
Usa el mismo grafismo que zapatas_dibujo.
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
from zapatas_dibujo import (L_ARM, L_CONC, L_GRAF, L_TERR, RELLENO, _achurar, _capas, _eje,
                            _rect, distribution_line)


def draw_combined_section(z: dict[str, Any], x: float, y: float, upm: float,
                          column_above: float = 0.60, working_space: float = 0.30,
                          slope: float = 0.5, soil_band: float = 0.25,
                          soil_extend: float = 0.50, column_cover: float = 0.04,
                          title: Optional[str] = None, mark: str = "",
                          text_mm: float = 2.0) -> dict[str, Any]:
    """Corte LONGITUDINAL por el eje de las dos columnas.
    (x, y): x = borde izquierdo de la zapata, y = N.T.N."""
    if z.get("kind") != "combinada":
        raise ValueError("draw_combined_section es para zapatas combinadas.")
    _capas()
    with acad.lote():
        r = _corte(z, x, y, upm, column_above, working_space, slope, soil_band,
                   soil_extend, column_cover, title, mark, text_mm)
    r = acad.resolver(r)
    r["batchErrors"] = list(acad.LOTE_ERRORES)
    acad.LOTE_ERRORES.clear()
    return r


def _franja_terreno(corte, soil_band, upm):
    franja = dt.offset_open(corte, soil_band)
    borde = []
    for a, b in zip(franja, franja[1:]):
        borde += dt.jagged_points(a, b, upm, amp_mm=1.2, step_mm=3.0,
                                  seed=int(abs(a[0] * 100)) % 97)[:-1]
    borde.append(franja[-1])
    _achurar(corte + list(reversed(borde)), "tierra", upm)


def _corte(z, x, y, upm, column_above, working_space, slope, soil_band, soil_extend,
           column_cover, title, mark, text_mm):
    sp = z["specs"]
    Lx, h, Df = z["B"], z["h"], z["depth"]
    e_pl, cov, cov_t = z["lean_concrete"], z["cover"], z.get("cover_top", 0.05)
    bb, bt = z["bars_bottom"], z["bars_top"]
    dw = z["dowels"]
    cols = z["columns"]
    xl, xr = x, x + Lx
    y_fb = y - Df
    y_ft = y_fb + h
    y_exc = y_fb - e_pl
    H = y - y_exc
    colind = z.get("boundary_left", False)
    ex_l0 = xl if colind else xl - working_space
    ex_l1 = xl if colind else ex_l0 - slope * H
    ex_r0 = xr + working_space
    ex_r1 = ex_r0 + slope * H
    X_L = (xl - soil_band - 0.15) if colind else ex_l1 - soil_extend
    X_R = ex_r1 + soil_extend
    yc_top = y + column_above
    hu = text_mm * upm

    # ---- terreno, excavación y relleno --------------------------------------
    corte = ([(xl, y), (xl, y_exc)] if colind else
             [(X_L, y), (ex_l1, y), (ex_l0, y_exc)]) + [(ex_r0, y_exc), (ex_r1, y), (X_R, y)]
    _franja_terreno(corte, soil_band, upm)
    dt._poly([(ex_l1, y), (ex_l0, y_exc), (ex_r0, y_exc), (ex_r1, y)], L_TERR, 25)
    if colind:
        layers.ensure("LIMITE-PROPIEDAD", 8, 25, layers.LT_LIMITE)
        dt._poly([(xl, y_exc - soil_band - 0.10), (xl, yc_top + 0.15)], "LIMITE-PROPIEDAD", 25)
    else:
        dt._poly([(X_L, y), (ex_l1, y)], L_TERR, 35, color=7)
    dt._poly([(ex_r1, y), (X_R, y)], L_TERR, 35, color=7)
    caras = []
    for c in cols:
        cx = xl + c["x"]
        caras.append((cx - c["size"][0] / 2, cx + c["size"][0] / 2))
    tramos = []
    if not colind:
        tramos.append([(ex_l0, y_exc), (xl, y_exc), (xl, y_ft), (caras[0][0], y_ft),
                       (caras[0][0], y), (ex_l1, y)])
    elif caras[0][0] - xl > 0.02:
        tramos.append([(xl, y_ft), (caras[0][0], y_ft), (caras[0][0], y), (xl, y)])
    tramos.append([(caras[0][1], y_ft), (caras[1][0], y_ft), (caras[1][0], y),
                   (caras[0][1], y)])
    tramos.append([(ex_r0, y_exc), (xr, y_exc), (xr, y_ft), (caras[1][1], y_ft),
                   (caras[1][1], y), (ex_r1, y)])
    for pts in tramos:
        _achurar(pts, RELLENO, upm)

    # ---- concreto -----------------------------------------------------------
    plantilla = mat_mod.draw_material(_rect(xl, y_exc, xr, y_fb), "concreto_pobre",
                                      layer=L_CONC, scale=upm, lineweight=35)
    zapata = mat_mod.draw_material(_rect(xl, y_fb, xr, y_ft), "concreto", layer=L_CONC,
                                   scale=upm)
    for c0, c1 in caras:
        mat_mod.draw_material(_rect(c0, y_ft, c1, yc_top), "concreto", layer=L_CONC,
                              scale=upm, outline=False)
        dt._poly([(c0, yc_top), (c0, y_ft)], L_CONC, 50)
        dt._poly([(c1, yc_top), (c1, y_ft)], L_CONC, 50)
        dt.break_line((c0, yc_top), (c1, yc_top), upm, L_CONC, 25)
        dt.rough_line((c0, y_ft), (c1, y_ft), upm, L_GRAF, 35)
    for a, b in ((xl, caras[0][0]), (caras[0][1], caras[1][0]), (caras[1][1], xr)):
        if b - a > 0.15:
            dt.roughness_marks((a + 0.04, y_ft), (b - 0.04, y_ft), upm, L_GRAF)

    # ---- acero longitudinal: inferior (ganchos arriba), superior (abajo) ----
    gancho_i = min(max(12 * bb["db"], 0.15), h - cov - cov_t)
    gancho_s = min(max(12 * bt["db"], 0.15), h - cov - cov_t)
    y_bi = y_fb + cov + bb["db"] / 2
    y_bs = y_ft - cov_t - bt["db"] / 2
    rebar.create_rebar([[xl + cov, y_bi], [xr - cov, y_bi]], bb["db"], start_hook="90",
                       end_hook="90", hook_side="left", hook_extension=gancho_i,
                       layer=L_ARM, width=bb["db"])
    rebar.create_rebar([[xl + cov, y_bs], [xr - cov, y_bs]], bt["db"], start_hook="90",
                       end_hook="90", hook_side="right", hook_extension=gancho_s,
                       layer=L_ARM, width=bt["db"])

    # ---- transversales de punta ----------------------------------------------
    tmin = z["transverse_min"]
    y_ti = y_bi + bb["db"] / 2 + tmin["db"] / 2
    bandas = []
    for c, banda in zip(cols, z["transverse_bands"]):
        cx = xl + c["x"]
        w = banda["width_m"]
        bandas.append((max(xl + cov, cx - w / 2), min(xr - cov, cx + w / 2), banda))
    puntos = []
    for b0, b1, banda in bandas:
        n = max(2, int(round((b1 - b0) / banda["spacing"])) + 1)
        puntos += [(b0 + k * (b1 - b0) / (n - 1), banda["db"]) for k in range(n)]
    for a, b in ((xl + cov, bandas[0][0]), (bandas[0][1], bandas[1][0]),
                 (bandas[1][1], xr - cov)):
        if b - a > tmin["spacing"]:
            n = int((b - a) / tmin["spacing"])
            puntos += [(a + (k + 0.5) * (b - a) / n, tmin["db"]) for k in range(n)]
    for px, db in puntos:
        dt.dot(px, y_ti, db / 2, L_ARM, 7)
    mt = z["top_transverse"]
    y_ts = y_bs - bt["db"] / 2 - mt["db"] / 2
    xs_ts = []
    xx = xl + cov + 0.10
    while xx < xr - cov - 0.05:
        xs_ts.append(xx)
        dt.dot(xx, y_ts, mt["db"] / 2, L_ARM, 7)
        xx += mt["spacing"]
    n_cal = max(2, math.ceil((Lx - 2 * cov - 0.20) / 1.0) + 1)
    xs_cal = [xl + cov + 0.10 + k * (Lx - 2 * cov - 0.20) / (n_cal - 1) for k in range(n_cal)]
    for cx in xs_cal:
        dt.chair(cx, y_fb, cov, L_ARM)

    # ---- arranques de las dos columnas -------------------------------------
    db_c, lap, pata = dw["db"], dw["lap_m"], dw["leg_m"]
    y_ap = y_ti + tmin["db"] / 2 + db_c / 2
    y_lap = y_ft + lap
    est = 0.0079
    for i, (c0, c1) in enumerate(caras):
        xb0 = c0 + column_cover + est + db_c / 2
        xb1 = c1 - column_cover - est - db_c / 2
        for ax, lado in ((xb0, -1), (xb1, 1)):
            if colind and i == 0 and lado < 0:
                lado = 1                      # en colindancia la pata va hacia adentro
            rebar.create_rebar([[ax, y_lap], [ax, y_ap]], db_c, end_hook="90",
                               hook_side="right" if lado < 0 else "left",
                               hook_extension=pata, layer=L_ARM, width=db_c)
            xb = ax + (db_c * 1.15 if ax < (c0 + c1) / 2 else -db_c * 1.15)
            dt._poly([(xb, yc_top), (xb, y_ft + 0.05)], L_ARM, 35, width=db_c)
        for k in range(3):
            ym = y_ap + 0.10 + k * (y_bs - 0.08 - y_ap - 0.10) / 2
            dt._poly([(c0 + column_cover, ym), (c1 - column_cover, ym)], L_ARM, 25, width=est)
        ye = y_ft + 0.05
        while ye < yc_top - 0.04:
            dt._poly([(c0 + column_cover, ye), (c1 - column_cover, ye)], L_ARM, 25, width=est)
            ye += 0.10

    # ---- cotas ----------------------------------------------------------------
    x_ref = (min(X_L, ex_l1 - soil_band) if not colind else xl - soil_band - 0.15) - 3 * upm
    ann_mod.create_dimension_chain(positions=[y_exc, y_fb, y_ft, y], side="left",
                                   reference=x_ref, offset=8 * upm, scale=upm)
    dt.dimension((x_ref, y_fb), (x_ref, y), (x_ref - 17 * upm, (y_fb + y) / 2), upm,
                 angle=90, text_override="Df = <> (DESPLANTE)")
    sym_mod.create_level_mark(x=(X_L + 0.10) if not colind else xl - 0.05, y=y,
                              elevation=0.0, prefix="N.T.N.", side="left", height=hu)
    y_inf = y_exc - soil_band - 6 * upm
    cortes = sorted({round(v, 4) for v in (xl, caras[0][0], caras[0][1], caras[1][0],
                                            caras[1][1], xr)})
    for a, b in zip(cortes, cortes[1:]):
        dt.dimension((a, y_exc), (b, y_exc), ((a + b) / 2, y_inf), upm,
                     text_override=dt.texto_cota(b - a))
    ejes = [xl + c["x"] for c in cols]
    dt.dimension((ejes[0], y_exc), (ejes[1], y_exc), (sum(ejes) / 2, y_inf - 8 * upm), upm,
                 text_override="ENTRE EJES <>")
    dt.dimension((xl, y_exc), (xr, y_exc), ((xl + xr) / 2, y_inf - 16 * upm), upm,
                 text_override="L = <>")
    xlb = caras[1][1] - column_cover - est - db_c / 2
    dt.dimension((xlb, y_ft), (xlb, y_lap), (caras[1][1] + 5 * upm, (y_ft + y_lap) / 2), upm,
                 angle=90, text_override="lb = <>")

    # ---- llamadas a la derecha (tramo derecho: columna 2 y volado) -------
    c20, c21 = caras[1]
    xv = (c21 + xr) / 2
    xm = (caras[0][1] + c20) / 2
    arr = sp["arranques"].replace(f"{dw['count']} ARRANQUES", f"{dw['count']} ARRANQUES POR COLUMNA")
    items = [
        ((c21 - 0.08, yc_top - 0.10), "COLUMNAS (VER DISEÑO DE COLUMNAS)"),
        ((xlb, y_ft + lap * 0.6), arr + ", " + sp["traslape"]),
        ((ex_r1 + soil_extend * 0.5, y - soil_band * 0.5), sp["terreno"]),
        (((ex_r0 + ex_r1) / 2 + 0.05, (y + y_exc) / 2), sp["talud"]),
        ((xm + 0.6, (y_ft + y) / 2), sp["relleno"]),
        (((c20 + c21) / 2, y_ft), sp["junta"]),
        ((xm + 0.9, y_ft), sp["acabado"]),
        ((xm + 0.3, y_bs), f"LECHO SUPERIOR {bt['text']} CON GANCHO A 90° (ENTRE COLUMNAS)"),
        ((xs_ts[min(len(xs_ts) - 1, int(len(xs_ts) * 0.6))], y_ts),
         f"MONTAJE TRANSVERSAL SUPERIOR {mt['text']} (DE PUNTA)"),
        ((xr - 0.2, (y_fb + y_ft) / 2), sp["zapata"]),
        (((c20 + c21) / 2 + 0.05, y_ti),
         f"BANDA BAJO COLUMNA {z['transverse_bands'][1]['text']} (DE PUNTA)"),
        ((xv + 0.15, y_ti), f"TRANSVERSAL FUERA DE BANDAS {tmin['text']} (DE PUNTA)"),
        ((xv - 0.15, y_bi), f"LECHO INFERIOR {bb['text']} CON GANCHO A 90°"),
        ((xs_cal[-1], y_fb + cov * 0.35), sp["calzos"]),
        ((xv, (y_exc + y_fb) / 2), sp["plantilla"]),
        (((xr + ex_r0) / 2, y_exc), sp["fondo"]),
    ]
    llam = dt.callouts(items, "right", X_R + 3 * upm, upm, (y_inf - 16 * upm, yc_top + 0.15),
                       text_mm=text_mm, gap_mm=8.0, max_chars=48)
    tit = title or f"CORTE LONGITUDINAL {z['mark']} - ZAPATA COMBINADA"
    techo = max(yc_top + 0.15, llam["box"][3])
    t = sym_mod.create_view_title(x_ref - 25 * upm, techo + 8 * upm, tit,
                                  scale_text=f"ESC. 1:{round(upm * 1000)}",
                                  height=3.5 * upm, spaced=False, mark=mark)
    return {"box": [x_ref - 30 * upm, y_inf - 30 * upm, llam["box"][2],
                    (t.get("box") or [0, 0, 0, techo])[3]],
            "footing": zapata["handle"], "lean": plantilla["handle"]}


def draw_combined_plan(z: dict[str, Any], x: float, y: float, upm: float,
                       axes_x: tuple[str, str] = ("1", "2"), axis_y: str = "A",
                       section_label: str = "A", title: Optional[str] = None,
                       mark: str = "", text_mm: float = 2.0) -> dict[str, Any]:
    """Planta de zapata combinada. (x, y): esquina inferior izquierda."""
    if z.get("kind") != "combinada":
        raise ValueError("draw_combined_plan es para zapatas combinadas.")
    _capas()
    with acad.lote():
        r = _planta(z, x, y, upm, axes_x, axis_y, section_label, title, mark, text_mm)
    r = acad.resolver(r)
    r["batchErrors"] = list(acad.LOTE_ERRORES)
    acad.LOTE_ERRORES.clear()
    return r


def _planta(z, x, y, upm, axes_x, axis_y, section_label, title, mark, text_mm):
    Lx, By, cov = z["B"], z["L"], z["cover"]
    bb = z["bars_bottom"]
    tmin = z["transverse_min"]
    h = text_mm * upm
    x0, x1, y0, y1 = x, x + Lx, y, y + By
    yc = y + By / 2
    dt._poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], L_CONC, 50, closed=True)
    n = max(2, int(round((By - 2 * cov - bb["db"]) / bb["spacing"])) + 1)
    ys = [y0 + cov + bb["db"] / 2 + k * (By - 2 * cov - bb["db"]) / (n - 1) for k in range(n)]
    for yy in ys:
        dt._poly([(x0 + cov, yy), (x1 - cov, yy)], L_GRAF, 13, color=8)
    bandas = []
    for c, b in zip(z["columns"], z["transverse_bands"]):
        cx = x0 + c["x"]
        bandas.append((max(x0 + cov, cx - b["width_m"] / 2),
                       min(x1 - cov, cx + b["width_m"] / 2), b))
    xs = []
    for b0, b1, b in bandas:
        k = max(2, int(round((b1 - b0) / b["spacing"])) + 1)
        xs += [b0 + i * (b1 - b0) / (k - 1) for i in range(k)]
    for a, b_ in ((x0 + cov, bandas[0][0]), (bandas[0][1], bandas[1][0]),
                  (bandas[1][1], x1 - cov)):
        if b_ - a > tmin["spacing"]:
            k = int((b_ - a) / tmin["spacing"])
            xs += [a + (i + 0.5) * (b_ - a) / k for i in range(k)]
    for xx in xs:
        dt._poly([(xx, y0 + cov), (xx, y1 - cov)], L_GRAF, 13, color=8)
    layers.ensure("OCULTO", 8, 13, layers.LT_OCULTO)
    for b0, b1, b in bandas:
        for xb in (b0, b1):
            dt._poly([(xb, y0 - 0.12), (xb, y1 + 0.12)], "OCULTO", 13)
        distribution_line((b0, y1 - 0.25), (b1, y1 - 0.25), upm,
                          f"BANDA {b['width_m']:.2f}: {b['text']}", side=1)
    for c in z["columns"]:
        cx = x0 + c["x"]
        a, b_ = c["size"]
        hc = dt._poly([(cx - a / 2, yc - b_ / 2), (cx + a / 2, yc - b_ / 2),
                       (cx + a / 2, yc + b_ / 2), (cx - a / 2, yc + b_ / 2)],
                      L_CONC, 50, closed=True)
        dt._solid(hc, L_CONC, 8)
    yb = ys[max(0, len(ys) - 3)]
    dt._poly([(x0 + cov, yb), (x1 - cov, yb)], L_ARM, 35, width=bb["db"])
    for xe in (x0 + cov, x1 - cov):
        dt.dot(xe, yb, bb["db"] * 0.9, L_ARM, 7)
    xm = (bandas[0][1] + bandas[1][0]) / 2
    dt.text(f"LECHO INF. {bb['text']} L={Lx - 2 * cov:.2f}+GANCHOS; LECHO SUP. "
            f"{z['bars_top']['text']}", bandas[0][1] + 0.08, yb + bb["db"] + 0.6 * h, h)
    distribution_line((xm, ys[0]), (xm, ys[-1]), upm, f"{len(ys)} VARS. {bb['bar']}",
                      side=-1, at=0.35)
    distribution_line((bandas[0][1] + 0.05, y0 + 0.30), (bandas[1][0] - 0.05, y0 + 0.30), upm,
                      f"FUERA DE BANDAS {tmin['text']}", side=1)
    for c, et in zip(z["columns"], axes_x):
        _eje((x0 + c["x"], y1 + 0.35), (x0 + c["x"], y0 - 0.15), et, upm, al_inicio=True)
    _eje((x0 - 0.15, yc), (x1 + 0.95, yc), axis_y, upm, al_inicio=False)
    sym_mod.create_section_mark(x1=x0 - 0.30, y1=yc, x2=x1 + 0.30, y2=yc,
                                label=section_label, direction="left", height=h * 1.25)
    if z.get("boundary_left"):
        layers.ensure("LIMITE-PROPIEDAD", 8, 35, layers.LT_LIMITE)
        dt._poly([(x0, y0 - 0.60), (x0, y1 + 0.60)], "LIMITE-PROPIEDAD", 35)
        dt.text("LÍMITE DE PROPIEDAD", x0 - 0.6 * h,
                y1 - dt.text_width("LÍMITE DE PROPIEDAD", h) - 0.05, h, rotation=90)
    dt.chain([x0, x1] + [x0 + c["x"] for c in z["columns"]], "bottom", y0 - 0.20, upm)
    dt.chain([y0, y1], "right", x1 + 0.40, upm, total=False)
    dt.text(z["mark"], x0 + 0.10, y0 + 0.10, h * 1.6, lw=35)
    tit = title or f"PLANTA {z['mark']}"
    t = sym_mod.create_view_title(x0 - 0.45, y1 + 0.35 + 22 * upm, tit,
                                  scale_text=f"ESC. 1:{round(upm * 1000)}",
                                  height=3.5 * upm, spaced=False, mark=mark)
    return {"box": [x0 - 0.45 - 10 * upm, y0 - 0.20 - 32 * upm, x1 + 0.95 + 10 * upm,
                    (t.get("box") or [0, 0, 0, y1 + 1])[3] + 3 * upm]}
