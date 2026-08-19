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

import math
from typing import Any, Optional

import autocad_client as acad
import furniture as fur
import space

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
    orientation: str = "horizontal",
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
        # Sin esto la hoja sale SIEMPRE apaisada: fit_sheet puede haber elegido
        # el formato vertical y el cajon se dibujaba acostado, con el dibujo
        # saliendose por arriba.
        if str(orientation).lower() in ("vertical", "portrait", "retrato"):
            sheet_w, sheet_h = sheet_h, sheet_w
            fmt_name = key + " vertical"

    mm = _Paper(scale_denominator, model_units)

    # Una lamina nueva es un plano nuevo: la escala que rige pasa a ser esta y
    # lo ocupado por el plano anterior deja de contar. Sin esto, redibujar el
    # mismo plano en una sesion larga iba corriendo las cotas cada vez mas
    # afuera, apilandolas sobre franjas que ya no existen.
    space.set_scale(mm(1.0))
    space.clear()
    fur.reset_footprints()

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


# ------------------------------------------- encuadre sobre lo ya dibujado

# Formatos ordenados de menor a mayor, para elegir el primero que alcance.
FORMATOS_ORDENADOS = ["A4", "A3", "A2", "A1", "A0"]

# Escalas de dibujo usuales; se prueban de la mas detallada a la mas chica.
ESCALAS_USUALES = [10, 20, 25, 50, 75, 100, 150, 200, 250, 500, 1000]


def escala_sugerida(tamano_max: float, model_units: str = "m") -> float:
    """Escala usual segun lo que mide el dibujo.

    No es una cuenta: es la convencion de la profesion. Una planta de casa se
    dibuja a 1:50 aunque entrara a 1:100 en una hoja mas chica, porque a 1:100
    no se leen los espesores ni las cotas de un baño.
    """
    metros = tamano_max * MM_PER_MODEL_UNIT[model_units] / 1000.0
    for limite, escala in ((6, 20.0), (20, 50.0), (45, 100.0),
                           (120, 200.0), (300, 500.0)):
        if metros <= limite:
            return escala
    return 1000.0


def fit_sheet(min_x: float, min_y: float, max_x: float, max_y: float,
              model_units: str = "m",
              sheet_format: Optional[str] = None,
              scale_denominator: Optional[float] = None,
              margin_mm: float = 15.0,
              allow_portrait: bool = True) -> dict[str, Any]:
    """Qué formato y escala hacen falta para que el dibujo entre, y dónde va
    la esquina de la hoja.

    No dibuja nada: solo calcula. Es el paso que permite invertir el orden —
    dibujar primero, medir, y recién entonces encuadrar. Al revés, un dibujo
    más grande de lo previsto se sale de la hoja.

    Sin `scale_denominator` elige la escala usual para ese tamaño (1:50 para
    una casa, 1:200 para una calle) y después el formato MÁS CHICO que la
    contenga. Fijando el formato, busca la escala que entre en él.

    allow_portrait: además del formato apaisado prueba el vertical, que es lo
    que corresponde cuando el dibujo es más alto que ancho.
    """
    ancho = max_x - min_x
    alto = max_y - min_y
    if ancho <= 0 or alto <= 0:
        raise ValueError(
            f"La extensión del dibujo es vacía ({ancho:g} x {alto:g}). "
            "¿Hay algo dibujado?")
    if model_units not in MM_PER_MODEL_UNIT:
        raise ValueError(f"model_units inválido: {model_units!r}.")

    mm_por_unidad = MM_PER_MODEL_UNIT[model_units]

    def candidatos_formato():
        """(nombre, ancho_mm, alto_mm) en apaisado y, si se permite, vertical."""
        nombres = [sheet_format.upper()] if sheet_format else FORMATOS_ORDENADOS
        for n in nombres:
            if n not in SHEET_FORMATS:
                raise ValueError(f"Formato {n!r} desconocido.")
            w, h = SHEET_FORMATS[n]
            yield n, w, h, "horizontal"
            if allow_portrait:
                yield n, h, w, "vertical"

    # El rotulo ocupa la esquina inferior derecha: si no se descuenta, el
    # dibujo se centra sobre el y quedan encimados.
    alto_rotulo = ROW_PROJECT_MM + 3 * ROW_MM + ROW_FOOT_MM

    def libre(w_hoja, h_hoja):
        return (w_hoja - MARGIN_LEFT_MM - MARGIN_MM - 2 * margin_mm,
                h_hoja - 2 * MARGIN_MM - alto_rotulo - 2 * margin_mm)

    def entra(w_hoja, h_hoja, esc):
        libre_w, libre_h = libre(w_hoja, h_hoja)
        return (ancho * mm_por_unidad / esc <= libre_w
                and alto * mm_por_unidad / esc <= libre_h)

    if scale_denominator:
        escalas = [float(scale_denominator)]
    elif sheet_format:
        # Formato fijo: la escala más detallada que entre en él.
        escalas = [float(e) for e in ESCALAS_USUALES]
    else:
        # Escala de la profesión y, si no alcanza, se va abriendo.
        sugerida = escala_sugerida(max(ancho, alto), model_units)
        escalas = [e for e in ESCALAS_USUALES if e >= sugerida] or [1000.0]
        escalas = [float(e) for e in escalas]

    elegido = None
    for esc in escalas:
        for nombre, w_hoja, h_hoja, orient in candidatos_formato():
            if entra(w_hoja, h_hoja, esc):
                elegido = (nombre, w_hoja, h_hoja, orient, esc)
                break
        if elegido:
            break

    if elegido is None:
        mayor = SHEET_FORMATS[FORMATOS_ORDENADOS[-1]]
        libre_w = max(mayor) - MARGIN_LEFT_MM - MARGIN_MM - 2 * margin_mm
        libre_h = min(mayor) - 2 * MARGIN_MM - 2 * margin_mm
        necesaria = max(ancho * mm_por_unidad / libre_w,
                        alto * mm_por_unidad / libre_h)
        raise ValueError(
            f"El dibujo mide {ancho:.2f} x {alto:.2f} {model_units} y no entra "
            f"en ningún formato con las escalas usuales: haría falta al menos "
            f"1:{necesaria:.0f}. Pasá una escala explícita.")

    nombre, w_hoja, h_hoja, orient, esc = elegido
    factor = esc / mm_por_unidad          # mm de papel -> unidades de modelo
    hoja_w_modelo, hoja_h_modelo = w_hoja * factor, h_hoja * factor

    # El dibujo se centra en la franja util, que es la que queda ARRIBA del
    # rotulo, no en la hoja entera.
    cx, cy = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
    origin_x = cx - hoja_w_modelo / 2.0 + (MARGIN_LEFT_MM - MARGIN_MM) / 2.0 * factor
    centro_util_mm = MARGIN_MM + alto_rotulo + (h_hoja - 2 * MARGIN_MM - alto_rotulo) / 2.0
    origin_y = cy - centro_util_mm * factor

    return {
        "sheet_format": nombre,
        "orientation": orient,
        "width_mm": w_hoja,
        "height_mm": h_hoja,
        "scale_denominator": esc,
        "origin_x": origin_x,
        "origin_y": origin_y,
        "model_units": model_units,
        "drawingWidth": ancho,
        "drawingHeight": alto,
        "sheetWidthModel": hoja_w_modelo,
        "sheetHeightModel": hoja_h_modelo,
        "paperWidthUsed": ancho * mm_por_unidad / esc,
        "paperHeightUsed": alto * mm_por_unidad / esc,
    }


# ------------------------------------------ validacion del programa vs lote

def check_program(lot_width: float, lot_depth: float,
                  spaces: list[dict[str, Any]],
                  outdoor: Optional[list[dict[str, Any]]] = None,
                  wall_thickness: float = 0.15,
                  circulation_factor: float = 0.12,
                  model_units: str = "m") -> dict[str, Any]:
    """¿El programa que pidió el cliente entra en el terreno?

    Se responde ANTES de dibujar. Un programa que no cierra no se arregla
    dibujando con cuidado: hay que decirlo, con el número, para que la decisión
    de qué achicar la tome quien corresponde y no quede escondida en un plano
    que después no se puede construir.

    spaces: [{"name": "Recámara", "width": 3.85, "depth": 4.00}] o
            [{"name": "Recámara", "area": 15.40}]
    outdoor: áreas descubiertas que se restan del terreno (cochera, jardín,
             patio), en el mismo formato.
    wall_thickness: para estimar cuánto se lleva la mampostería.
    circulation_factor: pasillos y vestíbulos como fracción del programa; 0.12
             es lo habitual en vivienda.

    Devuelve fits (True/False), el déficit en m2 y en porcentaje, y qué habría
    que hacer para que cierre.
    """
    if lot_width <= 0 or lot_depth <= 0:
        raise ValueError("El terreno tiene que tener dimensiones positivas.")
    if not spaces:
        raise ValueError("Hay que pasar al menos un ambiente en 'spaces'.")

    def area_de(item: dict[str, Any], donde: str) -> float:
        if item.get("area") is not None:
            a = float(item["area"])
        elif item.get("width") is not None and item.get("depth") is not None:
            a = float(item["width"]) * float(item["depth"])
        else:
            raise ValueError(
                f"{donde} '{item.get('name', '?')}': hace falta 'area' o "
                "'width' y 'depth'.")
        if a <= 0:
            raise ValueError(f"{donde} '{item.get('name','?')}': área <= 0.")
        return a

    area_lote = lot_width * lot_depth
    descubierto = [{"name": o.get("name", "descubierto"),
                    "area": area_de(o, "Área descubierta")}
                   for o in (outdoor or [])]
    area_descubierta = sum(o["area"] for o in descubierto)

    programa = [{"name": s.get("name", "?"), "area": area_de(s, "Ambiente")}
                for s in spaces]
    area_programa = sum(p["area"] for p in programa)
    circulacion = area_programa * circulation_factor
    necesario = area_programa + circulacion

    bruto = area_lote - area_descubierta
    if bruto <= 0:
        raise ValueError(
            f"Las áreas descubiertas ({area_descubierta:.2f} m2) ocupan todo el "
            f"terreno ({area_lote:.2f} m2): no queda nada para construir.")

    # Mampostería: perímetro del bruto mas los divisorios, estimados a partir
    # de la cantidad de ambientes.
    lado = math.sqrt(bruto)
    muros = (4 * lado + 2.2 * lado * len(programa) ** 0.5) * wall_thickness
    util = bruto - muros

    deficit = necesario - util
    entra = deficit <= 0

    resultado = {
        "fits": entra,
        "lotArea": round(area_lote, 2),
        "outdoorArea": round(area_descubierta, 2),
        "grossBuildable": round(bruto, 2),
        "wallsEstimate": round(muros, 2),
        "usableArea": round(util, 2),
        "programArea": round(area_programa, 2),
        "circulation": round(circulacion, 2),
        "required": round(necesario, 2),
        "deficit": round(max(deficit, 0.0), 2),
        "surplus": round(max(-deficit, 0.0), 2),
        "spaces": programa,
        "outdoorSpaces": descubierto,
    }

    if entra:
        resultado["message"] = (
            f"El programa entra: hacen falta {necesario:.2f} m2 y hay "
            f"{util:.2f} m2 útiles ({resultado['surplus']:.2f} m2 de holgura).")
        return resultado

    # No entra: se dice cuanto falta y por donde puede salir.
    pct = deficit / necesario * 100.0
    opciones = []
    if descubierto:
        mayor = max(descubierto, key=lambda o: o["area"])
        opciones.append(
            f"reducir {mayor['name']} ({mayor['area']:.2f} m2 hoy) en "
            f"{min(deficit, mayor['area'] * 0.6):.2f} m2")
    mayor_amb = max(programa, key=lambda p: p["area"])
    opciones.append(
        f"achicar {mayor_amb['name']} ({mayor_amb['area']:.2f} m2), el ambiente "
        "más grande del programa")
    opciones.append(
        f"repartir el faltante entre todos los ambientes: {pct:.1f}% cada uno")

    resultado["message"] = (
        f"NO ENTRA: el programa pide {necesario:.2f} m2 (incluida circulación) "
        f"y el terreno deja {util:.2f} m2 útiles. Faltan {deficit:.2f} m2, "
        f"un {pct:.1f}%.")
    resultado["options"] = opciones
    return resultado
