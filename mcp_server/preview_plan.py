"""Plano completo de ejemplo, renderizado a SVG SIN AutoCAD.

Dibuja lo que produciría una sesión típica: cajón + rótulo, muros con espesor y
huecos, puertas y ventanas, y ejes estructurales. Sirve para verificar que las
piezas encajan (que los muros cierren en las esquinas, que los huecos caigan
donde deben, que todo entre en la hoja) antes de ir a la máquina con AutoCAD.

Uso:
  python preview_plan.py [salida.svg]
"""
from __future__ import annotations

import sys

import preview

preview.install()

import arch      # noqa: E402  (después de install, para que use el mock)
import sheet     # noqa: E402


def main() -> int:
    # --- 1. La lámina, siempre primero ---
    info = sheet.create_sheet(
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
    area = info["drawArea"]
    print(f"lamina {info['format']} {info['scale']} ({info['modelUnits']})")
    print(f"  area util: {area['x2'] - area['x1']:.2f} x "
          f"{area['y2'] - area['y1']:.2f} unidades")

    # --- 2. Ubicar la casa dentro del área útil ---
    house_w, house_h = 9.0, 7.0
    ox = area["x1"] + ((area["x2"] - area["x1"]) - house_w) / 2.0
    oy = area["y1"] + ((area["y2"] - area["y1"]) - house_h) / 2.0
    print(f"  casa de {house_w}x{house_h} en ({ox:.2f}, {oy:.2f})")

    # --- 3. Muro perimetral, recorrido antihorario, con huecos ---
    # El eje arranca abajo a la izquierda: 0..9 el frente, 9..16 el lateral
    # derecho, 16..25 el fondo, 25..32 el lateral izquierdo.
    perimeter = [
        (ox, oy),
        (ox + house_w, oy),
        (ox + house_w, oy + house_h),
        (ox, oy + house_h),
    ]
    walls = arch.create_walls(
        points=[[p[0], p[1]] for p in perimeter],
        thickness=0.15,
        closed=True,
        openings=[
            {"distance": 2.0, "width": 0.90, "type": "door",
             "swing": "left", "side": "left"},            # entrada, al frente
            {"distance": 5.5, "width": 1.50, "type": "window"},   # frente
            {"distance": 12.0, "width": 1.20, "type": "window"},  # lateral der.
            {"distance": 20.5, "width": 1.50, "type": "window"},  # fondo
            {"distance": 29.0, "width": 1.20, "type": "window"},  # lateral izq.
        ],
    )
    print(f"  muro perimetral: {len(walls['wallHandles'])} tramos, "
          f"{len(walls['openings'])} huecos, eje de "
          f"{walls['axisLength']:.2f} de largo")

    # --- 4. Un muro interior que divide, con su puerta ---
    divider = arch.create_walls(
        points=[[ox + 5.0, oy], [ox + 5.0, oy + house_h]],
        thickness=0.10,
        openings=[{"distance": 4.5, "width": 0.80, "type": "door",
                   "swing": "right", "side": "right"}],
    )
    print(f"  muro divisorio: {len(divider['wallHandles'])} tramos")

    # --- 5. Ejes estructurales sobre los muros portantes ---
    grid = arch.create_axis_grid(
        x_positions=[ox, ox + 5.0, ox + house_w],
        y_positions=[oy, oy + house_h],
    )
    print(f"  ejes: {grid['verticalAxes']} x {grid['horizontalAxes']}")

    # --- 6. Guardar y verificar ---
    w, h = info["sheetSizeModel"]
    out_path = sys.argv[1] if len(sys.argv) > 1 else "preview_plan.svg"
    preview.save(out_path, preview.DRAWN, reference_span=max(w, h))
    print(f"{len(preview.DRAWN)} entidades -> {out_path}")

    fuera = preview.check_inside(preview.DRAWN, w, h)
    if fuera:
        print(f"AVISO: {len(fuera)} puntos fuera de la hoja, p.ej. {fuera[:3]}")
        return 1
    print("OK: todo el plano entra en la hoja.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
