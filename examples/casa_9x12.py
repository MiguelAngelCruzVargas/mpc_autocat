"""Planta arquitectónica de casa habitación 9.00 x 12.00 m.

Distribución tomada de un render de referencia del cliente: 3 recámaras, 2
baños, sala, comedor y cocina, con pasillo central.

Las medidas de la referencia eran solo 9 x 12 (exteriores, a paño de muro); el
reparto interior está derivado de las proporciones del render y redondeado a
medidas de obra. Todas las cotas quedan dibujadas en el plano para poder
ajustarlas con el cliente.

EJEMPLO, no biblioteca. Esta guardado porque es un plano real y sirve de
referencia de como se compone uno entero, pero NO es la forma normal de
trabajar: para dibujar un plano nuevo se llaman las tools del MCP
(create_sheet, create_walls, place_furniture, label_rooms) directamente, sin
escribir un archivo por cada plano.

Uso:
  python examples/casa_9x12.py --preview salida.svg   # sin AutoCAD, a SVG
  python examples/casa_9x12.py                        # dibuja en AutoCAD
"""
from __future__ import annotations

import os
import sys

# Vive en examples/, pero usa la biblioteca de mcp_server/.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "mcp_server"))

# --preview tiene que instalar el mock ANTES de importar los módulos que
# resuelven acad.call, si no se quedan con el cliente real.
PREVIEW = "--preview" in sys.argv
if PREVIEW:
    import preview
    preview.install()

import arch          # noqa: E402
import autocad_client as acad  # noqa: E402
import furniture as fur        # noqa: E402
import sheet         # noqa: E402

# ---------------------------------------------------------------- medidas

EXT_W, EXT_H = 9.00, 12.00      # exteriores, a paño de muro
W_EXT = 0.15                    # muro exterior
W_INT = 0.10                    # muros divisorios

HALF = W_EXT / 2.0
# Eje del muro perimetral.
AX0, AY0 = HALF, HALF
AX1, AY1 = EXT_W - HALF, EXT_H - HALF

# Caras interiores del perímetro.
IX0, IY0 = W_EXT, W_EXT
IX1, IY1 = EXT_W - W_EXT, EXT_H - W_EXT

# Columnas: recámaras/sala | pasillo | zona de servicio.
COL_L = 3.30                    # ancho columna izquierda
HALL = 1.00                     # ancho del pasillo
AXIS_VL = IX0 + COL_L + W_INT / 2.0        # eje muro izq del pasillo = 3.50
AXIS_VR = AXIS_VL + W_INT / 2.0 + HALL + W_INT / 2.0   # eje muro der = 4.60
COL_R = IX1 - (AXIS_VR + W_INT / 2.0)      # ancho columna derecha = 4.20

# Franjas horizontales, de abajo hacia arriba.
BAND_LOW = 5.40                 # sala | comedor + cocina
BAND_MID = 2.90                 # recámara 1 | baños
AXIS_HL = IY0 + BAND_LOW + W_INT / 2.0     # eje = 5.60
AXIS_HU = AXIS_HL + W_INT / 2.0 + BAND_MID + W_INT / 2.0   # eje = 8.60
BAND_TOP = IY1 - (AXIS_HU + W_INT / 2.0)   # = 3.20

# Subdivisiones.
AXIS_BATH = AXIS_VR + W_INT / 2.0 + 2.05 + W_INT / 2.0     # entre los 2 baños
AXIS_KITCHEN = IY0 + 2.70 + W_INT / 2.0                    # cocina | comedor

# Bordes útiles de cada ambiente (x0, y0, x1, y1).
ROOMS = {
    "sala":       (IX0, IY0, AXIS_VL - W_INT / 2.0, AXIS_HL - W_INT / 2.0),
    "rec1":       (IX0, AXIS_HL + W_INT / 2.0, AXIS_VL - W_INT / 2.0, AXIS_HU - W_INT / 2.0),
    "rec2":       (IX0, AXIS_HU + W_INT / 2.0, AXIS_VL - W_INT / 2.0, IY1),
    "pasillo":    (AXIS_VL + W_INT / 2.0, IY0, AXIS_VR - W_INT / 2.0, IY1),
    "cocina":     (AXIS_VR + W_INT / 2.0, IY0, IX1, AXIS_KITCHEN - W_INT / 2.0),
    "comedor":    (AXIS_VR + W_INT / 2.0, AXIS_KITCHEN + W_INT / 2.0, IX1, AXIS_HL - W_INT / 2.0),
    "bano_comun": (AXIS_VR + W_INT / 2.0, AXIS_HL + W_INT / 2.0, AXIS_BATH - W_INT / 2.0, AXIS_HU - W_INT / 2.0),
    "bano_prin":  (AXIS_BATH + W_INT / 2.0, AXIS_HL + W_INT / 2.0, IX1, AXIS_HU - W_INT / 2.0),
    "recprin":    (AXIS_VR + W_INT / 2.0, AXIS_HU + W_INT / 2.0, IX1, IY1),
}

NAMES = {
    "sala": "SALA", "rec1": "RECÁMARA 1", "rec2": "RECÁMARA 2",
    "pasillo": "PASILLO", "cocina": "COCINA", "comedor": "COMEDOR",
    "bano_comun": "BAÑO", "bano_prin": "BAÑO", "recprin": "RECÁMARA PRINCIPAL",
}

# Alturas de texto: mm de papel x escala (1:50 en metros -> x0.05).
SCALE_DEN = 50.0
PAPER = SCALE_DEN / 1000.0
H_ROOM = 3.0 * PAPER
H_AREA = 2.2 * PAPER
DIM_SCALE = PAPER

ORIGIN = [0.0, 0.0]   # se completa con la posición dentro de la lámina


def P(x: float, y: float) -> list[float]:
    """Coordenada local de la casa -> coordenada del dibujo."""
    return [ORIGIN[0] + x, ORIGIN[1] + y]


def area_of(key: str) -> float:
    x0, y0, x1, y1 = ROOMS[key]
    return (x1 - x0) * (y1 - y0)


# ------------------------------------------------------------------ muros

def draw_walls() -> None:
    """Perímetro y divisorios. Las distancias de los huecos se miden a lo
    largo del eje de cada muro, desde su arranque."""

    # --- Perímetro, antihorario desde la esquina inferior izquierda ---
    # Tramos: abajo 0..8.85, derecha 8.85..20.70, arriba 20.70..29.55,
    # izquierda 29.55..41.40.
    bottom, right, top = AX1 - AX0, AY1 - AY0, AX1 - AX0
    d_right, d_top, d_left = bottom, bottom + right, bottom + right + top

    def on_bottom(x: float) -> float:
        return x - AX0

    def on_right(y: float) -> float:
        return d_right + (y - AY0)

    def on_top(x: float) -> float:
        return d_top + (AX1 - x)

    def on_left(y: float) -> float:
        return d_left + (AY1 - y)

    hall_cx = (ROOMS["pasillo"][0] + ROOMS["pasillo"][2]) / 2.0
    sala = ROOMS["sala"]
    cocina = ROOMS["cocina"]
    comedor = ROOMS["comedor"]
    recprin = ROOMS["recprin"]
    rec2 = ROOMS["rec2"]
    rec1 = ROOMS["rec1"]
    bano_prin = ROOMS["bano_prin"]

    arch.create_walls(
        points=[P(AX0, AY0), P(AX1, AY0), P(AX1, AY1), P(AX0, AY1)],
        thickness=W_EXT, closed=True, lineweight=50,
        openings=[
            # Fachada (abajo): acceso por el pasillo + ventanas.
            {"distance": on_bottom(sala[0] + (sala[2] - sala[0]) / 2.0),
             "width": 1.50, "type": "window"},
            {"distance": on_bottom(hall_cx), "width": 0.90, "type": "door",
             "swing": "left", "side": "left"},
            {"distance": on_bottom(cocina[0] + (cocina[2] - cocina[0]) / 2.0),
             "width": 1.20, "type": "window"},
            # Lateral derecho.
            {"distance": on_right(comedor[1] + (comedor[3] - comedor[1]) / 2.0),
             "width": 1.50, "type": "window"},
            {"distance": on_right(bano_prin[1] + (bano_prin[3] - bano_prin[1]) / 2.0),
             "width": 0.60, "type": "window"},
            {"distance": on_right(recprin[1] + (recprin[3] - recprin[1]) / 2.0),
             "width": 1.50, "type": "window"},
            # Fachada posterior (arriba).
            {"distance": on_top(recprin[0] + (recprin[2] - recprin[0]) / 2.0),
             "width": 1.50, "type": "window"},
            {"distance": on_top(rec2[0] + (rec2[2] - rec2[0]) / 2.0),
             "width": 1.50, "type": "window"},
            # Lateral izquierdo.
            {"distance": on_left(rec1[1] + (rec1[3] - rec1[1]) / 2.0),
             "width": 1.20, "type": "window"},
            {"distance": on_left(sala[1] + (sala[3] - sala[1]) / 2.0),
             "width": 1.50, "type": "window"},
        ],
    )

    # --- Muro izquierdo del pasillo: puertas de sala, recámaras 1 y 2 ---
    arch.create_walls(
        points=[P(AXIS_VL, AY0), P(AXIS_VL, AY1)],
        thickness=W_INT,
        openings=[
            {"distance": (sala[1] + sala[3]) / 2.0 - AY0 + 0.60,
             "width": 1.20, "type": "pass"},
            {"distance": (rec1[1] + rec1[3]) / 2.0 - AY0,
             "width": 0.80, "type": "door", "swing": "left", "side": "left"},
            {"distance": (rec2[1] + rec2[3]) / 2.0 - AY0,
             "width": 0.80, "type": "door", "swing": "left", "side": "left"},
        ],
    )

    # --- Muro derecho del pasillo: comedor, baño común, recámara principal ---
    arch.create_walls(
        points=[P(AXIS_VR, AY0), P(AXIS_VR, AY1)],
        thickness=W_INT,
        openings=[
            {"distance": (comedor[1] + comedor[3]) / 2.0 - AY0,
             "width": 1.20, "type": "pass"},
            {"distance": (ROOMS["bano_comun"][1] + ROOMS["bano_comun"][3]) / 2.0 - AY0,
             "width": 0.70, "type": "door", "swing": "left", "side": "right"},
            {"distance": (recprin[1] + recprin[3]) / 2.0 - AY0,
             "width": 0.90, "type": "door", "swing": "left", "side": "right"},
        ],
    )

    # --- Horizontales: se cortan en el pasillo, que es continuo ---
    for axis_y, with_bath_door in ((AXIS_HL, False), (AXIS_HU, True)):
        arch.create_walls(points=[P(AX0, axis_y), P(AXIS_VL, axis_y)],
                          thickness=W_INT)
        openings = []
        if with_bath_door:
            # Baño principal, en suite: se entra desde la recámara principal.
            bp = ROOMS["bano_prin"]
            openings.append({
                "distance": (bp[0] + bp[2]) / 2.0 - AXIS_VR,
                "width": 0.70, "type": "door", "swing": "left", "side": "left"})
        arch.create_walls(points=[P(AXIS_VR, axis_y), P(AX1, axis_y)],
                          thickness=W_INT, openings=openings or None)

    # --- Entre los dos baños ---
    arch.create_walls(
        points=[P(AXIS_BATH, AXIS_HL), P(AXIS_BATH, AXIS_HU)], thickness=W_INT)

    # --- Entre cocina y comedor, con paso ---
    arch.create_walls(
        points=[P(AXIS_VR, AXIS_KITCHEN), P(AX1, AXIS_KITCHEN)],
        thickness=W_INT,
        openings=[{"distance": (AX1 - AXIS_VR) / 2.0, "width": 1.00,
                   "type": "pass"}],
    )


# ------------------------------------------------------------- mobiliario

def draw_furniture() -> None:
    fur.ensure_layer()

    # --- Recámara principal: cama matrimonial contra el muro de fondo ---
    x0, y0, x1, y1 = ROOMS["recprin"]
    cx = (x0 + x1) / 2.0
    fur.bed(*P(cx + 0.80, y1 - 0.05), width=1.60, length=2.00, rotation_deg=180)
    fur.nightstand(*P(cx - 1.25, y1 - 0.50))
    fur.nightstand(*P(cx + 0.85, y1 - 0.50))
    fur.closet(*P(x0 + 0.10, y0 + 0.10), width=1.80, depth=0.60)

    # --- Recámara 2 ---
    x0, y0, x1, y1 = ROOMS["rec2"]
    fur.bed(*P(x0 + 1.60, y1 - 0.05), width=1.00, length=1.90, rotation_deg=180)
    fur.nightstand(*P(x0 + 1.65, y1 - 0.50))
    fur.closet(*P(x0 + 0.10, y0 + 0.10), width=1.50, depth=0.55)

    # --- Recámara 1 ---
    x0, y0, x1, y1 = ROOMS["rec1"]
    fur.bed(*P(x0 + 1.60, y1 - 0.05), width=1.00, length=1.90, rotation_deg=180)
    fur.nightstand(*P(x0 + 1.65, y1 - 0.50))
    fur.closet(*P(x0 + 0.10, y0 + 0.10), width=1.50, depth=0.55)

    # --- Sala ---
    x0, y0, x1, y1 = ROOMS["sala"]
    fur.sofa(*P(x0 + 0.55, y0 + 0.25), width=1.90, depth=0.85)
    fur.coffee_table(*P(x0 + 0.90, y0 + 1.45), width=1.10, depth=0.55)
    fur.armchair(*P(x0 + 0.30, y0 + 2.35), size=0.85)
    fur.armchair(*P(x0 + 2.10, y0 + 2.35), size=0.85)

    # --- Comedor ---
    x0, y0, x1, y1 = ROOMS["comedor"]
    fur.dining_table(*P((x0 + x1) / 2.0, (y0 + y1) / 2.0),
                     width=1.60, depth=0.90, seats_per_side=3)

    # --- Cocina: mesada corrida contra la fachada ---
    x0, y0, x1, y1 = ROOMS["cocina"]
    fur.counter(*P(x0 + 0.10, y0 + 0.10), width=3.10, depth=0.60)
    fur.kitchen_sink(*P(x0 + 0.25, y0 + 0.10), width=0.80, depth=0.60)
    fur.stove(*P(x0 + 1.70, y0 + 0.10), width=0.60, depth=0.60)
    fur.fridge(*P(x1 - 0.80, y0 + 0.10), width=0.70, depth=0.70)

    # --- Baños ---
    for key in ("bano_comun", "bano_prin"):
        x0, y0, x1, y1 = ROOMS[key]
        fur.wc(*P(x0 + 0.15, y0 + 0.12))
        fur.lavatory(*P(x0 + 0.75, y0 + 0.10), width=0.60, depth=0.45)
        fur.shower(*P(x1 - 1.00, y1 - 1.00), width=0.90, depth=0.90)


# ------------------------------------------------------------- anotación

def draw_labels() -> None:
    """Rotula cada ambiente en el hueco más despejado que le quede.

    Se llama DESPUES de draw_furniture(): los muebles ya registraron su huella
    en fur.OCCUPIED, asi que el rotulo puede esquivarlos en vez de caer siempre
    en el centro geometrico, que es justo donde suele estar la cama o el sillon.
    """
    acad.call("set_layer", {"name": "TEXTOS", "colorIndex": 7,
                            "linetype": None, "lineweightHundredthsMm": 25})

    for key, room in ROOMS.items():
        name = NAMES[key]
        local = (room[0] + ORIGIN[0], room[1] + ORIGIN[1],
                 room[2] + ORIGIN[0], room[3] + ORIGIN[1])

        if key == "pasillo":
            # Angosto: solo el nombre, y en chico.
            spot, ok = fur.find_label_spot(local, name, H_AREA)
            fur.label(name, spot[0], spot[1], height=H_AREA)
            continue

        spot, ok = fur.find_label_spot(local, name, H_ROOM,
                                       area=area_of(key), area_height=H_AREA)
        if not ok:
            # No habia lugar para nombre + area: probamos solo con el nombre.
            spot, ok = fur.find_label_spot(local, name, H_AREA)
            fur.label(name, spot[0], spot[1], height=H_AREA)
            print(f"  aviso: {name} quedo apretado, se rotulo sin superficie")
            continue

        fur.label(name, spot[0], spot[1], height=H_ROOM,
                  area=area_of(key), area_height=H_AREA)


def draw_dimensions() -> None:
    acad.call("set_layer", {"name": "COTAS", "colorIndex": 7,
                            "linetype": None, "lineweightHundredthsMm": 13})
    off = 1.10

    def dim(p0: list[float], p1: list[float], line: list[float]) -> None:
        acad.call("create_dimension", {
            "x1": p0[0], "y1": p0[1], "x2": p1[0], "y2": p1[1],
            "dimLineX": line[0], "dimLineY": line[1],
            "layer": "COTAS", "scale": DIM_SCALE,
            "lineweight": 13, "colorIndex": None,
        })

    # Generales.
    dim(P(0, 0), P(EXT_W, 0), P(EXT_W / 2.0, -off))
    dim(P(0, 0), P(0, EXT_H), P(-off, EXT_H / 2.0))

    # Parciales horizontales: columnas.
    y_line = -off * 0.55
    dim(P(0, 0), P(AXIS_VL, 0), P(AXIS_VL / 2.0, y_line))
    dim(P(AXIS_VL, 0), P(AXIS_VR, 0), P((AXIS_VL + AXIS_VR) / 2.0, y_line))
    dim(P(AXIS_VR, 0), P(EXT_W, 0), P((AXIS_VR + EXT_W) / 2.0, y_line))

    # Parciales verticales: franjas.
    x_line = -off * 0.55
    dim(P(0, 0), P(0, AXIS_HL), P(x_line, AXIS_HL / 2.0))
    dim(P(0, AXIS_HL), P(0, AXIS_HU), P(x_line, (AXIS_HL + AXIS_HU) / 2.0))
    dim(P(0, AXIS_HU), P(0, EXT_H), P(x_line, (AXIS_HU + EXT_H) / 2.0))


# ----------------------------------------------------------------- main

def main() -> int:
    lamina = sheet.create_sheet(
        sheet_format="A2", scale_denominator=SCALE_DEN, model_units="m",
        project="CASA HABITACIÓN 9.00 x 12.00 m",
        location="POR DEFINIR",
        client="POR DEFINIR",
        content="PLANTA ARQUITECTÓNICA",
        drawn_by="", reviewed_by="", date="18/08/2026", sheet_number="A-01",
    )
    area = lamina["drawArea"]
    aw, ah = area["x2"] - area["x1"], area["y2"] - area["y1"]

    # Centrado, dejando aire para las cotas exteriores.
    ORIGIN[0] = area["x1"] + (aw - EXT_W) / 2.0
    ORIGIN[1] = area["y1"] + (ah - EXT_H) / 2.0 + 0.60
    print(f"lamina {lamina['format']} {lamina['scale']} -> util {aw:.2f} x {ah:.2f}")
    print(f"casa {EXT_W} x {EXT_H} en ({ORIGIN[0]:.2f}, {ORIGIN[1]:.2f})")

    if EXT_W > aw or EXT_H > ah:
        print("La casa no entra en el area util: subir el formato o la escala.")
        return 1

    acad.call("set_display_options", {"lineweightDisplay": True})
    fur.reset_footprints()
    draw_walls()
    draw_furniture()
    draw_labels()
    draw_dimensions()

    total = sum(area_of(k) for k in ROOMS)
    print(f"superficie util: {total:.2f} m2 (construida {EXT_W * EXT_H:.2f} m2)")
    for key in ROOMS:
        print(f"  {NAMES[key]:<20} {area_of(key):6.2f} m2")

    if PREVIEW:
        import preview
        w, h = lamina["sheetSizeModel"]
        out = sys.argv[sys.argv.index("--preview") + 1]
        preview.save(out, preview.DRAWN, reference_span=max(w, h))
        fuera = preview.check_inside(preview.DRAWN, w, h)
        print(f"{len(preview.DRAWN)} entidades -> {out}")
        if fuera:
            print(f"AVISO: {len(fuera)} puntos fuera de la hoja: {fuera[:3]}")
            return 1
        print("OK: todo entra en la hoja.")
    else:
        acad.call("zoom_extents")
        info = acad.call("get_drawing_info")
        print(f"listo: {info['entityCount']} entidades en el dibujo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
