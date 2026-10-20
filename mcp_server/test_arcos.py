"""Tests de arcos.py (trazo y revisión de arcos de mampostería) contra el
socket mockeado. NO necesita AutoCAD.

Uso:  python test_arcos.py
"""
from __future__ import annotations

import math
import sys

import preview

preview.install()

import arcos  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name + (f" -- {detalle}" if not ok else ""))


def _cierra(g: dict, L: float, f: float) -> bool:
    ip = g["intrados"]["points"]
    return (abs(ip[0][0]) < 1e-6 and abs(ip[0][1]) < 1e-6
            and abs(ip[-1][0] - L) < 1e-6 and abs(ip[-1][1]) < 1e-6
            and abs(g["crown"][1] - f) < 1e-6)


def _pasa_por_clave(g: dict, L: float, f: float) -> bool:
    """Algún arco del trazo pasa por la clave (L/2, f)."""
    for (cx, cy), R in zip(g["centers"], g["radii"]):
        if abs(math.hypot(L / 2 - cx, f - cy) - R) < 2e-3:   # centros redondeados a mm
            return True
    return False


def test_medio_punto() -> None:
    g = arcos.arch_geometry(2.4, None, "medio_punto", thickness=0.14, voussoirs=9)
    check("arranques en (0,0) y (L,0), clave en (L/2, L/2)", _cierra(g, 2.4, 1.2))
    check("un centro en (L/2, 0), radio L/2", g["centers"] == [[1.2, 0.0]] and g["radii"] == [1.2])
    check("largo del intradós = pi·R", abs(g["intrados"]["length"] - math.pi * 1.2) < 1e-3)
    check("extradós a +t", abs(g["extrados"]["points"][0][0] - (-0.14)) < 1e-6)
    check("9 dovelas: 8 juntas y clave en el medio",
          len(g["voussoirs"]["joints"]) == 8 and g["voussoirs"]["keystone_index"] == 4)
    g2 = arcos.arch_geometry(2.4, 0.9, "medio_punto")
    check("rise distinto en medio punto se avisa", g2["warnings"] and g2["rise"] == 1.2)


def test_rebajado_apuntado_carpanel() -> None:
    g = arcos.arch_geometry(2.4, 0.6, "rebajado")
    R = (2.4 ** 2 / 4 + 0.6 ** 2) / (2 * 0.6)
    check("rebajado: radio (L²/4+f²)/2f y centro bajo los arranques",
          abs(g["radii"][0] - R) < 1e-6 and g["centers"][0][1] < 0 and _cierra(g, 2.4, 0.6))
    g = arcos.arch_geometry(2.4, 1.6, "apuntado")
    check("apuntado: dos centros simétricos sobre los arranques",
          len(g["centers"]) == 2 and abs(g["centers"][0][0] + g["centers"][1][0] - 2.4) < 1e-6
          and all(abs(c[1]) < 1e-9 for c in g["centers"]))
    check("apuntado: ambos arcos pasan por la clave y cierran", _pasa_por_clave(g, 2.4, 1.6) and _cierra(g, 2.4, 1.6))
    g = arcos.arch_geometry(2.4, 0.8, "carpanel")
    check("carpanel: tres centros, el central más bajo", len(g["centers"]) == 3 and g["centers"][1][1] < 0)
    check("carpanel: cierra y el central pasa por la clave", _cierra(g, 2.4, 0.8) and _pasa_por_clave(g, 2.4, 0.8))
    # tangencia: el punto de unión equidista de ambos centros según sus radios
    (c1, R1), (c2, R2) = (g["centers"][0], g["radii"][0]), (g["centers"][1], g["radii"][1])
    check("carpanel: arcos laterales tangentes al central (R-r = distancia entre centros)",
          abs(math.dist(c1, c2) - (R2 - R1)) < 1e-3)
    for kw in ({"rise": 1.2, "kind": "rebajado"}, {"rise": 0.9, "kind": "apuntado"},
               {"rise": None, "kind": "carpanel"}, {"rise": 0.5, "kind": "ojival"}):
        try:
            arcos.arch_geometry(2.4, kw["rise"], kw["kind"])
            check(f"rechaza {kw}", False, "no tiró")
        except ValueError:
            check(f"rechaza {kw}", True)
    try:
        arcos.arch_geometry(2.4, None, "medio_punto", voussoirs=8)
        check("dovelas pares se rechazan (sin clave centrada)", False)
    except ValueError:
        check("dovelas pares se rechazan (sin clave centrada)", True)


def test_dibujo() -> None:
    preview.DRAWN.clear()
    r = arcos.create_arch(10, 5, 2.4, None, "medio_punto", thickness=0.14, voussoirs=5)
    pl = [d for d in preview.DRAWN if d["cmd"] == "create_polyline"]
    ln = [d for d in preview.DRAWN if d["cmd"] == "create_line"]
    check("dibuja intradós y extradós", len(pl) == 2)
    check("cierres de arranque + 4 juntas", len(ln) == 2 + 4, len(ln))
    check("el arco está desplazado al origen pedido", pl[0]["points"][0] == [10.0, 5.0], pl[0]["points"][0])
    check("bulges negativos (recorrido horario de izq. a der.)", pl[0]["bulges"][0] < 0)


def test_revision() -> None:
    c = arcos.check_masonry_arch(2.4, 0.6, 0.14, 0.15, 800, fm_kgcm2=40, kind="rebajado")
    w = 800 + 1800 * 0.14 * 0.15
    check("empuje H = wL²/8f", abs(c["thrust_H_kg"] - w * 2.4 ** 2 / (8 * 0.6)) < 0.5, c["thrust_H_kg"])
    check("reacción V = wL/2", abs(c["reaction_V_kg"] - w * 1.2) < 0.5)
    check("t requerido = 6·e_max", abs(c["t_required_m"] - 6 * c["e_max_m"]) < 1e-3)
    check("tercio central falla con t=14 y lo dice", not c["middle_third"]["ok"] and not c["ok"])
    c2 = arcos.check_masonry_arch(2.4, 0.6, 0.30, 0.15, 800, fm_kgcm2=40, kind="rebajado")
    check("con t=30 la línea entra en el tercio central", c2["middle_third"]["ok"], c2["e_max_m"])
    c3 = arcos.check_masonry_arch(2.4, 1.2, 0.14, 0.15, 800)
    check("sin f'm no revisa esfuerzo y lo dice", c3["stress"]["ok"] is None)
    # un arco parabólico perfecto tendría e = 0: el medio punto bajo carga uniforme no
    check("medio punto: la parábola se separa del semicírculo", c3["e_max_m"] > 0.01)
    try:
        arcos.check_masonry_arch(2.4, 0.6, 0.14, 0.15, -5)
        check("carga negativa se rechaza", False)
    except ValueError:
        check("carga negativa se rechaza", True)


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
