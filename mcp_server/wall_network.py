"""Encuentros de muros resueltos de una vez: la red entera, no tramo por tramo.

Por qué existe. Cada `create_walls` dibuja SU muro como contornos cerrados
que terminan en el eje. Donde dos muros de llamadas distintas se encuentran
pasaban dos cosas, y las dos se veían en el plano:

- **Sin fusionar**, las líneas de cada contorno se cruzan y sobresalen del
  encuentro: "le sobran puntas de cada lado", como un dibujante que no sabe
  rematar una esquina.
- **Fusionando** (union_regions), las puntas desaparecen pero la esquina
  EXTERIOR de una L queda mordida: ningún rectángulo cubre el cuadrito de
  medio espesor por medio espesor que está más allá de los dos ejes.

Acá la red se resuelve como lo resuelve quien dibuja a mano: en cada nodo se
ordenan los muros que llegan por ángulo y cada par vecino se remata a
inglete (la intersección de sus caras). En una L eso cierra la esquina; en
una T el muro que llega termina contra la cara del otro; en un cruce o en
un nodo de 3+ muros queda un "núcleo" poligonal que tapa el centro. Después
se calcula el contorno de la mampostería (menos los vanos) y se devuelve
como polilíneas cerradas: sin Regions, editables, y sin depender de una
operación booleana de AutoCAD que puede fallar.

Todo es geometría pura, sin AutoCAD: se prueba en test_wall_network.py.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from geom import Point, intersect, left_normal, unit

# Pasado este múltiplo del semiespesor, el inglete de un ángulo muy agudo se
# convierte en una espina larguísima: se corta en bisel, como en obra.
MITER_LIMIT = 4.0


def _cross(a: Point, b: Point) -> float:
    return a[0] * b[1] - a[1] * b[0]


def _angle(d: Point) -> float:
    return math.atan2(d[1], d[0]) % (2.0 * math.pi)


def _inside(x: float, y: float, poly: list[Point]) -> bool:
    """Ray casting SIN tolerancia de borde: las sondas caen a propósito a
    una distancia mínima del borde, y contar el borde como adentro las
    arruinaría."""
    dentro = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            if x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                dentro = not dentro
    return dentro


def _signed_area(poly: list[Point]) -> float:
    """Shoelace CON signo: los huecos (lazos horarios) restan."""
    return sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
               - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly))) / 2.0


def _bbox(poly: list[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


# ------------------------------------------------------------ la red

class _Seg:
    """Un tramo recto de eje, con sus cuatro esquinas por resolver."""

    def __init__(self, p0: Point, p1: Point, half: float, wall: int):
        self.p0, self.p1, self.half, self.wall = p0, p1, half, wall
        self.u = unit(p1[0] - p0[0], p1[1] - p0[1])
        self.n = left_normal(self.u)
        # Esquinas por defecto: extremo a escuadra (lo que queda en un
        # extremo libre). Los nodos las reemplazan por ingletes.
        self.s_left = (p0[0] + self.n[0] * half, p0[1] + self.n[1] * half)
        self.s_right = (p0[0] - self.n[0] * half, p0[1] - self.n[1] * half)
        self.e_left = (p1[0] + self.n[0] * half, p1[1] + self.n[1] * half)
        self.e_right = (p1[0] - self.n[0] * half, p1[1] - self.n[1] * half)

    def quad(self) -> list[Point]:
        return [self.s_right, self.e_right, self.e_left, self.s_left]


def _proyectar(p: Point, a: Point, b: Point) -> tuple[float, float]:
    """(t a lo largo de a→b, distancia perpendicular) del punto p."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2
    q = (a[0] + t * dx, a[1] + t * dy)
    return t, math.dist(p, q)


def snap_axes(walls: list[dict[str, Any]], snap: float
              ) -> tuple[list[list[Point]], list[dict[str, Any]]]:
    """Ajusta los extremos que quedaron CASI sobre otro muro.

    Un eje que termina a 2 cm del eje del muro al que llega no es una
    decisión de proyecto: es una coordenada mal tipeada, y dibujada tal
    cual deja un escalón o una rendija en el encuentro. Se ajusta, y se
    devuelve la lista de lo que se movió: nada se corrige en silencio.

    Solo se mueven EXTREMOS de eje (no vértices intermedios), y solo hacia
    otro extremo (encuentro en L o en cruce) o hacia el eje de otro muro
    (encuentro en T).
    """
    ejes = [[(float(p[0]), float(p[1])) for p in w["points"]] for w in walls]
    ajustes: list[dict[str, Any]] = []

    def _extremos():
        for wi, pts in enumerate(ejes):
            if walls[wi].get("closed"):
                continue
            yield wi, 0
            yield wi, len(pts) - 1

    # 1) Extremo contra extremo: se juntan en el primero que se vio.
    nodos: list[Point] = []
    for wi, k in _extremos():
        p = ejes[wi][k]
        cerca = [q for q in nodos if math.dist(p, q) <= snap]
        if cerca:
            q = min(cerca, key=lambda c: math.dist(p, c))
            if math.dist(p, q) > 1e-9:
                ajustes.append({"wall": wi, "from": [p[0], p[1]],
                                "to": [q[0], q[1]], "kind": "extremo"})
                ejes[wi][k] = q
        else:
            nodos.append(p)

    # 2) Extremo que cae junto al eje de OTRO muro (T): se lleva al eje.
    for wi, k in _extremos():
        p = ejes[wi][k]
        if any(math.dist(p, q) <= 1e-9 for q in nodos
               if sum(1 for wj, kj in _extremos()
                      if math.dist(ejes[wj][kj], q) <= 1e-9) > 1):
            continue    # ya es un nodo compartido: no es una T
        mejor: Optional[tuple[float, Point]] = None
        for wj, pts in enumerate(ejes):
            for i in range(len(pts) - 1):
                if wj == wi and i in (k - 1, k):
                    continue    # el propio tramo que termina ahí
                a, b = pts[i], pts[i + 1]
                if math.dist(a, b) < 1e-12:
                    continue
                t, d = _proyectar(p, a, b)
                largo = math.dist(a, b)
                if 1e-9 < d <= snap and -snap / largo <= t <= 1 + snap / largo:
                    t = min(max(t, 0.0), 1.0)
                    q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
                    if mejor is None or d < mejor[0]:
                        mejor = (d, q)
        if mejor is not None:
            q = mejor[1]
            ajustes.append({"wall": wi, "from": [p[0], p[1]],
                            "to": [q[0], q[1]], "kind": "T"})
            ejes[wi][k] = q
    return ejes, ajustes


def build_pieces(axes: list[list[Point]], halves: list[float],
                 closed: list[bool], tol: float
                 ) -> tuple[list[_Seg], list[list[Point]]]:
    """Tramos con sus esquinas resueltas + los núcleos de los nodos.

    Devuelve (tramos, núcleos). Cada tramo sabe dar su cuadrilátero; los
    núcleos son los polígonos que tapan el centro de un nodo de 3+ muros.
    La unión de todo es la mampostería exacta.
    """
    segs: list[_Seg] = []
    for wi, pts in enumerate(axes):
        pts = list(pts)
        if closed[wi] and math.dist(pts[0], pts[-1]) > tol:
            pts.append(pts[0])
        for i in range(len(pts) - 1):
            if math.dist(pts[i], pts[i + 1]) > tol:
                segs.append(_Seg(pts[i], pts[i + 1], halves[wi], wi))

    # Encuentros en T: un extremo que cae en el INTERIOR de otro tramo
    # parte ese tramo en dos. Así la T queda como un nodo de tres muros y
    # se remata igual que cualquier otro nodo.
    cambio = True
    while cambio:
        cambio = False
        extremos = [s.p0 for s in segs] + [s.p1 for s in segs]
        for idx, s in enumerate(segs):
            largo = math.dist(s.p0, s.p1)
            for p in extremos:
                t, d = _proyectar(p, s.p0, s.p1)
                if d <= tol and tol / largo < t < 1 - tol / largo:
                    q = (s.p0[0] + t * (s.p1[0] - s.p0[0]),
                         s.p0[1] + t * (s.p1[1] - s.p0[1]))
                    segs[idx:idx + 1] = [_Seg(s.p0, q, s.half, s.wall),
                                         _Seg(q, s.p1, s.half, s.wall)]
                    cambio = True
                    break
            if cambio:
                break

    # Nodos: los extremos que coinciden.
    nodos: list[tuple[Point, list[tuple[_Seg, bool]]]] = []
    for s in segs:
        for at_start, p in ((True, s.p0), (False, s.p1)):
            for q, ends in nodos:
                if math.dist(p, q) <= tol:
                    ends.append((s, at_start))
                    break
            else:
                nodos.append((p, [(s, at_start)]))

    nucleos: list[list[Point]] = []
    for p, ends in nodos:
        if len(ends) < 2:
            continue
        # Cada extremo, visto desde el nodo hacia afuera.
        brazos = []
        for s, at_start in ends:
            d = s.u if at_start else (-s.u[0], -s.u[1])
            brazos.append((_angle(d), d, s, at_start))
        brazos.sort(key=lambda b: b[0])
        puntos_nucleo: list[Point] = []
        for i in range(len(brazos)):
            _, da, sa, a_start = brazos[i]
            _, db, sb, b_start = brazos[(i + 1) % len(brazos)]
            na, nb = left_normal(da), left_normal(db)
            # Cara de A que mira a B (su izquierda, mirando hacia afuera) y
            # cara de B que mira a A (su derecha).
            ca = (p[0] + na[0] * sa.half, p[1] + na[1] * sa.half)
            cb = (p[0] - nb[0] * sb.half, p[1] - nb[1] * sb.half)
            x = None
            if abs(_cross(da, db)) > 1e-9:
                x = intersect(ca, da, cb, db)
                if (x is not None and math.dist(x, p)
                        > MITER_LIMIT * max(sa.half, sb.half)):
                    x = None    # ángulo muy agudo: bisel
            esq_a, esq_b = (x, x) if x is not None else (ca, cb)
            _asignar(sa, a_start, izquierda=True, punto=esq_a)
            _asignar(sb, b_start, izquierda=False, punto=esq_b)
            for q in (esq_a, esq_b):
                if not puntos_nucleo or math.dist(puntos_nucleo[-1], q) > tol:
                    puntos_nucleo.append(q)
        if (len(puntos_nucleo) > 2
                and math.dist(puntos_nucleo[0], puntos_nucleo[-1]) <= tol):
            puntos_nucleo.pop()
        if len(puntos_nucleo) >= 3 and abs(_signed_area(puntos_nucleo)) > tol * tol:
            nucleos.append(puntos_nucleo)
    return segs, nucleos


def _asignar(s: _Seg, at_start: bool, izquierda: bool, punto: Point) -> None:
    """Fija una esquina del tramo. 'izquierda' es mirando desde el nodo
    hacia afuera: en el extremo final eso es el lado DERECHO del tramo."""
    if at_start:
        if izquierda:
            s.s_left = punto
        else:
            s.s_right = punto
    else:
        if izquierda:
            s.e_right = punto
        else:
            s.e_left = punto


# ------------------------------------------------- contorno de la unión

def outline(pieces: list[list[Point]], cuts: list[list[Point]],
            tol: float) -> tuple[list[list[Point]], list[list[Point]]]:
    """Contorno de (unión de pieces) menos (unión de cuts).

    Se parten todos los bordes donde se cruzan con cualquier otro y se
    queda cada pedazo que tenga mampostería de un lado y nada del otro.
    Devuelve los lazos cerrados, cada uno con la mampostería a su
    izquierda (exteriores antihorarios, huecos horarios), y aparte las
    cadenas que no cerraron (no debería haber ninguna: si aparece, es un
    caso de tolerancia que hay que mirar, no algo para cerrar a la fuerza)."""
    eps = tol * 10.0
    regiones = [(p, _bbox(p)) for p in pieces]
    vanos = [(c, _bbox(c)) for c in cuts]

    def adentro(x: float, y: float) -> bool:
        if not any(b[0] <= x <= b[2] and b[1] <= y <= b[3] and _inside(x, y, p)
                   for p, b in regiones):
            return False
        return not any(b[0] <= x <= b[2] and b[1] <= y <= b[3]
                       and _inside(x, y, c) for c, b in vanos)

    bordes: list[tuple[Point, Point]] = []
    for poly in pieces + cuts:
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            if math.dist(a, b) > tol:
                bordes.append((a, b))
    cajas = [(min(a[0], b[0]) - tol, min(a[1], b[1]) - tol,
              max(a[0], b[0]) + tol, max(a[1], b[1]) + tol) for a, b in bordes]

    pedazos: dict[tuple, tuple[Point, Point]] = {}

    def clave(p: Point) -> tuple[int, int]:
        return (round(p[0] / tol), round(p[1] / tol))

    for i, (a, b) in enumerate(bordes):
        dx, dy = b[0] - a[0], b[1] - a[1]
        largo = math.hypot(dx, dy)
        ts = [0.0, 1.0]
        ca = cajas[i]
        for j, (c, d) in enumerate(bordes):
            if i == j:
                continue
            cb = cajas[j]
            if cb[0] > ca[2] or cb[2] < ca[0] or cb[1] > ca[3] or cb[3] < ca[1]:
                continue
            # Extremos del otro borde que caen sobre este (T y solapes).
            for q in (c, d):
                t, dist = _proyectar(q, a, b)
                if dist <= tol and 0.0 < t < 1.0:
                    ts.append(t)
            # Cruce propio.
            ex, ey = d[0] - c[0], d[1] - c[1]
            den = dx * ey - dy * ex
            if abs(den) > 1e-15:
                t = ((c[0] - a[0]) * ey - (c[1] - a[1]) * ex) / den
                s = ((c[0] - a[0]) * dy - (c[1] - a[1]) * dx) / den
                if 0.0 < t < 1.0 and -1e-12 <= s <= 1.0 + 1e-12:
                    ts.append(t)
        ts.sort()
        nx, ny = -dy / largo, dx / largo
        for t0, t1 in zip(ts, ts[1:]):
            if (t1 - t0) * largo <= tol:
                continue
            p0 = (a[0] + t0 * dx, a[1] + t0 * dy)
            p1 = (a[0] + t1 * dx, a[1] + t1 * dy)
            mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
            izq = adentro(mx + nx * eps, my + ny * eps)
            der = adentro(mx - nx * eps, my - ny * eps)
            if izq == der:
                continue        # adentro de los dos lados o afuera: no es borde
            tramo = (p0, p1) if izq else (p1, p0)
            pedazos[(clave(tramo[0]), clave(tramo[1]))] = tramo

    return _encadenar(list(pedazos.values()), clave, tol)


def _encadenar(tramos: list[tuple[Point, Point]], clave, tol: float
               ) -> tuple[list[list[Point]], list[list[Point]]]:
    """Une los pedazos en lazos. En un vértice donde se tocan dos lazos (dos
    muros que apenas se tocan en una esquina) se dobla lo más a la izquierda
    posible: así cada lazo sigue por su propio contorno."""
    salen: dict[tuple, list[int]] = {}
    for i, (a, _b) in enumerate(tramos):
        salen.setdefault(clave(a), []).append(i)
    usados = [False] * len(tramos)
    lazos: list[list[Point]] = []
    abiertas: list[list[Point]] = []
    for inicio in range(len(tramos)):
        if usados[inicio]:
            continue
        usados[inicio] = True
        lazo = [tramos[inicio][0]]
        actual = inicio
        for _ in range(len(tramos)):
            a, b = tramos[actual]
            lazo.append(b)
            if clave(b) == clave(tramos[inicio][0]):
                break
            din = unit(b[0] - a[0], b[1] - a[1])
            mejor, mejor_giro = None, -math.inf
            for j in salen.get(clave(b), []):
                if usados[j]:
                    continue
                c, d = tramos[j]
                dout = unit(d[0] - c[0], d[1] - c[1])
                giro = math.atan2(_cross(din, dout),
                                  din[0] * dout[0] + din[1] * dout[1])
                if giro > math.pi - 1e-9:
                    giro = -math.pi     # media vuelta: la última opción
                if giro > mejor_giro:
                    mejor, mejor_giro = j, giro
            if mejor is None:
                break
            usados[mejor] = True
            actual = mejor
        if clave(lazo[0]) == clave(lazo[-1]):
            lazos.append(_simplificar(lazo[:-1], tol))
        else:
            abiertas.append(lazo)
    return [l for l in lazos if len(l) >= 3], abiertas


def _simplificar(pts: list[Point], tol: float) -> list[Point]:
    """Saca los vértices que quedaron en medio de un lado recto."""
    cambio = True
    while cambio and len(pts) > 3:
        cambio = False
        for i in range(len(pts)):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
            if math.dist(a, c) > tol and _proyectar(b, a, c)[1] <= tol / 10.0:
                del pts[i]
                cambio = True
                break
    return pts


# ------------------------------------------------------------ todo junto

def resolve(walls: list[dict[str, Any]], tol: float = 1e-6,
            snap: Optional[float] = None) -> dict[str, Any]:
    """La red de muros resuelta: lazos de contorno, piezas y ajustes.

    walls: [{"points": [[x,y],...], "thickness": t, "closed": bool,
             "cuts": [[[x,y],...], ...]}] — 'cuts' son los polígonos de los
    vanos (los arma arch.py, que sabe ubicar los huecos sobre el eje).
    snap: hasta qué distancia se considera que un extremo quiso llegar a
    otro muro. Por default, medio espesor del muro más fino.
    """
    if not walls:
        raise ValueError("La red de muros está vacía.")
    halves = [float(w["thickness"]) / 2.0 for w in walls]
    if min(halves) <= 0:
        raise ValueError("Todos los muros necesitan thickness > 0.")
    if snap is None:
        snap = min(halves)
    ejes, ajustes = snap_axes(walls, snap) if snap > 0 else (
        [[(float(p[0]), float(p[1])) for p in w["points"]] for w in walls], [])
    closed = [bool(w.get("closed")) for w in walls]
    segs, nucleos = build_pieces(ejes, halves, closed, tol=max(tol, 1e-9))
    piezas = [s.quad() for s in segs] + nucleos
    cortes = [c for w in walls for c in (w.get("cuts") or [])]
    lazos, abiertas = outline(piezas, cortes, tol=max(tol, 1e-9))
    area = sum(_signed_area(l) for l in lazos)
    perimetro = sum(math.dist(l[i], l[(i + 1) % len(l)])
                    for l in lazos for i in range(len(l)))
    return {"loops": lazos, "openChains": abiertas,
            "axes": ejes, "snapped": ajustes,
            "quads": [s.quad() for s in segs], "cores": nucleos,
            "area": area, "perimeter": perimetro}
