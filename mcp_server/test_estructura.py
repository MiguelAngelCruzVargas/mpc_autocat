"""Tests de estructura.py (viga continua, trabes, losas) y alberca.py
(diseño). Contra cuentas a mano; NO necesita AutoCAD.

Uso:  python test_estructura.py
"""
from __future__ import annotations

import sys

import alberca
import estructura as es

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: object = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name + (f" -- {detalle}" if not ok else ""))


def test_viga_continua_contra_tablas() -> None:
    r = es.continuous_beam([5, 5], [1000, 1000])
    check("2 claros iguales: M apoyo = wL²/8", abs(r["support_moments_tm"][1] + 3.125) < 1e-3,
          r["support_moments_tm"])
    check("2 claros iguales: reacciones 3/8, 10/8, 3/8 wL",
          r["reactions_t"] == [1.875, 6.25, 1.875], r["reactions_t"])
    m = [s["M_pos_tm"] for s in r["spans"]]
    check("2 claros iguales: los dos positivos iguales (9/128 wL²)",
          abs(m[0] - m[1]) < 1e-3 and abs(m[0] - 1.758) < 2e-3, m)
    r = es.continuous_beam([6], [1000])
    check("simplemente apoyada: wL²/8", abs(r["spans"][0]["M_pos_tm"] - 4.5) < 1e-3)
    r = es.continuous_beam([4], [0], point_loads=[[(2, 1000)]])
    check("puntual al centro: PL/4", abs(r["spans"][0]["M_pos_tm"] - 1.0) < 1e-3)
    r = es.continuous_beam([5.6, 3.8, 2.6], [1500, 1500, 1500])
    check("equilibrio: suma de reacciones = carga total", abs(sum(r["reactions_t"]) - 18.0) < 1e-2,
          sum(r["reactions_t"]))


def test_reparto_de_tablero() -> None:
    p = es.panel_edge_loads(4.0, 4.0, 600)
    check("tablero cuadrado: triángulo w·a/3", abs(p["short"]["equiv_kg_m"] - 800) < 1e-6, p)
    p = es.panel_edge_loads(6.0, 3.0, 600)
    check("lados se ordenan solos", p["short"]["length"] == 3.0 and p["long"]["length"] == 6.0)


def test_trabe() -> None:
    d = es.design_beam(0.20, 0.45, 5.0, 6.0, 8.0, fc=250, span=5.6, condition="one_end")
    check("trabe cumple", d["ok"], d)
    check("acero inferior >= requerido", d["bottom"]["As_cm2"] >= d["bottom"]["As_req_cm2"], d["bottom"])
    check("estribos a s <= d/2", d["stirrups"]["spacing"] <= d["d"] / 2 + 1e-9, d["stirrups"])
    check("peralte mínimo L/18.5", abs(d["min_depth"]["h_min"] - 5.6 / 18.5) < 1e-3)
    try:
        es.design_beam(0.15, 0.25, 40.0, 40.0, 10.0, fc=250)
        check("sección que no da avisa", False, "no levantó ValueError")
    except ValueError:
        check("sección que no da avisa", True)


def test_losa_espesor_minimo() -> None:
    d12 = es.design_two_way_slab(4.6, 6.5, 670, 190, fc=250, h=0.12, continuous_edges=1)
    d15 = es.design_two_way_slab(4.6, 6.5, 670, 190, fc=250, h=0.15, continuous_edges=1)
    check("4.6x6.5 con 12 cm NO cumple el espesor mínimo", not d12["min_thickness"]["ok"])
    check("4.6x6.5 con 15 cm cumple", d15["ok"], d15)
    check("el claro corto lleva más acero", d15["short"]["As_req_cm2_m"] >= d15["long"]["As_req_cm2_m"])


def test_alberca() -> None:
    p = alberca.design_pool(8, 4, 1.2, 1.8, fc=250, soil_unit_weight=1.6)
    check("volumen 8x4x1.5 = 48 m³", abs(p["volume_m3"] - 48.0) < 1e-6, p["volume_m3"])
    check("recirculación 48/6 = 8 m³/h", abs(p["flow_m3_h"] - 8.0) < 1e-6)
    check("succión bajo 1.83 m/s", p["suction_pipe"]["velocity_m_s"] <= 1.83, p["suction_pipe"])
    check("dos drenes de fondo", p["main_drains"]["count"] == 2)
    check("muro cumple", p["ok"], p["checks"])
    try:
        alberca.design_pool(8, 4, 1.2, 1.8, fc=None)
        check("sin f'c rechaza", False)
    except ValueError:
        check("sin f'c rechaza", True)


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_") and callable(f):
            print(f"\n{nombre}")
            f()
    print(f"\n{'FALLARON ' + str(len(FAILED)) if FAILED else 'TODO OK'}")
    for f in FAILED:
        print("  -", f)
    sys.exit(1 if FAILED else 0)
