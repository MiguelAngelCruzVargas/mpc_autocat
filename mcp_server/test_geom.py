"""Tests de geom.py. Matemática pura: no necesita AutoCAD ni el plugin.

Uso:  python test_geom.py
"""
from __future__ import annotations

import math
import sys

from geom import Axis

FAILED: list[str] = []


def check(name: str, got, expected, tol: float = 1e-6) -> None:
    if isinstance(expected, (tuple, list)):
        ok = (len(got) == len(expected)
              and all(abs(a - b) <= tol for a, b in zip(got, expected)))
    else:
        ok = abs(got - expected) <= tol
    if not ok:
        FAILED.append(f"{name}: esperaba {expected}, obtuve {got}")
    print(("  ok  " if ok else " FALLA ") + name)


def test_recta():
    """Muro recto horizontal de 10m: la paralela va derechito arriba/abajo."""
    ax = Axis([(0, 0), (10, 0)])
    check("largo total", ax.total_length, 10.0)
    izq = ax.offset_vertices(0.15)
    check("izq arranque", izq[0], (0.0, 0.15))
    check("izq final", izq[-1], (10.0, 0.15))
    der = ax.offset_vertices(-0.15)
    check("der arranque", der[0], (0.0, -0.15))


def test_esquina_recta():
    """Codo a 90°: el inglete tiene que dar la esquina exacta, sin escalón.

    Eje (0,0)->(10,0)->(10,10). Offset +0.15 (lado interior del codo) cae en
    (9.85, 0.15); offset -0.15 (exterior) en (10.15, -0.15).
    """
    ax = Axis([(0, 0), (10, 0), (10, 10)])
    interior = ax.offset_vertices(0.15)
    check("codo interior", interior[1], (9.85, 0.15))
    exterior = ax.offset_vertices(-0.15)
    check("codo exterior", exterior[1], (10.15, -0.15))


def test_cerrado():
    """Perímetro cerrado de 10x8: el offset interior da un rectángulo 9.7x7.7."""
    ax = Axis([(0, 0), (10, 0), (10, 8), (0, 8)], closed=True)
    check("perimetro", ax.total_length, 36.0)
    # Recorrido antihorario -> la normal izquierda apunta hacia adentro.
    dentro = ax.offset_vertices(0.15)
    xs = [p[0] for p in dentro]
    ys = [p[1] for p in dentro]
    check("ancho interior", max(xs) - min(xs), 9.7)
    check("alto interior", max(ys) - min(ys), 7.7)
    check("cierra sobre si mismo", dentro[0], dentro[-1])


def test_punto_a_distancia():
    ax = Axis([(0, 0), (10, 0), (10, 10)])
    check("punto a 5", ax.point_at(5.0), (5.0, 0.0))
    check("punto a 15", ax.point_at(15.0), (10.0, 5.0))
    check("punto pasado el final", ax.point_at(999.0), (10.0, 10.0))
    check("offset a 5", ax.offset_point_at(5.0, 0.15), (5.0, 0.15))


def test_tramo_entre_huecos():
    """Un tramo que no toca esquinas es un simple rectángulo."""
    ax = Axis([(0, 0), (10, 0)])
    pts = ax.vertices_between(2.0, 4.0, 0.15)
    check("tramo arranque", pts[0], (2.0, 0.15))
    check("tramo final", pts[-1], (4.0, 0.15))
    check("tramo sin vertices de mas", len(pts), 2)


def test_tramo_cruzando_esquina():
    """Un tramo que abarca el codo tiene que conservar el vértice a inglete."""
    ax = Axis([(0, 0), (10, 0), (10, 10)])
    pts = ax.vertices_between(5.0, 15.0, 0.15)
    check("cruza esquina: arranque", pts[0], (5.0, 0.15))
    check("cruza esquina: vertice", pts[1], (9.85, 0.15))
    check("cruza esquina: final", pts[-1], (9.85, 5.0))


def test_segmento_degenerado():
    """Un punto repetido no puede romper las normales."""
    ax = Axis([(0, 0), (0, 0), (10, 0)])
    check("ignora el segmento nulo", ax.total_length, 10.0)


def test_colineal():
    """Tres puntos en línea: no hay inglete posible, no debe explotar."""
    ax = Axis([(0, 0), (5, 0), (10, 0)])
    pts = ax.offset_vertices(0.15)
    check("colineal final", pts[-1], (10.0, 0.15))
    check("colineal medio", pts[1], (5.0, 0.15))


def main() -> int:
    for fn in [test_recta, test_esquina_recta, test_cerrado,
               test_punto_a_distancia, test_tramo_entre_huecos,
               test_tramo_cruzando_esquina, test_segmento_degenerado,
               test_colineal]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: geometria de muros correcta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
