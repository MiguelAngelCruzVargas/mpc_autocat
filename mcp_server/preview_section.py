"""Corte de ejemplo, renderizado a SVG SIN AutoCAD.

Dibuja un corte de dos niveles (PB + PA) con puerta, ventana y losas
achuradas, más su fachada equivalente, para verificar visualmente que los
niveles caen a la cota correcta, el achurado se ve y la cadena de cotas de
piso no se encima con los rótulos de nivel — antes de ir a la máquina con
AutoCAD.

Uso:
  python preview_section.py [salida.svg]
"""
from __future__ import annotations

import sys

import preview

preview.install()

import sections  # noqa: E402  (después de install, para que use el mock)
import space     # noqa: E402


CASA = [
    {"name": "PB", "height": 2.90, "slab_thickness": 0.12, "elements": [
        {"type": "cut_wall", "x": 0.15, "thickness": 0.15},
        {"type": "cut_wall", "x": 6.30, "thickness": 0.15},
        {"type": "door", "x_start": 3.80, "x_end": 4.70, "head": 2.10},
        {"type": "seen_wall", "x_start": 0.15, "x_end": 6.30},
    ]},
    {"name": "PA", "height": 2.70, "slab_thickness": 0.12, "elements": [
        {"type": "cut_wall", "x": 0.15, "thickness": 0.15},
        {"type": "cut_wall", "x": 6.30, "thickness": 0.15},
        {"type": "window", "x_start": 1.20, "x_end": 2.60, "sill": 0.90, "head": 2.10},
    ]},
]


def main() -> int:
    space.set_scale(0.05)  # 1:50 en metros

    r = sections.create_building_section(0.0, 0.0, 6.45, CASA)
    print(f"corte: {len(r['levels'])} niveles, altura total {r['totalHeight']:.2f} m")
    for n in r["levels"]:
        print(f"  {n['name']}: cota {n['elevation']:+.2f}")
    if r.get("warning"):
        print("  AVISO:", r["warning"])

    # Fachada equivalente, corrida a la derecha para no encimarse en el SVG.
    space.clear()
    space.set_scale(0.05)
    sections.create_building_section(9.0, 0.0, 6.45, CASA, view="fachada",
                                     dimension_stories=False)

    out_path = sys.argv[1] if len(sys.argv) > 1 else "preview_section.svg"
    preview.save(out_path, preview.DRAWN)
    print(f"{len(preview.DRAWN)} entidades -> {out_path}")
    print("OK: corte y fachada dibujados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
