"""Tests de phone3d.py (teléfono 3D por dimensiones) con el socket
mockeado. NO necesita AutoCAD.

Uso:  python test_phone3d.py
"""
from __future__ import annotations

import math
import sys

import autocad_client as acad

import phone3d

FAILED: list[str] = []
CALLS: list[tuple[str, dict]] = []
_n = [0x200]


def fake_call(cmd, params=None, fallback=None):
    CALLS.append((cmd, params or {}))
    _n[0] += 1
    return {"handle": format(_n[0], "X"), "edgesFilleted": 12}


acad.call = fake_call  # type: ignore[assignment]


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


DIM = dict(width=78.0, height=163.4, thickness=8.75, corner_radius=12.0)
FULL = dict(
    DIM, edge_radius=2.0,
    screen={"bezel": 1.5, "depth": 0.8,
            "island": {"width": 20, "height": 6, "from_top": 3}},
    plateau={"width": 38, "height": 38, "protrusion": 1.0,
             "from_left": 4, "from_top": 4, "corner_radius": 9},
    lenses=[{"dx": 12, "dy": 12, "diameter": 12, "ring_diameter": 15,
             "protrusion": 2.0},
            {"dx": 26, "dy": 26, "diameter": 12, "ring_diameter": 15,
             "protrusion": 2.0}],
    buttons=[{"side": "left", "from_start": 30, "length": 12, "protrusion": 0.6},
             {"side": "right", "from_start": 50, "length": 18,
              "protrusion": 0.6, "height": 3.0}])


def _area_poligono(pts, bul):
    """Área de un contorno con bulges (shoelace + segmentos circulares)."""
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += (x1 * y2 - x2 * y1) / 2
        b = bul[i]
        if b:
            c = math.dist(pts[i], pts[(i + 1) % n])
            th = 4 * math.atan(b)
            r = c / (2 * math.sin(th / 2))
            a += r * r / 2 * (th - math.sin(th))
    return a


def test_rounded_rect_area() -> None:
    p, b = phone3d.rounded_rect(0, 0, 78, 163.4, 12)
    esperado = 78 * 163.4 - (4 - math.pi) * 12 ** 2
    check("rounded_rect: 8 vértices", len(p) == 8, len(p))
    check("rounded_rect: área = caja - 4 esquinas",
          abs(_area_poligono(p, b) - esperado) < 1e-6,
          _area_poligono(p, b))
    p2, b2 = phone3d.rounded_rect(0, 0, 10, 4, 2)
    check("píldora: sin tramos de largo 0", len(p2) == 6, len(p2))
    check("píldora: área exacta",
          abs(_area_poligono(p2, b2) - (6 * 4 + math.pi * 4)) < 1e-6)


def test_circle() -> None:
    p, b = phone3d.circle(5, 5, 12)
    check("círculo: area pi r2",
          abs(_area_poligono(p, b) - math.pi * 36) < 1e-6)


def test_completo() -> None:
    CALLS.clear()
    r = phone3d.create_phone(**FULL, finish="azul", colors={"button": 8})
    cmds = [c for c, _ in CALLS]
    check("usa extrude_profile, solid_boolean y fillet (no run_code)",
          set(cmds) == {"extrude_profile", "solid_boolean",
                        "fillet_solid_edges"}, set(cmds))
    check("fillet del canto: Z 0 y espesor, solo exterior",
          any(c == "fillet_solid_edges" and p["zPlanes"] == [0.0, 8.75]
              and p["outerOnly"] and p["radius"] == 2.0 for c, p in CALLS))
    ext = [p for c, p in CALLS if c == "extrude_profile"]
    # cuerpo, corte, vidrio, isla, plateau, 2x(anillo+vidrio), 2 botones
    check("cantidad de sólidos", len(ext) == 1 + 1 + 1 + 1 + 1 + 4 + 2, len(ext))
    check("cuerpo de Z=0 a espesor", ext[0]["z0"] == 0.0 and ext[0]["height"] == 8.75)
    check("plateau baja hacia -Z",
          any(p["layer"] == "TEL-PLATEAU" and p["height"] < 0 for p in ext))
    check("colores del acabado + override",
          r["colors"]["body"] == 150 and r["colors"]["button"] == 8, r["colors"])
    check("cada pieza lleva su colorIndex",
          {p["layer"]: p["colorIndex"] for p in ext}["TEL-CUERPO"] == 150)
    check("el rebaje se resta del cuerpo y se consume",
          any(c == "solid_boolean" and p["op"] == "subtract"
              and p["deleteTools"] and p["target"] == r["pieces"]["body"]
              for c, p in CALLS))
    check("handles del rebaje no quedan en la lista",
          len(r["handles"]) == len(ext) - 1, len(r["handles"]))
    check("botón izquierdo sale del costado",
          any(p["layer"] == "TEL-BOTONES" and
              min(q[0] for q in p["points"]) < 0 for p in ext))


def test_cuatro_acabados() -> None:
    cuerpos = set()
    for f in phone3d.ACABADOS:
        r = phone3d.create_phone(**DIM, finish=f)
        cuerpos.add(r["colors"]["body"])
    check("4 acabados con cuerpo distinto", len(cuerpos) == 4, cuerpos)


def test_origen_y_prefijo() -> None:
    CALLS.clear()
    phone3d.create_phone(**DIM, origin=(200.0, 50.0), layer_prefix="IP")
    p = [p for c, p in CALLS if c == "extrude_profile"][0]
    check("origen corre el contorno",
          min(q[0] for q in p["points"]) == 200.0
          and min(q[1] for q in p["points"]) == 50.0)
    check("prefijo de capa", p["layer"] == "IPCUERPO", p["layer"])


def _falla(nombre, **kw) -> None:
    CALLS.clear()
    try:
        phone3d.create_phone(**{**DIM, **kw})
    except ValueError:
        check(nombre, not CALLS, f"dibujó {len(CALLS)} comandos antes de fallar")
        return
    check(nombre, False, "no tiró ValueError")


def test_validaciones() -> None:
    _falla("radio de esquina imposible", corner_radius=50.0)
    _falla("edge_radius > mitad del espesor", edge_radius=5.0)
    _falla("pantalla sin depth", screen={"bezel": 2})
    _falla("bezel se come la pantalla", screen={"bezel": 40, "depth": 0.5})
    _falla("lentes sin plateau",
           lenses=[{"dx": 5, "dy": 5, "diameter": 4, "protrusion": 1}])
    _falla("lente fuera del plateau",
           plateau={"width": 20, "height": 20, "protrusion": 1,
                    "from_left": 2, "from_top": 2},
           lenses=[{"dx": 19, "dy": 5, "diameter": 6, "protrusion": 1}])
    _falla("botón fuera del lado",
           buttons=[{"side": "left", "from_start": 160, "length": 20,
                     "protrusion": 1}])
    _falla("acabado inexistente", finish="rosa")
    _falla("color de pieza inexistente", colors={"tapa": 3})


def test_falla_a_mitad_borra() -> None:
    CALLS.clear()
    orig = acad.call
    estado = {"n": 0}

    def rota(cmd, params=None, fallback=None):
        if cmd == "solid_boolean":
            raise RuntimeError("AutoCAD rechazó la resta")
        return orig(cmd, params, fallback)

    acad.call = rota  # type: ignore[assignment]
    try:
        phone3d.create_phone(**DIM, screen={"bezel": 2, "depth": 0.5})
        check("propaga el error", False)
    except RuntimeError:
        borrados = [p for c, p in CALLS if c == "delete_entities"]
        check("borra lo ya creado al fallar",
              len(borrados) == 1 and len(borrados[0]["handles"]) == 2,
              borrados)
    finally:
        acad.call = orig  # type: ignore[assignment]


if __name__ == "__main__":
    for nombre, fn in list(globals().items()):
        if nombre.startswith("test_") and callable(fn):
            print(nombre)
            fn()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" -", f)
        sys.exit(1)
    print("\nOK")
