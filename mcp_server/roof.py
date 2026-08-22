"""Cubiertas a dos aguas y armaduras de techo.

`create_building_section` (sections.py) resuelve cortes por NIVELES
horizontales, piso a piso -- no tiene ningún concepto de pendiente, alero
ni cumbrera, porque una losa plana no lo necesita. Una nave o cancha
techada sí: el elemento principal del corte tiene pendiente, y eso es lo
que vive acá.

Se compone igual que el resto de arch.py/sections.py: líneas rectas sobre
las tools básicas del plugin, así que no hace falta tocar el DLL para
cambiar esto. Unidades: las del modelo.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad
import layers
import space

LAYER_ROOF = "CUBIERTA"
LAYER_TRUSS = "ESTRUCTURA-TECHO"

LW_ROOF = 50
LW_TRUSS = 35


def _layer(name: str, lineweight: int) -> None:
    layers.ensure(name, layers.COLOR_PRINCIPAL, lineweight)
    layers.ensure_text_style()


def _line(p0: tuple[float, float], p1: tuple[float, float], layer: str,
          lineweight: int) -> str:
    result = acad.call("create_line", {
        "x1": p0[0], "y1": p0[1], "z1": 0.0,
        "x2": p1[0], "y2": p1[1], "z2": 0.0,
        "layer": layer, "lineweight": lineweight, "colorIndex": None,
    })
    return result["handle"]


def create_gable_roof(x: float, y: float, span: float, rise: float,
                      overhang: float = 0.0, layer: Optional[str] = None,
                      lineweight: int = LW_ROOF) -> dict[str, Any]:
    """Perfil de una cubierta a dos aguas (alero-cumbrera-alero), para un
    corte o una fachada -- lo que `create_building_section` no dibuja,
    porque ahí los niveles son horizontales y esto tiene pendiente.

    (x, y) es el apoyo IZQUIERDO (eje de columna o cara de muro), a la cota
    del alero. span es la distancia horizontal entre los dos apoyos; rise
    es la altura de la cumbrera SOBRE el alero (no cota absoluta -- si el
    alero está a NPT+5.00 y la cumbrera a NPT+7.46, rise=2.46).
    overhang prolonga cada agua más allá del apoyo, en línea con la
    pendiente de esa agua (no horizontal) -- 0 si el alero coincide con el
    eje de apoyo, sin volado.

    Devuelve los handles de las dos aguas, el punto de cumbrera, la
    pendiente (m/m y grados) y el largo real de cada agua -- ese largo es
    el que hace falta para pedir la lámina con el desarrollo correcto, no
    la proyección horizontal del claro."""
    if span <= 0:
        raise ValueError("span tiene que ser mayor que 0.")
    if rise < 0:
        raise ValueError("rise no puede ser negativo.")
    if overhang < 0:
        raise ValueError("overhang no puede ser negativo.")

    lyr = layer or LAYER_ROOF
    _layer(lyr, lineweight)

    half_span = span / 2.0
    ridge_x = x + half_span
    ridge_y = y + rise
    slope_ratio = (rise / half_span) if half_span > 0 else 0.0
    slope_deg = math.degrees(math.atan(slope_ratio))

    if overhang > 0 and half_span > 0:
        largo_medio_agua = math.hypot(half_span, rise)
        factor = overhang / largo_medio_agua
        left_eave = (x - half_span * factor, y - rise * factor)
        right_eave = (x + span + half_span * factor, y - rise * factor)
    else:
        left_eave = (x, y)
        right_eave = (x + span, y)
    ridge = (ridge_x, ridge_y)

    h_left = _line(left_eave, ridge, lyr, lineweight)
    h_right = _line(ridge, right_eave, lyr, lineweight)

    largo_agua = math.hypot(half_span, rise) + overhang

    xs = [left_eave[0], ridge_x, right_eave[0]]
    ys = [left_eave[1], ridge_y, right_eave[1]]
    space.track(min(xs), min(ys), max(xs), max(ys), "cubierta")

    return {
        "leftSlopeHandle": h_left,
        "rightSlopeHandle": h_right,
        "ridge": {"x": ridge_x, "y": ridge_y},
        "leftEave": {"x": left_eave[0], "y": left_eave[1]},
        "rightEave": {"x": right_eave[0], "y": right_eave[1]},
        "slopeRatio": round(slope_ratio, 4),
        "slopeDeg": round(slope_deg, 2),
        "slopeLength_m": round(largo_agua, 3),
    }


def create_truss(x: float, y: float, span: float, rise: float,
                 panels: int = 3, layer: Optional[str] = None,
                 chord_lineweight: int = LW_ROOF,
                 web_lineweight: int = LW_TRUSS) -> dict[str, Any]:
    """Símbolo ESQUEMÁTICO de una armadura de techo a dos aguas: cuerda
    inferior horizontal, cuerda superior con pendiente (dos aguas) y
    montantes verticales de alma entre las dos -- para que un corte
    estructural se lea como corte estructural (con su "ARMADURA EST-1") y
    no como una cubierta sin nada debajo.

    Esto NO es un diseño de armadura: no calcula fuerza por barra ni
    tamaño de perfil, es la geometría que se ve en el corte. Para la
    reacción que baja a la columna, usá `check_roof_truss` (rules.py, se
    calcula aparte); para verificar la columna que la recibe,
    `check_column`.

    (x, y) es el apoyo izquierdo, a la cota de la cuerda inferior (el
    alero). span: distancia entre apoyos. rise: altura de cumbrera sobre
    la cuerda inferior. panels: paños por CADA media armadura (mínimo 1);
    3 es un valor de referencia razonable para una armadura chica.

    Devuelve los handles de cuerda inferior, cuerdas superiores y
    montantes, más la misma cumbrera/pendiente que `create_gable_roof` --
    se puede usar cualquiera de las dos sola, o esta arriba de la otra si
    el corte necesita mostrar cubierta Y estructura."""
    if span <= 0:
        raise ValueError("span tiene que ser mayor que 0.")
    if rise < 0:
        raise ValueError("rise no puede ser negativo.")
    if panels < 1:
        raise ValueError("panels tiene que ser al menos 1 por media armadura.")

    lyr = layer or LAYER_TRUSS
    _layer(lyr, chord_lineweight)

    half_span = span / 2.0
    ridge_x = x + half_span
    ridge_y = y + rise

    def top_y(xi: float) -> float:
        if half_span <= 0:
            return y
        if xi <= ridge_x:
            return y + rise * (xi - x) / half_span
        return y + rise * ((x + span) - xi) / half_span

    bottom_handle = _line((x, y), (x + span, y), lyr, chord_lineweight)
    left_top = _line((x, y), (ridge_x, ridge_y), lyr, chord_lineweight)
    right_top = _line((ridge_x, ridge_y), (x + span, y), lyr, chord_lineweight)

    n_nodes = panels * 2
    step = span / n_nodes
    web_handles: list[str] = []
    for i in range(1, n_nodes):
        xi = x + i * step
        yt = top_y(xi)
        web_handles.append(_line((xi, y), (xi, yt), lyr, web_lineweight))

    space.track(x, y, x + span, ridge_y, "armadura")

    slope_deg = math.degrees(math.atan(rise / half_span)) if half_span > 0 else 0.0

    return {
        "bottomChordHandle": bottom_handle,
        "topChordHandles": [left_top, right_top],
        "webHandles": web_handles,
        "ridge": {"x": ridge_x, "y": ridge_y},
        "slopeDeg": round(slope_deg, 2),
    }
