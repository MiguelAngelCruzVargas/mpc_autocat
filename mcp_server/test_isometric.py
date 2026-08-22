"""Tests de isometric.py (cajas en proyeccion isometrica 30 grados, sin
geometria 3D real) contra el socket mockeado. NO necesita AutoCAD.

Uso:  python test_isometric.py
"""
from __future__ import annotations

import math
import sys

import preview

preview.install()

import isometric  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def test_proyeccion_ejes_conocidos() -> None:
    """Los tres ejes reales tienen que proyectar en las tres direcciones
    clasicas del isometrico: X hacia arriba-derecha, Y hacia arriba-
    izquierda, Z derecho hacia arriba."""
    ox, oy = isometric.iso_project(0, 0, 0)
    check("origen en el origen", abs(ox) < 1e-9 and abs(oy) < 1e-9, (ox, oy))

    xx, xy = isometric.iso_project(1, 0, 0)
    check("eje X: componente horizontal positiva", xx > 0, xx)
    check("eje X: sube (no baja)", xy > 0, xy)

    yx, yy = isometric.iso_project(0, 1, 0)
    check("eje Y: componente horizontal negativa (va a la izquierda)",
          yx < 0, yx)
    check("eje Y: sube igual que X", abs(yy - xy) < 1e-9, (yy, xy))

    zx, zy = isometric.iso_project(0, 0, 1)
    check("eje Z: sin componente horizontal", abs(zx) < 1e-9, zx)
    check("eje Z: sube derecho, 1 unidad real = 1 unidad de pagina",
          abs(zy - 1.0) < 1e-9, zy)


def test_caja_dibuja_tres_caras() -> None:
    preview.DRAWN.clear()
    r = isometric.create_isometric_box(x=0, y=0, z=0, dx=0.4, dy=0.4, dz=1.5)
    check("tres caras (top/right/left)",
          sum(1 for d in preview.DRAWN if d["cmd"] == "create_polyline") == 3,
          preview.DRAWN)
    check("cada cara con 4 vertices",
          all(len(d["points"]) == 4 for d in preview.DRAWN
              if d["cmd"] == "create_polyline"),
          preview.DRAWN)


def test_caja_rechaza_dimensiones_invalidas() -> None:
    for kwargs in [dict(dx=0.0, dy=0.4, dz=1.0),
                  dict(dx=0.4, dy=0.0, dz=1.0),
                  dict(dx=0.4, dy=0.4, dz=0.0)]:
        try:
            isometric.create_isometric_box(x=0, y=0, z=0, **kwargs)
            check("rechaza dimension 0", False, "no elevo excepcion")
        except ValueError:
            check("rechaza dimension 0", True)


def test_top_center_coincide_con_la_proyeccion_manual() -> None:
    r = isometric.create_isometric_box(x=1.0, y=2.0, z=0.5, dx=0.4, dy=0.4, dz=1.5)
    esperado = isometric.iso_project(1.0 + 0.2, 2.0 + 0.2, 0.5 + 1.5)
    check("topCenter es el centro real de la cara superior, proyectado",
          abs(r["topCenter"]["x"] - esperado[0]) < 1e-9
          and abs(r["topCenter"]["y"] - esperado[1]) < 1e-9,
          (r["topCenter"], esperado))


def test_apilar_columna_sobre_dado_con_hatch() -> None:
    """El caso real: dado mas ancho abajo, columna angosta arriba, cada
    uno su color -- no debe fallar ni mezclar handles entre cajas."""
    preview.DRAWN.clear()
    dado = isometric.create_isometric_box(x=0, y=0, z=0, dx=0.5, dy=0.5, dz=0.5,
                                          hatch_pattern="SOLID", color_index=96)
    columna = isometric.create_isometric_box(x=0.05, y=0.05, z=0.5,
                                             dx=0.4, dy=0.4, dz=2.0,
                                             hatch_pattern="SOLID", color_index=12)
    check("las dos cajas devuelven handles distintos",
          dado["topFaceHandle"] != columna["topFaceHandle"], (dado, columna))
    check("la base de la columna proyecta mas arriba que la del dado "
          "(z apilado se nota en la pagina)",
          columna["frontBottomCorner"]["y"] > dado["frontBottomCorner"]["y"],
          (dado["frontBottomCorner"], columna["frontBottomCorner"]))


def main() -> int:
    for fn in [test_proyeccion_ejes_conocidos,
               test_caja_dibuja_tres_caras,
               test_caja_rechaza_dimensiones_invalidas,
               test_top_center_coincide_con_la_proyeccion_manual,
               test_apilar_columna_sobre_dado_con_hatch]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: isometric.py proyecta cajas en 30 grados clasicos sin "
          "geometria 3D, componiendo sobre las mismas tools 2D de siempre.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
