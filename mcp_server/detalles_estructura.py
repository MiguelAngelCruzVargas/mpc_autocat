"""Detalles estructurales de oficio que se arman solos desde un diseño.

  draw_lintel_detail   el dintel de design_lintel: elevación con varillas y
                       estribos, los dos apoyos de muro achurados, cotas, el
                       corte con su armado y los rótulos de acero. Devuelve
                       la caja para ponerlo a 1:10 en su viewport.

Todo sale del dict de diseño: ningún número se escribe a mano, y por eso el
detalle es igual lo llame quien lo llame.
"""
from __future__ import annotations

from typing import Any, Optional

import annotation as ann
import autocad_client as acad
import materials
import prim
import rebar
import symbols as sym_mod

L_MURO = "MUROS"
L_ACH = "ACHURADOS"
L_TXT = "EST-TEXTOS"


def draw_lintel_detail(design: dict[str, Any], x: float, y: float, upm: float,
                       mark: str = "D-1", title: bool = True) -> dict[str, Any]:
    """(x, y) = esquina inferior izquierda del dintel (cara inferior, sobre el
    apoyo izquierdo). upm = unidades por mm de papel de la vista (0.01 = 1:10)."""
    if upm <= 0:
        raise ValueError("upm tiene que ser > 0 (0.01 para 1:10, 0.02 para 1:20).")
    b = float(design["section"]["b"])
    h = float(design["section"]["h"])
    ap = float(design["bearing"])
    L = float(design["clear_span"]) + 2 * ap
    s_e = float(design["stirrups"]["spacing"])
    db = rebar_bar_diameter(design["bottom"]["bar"])
    de = rebar_bar_diameter(design["stirrups"]["bar"])
    th = 2.0 * upm
    prim.capa(L_MURO, 7, 35)
    prim.capa(L_ACH, 8, 5)
    prim.capa(L_TXT, 7, 0)
    hs: list[str] = []
    with acad.lote():
        elev = rebar.create_rebar_elevation(x=x, y=y, width=L, height=h, stirrup_spacing=s_e,
                                            bars_interior=max(0, design["bottom"]["count"] - 2),
                                            bar_diameter=db, stirrup_diameter=de, cover=0.025,
                                            depth=b, orientation="horizontal")
        # Apoyos de muro (0.60 de alto) achurados.
        alto_muro = max(0.60, 3 * h)
        esc_h = materials.hatch_scale("ANSI31", paper_mm=2.0, scale=upm)
        for xa in (x, x + L - ap):
            hm = prim.poly([(xa, y - alto_muro), (xa + ap, y - alto_muro), (xa + ap, y), (xa, y)],
                           L_MURO, True, 35)
            acad.call("create_hatch", {"boundaryHandle": hm, "pattern": "ANSI31", "scale": esc_h,
                                       "angleDeg": 0.0, "layer": L_ACH, "lineweight": 5,
                                       "colorIndex": 8, "islandHandles": None})
            hs.append(hm)
    # Cotas: apoyos y claro abajo; peralte a la izquierda.
    ann.create_dimension_chain(positions=[x, x + ap, x + L - ap, x + L], side="bottom",
                               reference=y - alto_muro, scale=upm)
    ann.create_dimension_chain(positions=[y, y + h], side="left", reference=x, scale=upm)
    # Corte, a la derecha, con su armado real.
    xs = x + L + 40 * upm
    sec = rebar.create_column_section(x=xs, y=y, width=b, depth=h,
                                      bars_top_bottom=max(0, design["bottom"]["count"] - 2),
                                      bar_diameter=db, cover=0.025, stirrup_diameter=de)
    ann.create_dimension_chain(positions=[xs, xs + b], side="bottom", reference=y, scale=upm)
    ann.create_dimension_chain(positions=[y, y + h], side="right", reference=xs + b, scale=upm)
    etiquetas = [
        {"text": f"{design['bottom']['text']} INF. + {design['top']['text']} SUP.",
         "x": x + ap, "y": y + h + 4.5 * th},
        {"text": f"{design['stirrups']['text']} cm" + ("" if design["stirrups"].get("required", True)
                                                      else " (CONSTRUCTIVOS)"),
         "x": x + ap, "y": y + h + 2.5 * th},
        {"text": f"APOYO {ap * 100:.0f} cm C/LADO", "x": x + L + 1.0 * th, "y": y - alto_muro / 2},
        {"text": f"CORTE {b * 100:.0f} x {h * 100:.0f}", "x": xs, "y": y + h + 2.5 * th},
    ]
    ann.place_labels(etiquetas, height=th, layer=L_TXT)
    box = [x - 14 * upm, y - alto_muro - 22 * upm, xs + b + 16 * upm, y + h + 8 * th]
    if title:
        # Altura del título a la escala DEL DETALLE (5 mm de papel): con la
        # escala registrada de la lámina (1:75) el título de un detalle 1:10
        # salía 7 veces más grande que el detalle y su caja no entraba en el papel.
        t = sym_mod.create_view_title(title=f"DETALLE DE DINTEL {mark}", scale_text=f"ESC. 1:{round(1000 * upm)}",
                                      spaced=False, figure_box=box, height=5.0 * upm)
        box = [min(box[0], t["box"][0]), min(box[1], t["box"][1]), max(box[2], t["box"][2]), box[3]]
    return {"box": box, "elevation": elev, "section": sec, "mark": mark,
            "model": design["load_model"], "ok": design["ok"]}


def rebar_bar_diameter(nombre: str) -> float:
    import zapatas as zap
    return zap.VARILLAS[nombre][0]
