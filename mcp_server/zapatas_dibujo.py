"""Dibujo de oficio de una zapata diseñada con zapatas.design_footing.

draw_footing_section: el corte por el eje de la columna, de la excavación
hacia arriba, con todo lo que muestra un detalle profesional:

  - terreno natural achurado en una FRANJA a lo largo del corte (talud y
    fondo), que se desvanece hacia afuera -- no una masa entera ni una caja;
  - relleno compactado alrededor de la columna, con textura propia;
  - plantilla de concreto pobre; zapata con su textura;
  - parrilla a su diámetro real: la barra en el plano del corte con ganchos
    a 90° y las de la otra dirección de punta, apoyadas encima; calzos;
  - arranques anclados en L sobre la parrilla, traslape lb con las varillas
    de la columna, estribos de montaje y de columna;
  - junta de colado rugosa y acabado rugoso en la cara superior;
  - cotas y niveles a la IZQUIERDA, llamadas en una columna a la DERECHA
    (señalando la mitad derecha de la pieza, que es simétrica): ninguna
    línea de llamada cruza una cota.

Todo sale del dict del diseño: ningún número se escribe a mano.
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
import space
import symbols as sym_mod
import zapatas as zapatas_mod

L_CONC = "ZAP-CONCRETO"
L_ARM = "ZAP-ARMADO"
L_TERR = "ZAP-TERRENO"
L_GRAF = "ZAP-GRAFISMO"

RELLENO = {"label": "RELLENO COMPACTADO", "pattern": "AR-SAND", "paper_mm": 2.2,
           "angle": 0.0, "fallback": "DOTS", "fallback_mm": 2.0, "color": 8}


def _capas() -> None:
    layers.ensure(L_CONC, 7, 50)
    layers.ensure(L_ARM, 7, 35)
    layers.ensure(L_TERR, 8, 25)
    layers.ensure(L_GRAF, 8, 13)
    layers.ensure_text_style()


def _rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _achurar(points, material, upm) -> Optional[str]:
    """Achura un contorno y BORRA el contorno: el borde lo dibuja quien
    llama, con el trazo que le corresponde a cada lado."""
    spec = mat_mod.resolve_material(material)
    b = acad.call("create_polyline", {"points": [list(p) for p in points], "closed": True,
                                      "layer": L_TERR, "lineweight": 0,
                                      "colorIndex": 8})["handle"]
    h, _info, _av = mat_mod.apply_hatch(b, spec, L_TERR, upm)
    acad.call("delete_entity", {"handle": b})
    return h


def draw_footing_section(z: dict[str, Any], x: float, y: float, upm: float,
                         column_above: float = 0.60,
                         working_space: float = 0.30,
                         slope: float = 0.5,
                         soil_band: float = 0.25,
                         soil_extend: float = 0.50,
                         column_cover: float = 0.04,
                         column_stirrup_spacing: float = 0.10,
                         title: Optional[str] = None,
                         mark: str = "",
                         text_mm: float = 2.0) -> dict[str, Any]:
    """Corte de una zapata bajo columna ('aislada', 'lindero', 'esquina').

    (x, y): x = eje de la columna, y = nivel del terreno natural (N.T.N.).
    upm: unidades del modelo por mm de papel (1:20 en metros = 0.02).
    working_space: holgura de excavación a cada lado de la zapata, m.
    slope: talud de la excavación, horizontal por unidad vertical.
    soil_band: ancho de la franja de terreno achurada a lo largo del corte.
    soil_extend: cuánto sigue el terreno más allá del borde de excavación.
    """
    if z.get("kind") not in ("aislada", "lindero", "esquina", "corrida"):
        raise ValueError("draw_footing_section dibuja zapatas bajo columna o corridas; "
                         "la combinada tiene su propio corte longitudinal.")
    _capas()
    with acad.lote():
        r = _corte(z, x, y, upm, column_above, working_space, slope, soil_band,
                   soil_extend, column_cover, column_stirrup_spacing, title, mark, text_mm)
    r = acad.resolver(r)
    r["batchErrors"] = list(acad.LOTE_ERRORES)
    acad.LOTE_ERRORES.clear()
    return r


def _corte(z, x, y, upm, column_above, working_space, slope, soil_band, soil_extend,
           column_cover, column_stirrup_spacing, title, mark, text_mm):
    sp = z["specs"]
    muro = z["kind"] == "corrida"
    gb = z.get("grade_beam") if muro else None
    B, h, Df = z["B"], z["h"], z["depth"]
    e_pl = z["lean_concrete"]
    c1 = z["column"][0]
    a1 = (z.get("pedestal") or z["column"])[0]
    izq, der = z["column_offsets"][0], z["column_offsets"][1]
    cov = z["cover"]
    bx, by = z["bars_x"], z["bars_y"]
    dw = z["dowels"]
    hu = text_mm * upm

    hp = (gb["height"] if gb else 0.0) if muro else (z.get("pedestal_height") or 0.0)
    xl = x - a1 / 2 - izq                     # borde izquierdo de la zapata
    xr = x + a1 / 2 + der
    y_fb = y - Df                             # fondo de zapata (desplante)
    y_ft = y_fb + h                           # cara superior
    y_exc = y_fb - e_pl                       # fondo de excavación
    y_pt = y_ft + hp                          # arranque de la columna
    H_exc = y - y_exc
    colind = izq < 1e-6                       # lindero: el vecino llega a la cara
    ex_l0 = xl if colind else xl - working_space
    ex_l1 = xl if colind else ex_l0 - slope * H_exc
    ex_r0 = xr + working_space
    ex_r1 = ex_r0 + slope * H_exc
    X_L = (xl - soil_band - 0.15) if colind else ex_l1 - soil_extend
    X_R = ex_r1 + soil_extend
    yc_top = y + column_above
    xcl, xcr = x - c1 / 2, x + c1 / 2
    xal, xar = x - a1 / 2, x + a1 / 2

    # ---- terreno natural: franja a lo largo del corte -------------------------
    corte = ([(X_L, y)] if not colind else []) + \
        [(ex_l1, y), (ex_l0, y_exc), (ex_r0, y_exc), (ex_r1, y), (X_R, y)]
    if colind:
        corte = [(xl, y + 0.0), (xl, y_exc), (ex_r0, y_exc), (ex_r1, y), (X_R, y)]
    franja = dt.offset_open(corte, soil_band)
    # El borde de afuera de la franja, irregular: se lee como tierra cortada.
    borde = []
    for a, b in zip(franja, franja[1:]):
        borde += dt.jagged_points(a, b, upm, amp_mm=1.2, step_mm=3.0,
                                  seed=int(abs(a[0] * 100)) % 97)[:-1]
    borde.append(franja[-1])
    _achurar(corte + list(reversed(borde)), "tierra", upm)
    # El corte (talud y fondo de excavación) y el terreno natural.
    dt._poly([(ex_l1, y), (ex_l0, y_exc), (ex_r0, y_exc), (ex_r1, y)], L_TERR, 25)
    if not colind:
        dt._poly([(X_L, y), (ex_l1, y)], L_TERR, 35, color=7)
    dt._poly([(ex_r1, y), (X_R, y)], L_TERR, 35, color=7)
    if colind:
        # Límite de propiedad sobre la cara de la zapata.
        layers.ensure("LIMITE-PROPIEDAD", 8, 25, layers.LT_LIMITE)
        dt._poly([(xl, y_exc - soil_band - 0.10), (xl, yc_top + 0.15)], "LIMITE-PROPIEDAD", 25)

    # ---- relleno compactado: dos piezas, de la excavación a la columna --------
    for lado in (-1, 1):
        if lado < 0 and colind:
            continue
        x_b = xl if lado < 0 else xr
        x_e0 = ex_l0 if lado < 0 else ex_r0
        x_e1 = ex_l1 if lado < 0 else ex_r1
        x_c = xcl if lado < 0 else xcr
        x_a = xal if lado < 0 else xar
        _achurar([(x_e0, y_exc), (x_b, y_exc), (x_b, y_ft), (x_a, y_ft), (x_a, y_pt),
                  (x_c, y_pt), (x_c, y), (x_e1, y)], RELLENO, upm)

    # ---- plantilla, zapata, columna -------------------------------------------
    plantilla = mat_mod.draw_material(_rect(xl, y_exc, xr, y_fb), "concreto_pobre",
                                      layer=L_CONC, scale=upm, lineweight=35)
    zapata = mat_mod.draw_material(_rect(xl, y_fb, xr, y_ft), "concreto",
                                   layer=L_CONC, scale=upm)
    if hp > 0:
        mat_mod.draw_material(_rect(xal, y_ft, xar, y_pt), "concreto", layer=L_CONC, scale=upm)
    mat_muro = ("block" if z.get("wall_material") == "mamposteria" else "concreto")         if muro else "concreto"
    col = mat_mod.draw_material(_rect(xcl, y_pt, xcr, yc_top), mat_muro,
                                layer=L_CONC, scale=upm, outline=False)
    dt._poly([(xcl, yc_top), (xcl, y_pt)], L_CONC, 50)
    dt._poly([(xcr, yc_top), (xcr, y_pt)], L_CONC, 50)
    dt.break_line((xcl, yc_top), (xcr, yc_top), upm, L_CONC, 25)
    # Junta de colado rugosa (zapata-dado y dado-columna) y rayado de
    # acabado rugoso en la cara superior expuesta.
    dt.rough_line((xal, y_ft), (xar, y_ft), upm, L_GRAF, 35)
    if hp > 0 and not muro:
        dt.rough_line((xcl, y_pt), (xcr, y_pt), upm, L_GRAF, 35)
        for a, b in (((xal, y_pt), (xcl, y_pt)), ((xcr, y_pt), (xar, y_pt))):
            if b[0] - a[0] > 0.08:
                dt.roughness_marks((a[0] + 0.02, a[1]), (b[0] - 0.02, b[1]), upm, L_GRAF)
    for a, b in (((xl, y_ft), (xal, y_ft)), ((xar, y_ft), (xr, y_ft))):
        if b[0] - a[0] > 0.15:
            dt.roughness_marks((a[0] + 0.04, a[1]), (b[0] - 0.04, b[1]), upm, L_GRAF)

    # ---- acero (a su diámetro real) ------------------------------------------
    dbx, dby = bx["db"], by["db"]
    y_bx = y_fb + cov + dbx / 2
    y_by = y_bx + dbx / 2 + dby / 2
    gancho = min(max(12 * dbx, 0.15), h - 2 * cov)
    if gancho > 0.10:
        gancho = math.floor(gancho / 0.05 + 1e-6) * 0.05
    barra = rebar.create_rebar([[xl + cov, y_bx], [xr - cov, y_bx]], dbx,
                               start_hook="90", end_hook="90", hook_side="left",
                               hook_extension=gancho, layer=L_ARM, width=dbx)
    n_y = (by["count"] if muro and by.get("count") else
           max(2, int(round((B - 2 * cov - dby) / by["spacing"])) + 1))
    paso = (B - 2 * cov - 2 * dbx - dby) / (n_y - 1)
    xs_dots = [xl + cov + dbx + dby / 2 + i * paso for i in range(n_y)]
    for px in xs_dots:
        dt.dot(px, y_by, dby / 2, L_ARM, 7)
    n_cal = max(2, math.ceil((B - 2 * cov - 0.20) / 1.0) + 1)
    xs_cal = [xl + cov + 0.10 + k * (B - 2 * cov - 0.20) / (n_cal - 1) for k in range(n_cal)]
    for cx in xs_cal:
        dt.chair(cx, y_fb, cov - dbx * 0.0, L_ARM)

    arranques = []
    ys_m, ys_d, ys_e = [], [], []
    est = 0.0079
    e0, e1 = xcl + column_cover, xcr - column_cover
    x_bar_l = x_bar_r = x
    lap = 0.0
    if muro:
        if gb:
            # Dala de desplante: estribo cerrado con ganchos a 135° y las
            # cuatro varillas de punta en las esquinas.
            rc = 0.025
            sx0, sy0, sx1, sy1 = xal + rc, y_ft + rc, xar - rc, y_pt - rc
            db_e = zapatas_mod.VARILLAS[gb["stirrup"]][0]
            db_d = zapatas_mod.VARILLAS[gb["bar"]][0]
            rebar.create_rebar([[sx0, sy0], [sx1, sy0], [sx1, sy1], [sx0, sy1]], db_e,
                               closed=True, layer=L_ARM, lineweight=25, width=db_e,
                               bend_diameter_factor=4.0)
            k = db_e + db_d / 2
            for px, py in ((sx0 + k, sy0 + k), (sx1 - k, sy0 + k), (sx1 - k, sy1 - k),
                           (sx0 + k, sy1 - k)):
                dt.dot(px, py, db_d / 2, L_ARM, 7)
        dw = None
    if dw:
        db_c = dw["db"]
        y_apoyo = y_by + dby / 2 + db_c / 2
        lap = dw["lap_m"]
        y_lap = y_pt + lap
        pata = dw["leg_m"]
        x_bar_l = xcl + column_cover + est + db_c / 2
        x_bar_r = xcr - column_cover - est - db_c / 2
        por_cara = max(2, dw["count"] // 4 + 1)
        xs_arr = [x_bar_l + k * (x_bar_r - x_bar_l) / (por_cara - 1) for k in range(por_cara)]
        for i, ax in enumerate(xs_arr):
            afuera = -1 if ax < x - 1e-6 else 1
            if abs(ax - x) < 1e-6:
                afuera = 1 if i % 2 else -1
            if colind and afuera < 0:
                afuera = 1
            r = rebar.create_rebar([[ax, y_lap], [ax, y_apoyo]], db_c, end_hook="90",
                                   hook_side="right" if afuera < 0 else "left",
                                   hook_extension=pata, layer=L_ARM, width=db_c)
            arranques.append(r)
            # Varilla de la columna, corrida un diámetro hacia adentro: el
            # traslape se lee como dos barras juntas.
            xb = ax + (db_c * 1.15 if ax < x else -db_c * 1.15)
            dt._poly([(xb, yc_top), (xb, y_pt + 0.05)], L_ARM, 35, width=db_c)
        ms = z.get("mounting_stirrups") or {"count": 3}
        y_m0, y_m1 = y_apoyo + 0.10, y_ft - 0.07
        ys_m = [y_m0 + k * (y_m1 - y_m0) / max(ms["count"] - 1, 1) for k in range(ms["count"])]
        for ym in ys_m:
            dt._poly([(e0, ym), (e1, ym)], L_ARM, 25, width=est)
        if hp > 0:
            s_d = (z.get("pedestal_ties") or {}).get("spacing", 0.15)
            d0, d1 = xal + column_cover, xar - column_cover
            yd = y_ft + 0.05
            while yd < y_pt - 0.03:
                ys_d.append(yd)
                dt._poly([(d0, yd), (d1, yd)], L_ARM, 25, width=0.0095)
                yd += s_d
        ye = y_pt + 0.05
        while ye < yc_top - 0.04:
            ys_e.append(ye)
            dt._poly([(e0, ye), (e1, ye)], L_ARM, 25, width=est)
            ye += column_stirrup_spacing

    # ---- cotas y niveles a la izquierda ----------------------------------------
    x_ref = min(X_L, ex_l1 - soil_band) - 3 * upm
    x_c1 = x_ref - 8 * upm
    ann_mod.create_dimension_chain(positions=[y_exc, y_fb, y_ft] + ([y_pt] if hp > 0 else []) + [y],
                                   side="left",
                                   reference=x_ref, offset=8 * upm, scale=upm)
    dt.dimension((x_ref, y_fb), (x_ref, y), (x_c1 - 9 * upm, (y_fb + y) / 2), upm,
                 angle=90, text_override="Df = <> (DESPLANTE)")
    sym_mod.create_level_mark(x=X_L + 0.10 if not colind else xl - 0.05, y=y, elevation=0.0,
                              prefix="N.T.N.", side="left", height=hu)
    # lb a la izquierda de la columna, gancho en la punta izquierda de la barra.
    if dw:
        dt.dimension((x_bar_l, y_pt), (x_bar_l, y_lap), (xcl - 5 * upm, (y_pt + y_lap) / 2), upm,
                     angle=90, text_override="lb = <>")
    dt.dimension((xl + cov, y_bx), (xl + cov, y_bx + gancho),
                 (xl - 4 * upm, y_bx + gancho / 2), upm, angle=90)
    # Abajo: volados + columna, y el total.
    y_inf = min(y_exc - soil_band, y_exc) - 6 * upm
    cortes = sorted({round(v, 4) for v in (xl, x - a1 / 2, x + a1 / 2, xr)})
    for a, b in zip(cortes, cortes[1:]):
        dt.dimension((a, y_exc), (b, y_exc), ((a + b) / 2, y_inf), upm,
                     text_override=dt.texto_cota(b - a))
    dt.dimension((xl, y_exc), (xr, y_exc), ((xl + xr) / 2, y_inf - 8 * upm), upm,
                 text_override="B = <>")

    # ---- llamadas a la derecha -------------------------------------------------
    xd = (xcr + xr) / 2                       # el centro del volado derecho
    comunes = [
        ((ex_r1 + soil_extend * 0.5, y - soil_band * 0.5), sp["terreno"]),
        (((ex_r0 + ex_r1) / 2 + 0.05, (y + y_exc) / 2), sp["talud"]),
        (((ex_r0 + xcr) / 2 + 0.25 * (1 if not muro else 0.4), (y_ft + y) / 2), sp["relleno"]),
        ((xd, y_ft), sp["acabado"]),
        ((xr - min(0.12, (xr - xar) * 0.3), (y_fb + y_ft) / 2 + 0.03), sp["zapata"]),
        ((xr - cov, y_bx + gancho * 0.7), "GANCHO ESTÁNDAR A 90° (12db)"),
        ((xd + min(0.1, (xr - xar) * 0.2), y_bx), sp["parrilla_x"]),
        ((xs_cal[-1], y_fb + cov * 0.35), sp["calzos"]),
        ((xd - min(0.1, (xr - xar) * 0.2), (y_exc + y_fb) / 2), sp["plantilla"]),
        (((xr + ex_r0) / 2, y_exc), sp["fondo"]),
    ]
    if muro:
        nombre_muro = ("MURO DE BLOCK" if z.get("wall_material") == "mamposteria"
                       else "MURO DE CONCRETO") + f" e={c1 * 100:.0f} cm"
        items = [((x, yc_top - 0.12), nombre_muro + " (VER PROYECTO ARQUITECTÓNICO)")]
        if gb:
            items.append(((xar - 0.03, (y_ft + y_pt) / 2),
                          f"DALA DE DESPLANTE {gb['width'] * 100:.0f}x{gb['height'] * 100:.0f}: "
                          f"{gb['text']} (NTC MAMPOSTERÍA 5.1)"))
        items.append(((xar - 0.02, y_ft), sp["junta"]))
        items.append(((xs_dots[-2], y_by), f"LONGITUDINAL {by.get('count') or len(xs_dots)} "
                      f"VARS. {by['bar']} (DE PUNTA)"))
        items += comunes
    else:
        items = [
            ((xcr - c1 * 0.25, yc_top - 0.10),
             f"COLUMNA {c1 * 100:.0f}x{z['column'][1] * 100:.0f} (VER DISEÑO DE COLUMNAS)"),
            ((e1 - 0.03, ys_e[-1] if ys_e else y_ft + 0.1), "ESTRIBOS DE COLUMNA SEGÚN DISEÑO"),
            ((x_bar_r, y_pt + lap * 0.6), sp["arranques"] + ", " + sp["traslape"]),
            ((x + c1 * 0.25, y_pt), sp["junta"]),
            ((x + c1 * 0.2, ys_m[-1]), sp["montaje"]),
            ((xs_dots[-3], y_by), sp["parrilla_y"] + " (DE PUNTA)"),
        ] + ([((xar - 0.06, (y_ft + y_pt) / 2 + 0.06),
               f"DADO {a1 * 100:.0f}x{(z.get('pedestal') or [0, 0])[1] * 100:.0f} h={hp:.2f} m, "
               f"EST. {(z.get('pedestal_ties') or {}).get('bar', '#3')} @ "
               f"{(z.get('pedestal_ties') or {}).get('spacing', 0) * 100:.0f} (ACI 25.7.2.1)")]
             if hp > 0 else []) + comunes
    x_borde = X_R + 3 * upm
    llam = dt.callouts(items, "right", x_borde, upm, (y_inf, yc_top + 0.15),
                       text_mm=text_mm, gap_mm=8.0, max_chars=44)

    # ---- título ---------------------------------------------------------------------
    tit = title or f"CORTE {z['mark']} - ZAPATA {z['kind'].upper()}"
    techo = max(yc_top + 0.15, llam["box"][3] if llam["box"] else yc_top)
    t = sym_mod.create_view_title(x_c1 - 8 * upm, techo + 8 * upm, tit,
                                  scale_text=f"ESC. 1:{round(upm * 1000)}",
                                  height=3.5 * upm, spaced=False, mark=mark)
    caja = [x_c1 - 14 * upm, y_inf - 14 * upm,
            llam["box"][2] if llam["box"] else X_R, (t.get("box") or [0, 0, 0, techo])[3]]
    return {"box": caja, "footing": zapata["handle"], "lean": plantilla["handle"],
            "column": col["handle"], "barX": barra, "dowels": arranques, "hookLeg": gancho}


# ================================================================ planta

def distribution_line(p0, p1, upm: float, label: str, layer: str = dt.LAYER_LLAMADAS,
                      text_mm: float = 2.0, side: int = 1, at: float = 0.5) -> None:
    """Línea de reparto: cruza las barras de una dirección, con trazos a 45°
    en la primera y la última, y el texto del armado sobre ella -- dice
    'de acá a acá, tantas varillas a tal separación' sin acotar cada una."""
    (x0, y0), (x1, y1) = p0, p1
    L = math.dist(p0, p1)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    t = 1.2 * upm
    dt._poly([p0, p1], layer, 18)
    for px, py in (p0, p1):
        dt._poly([(px - (ux + uy) * t, py - (uy - ux) * t),
                  (px + (ux + uy) * t, py + (uy - ux) * t)], layer, 25)
    ang = math.degrees(math.atan2(uy, ux))
    if ang > 90.01 or ang < -89.99:
        ang += 180
    h = text_mm * upm
    mx, my = x0 + (x1 - x0) * at, y0 + (y1 - y0) * at
    nx, ny = -uy * side, ux * side
    # 'center' apoya la base del texto: del lado de abajo se corre un alto más.
    k = 0.8 if side > 0 else 1.8
    if (ang > 0) != (side > 0) and abs(ang) > 1e-6:
        k = 1.8 if side > 0 else 0.8
    dt.text(label, mx + nx * h * k, my + ny * h * k, h, layer=dt.LAYER_TEXTOS,
            justify="center", rotation=ang)


def _eje(p0, p1, etiqueta: str, upm: float, al_inicio: bool = True) -> None:
    layers.ensure("EJES", 32, 13, layers.LT_EJE)
    dt._poly([p0, p1], "EJES", 13)
    r = 4.0 * upm
    (x0, y0), (x1, y1) = p0, p1
    L = math.dist(p0, p1)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    cx, cy = (x0 - ux * r, y0 - uy * r) if al_inicio else (x1 + ux * r, y1 + uy * r)
    acad.call("create_circle", {"x": cx, "y": cy, "z": 0.0, "radius": r, "layer": "EJES",
                                "lineweight": 25, "colorIndex": None})
    dt.text(etiqueta, cx, cy, 3.0 * upm, layer="EJES", justify="middle_center")


def draw_footing_plan(z: dict[str, Any], x: float, y: float, upm: float,
                      axis_x: Optional[str] = "1", axis_y: Optional[str] = "A",
                      section_label: str = "A", title: Optional[str] = None,
                      mark: str = "", text_mm: float = 2.0) -> dict[str, Any]:
    """Planta de una zapata bajo columna: contorno, columna cortada, la
    parrilla completa a su diámetro (barras X y barras Y), líneas de reparto
    con la cantidad y separación, ejes con globo, marca de corte, cotas.

    (x, y): el centro de la COLUMNA (el cruce de ejes)."""
    if z.get("kind") not in ("aislada", "lindero", "esquina"):
        raise ValueError("draw_footing_plan dibuja zapatas bajo columna.")
    _capas()
    with acad.lote():
        r = _planta(z, x, y, upm, axis_x, axis_y, section_label, title, mark, text_mm)
    r = acad.resolver(r)
    r["batchErrors"] = list(acad.LOTE_ERRORES)
    acad.LOTE_ERRORES.clear()
    return r


def _planta(z, x, y, upm, axis_x, axis_y, section_label, title, mark, text_mm):
    B, L = z["B"], z["L"]
    c1, c2 = z["column"]
    a1, a2 = z.get("pedestal") or z["column"]
    izq, der, aba, arr = z["column_offsets"]
    cov = z["cover"]
    bx, by = z["bars_x"], z["bars_y"]
    x0, x1 = x - a1 / 2 - izq, x + a1 / 2 + der
    y0, y1 = y - a2 / 2 - aba, y + a2 / 2 + arr
    h = text_mm * upm

    dt._poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], L_CONC, 50, closed=True)

    # Parrilla: TODAS las barras finas (se ve la malla sin tapar nada) y una
    # barra tipo por dirección a su diámetro, que es la que se rotula.
    def reparto(a, b, s, db):
        n = max(2, int(round((b - a - db) / s)) + 1)
        paso = (b - a - db) / (n - 1)
        return [a + db / 2 + i * paso for i in range(n)]

    ys_x = reparto(y0 + cov, y1 - cov, bx["spacing"], bx["db"])
    xs_y = reparto(x0 + cov, x1 - cov, by["spacing"], by["db"])
    for yy in ys_x:
        dt._poly([(x0 + cov, yy), (x1 - cov, yy)], L_GRAF, 13, color=8)
    for xx in xs_y:
        dt._poly([(xx, y0 + cov), (xx, y1 - cov)], L_GRAF, 13, color=8)
    # Columna cortada: macizo gris, encima de la malla.
    hc = dt._poly([(x - c1 / 2, y - c2 / 2), (x + c1 / 2, y - c2 / 2), (x + c1 / 2, y + c2 / 2),
                   (x - c1 / 2, y + c2 / 2)], L_CONC, 50, closed=True)
    dt._solid(hc, L_CONC, 8)
    if z.get("pedestal"):
        dt._poly([(x - a1 / 2, y - a2 / 2), (x + a1 / 2, y - a2 / 2), (x + a1 / 2, y + a2 / 2),
                  (x - a1 / 2, y + a2 / 2)], L_CONC, 35, closed=True)
    # Barra tipo y líneas de reparto en el volado MÁS GRANDE de cada
    # dirección: en lindero y esquina el otro lado es la columna.
    def cerca(lista, v):
        return min(range(len(lista)), key=lambda i: abs(lista[i] - v))

    arriba = arr >= aba
    vy = arr if arriba else aba
    y_cara = y + c2 / 2 if arriba else y - c2 / 2
    sg_y = 1 if arriba else -1
    derecha = der >= izq
    vx = der if derecha else izq
    x_cara = x + c1 / 2 if derecha else x - c1 / 2
    sg_x = 1 if derecha else -1

    yb = ys_x[cerca(ys_x, y_cara + sg_y * vy * 0.78)]
    dt._poly([(x0 + cov, yb), (x1 - cov, yb)], L_ARM, 35, width=bx["db"])
    for xe in (x0 + cov, x1 - cov):        # el gancho a 90° visto desde arriba
        dt.dot(xe, yb, bx["db"] * 0.9, L_ARM, 7)
    xb_ = xs_y[cerca(xs_y, x_cara + sg_x * vx * 0.30)]
    dt._poly([(xb_, y0 + cov), (xb_, y1 - cov)], L_ARM, 35, width=by["db"])
    for ye in (y0 + cov, y1 - cov):
        dt.dot(xb_, ye, by["db"] * 0.9, L_ARM, 7)
    dt.text(f"{bx['bar']} @ {bx['spacing'] * 100:.0f} (X) L={B - 2 * cov:.2f}+GANCHOS",
            xb_ + 0.06, yb + bx["db"] + 0.6 * h, h)
    y_txt_y = (y_cara + sg_y * vy * 0.10) if arriba else (y0 + cov + 0.08)
    dt.text(f"{by['bar']} @ {by['spacing'] * 100:.0f} (Y) L={L - 2 * cov:.2f}+GANCHOS",
            xb_ - by["db"] - 0.6 * h, y_txt_y, h, rotation=90)
    xd = x_cara + sg_x * vx * 0.70
    distribution_line((xd, ys_x[0]), (xd, ys_x[-1]), upm,
                      f"{len(ys_x)} VARS. {bx['bar']}", side=-1)
    yd = y_cara + sg_y * vy * 0.45
    distribution_line((xs_y[0], yd), (xs_y[-1], yd), upm,
                      f"{len(xs_y)} VARS. {by['bar']}", side=1,
                      at=0.75 if derecha else 0.25)

    # Colindancia: el límite de propiedad sobre la cara de la zapata.
    lados_col = [o < 1e-6 for o in (izq, der, aba, arr)]
    if any(lados_col):
        layers.ensure("LIMITE-PROPIEDAD", 8, 35, layers.LT_LIMITE)
        if lados_col[0]:
            dt._poly([(x0, y0 - 0.60), (x0, y1 + 0.60)], "LIMITE-PROPIEDAD", 35)
            dt.text("LÍMITE DE PROPIEDAD", x0 - 0.6 * h,
                    y1 - dt.text_width("LÍMITE DE PROPIEDAD", h) - 0.05, h, rotation=90)
        if lados_col[2]:
            dt._poly([(x0 - 0.60, y0), (x1 + 0.60, y0)], "LIMITE-PROPIEDAD", 35)
            dt.text("LÍMITE DE PROPIEDAD", x1 - dt.text_width("LÍMITE DE PROPIEDAD", h) - 0.05,
                    y0 - 1.6 * h, h)

    # Ejes por el centro de la columna: el vertical con globo arriba, el
    # horizontal a la derecha, afuera de las cotas.
    ext = 0.35
    if axis_x:
        _eje((x, y1 + ext), (x, y0 - 0.15), axis_x, upm, al_inicio=True)
    if axis_y:
        _eje((x0 - 0.15, y), (x1 + 0.95, y), axis_y, upm, al_inicio=False)

    # Marca de corte por el eje de la columna.
    sym_mod.create_section_mark(x1=x0 - 0.25, y1=y, x2=x1 + 0.25, y2=y,
                                label=section_label, direction="left", height=h * 1.25)

    dt.chain([x0, x - a1 / 2, x + a1 / 2, x1], "bottom", y0 - 0.20, upm)
    dt.chain([y0, y - a2 / 2, y + a2 / 2, y1], "right", x1 + 0.40, upm)
    # Nombre de la zapata en el volado de arriba a la izquierda.
    dt.text(z["mark"], x0 + 0.10, y1 - 0.12 - h * 1.6, h * 1.6, lw=35)

    tit = title or f"PLANTA {z['mark']}"
    t = sym_mod.create_view_title(x0 - 0.45, y1 + ext + 22 * upm, tit,
                                  scale_text=f"ESC. 1:{round(upm * 1000)}",
                                  height=3.5 * upm, spaced=False, mark=mark)
    return {"box": [x0 - 0.45 - 10 * upm, y0 - 0.20 - 32 * upm, x1 + 0.95 + 10 * upm,
                    (t.get("box") or [0, 0, 0, y1 + 1])[3] + 3 * upm],
            "barsX": len(ys_x), "barsY": len(xs_y)}


def draw_strip_plan(z: dict[str, Any], x: float, y: float, upm: float,
                    length: float = 2.40, axis: Optional[str] = "1",
                    section_label: str = "A", title: Optional[str] = None,
                    mark: str = "", text_mm: float = 2.0) -> dict[str, Any]:
    """Planta de un tramo de zapata corrida: el muro corre en X, la zapata
    se corta con símbolo de corte en las dos puntas (sigue más allá), las
    transversales a su separación y las longitudinales corridas."""
    if z.get("kind") != "corrida":
        raise ValueError("draw_strip_plan es para zapatas corridas.")
    _capas()
    with acad.lote():
        r = _planta_corrida(z, x, y, upm, length, axis, section_label, title, mark, text_mm)
    r = acad.resolver(r)
    r["batchErrors"] = list(acad.LOTE_ERRORES)
    acad.LOTE_ERRORES.clear()
    return r


def _planta_corrida(z, x, y, upm, length, axis, section_label, title, mark, text_mm):
    B, t, cov = z["B"], z["wall_thickness"], z["cover"]
    bx, by = z["bars_x"], z["bars_y"]
    h = text_mm * upm
    x0, x1 = x - length / 2, x + length / 2
    y0, y1 = y - B / 2, y + B / 2
    # Bordes largos de la zapata; las puntas, con símbolo de corte.
    dt._poly([(x0, y0), (x1, y0)], L_CONC, 50)
    dt._poly([(x0, y1), (x1, y1)], L_CONC, 50)
    for xe in (x0, x1):
        dt.break_line((xe, y0), (xe, y1), upm, L_CONC, 25)
    # Muro de arriba, cortado: achurado de su material.
    mat = "block" if z.get("wall_material") == "mamposteria" else "concreto"
    mat_mod.draw_material(_rect(x0, y - t / 2, x1, y + t / 2), mat, layer=L_CONC, scale=upm)
    # Transversales (en Y) a su separación; longitudinales (en X) corridas.
    s = bx["spacing"]
    xs = []
    xx = x0 + s / 2
    while xx < x1 - 1e-6:
        xs.append(xx)
        xx += s
    for xx in xs:
        dt._poly([(xx, y0 + cov), (xx, y1 - cov)], L_GRAF, 13, color=8)
    n = by.get("count") or 4
    ys = [y0 + cov + bx["db"] + k * (B - 2 * cov - 2 * bx["db"]) / (n - 1) for k in range(n)]
    for yy in ys:
        dt._poly([(x0, yy), (x1, yy)], L_GRAF, 13, color=8)
    # Barra tipo transversal y longitudinal.
    xt = xs[len(xs) // 4]
    dt._poly([(xt, y0 + cov), (xt, y1 - cov)], L_ARM, 35, width=bx["db"])
    for ye in (y0 + cov, y1 - cov):
        dt.dot(xt, ye, bx["db"] * 0.9, L_ARM, 7)
    dt.text(f"TRANSVERSAL {bx['bar']} @ {s * 100:.0f}, L={B - 2 * cov:.2f} + 2 GANCHOS",
            xt + 0.06, y - t / 2 - (B / 2 - t / 2) * 0.45, h)
    yl = ys[-1]
    dt._poly([(x0, yl), (x1, yl)], L_ARM, 35, width=by["db"])
    dt.text(f"{n} VARS. {by['bar']} LONGITUDINALES CORRIDAS", xt + 0.08, yl + 0.6 * h, h)
    xd = x0 + (x1 - x0) * 0.70
    distribution_line((xd - 2 * s, y0 + 0.08), (xd + 2 * s, y0 + 0.08), upm,
                      f"{bx['bar']} @ {s * 100:.0f}", side=1)
    if axis:
        _eje((x0 - 0.30, y), (x1 + 0.10, y), axis, upm, al_inicio=True)
    xm = x0 + (x1 - x0) * 0.55
    sym_mod.create_section_mark(x1=xm, y1=y1 + 0.25, x2=xm, y2=y0 - 0.25,
                                label=section_label, direction="left", height=h * 1.25)
    dt.chain([y0, y - t / 2, y + t / 2, y1], "right", x1 + 0.15, upm)
    tit = title or f"PLANTA {z['mark']}"
    t_ = sym_mod.create_view_title(x0 - 0.30, y1 + 0.25 + 16 * upm, tit,
                                   scale_text=f"ESC. 1:{round(upm * 1000)}",
                                   height=3.5 * upm, spaced=False, mark=mark)
    return {"box": [x0 - 0.30 - 10 * upm, y0 - 0.25 - 12 * upm, x1 + 0.15 + 30 * upm,
                    (t_.get("box") or [0, 0, 0, y1 + 1])[3] + 3 * upm]}
