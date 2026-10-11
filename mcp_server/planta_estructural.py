"""Plantas estructurales de una estructura de marcos de concreto: la de
CIMENTACIÓN (zapatas por tipo, contratrabes, columnas) y la de ENTREPISO /
AZOTEA (trabes, columnas, tableros de losa con su armado). Se dibujan desde
los datos de diseño (zapatas.design_footing, estructura.design_beam /
design_two_way_slab): ninguna medida se escribe a mano.

Convenciones de planta estructural:
  - columnas cortadas: macizo negro; trabes bajo la losa: trazo oculto;
    zapatas: contorno grueso; contratrabes: dos líneas finas;
  - cada tablero lleva su número en un círculo y sus dos bastones de
    armado (corto y largo) con la varilla y la separación;
  - ejes con globo, cotas entre ejes y totales; marcas de cada elemento
    (Z-1, ZL-1, T-1, CT-1, C-1).
"""
from __future__ import annotations

from typing import Any, Optional

import autocad_client as acad
import detalle as dt
import layers
import symbols as sym_mod

L_COL = "EST-COLUMNAS"
L_ZAP = "EST-ZAPATAS"
L_TRA = "EST-TRABES"
L_LOSA = "EST-LOSAS"
L_EJE = "EJES"


def _capas():
    layers.ensure(L_COL, 7, 50)
    layers.ensure(L_ZAP, 7, 50)
    layers.ensure(L_TRA, 7, 25, layers.LT_OCULTO)
    layers.ensure(L_LOSA, 12, 25)
    layers.ensure(L_EJE, 32, 13, layers.LT_EJE)
    layers.ensure_text_style()


def _rect(x0, y0, x1, y1, layer, lw, closed=True):
    return dt._poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer, lw, closed=closed)


def footing_rect(col: dict[str, Any], z: dict[str, Any], lot: tuple[float, float],
                 origin: tuple[float, float] = (0.0, 0.0)):
    """Rectángulo de la zapata en planta según su tipo y de qué lado está la
    colindancia: lindero en x=0 / x=ancho se abre hacia adentro en X; en
    y=0 (frente) hacia adentro en Y; esquina hacia adentro en las dos."""
    ox, oy = origin
    x, y = col["x"] - ox, col["y"] - oy
    c = 0.30 if not z.get("column") else z["column"][0]
    r = _footing_local(x, y, c, z, lot)
    return (r[0] + ox, r[1] + oy, r[2] + ox, r[3] + oy)


def _footing_local(x, y, c, z, lot):
    B, L = z["B"], z["L"]
    W, D = lot
    kind = z["kind"]
    if kind == "aislada":
        return (x - B / 2, y - L / 2, x + B / 2, y + L / 2)
    if kind == "esquina":
        sx = 1 if x < W / 2 else -1
        sy = 1 if y < D / 2 else -1
        xa = x - sx * c / 2
        ya = y - sy * c / 2
        return (min(xa, xa + sx * B), min(ya, ya + sy * L), max(xa, xa + sx * B),
                max(ya, ya + sy * L))
    # lindero
    if abs(x) < 1e-6 or abs(x - W) < 1e-6:
        sx = 1 if x < W / 2 else -1
        xa = x - sx * c / 2
        return (min(xa, xa + sx * B), y - L / 2, max(xa, xa + sx * B), y + L / 2)
    sy = 1 if y < D / 2 else -1
    ya = y - sy * c / 2
    return (x - L / 2, min(ya, ya + sy * B), x + L / 2, max(ya, ya + sy * B))


def _ejes(xs, ys, x0, y0, x1, y1, upm, ext=1.2):
    r = 4.0 * upm
    out = []
    for i, x in enumerate(sorted(set(xs))):
        dt._poly([(x, y0 - ext), (x, y1 + ext)], L_EJE, 13)
        acad.call("create_circle", {"x": x, "y": y1 + ext + r, "z": 0.0, "radius": r,
                                    "layer": L_EJE, "lineweight": 25, "colorIndex": None})
        dt.text(str(i + 1), x, y1 + ext + r, 3.0 * upm, layer=L_EJE, justify="middle_center")
        out.append(x)
    for j, y in enumerate(sorted(set(ys))):
        dt._poly([(x0 - ext, y), (x1 + ext, y)], L_EJE, 13)
        acad.call("create_circle", {"x": x0 - ext - r, "y": y, "z": 0.0, "radius": r,
                                    "layer": L_EJE, "lineweight": 25, "colorIndex": None})
        dt.text("ABCDEFGHJK"[j], x0 - ext - r, y, 3.0 * upm, layer=L_EJE, justify="middle_center")
    return out


def draw_foundation_plan(columns: list[dict[str, Any]], footing_types: dict[str, Any],
                         tie_beams: list[dict[str, Any]], lot: tuple[float, float],
                         upm: float, column_size: float = 0.30,
                         title: str = "PLANTA DE CIMENTACIÓN", text_mm: float = 2.0,
                         origin: tuple[float, float] = (0.0, 0.0)) -> dict[str, Any]:
    """columns: [{"x","y","type": marca de footing_types}], en coordenadas
    del MODELO; origin = dónde cae la esquina (0,0) del lote en el modelo.
    footing_types: {marca: dict de design_footing}. tie_beams: [{"x0","y0",
    "x1","y1","b","mark"}] (eje de la contratrabe). lot: (ancho, fondo)."""
    _capas()
    with acad.lote():
        r = _cimentacion(columns, footing_types, tie_beams, lot, upm, column_size, title,
                         text_mm, origin)
    return acad.resolver(r)


def _cimentacion(columns, tipos, ligas, lot, upm, c, title, text_mm, origin):
    h = text_mm * upm
    W, D = lot
    ox, oy = origin
    xs = [k["x"] for k in columns]
    ys = [k["y"] for k in columns]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    _ejes(xs, ys, x0, y0, x1, y1, upm)
    # Límite de propiedad.
    layers.ensure("LIMITE-PROPIEDAD", 8, 35, layers.LT_LIMITE)
    dt._poly([(ox, oy - 0.6), (ox, oy + D + 0.6)], "LIMITE-PROPIEDAD", 35)
    dt._poly([(ox + W, oy - 0.6), (ox + W, oy + D + 0.6)], "LIMITE-PROPIEDAD", 35)
    dt._poly([(ox - 0.6, oy), (ox + W + 0.6, oy)], "LIMITE-PROPIEDAD", 35)
    # Contratrabes (dos líneas por cara, entre zapatas).
    for t in ligas:
        b = t["b"]
        if abs(t["y0"] - t["y1"]) < 1e-6:
            _rect(min(t["x0"], t["x1"]), t["y0"] - b / 2, max(t["x0"], t["x1"]), t["y0"] + b / 2,
                  L_ZAP, 18)
            mx, my = (t["x0"] + t["x1"]) / 2, t["y0"] + b / 2 + 0.6 * h
            dt.text(t["mark"], mx, my, h * 1.2, justify="center")
        else:
            _rect(t["x0"] - b / 2, min(t["y0"], t["y1"]), t["x0"] + b / 2, max(t["y0"], t["y1"]),
                  L_ZAP, 18)
            mx, my = t["x0"] + b / 2 + 0.6 * h, (t["y0"] + t["y1"]) / 2
            dt.text(t["mark"], mx, my, h * 1.2, rotation=90)
    # Zapatas y columnas.
    for k in columns:
        z = tipos[k["type"]]
        zx0, zy0, zx1, zy1 = footing_rect(k, z, lot, origin)
        _rect(zx0, zy0, zx1, zy1, L_ZAP, 50)
        hc = _rect(k["x"] - c / 2, k["y"] - c / 2, k["x"] + c / 2, k["y"] + c / 2, L_COL, 50)
        dt._solid(hc, L_COL, 7)
        # Marca de la zapata dentro de ella, del lado lejano a la columna.
        tx = zx0 + 0.10 if abs(k["x"] - zx1) < abs(k["x"] - zx0) else zx1 - 0.10
        ty = zy1 - 0.12 - h * 1.4 if abs(k["y"] - zy0) < abs(k["y"] - zy1) else zy0 + 0.12
        dt.text(k["type"], tx, ty, h * 1.4, justify=None if tx < k["x"] else "right")
    # Cotas entre ejes.
    dt.chain(xs, "bottom", y0 - 1.5, upm)
    dt.chain(ys, "left", x0 - 1.5, upm)
    t = sym_mod.create_view_title(x0 - 1.6, y1 + 1.6 + 12 * upm, title,
                                  scale_text=f"ESC. 1:{round(upm * 1000)}", height=3.5 * upm,
                                  spaced=False)
    return {"box": [x0 - 1.6 - 30 * upm, y0 - 1.5 - 30 * upm, x1 + 1.6,
                    (t.get("box") or [0, 0, 0, y1 + 3])[3]]}


def draw_framing_plan(columns: list[dict[str, Any]], beams: list[dict[str, Any]],
                      panels: list[dict[str, Any]], upm: float,
                      openings: Optional[list[list[float]]] = None,
                      column_size: float = 0.30, title: str = "PLANTA ESTRUCTURAL",
                      text_mm: float = 2.0) -> dict[str, Any]:
    """beams: [{"x0","y0","x1","y1","b","mark"}] (eje); panels: [{"x0","y0",
    "x1","y1","mark","short": {"text"}, "long": {"text"}}]; openings:
    [[x0,y0,x1,y1]] huecos de losa (cubo de escalera) con su cruz."""
    _capas()
    with acad.lote():
        r = _losas(columns, beams, panels, upm, openings or [], column_size, title, text_mm)
    return acad.resolver(r)


def _losas(columns, beams, panels, upm, huecos, c, title, text_mm):
    h = text_mm * upm
    xs = [k["x"] for k in columns]
    ys = [k["y"] for k in columns]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    _ejes(xs, ys, x0, y0, x1, y1, upm)
    # Borde de losa.
    _rect(x0 - c / 2, y0 - c / 2, x1 + c / 2, y1 + c / 2, L_LOSA, 35)
    # Trabes (ocultas bajo la losa): dos líneas por cara.
    for t in beams:
        b = t["b"]
        if abs(t["y0"] - t["y1"]) < 1e-6:
            a, z = sorted((t["x0"], t["x1"]))
            for yy in (t["y0"] - b / 2, t["y0"] + b / 2):
                dt._poly([(a + c / 2, yy), (z - c / 2, yy)], L_TRA, 25)
            dt.text(t["mark"], (a + z) / 2, t["y0"] + b / 2 + 0.6 * h, h * 1.1, justify="center")
        else:
            a, z = sorted((t["y0"], t["y1"]))
            for xx in (t["x0"] - b / 2, t["x0"] + b / 2):
                dt._poly([(xx, a + c / 2), (xx, z - c / 2)], L_TRA, 25)
            dt.text(t["mark"], t["x0"] - b / 2 - 0.6 * h, (a + z) / 2, h * 1.1, rotation=90,
                    justify="center")
    # Columnas.
    for k in columns:
        hc = _rect(k["x"] - c / 2, k["y"] - c / 2, k["x"] + c / 2, k["y"] + c / 2, L_COL, 50)
        dt._solid(hc, L_COL, 7)
    # Huecos (cubo de escalera).
    for hx0, hy0, hx1, hy1 in huecos:
        _rect(hx0, hy0, hx1, hy1, L_LOSA, 35)
        dt._poly([(hx0, hy0), (hx1, hy1)], L_LOSA, 13)
        dt._poly([(hx0, hy1), (hx1, hy0)], L_LOSA, 13)
        dt.text("HUECO DE ESCALERA", (hx0 + hx1) / 2, (hy0 + hy1) / 2 + 0.3, h, justify="center")
    # Tableros: número y bastones de armado.
    for p in panels:
        px0, py0, px1, py1 = p["x0"], p["y0"], p["x1"], p["y1"]
        cx, cy = (px0 + px1) / 2, (py0 + py1) / 2
        r = 3.5 * upm
        acad.call("create_circle", {"x": cx, "y": cy, "z": 0.0, "radius": r, "layer": L_LOSA,
                                    "lineweight": 25, "colorIndex": None})
        dt.text(p["mark"], cx, cy, 2.5 * upm, layer=L_LOSA, justify="middle_center")
        corto_x = (px1 - px0) <= (py1 - py0)
        # Bastón del claro corto y del largo, con medio gancho en las puntas.
        largo_b = 0.55
        if corto_x:
            ax = [(px0 + 0.25, cy - largo_b), (px1 - 0.25, cy - largo_b)]
            ay = [(cx + largo_b, py0 + 0.25), (cx + largo_b, py1 - 0.25)]
        else:
            ay = [(cx - largo_b, py0 + 0.25), (cx - largo_b, py1 - 0.25)]
            ax = [(px0 + 0.25, cy + largo_b), (px1 - 0.25, cy + largo_b)]
        corto_pts, largo_pts = (ax, ay) if corto_x else (ay, ax)
        for pts, arm in ((corto_pts, p["short"]), (largo_pts, p["long"])):
            (a0, a1) = pts
            dt._poly([a0, a1], L_LOSA, 35)
            for q, sgn in ((a0, 1), (a1, -1)):
                if abs(a0[1] - a1[1]) < 1e-6:
                    dt._poly([q, (q[0], q[1] + 0.12)], L_LOSA, 35)
                else:
                    dt._poly([q, (q[0] + 0.12, q[1])], L_LOSA, 35)
            if abs(a0[1] - a1[1]) < 1e-6:
                dt.text(arm["text"], (a0[0] + a1[0]) / 2, a0[1] - 1.6 * h, h, layer=L_LOSA,
                        justify="center")
            else:
                dt.text(arm["text"], a0[0] - 0.6 * h, (a0[1] + a1[1]) / 2, h, layer=L_LOSA,
                        justify="center", rotation=90)
    dt.chain(xs, "bottom", y0 - 1.5, upm)
    dt.chain(ys, "left", x0 - 1.5, upm)
    t = sym_mod.create_view_title(x0 - 1.6, y1 + 1.6 + 12 * upm, title,
                                  scale_text=f"ESC. 1:{round(upm * 1000)}", height=3.5 * upm,
                                  spaced=False)
    return {"box": [x0 - 1.6 - 30 * upm, y0 - 1.5 - 30 * upm, x1 + 1.6,
                    (t.get("box") or [0, 0, 0, y1 + 3])[3]]}
