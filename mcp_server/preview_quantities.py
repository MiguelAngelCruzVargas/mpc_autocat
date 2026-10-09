"""Cuadro de volúmenes de obra renderizado a SVG SIN AutoCAD, con partidas,
totales y (a la derecha) la variante con columna de MEDICIÓN -- para juzgar
el cuadro como pieza de lámina antes de ir a la máquina.

Uso:
  python preview_quantities.py [salida.svg]
"""
from __future__ import annotations

import sys

import preview

preview.install()

import quantities  # noqa: E402
import space       # noqa: E402

AREAS = {"K1": 0.0225, "MURO": 7.2, "ZAP": 3.6, "LOSA": 12.5}
PERIM = {"EST": 0.36, "K1": 0.60}


def _fake(cmd, params=None):
    params = params or {}
    if cmd == "calculate_area":
        return {"area": AREAS[params["handle"]]}
    if cmd == "get_entity":
        return {"length": PERIM.get(params["handle"], 0.0)}
    return preview.fake_call(cmd, params)


def main() -> int:
    quantities.acad.call = _fake
    space.set_scale(0.1)   # 1:100 en metros
    r = quantities.calculate_quantities([
        {"type": "earthwork", "mode": "excavation", "group": "Preliminares",
         "label": "Excavación a mano en cepas, material tipo II", "handles": ["ZAP"],
         "depth": 0.80, "swell_pct": 25},
        {"type": "concrete_volume", "group": "Cimentación",
         "label": "Plantilla de concreto pobre f'c=100 kg/cm² e=5 cm",
         "handles": ["ZAP"], "depth": 0.05},
        {"type": "concrete_volume", "group": "Cimentación",
         "label": "Zapata corrida de concreto f'c=200 kg/cm²", "handles": ["ZAP"],
         "depth": 0.25, "waste_pct": 5},
        {"type": "earthwork", "mode": "backfill", "group": "Cimentación",
         "label": "Relleno compactado con material de banco", "handles": ["ZAP"],
         "depth": 0.80, "structure_volume": 1.08},
        {"type": "concrete_volume", "group": "Estructura",
         "label": "Castillos K-1 15x15 (12 pzas)", "handles": ["K1"] * 12,
         "depth": 2.50, "waste_pct": 5},
        {"type": "steel_weight", "group": "Estructura",
         "label": "Acero en castillos K-1: 4 vars. #3, est. #2 @ 15", "count": 12,
         "length": 2.5, "long_bars": 4, "long_bar_size": "#3",
         "stirrup_size": "#2", "stirrup_spacing": 0.15, "stirrup_handle": "EST",
         "waste_pct": 5},
        {"type": "formwork", "group": "Estructura",
         "label": "Cimbra en castillos K-1", "count": 12, "length": 2.5,
         "section_handle": "K1"},
        {"type": "brick_count", "group": "Albañilería",
         "label": "Muro de tabique rojo recocido 14 cm", "handles": ["MURO"]},
        {"type": "mortar_volume", "group": "Albañilería",
         "label": "Mortero cemento-arena 1:5 en juntas", "handles": ["MURO"],
         "thickness": 0.14},
        {"type": "area_finish", "group": "Acabados", "material": "aplanado",
         "label": "Aplanado fino en muros, mortero 1:5", "handles": ["MURO"],
         "coats": 1, "thickness": 0.015, "waste_pct": 5},
        {"type": "area_finish", "group": "Acabados", "material": "pintura",
         "label": "Pintura vinílica dos manos", "handles": ["MURO"], "coats": 2},
    ])
    t1 = quantities.create_quantities_table(0.0, 0.0, r)
    print("cuadro: %.2f x %.2f m, %d filas, aviso: %s"
          % (t1["width"], t1["height"], t1["rows"], t1.get("warning")))
    t2 = quantities.create_quantities_table(t1["right"] + 2.0, 0.0, r,
                                            show_calc=True)
    print("con medición: %.2f x %.2f m, aviso: %s"
          % (t2["width"], t2["height"], t2.get("warning")))

    out_path = sys.argv[1] if len(sys.argv) > 1 else "preview_quantities.svg"
    preview.save(out_path, preview.DRAWN, width_px=1800)
    print(f"{len(preview.DRAWN)} entidades -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
