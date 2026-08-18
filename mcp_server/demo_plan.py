"""Dibuja un plano completo EN AUTOCAD (necesita el plugin cargado).

Mismo contenido que preview_plan.py, pero contra el dibujo abierto de verdad:
sirve para verificar de punta a punta que el pipeline funciona y que el plano
sale como lo muestra el preview.

Uso:
  1. AutoCAD abierto con un dibujo NUEVO (esto dibuja sobre el activo).
  2. NETLOAD del DLL que corresponda a la versión.
  3. python demo_plan.py
"""
from __future__ import annotations

import sys

import arch
import autocad_client as acad
import sheet


def main() -> int:
    info = acad.call("get_drawing_info")
    print(f"dibujo activo: {info['fileName']} ({info['entityCount']} entidades)")

    # Los grosores tienen que estar visibles o se ve todo a 1 pixel.
    acad.call("set_display_options", {"lineweightDisplay": True})

    lamina = sheet.create_sheet(
        sheet_format="A2",
        scale_denominator=50.0,
        model_units="m",
        project="CASA HABITACIÓN DE INTERÉS SOCIAL",
        location="AV. REFORMA 123, COL. CENTRO, OAXACA DE JUÁREZ, OAX.",
        client="MIGUEL ÁNGEL CRUZ VARGAS",
        content="PLANTA ARQUITECTÓNICA",
        drawn_by="M. A. CRUZ",
        reviewed_by="ARQ. RESPONSABLE",
        date="18/08/2026",
        sheet_number="A-01",
    )
    area = lamina["drawArea"]
    print(f"lamina {lamina['format']} {lamina['scale']} -> area util "
          f"{area['x2'] - area['x1']:.2f} x {area['y2'] - area['y1']:.2f}")

    house_w, house_h = 9.0, 7.0
    ox = area["x1"] + ((area["x2"] - area["x1"]) - house_w) / 2.0
    oy = area["y1"] + ((area["y2"] - area["y1"]) - house_h) / 2.0

    walls = arch.create_walls(
        points=[[ox, oy], [ox + house_w, oy],
                [ox + house_w, oy + house_h], [ox, oy + house_h]],
        thickness=0.15,
        closed=True,
        openings=[
            {"distance": 2.0, "width": 0.90, "type": "door",
             "swing": "left", "side": "left"},
            {"distance": 5.5, "width": 1.50, "type": "window"},
            {"distance": 12.0, "width": 1.20, "type": "window"},
            {"distance": 20.5, "width": 1.50, "type": "window"},
            {"distance": 29.0, "width": 1.20, "type": "window"},
        ],
    )
    print(f"muro perimetral: {len(walls['wallHandles'])} tramos, "
          f"{len(walls['openings'])} huecos")

    divider = arch.create_walls(
        points=[[ox + 5.0, oy], [ox + 5.0, oy + house_h]],
        thickness=0.10,
        openings=[{"distance": 4.5, "width": 0.80, "type": "door",
                   "swing": "right", "side": "right"}],
    )
    print(f"muro divisorio: {len(divider['wallHandles'])} tramos")

    grid = arch.create_axis_grid(
        x_positions=[ox, ox + 5.0, ox + house_w],
        y_positions=[oy, oy + house_h],
    )
    print(f"ejes: {grid['verticalAxes']} x {grid['horizontalAxes']}")

    # Una cota, para ver que el texto queda a escala.
    acad.call("create_dimension", {
        "x1": ox, "y1": oy - 1.5, "x2": ox + house_w, "y2": oy - 1.5,
        "dimLineX": ox + house_w / 2.0, "dimLineY": oy - 1.5,
        "layer": "COTAS", "scale": 0.05,
        "lineweight": 13, "colorIndex": None,
    })

    acad.call("zoom_extents")
    final = acad.call("get_drawing_info")
    print(f"listo: {final['entityCount']} entidades en el dibujo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
