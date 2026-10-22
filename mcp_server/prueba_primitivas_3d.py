"""Prueba en vivo: create_object + primitivas 3D (CreateBox, CreateSphere, ...), Extrude desde
región y Slice con superficie. Dibujo NUEVO descartable. Una llamada nativa mal armada puede
tumbar AutoCAD: no usarlo con un plano en curso.
"""
from __future__ import annotations

import json
import math
import sys

import server as s

R: list[tuple[str, bool]] = []


def chk(n, ok, det=""):
    R.append((n, bool(ok)))
    print(("  ok   " if ok else " FALLA ") + n + (f"  [{det}]" if det and not ok else ""))


def intento(n, f):
    try:
        return f()
    except Exception as e:  # noqa: BLE001
        chk(n, False, str(e)[:220])
        return None


def vol(h):
    return s.get_object_properties([h], ["MassProperties"])["objects"][h]["properties"]["MassProperties"]["Volume"]


def main() -> int:
    s.new_document()
    print("== version:", s.ping())
    print("\n-- create_object en 2D")
    c = intento("create_object Circle con propiedades",
                lambda: s.create_object("Circle", {"Center": [5, 5, 0], "Radius": 2.5, "Layer": "0"}))
    chk("Circle creado con radio 2.5", c and abs(s.get_object_properties([c["handle"]], ["Radius"])["objects"][c["handle"]]["properties"]["Radius"] - 2.5) < 1e-9, c)
    ln = intento("create_object Line", lambda: s.create_object("Line", {"StartPoint": [0, 0, 0], "EndPoint": [3, 4, 0]}))
    chk("Line de largo 5", ln and abs(s.get_object_properties([ln["handle"]], ["Length"])["objects"][ln["handle"]]["properties"]["Length"] - 5) < 1e-9, ln)
    for nombre, args, extra in (("Clase inexistente", ("Foo",), None), ("Clase no entidad", ("LayerTableRecord",), None),
                                ("Viewport no creable", ("Viewport",), None)):
        try:
            s.create_object(*args)
            chk(f"create_object rechaza: {nombre}", False)
        except Exception:  # noqa: BLE001
            chk(f"create_object rechaza: {nombre}", True)
    try:
        s.create_object("Circle", {"Radius": "abc"})
        chk("create_object rechaza un valor inválido", False)
    except Exception:  # noqa: BLE001
        chk("create_object rechaza un valor inválido", True)
    n0 = s.list_entities(entity_type="Circle")["count"]
    try:
        s.create_object("Circle", {"Radius": 1, "Layer": "NO_EXISTE"})
    except Exception:  # noqa: BLE001
        pass
    chk("create_object atómico: la falla no deja nada", s.list_entities(entity_type="Circle")["count"] == n0)

    print("\n-- primitivas 3D de Solid3d")
    caja = intento("CreateBox", lambda: s.create_object("Solid3d", init_method="CreateBox", init_args=[10, 5, 3]))
    chk("caja 10x5x3 = 150", caja and abs(vol(caja["handle"]) - 150) < 1e-6, caja and vol(caja["handle"]))
    esf = intento("CreateSphere", lambda: s.create_object("Solid3d", init_method="CreateSphere", init_args=[2.0]))
    chk("esfera r=2 ~ 33.51", esf and abs(vol(esf["handle"]) - 4 / 3 * math.pi * 8) < 0.05, esf and vol(esf["handle"]))
    cun = intento("CreateWedge", lambda: s.create_object("Solid3d", init_method="CreateWedge", init_args=[10, 4, 6]))
    chk("cuña 10x4x6 = 120", cun and abs(vol(cun["handle"]) - 120) < 1e-6, cun and vol(cun["handle"]))
    tor = intento("CreateTorus", lambda: s.create_object("Solid3d", init_method="CreateTorus", init_args=[5.0, 1.0]))
    chk("toro R=5 r=1 ~ 2*pi^2*5*1", tor and abs(vol(tor["handle"]) - 2 * math.pi ** 2 * 5) < 0.5, tor and vol(tor["handle"]))
    n0 = s.list_entities(entity_type="Solid3d")["count"]
    try:
        s.create_object("Solid3d", init_method="CreateBox", init_args=["ancho", 5, 3])
        chk("un método con argumento inválido falla", False)
    except Exception:  # noqa: BLE001
        chk("un método con argumento inválido falla", True)
    chk("...y borra la entidad vacía", s.list_entities(entity_type="Solid3d")["count"] == n0)

    print("\n-- Extrude desde una región")
    P1 = s.create_polyline([[100, 0], [110, 0], [110, 10], [100, 10]], closed=True)["handle"]
    P2 = s.create_polyline([[105, 5], [115, 5], [115, 15], [105, 15]], closed=True)["handle"]
    rg = s.union_regions([P1, P2], delete_sources=True)["handle"]
    ex = intento("Extrude de la región", lambda: s.create_object("Solid3d", init_method="Extrude", init_args=[rg, 4.0, 0.0]))
    chk("región 175 m2 x 4 = 700", ex and abs(vol(ex["handle"]) - 700) < 1e-6, ex and vol(ex["handle"]))

    print("\n-- Slice con superficie")
    blq = s.extrude_profile([[200, 0], [210, 0], [210, 10], [200, 10]], 10)["handle"]
    pl = intento("PlaneSurface vacía", lambda: s.create_object("PlaneSurface"))
    if pl:
        print("   métodos de PlaneSurface:", sorted({m["name"] for m in s.list_object_methods("PlaneSurface")["methods"] if "Create" in m["name"] or "From" in m["name"]}))
    # una región grande en z=5 como superficie de corte
    cut = s.create_polyline([[190, -5], [220, -5], [220, 15], [190, 15]], closed=True)["handle"]
    cut2 = s.create_polyline([[191, -4], [219, -4], [219, 14], [191, 14]], closed=True)["handle"]
    rcut = s.union_regions([cut, cut2], delete_sources=True)["handle"]
    if pl:
        m = intento("PlaneSurface.CreateFromRegion", lambda: s.call_object_method(pl["handle"], "CreateFromRegion", [rcut]))
        s.set_object_properties([pl["handle"]], {})  if False else None
        # subir la superficie a z=5 con una matriz
        intento("mover la superficie a z=5", lambda: s.call_object_method(
            pl["handle"], "TransformBy", [[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 5], [0, 0, 0, 1]]]))
        sl = intento("Slice con la superficie (mitad negativa agregada)", lambda: s.call_object_method(
            blq, "Slice", [pl["handle"], True], add_results_to_space=True))
        chk("Slice con superficie: crea la otra mitad", sl and sl.get("created"), sl)
        chk("el original queda en 500", abs(vol(blq) - 500) < 1e-6, vol(blq))

    n = sum(1 for _, ok in R if ok)
    print(f"\nRESULTADO: {n}/{len(R)} OK  (plugin {s.ping().get('pluginVersion')})")
    fallan = [x for x, ok in R if not ok]
    if fallan:
        print("FALLAN:", fallan)
    try:
        s.close_document(discard_unsaved=True)
    except Exception:  # noqa: BLE001
        pass
    return 0 if not fallan else 1


if __name__ == "__main__":
    sys.exit(main())
