"""Estacionamientos: cajones en fila con su numeración y su coche, y rampas.

Piezas reutilizables para cualquier planta de estacionamiento (no un plano
concreto): `create_parking_stalls` (una fila de cajones), `create_car_symbol`
(un coche visto desde arriba), `create_ramp_track` (rampa en anillo entre dos
contornos redondeados, con sus líneas radiales) y `create_ramp_arc` (tramo
curvo de rampa). Las medidas son las del proyecto, en las unidades del
dibujo: ningún cajón ni radio viene cableado.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad
import prim

LAYER_CAJON = "ESTAC-CAJONES"
LAYER_COCHE = "ESTAC-COCHES"
LAYER_NUM = "ESTAC-NUMEROS"
LAYER_RAMPA = "ESTAC-RAMPA"
LAYER_RAMPA_LIN = "ESTAC-RAMPA-LINEAS"
COLOR_CAJON, COLOR_COCHE, COLOR_NUM = 8, 253, 94
COLOR_RAMPA, COLOR_RAMPA_LIN = 7, 14


def car_symbol(cx: float, cy: float, length: float, width: float,
               angle_deg: float = 0.0, layer: str = LAYER_COCHE,
               color: Optional[int] = None) -> list[str]:
    """Coche en planta centrado en (cx, cy). `length` va a lo largo del eje
    del coche, que apunta a `angle_deg` (0 = hacia +X). Carrocería, cabina,
    parabrisas, luneta y cuatro ruedas."""
    prim.capa(layer, COLOR_COCHE, 13)
    c = (cx, cy)
    L, W = length, width

    def R(p: prim.Point) -> prim.Point:
        return prim.rot((cx + p[0], cy + p[1]), c, angle_deg)

    hs: list[str] = []
    pts, bul = prim.rounded_rect(-L / 2, -W / 2, L / 2, W / 2, W * 0.28)
    hs.append(prim.poly([R(p) for p in pts], layer, True, 18, color, bul))
    pts, bul = prim.rounded_rect(-0.20 * L, -0.38 * W, 0.22 * L, 0.38 * W, W * 0.12)
    hs.append(prim.poly([R(p) for p in pts], layer, True, 13, color, bul))
    for x in (-0.28 * L, 0.30 * L):                       # luneta y capó
        hs.append(prim.line(R((x, -0.40 * W)), R((x, 0.40 * W)), layer, 13, color))
    for sx in (-0.30, 0.30):                               # ruedas
        for sy in (-1, 1):
            y0 = sy * (W / 2 - 0.02 * W)
            hs.append(prim.poly([R((sx * L - 0.09 * L, y0 - sy * 0.05 * W)),
                                 R((sx * L + 0.09 * L, y0 - sy * 0.05 * W)),
                                 R((sx * L + 0.09 * L, y0 + sy * 0.03 * W)),
                                 R((sx * L - 0.09 * L, y0 + sy * 0.03 * W))],
                                layer, True, 13, color))
    return hs


def parking_stalls(x: float, y: float, count: int, stall_width: float,
                   stall_depth: float, along: str = "x", depth_sign: int = 1,
                   start_number: int = 1, number_step: int = 1,
                   car: bool = True, car_length: float = 0.0,
                   number_radius: float = 0.0, text_height: float = 0.0,
                   layer: str = LAYER_CAJON, front_line: bool = True
                   ) -> dict[str, Any]:
    """Una fila de `count` cajones. (x, y) es la esquina de arranque de la
    línea del FONDO del primer cajón. `along`: 'x' (cajones uno junto al otro
    en X, profundidad en Y) o 'y'. `depth_sign`: +1 la profundidad crece hacia
    +Y (o +X si along='y'), -1 hacia el otro lado. Numera con `start_number`
    y `number_step` (negativo para numerar al revés). Cada línea se dibuja
    UNA vez (no hay separadores duplicados entre cajones vecinos)."""
    if count < 1 or stall_width <= 0 or stall_depth <= 0:
        raise ValueError("count, stall_width y stall_depth tienen que ser > 0.")
    if along not in ("x", "y") or depth_sign not in (1, -1):
        raise ValueError("along: 'x' o 'y'; depth_sign: 1 o -1.")
    prim.capa(layer, COLOR_CAJON, 25)
    prim.capa(LAYER_NUM, COLOR_NUM, 13)
    nr = number_radius or min(stall_width, stall_depth) * 0.13
    th = text_height or nr * 0.9
    cl = car_length or stall_depth * 0.80

    def P(i: float, d: float) -> prim.Point:
        """i = posición a lo largo de la fila, d = profundidad desde el fondo."""
        if along == "x":
            return (x + i, y + depth_sign * d)
        return (x + depth_sign * d, y + i)

    handles: list[str] = []
    numeros: list[int] = []
    with acad.lote():
        handles.append(prim.line(P(0, 0), P(count * stall_width, 0), layer, 25))
        if front_line:
            handles.append(prim.line(P(0, stall_depth),
                                     P(count * stall_width, stall_depth), layer, 25))
        for i in range(count + 1):
            handles.append(prim.line(P(i * stall_width, 0),
                                     P(i * stall_width, stall_depth), layer, 25))
        for i in range(count):
            n = start_number + i * number_step
            numeros.append(n)
            c = P((i + 0.5) * stall_width, stall_depth / 2)
            if car:
                # el eje del coche va a lo largo de la profundidad y el morro
                # mira hacia el FONDO del cajón (lo contrario de la profundidad)
                nx, ny = ((0.0, -float(depth_sign)) if along == "x"
                          else (-float(depth_sign), 0.0))
                handles += car_symbol(c[0], c[1], cl, stall_width * 0.62,
                                      math.degrees(math.atan2(ny, nx)))
            handles.append(prim.circle(c, nr, LAYER_NUM, 13))
            s = f"{n:02d}"
            handles.append(prim.text(s, c[0] - 0.30 * th * len(s),
                                     c[1] - 0.5 * th, th, LAYER_NUM))
    x0, y0 = P(0, 0)
    x1, y1 = P(count * stall_width, stall_depth)
    return {"handles": handles, "numbers": numeros,
            "box": [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)],
            "count": count}


def ramp_track(outer: tuple[float, float, float, float, float],
               inner: tuple[float, float, float, float, float],
               pitch: float, layer: str = LAYER_RAMPA,
               lines_layer: str = LAYER_RAMPA_LIN) -> dict[str, Any]:
    """Rampa en anillo: dos contornos redondeados (x0, y0, x1, y1, radio) y
    líneas "radiales" entre ellos cada `pitch` medido sobre el contorno
    exterior. Las líneas unen puntos de igual posición fraccionaria del
    perímetro, así que se abren en abanico en las curvas."""
    if pitch <= 0:
        raise ValueError("pitch tiene que ser > 0.")
    o, i = prim.Perimetro(*outer), prim.Perimetro(*inner)
    if not (outer[0] < inner[0] and outer[1] < inner[1]
            and inner[2] < outer[2] and inner[3] < outer[3]):
        raise ValueError("El contorno interior tiene que quedar dentro del exterior.")
    prim.capa(layer, COLOR_RAMPA, 35)
    prim.capa(lines_layer, COLOR_RAMPA_LIN, 5)
    n = max(8, int(round(o.largo / pitch)))
    handles: list[str] = []
    with acad.lote():
        pts, bul = prim.rounded_rect(*outer[:4], outer[4])
        handles.append(prim.poly(pts, layer, True, 35, None, bul))
        pts, bul = prim.rounded_rect(*inner[:4], inner[4])
        handles.append(prim.poly(pts, layer, True, 35, None, bul))
        for k in range(n):
            t = k / n
            handles.append(prim.line(o.punto(t)[0], i.punto(t)[0], lines_layer, 5))
    return {"handles": handles, "radialLines": n,
            "outerPerimeter": round(o.largo, 2), "innerPerimeter": round(i.largo, 2)}


def ramp_arc(center: prim.Point, r_in: float, r_out: float, start_deg: float,
             end_deg: float, pitch: float, layer: str = LAYER_RAMPA,
             lines_layer: str = LAYER_RAMPA_LIN) -> dict[str, Any]:
    """Tramo curvo de rampa entre dos arcos concéntricos, con líneas radiales
    cada `pitch` medido sobre el radio medio."""
    if not (0 < r_in < r_out) or pitch <= 0 or end_deg == start_deg:
        raise ValueError("Hace falta 0 < r_in < r_out, pitch > 0 y un arco no vacío.")
    prim.capa(layer, COLOR_RAMPA, 35)
    prim.capa(lines_layer, COLOR_RAMPA_LIN, 5)
    span = (end_deg - start_deg) % 360.0 or 360.0
    n = max(2, int(round(math.radians(span) * (r_in + r_out) / 2 / pitch)))
    handles: list[str] = []
    with acad.lote():
        handles.append(prim.arc(center, r_in, start_deg, end_deg, layer, 35))
        handles.append(prim.arc(center, r_out, start_deg, end_deg, layer, 35))
        for k in range(n + 1):
            a = math.radians(start_deg + span * k / n)
            handles.append(prim.line(
                (center[0] + r_in * math.cos(a), center[1] + r_in * math.sin(a)),
                (center[0] + r_out * math.cos(a), center[1] + r_out * math.sin(a)),
                lines_layer, 5))
    return {"handles": handles, "radialLines": n + 1}
