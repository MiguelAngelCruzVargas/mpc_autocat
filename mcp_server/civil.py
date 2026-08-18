"""Obra civil lineal: calles, banquetas, guarniciones.

Una calle es un eje con anchos a los lados: calzada, guarnición, banqueta. Todo
sale del mismo offset paralelo que usan los muros (geom.py), así que las curvas
y los quiebres cierran igual de bien.

Unidades: las del modelo (metros si dibujás en metros).
"""
from __future__ import annotations

from typing import Any, Optional

import autocad_client as acad
from geom import Axis, Point

LAYER_AXIS = "EJE-CALLE"
LAYER_PAVEMENT = "PAVIMENTO"
LAYER_CURB = "GUARNICION"
LAYER_SIDEWALK = "BANQUETA"

LW_AXIS = 13
LW_PAVEMENT = 35
LW_CURB = 50
LW_SIDEWALK = 25

AXIS_LINETYPE = "CENTER"
AXIS_COLOR = 1


def _ensure(name: str, color: int, lineweight: int,
            linetype: Optional[str] = None) -> None:
    acad.call("set_layer", {"name": name, "colorIndex": color,
                            "linetype": linetype,
                            "lineweightHundredthsMm": lineweight})


def _band(axis: Axis, inner: float, outer: float, layer: str,
          lineweight: int, closed_axis: bool,
          pattern: Optional[str] = None, scale: float = 1.0,
          color: Optional[int] = None) -> str:
    """Franja paralela al eje entre dos distancias (con signo: + es izquierda)."""
    a = axis.offset_vertices(inner)
    b = axis.offset_vertices(outer)
    pts = a + list(reversed(b))

    handle = acad.call("create_polyline", {
        "points": [[p[0], p[1]] for p in pts],
        "closed": True, "layer": layer,
        "lineweight": lineweight, "colorIndex": color,
    })["handle"]

    if pattern:
        try:
            acad.call("create_hatch", {
                "boundaryHandle": handle, "pattern": pattern, "scale": scale,
                "angleDeg": 0.0, "layer": layer,
                "lineweight": 9, "colorIndex": color,
            })
        except acad.AutoCadError:
            pass   # un patrón inexistente no debe tumbar el trazo
    return handle


def create_road(
    points: list[list[float]],
    width: float = 7.00,
    curb_width: float = 0.40,
    sidewalk_width: float = 0.0,
    closed: bool = False,
    draw_axis: bool = True,
    pavement_pattern: Optional[str] = None,
    pavement_scale: float = 1.0,
    axis_layer: str = LAYER_AXIS,
    pavement_layer: str = LAYER_PAVEMENT,
    curb_layer: str = LAYER_CURB,
    sidewalk_layer: str = LAYER_SIDEWALK,
) -> dict[str, Any]:
    """Calle en planta a partir de su eje: calzada, guarniciones y banquetas.

    points: el eje por donde pasa el CENTRO de la calzada.
    width: ancho total de calzada (de guarnición a guarnición).
    curb_width: ancho de la guarnición, a cada lado, por fuera de la calzada.
    sidewalk_width: ancho de banqueta por fuera de la guarnición; 0 la omite.

    Devuelve el largo del eje, que es el dato con el que se cuantifica la obra
    (metros lineales de guarnición, metros cuadrados de pavimento).
    """
    if width <= 0:
        raise ValueError("width tiene que ser > 0.")
    if curb_width < 0 or sidewalk_width < 0:
        raise ValueError("Los anchos no pueden ser negativos.")

    axis = Axis([(p[0], p[1]) for p in points], closed=closed)
    half = width / 2.0
    result: dict[str, Any] = {}

    # --- Calzada ---
    _ensure(pavement_layer, 8, LW_PAVEMENT)
    result["pavementHandle"] = _band(
        axis, -half, half, pavement_layer, LW_PAVEMENT, closed,
        pavement_pattern, pavement_scale)

    # --- Guarniciones, una por lado ---
    if curb_width > 0:
        _ensure(curb_layer, 4, LW_CURB)
        result["curbHandles"] = [
            _band(axis, half, half + curb_width, curb_layer, LW_CURB, closed),
            _band(axis, -half - curb_width, -half, curb_layer, LW_CURB, closed),
        ]

    # --- Banquetas ---
    if sidewalk_width > 0:
        _ensure(sidewalk_layer, 9, LW_SIDEWALK)
        base = half + curb_width
        result["sidewalkHandles"] = [
            _band(axis, base, base + sidewalk_width, sidewalk_layer,
                  LW_SIDEWALK, closed),
            _band(axis, -base - sidewalk_width, -base, sidewalk_layer,
                  LW_SIDEWALK, closed),
        ]

    # --- Eje, al final para que quede por encima del relleno ---
    if draw_axis:
        _ensure(axis_layer, AXIS_COLOR, LW_AXIS, AXIS_LINETYPE)
        acad.call("create_polyline", {
            "points": [[p[0], p[1]] for p in axis.points],
            "closed": closed, "layer": axis_layer,
            "lineweight": LW_AXIS, "colorIndex": AXIS_COLOR,
        })

    largo = axis.total_length
    result.update({
        "length": largo,
        "width": width,
        "pavementArea": largo * width,
        "curbLength": largo * 2 if curb_width > 0 else 0.0,
        "sidewalkArea": largo * sidewalk_width * 2 if sidewalk_width > 0 else 0.0,
        "totalWidth": width + 2 * curb_width + 2 * sidewalk_width,
    })
    return result


def road_edge(points: list[list[float]], offset: float,
              closed: bool = False) -> list[list[float]]:
    """Los vértices de una paralela al eje, sin dibujar nada.

    Sirve para ubicar cosas respecto de la calle —un poste, el arranque de un
    ramal, dónde cae una cota— sin tener que recalcular el offset a mano.
    """
    axis = Axis([(p[0], p[1]) for p in points], closed=closed)
    return [[p[0], p[1]] for p in axis.offset_vertices(offset)]


def point_on_road(points: list[list[float]], distance: float,
                  offset: float = 0.0, closed: bool = False) -> dict[str, Any]:
    """Punto a una distancia dada del arranque del eje, y opcionalmente
    desplazado perpendicularmente. Es cómo se ubica algo por cadenamiento."""
    axis = Axis([(p[0], p[1]) for p in points], closed=closed)
    p = axis.offset_point_at(distance, offset)
    seg, _ = axis.segment_at(distance)
    u = axis.dirs[seg]
    return {"x": p[0], "y": p[1], "dirX": u[0], "dirY": u[1],
            "totalLength": axis.total_length}
