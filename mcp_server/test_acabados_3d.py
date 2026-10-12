"""Acabados del 3D sin AutoCAD: texturas, código generado y muebles.

Lo que salió al armarlo en AutoCAD: el forro de ladrillo tapaba la cochera
(vano abierto), sin piso se veía el pasto adentro, una caja por mueble se
leía como baúl y los planos 2D flotaban en el cielo de la vista.

Uso:  python test_acabados_3d.py
"""
from __future__ import annotations

import math
import os
import sys

import engine
import model3d_acabados as acab

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


ROOMS = [{"name": "COCHERA", "x0": 0.0, "y0": 0.0, "x1": 5.6, "y1": 6.0},
         {"name": "SALA", "x0": 5.6, "y0": 0.0, "x1": 12.0, "y1": 6.0}]
DOORS = [{"from": "EXTERIOR", "to": "COCHERA", "width": 5.0, "type": "pass", "open": True,
          "x": 2.8, "y": 0.0},
         {"from": "EXTERIOR", "to": "SALA", "width": 1.0, "x": 8.5, "y": 0.0},
         {"from": "COCHERA", "to": "SALA", "width": 0.9, "x": 5.6, "y": 3.0}]
WINS = [{"room": "SALA", "x": 10.5, "y": 0.0, "width": 1.5, "height": 1.2}]


def test_texturas() -> None:
    t = acab.texturas()
    check("cinco texturas", set(t) == {"ladrillo", "madera", "pasto", "follaje", "piso"}, str(t))
    ruta, ancho, alto = t["ladrillo"]
    check("ladrillo a escala real (dos hiladas de 7 cm)", (ancho, alto) == (0.50, 0.14),
          str((ancho, alto)))
    with open(ruta, "rb") as f:
        check("es un BMP", f.read(2) == b"BM")


def test_codigo_del_nivel() -> None:
    nivel = {"rooms": ROOMS, "doors": DOORS, "windows": WINS, "base_z": 0.0,
             "wall_height": 2.75, "slab_thickness": 0.15, "offset": 100.0,
             "furniture": [{"type": "dining_table", "x": 9.0, "y": 3.0, "rotation_deg": 0.0},
                           {"type": "sofa", "x": 6.0, "y": 0.5, "rotation_deg": 0.0}]}
    c = acab._codigo_nivel(nivel, 0.15, 0.12, 1.2, {})
    check("hay forro de ladrillo", "mLadrillo" in c)
    check("el vano abierto de la cochera se resta del forro (5.00 m)", "caja(5.0000" in c, c[:400])
    check("puerta de madera", "mMadera" in c)
    check("ventana con vidrio y marco", "mVidrio" in c and "mAluminio" in c)
    check("piso cerámico", "mPiso" in c)
    check("muebles por piezas (mesa + sillas son muchas)", c.count("CAPA_MUEBLES") == 0
          and c.count("3D-MUEBLES") > 20, str(c.count("3D-MUEBLES")))
    check("corrido al offset", "100." in c or "10" in c)


def test_mueble_girado() -> None:
    # Una cama girada 90°: sus piezas quedan del lado correcto del ancla.
    linea = acab._mueble({"type": "bed", "x": 2.0, "y": 1.0, "rotation_deg": 90.0,
                          "width": 1.6, "length": 2.0}, 0.0, 0.0)
    check("cama con base, colchón, cobertor, cabecera y 2 almohadas", linea.count("poner(") == 6,
          str(linea.count("poner(")))
    # girada 90°, todo cae a la izquierda del ancla (x <= 2.0)
    import re
    xs = [float(m) for m in re.findall(r"caja\([^,]+, [^,]+, [^,]+, ([-\d.]+),", linea)]
    check("girada 90° queda a la izquierda del ancla", all(x <= 2.0 + 1e-6 for x in xs), str(xs))


def test_vista_aisla_el_2d(monkeypatch=None) -> None:
    capturado = {}

    def falso(code, description="", **k):
        capturado["code"] = code
        return {"compiled": True, "executed": True}
    original = engine.run_code
    engine.run_code = falso
    try:
        r = acab.set_3d_view([0, -10, 1.6], [0, 0, 1.6], lens=20, roof_visible=True)
    finally:
        engine.run_code = original
    c = capturado["code"]
    check("vista ok", r["ok"], str(r))
    check("perspectiva", "PerspectiveEnabled = true" in c)
    check("aísla el 3D (apaga lo que no es 3D-)", 'StartsWith("3D-")' in c)
    check("la cámara queda 10 m atrás del objetivo", "new Vector3d(0.0000, -10.0000, 0.0000)" in c,
          c[:300])
    try:
        acab.set_3d_view([1, 1, 1], [1, 1, 1])
        check("cámara = objetivo falla", False)
    except ValueError:
        check("cámara = objetivo falla", True)


def main() -> int:
    for t in (test_texturas, test_codigo_del_nivel, test_mueble_girado, test_vista_aisla_el_2d):
        print(t.__name__)
        t()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" - " + f)
        return 1
    print("\nOK: acabados del 3D.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
