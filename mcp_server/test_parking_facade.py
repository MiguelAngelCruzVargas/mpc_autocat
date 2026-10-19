"""Tests de parking.py y facade.py (estacionamientos y fachadas con ornamento)
contra el socket mockeado. NO necesita AutoCAD.

Uso:  python test_parking_facade.py
"""
from __future__ import annotations

import math
import sys

import preview

preview.install()

import facade  # noqa: E402
import parking  # noqa: E402
import prim  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name + (f" -- {detalle}" if not ok else ""))


def cuantas(cmd: str) -> int:
    return sum(1 for d in preview.DRAWN if d["cmd"] == cmd)


def test_cajones() -> None:
    preview.DRAWN.clear()
    r = parking.parking_stalls(0, 0, 6, 278, 550, along="y", depth_sign=1,
                               start_number=1, car=False)
    check("6 cajones, numerados 1..6", r["numbers"] == [1, 2, 3, 4, 5, 6], r["numbers"])
    check("caja de la fila = 6 x 278 por 550", r["box"] == [0, 0, 550, 1668], r["box"])
    lineas = [(round(d["x1"]), round(d["y1"]), round(d["x2"]), round(d["y2"]))
              for d in preview.DRAWN if d["cmd"] == "create_line"]
    check("cada línea se dibuja una sola vez", len(lineas) == len(set(lineas)), len(lineas))
    check("fondo + frente + 7 separadores", len(lineas) == 9, len(lineas))
    preview.DRAWN.clear()
    r = parking.parking_stalls(0, 0, 4, 335, 550, along="x", depth_sign=-1,
                               start_number=34, number_step=-1)
    check("numeración al revés", r["numbers"] == [34, 33, 32, 31], r["numbers"])
    check("un coche por cajón (6 polilíneas cada uno)",
          cuantas("create_polyline") == 4 * 6, cuantas("create_polyline"))
    for mal in ({"count": 0}, {"along": "z"}, {"depth_sign": 2}):
        try:
            parking.parking_stalls(**{**dict(x=0, y=0, count=2, stall_width=250,
                                             stall_depth=500), **mal})
            check(f"rechaza {mal}", False)
        except ValueError:
            check(f"rechaza {mal}", True)


def test_coche_orientado() -> None:
    preview.DRAWN.clear()
    parking.car_symbol(0, 0, 400, 180, 0.0)
    xs = [p[0] for d in preview.DRAWN if d["cmd"] == "create_polyline" for p in d["points"]]
    check("coche a 0 grados: largo en X", abs((max(xs) - min(xs)) - 400) < 1, max(xs) - min(xs))
    preview.DRAWN.clear()
    parking.car_symbol(0, 0, 400, 180, 90.0)
    ys = [p[1] for d in preview.DRAWN if d["cmd"] == "create_polyline" for p in d["points"]]
    check("coche a 90 grados: largo en Y", abs((max(ys) - min(ys)) - 400) < 1, max(ys) - min(ys))


def test_perimetro_y_rampa() -> None:
    p = prim.Perimetro(0, 0, 100, 60, 15)
    a, b = p.punto(0.0)[0], p.punto(1.0)[0]
    check("el perímetro cierra", math.dist(a, b) < 1e-6)
    esperado = 2 * (70 + 30) + 2 * math.pi * 15
    check("largo = lados rectos + circunferencia", abs(p.largo - esperado) < 1e-6, p.largo)
    pts = [p.punto(k / 200)[0] for k in range(200)]
    check("todos los puntos sobre el contorno", all(
        -1e-6 <= q[0] <= 100 + 1e-6 and -1e-6 <= q[1] <= 60 + 1e-6 for q in pts))
    preview.DRAWN.clear()
    r = parking.ramp_track((0, 0, 400, 300, 120), (80, 80, 320, 220, 60), pitch=20)
    check("líneas radiales = perímetro / paso", r["radialLines"] == round(r["outerPerimeter"] / 20),
          r["radialLines"])
    try:
        parking.ramp_track((0, 0, 100, 100, 10), (50, 50, 200, 200, 10), 10)
        check("rechaza un interior que se sale", False)
    except ValueError:
        check("rechaza un interior que se sale", True)
    preview.DRAWN.clear()
    r = parking.ramp_arc((0, 0), 300, 500, 0, 90, pitch=25)
    check("abanico sobre el radio medio", r["radialLines"] == round(math.radians(90) * 400 / 25) + 1,
          r["radialLines"])


def test_fachada() -> None:
    preview.DRAWN.clear()
    r = facade.crenellation(0, 12.4, 10, 0.5, 0.3, 0.6)
    check("almenas: empieza y termina en merlón", r["merlons"] == round((12.4 - 0.5) / 0.8) + 1, r)
    pts = preview.DRAWN[-1]["points"]
    check("el contorno arranca y cierra en la base", pts[0][1] == 10 and pts[-1][1] == 10, pts[:2])
    check("almenas: el hueco real reparte parejo",
          abs((r["merlons"]) * 0.5 + (r["merlons"] - 1) * r["gapWidth"] - 12.4) < 1e-3)
    preview.DRAWN.clear()
    facade.arched_opening(0, 0, 3.0, 5.0, 1.5, cols=3, rows=2)
    poli = [d for d in preview.DRAWN if d["cmd"] == "create_polyline"]
    check("vano con arco: 2 marcos", len(poli) == 2, len(poli))
    bul = poli[0]["bulges"]
    check("el arco es un medio punto (bulge 1 hacia arriba)", abs(bul[2] - 1.0) < 1e-9, bul)
    ymax = max(p[1] for p in poli[0]["points"])
    check("el rectángulo llega a height - rise", abs(ymax - 3.5) < 1e-9, ymax)
    try:
        facade.arched_opening(0, 0, 3, 2, 2.5)
        check("rechaza un arco más alto que el vano", False)
    except ValueError:
        check("rechaza un arco más alto que el vano", True)
    preview.DRAWN.clear()
    r = facade.lattice_panel(0, 0, 3.4, 1.2, 0.3)
    ls = [d for d in preview.DRAWN if d["cmd"] == "create_line"]
    check("celosía: todas las diagonales dentro del panel", all(
        -1e-6 <= min(d["x1"], d["x2"]) and max(d["x1"], d["x2"]) <= 3.4 + 1e-6
        and -1e-6 <= min(d["y1"], d["y2"]) and max(d["y1"], d["y2"]) <= 1.2 + 1e-6 for d in ls))
    check("celosía: dos familias cruzadas", any((d["x2"] - d["x1"]) * (d["y2"] - d["y1"]) > 0 for d in ls)
          and any((d["x2"] - d["x1"]) * (d["y2"] - d["y1"]) < 0 for d in ls))
    preview.DRAWN.clear()
    r = facade.steps(0, 4, 0, 5, 0.17, 0.3)
    check("escalones: cada uno se retrae", r["steps"] == 5)
    r = facade.balustrade(0, 3, 4, 0.9, balusters=10)
    check("barandal con 10 balaustres", r["balusters"] == 10)


def test_ejes_letra_arriba() -> None:
    import arch
    preview.DRAWN.clear()
    arch.create_axis_grid(x_positions=[0, 5], y_positions=[0, 3, 7], y_labels="letters",
                          y_top_down=True)
    txt = [(d["y"], d["text"]) for d in preview.DRAWN if d["cmd"] == "create_text"
           and d["text"] in ("A", "B", "C")]
    por_y = sorted(set(txt))
    check("A arriba y C abajo con y_top_down", [t for _, t in por_y] == ["C", "B", "A"], por_y)


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_") and callable(fn):
            print(n)
            fn()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" -", f)
        sys.exit(1)
    print("\nOK")
