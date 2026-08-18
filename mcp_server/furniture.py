"""Mobiliario esquemático en planta: camas, sillones, comedor, cocina, baño.

Son símbolos, no muebles reales: lo justo para que el cliente lea el uso de cada
espacio. Todo va en su propia capa con trazo fino, para poder apagarlo y quedarse
con la arquitectura sola.

Coordenadas en unidades del modelo (metros si dibujás en metros). Cada pieza se
define en coordenadas locales y se rota alrededor de su punto base, así se puede
apoyar contra cualquier muro.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad

LAYER = "MOBILIARIO"
LW = 18
LW_SOFT = 13  # colchones, cojines: aún más liviano que el contorno

# Huella de todo lo dibujado, para que los rótulos de ambiente no caigan
# encima de un mueble. Cada entrada es un bounding box (x0, y0, x1, y1).
OCCUPIED: list[tuple[float, float, float, float]] = []

# Ancho de caracter respecto de la altura, para la fuente por defecto de
# AutoCAD. Sirve para estimar cuánto mide un texto sin preguntarle al dibujo.
CHAR_W = 0.62


def reset_footprints() -> None:
    OCCUPIED.clear()


def track(x0: float, y0: float, x1: float, y1: float) -> None:
    """Registra un rectángulo como ocupado."""
    OCCUPIED.append((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))


def _track_points(points: list[tuple[float, float]]) -> None:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    track(min(xs), min(ys), max(xs), max(ys))


def ensure_layer() -> None:
    acad.call("set_layer", {"name": LAYER, "colorIndex": 8,
                            "linetype": None, "lineweightHundredthsMm": LW})


def _rot(p: tuple[float, float], base: tuple[float, float],
         deg: float) -> tuple[float, float]:
    if not deg:
        return p
    a = math.radians(deg)
    dx, dy = p[0] - base[0], p[1] - base[1]
    return (base[0] + dx * math.cos(a) - dy * math.sin(a),
            base[1] + dx * math.sin(a) + dy * math.cos(a))


def _poly(points: list[tuple[float, float]], base: tuple[float, float],
          deg: float, lineweight: int = LW, closed: bool = True) -> str:
    pts = [_rot(p, base, deg) for p in points]
    _track_points(pts)
    return acad.call("create_polyline", {
        "points": [[p[0], p[1]] for p in pts], "closed": closed,
        "layer": LAYER, "lineweight": lineweight, "colorIndex": None,
    })["handle"]


def _rect(x: float, y: float, w: float, h: float,
          base: tuple[float, float], deg: float,
          lineweight: int = LW) -> str:
    return _poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                 base, deg, lineweight)


def _circle(cx: float, cy: float, r: float, base: tuple[float, float],
            deg: float, lineweight: int = LW) -> str:
    c = _rot((cx, cy), base, deg)
    track(c[0] - r, c[1] - r, c[0] + r, c[1] + r)
    return acad.call("create_circle", {
        "x": c[0], "y": c[1], "z": 0.0, "radius": r,
        "layer": LAYER, "lineweight": lineweight, "colorIndex": None,
    })["handle"]


def _line(p0: tuple[float, float], p1: tuple[float, float],
          base: tuple[float, float], deg: float,
          lineweight: int = LW) -> str:
    a, b = _rot(p0, base, deg), _rot(p1, base, deg)
    _track_points([a, b])
    return acad.call("create_line", {
        "x1": a[0], "y1": a[1], "z1": 0.0, "x2": b[0], "y2": b[1], "z2": 0.0,
        "layer": LAYER, "lineweight": lineweight, "colorIndex": None,
    })["handle"]


# ------------------------------------------------------------- dormitorio

def bed(x: float, y: float, width: float = 1.60, length: float = 2.00,
        rotation_deg: float = 0.0) -> None:
    """Cama vista en planta. (x,y) es la esquina de la cabecera, a la izquierda.

    Sin rotar, la cabecera queda abajo y la cama se extiende hacia +Y.
    """
    base = (x, y)
    _rect(x, y, width, length, base, rotation_deg)
    # Almohadas contra la cabecera.
    pillow_h = 0.35
    if width >= 1.40:
        gap = 0.06
        pw = (width - 3 * gap) / 2.0
        _rect(x + gap, y + 0.08, pw, pillow_h, base, rotation_deg, LW_SOFT)
        _rect(x + 2 * gap + pw, y + 0.08, pw, pillow_h, base, rotation_deg, LW_SOFT)
    else:
        _rect(x + 0.08, y + 0.08, width - 0.16, pillow_h, base, rotation_deg, LW_SOFT)
    # Doblez del cobertor.
    _line((x, y + length - 0.55), (x + width, y + length - 0.55),
          base, rotation_deg, LW_SOFT)


def nightstand(x: float, y: float, size: float = 0.45,
               rotation_deg: float = 0.0) -> None:
    _rect(x, y, size, size, (x, y), rotation_deg, LW_SOFT)


def closet(x: float, y: float, width: float, depth: float = 0.60,
           rotation_deg: float = 0.0) -> None:
    """Clóset: el mueble y la línea de puertas corredizas."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    _line((x, y + depth * 0.65), (x + width, y + depth * 0.65),
          base, rotation_deg, LW_SOFT)


# ------------------------------------------------------------------- sala

def sofa(x: float, y: float, width: float = 1.90, depth: float = 0.85,
         rotation_deg: float = 0.0) -> None:
    """Sillón. Sin rotar, el respaldo queda abajo y mira hacia +Y."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    back = 0.20
    _line((x, y + back), (x + width, y + back), base, rotation_deg, LW_SOFT)
    arm = 0.20
    _line((x + arm, y + back), (x + arm, y + depth), base, rotation_deg, LW_SOFT)
    _line((x + width - arm, y + back), (x + width - arm, y + depth),
          base, rotation_deg, LW_SOFT)


def armchair(x: float, y: float, size: float = 0.85,
             rotation_deg: float = 0.0) -> None:
    sofa(x, y, size, size * 0.95, rotation_deg)


def coffee_table(x: float, y: float, width: float = 1.10,
                 depth: float = 0.55, rotation_deg: float = 0.0) -> None:
    _rect(x, y, width, depth, (x, y), rotation_deg, LW_SOFT)


# ---------------------------------------------------------------- comedor

def dining_table(cx: float, cy: float, width: float = 1.60,
                 depth: float = 0.90, seats_per_side: int = 3,
                 rotation_deg: float = 0.0) -> None:
    """Mesa de comedor centrada en (cx,cy), con sillas a los cuatro lados."""
    base = (cx, cy)
    x, y = cx - width / 2.0, cy - depth / 2.0
    _rect(x, y, width, depth, base, rotation_deg)

    chair, gap = 0.45, 0.10
    for i in range(seats_per_side):
        step = width / seats_per_side
        cxx = x + step * (i + 0.5) - chair / 2.0
        _rect(cxx, y - gap - chair, chair, chair, base, rotation_deg, LW_SOFT)
        _rect(cxx, y + depth + gap, chair, chair, base, rotation_deg, LW_SOFT)
    for side_x in (x - gap - chair, x + width + gap):
        _rect(side_x, cy - chair / 2.0, chair, chair, base, rotation_deg, LW_SOFT)


# ----------------------------------------------------------------- cocina

def counter(x: float, y: float, width: float, depth: float = 0.60,
            rotation_deg: float = 0.0) -> None:
    """Mesada / barra de cocina."""
    _rect(x, y, width, depth, (x, y), rotation_deg, LW)


def stove(x: float, y: float, width: float = 0.60, depth: float = 0.60,
          rotation_deg: float = 0.0) -> None:
    """Estufa: el mueble y sus cuatro quemadores."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    r = min(width, depth) * 0.11
    for fx in (0.30, 0.70):
        for fy in (0.30, 0.70):
            _circle(x + width * fx, y + depth * fy, r, base, rotation_deg, LW_SOFT)


def kitchen_sink(x: float, y: float, width: float = 0.80, depth: float = 0.60,
                 rotation_deg: float = 0.0) -> None:
    """Fregadero: tarja y escurridor."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    _rect(x + 0.06, y + 0.10, width * 0.5, depth - 0.20, base, rotation_deg, LW_SOFT)


def fridge(x: float, y: float, width: float = 0.70, depth: float = 0.70,
           rotation_deg: float = 0.0) -> None:
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    _line((x + width * 0.5, y), (x + width * 0.5, y + depth),
          base, rotation_deg, LW_SOFT)


# ------------------------------------------------------------------- baño

def wc(x: float, y: float, rotation_deg: float = 0.0) -> None:
    """Inodoro: tanque contra el muro y taza. (x,y) = esquina del tanque."""
    base = (x, y)
    w, tank = 0.38, 0.20
    _rect(x, y, w, tank, base, rotation_deg)
    _circle(x + w / 2.0, y + tank + 0.22, 0.19, base, rotation_deg)


def lavatory(x: float, y: float, width: float = 0.60, depth: float = 0.45,
             rotation_deg: float = 0.0) -> None:
    """Lavabo con su mueble."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    _circle(x + width / 2.0, y + depth * 0.55, min(width, depth) * 0.30,
            base, rotation_deg, LW_SOFT)


def shower(x: float, y: float, width: float = 0.90, depth: float = 0.90,
           rotation_deg: float = 0.0) -> None:
    """Regadera: el plato y las diagonales que la identifican en planta."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    _line((x, y), (x + width, y + depth), base, rotation_deg, LW_SOFT)
    _line((x + width, y), (x, y + depth), base, rotation_deg, LW_SOFT)


# ------------------------------------------------------------------ otros

def text_block_size(text: str, height: float, area: Optional[float] = None,
                    area_height: float = 0.0) -> tuple[float, float]:
    """Cuánto mide el bloque nombre + superficie, en unidades del modelo."""
    w = len(text) * height * CHAR_W
    h = height
    if area is not None:
        ah = area_height or height * 0.72
        w = max(w, len(f"{area:.2f} m2") * ah * CHAR_W)
        h += ah * 1.5
    return w, h


def label(text: str, cx: float, cy: float, height: float,
          layer: str = "TEXTOS", lineweight: int = 25,
          area: Optional[float] = None, area_height: float = 0.0) -> None:
    """Nombre del ambiente y su superficie, CENTRADOS en (cx, cy).

    DBText se ancla abajo a la izquierda, así que acá se calcula el ancla a
    partir del centro pedido: quien llama razona con el centro del bloque, que
    es lo que hace falta para ubicarlo en un hueco libre.
    """
    name = text.upper()
    _, block_h = text_block_size(name, height, area, area_height)
    top = cy + block_h / 2.0

    acad.call("create_text", {
        "text": name,
        "x": cx - len(name) * height * CHAR_W / 2.0,
        "y": top - height, "z": 0.0, "height": height,
        "layer": layer, "rotationDeg": 0.0,
        "lineweight": lineweight, "colorIndex": None,
    })
    if area is not None:
        ah = area_height or height * 0.72
        txt = f"{area:.2f} m2"
        acad.call("create_text", {
            "text": txt,
            "x": cx - len(txt) * ah * CHAR_W / 2.0,
            "y": cy - block_h / 2.0, "z": 0.0,
            "height": ah, "layer": layer, "rotationDeg": 0.0,
            "lineweight": 13, "colorIndex": None,
        })


def _overlaps(a: tuple[float, float, float, float],
              b: tuple[float, float, float, float], gap: float) -> bool:
    return not (a[2] + gap <= b[0] or a[0] - gap >= b[2]
                or a[3] + gap <= b[1] or a[1] - gap >= b[3])


def _clearance(box: tuple[float, float, float, float],
               obstacles: list[tuple[float, float, float, float]]) -> float:
    """Distancia al obstáculo más cercano (0 si toca alguno)."""
    best = float("inf")
    for o in obstacles:
        dx = max(o[0] - box[2], box[0] - o[2], 0.0)
        dy = max(o[1] - box[3], box[1] - o[3], 0.0)
        best = min(best, (dx * dx + dy * dy) ** 0.5)
    return best


def find_label_spot(room: tuple[float, float, float, float],
                    text: str, height: float,
                    area: Optional[float] = None, area_height: float = 0.0,
                    margin: float = 0.12, steps: int = 16
                    ) -> tuple[tuple[float, float], bool]:
    """Dónde poner el rótulo de un ambiente sin taparle el mobiliario.

    Barre posiciones dentro del ambiente y se queda con la que tiene más aire
    alrededor, prefiriendo las cercanas al centro cuando empatan. Devuelve
    ((cx, cy), cupo) — si `cupo` es False no había ningún lugar libre y se
    devuelve el centro del ambiente igual, para no dejar el ambiente sin
    rotular.
    """
    x0, y0, x1, y1 = room
    w, h = text_block_size(text.upper(), height, area, area_height)

    half_w, half_h = w / 2.0 + margin, h / 2.0 + margin
    min_cx, max_cx = x0 + half_w, x1 - half_w
    min_cy, max_cy = y0 + half_h, y1 - half_h
    room_cx, room_cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0

    if min_cx > max_cx or min_cy > max_cy:
        return (room_cx, room_cy), False   # el texto no entra ni vacío

    # Solo estorban los muebles que caen dentro de este ambiente.
    obstacles = [o for o in OCCUPIED
                 if _overlaps(o, (x0, y0, x1, y1), 0.0)]

    best = None
    for i in range(steps + 1):
        for j in range(steps + 1):
            cx = min_cx + (max_cx - min_cx) * (i / steps if steps else 0.5)
            cy = min_cy + (max_cy - min_cy) * (j / steps if steps else 0.5)
            box = (cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)
            if any(_overlaps(box, o, margin) for o in obstacles):
                continue
            clear = _clearance(box, obstacles)
            # Con holgura parecida, gana el más centrado.
            dist = abs(cx - room_cx) + abs(cy - room_cy)
            score = (round(clear, 2), -dist)
            if best is None or score > best[0]:
                best = (score, (cx, cy))

    if best is None:
        return (room_cx, room_cy), False
    return best[1], True
