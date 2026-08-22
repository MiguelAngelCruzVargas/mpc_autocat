"""Vistas isométricas de conjunto (p.ej. una cimentación completa: columna +
dado + trabe de liga + zapata, cada elemento apilado en su lugar real) SIN
geometría 3D -- el mismo truco que cualquier isométrico de obra dibujado en
un CAD 2D desde antes de que existiera el modelado 3D: proyectar los
vértices de cada prisma con la fórmula isométrica clásica

    x' = (X - Y)·cos(30°)
    y' = (X + Y)·sin(30°) + Z

y dibujar sus caras visibles como polígonos PLANOS en el plano de la lámina.
Este repo es 2D puro (Z de modelo siempre 0.0, ver sections.py) y esto no lo
cambia -- la "profundidad" es enteramente un efecto de la proyección, igual
que cualquier isométrico dibujado a mano o en AutoCAD clásico con isoplanos.

Se compone con create_polyline/create_hatch, como el resto de arch.py/
sections.py/roof.py/rebar.py -- no hace falta tocar el plugin.

x, y, z de cada prisma son medidas REALES de obra (m si se dibuja en
metros); x, y en planta, z la altura. El resultado 2D que se dibuja está en
las unidades del modelo de la lámina -- elegí un origen (x, y) del isométrico
lejos del resto del dibujo, igual que cualquier detalle aparte.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad
import layers
import space

LAYER_ISOMETRIC = "ISOMETRICO"

LW_FACE = 25

_COS30 = math.cos(math.radians(30.0))
_SIN30 = math.sin(math.radians(30.0))


def _layer(name: str, lineweight: int) -> None:
    layers.ensure(name, layers.COLOR_PRINCIPAL, lineweight)
    layers.ensure_text_style()


def iso_project(rx: float, ry: float, rz: float) -> tuple[float, float]:
    """Proyecta un punto 3D real (X planta, Y planta, Z altura) al punto 2D
    de la lámina, con la fórmula isométrica clásica (30°). Útil para ubicar
    un leader o un texto apuntando a un punto preciso de la caja, no solo
    al centro que ya devuelve create_isometric_box."""
    return ((rx - ry) * _COS30, (rx + ry) * _SIN30 + rz)


def _face(handle_points: list[tuple[float, float, float]], layer: str,
         lineweight: int) -> str:
    pts2d = [iso_project(*p) for p in handle_points]
    return acad.call("create_polyline", {
        "points": [[p[0], p[1]] for p in pts2d],
        "closed": True, "layer": layer,
        "lineweight": lineweight, "colorIndex": None,
    })["handle"]


def _hatch(handle: str, pattern: str, scale: float, layer: str,
          color_index: Optional[int]) -> Optional[str]:
    try:
        return acad.call("create_hatch", {
            "boundaryHandle": handle, "pattern": pattern, "scale": scale,
            "angleDeg": 0.0, "layer": layer,
            "lineweight": 5, "colorIndex": color_index,
        })["handle"]
    except acad.AutoCadError:
        return None


def create_isometric_box(x: float, y: float, z: float,
                         dx: float, dy: float, dz: float,
                         layer: Optional[str] = None,
                         lineweight: int = LW_FACE,
                         hatch_pattern: Optional[str] = None,
                         hatch_scale: float = 1.0,
                         color_index: Optional[int] = None) -> dict[str, Any]:
    """Un prisma rectangular (columna, dado, trabe, zapata -- cualquier
    elemento de concreto) en proyección isométrica: las 3 caras visibles
    (superior, y las dos laterales que dan hacia el observador), cada una
    un polígono plano ya proyectado. Para una cimentación completa (el
    caso típico), llamala una vez por elemento apilado -- columna, dado,
    trabe de liga, zapata -- con el mismo (x, y) en planta y el 'z' real
    de arranque de cada uno; el apilado y qué tapa a qué sale solo si
    dibujás de ABAJO hacia ARRIBA (zapata primero, columna al final), en
    el mismo orden en que existen en obra.

    (x, y, z): esquina de coordenadas MÍNIMAS del prisma, medidas reales
    (x, y en planta, z altura sobre el datum del isométrico -- no cota
    absoluta del proyecto, elegí un origen para el dibujo isométrico en
    sí). dx, dy, dz: dimensiones reales en cada eje.

    hatch_pattern: None (default) deja las caras solo con contorno --
    'SOLID' para relleno sólido de color (lo que hace leíble un
    isométrico de verdad, un color POR ELEMENTO como en cualquier
    isométrico de obra: columna de un color, dado de otro). color_index:
    evitá los puros 1-6 (se lavan en papel o son chillones en pantalla,
    ver layers.EVITAR) -- 32/12/152/96/172 son la paleta ya elegida en
    layers.py para justamente distinguir elementos por color.

    Devuelve los 3 handles de cara (top/right/left, cada uno la Polyline
    cerrada ya proyectada) y 'topCenter'/'frontBottomCorner' en
    coordenadas 2D de la lámina -- para apuntar un leader con el nombre
    del elemento sin tener que calcular la proyección a mano."""
    if dx <= 0 or dy <= 0 or dz <= 0:
        raise ValueError("dx, dy y dz tienen que ser mayores que 0.")

    lyr = layer or LAYER_ISOMETRIC
    _layer(lyr, lineweight)

    p000 = (x, y, z)
    p100 = (x + dx, y, z)
    p010 = (x, y + dy, z)
    p001 = (x, y, z + dz)
    p101 = (x + dx, y, z + dz)
    p011 = (x, y + dy, z + dz)
    p111 = (x + dx, y + dy, z + dz)

    right_handle = _face([p000, p100, p101, p001], lyr, lineweight)
    left_handle = _face([p000, p010, p011, p001], lyr, lineweight)
    top_handle = _face([p001, p101, p111, p011], lyr, lineweight)

    if hatch_pattern:
        for h in (right_handle, left_handle, top_handle):
            _hatch(h, hatch_pattern, hatch_scale, lyr, color_index)

    all_2d = [iso_project(*p) for p in
             (p000, p100, p010, p001, p101, p011, p111,
              (x + dx, y + dy, z))]
    xs = [p[0] for p in all_2d]
    ys = [p[1] for p in all_2d]
    space.track(min(xs), min(ys), max(xs), max(ys), f"isometrico {lyr}")

    top_center = iso_project(x + dx / 2.0, y + dy / 2.0, z + dz)

    return {
        "rightFaceHandle": right_handle,
        "leftFaceHandle": left_handle,
        "topFaceHandle": top_handle,
        "topCenter": {"x": top_center[0], "y": top_center[1]},
        "frontBottomCorner": {"x": iso_project(*p000)[0],
                              "y": iso_project(*p000)[1]},
    }
