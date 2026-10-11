"""Grafismo de detalle constructivo: lo que separa un dibujo de oficio de un
esquema hecho con rectángulos.

Primitivas que NO saben de zapatas -- sirven para cualquier detalle:

  break_line      símbolo de corte (la Z) donde una pieza sigue más allá
  jagged_line     borde irregular de una masa de terreno cortada
  rough_line      junta rugosa / superficie rayada (dientes finos)
  chair           calzo / silleta bajo una parrilla
  callouts        llamadas ordenadas a un lado: punto en el elemento,
                  quiebre, renglón con el texto ENCIMA -- sin cruzarse
  dimension       una cota suelta con texto propio ("lb = <>")

Todo se mide en mm de PAPEL y se convierte con 'upm' (unidades del modelo
por mm de papel), para que un detalle a 1:10 y otro a 1:25 salgan con el
mismo grafismo impreso.
"""
from __future__ import annotations

import math
import random
from typing import Any, Optional

import annotation as ann_mod
import autocad_client as acad
import layers
import space

LAYER_TEXTOS = "TEXTOS"
LAYER_LLAMADAS = "LLAMADAS"
LAYER_COTAS = "COTAS"


def _poly(points, layer, lw, closed=False, color=None, bulges=None,
          width: float = 0.0) -> str:
    return acad.call("create_polyline", {
        "points": [[float(p[0]), float(p[1])] for p in points], "closed": closed,
        "layer": layer, "lineweight": lw, "colorIndex": color,
        **({"bulges": bulges} if bulges else {}),
        **({"width": width} if width > 0 else {})})["handle"]


def offset_open(pts, d: float) -> list[tuple[float, float]]:
    """Paralela a una polilínea abierta, a la DERECHA del sentido de avance,
    con las esquinas a inglete (intersección de los tramos corridos)."""
    lineas = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        L = math.dist((x0, y0), (x1, y1))
        nx, ny = (y1 - y0) / L, -(x1 - x0) / L          # normal derecha
        lineas.append(((x0 + nx * d, y0 + ny * d), (x1 + nx * d, y1 + ny * d)))
    out = [lineas[0][0]]
    for (a0, a1), (b0, b1) in zip(lineas, lineas[1:]):
        dax, day = a1[0] - a0[0], a1[1] - a0[1]
        dbx, dby = b1[0] - b0[0], b1[1] - b0[1]
        den = dax * dby - day * dbx
        if abs(den) < 1e-12:
            out.append(a1)
            continue
        t = ((b0[0] - a0[0]) * dby - (b0[1] - a0[1]) * dbx) / den
        out.append((a0[0] + dax * t, a0[1] + day * t))
    out.append(lineas[-1][1])
    return out


def _solid(handle: str, layer: str, color: Optional[int] = None) -> Optional[str]:
    try:
        return acad.call("create_hatch", {
            "boundaryHandle": handle, "pattern": "SOLID", "scale": 1.0, "angleDeg": 0.0,
            "layer": layer, "islandHandles": None, "lineweight": 0,
            "colorIndex": color})["handle"]
    except acad.AutoCadError:
        return None


def text(content: str, x: float, y: float, height: float, layer: str = LAYER_TEXTOS,
         justify: Optional[str] = None, rotation: float = 0.0, lw: int = 18,
         color: Optional[int] = None) -> str:
    layers.ensure_text_style()
    h = acad.call("create_text", {
        "text": content, "x": x, "y": y, "z": 0.0, "height": height, "layer": layer,
        "justify": justify, "rotationDeg": rotation, "lineweight": layers.LW_TEXTO,
        "colorIndex": color})["handle"]
    ancho = text_width(content, height)
    if not justify or justify.endswith("left"):
        x0 = x
    elif justify.endswith("center"):
        x0 = x - ancho / 2
    else:
        x0 = x - ancho
    if abs(rotation) < 1e-6:
        space.track(x0, y - height * 0.3, x0 + ancho, y + height * 1.1,
                    f"{space.PREFIJO_TEXTO}{content[:40]}")
    return h


def text_width(content: str, height: float) -> float:
    return len(content) * height * 0.92


# ------------------------------------------------------------ líneas

def break_line(p0, p1, upm: float, layer: str, lw: int = 18,
               overrun_mm: float = 2.0, size_mm: float = 3.0) -> str:
    """Símbolo de corte: recta con una Z al medio que sigue overrun_mm más
    allá de cada punta -- dice 'la pieza continúa', que un tope recto no."""
    (x0, y0), (x1, y1) = p0, p1
    L = math.dist(p0, p1)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    nx, ny = -uy, ux
    o = overrun_mm * upm
    s = min(size_mm * upm, L * 0.4)
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    pts = [(x0 - ux * o, y0 - uy * o),
           (mx - ux * s / 2, my - uy * s / 2),
           (mx - ux * s / 6 + nx * s * 0.7, my - uy * s / 6 + ny * s * 0.7),
           (mx + ux * s / 6 - nx * s * 0.7, my + uy * s / 6 - ny * s * 0.7),
           (mx + ux * s / 2, my + uy * s / 2),
           (x1 + ux * o, y1 + uy * o)]
    return _poly(pts, layer, lw)


def jagged_points(p0, p1, upm: float, amp_mm: float = 1.6, step_mm: float = 2.5,
                  seed: int = 7) -> list[tuple[float, float]]:
    """Borde irregular (sin el primer punto repetido) de una masa cortada:
    quiebres de amplitud y paso variables, como lo traza la mano."""
    rnd = random.Random(seed)
    (x0, y0), (x1, y1) = p0, p1
    L = math.dist(p0, p1)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    nx, ny = -uy, ux
    n = max(2, int(L / (step_mm * upm)))
    pts = [(x0, y0)]
    for k in range(1, n):
        t = k / n + (rnd.random() - 0.5) * 0.4 / n
        a = amp_mm * upm * (0.4 + 0.6 * rnd.random()) * (1 if k % 2 else -1)
        pts.append((x0 + ux * L * t + nx * a, y0 + uy * L * t + ny * a))
    pts.append((x1, y1))
    return pts


def jagged_line(p0, p1, upm: float, layer: str, lw: int = 13, **kw) -> str:
    return _poly(jagged_points(p0, p1, upm, **kw), layer, lw)


def rough_line(p0, p1, upm: float, layer: str, lw: int = 25,
               amp_mm: float = 0.6, pitch_mm: float = 1.2) -> str:
    """Junta rugosa: dientes de sierra finos y regulares sobre la línea."""
    (x0, y0), (x1, y1) = p0, p1
    L = math.dist(p0, p1)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    nx, ny = -uy, ux
    n = max(2, int(round(L / (pitch_mm * upm))))
    a = amp_mm * upm
    pts = [(x0, y0)]
    for k in range(1, n):
        t = k / n
        s = 1 if k % 2 else -1
        pts.append((x0 + ux * L * t + nx * a * s, y0 + uy * L * t + ny * a * s))
    pts.append((x1, y1))
    return _poly(pts, layer, lw)


def roughness_marks(p0, p1, upm: float, layer: str, lw: int = 13,
                    pitch_mm: float = 2.0, size_mm: float = 0.9) -> list[str]:
    """Rayado de acabado rugoso: trazos cortos inclinados a lo largo de una
    superficie (hacia el lado izquierdo del avance p0->p1)."""
    (x0, y0), (x1, y1) = p0, p1
    L = math.dist(p0, p1)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    nx, ny = -uy, ux
    n = max(1, int(L / (pitch_mm * upm)))
    s = size_mm * upm
    pts: list[tuple[float, float]] = []
    for k in range(n + 1):
        t = (k + 0.5) / (n + 1)
        bx, by = x0 + ux * L * t, y0 + uy * L * t
        pts += [(bx, by), (bx + (nx + ux * 0.6) * s, by + (ny + uy * 0.6) * s), (bx + ux * s * 1.2, by + uy * s * 1.2)]
    return [_poly(pts, layer, lw)]


def chair(x: float, y_base: float, height: float, layer: str,
          color: int = 8) -> list[str]:
    """Calzo de concreto bajo la parrilla: triángulo macizo con la punta
    tocando la varilla."""
    w = height * 0.9
    h = _poly([(x - w / 2, y_base), (x + w / 2, y_base), (x, y_base + height)], layer, 13,
              closed=True)
    out = [h]
    s = _solid(h, layer, color)
    if s:
        out.append(s)
    return out


def dot(x: float, y: float, r: float, layer: str, color: Optional[int] = None) -> list[str]:
    h = acad.call("create_circle", {"x": x, "y": y, "z": 0.0, "radius": r, "layer": layer,
                                    "lineweight": 13, "colorIndex": color})["handle"]
    out = [h]
    s = _solid(h, layer, color)
    if s:
        out.append(s)
    return out


# ------------------------------------------------------------ cotas

def dimension(p1, p2, line_pt, upm: float, angle: float = 0.0,
              text_override: Optional[str] = None, layer: str = LAYER_COTAS) -> str:
    """Cota rotada (0 = horizontal, 90 = vertical) con el estilo MCP-COTAS.
    text_override: '<>' es la medida -> 'lb = <>' escribe 'lb = 0.60'."""
    estilo = ann_mod.ensure_dim_style()
    layers.ensure(layer, 12, 13)
    h = acad.call("create_dimension_rotated", {
        "x1": p1[0], "y1": p1[1], "x2": p2[0], "y2": p2[1],
        "dimLineX": line_pt[0], "dimLineY": line_pt[1], "angleDeg": angle,
        "layer": layer, "style": estilo, "scale": upm, "text": text_override,
        "lineweight": 13, "colorIndex": None})["handle"]
    xs = [p1[0], p2[0], line_pt[0]]
    ys = [p1[1], p2[1], line_pt[1]]
    space.track(min(xs), min(ys), max(xs), max(ys), "cota")
    return h


def texto_cota(valor: float) -> Optional[str]:
    """None si la medida es de cm redondos (la cota muestra 2 decimales); si
    no, el número con 3. Una columna de 35 en colindancia pone su eje a
    0.175: redondeado a 0.18 la cadena suma 5.11 contra un total de 5.10, y
    el plano se contradice."""
    cm = valor * 100.0
    if abs(cm - round(cm)) < 1e-6:
        return None
    return f"{valor:.3f}"


def chain(positions: list[float], side: str, reference: float, upm: float,
          offset_mm: float = 8.0, total: bool = True, layer: str = LAYER_COTAS,
          total_text: Optional[str] = None) -> float:
    """Cadena de cotas con texto exacto (texto_cota) y la total un renglón
    más afuera. side: 'bottom' (reference = y del borde) o 'right'/'left'
    (reference = x). Devuelve la coordenada de la línea más afuera."""
    pos = sorted({round(p, 5) for p in positions})
    sg = -1 if side in ("bottom", "left") else 1
    linea = reference + sg * offset_mm * upm
    horiz = side in ("bottom", "top")
    for a, b in zip(pos, pos[1:]):
        p1, p2 = ((a, reference), (b, reference)) if horiz else ((reference, a), (reference, b))
        lp = ((a + b) / 2, linea) if horiz else (linea, (a + b) / 2)
        dimension(p1, p2, lp, upm, angle=0 if horiz else 90, text_override=texto_cota(b - a),
                  layer=layer)
    if total and len(pos) > 2:
        linea += sg * 8 * upm
        a, b = pos[0], pos[-1]
        p1, p2 = ((a, reference), (b, reference)) if horiz else ((reference, a), (reference, b))
        lp = ((a + b) / 2, linea) if horiz else (linea, (a + b) / 2)
        t = total_text if total_text else texto_cota(b - a)
        dimension(p1, p2, lp, upm, angle=0 if horiz else 90, text_override=t, layer=layer)
    return linea


# ------------------------------------------------------------ llamadas

def _repartir(ideales: list[float], gap: float, lo: float, hi: float) -> list[float]:
    """Posiciones lo más cerca posible de las ideales, en el mismo orden y
    separadas al menos 'gap' (relajación por bloques, como un dibujante que
    corre los rótulos de a uno)."""
    n = len(ideales)
    if n == 0:
        return []
    ys = list(ideales)
    for _ in range(200):
        movido = False
        for i in range(1, n):
            if ys[i - 1] - ys[i] < gap - 1e-9:      # ordenados de arriba a abajo
                falta = gap - (ys[i - 1] - ys[i])
                ys[i - 1] += falta / 2
                ys[i] -= falta / 2
                movido = True
        if ys[0] > hi:
            d = ys[0] - hi
            ys = [y - d for y in ys]
            movido = True
        if ys[-1] < lo:
            d = lo - ys[-1]
            ys = [y + d for y in ys]
            movido = True
        if not movido:
            break
    return ys


def _se_cruzan(p1, p2, q1, q2) -> bool:
    def lado(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = lado(q1, q2, p1), lado(q1, q2, p2)
    d3, d4 = lado(p1, p2, q1), lado(p1, p2, q2)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def wrap(content: str, max_chars: int) -> list[str]:
    palabras = content.split()
    renglones, actual = [], ""
    for p in palabras:
        if actual and len(actual) + 1 + len(p) > max_chars:
            renglones.append(actual)
            actual = p
        else:
            actual = f"{actual} {p}".strip()
    if actual:
        renglones.append(actual)
    return renglones


def callouts(items: list[tuple[tuple[float, float], str]], side: str, x_edge: float,
             upm: float, y_range: Optional[tuple[float, float]] = None,
             text_mm: float = 2.0, gap_mm: float = 6.0, max_chars: int = 38,
             layer: str = LAYER_LLAMADAS, dot_mm: float = 0.6) -> dict[str, Any]:
    """Llamadas en UNA columna a un lado del dibujo.

    items: [((x, y) del punto señalado, texto), ...].
    side: 'left' o 'right'. x_edge: el borde del dibujo de ese lado; los
    renglones arrancan gap_mm más afuera.
    El punto lleva un punto macizo; la línea va del punto al quiebre y
    sigue horizontal bajo el texto (texto ENCIMA del renglón, como se
    rotula a mano). Se ordenan por la altura del punto, así ninguna línea
    cruza a otra, y se separan lo justo para que los textos no se toquen.
    Devuelve la caja que ocupan.
    """
    if not items:
        return {"box": None, "handles": []}
    layers.ensure(layer, 7, 13)
    h = text_mm * upm
    sgn = 1 if side == "right" else -1
    x_quiebre = x_edge + sgn * gap_mm * upm
    orden = sorted(items, key=lambda it: -it[0][1])
    bloques = [wrap(t, max_chars) for _, t in orden]
    altos = [len(b) * h * 1.6 for b in bloques]
    gap = max(altos) + h * 0.9
    ideales = [p[1] for p, _ in orden]
    lo, hi = y_range if y_range else (min(ideales) - 10 * h, max(ideales) + 10 * h)
    ys = _repartir(ideales, gap, lo, hi)
    # Ordenar por altura no alcanza: un punto lejano y otro cercano a la
    # misma altura cruzan sus líneas. Se intercambian vecinos que se cruzan
    # hasta que no quede ninguno (siempre existe un orden sin cruces cuando
    # todas las líneas llegan a la misma vertical).
    orden = list(orden)
    bloques = list(bloques)
    for _ in range(len(orden) ** 2 + 1):
        cambio = False
        for i in range(len(orden) - 1):
            for j in range(i + 1, len(orden)):
                a0, b0 = orden[i][0], (x_quiebre, ys[i])
                a1, b1 = orden[j][0], (x_quiebre, ys[j])
                if _se_cruzan(a0, b0, a1, b1):
                    orden[i], orden[j] = orden[j], orden[i]
                    bloques[i], bloques[j] = bloques[j], bloques[i]
                    cambio = True
        if not cambio:
            break
    handles: list[str] = []
    x_min, x_max = x_quiebre, x_quiebre
    for ((px, py), _t), renglones, y in zip(orden, bloques, ys):
        ancho = max(text_width(r, h) for r in renglones) + h * 0.6
        x_fin = x_quiebre + sgn * ancho
        handles += dot(px, py, dot_mm * upm / 2, layer)
        handles.append(_poly([(px, py), (x_quiebre, y), (x_fin, y)], layer, 13))
        x_txt = x_quiebre + sgn * h * 0.3 if sgn > 0 else x_fin + h * 0.3
        for k, r in enumerate(reversed(renglones)):
            handles.append(text(r, x_txt, y + h * 0.45 + k * h * 1.6, h, layer))
        x_min, x_max = min(x_min, x_fin, x_quiebre), max(x_max, x_fin, x_quiebre)
    return {"box": [x_min, min(ys) - h, x_max, max(ys) + gap], "handles": handles}
