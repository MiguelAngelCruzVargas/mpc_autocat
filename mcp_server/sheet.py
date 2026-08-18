"""Cajón (marco) y cuadro de rotulación de una lámina.

Es lo PRIMERO que se dibuja en un plano: define el formato de hoja, la escala y
el área útil donde entra el dibujo. Todo lo demás se ubica adentro de esa área.

Se compone con las tools básicas (create_polyline / create_line / create_text)
en vez de ser un comando del plugin, así el diseño del rótulo se puede cambiar
sin recompilar el DLL ni volver a cargarlo en AutoCAD.

Unidades: todas las medidas de acá adentro están en MILÍMETROS DE PAPEL, que es
como se piensa un formato (un A1 son 841x594mm impresos, sin importar si el
dibujo está en metros o en centímetros). `_Paper.to_model()` las convierte a
unidades del modelo según la escala y la unidad en la que se dibuja.
"""
from __future__ import annotations

from typing import Any, Optional

import autocad_client as acad

# Formatos ISO 216 en mm (ancho, alto), apaisados.
SHEET_FORMATS: dict[str, tuple[float, float]] = {
    "A0": (1189.0, 841.0),
    "A1": (841.0, 594.0),
    "A2": (594.0, 420.0),
    "A3": (420.0, 297.0),
    "A4": (297.0, 210.0),
}

# Cuántos mm mide 1 unidad del modelo. Dibujar en metros es lo habitual en
# arquitectura/urbanismo; en mm, en despiece y detalle.
MM_PER_MODEL_UNIT: dict[str, float] = {"m": 1000.0, "cm": 10.0, "mm": 1.0}

# Márgenes del cajón (ISO 5457): el izquierdo es más ancho para encuadernar.
MARGIN_LEFT_MM = 25.0
MARGIN_MM = 10.0

# Rótulo, esquina inferior derecha del cajón.
TITLE_W_MM = 180.0
ROW_PROJECT_MM = 16.0   # nombre de la obra, la franja más alta
ROW_MM = 9.0            # ubicación / propietario / contenido
ROW_FOOT_MM = 13.0      # escala | fecha | dibujó | lámina

# Alturas de texto en mm de papel.
H_PROJECT_MM = 4.5
H_VALUE_MM = 2.8
H_LABEL_MM = 1.8

# Grosores de trazo en centésimas de mm.
LW_FRAME = 70    # el cajón: el trazo más grueso de la lámina
LW_BOX = 35      # divisiones del rótulo
LW_SHEET = 13    # borde de hoja
LW_TEXT = 25

LAYER_FRAME = "CAJON"
LAYER_TITLE = "ROTULO"


class _Paper:
    """Convierte mm de papel a unidades del modelo para una escala dada."""

    def __init__(self, scale_denominator: float, model_units: str):
        if scale_denominator <= 0:
            raise ValueError("scale_denominator tiene que ser > 0 (1:100 -> 100).")
        if model_units not in MM_PER_MODEL_UNIT:
            raise ValueError(
                f"model_units invalido: {model_units!r}. "
                f"Opciones: {', '.join(MM_PER_MODEL_UNIT)}."
            )
        self.factor = scale_denominator / MM_PER_MODEL_UNIT[model_units]

    def __call__(self, mm: float) -> float:
        return mm * self.factor


def _rect(x1: float, y1: float, x2: float, y2: float, layer: str,
          lineweight: int) -> str:
    """Rectángulo como polilínea cerrada. Devuelve su handle."""
    result = acad.call("create_polyline", {
        "points": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
        "closed": True,
        "layer": layer,
        "lineweight": lineweight,
        "colorIndex": None,
    })
    return result["handle"]


def _line(x1: float, y1: float, x2: float, y2: float, layer: str,
          lineweight: int) -> None:
    acad.call("create_line", {
        "x1": x1, "y1": y1, "z1": 0.0, "x2": x2, "y2": y2, "z2": 0.0,
        "layer": layer, "lineweight": lineweight, "colorIndex": None,
    })


def _text(content: str, x: float, y: float, height: float, layer: str,
          lineweight: int) -> None:
    if not content:
        return
    acad.call("create_text", {
        "text": content, "x": x, "y": y, "z": 0.0, "height": height,
        "layer": layer, "rotationDeg": 0.0,
        "lineweight": lineweight, "colorIndex": None,
    })


def _cell(mm, x_left_mm: float, y_bottom_mm: float, label: str, value: str,
          origin_x: float, origin_y: float, pad_mm: float = 2.0,
          value_height_mm: float = H_VALUE_MM) -> None:
    """Una celda del rótulo: etiqueta chica arriba, valor debajo."""
    x = origin_x + mm(x_left_mm + pad_mm)
    _text(label.upper(),
          x, origin_y + mm(y_bottom_mm + ROW_FOOT_MM - pad_mm - H_LABEL_MM),
          mm(H_LABEL_MM), LAYER_TITLE, LW_TEXT)
    _text(value,
          x, origin_y + mm(y_bottom_mm + pad_mm),
          mm(value_height_mm), LAYER_TITLE, LW_TEXT)


def create_sheet(
    sheet_format: str = "A1",
    scale_denominator: float = 100.0,
    model_units: str = "m",
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    project: str = "",
    location: str = "",
    client: str = "",
    content: str = "",
    drawn_by: str = "",
    reviewed_by: str = "",
    date: str = "",
    sheet_number: str = "",
    width_mm: Optional[float] = None,
    height_mm: Optional[float] = None,
) -> dict[str, Any]:
    """Dibuja el cajón y el cuadro de rotulación. Devuelve el área útil."""
    if width_mm is not None and height_mm is not None:
        sheet_w, sheet_h = float(width_mm), float(height_mm)
        fmt_name = f"{sheet_w:g}x{sheet_h:g}mm"
    else:
        key = sheet_format.upper().strip()
        if key not in SHEET_FORMATS:
            raise ValueError(
                f"Formato {sheet_format!r} desconocido. Opciones: "
                f"{', '.join(SHEET_FORMATS)}, o pasá width_mm y height_mm."
            )
        sheet_w, sheet_h = SHEET_FORMATS[key]
        fmt_name = key

    mm = _Paper(scale_denominator, model_units)

    # Capas propias, para poder apagar el formato y ver solo el dibujo.
    acad.call("set_layer", {"name": LAYER_FRAME, "colorIndex": 7,
                            "linetype": None, "lineweightHundredthsMm": LW_FRAME})
    acad.call("set_layer", {"name": LAYER_TITLE, "colorIndex": 7,
                            "linetype": None, "lineweightHundredthsMm": LW_BOX})

    ox, oy = origin_x, origin_y

    # Borde de hoja (el papel) y cajón (el marco de dibujo, con márgenes).
    _rect(ox, oy, ox + mm(sheet_w), oy + mm(sheet_h), LAYER_FRAME, LW_SHEET)

    fx1, fy1 = ox + mm(MARGIN_LEFT_MM), oy + mm(MARGIN_MM)
    fx2, fy2 = ox + mm(sheet_w - MARGIN_MM), oy + mm(sheet_h - MARGIN_MM)
    frame_handle = _rect(fx1, fy1, fx2, fy2, LAYER_FRAME, LW_FRAME)

    # --- Rótulo, pegado a la esquina inferior derecha del cajón ---
    title_h_mm = ROW_PROJECT_MM + 3 * ROW_MM + ROW_FOOT_MM
    tx1 = fx2 - mm(TITLE_W_MM)
    ty1 = fy1
    title_handle = _rect(tx1, ty1, fx2, ty1 + mm(title_h_mm), LAYER_TITLE, LW_BOX)

    # Filas, de abajo hacia arriba: pie, contenido, propietario, ubicación, obra.
    y_mm = 0.0
    row_tops_mm = []
    for h in (ROW_FOOT_MM, ROW_MM, ROW_MM, ROW_MM):
        y_mm += h
        row_tops_mm.append(y_mm)
        _line(tx1, ty1 + mm(y_mm), fx2, ty1 + mm(y_mm), LAYER_TITLE, LW_BOX)

    # Pie dividido en 5: escala | fecha | dibujó | revisó | lámina.
    col_w_mm = TITLE_W_MM / 5.0
    foot_cols_mm = [i * col_w_mm for i in range(6)]
    for x_mm in foot_cols_mm[1:-1]:
        _line(tx1 + mm(x_mm), ty1, tx1 + mm(x_mm), ty1 + mm(ROW_FOOT_MM),
              LAYER_TITLE, LW_BOX)

    scale_text = f"1:{scale_denominator:g}"
    foot = [("ESCALA", scale_text), ("FECHA", date), ("DIBUJÓ", drawn_by),
            ("REVISÓ", reviewed_by), ("LÁMINA", sheet_number)]
    for (label, value), x_mm in zip(foot, foot_cols_mm[:-1]):
        # La lámina es el dato que se busca de un vistazo: va más grande.
        big = label == "LÁMINA"
        _cell(mm, x_mm, 0.0, label, value, tx1, ty1,
              value_height_mm=H_PROJECT_MM if big else H_VALUE_MM)

    # Filas de datos: contenido, propietario, ubicación (de abajo hacia arriba).
    rows = [("CONTENIDO", content), ("PROPIETARIO", client), ("UBICACIÓN", location)]
    for (label, value), y_base_mm in zip(rows, row_tops_mm[:-1]):
        _text(label, tx1 + mm(2.0), ty1 + mm(y_base_mm + 2.2),
              mm(H_LABEL_MM), LAYER_TITLE, LW_TEXT)
        _text(value, tx1 + mm(30.0), ty1 + mm(y_base_mm + 2.0),
              mm(H_VALUE_MM), LAYER_TITLE, LW_TEXT)

    # Nombre de la obra, la franja de arriba.
    y_project_mm = row_tops_mm[-1]
    _text("OBRA", tx1 + mm(2.0), ty1 + mm(y_project_mm + ROW_PROJECT_MM - 4.0),
          mm(H_LABEL_MM), LAYER_TITLE, LW_TEXT)
    _text(project, tx1 + mm(2.0), ty1 + mm(y_project_mm + 3.0),
          mm(H_PROJECT_MM), LAYER_TITLE, LW_TEXT)

    # Área útil = adentro del cajón, sin pisar el rótulo. Es lo que hay que
    # respetar al dibujar: todo el plano entra acá.
    draw = {
        "x1": fx1, "y1": ty1 + mm(title_h_mm), "x2": fx2, "y2": fy2,
        "full_x1": fx1, "full_y1": fy1, "full_x2": tx1, "full_y2": fy2,
    }

    return {
        "format": fmt_name,
        "scale": scale_text,
        "modelUnits": model_units,
        "sheetSizeModel": [mm(sheet_w), mm(sheet_h)],
        "unitsPerPaperMm": mm(1.0),
        "drawArea": draw,
        "frameHandle": frame_handle,
        "titleBlockHandle": title_handle,
    }
