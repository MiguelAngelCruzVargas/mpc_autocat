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

Lo que se aprendió mirándolas en AutoCAD (y que ahora está resuelto):
  - la marca de una trabe va en el MEDIO DEL CLARO más largo, no en el
    medio de la trabe: con un número par de claros ese punto es una columna
    y la marca caía encima del macizo;
  - un tablero con hueco (cubo de escalera) anota en la parte libre y sus
    bastones no cruzan el hueco;
  - la etiqueta de la zapata va en un cuadrante que no cruce ninguna
    contratrabe; si no cabe, afuera;
  - las cotas se dibujan ANTES que los ejes y el título va debajo de la
    cadena total, no encima;
  - cada columna lleva su marca, y la lámina su CUADRO (trabes o zapatas)
    y sus NOTAS: sin ellos la planta no se puede construir.
"""
from __future__ import annotations

from typing import Any, Optional

import annotation as ann
import autocad_client as acad
import detalle as dt
import layers
import symbols as sym_mod

L_COL = "EST-COLUMNAS"
L_ZAP = "EST-ZAPATAS"
L_TRA = "EST-TRABES"
L_LOSA = "EST-LOSAS"
L_EJE = "EJES"
L_TXT = "EST-TEXTOS"


def _capas():
    layers.ensure(L_COL, 7, 50)
    layers.ensure(L_ZAP, 7, 50)
    layers.ensure(L_TRA, 7, 25, layers.LT_OCULTO)
    layers.ensure(L_LOSA, 12, 25)
    layers.ensure(L_EJE, 32, 13, layers.LT_EJE)
    layers.ensure(L_TXT, 7, 0)
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


# ------------------------------------------------------------ ubicación

def _claro_mas_largo(a: float, z: float, cortes: list[float],
                     medios: Optional[dict[float, float]] = None) -> float:
    """Punto medio del tramo libre más largo de [a, z] entre los 'cortes'
    (columnas o zapatas sobre la línea). medios: semiancho a descontar en
    cada corte (el macizo de la columna o la zapata)."""
    pts = sorted({a, z, *[c for c in cortes if a - 1e-6 <= c <= z + 1e-6]})
    mejor, pos = -1.0, (a + z) / 2
    for p, q in zip(pts, pts[1:]):
        lo = p + (medios or {}).get(round(p, 5), 0.0)
        hi = q - (medios or {}).get(round(q, 5), 0.0)
        if hi - lo > mejor:
            mejor, pos = hi - lo, (lo + hi) / 2
    return pos


def _ejes(xs, ys, x0, y0, x1, y1, upm, ext_top=1.2, ext_left=1.2):
    """Ejes con globo: los verticales rematan arriba, los horizontales a la
    izquierda, AFUERA de las cadenas de cotas (ext_left ya las descuenta)."""
    r = 4.0 * upm
    for i, x in enumerate(sorted(set(xs))):
        dt._poly([(x, y0 - ext_top), (x, y1 + ext_top)], L_EJE, 13)
        acad.call("create_circle", {"x": x, "y": y1 + ext_top + r, "z": 0.0, "radius": r,
                                    "layer": L_EJE, "lineweight": 25, "colorIndex": None})
        dt.text(str(i + 1), x, y1 + ext_top + r, 3.0 * upm, layer=L_EJE, justify="middle_center")
    for j, y in enumerate(sorted(set(ys))):
        dt._poly([(x0 - ext_left, y), (x1 + 1.2, y)], L_EJE, 13)
        acad.call("create_circle", {"x": x0 - ext_left - r, "y": y, "z": 0.0, "radius": r,
                                    "layer": L_EJE, "lineweight": 25, "colorIndex": None})
        dt.text("ABCDEFGHJK"[j], x0 - ext_left - r, y, 3.0 * upm, layer=L_EJE,
                justify="middle_center")
    return {"top": y1 + ext_top + 2 * r, "left": x0 - ext_left - 2 * r}


def _cotas_y_ejes(xs, ys, x0, y0, x1, y1, upm):
    """Cotas primero (reservan su franja), ejes después y por afuera."""
    lin_b = dt.chain(xs, "bottom", y0 - 1.2, upm)
    lin_l = dt.chain(ys, "left", x0 - 1.2, upm)
    ext_left = (x0 - lin_l) + 6 * upm
    e = _ejes(xs, ys, x0, y0, x1, y1, upm, ext_top=1.2, ext_left=ext_left)
    return lin_b, e


def _titulo(title, upm, x0, x1, y0, y1, lin_b, ejes):
    if not title:          # la lámina (compose_layout) pone el título en el papel
        return {"box": [ejes["left"], lin_b - 3 * upm, x1 + 1.6, ejes["top"]]}
    t = sym_mod.create_view_title(title=title, scale_text=f"ESC. 1:{round(upm * 1000)}",
                                  spaced=False,
                                  figure_box=[ejes["left"], lin_b - 3 * upm, x1 + 1.6, ejes["top"]])
    return t


def _notas(notes: list[str], x: float, y: float, upm: float, titulo: str = "NOTAS:") -> float:
    """Bloque de notas numeradas (texto de 2 mm) desde (x, y) hacia abajo.
    Devuelve la y final."""
    h = 2.0 * upm
    dt.text(titulo, x, y, h * 1.1, layer=L_TXT)
    yy = y - 2.2 * h
    for i, n in enumerate(notes, 1):
        for k, linea in enumerate(dt.wrap(f"{i}. {n}", 70)):
            dt.text(("    " if k else "") + linea, x, yy, h, layer=L_TXT)
            yy -= 1.8 * h
    return yy


def _marcas_columnas(columns, c, h, mark):
    for k in columns:
        m = k.get("mark") or mark
        if m:
            dt.text(m, k["x"] + c / 2 + 0.4 * h, k["y"] + c / 2 + 0.4 * h, h * 0.9, layer=L_TXT)


# ------------------------------------------------------------ cimentación

def draw_foundation_plan(columns: list[dict[str, Any]], footing_types: dict[str, Any],
                         tie_beams: list[dict[str, Any]], lot: tuple[float, float],
                         upm: float, column_size: float = 0.30,
                         title: str = "PLANTA DE CIMENTACIÓN", text_mm: float = 2.0,
                         origin: tuple[float, float] = (0.0, 0.0),
                         column_mark: str = "C-1", notes: Optional[list[str]] = None,
                         table: bool = True) -> dict[str, Any]:
    """columns: [{"x","y","type"}], en coordenadas del MODELO; origin = dónde
    cae la esquina (0,0) del lote en el modelo. footing_types: {marca: dict de
    design_footing}. tie_beams: [{"x0","y0","x1","y1","b","mark"}] (eje de la
    contratrabe). lot: (ancho, fondo). Con table dibuja el CUADRO DE ZAPATAS a
    la derecha; notes agrega el bloque de notas debajo del cuadro."""
    _capas()
    with acad.lote():
        r = _cimentacion(columns, footing_types, tie_beams, lot, upm, column_size, title,
                         text_mm, origin, column_mark, notes or [], table)
    return acad.resolver(r)


def _cuadrante_libre(k, rect, ties, c, h_txt, ancho_txt):
    """Esquina de la zapata donde la etiqueta no cruza ninguna contratrabe:
    las contratrabes pasan por el centro de la columna, así que cada cuadrante
    libre mide (semi-zapata − semi-contratrabe). Devuelve (x, y, justify) o
    None si no cabe en ninguno."""
    zx0, zy0, zx1, zy1 = rect
    bx = by = c / 2
    for t in ties:
        if abs(t["y0"] - t["y1"]) < 1e-6 and abs(t["y0"] - k["y"]) < 1e-6 \
                and min(t["x0"], t["x1"]) - 1e-6 <= k["x"] <= max(t["x0"], t["x1"]) + 1e-6:
            by = max(by, t["b"] / 2)
        if abs(t["x0"] - t["x1"]) < 1e-6 and abs(t["x0"] - k["x"]) < 1e-6 \
                and min(t["y0"], t["y1"]) - 1e-6 <= k["y"] <= max(t["y0"], t["y1"]) + 1e-6:
            bx = max(bx, t["b"] / 2)
    m = 0.08
    cuadrantes = [
        ((zx0 + m, k["x"] - bx - m), (zy0 + m, k["y"] - by - m), None),           # abajo-izq
        ((k["x"] + bx + m, zx1 - m), (zy0 + m, k["y"] - by - m), "right"),        # abajo-der
        ((zx0 + m, k["x"] - bx - m), (k["y"] + by + m, zy1 - m), None),           # arriba-izq
        ((k["x"] + bx + m, zx1 - m), (k["y"] + by + m, zy1 - m), "right"),        # arriba-der
    ]
    for (xa, xb), (ya, yb), just in cuadrantes:
        if xb - xa >= ancho_txt and yb - ya >= h_txt:
            return ((xa if just is None else xb), ya, just)
    return None


def _cimentacion(columns, tipos, ligas, lot, upm, c, title, text_mm, origin, column_mark,
                 notes, table):
    h = text_mm * upm
    W, D = lot
    ox, oy = origin
    xs = [k["x"] for k in columns]
    ys = [k["y"] for k in columns]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    # Límite de propiedad.
    layers.ensure("LIMITE-PROPIEDAD", 8, 35, layers.LT_LIMITE)
    dt._poly([(ox, oy - 0.6), (ox, oy + D + 0.6)], "LIMITE-PROPIEDAD", 35)
    dt._poly([(ox + W, oy - 0.6), (ox + W, oy + D + 0.6)], "LIMITE-PROPIEDAD", 35)
    dt._poly([(ox - 0.6, oy), (ox + W + 0.6, oy)], "LIMITE-PROPIEDAD", 35)
    # Zapatas: rectángulos primero (los necesitan las marcas de contratrabe).
    rects = {}
    for k in columns:
        z = tipos[k["type"]]
        rects[id(k)] = tuple(round(v, 4) for v in (k.get("rect") or footing_rect(k, z, lot, origin)))
    # Contratrabes (dos líneas por cara) con la marca en el claro más largo
    # entre zapatas, no en el medio de la pieza (que suele ser una zapata).
    for t in ligas:
        b = t["b"]
        if abs(t["y0"] - t["y1"]) < 1e-6:
            a, z = sorted((t["x0"], t["x1"]))
            _rect(a, t["y0"] - b / 2, z, t["y0"] + b / 2, L_ZAP, 18)
            cortes = {}
            for k in columns:
                if abs(k["y"] - t["y0"]) < 1e-6:
                    r = rects[id(k)]
                    cortes[round(k["x"], 5)] = (r[2] - r[0]) / 2
            mx = _claro_mas_largo(a, z, list(cortes), cortes)
            dt.text(t["mark"], mx, t["y0"] + b / 2 + 0.6 * h, h * 1.2, justify="center", layer=L_TXT)
        else:
            a, z = sorted((t["y0"], t["y1"]))
            _rect(t["x0"] - b / 2, a, t["x0"] + b / 2, z, L_ZAP, 18)
            cortes = {}
            for k in columns:
                if abs(k["x"] - t["x0"]) < 1e-6:
                    r = rects[id(k)]
                    cortes[round(k["y"], 5)] = (r[3] - r[1]) / 2
            my = _claro_mas_largo(a, z, list(cortes), cortes)
            # rotado 90 el texto crece hacia −x: la inserción va una altura más allá
            dt.text(t["mark"], t["x0"] + b / 2 + 0.6 * h + 1.2 * h, my, h * 1.2, rotation=90,
                    layer=L_TXT)
    # Zapatas y columnas. Una columna puede traer 'rect' (la zapata
    # combinada que comparte con otra): se dibuja UNA vez.
    dibujadas = {}
    afuera = []
    for k in columns:
        rect = rects[id(k)]
        if rect not in dibujadas:
            zx0, zy0, zx1, zy1 = rect
            _rect(zx0, zy0, zx1, zy1, L_ZAP, 50)
            ht = h * 1.4
            pos = _cuadrante_libre(k, rect, ligas, c, ht, dt.text_width(k["type"], ht))
            if pos:
                tx, ty, just = pos
                dt.text(k["type"], tx, ty, ht, justify=just, layer=L_TXT)
            else:
                afuera.append(k["type"])
                dt.text(k["type"], zx1 + 0.10, zy0, ht, layer=L_TXT)
            dibujadas[rect] = k["type"]
        hc = _rect(k["x"] - c / 2, k["y"] - c / 2, k["x"] + c / 2, k["y"] + c / 2, L_COL, 50)
        dt._solid(hc, L_COL, 7)
    _marcas_columnas(columns, c, h, column_mark)
    # Revisión: dos zapatas que se pisan no son dos zapatas, son una
    # combinada. Pasó: en un eje con columnas a 2.0 m las aisladas se
    # encimaban y la planta se veía "bien".
    encimadas = []
    rs = list(dibujadas.items())
    for i in range(len(rs)):
        for j in range(i + 1, len(rs)):
            (a, ma), (b, mb) = rs[i], rs[j]
            if a[0] < b[2] - 1e-6 and b[0] < a[2] - 1e-6 and a[1] < b[3] - 1e-6 and b[1] < a[3] - 1e-6:
                encimadas.append({"a": ma, "b": mb, "rect_a": list(a), "rect_b": list(b)})
    # Cotas ANTES que los ejes; el título debajo de la cadena total.
    zb = min(r[1] for r in rects.values())
    zl = min(r[0] for r in rects.values())
    lin_b, ejes = _cotas_y_ejes(xs, ys, zl, zb, max(r[2] for r in rects.values()),
                                max(r[3] for r in rects.values()), upm)
    t = _titulo(title, upm, x0, x1, y0, y1, lin_b, ejes)
    # Cuadro de zapatas y notas, a la derecha de la planta.
    right = max(r[2] for r in rects.values()) + 1.6
    tx0 = right + 1.5
    ty = max(r[3] for r in rects.values())
    if table:
        filas = [["MARCA", "B x L (m)", "PERALTE", "ARMADO X", "ARMADO Y", "DESPLANTE"]]
        for marca, z in tipos.items():
            filas.append([marca, f"{z['B']:.2f} x {z['L']:.2f}", f"{z['h'] * 100:.0f} cm",
                          z["bars_x"]["text"], z["bars_y"]["text"], f"{z['depth']:.2f} m"])
        anchos = [a * upm for a in (14, 22, 16, 22, 22, 18)]
        tb = ann.create_table(x=tx0, y=ty, rows=filas, col_widths=anchos, title="CUADRO DE ZAPATAS",
                              align=["center", "center", "center", "center", "center", "center"],
                              layer=L_TXT, scale=upm)
        ty = tb["bottom"] - 3.0 * h
        right = max(right, tb["right"])
    if notes:
        _notas(notes, tx0, ty, upm)
        right = max(right, tx0 + 70 * 0.92 * 2.0 * upm)
    return {"box": [ejes["left"], min(lin_b - 3 * upm, t["box"][1]), right, ejes["top"]],
            "overlaps": encimadas,
            "warnings": [f"Zapatas encimadas {e['a']} / {e['b']}: van COMBINADAS"
                         for e in encimadas]
            + ([f"Etiqueta de zapata afuera del contorno en {len(afuera)} zapata(s) "
                f"({', '.join(sorted(set(afuera)))}): adentro cruzaba una contratrabe"]
               if afuera else [])}


# ------------------------------------------------------------ entrepiso

def draw_framing_plan(columns: list[dict[str, Any]], beams: list[dict[str, Any]],
                      panels: list[dict[str, Any]], upm: float,
                      openings: Optional[list[list[float]]] = None,
                      column_size: float = 0.30, title: str = "PLANTA ESTRUCTURAL",
                      text_mm: float = 2.0, column_mark: str = "C-1",
                      beam_designs: Optional[dict[str, dict[str, Any]]] = None,
                      slab_thickness: float = 0.0,
                      notes: Optional[list[str]] = None) -> dict[str, Any]:
    """beams: [{"x0","y0","x1","y1","b","mark"}] (eje); panels: [{"x0","y0",
    "x1","y1","mark","short": {"text"}, "long": {"text"}}]; openings:
    [[x0,y0,x1,y1]] huecos de losa (cubo de escalera) con su cruz.
    beam_designs: {marca: dict de design_beam} -> CUADRO DE TRABES a la
    derecha; slab_thickness (m) y notes -> bloque de NOTAS."""
    _capas()
    with acad.lote():
        r = _losas(columns, beams, panels, upm, openings or [], column_size, title, text_mm,
                   column_mark, beam_designs or {}, slab_thickness, notes or [])
    return acad.resolver(r)


def _zona_libre(p, huecos):
    """El rectángulo del tablero que queda libre de huecos: si un hueco lo
    cruza, la franja (izq/der/arriba/abajo del hueco) de mayor área."""
    px0, py0, px1, py1 = p["x0"], p["y0"], p["x1"], p["y1"]
    libre = (px0, py0, px1, py1)
    for hx0, hy0, hx1, hy1 in huecos:
        if hx0 >= px1 or hx1 <= px0 or hy0 >= py1 or hy1 <= py0:
            continue
        cand = [(px0, py0, hx0, py1), (hx1, py0, px1, py1), (px0, hy1, px1, py1), (px0, py0, px1, hy0)]
        cand = [c for c in cand if c[2] - c[0] > 0.6 and c[3] - c[1] > 0.6]
        if not cand:
            return None
        libre = max(cand, key=lambda c: (c[2] - c[0]) * (c[3] - c[1]))
    return libre


def _losas(columns, beams, panels, upm, huecos, c, title, text_mm, column_mark, disenos,
           slab_thickness, notes):
    h = text_mm * upm
    xs = [k["x"] for k in columns]
    ys = [k["y"] for k in columns]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    # Borde de losa.
    _rect(x0 - c / 2, y0 - c / 2, x1 + c / 2, y1 + c / 2, L_LOSA, 35)
    # Trabes (ocultas bajo la losa): dos líneas por cara; la marca en el
    # medio del claro más largo entre columnas.
    for t in beams:
        b = t["b"]
        if abs(t["y0"] - t["y1"]) < 1e-6:
            a, z = sorted((t["x0"], t["x1"]))
            for yy in (t["y0"] - b / 2, t["y0"] + b / 2):
                dt._poly([(a + c / 2, yy), (z - c / 2, yy)], L_TRA, 25)
            cols = [k["x"] for k in columns if abs(k["y"] - t["y0"]) < 1e-6]
            mx = _claro_mas_largo(a, z, cols, {round(v, 5): c / 2 for v in cols})
            dt.text(t["mark"], mx, t["y0"] + b / 2 + 0.6 * h, h * 1.1, justify="center", layer=L_TXT)
        else:
            a, z = sorted((t["y0"], t["y1"]))
            for xx in (t["x0"] - b / 2, t["x0"] + b / 2):
                dt._poly([(xx, a + c / 2), (xx, z - c / 2)], L_TRA, 25)
            cols = [k["y"] for k in columns if abs(k["x"] - t["x0"]) < 1e-6]
            my = _claro_mas_largo(a, z, cols, {round(v, 5): c / 2 for v in cols})
            dt.text(t["mark"], t["x0"] - b / 2 - 0.6 * h, my, h * 1.1, rotation=90,
                    justify="center", layer=L_TXT)
    # Columnas.
    for k in columns:
        hc = _rect(k["x"] - c / 2, k["y"] - c / 2, k["x"] + c / 2, k["y"] + c / 2, L_COL, 50)
        dt._solid(hc, L_COL, 7)
    _marcas_columnas(columns, c, h, column_mark)
    # Huecos (cubo de escalera).
    for hx0, hy0, hx1, hy1 in huecos:
        _rect(hx0, hy0, hx1, hy1, L_LOSA, 35)
        dt._poly([(hx0, hy0), (hx1, hy1)], L_LOSA, 13)
        dt._poly([(hx0, hy1), (hx1, hy0)], L_LOSA, 13)
        dt.text("HUECO", (hx0 + hx1) / 2, (hy0 + hy1) / 2 + 0.6 * h, h, justify="center", layer=L_TXT)
        dt.text("DE ESCALERA", (hx0 + hx1) / 2, (hy0 + hy1) / 2 - 1.4 * h, h, justify="center",
                layer=L_TXT)
    # Tableros: número y bastones de armado, en la zona libre de huecos.
    sin_lugar = []
    for p in panels:
        zona = _zona_libre(p, huecos)
        if zona is None:
            sin_lugar.append(p["mark"])
            continue
        px0, py0, px1, py1 = zona
        cx, cy = (px0 + px1) / 2, (py0 + py1) / 2
        r = 3.5 * upm
        acad.call("create_circle", {"x": cx, "y": cy, "z": 0.0, "radius": r, "layer": L_LOSA,
                                    "lineweight": 25, "colorIndex": None})
        dt.text(p["mark"], cx, cy, 2.5 * upm, layer=L_LOSA, justify="middle_center")
        corto_x = (p["x1"] - p["x0"]) <= (p["y1"] - p["y0"])
        # Bastón del claro corto y del largo, con medio gancho en las puntas,
        # separados del círculo y DENTRO de la zona libre: el lado del
        # círculo donde va cada bastón (y su texto) se elige según quepa; en
        # la franja angosta junto a un hueco el texto caía sobre el hueco.
        sep = r + 2.0 * h
        mx, my = min(0.25, (px1 - px0) * 0.1), min(0.25, (py1 - py0) * 0.1)
        # vertical: a la izquierda del círculo si cabe el texto (2.2 h más)
        cabe_izq = cx - sep - 2.2 * h >= px0 + mx
        cabe_der = cx + sep + 2.2 * h <= px1 - mx
        if corto_x:
            vx = cx + sep if cabe_der else cx - sep
        else:
            vx = cx - sep if cabe_izq else cx + sep
        # Franja angosta (junto a un hueco): el texto del bastón vertical no
        # cabe a ningún lado sin pisar el borde; va horizontal sobre su punta.
        texto_v_arriba = not (cabe_izq or cabe_der)
        # horizontal: abajo del círculo si cabe el texto, si no arriba
        hy = cy - sep if cy - sep - 2.2 * h >= py0 + my else cy + sep
        if not corto_x:
            hy = cy + sep if cy + sep + 2.2 * h <= py1 - my else cy - sep
        ax = [(px0 + mx, hy), (px1 - mx, hy)]
        # Con el texto sobre la punta, el bastón se acorta para que el texto
        # también quede dentro del tablero (y no sobre la trabe de arriba).
        ay = [(vx, py0 + my), (vx, py1 - my - (2.4 * h if texto_v_arriba else 0.0))]
        corto_pts, largo_pts = (ax, ay) if corto_x else (ay, ax)
        for pts, arm in ((corto_pts, p["short"]), (largo_pts, p["long"])):
            (a0, a1) = pts
            dt._poly([a0, a1], L_LOSA, 35)
            horiz = abs(a0[1] - a1[1]) < 1e-6
            for q in (a0, a1):
                dt._poly([q, (q[0], q[1] + 0.12)] if horiz else [q, (q[0] + 0.12, q[1])], L_LOSA, 35)
            if horiz:
                ty = a0[1] - 1.6 * h if a0[1] < cy else a0[1] + 0.6 * h
                dt.text(arm["text"], (a0[0] + a1[0]) / 2, ty, h, layer=L_LOSA, justify="center")
            elif texto_v_arriba:
                # Centrado en la FRANJA libre, no en el bastón: centrado en la
                # barra, medio texto se salía de la franja y caía sobre la
                # trabe y el eje de al lado.
                ancho = 0.75 * h * len(arm["text"])
                tcx = min(max((px0 + px1) / 2, px0 + mx + ancho / 2), px1 - mx - ancho / 2)
                dt.text(arm["text"], tcx, max(a0[1], a1[1]) + 0.6 * h, h, layer=L_LOSA,
                        justify="center")
            else:
                # rotado 90: el texto crece hacia −x desde su inserción
                tx = a0[0] - 0.8 * h if a0[0] < cx else a0[0] + 0.8 * h + h
                dt.text(arm["text"], tx, (a0[1] + a1[1]) / 2, h, layer=L_LOSA,
                        justify="center", rotation=90)
    # Cotas ANTES que los ejes; el título debajo de la cadena total.
    lin_b, ejes = _cotas_y_ejes(xs, ys, x0, y0, x1, y1, upm)
    t = _titulo(title, upm, x0, x1, y0, y1, lin_b, ejes)
    right = x1 + 1.6
    tx0 = right + 1.5
    ty = y1 + c / 2
    if disenos:
        filas = [["MARCA", "SECCIÓN (cm)", "LECHO INFERIOR", "LECHO SUPERIOR", "ESTRIBOS"]]
        for marca, d in disenos.items():
            filas.append([marca, f"{d['b'] * 100:.0f} x {d['h'] * 100:.0f}", d["bottom"]["text"],
                          d["top"]["text"], d["stirrups"]["text"]])
        anchos = [a * upm for a in (14, 22, 26, 26, 24)]
        tb = ann.create_table(x=tx0, y=ty, rows=filas, col_widths=anchos, title="CUADRO DE TRABES",
                              align=["center"] * 5, layer=L_TXT, scale=upm)
        ty = tb["bottom"] - 3.0 * h
        right = max(right, tb["right"])
    todas = list(notes)
    if slab_thickness:
        todas.insert(0, f"Losa maciza de {slab_thickness * 100:.0f} cm de espesor; el armado de cada "
                        "tablero se indica con sus bastones (varilla @ separación en cm).")
    if todas:
        _notas(todas, tx0, ty, upm)
        right = max(right, tx0 + 70 * 0.92 * 2.0 * upm)
    return {"box": [ejes["left"], min(lin_b - 3 * upm, t["box"][1]), right, ejes["top"]],
            "warnings": [f"Tablero {m}: el hueco lo ocupa casi entero, sin lugar para anotarlo"
                         for m in sin_lugar]}
