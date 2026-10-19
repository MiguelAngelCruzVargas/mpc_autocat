"""Primitivas de trazo compartidas por los módulos de dibujo paramétrico
(estacionamientos, fachadas): una línea, una polilínea con bulges, un círculo,
un arco, un texto, un relleno sólido. Todas mandan UN comando al plugin y
devuelven el handle; los módulos las envuelven en `with acad.lote():` para
que un dibujo de cientos de entidades viaje en pocos viajes.

Los arcos se piden en grados antihorarios; los bulges son tan(ángulo/4).
"""
from __future__ import annotations

import math
from typing import Any, Optional, Sequence

import autocad_client as acad
import layers

Point = tuple[float, float]
K90 = math.tan(math.radians(90) / 4)


def capa(nombre: str, color: int, lw: int, linetype: Optional[str] = None) -> str:
    layers.ensure(nombre, color, lw, linetype)
    return nombre


def line(p: Point, q: Point, layer: str, lw: int = 18,
         color: Optional[int] = None) -> str:
    return acad.call("create_line", {
        "x1": p[0], "y1": p[1], "z1": 0.0, "x2": q[0], "y2": q[1], "z2": 0.0,
        "layer": layer, "lineweight": lw, "colorIndex": color})["handle"]


def poly(points: Sequence[Point], layer: str, closed: bool = True, lw: int = 25,
         color: Optional[int] = None,
         bulges: Optional[Sequence[float]] = None) -> str:
    return acad.call("create_polyline", {
        "points": [[p[0], p[1]] for p in points], "closed": closed,
        "layer": layer, "lineweight": lw, "colorIndex": color,
        "bulges": list(bulges) if bulges is not None else None})["handle"]


def circle(c: Point, r: float, layer: str, lw: int = 25,
           color: Optional[int] = None) -> str:
    return acad.call("create_circle", {
        "x": c[0], "y": c[1], "z": 0.0, "radius": r, "layer": layer,
        "lineweight": lw, "colorIndex": color})["handle"]


def arc(c: Point, r: float, a0: float, a1: float, layer: str, lw: int = 25,
        color: Optional[int] = None) -> str:
    return acad.call("create_arc", {
        "x": c[0], "y": c[1], "z": 0.0, "radius": r,
        "startAngleDeg": a0, "endAngleDeg": a1, "layer": layer,
        "lineweight": lw, "colorIndex": color})["handle"]


def text(s: str, x: float, y: float, h: float, layer: str, rot: float = 0.0,
         color: Optional[int] = None) -> str:
    return acad.call("create_text", {
        "text": s, "x": x, "y": y, "z": 0.0, "height": h, "layer": layer,
        "rotationDeg": rot, "lineweight": layers.LW_TEXTO,
        "colorIndex": color})["handle"]


def solid(points: Sequence[Point], layer: str, color: Optional[int] = None) -> str:
    """Polígono con relleno sólido (contorno + SOLID)."""
    h = poly(points, layer, True, 5, color)
    acad.call("create_hatch", {
        "boundaryHandle": h, "pattern": "SOLID", "scale": 1.0, "angleDeg": 0.0,
        "layer": layer, "lineweight": 5, "colorIndex": color,
        "islandHandles": None})
    return h


def rot(p: Point, c: Point, ang_deg: float) -> Point:
    a = math.radians(ang_deg)
    dx, dy = p[0] - c[0], p[1] - c[1]
    return (c[0] + dx * math.cos(a) - dy * math.sin(a),
            c[1] + dx * math.sin(a) + dy * math.cos(a))


def rounded_rect(x0: float, y0: float, x1: float, y1: float, r: float
                 ) -> tuple[list[Point], list[float]]:
    """Rectángulo de esquinas redondeadas (puntos + bulges, antihorario)."""
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    if r < 1e-9:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], [0.0] * 4
    pts = [(x0 + r, y0), (x1 - r, y0), (x1, y0 + r), (x1, y1 - r),
           (x1 - r, y1), (x0 + r, y1), (x0, y1 - r), (x0, y0 + r)]
    bul = [0.0, K90, 0.0, K90, 0.0, K90, 0.0, K90]
    op: list[Point] = []
    ob: list[float] = []
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        if math.dist(p, q) < 1e-9:
            continue
        op.append(p)
        ob.append(bul[i])
    return op, ob


class Perimetro:
    """Perímetro de un rectángulo redondeado parametrizado por longitud de
    arco: `punto(t)` con t en [0, 1) da el punto y la normal exterior. Sirve
    para trazar líneas "radiales" entre dos contornos concéntricos aunque
    tengan radios y anchos distintos (la rampa de un estacionamiento)."""

    def __init__(self, x0: float, y0: float, x1: float, y1: float, r: float):
        r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
        self.x0, self.y0, self.x1, self.y1, self.r = x0, y0, x1, y1, r
        w, h = x1 - x0 - 2 * r, y1 - y0 - 2 * r
        q = math.pi * r / 2
        # (tipo, largo, datos): recorrido antihorario desde (x0+r, y0)
        self.tramos = [
            ("L", w, ((x0 + r, y0), (x1 - r, y0), (0.0, -1.0))),
            ("A", q, ((x1 - r, y0 + r), 270.0)),
            ("L", h, ((x1, y0 + r), (x1, y1 - r), (1.0, 0.0))),
            ("A", q, ((x1 - r, y1 - r), 0.0)),
            ("L", w, ((x1 - r, y1), (x0 + r, y1), (0.0, 1.0))),
            ("A", q, ((x0 + r, y1 - r), 90.0)),
            ("L", h, ((x0, y1 - r), (x0, y0 + r), (-1.0, 0.0))),
            ("A", q, ((x0 + r, y0 + r), 180.0)),
        ]
        self.largo = sum(t[1] for t in self.tramos)

    def punto(self, t: float) -> tuple[Point, Point]:
        s = (t % 1.0) * self.largo
        for tipo, largo, d in self.tramos:
            if s <= largo + 1e-9:
                f = s / largo if largo > 1e-12 else 0.0
                if tipo == "L":
                    (ax, ay), (bx, by), n = d
                    return (ax + (bx - ax) * f, ay + (by - ay) * f), n
                (cx, cy), a0 = d
                a = math.radians(a0 + 90.0 * f)
                return ((cx + self.r * math.cos(a), cy + self.r * math.sin(a)),
                        (math.cos(a), math.sin(a)))
            s -= largo
        return self.tramos[0][2][0], (0.0, -1.0)
