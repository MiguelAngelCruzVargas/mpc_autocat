"""Castillos de la muraria confinada. NO necesita AutoCAD.

Fija las reglas de oficio: uno en cada esquina/cruce, a los lados de las
ventanas, nunca dos tramos más largos que la separación máxima, y nunca dos
castillos pegados (el machón chico lleva uno solo, y la esquina manda).

Uso:  python test_castillos.py
"""
from __future__ import annotations

import math
import sys

import preview

preview.install()

import arch  # noqa: E402

FALLAS: list[str] = []


def check(nombre: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FALLAS.append(f"{nombre}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + nombre + (f" -- {detalle}" if not ok else ""))


def main() -> int:
    # Una casita de 2 cuartos: 8 x 4 m en ejes, divisorio en x=4.
    rooms = [{"name": "SALA", "x0": 0, "y0": 0, "x1": 4, "y1": 4},
             {"name": "RECÁMARA", "x0": 4, "y0": 0, "x1": 8, "y1": 4}]
    doors = [{"from": "EXTERIOR", "to": "SALA", "width": 0.9, "x": 2.0, "y": 0.0},
             {"from": "SALA", "to": "RECÁMARA", "width": 0.8, "x": 4.0, "y": 2.0}]
    windows = [{"room": "RECÁMARA", "x": 6.0, "y": 0.0, "width": 1.2}]
    r = arch.plan_castillos(rooms, doors, windows, 0.15, 0.10, max_spacing=3.0)
    pts = [tuple(p) for p in r["points"]]

    def hay(x: float, y: float, tol: float = 1e-3) -> bool:
        return any(math.dist(p, (x, y)) <= tol for p in pts)

    for esq in ((0, 0), (8, 0), (8, 4), (0, 4), (4, 0), (4, 4)):
        check(f"castillo en esquina/T {esq}", hay(*esq))
    check("castillos a los lados de la ventana",
          hay(6.0 - 0.6 - 0.075, 0.0) and hay(6.0 + 0.6 + 0.075, 0.0), str(sorted(pts)))
    check("castillos a los lados de la puerta exterior",
          hay(2.0 - 0.45 - 0.075, 0.0) and hay(2.0 + 0.45 + 0.075, 0.0), str(sorted(pts)))
    cercanos = [(a, b) for i, a in enumerate(pts) for b in pts[i + 1:] if math.dist(a, b) < 0.30]
    check("nunca dos castillos a menos de 0.30", not cercanos, str(cercanos))
    # Muro de fondo (y=4) de 8 m sin vanos: con esquinas en 0, 4 y 8 hay
    # tramos de 4 m > 3.0 -> se intercala uno en cada uno.
    en_fondo = sorted(p[0] for p in pts if abs(p[1] - 4) < 1e-6)
    tramos = [b - a for a, b in zip(en_fondo, en_fondo[1:])]
    check("ningún tramo supera la separación máxima", max(tramos) <= 3.0 + 1e-6, str(en_fondo))

    if FALLAS:
        print("\n%d FALLAS:" % len(FALLAS))
        for f in FALLAS:
            print(" -", f)
        return 1
    print("\nOK: los castillos confinan donde corresponde y sin amontonarse.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
