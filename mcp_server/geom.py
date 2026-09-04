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


def _cerrar(points: list) -> list[Point]:
    """La lista de vértices sin repetir el primero al final."""
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) >= 2 and math.dist(pts[0], pts[-1]) < EPS:
        pts = pts[:-1]
    if len(pts) < 3:
        raise ValueError("Un polígono necesita al menos 3 vértices distintos.")
    return pts


def polygon_area(points: list) -> float:
    """Superficie de un polígono por la fórmula del zapatero (shoelace).

    Siempre positiva: no importa si los vértices vienen en sentido horario o
    antihorario, que es como llegan de un plano real según por dónde se
    empezó a recorrer el terreno.
    """
    pts = _cerrar(points)
    doble = 0.0
    for i, p0 in enumerate(pts):
        p1 = pts[(i + 1) % len(pts)]
        doble += p0[0] * p1[1] - p1[0] * p0[1]
    return abs(doble) / 2.0


def polygon_perimeter(points: list) -> float:
    pts = _cerrar(points)
    return sum(math.dist(pts[i], pts[(i + 1) % len(pts)])
               for i in range(len(pts)))


def point_in_polygon(x: float, y: float, points: list,
                     tolerance: float = EPS) -> bool:
    """¿El punto cae DENTRO del polígono? (un punto sobre el borde cuenta).

    Ray casting horizontal. El borde se acepta a propósito: un recinto que
    apoya justo en la colindancia está adentro del terreno, y rechazarlo
    obligaría a dejar un retiro que el proyecto puede no tener.
    """
    pts = _cerrar(points)
    n = len(pts)

    for i in range(n):
        p0, p1 = pts[i], pts[(i + 1) % n]
        if _en_segmento(x, y, p0, p1, tolerance):
            return True

    adentro = False
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            corte = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < corte:
                adentro = not adentro
    return adentro


def _en_segmento(x: float, y: float, p0: Point, p1: Point,
                 tolerance: float) -> bool:
    """¿El punto está sobre el segmento, dentro de la tolerancia?"""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    largo = math.hypot(dx, dy)
    if largo < EPS:
        return math.dist((x, y), p0) <= tolerance
    # Distancia perpendicular a la recta, y que caiga entre los extremos.
    t = ((x - p0[0]) * dx + (y - p0[1]) * dy) / (largo * largo)
    if t < -tolerance or t > 1.0 + tolerance:
        return False
    px, py = p0[0] + t * dx, p0[1] + t * dy
    return math.hypot(x - px, y - py) <= tolerance


def segments_cross(a0: Point, a1: Point, b0: Point, b1: Point) -> bool:
    """¿Dos segmentos se cruzan de verdad? (tocarse en un extremo no cuenta)."""
    def lado(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    d1, d2 = lado(b0, b1, a0), lado(b0, b1, a1)
    d3, d4 = lado(a0, a1, b0), lado(a0, a1, b1)
    return ((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)) and \
           ((d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS))


def rect_in_polygon(x0: float, y0: float, x1: float, y1: float,
                    points: list, tolerance: float = 1e-6) -> bool:
    """¿El rectángulo entra ENTERO en el polígono?

    No alcanza con que las cuatro esquinas estén adentro: en un terreno
    cóncavo (una escuadra, un terreno en L) las cuatro pueden caer dentro y
    el rectángulo cruzar igual por afuera. Por eso además se comprueba que
    ningún lado del rectángulo corte un lado del polígono.
    """
    ax0, ax1 = min(x0, x1), max(x0, x1)
    ay0, ay1 = min(y0, y1), max(y0, y1)
    esquinas = [(ax0, ay0), (ax1, ay0), (ax1, ay1), (ax0, ay1)]
    if not all(point_in_polygon(px, py, points, tolerance)
               for px, py in esquinas):
        return False

    pts = _cerrar(points)
    n = len(pts)
    for i in range(4):
        a0, a1 = esquinas[i], esquinas[(i + 1) % 4]
        for j in range(n):
            if segments_cross(a0, a1, pts[j], pts[(j + 1) % n]):
                return False
    return True


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


def densify(points: list[list[float]], bulges: list[float],
            per_arc: int = 0) -> list[list[float]]:
    """Convierte una polilinea con arcos (bulges) en una poligonal fina.

    Los offsets paralelos trabajan sobre segmentos rectos, asi que un arco hay
    que muestrearlo: con pocos puntos la guarnicion de una curva sale poligonal
    y se nota.

    per_arc=0 lo decide el barrido: un segmento por grado. Con un numero fijo,
    una curva de 45 grados quedaba 0.5 mm mas corta que su desarrollo real y
    la ultima marca de cadenamiento (la del final del tramo) no se dibujaba.
    """
    out: list[list[float]] = []
    for i in range(len(points) - 1):
        p0, p1 = points[i], points[i + 1]
        b = bulges[i] if i < len(bulges) else 0.0
        out.append(list(p0))
        if abs(b) < 1e-12:
            continue
        # De bulge a arco: barrido = 4*atan(b), y de ahi centro y radio.
        barrido = 4.0 * math.atan(b)
        cuerda = math.dist(p0, p1)
        if cuerda < 1e-9:
            continue
        radio = cuerda / (2.0 * math.sin(abs(barrido) / 2.0))
        mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
        dx, dy = (p1[0] - p0[0]) / cuerda, (p1[1] - p0[1]) / cuerda
        h = math.sqrt(max(radio * radio - (cuerda / 2.0) ** 2, 0.0))
        signo = 1.0 if barrido > 0 else -1.0
        cx, cy = mx - dy * h * signo, my + dx * h * signo
        a0 = math.atan2(p0[1] - cy, p0[0] - cx)
        n = per_arc or min(360, max(8, int(math.degrees(abs(barrido)))))
        for k in range(1, n):
            a = a0 + barrido * k / n
            out.append([cx + radio * math.cos(a), cy + radio * math.sin(a)])
    out.append(list(points[-1]))
    return out


# ------------------------------------------- propiedades de una seccion

def section_properties(points: list[list[float]],
                       bulges: Optional[list[float]] = None,
                       arc_segments: int = 0) -> dict[str, float]:
    """Area, perimetro, centroide y momentos de inercia de un contorno cerrado.

    Existe porque calculate_area devolvia SOLO el area. El centroide y los
    momentos son lo que hace falta apenas se pasa de "cuanto concreto lleva"
    a "resiste": el modulo de seccion sale de ahi. Sin esto habia que
    calcularlos a mano cada vez, que es justo lo que esta biblioteca trata
    de no hacer.

    points: los vertices, sin repetir el primero al final (es lo que
    devuelve get_entity para una Polyline cerrada).
    bulges: uno por vertice, si el contorno tiene arcos. Los arcos se
    muestrean con densify, asi que el resultado es una APROXIMACION y se
    dice: 'exact' viene en False.

    El signo del area no importa -- se toma el valor absoluto -- pero los
    momentos se devuelven respecto del CENTROIDE, que es como se usan para
    dimensionar. Ixx flexiona alrededor del eje horizontal.

    Unidades: las del dibujo. Un area en m2 da momentos en m4.
    """
    # 2 vertices con bulges SI son un contorno cerrado: dos semicircunferencias
    # son un circulo, y asi lo guarda AutoCAD. Por eso el minimo de 3 se exige
    # DESPUES de muestrear los arcos, no antes.
    if not points or len(points) < 2:
        raise ValueError(
            "Hacen falta al menos 2 vertices; vinieron %d." % len(points or []))

    exacto = True
    pts = [[float(p[0]), float(p[1])] for p in points]
    if bulges and any(abs(float(b)) > 1e-12 for b in bulges):
        # densify espera el contorno abierto con el cierre explicito.
        cerrado = pts + [pts[0]]
        bs = [float(b) for b in bulges] + [0.0]
        pts = densify(cerrado, bs, arc_segments)
        if pts and math.dist(pts[0], pts[-1]) < 1e-9:
            pts = pts[:-1]
        exacto = False

    if len(pts) < 3:
        raise ValueError(
            "Con %d vertices y sin arcos no hay area que calcular." % len(pts))

    n = len(pts)
    a2 = 0.0        # 2A
    cx6 = 0.0       # 6*A*Cx
    cy6 = 0.0
    ixx12 = 0.0     # 12*Ixx respecto del origen
    iyy12 = 0.0
    perimetro = 0.0

    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        cruz = x0 * y1 - x1 * y0
        a2 += cruz
        cx6 += (x0 + x1) * cruz
        cy6 += (y0 + y1) * cruz
        ixx12 += (y0 * y0 + y0 * y1 + y1 * y1) * cruz
        iyy12 += (x0 * x0 + x0 * x1 + x1 * x1) * cruz
        perimetro += math.hypot(x1 - x0, y1 - y0)

    area_con_signo = a2 / 2.0
    if abs(area_con_signo) < 1e-12:
        raise ValueError(
            "El contorno tiene area cero: los vertices son colineales o se "
            "repiten.")

    cx = cx6 / (6.0 * area_con_signo)
    cy = cy6 / (6.0 * area_con_signo)
    area = abs(area_con_signo)

    # Steiner: del origen al centroide.
    ixx = abs(ixx12 / 12.0) - area * cy * cy
    iyy = abs(iyy12 / 12.0) - area * cx * cx

    return {
        "area": area,
        "perimeter": perimetro,
        "centroidX": cx,
        "centroidY": cy,
        "Ixx": ixx,
        "Iyy": iyy,
        "vertices": n,
        "exact": exacto,
    }
