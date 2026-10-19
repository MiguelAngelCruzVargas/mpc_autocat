"""Fachadas con ornamento: almenas, vanos con arco, celosías, columnas,
barandales y escalones.

Primitivas paramétricas para elevaciones (vistas frontales) con carácter
decorativo: cada una dibuja UN motivo a partir de sus medidas, y una fachada
se compone llamándolas con las dimensiones del proyecto. Nada de un edificio
concreto vive acá. Unidades: las del dibujo (metros en los ejemplos).
"""
from __future__ import annotations

import math
from typing import Any, Optional, Sequence

import autocad_client as acad
import prim

LAYER_MURO = "FACHADA-MURO"
LAYER_MARCO = "FACHADA-MARCO"
LAYER_VANO = "FACHADA-VANO"
LAYER_CELOSIA = "FACHADA-CELOSIA"
LAYER_BARANDAL = "FACHADA-BARANDAL"
LAYER_ESCALON = "FACHADA-ESCALERA"
COLORES = {LAYER_MURO: 7, LAYER_MARCO: 14, LAYER_VANO: 134,
           LAYER_CELOSIA: 12, LAYER_BARANDAL: 42, LAYER_ESCALON: 42}


def _capas() -> None:
    for n, c in COLORES.items():
        prim.capa(n, c, 25)


def crenellation(x0: float, x1: float, y: float, merlon_width: float,
                 gap_width: float, height: float, layer: str = LAYER_MURO,
                 lw: int = 35) -> dict[str, Any]:
    """Remate de almenas: merlones de `merlon_width` separados por huecos de
    `gap_width`, sobre la línea de base `y` entre x0 y x1. Arranca y termina
    en merlón; el paso se reparte parejo (el ancho real de hueco puede variar
    unos mm y se devuelve en `gapWidth`)."""
    if x1 <= x0 or merlon_width <= 0 or gap_width <= 0 or height <= 0:
        raise ValueError("Medidas inválidas para las almenas.")
    n = max(1, int(round((x1 - x0 - merlon_width) / (merlon_width + gap_width))))
    gap = ((x1 - x0) - (n + 1) * merlon_width) / n
    if gap <= 0:
        raise ValueError("No entran los merlones en ese ancho.")
    prim.capa(layer, COLORES.get(layer, 7), lw)
    pts: list[prim.Point] = [(x0, y)]
    x = x0
    for k in range(n + 1):
        pts += [(x, y + height), (x + merlon_width, y + height), (x + merlon_width, y)]
        x += merlon_width
        if k < n:
            pts.append((x + gap, y))
            x += gap
    with acad.lote():
        h = prim.poly(pts, layer, False, lw)
    return {"handle": h, "merlons": n + 1, "gapWidth": round(gap, 4)}


def _arch_pts(x: float, y: float, w: float, h: float, rise: float
              ) -> tuple[list[prim.Point], list[float]]:
    """Contorno de un vano: rectángulo (x, y, w, h) coronado por un arco
    de flecha `rise` (rise = w/2 es un medio punto)."""
    if rise <= 0:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], [0.0] * 4
    # bulge de un arco de cuerda w y flecha rise: tan(theta/4), theta ángulo central
    c = w
    R = (c * c / 4 + rise * rise) / (2 * rise)
    theta = 2 * math.asin(min(1.0, c / (2 * R)))
    if rise > R:                       # más que un semicírculo
        theta = 2 * math.pi - theta
    bulge = -math.tan(theta / 4)       # horario al ir de derecha a izquierda
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    # recorrido antihorario: (x,y) -> (x+w,y) -> (x+w,y+h) -> arco hacia (x,y+h)
    return pts, [0.0, 0.0, -bulge, 0.0]


def arched_opening(x: float, y: float, width: float, height: float, rise: float,
                   cols: int = 2, rows: int = 2, frame: float = 0.0,
                   layer: str = LAYER_VANO, frame_layer: str = LAYER_MARCO,
                   lw: int = 25) -> dict[str, Any]:
    """Vano (ventana o puerta) de altura total `height` (arco incluido) con
    arco de flecha `rise`: marco exterior, marco interior a `frame`, y
    divisiones verticales `cols` y horizontales `rows` en la parte recta. El
    arco lleva divisiones radiales. rise=0 da un vano rectangular."""
    if width <= 0 or height <= 0 or rise < 0 or rise >= height:
        raise ValueError("Medidas inválidas: 0 <= rise < height.")
    _capas()
    f = frame if frame > 0 else min(width, height) * 0.06
    body = height - rise
    hs: list[str] = []
    with acad.lote():
        pts, bul = _arch_pts(x, y, width, body, rise)
        hs.append(prim.poly(pts, frame_layer, True, lw, None, bul))
        if width - 2 * f > 0 and body - f > 0:
            pts, bul = _arch_pts(x + f, y + f, width - 2 * f, body - f,
                                 max(0.0, rise - f * 0.5))
            hs.append(prim.poly(pts, layer, True, lw, None, bul))
        for i in range(1, max(1, cols)):
            xx = x + f + (width - 2 * f) * i / max(1, cols)
            hs.append(prim.line((xx, y + f), (xx, y + body), layer, 13))
        for j in range(1, max(1, rows)):
            yy = y + f + (body - f) * j / max(1, rows)
            hs.append(prim.line((x + f, yy), (x + width - f, yy), layer, 13))
        if rise > 0:
            cx, cy = x + width / 2, y + body
            for k in range(1, 5):
                a = math.radians(180.0 * k / 5)
                r = rise * 0.95
                hs.append(prim.line((cx, cy), (cx + (width / 2 - f) * math.cos(a),
                                               cy + r * math.sin(a)), layer, 13))
    return {"handles": hs, "box": [x, y, x + width, y + height]}


def lattice_panel(x0: float, y0: float, x1: float, y1: float, pitch: float,
                  angle_deg: float = 45.0, border: float = 0.0,
                  layer: str = LAYER_CELOSIA, frame_layer: str = LAYER_MARCO,
                  lw: int = 13) -> dict[str, Any]:
    """Celosía de rombos: dos familias de diagonales a ±`angle_deg` con paso
    `pitch` (medido en horizontal), recortadas al rectángulo, dentro de un
    marco doble separado `border`."""
    if x1 <= x0 or y1 <= y0 or pitch <= 0 or not 0 < angle_deg < 90:
        raise ValueError("Medidas inválidas para la celosía.")
    _capas()
    b = border if border > 0 else min(x1 - x0, y1 - y0) * 0.06
    ix0, iy0, ix1, iy1 = x0 + b, y0 + b, x1 - b, y1 - b
    if ix1 <= ix0 or iy1 <= iy0:
        raise ValueError("El borde se come la celosía.")
    m = 1.0 / math.tan(math.radians(angle_deg))     # dx por unidad de dy
    segs: list[tuple[prim.Point, prim.Point]] = []
    h = iy1 - iy0
    for fam in (1, -1):
        s = fam * m                                   # pendiente dx/dy
        k = (ix0 - max(s, 0.0) * h) - pitch           # x en y = iy0 de la primera recta
        k = ix0 - (h * m if fam == 1 else 0.0) - pitch
        while k < ix1 + pitch:
            # x(y) = k + s*(y - iy0); recorte a x en [ix0, ix1] y y en [iy0, iy1]
            ya = iy0 + (ix0 - k) / s
            yb = iy0 + (ix1 - k) / s
            lo, hi = max(iy0, min(ya, yb)), min(iy1, max(ya, yb))
            if hi - lo > 1e-6:
                segs.append(((k + s * (lo - iy0), lo), (k + s * (hi - iy0), hi)))
            k += pitch
    hs: list[str] = []
    with acad.lote():
        hs.append(prim.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], frame_layer, True, 25))
        hs.append(prim.poly([(ix0, iy0), (ix1, iy0), (ix1, iy1), (ix0, iy1)], frame_layer, True, 13))
        for p, q in segs:
            hs.append(prim.line(p, q, layer, lw))
    return {"handles": hs, "diagonals": len(segs), "box": [x0, y0, x1, y1]}


def column(x: float, y0: float, y1: float, width: float, twisted: bool = True,
           layer: str = LAYER_MARCO, lw: int = 25) -> dict[str, Any]:
    """Columna con base y capitel; `twisted` le dibuja el fuste torneado
    (diagonales cortas)."""
    if y1 <= y0 or width <= 0:
        raise ValueError("Medidas inválidas para la columna.")
    _capas()
    w2 = width / 2
    cap = min(width * 0.5, (y1 - y0) * 0.12)
    hs: list[str] = []
    with acad.lote():
        hs.append(prim.poly([(x - w2 * 1.35, y0), (x + w2 * 1.35, y0),
                             (x + w2 * 1.35, y0 + cap), (x - w2 * 1.35, y0 + cap)], layer, True, lw))
        hs.append(prim.poly([(x - w2 * 1.35, y1 - cap), (x + w2 * 1.35, y1 - cap),
                             (x + w2 * 1.35, y1), (x - w2 * 1.35, y1)], layer, True, lw))
        hs.append(prim.poly([(x - w2, y0 + cap), (x + w2, y0 + cap),
                             (x + w2, y1 - cap), (x - w2, y1 - cap)], layer, True, 13))
        if twisted:
            paso = width * 0.9
            yy = y0 + cap
            while yy + paso < y1 - cap:
                hs.append(prim.line((x - w2, yy), (x + w2, yy + paso * 0.6), layer, 5))
                yy += paso
    return {"handles": hs}


def balustrade(x0: float, x1: float, y: float, height: float, balusters: int = 0,
               pitch: float = 0.0, layer: str = LAYER_BARANDAL, lw: int = 18
               ) -> dict[str, Any]:
    """Barandal: pasamanos arriba, base abajo y balaustres (círculo de remate
    + fuste) repartidos parejo. Da `balusters` o `pitch`."""
    if x1 <= x0 or height <= 0:
        raise ValueError("Medidas inválidas para el barandal.")
    _capas()
    n = balusters or max(2, int((x1 - x0) / (pitch or height * 0.25)))
    hs: list[str] = []
    rail = height * 0.08
    with acad.lote():
        hs.append(prim.poly([(x0, y), (x1, y), (x1, y + rail), (x0, y + rail)], layer, True, lw))
        hs.append(prim.poly([(x0, y + height - rail), (x1, y + height - rail),
                             (x1, y + height), (x0, y + height)], layer, True, lw))
        for k in range(n):
            xx = x0 + (x1 - x0) * (k + 0.5) / n
            hs.append(prim.line((xx, y + rail), (xx, y + height - rail), layer, 13))
            hs.append(prim.circle((xx, y + height * 0.55), (x1 - x0) / n * 0.28, layer, 13))
    return {"handles": hs, "balusters": n}


def steps(x0: float, x1: float, y: float, count: int, rise: float, run: float,
          layer: str = LAYER_ESCALON, lw: int = 25) -> dict[str, Any]:
    """Escalones en alzado, centrados: el de abajo ocupa todo el ancho
    [x0, x1] y cada uno de arriba se retrae `run` por lado."""
    if count < 1 or rise <= 0 or x1 <= x0 or run < 0:
        raise ValueError("Medidas inválidas para la escalera.")
    _capas()
    hs: list[str] = []
    with acad.lote():
        for k in range(count):
            a, b = x0 + run * k, x1 - run * k
            if b <= a:
                break
            hs.append(prim.poly([(a, y + rise * k), (b, y + rise * k),
                                 (b, y + rise * (k + 1)), (a, y + rise * (k + 1))],
                                layer, True, lw))
    return {"handles": hs, "steps": len(hs)}
