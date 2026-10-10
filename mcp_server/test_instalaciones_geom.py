"""Tests de la geometría de instalaciones (sin AutoCAD).

Uso:  python test_instalaciones_geom.py
"""
from __future__ import annotations

import math
import sys

import instalaciones_geom as g

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def test_conexion_en_el_muro_de_atras() -> None:
    wc = {"type": "wc", "x": 1.0, "y": 4.0, "rotation_deg": 0.0}
    check("WC a 0°: conecta al centro del tanque, contra el muro",
          g.conexion(wc) == (1.19, 4.0), str(g.conexion(wc)))
    girado = {"type": "lavatory", "x": 2.0, "y": 3.0, "rotation_deg": 90.0,
              "width": 0.60}
    x, y = g.conexion(girado)
    check("girado 90°: la conexión sigue sobre el muro (x fija)",
          abs(x - 2.0) < 1e-9 and abs(y - 3.3) < 1e-9, f"{(x, y)}")


def test_red_comparte_troncales() -> None:
    red = g.red_en_arbol((0, 0), [((5, 3), 3, "wc"), ((5, 4), 1, "lav"),
                                  ((2, 3), 2, "reg")])
    tramos = red.tramos()
    check("todos los tramos son ortogonales",
          all(abs(t["desde"][0] - t["hasta"][0]) < 1e-9
              or abs(t["desde"][1] - t["hasta"][1]) < 1e-9 for t in tramos))
    desde_raiz = [t for t in tramos if t["desde"] == (0, 0)]
    check("UN solo tramo sale de la fuente (troncal compartida)",
          len(desde_raiz) == 1, str(desde_raiz))
    check("y lleva la carga de todo lo que alimenta (3+1+2)",
          desde_raiz and desde_raiz[0]["carga"] == 6, str(desde_raiz))
    largo = sum(t["largo"] for t in tramos)
    check("menos tubería que tres líneas independientes desde la fuente",
          largo < (5 + 3) + (5 + 4) + (2 + 3), str(largo))
    hojas = sorted(red.aguas_abajo(0))
    check("desde la raíz se ven las tres salidas", hojas == ["lav", "reg", "wc"],
          str(hojas))


def test_tramos_de_muro_saltan_puertas() -> None:
    caja = (0.0, 0.0, 4.0, 3.0)
    tramos = g.tramos_de_muro(caja, [("bottom", 1.0, 1.9)])
    abajo = [(t["a0"], t["a1"]) for t in tramos if t["lado"] == "bottom"]
    check("el muro de abajo queda partido por la puerta",
          abajo == [(0.0, 1.0), (1.9, 4.0)], str(abajo))
    largo = sum(t["a1"] - t["a0"] for t in tramos)
    check("perímetro libre = perímetro - vano", math.isclose(largo, 14 - 0.9),
          str(largo))


def main() -> int:
    for t in (test_conexion_en_el_muro_de_atras, test_red_comparte_troncales,
              test_tramos_de_muro_saltan_puertas):
        print(t.__name__)
        t()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" - " + f)
        return 1
    print("\nOK: geometría de instalaciones.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
