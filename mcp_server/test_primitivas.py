"""Tests de primitivas.py y de create_rectangle / create_polygon / create_ellipse / create_construction_line /
create_point contra el socket mockeado. NO necesita AutoCAD.

Uso:  python test_primitivas.py
"""
from __future__ import annotations

import math

import primitivas as prim
import server

FAILED: list[str] = []


def check(name: str, got, expected, tol: float | None = None) -> None:
    ok = (abs(got - expected) <= tol) if tol is not None else got == expected
    if not ok:
        FAILED.append(f"{name}: esperaba {expected!r}, obtuve {got!r}")
    print(("  ok  " if ok else " FALLA ") + name)


def area(pts: list[list[float]]) -> float:
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))) / 2


def con_plugin(fn):
    llamadas: list[tuple[str, dict]] = []

    def fake(cmd, params=None):
        llamadas.append((cmd, params or {}))
        return {"handle": "AB", "ok": True}

    real = server.acad.call
    server.acad.call = fake
    try:
        return fn(), llamadas
    finally:
        server.acad.call = real


def rechaza(nombre, fn):
    try:
        fn()
    except prim.PrimitivaError:
        print("  ok  " + nombre)
        return
    FAILED.append(f"{nombre}: no se rechazó")
    print(" FALLA " + nombre)


def main() -> int:
    # ---- rectángulo
    r = prim.rectangulo(0, 0, 4, 3)
    check("rectángulo 4x3 tiene área 12", area(r["points"]), 12.0, 1e-9)
    check("rectángulo sin esquinas redondeadas no lleva bulges", r["bulges"], None)
    r = prim.rectangulo(4, 3, 0, 0)
    check("esquinas en cualquier orden", sorted(map(tuple, r["points"])), [(0.0, 0.0), (0.0, 3.0), (4.0, 0.0), (4.0, 3.0)])
    r = prim.rectangulo(0, 0, 10, 6, 1)
    check("redondeado: 8 vértices y 8 bulges", (len(r["points"]), len(r["bulges"])), (8, 8))
    check("redondeado: bulge de 90 grados", r["bulges"][1], math.tan(math.pi / 8), 1e-12)
    rechaza("rectángulo sin área", lambda: prim.rectangulo(0, 0, 0, 5))
    rechaza("radio que no entra", lambda: prim.rectangulo(0, 0, 10, 6, 3))
    rechaza("radio negativo", lambda: prim.rectangulo(0, 0, 10, 6, -1))
    rechaza("coordenada NaN", lambda: prim.rectangulo(0, 0, float("nan"), 6))

    # ---- polígono
    g = prim.poligono(6, 0, 0, 2)
    check("hexágono inscrito: 6 vértices a distancia 2", all(abs(math.hypot(x, y) - 2) < 1e-9 for x, y in g["points"]) and len(g["points"]) == 6, True)
    g = prim.poligono(4, 0, 0, 1, circunscrito=True)
    check("cuadrado circunscrito de apotema 1 es de lado 2 (área 4)", area(g["points"]), 4.0, 1e-9)
    g = prim.poligono(3, 5, 5, 1, rotacion_deg=90)
    check("rotación: primer vértice hacia +Y", (round(g["points"][0][0], 9), round(g["points"][0][1], 9)), (5.0, 6.0))
    rechaza("polígono de 2 lados", lambda: prim.poligono(2, 0, 0, 1))
    rechaza("polígono de lados no entero", lambda: prim.poligono(3.5, 0, 0, 1))
    rechaza("polígono radio 0", lambda: prim.poligono(5, 0, 0, 0))

    # ---- elipse, líneas, punto
    e = prim.elipse(1, 2, 3, 0, 0.5)
    check("elipse: Ellipse.Set con 6 argumentos", (e["entity_type"], e["init_method"], len(e["init_args"])), ("Ellipse", "Set", 6))
    rechaza("elipse con relación 0", lambda: prim.elipse(0, 0, 3, 0, 0))
    rechaza("elipse con relación mayor que 1", lambda: prim.elipse(0, 0, 3, 0, 1.5))
    rechaza("elipse con eje mayor nulo", lambda: prim.elipse(0, 0, 0, 0, 0.5))
    rechaza("elipse con fin <= inicio", lambda: prim.elipse(0, 0, 3, 0, 0.5, 2.0, 1.0))
    x = prim.linea_infinita("Xline", 1, 1, 0, 2)
    check("xline: BasePoint y SecondPoint", x["properties"], {"BasePoint": [1.0, 1.0, 0.0], "SecondPoint": [1.0, 3.0, 0.0]})
    rechaza("línea infinita sin dirección", lambda: prim.linea_infinita("Ray", 0, 0, 0, 0))
    check("punto", prim.punto(1, 2)["properties"], {"Position": [1.0, 2.0, 0.0]})
    check("capa se agrega a las propiedades", prim.con_capa(prim.punto(1, 2), "VEG")["properties"]["Layer"], "VEG")
    rechaza("capa vacía", lambda: prim.con_capa(prim.punto(1, 2), " "))

    # ---- las tools mandan lo correcto al plugin
    r, ll = con_plugin(lambda: server.create_rectangle(0, 0, 5, 3, layer="MUROS", lineweight=50))
    check("create_rectangle -> create_polyline cerrada", (ll[0][0], ll[0][1]["closed"], len(ll[0][1]["points"])), ("create_polyline", True, 4))
    check("create_rectangle respeta capa y grosor", (ll[0][1]["layer"], ll[0][1].get("lineweight")), ("MUROS", 50))
    r, ll = con_plugin(lambda: server.create_rectangle(0, 0, 0, 3))
    check("create_rectangle inválido se rechaza sin tocar AutoCAD", (r.get("ok"), ll), (False, []))
    r, ll = con_plugin(lambda: server.create_polygon(5, 0, 0, 2))
    check("create_polygon -> 5 vértices y vertexRadius", (len(ll[0][1]["points"]), r.get("vertexRadius")), (5, 2.0))
    r, ll = con_plugin(lambda: server.create_ellipse(0, 0, 4, 0, 0.5, layer="EJES"))
    check("create_ellipse -> create_object Ellipse", (ll[0][0], "Ellipse" in str(ll[0][1])), ("create_object", True))
    r, ll = con_plugin(lambda: server.create_construction_line(0, 0, 1, 1))
    check("create_construction_line por defecto es Xline", "Xline" in str(ll[0][1]), True)
    r, ll = con_plugin(lambda: server.create_construction_line(0, 0, 1, 1, infinite_both_ways=False))
    check("sin ser infinita en ambos sentidos es Ray", "Ray" in str(ll[0][1]), True)
    r, ll = con_plugin(lambda: server.create_point(1, 2, layer="PUNTOS"))
    check("create_point -> create_object DBPoint", "DBPoint" in str(ll[0][1]) or "Position" in str(ll[0][1]), True)
    r, ll = con_plugin(lambda: server.create_ellipse(0, 0, 4, 0, 2))
    check("create_ellipse inválido no toca AutoCAD", (r.get("ok"), ll), (False, []))

    if FAILED:
        print("\nFALLARON:")
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
