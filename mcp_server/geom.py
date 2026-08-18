"""Geometría 2D para armar muros: offset de polilínea con unión a inglete.

Separado de arch.py porque es matemática pura, sin AutoCAD de por medio: se
puede probar sola (ver test_geom.py).

Convención: la normal "izquierda" de un segmento que va de p0 a p1 es la
dirección (p1-p0) rotada +90°. Un offset positivo va hacia la izquierda del
sentido de avance.
"""
from __future__ import annotations

import math
from typing import Optional

Point = tuple[float, float]

EPS = 1e-9


def unit(dx: float, dy: float) -> Optional[Point]:
    """Vector unitario, o None si el vector es (casi) nulo."""
    length = math.hypot(dx, dy)
    if length < EPS:
        return None
    return dx / length, dy / length


def left_normal(u: Point) -> Point:
    """Normal izquierda de un vector unitario (rotación +90°)."""
    return -u[1], u[0]


def intersect(p: Point, u: Point, q: Point, v: Point) -> Optional[Point]:
    """Intersección de las rectas p+s·u y q+t·v. None si son paralelas."""
    den = u[0] * v[1] - u[1] * v[0]
    if abs(den) < 1e-12:
        return None
    dx, dy = q[0] - p[0], q[1] - p[1]
    s = (dx * v[1] - dy * v[0]) / den
    return p[0] + s * u[0], p[1] + s * u[1]


class Axis:
    """Eje de un muro: la polilínea por la que pasa su centro.

    Precalcula, para cada segmento, su dirección y su normal, y las distancias
    acumuladas — que es lo que permite ubicar un hueco "a 1.20m del arranque".
    """

    def __init__(self, points: list[Point], closed: bool = False):
        pts = [(float(x), float(y)) for x, y in points]
        if len(pts) < 2:
            raise ValueError("Un eje de muro necesita al menos 2 puntos.")
        if closed and pts[0] != pts[-1]:
            pts = pts + [pts[0]]

        self.points: list[Point] = []
        self.dirs: list[Point] = []
        self.normals: list[Point] = []
        self.lengths: list[float] = []

        # Descartamos segmentos de largo cero: rompen todas las normales.
        self.points.append(pts[0])
        for i in range(len(pts) - 1):
            u = unit(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            if u is None:
                continue
            self.points.append(pts[i + 1])
            self.dirs.append(u)
            self.normals.append(left_normal(u))
            self.lengths.append(math.dist(pts[i], pts[i + 1]))

        if not self.dirs:
            raise ValueError("El eje del muro tiene largo cero.")

        self.closed = closed
        self.cumulative = [0.0]
        for length in self.lengths:
            self.cumulative.append(self.cumulative[-1] + length)

    @property
    def total_length(self) -> float:
        return self.cumulative[-1]

    def segment_at(self, distance: float) -> tuple[int, float]:
        """(índice de segmento, distancia dentro de ese segmento)."""
        d = min(max(distance, 0.0), self.total_length)
        for i in range(len(self.lengths)):
            if d <= self.cumulative[i + 1] or i == len(self.lengths) - 1:
                return i, d - self.cumulative[i]
        return len(self.lengths) - 1, self.lengths[-1]

    def point_at(self, distance: float) -> Point:
        """Punto del eje a esa distancia del arranque."""
        i, local = self.segment_at(distance)
        p, u = self.points[i], self.dirs[i]
        return p[0] + u[0] * local, p[1] + u[1] * local

    def offset_point_at(self, distance: float, offset: float) -> Point:
        """Punto de la paralela, medido perpendicular al eje en esa distancia."""
        i, local = self.segment_at(distance)
        p, u, n = self.points[i], self.dirs[i], self.normals[i]
        return (p[0] + u[0] * local + n[0] * offset,
                p[1] + u[1] * local + n[1] * offset)

    def offset_vertices(self, offset: float) -> list[Point]:
        """Vértices de la polilínea paralela, con las esquinas a inglete.

        Cada vértice interior es la intersección de las dos rectas paralelas
        vecinas: eso es lo que hace que dos muros que se cruzan en una esquina
        cierren sin escalón ni superposición.
        """
        n_seg = len(self.dirs)
        lines = [((self.points[i][0] + self.normals[i][0] * offset,
                   self.points[i][1] + self.normals[i][1] * offset),
                  self.dirs[i])
                 for i in range(n_seg)]

        result: list[Point] = []

        if self.closed:
            for i in range(n_seg):
                prev = lines[i - 1]
                cur = lines[i]
                point = intersect(prev[0], prev[1], cur[0], cur[1])
                # Paralelos (muro que sigue derecho): el inglete no existe,
                # sirve el punto trasladado.
                result.append(point if point is not None else cur[0])
            result.append(result[0])
            return result

        result.append(lines[0][0])
        for i in range(1, n_seg):
            prev, cur = lines[i - 1], lines[i]
            point = intersect(prev[0], prev[1], cur[0], cur[1])
            result.append(point if point is not None else cur[0])
        last_p, last_u = lines[-1]
        result.append((last_p[0] + last_u[0] * self.lengths[-1],
                       last_p[1] + last_u[1] * self.lengths[-1]))
        return result

    def vertices_between(self, d_start: float, d_end: float,
                         offset: float) -> list[Point]:
        """Paralela entre dos distancias: extremos perpendiculares al eje y
        esquinas a inglete en el medio. Es lo que arma un tramo de muro entre
        dos huecos."""
        mitred = self.offset_vertices(offset)
        i_start, _ = self.segment_at(d_start)
        i_end, _ = self.segment_at(d_end)

        pts = [self.offset_point_at(d_start, offset)]
        # Vertices de esquina estrictamente adentro del tramo.
        for i in range(i_start + 1, i_end + 1):
            pts.append(mitred[i])
        pts.append(self.offset_point_at(d_end, offset))

        # Sacamos repetidos que aparecen cuando un hueco arranca justo en una
        # esquina.
        clean: list[Point] = []
        for p in pts:
            if not clean or math.dist(clean[-1], p) > 1e-7:
                clean.append(p)
        return clean
