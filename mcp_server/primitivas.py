"""Primitivas 2D de uso diario que AutoCAD tiene como comando propio (RECTANG, POLYGON, ELLIPSE, XLINE, RAY,
POINT) y que acá se arman con lo que ya existe: la geometría se calcula acá y se dibuja con create_polyline o
create_object. Todo se valida antes de tocar AutoCAD.

No hay plugin nuevo detrás: son composiciones sobre herramientas ya verificadas.
"""
from __future__ import annotations

import math
from typing import Any, Optional

TAN_OCTAVO = math.tan(math.pi / 8)      # bulge de un arco de 90 grados


class PrimitivaError(ValueError):
    """Argumento inválido: se informa antes de tocar AutoCAD."""


def _num(v: Any, cual: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) == float("inf"):
        raise PrimitivaError(f"'{cual}' tiene que ser un número finito.")
    return float(v)


def rectangulo(x1: float, y1: float, x2: float, y2: float, radio_esquina: float = 0.0) -> dict[str, Any]:
    """Vértices y bulges de un rectángulo (esquina opuesta a esquina), con esquinas redondeadas si radio > 0."""
    x1, y1, x2, y2 = (_num(v, n) for v, n in ((x1, "x1"), (y1, "y1"), (x2, "x2"), (y2, "y2")))
    r = _num(radio_esquina, "corner_radius")
    xa, xb = sorted((x1, x2))
    ya, yb = sorted((y1, y2))
    ancho, alto = xb - xa, yb - ya
    if ancho <= 0 or alto <= 0:
        raise PrimitivaError("El rectángulo no tiene área: las dos esquinas comparten una coordenada.")
    if r < 0:
        raise PrimitivaError("'corner_radius' no puede ser negativo.")
    if r == 0:
        return {"points": [[xa, ya], [xb, ya], [xb, yb], [xa, yb]], "bulges": None}
    if r * 2 >= min(ancho, alto):
        raise PrimitivaError(f"'corner_radius' ({r}) no entra: tiene que ser menor que la mitad del lado menor ({min(ancho, alto) / 2}).")
    t = TAN_OCTAVO                      # bulge de un arco de 90 grados: tan(90/4)
    pts = [[xa + r, ya], [xb - r, ya], [xb, ya + r], [xb, yb - r], [xb - r, yb], [xa + r, yb], [xa, yb - r], [xa, ya + r]]
    bul = [0.0, t, 0.0, t, 0.0, t, 0.0, t]
    return {"points": pts, "bulges": bul}


def poligono(lados: int, cx: float, cy: float, radio: float, circunscrito: bool = False,
             rotacion_deg: float = 0.0) -> dict[str, Any]:
    """Polígono regular. circunscrito=False: el radio llega a los vértices (inscrito en la circunferencia);
    True: el radio llega al punto medio de cada lado."""
    if isinstance(lados, bool) or not isinstance(lados, int) or not 3 <= lados <= 1000:
        raise PrimitivaError("'sides' es un entero de 3 a 1000.")
    cx, cy, radio = _num(cx, "cx"), _num(cy, "cy"), _num(radio, "radius")
    if radio <= 0:
        raise PrimitivaError("'radius' tiene que ser mayor que cero.")
    rot = math.radians(_num(rotacion_deg, "rotation_deg"))
    rv = radio / math.cos(math.pi / lados) if circunscrito else radio
    pts = [[cx + rv * math.cos(rot + 2 * math.pi * k / lados), cy + rv * math.sin(rot + 2 * math.pi * k / lados)]
           for k in range(lados)]
    return {"points": pts, "vertex_radius": rv}


def elipse(cx: float, cy: float, eje_mayor_x: float, eje_mayor_y: float, relacion: float,
           inicio_rad: float = 0.0, fin_rad: float = 2 * math.pi) -> dict[str, Any]:
    """Argumentos de Ellipse.Set. (eje_mayor_x, eje_mayor_y) es el vector del centro al extremo del eje mayor."""
    cx, cy = _num(cx, "cx"), _num(cy, "cy")
    mx, my = _num(eje_mayor_x, "major_x"), _num(eje_mayor_y, "major_y")
    if mx == 0 and my == 0:
        raise PrimitivaError("El eje mayor no puede ser un vector nulo.")
    rr = _num(relacion, "ratio")
    if not 0 < rr <= 1:
        raise PrimitivaError("'ratio' (eje menor / eje mayor) va de 0 (exclusive) a 1.")
    a, b = _num(inicio_rad, "start_rad"), _num(fin_rad, "end_rad")
    if not 0 <= a < 2 * math.pi + 1e-9 or not 0 < b <= 2 * math.pi + 1e-9 or b <= a:
        raise PrimitivaError("Los ángulos van de 0 a 2π (en radianes) y el final tiene que ser mayor que el inicio.")
    return {"entity_type": "Ellipse", "init_method": "Set",
            "init_args": [[cx, cy, 0.0], [0.0, 0.0, 1.0], [mx, my, 0.0], rr, a, b]}


def linea_infinita(tipo: str, x: float, y: float, dx: float, dy: float) -> dict[str, Any]:
    """Xline (infinita en los dos sentidos) o Ray (infinita en uno), por punto base y dirección."""
    if tipo not in ("Xline", "Ray"):
        raise PrimitivaError("tipo es Xline o Ray.")
    x, y, dx, dy = (_num(v, n) for v, n in ((x, "x"), (y, "y"), (dx, "dx"), (dy, "dy")))
    if dx == 0 and dy == 0:
        raise PrimitivaError("La dirección (dx, dy) no puede ser nula.")
    return {"entity_type": tipo, "properties": {"BasePoint": [x, y, 0.0], "SecondPoint": [x + dx, y + dy, 0.0]}}


def punto(x: float, y: float, z: float = 0.0) -> dict[str, Any]:
    return {"entity_type": "DBPoint", "properties": {"Position": [_num(x, "x"), _num(y, "y"), _num(z, "z")]}}


def con_capa(spec: dict[str, Any], layer: Optional[str]) -> dict[str, Any]:
    """Agrega la capa a las propiedades de un create_object (la capa tiene que existir)."""
    if layer is None:
        return spec
    if not isinstance(layer, str) or not layer.strip():
        raise PrimitivaError("'layer' es el nombre de una capa existente.")
    out = dict(spec)
    out["properties"] = dict(spec.get("properties", {}), Layer=layer.strip())
    return out
