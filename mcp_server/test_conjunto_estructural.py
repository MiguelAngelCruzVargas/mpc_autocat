"""Tests de conjunto_estructural.py (diseño completo de una planta de marcos)
y detalles_estructura.py (detalle de dintel) con el socket mockeado. NO
necesita AutoCAD.

Uso:  python test_conjunto_estructural.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import conjunto_estructural as ce  # noqa: E402
import detalles_estructura as de  # noqa: E402
import estructura as es  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name + (f" -- {detalle}" if not ok else ""))


def test_diseno_completo() -> None:
    d = ce.design_frame_structure([0, 5, 10, 15], [0, 4, 8], 300, 190, 250, 15, 1.2, soil_unit_weight=1.6,
                                  openings=[[6, 1, 8.5, 3]])
    check("losa cumple y el espesor se eligió iterando", d["slab"]["ok"] and d["slab_h"] >= 0.10, d["slab_h"])
    check("7 trabes (3 en X + 4 en Y) con marcas únicas", len(d["beams"]) == 7
          and len({b["mark"] for b in d["beams"]}) == 7)
    check("la trabe cumple con la sección elegida", d["beam_design"]["ok"] and d["beam_h"] >= 0.40, d["beam_h"])
    check("12 columnas, 6 tableros numerados", len(d["columns"]) == 12 and [p["mark"] for p in d["panels"]] == [str(i) for i in range(1, 7)])
    check("zapata diseñada y OK", d["footing"]["ok"] and d["footing"]["B"] > 1.0)
    check("las decisiones quedan explicadas", len(d["decisions"]) >= 3 and all("Losa" in x or "Trabe" in x or "Zapata" in x
                                                                               for x in d["decisions"]))
    check("cada trabe trae sus cargas y su análisis", all("loads_kg_m" in b and "analysis" in b for b in d["beams"]))
    rmax = max(c["reaction_t"] for c in d["columns"])
    check("la reacción mayor está en una columna interior", rmax > 10 and
          any(c["reaction_t"] == rmax and 0 < c["x"] < 15 for c in d["columns"]), rmax)
    for kw in ({"allowable_bearing": 0}, {"depth": 0}, {"fc": 0}):
        try:
            ce.design_frame_structure([0, 5], [0, 4], 300, 190, **{**dict(fc=250, allowable_bearing=15, depth=1.2), **kw})
            check(f"sin dato de proyecto rechaza {kw}", False)
        except ValueError:
            check(f"sin dato de proyecto rechaza {kw}", True)


def test_dibujo_del_juego() -> None:
    d = ce.design_frame_structure([0, 5, 10], [0, 4, 8], 300, 190, 250, 15, 1.2, soil_unit_weight=1.6)
    preview.DRAWN.clear()
    r = ce.draw_structural_set(d, upm=0.075, layout=None)
    b1, b2 = r["framing"]["box"], r["foundation"]["box"]
    check("la cimentación arranca a la derecha de la planta (no se pisan)", b2[0] >= b1[2] - 1e-6, (b1, b2))
    textos = [x["text"] for x in preview.DRAWN if x["cmd"] == "create_text"]
    check("marcas de trabe, zapata, contratrabe y columna dibujadas",
          any(t.startswith("T-") for t in textos) and "Z-1" in textos
          and any(t.startswith("CT-") for t in textos) and "C-1" in textos)
    check("cuadro de trabes y notas en la lámina", "CUADRO DE TRABES" in textos and "NOTAS:" in textos)
    check("con layout=None no se dibuja título de layout",
          sum(1 for t in textos if "PLANTA" in t) >= 2)


def test_detalle_dintel() -> None:
    din = es.design_lintel(1.20, 0.20, 0.15, 1.2, fc=250, h=0.20)
    preview.DRAWN.clear()
    r = de.draw_lintel_detail(din, 10, 20, 0.01)
    textos = [x["text"] for x in preview.DRAWN if x["cmd"] == "create_text"]
    check("rotula el acero y los estribos", any("INF." in t for t in textos) and any("E#" in t for t in textos), textos[:6])
    check("rotula el apoyo", any("APOYO" in t for t in textos))
    check("dos apoyos achurados (más el concreto del corte)",
          sum(1 for x in preview.DRAWN if x["cmd"] == "create_hatch" and x.get("layer") == de.L_ACH) == 2,
          [(x.get("layer"), x.get("pattern")) for x in preview.DRAWN if x["cmd"] == "create_hatch"])
    check("la caja cubre elevación y corte", r["box"][2] - r["box"][0] > 1.6 + 0.4, r["box"])
    try:
        de.draw_lintel_detail(din, 0, 0, 0)
        check("sin escala rechaza", False)
    except ValueError:
        check("sin escala rechaza", True)


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
