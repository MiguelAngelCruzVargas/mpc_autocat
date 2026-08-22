"""Tests de roof.py (cubierta a dos aguas y armadura esquematica) contra el
socket mockeado. NO necesita AutoCAD.

Uso:  python test_roof.py
"""
from __future__ import annotations

import math
import sys

import preview

preview.install()

import roof  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def test_gable_roof_cumbrera_en_el_medio() -> None:
    preview.DRAWN.clear()
    r = roof.create_gable_roof(x=0.0, y=5.0, span=16.25, rise=2.46)
    check("cumbrera centrada en X",
          abs(r["ridge"]["x"] - 8.125) < 1e-6, r["ridge"])
    check("cumbrera a la cota alero+rise",
          abs(r["ridge"]["y"] - 7.46) < 1e-6, r["ridge"])
    check("dibuja las dos aguas (dos lineas)",
          sum(1 for d in preview.DRAWN if d["cmd"] == "create_line") == 2,
          preview.DRAWN)


def test_gable_roof_pendiente() -> None:
    r = roof.create_gable_roof(x=0.0, y=0.0, span=20.0, rise=5.0)
    # rise/half_span = 5/10 = 0.5 -> ~26.57 grados
    check("pendiente en m/m",
          abs(r["slopeRatio"] - 0.5) < 1e-6, r["slopeRatio"])
    check("pendiente en grados",
          abs(r["slopeDeg"] - math.degrees(math.atan(0.5))) < 0.01,
          r["slopeDeg"])
    check("largo de agua es la hipotenusa, no la proyeccion horizontal",
          r["slopeLength_m"] > 10.0, r["slopeLength_m"])


def test_gable_roof_con_volado() -> None:
    sin_volado = roof.create_gable_roof(x=0.0, y=0.0, span=10.0, rise=2.0)
    con_volado = roof.create_gable_roof(x=0.0, y=0.0, span=10.0, rise=2.0,
                                        overhang=0.5)
    check("el volado alarga el agua",
          con_volado["slopeLength_m"] > sin_volado["slopeLength_m"],
          (sin_volado["slopeLength_m"], con_volado["slopeLength_m"]))
    check("el alero con volado queda mas alla del apoyo",
          con_volado["leftEave"]["x"] < 0.0, con_volado["leftEave"])
    check("el alero con volado baja (sigue la pendiente, no horizontal)",
          con_volado["leftEave"]["y"] < 0.0, con_volado["leftEave"])


def test_gable_roof_rechaza_valores_invalidos() -> None:
    for kwargs, fragmento in [
        (dict(x=0, y=0, span=0.0, rise=1.0), "span"),
        (dict(x=0, y=0, span=10.0, rise=-1.0), "rise"),
        (dict(x=0, y=0, span=10.0, rise=1.0, overhang=-0.5), "overhang"),
    ]:
        try:
            roof.create_gable_roof(**kwargs)
            check(f"rechaza {fragmento} invalido", False, "no elevo excepcion")
        except ValueError as exc:
            check(f"rechaza {fragmento} invalido", fragmento in str(exc),
                  str(exc))


def test_truss_dibuja_cuerdas_y_montantes() -> None:
    preview.DRAWN.clear()
    r = roof.create_truss(x=0.0, y=0.0, span=12.0, rise=2.0, panels=3)
    check("una cuerda inferior",
          r["bottomChordHandle"] is not None, r)
    check("dos cuerdas superiores",
          len(r["topChordHandles"]) == 2, r["topChordHandles"])
    # panels=3 por media armadura -> 6 nodos internos -> 5 montantes
    check("montantes internos = panels*2 - 1",
          len(r["webHandles"]) == 5, r["webHandles"])
    check("total de lineas dibujadas = 3 cuerdas + 5 montantes",
          sum(1 for d in preview.DRAWN if d["cmd"] == "create_line") == 8,
          preview.DRAWN)
    check("misma cumbrera que create_gable_roof para el mismo claro",
          abs(r["ridge"]["x"] - 6.0) < 1e-6 and abs(r["ridge"]["y"] - 2.0) < 1e-6,
          r["ridge"])


def test_truss_rechaza_panels_invalido() -> None:
    try:
        roof.create_truss(x=0.0, y=0.0, span=10.0, rise=2.0, panels=0)
        check("rechaza panels 0", False, "no elevo excepcion")
    except ValueError as exc:
        check("rechaza panels 0", "panels" in str(exc), str(exc))


def main() -> int:
    for fn in [test_gable_roof_cumbrera_en_el_medio,
               test_gable_roof_pendiente,
               test_gable_roof_con_volado,
               test_gable_roof_rechaza_valores_invalidos,
               test_truss_dibuja_cuerdas_y_montantes,
               test_truss_rechaza_panels_invalido]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: roof.py dibuja cubierta a dos aguas y armadura esquematica "
          "sin tocar el plugin C#.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
