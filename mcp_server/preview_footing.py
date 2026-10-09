"""Los dos cortes de cimentación de muro (piedra bola y zapata de concreto),
renderizados a SVG SIN AutoCAD, lado a lado -- el mismo par que muestra un
detalle de referencia real, para juzgar de un vistazo si la composición
(materiales, piedras, terreno, acero, rótulos, cotas) se lee como un plano
de obra antes de ir a la máquina con AutoCAD.

Uso:
  python preview_footing.py [salida.svg]
"""
from __future__ import annotations

import sys

import preview

preview.install()

import rebar   # noqa: E402  (después de install, para que use el mock)
import space   # noqa: E402


def main() -> int:
    space.set_scale(0.02)   # detalle a 1:20 en metros
    h = space.paper(2.5)    # texto de 2.5 mm de papel

    a = rebar.create_footing_section(
        x=0.0, y=0.0, foundation_type="piedra_bola",
        wall_thickness=0.15, footing_width=0.60, footing_thickness=0.60,
        lean_concrete_thickness=0.10, grade_beam_height=0.20,
        grade_beam_width=0.20, grade_beam_bars=4, beam_cover=0.025,
        wall_height=0.60,
        text_height=h, title="CIMENTACION CON PIEDRA BOLA", mark="A",
        specs={"plantilla": "f'c=100 kg/cm²",
               "stones": "JUNTEADA CON MORTERO CEMENTO-ARENA 1:5",
               "grade_beam": "20x20 4 VARS. #3 EST. #2 @ 20"})
    print("A) piedra bola: %d piedras, cobertura %s, avisos: %s"
          % (a["stoneCount"], a["footingArea_m2"], a["warnings"]))

    b = rebar.create_footing_section(
        x=3.2, y=0.0, foundation_type="zapata_concreto",
        wall_thickness=0.15, footing_width=1.00, footing_thickness=0.25,
        footing_edge_thickness=0.15, lean_concrete_thickness=0.05,
        pedestal_height=0.45, pedestal_width=0.30,
        grade_beam_height=0.20, grade_beam_width=0.20, grade_beam_bars=4,
        beam_cover=0.025, wall_height=0.60, dowel_count=2, stirrup_spacing=0.15,
        footing_bar_count=5, text_height=h,
        title="CIMENTACION ZAPATA DE CONCRETO", mark="B",
        specs={"plantilla": "f'c=100 kg/cm²",
               "footing": "f'c=200 kg/cm²",
               "bars": "VARS. #3 @ 20 A.S.",
               "dowels": "4 VARS. #3 EST. #2 @ 15"})
    print("B) zapata: acero transversal %.2f m, arranques %.2f m, avisos: %s"
          % (b["footingBarLength_m"], b["totalDowelLength_m"], b["warnings"]))

    out_path = sys.argv[1] if len(sys.argv) > 1 else "preview_footing.svg"
    preview.save(out_path, preview.DRAWN, width_px=1600)
    print(f"{len(preview.DRAWN)} entidades -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
