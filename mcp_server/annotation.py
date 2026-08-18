"""Aparato de documentación de un plano: tablas, leyendas, cadenamientos y
cortes por capas.

Es lo que separa un dibujo de un plano entregable. Son estructuras repetitivas
—una grilla, una lista de simbología, marcas cada N metros— así que vivir acá y
no en la cabeza de quien dibuja es lo que corresponde: se piden con una llamada
y salen siempre iguales.

Se compone con las tools básicas del plugin, así que se cambia sin recompilar.
Unidades: las del modelo (metros si dibujás en metros).
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad
from geom import Axis, Point

LAYER_TABLE = "TABLAS"
LAYER_LEGEND = "LEYENDA"
LAYER_STATION = "CADENAMIENTO"
LAYER_SECTION = "CORTES"

LW_BOX = 25
LW_GRID = 13
LW_TEXT = 18


def _layer(name: str, color: int = 7, lineweight: int = LW_BOX) -> None:
    acad.call("set_layer", {"name": name, "colorIndex": color,
                            "linetype": None, "lineweightHundredthsMm": lineweight})


def _rect(x0: float, y0: float, x1: float, y1: float, layer: str,
          lineweight: int, color: Optional[int] = None) -> str:
    return acad.call("create_polyline", {
        "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        "closed": True, "layer": layer,
        "lineweight": lineweight, "colorIndex": color,
    })["handle"]


def _line(p0: Point, p1: Point, layer: str, lineweight: int,
          color: Optional[int] = None) -> str:
    return acad.call("create_line", {
        "x1": p0[0], "y1": p0[1], "z1": 0.0,
        "x2": p1[0], "y2": p1[1], "z2": 0.0,
        "layer": layer, "lineweight": lineweight, "colorIndex": color,
    })["handle"]


def _text(content: str, x: float, y: float, height: float, layer: str,
          lineweight: int = LW_TEXT, rotation: float = 0.0) -> Optional[str]:
    if not content:
        return None
    return acad.call("create_text", {
        "text": content, "x": x, "y": y, "z": 0.0, "height": height,
        "layer": layer, "rotationDeg": rotation,
        "lineweight": lineweight, "colorIndex": None,
    })["handle"]


def _hatch(handle: str, pattern: str, scale: float, layer: str,
           color: Optional[int] = None) -> Optional[str]:
    try:
        return acad.call("create_hatch", {
            "boundaryHandle": handle, "pattern": pattern, "scale": scale,
            "angleDeg": 0.0, "layer": layer,
            "lineweight": 9, "colorIndex": color,
        })["handle"]
    except acad.AutoCadError:
        # Un patrón que no existe en acad.pat no debe tumbar el plano entero.
        return None


# ------------------------------------------------------------------ tabla

def create_table(x: float, y: float, rows: list[list[str]],
                 col_widths: list[float], row_height: float,
                 text_height: float, title: str = "",
                 header: bool = True, layer: str = LAYER_TABLE) -> dict[str, Any]:
    """Tabla con grilla y texto. (x, y) es la esquina SUPERIOR izquierda.

    rows: filas de celdas ya como texto. Si header=True la primera va con la
    línea de abajo más gruesa y el texto centrado.
    col_widths: ancho de cada columna; define cuántas columnas hay.
    """
    if not rows:
        raise ValueError("La tabla necesita al menos una fila.")
    if not col_widths:
        raise ValueError("Hay que pasar col_widths.")

    _layer(layer)
    total_w = sum(col_widths)
    n = len(rows)

    top = y
    if title:
        top = y - row_height
        _rect(x, top, x + total_w, y, layer, LW_BOX)
        _text(title.upper(), x + total_w / 2.0 - _w(title.upper(), text_height) / 2.0,
              y - row_height / 2.0 - text_height / 2.0, text_height, layer, LW_TEXT)

    bottom = top - n * row_height
    _rect(x, bottom, x + total_w, top, layer, LW_BOX)

    # Líneas horizontales entre filas.
    for i in range(1, n):
        yy = top - i * row_height
        _line((x, yy), (x + total_w, yy), layer,
              LW_BOX if (header and i == 1) else LW_GRID)

    # Verticales entre columnas.
    cx = x
    for w in col_widths[:-1]:
        cx += w
        _line((cx, bottom), (cx, top), layer, LW_GRID)

    pad = text_height * 0.5
    for i, row in enumerate(rows):
        cy = top - i * row_height - row_height / 2.0 - text_height / 2.0
        cx = x
        for j, w in enumerate(col_widths):
            cell = str(row[j]) if j < len(row) else ""
            if cell:
                centrar = header and i == 0
                tx = (cx + w / 2.0 - _w(cell, text_height) / 2.0) if centrar else cx + pad
                _text(cell, tx, cy, text_height, layer, LW_TEXT)
            cx += w

    return {"x": x, "y": y, "width": total_w,
            "height": (y - bottom), "rows": n,
            "bottom": bottom, "right": x + total_w}


def _w(text: str, height: float) -> float:
    """Ancho real del texto, preguntándole a AutoCAD (con respaldo estimado)."""
    try:
        return acad.call("measure_text", {
            "text": text, "height": height,
            "style": None, "widthFactor": None})["width"]
    except (acad.AutoCadError, KeyError, TypeError):
        return len(text) * height * 0.87


# ---------------------------------------------------------------- leyenda

def create_legend(x: float, y: float, items: list[dict[str, Any]],
                  text_height: float, swatch_width: float = 0.0,
                  swatch_height: float = 0.0, row_height: float = 0.0,
                  title: str = "LEYENDA",
                  layer: str = LAYER_LEGEND) -> dict[str, Any]:
    """Lista de simbología: una muestra del rayado y su descripción al lado.

    (x, y) es la esquina superior izquierda.
    items: [{"label": "PAVIMENTO", "pattern": "ANSI31", "scale": 0.5,
             "color_index": 8}]. pattern None deja el cuadro vacío (solo
    contorno), que es lo correcto para simbología de línea.
    """
    if not items:
        raise ValueError("La leyenda necesita al menos un item.")

    _layer(layer)
    sw = swatch_width or text_height * 3.0
    sh = swatch_height or text_height * 1.3
    rh = row_height or text_height * 2.2
    gap = text_height * 0.8

    cursor = y
    if title:
        _text(title.upper(), x, cursor - text_height * 1.3,
              text_height * 1.25, layer, LW_BOX)
        cursor -= text_height * 2.6

    ancho_texto = 0.0
    for item in items:
        label = str(item.get("label", ""))
        ancho_texto = max(ancho_texto, _w(label, text_height))

        y_sw = cursor - sh
        handle = _rect(x, y_sw, x + sw, cursor, layer, LW_GRID,
                       item.get("color_index"))
        pattern = item.get("pattern")
        if pattern:
            _hatch(handle, str(pattern), float(item.get("scale", 1.0)), layer,
                   item.get("color_index"))

        _text(label, x + sw + gap, y_sw + (sh - text_height) / 2.0,
              text_height, layer, LW_TEXT)
        cursor -= rh

    return {"x": x, "y": y, "bottom": cursor,
            "width": sw + gap + ancho_texto, "height": y - cursor,
            "items": len(items)}


# ----------------------------------------------------------- cadenamiento

def create_stationing(points: list[list[float]], interval: float,
                      text_height: float, tick: float = 0.0,
                      start_station: float = 0.0, closed: bool = False,
                      label_every: int = 1, station_format: str = "km",
                      layer: str = LAYER_STATION) -> dict[str, Any]:
    """Marcas de cadenamiento cada 'interval' metros sobre un eje.

    Es cómo se referencia una obra lineal: cada marca dice a qué distancia del
    arranque está, con el formato 0+000 que se usa en carreteras y calles.

    points: el eje (el mismo que usaste para la calle).
    tick: largo de la marca perpendicular; por defecto 3x la altura de texto.
    label_every: rotula 1 de cada N marcas, para no saturar en intervalos cortos.
    """
    if interval <= 0:
        raise ValueError("interval tiene que ser > 0.")

    axis = Axis([(p[0], p[1]) for p in points], closed=closed)
    _layer(layer, color=1, lineweight=LW_GRID)

    t = tick or text_height * 3.0
    marcas = []
    d = 0.0
    i = 0
    while d <= axis.total_length + 1e-9:
        p0 = axis.offset_point_at(d, -t / 2.0)
        p1 = axis.offset_point_at(d, t / 2.0)
        _line(p0, p1, layer, LW_GRID, 1)

        if i % max(1, label_every) == 0:
            estacion = start_station + d
            if station_format == "plain":
                # Como se rotula una calle corta: 0.00, 20.00, 40.00...
                etiqueta = f"{estacion:.2f}"
            else:
                etiqueta = f"{int(estacion // 1000)}+{estacion % 1000:06.2f}"
            seg, _ = axis.segment_at(d)
            u = axis.dirs[seg]
            ang = math.degrees(math.atan2(u[1], u[0]))
            # El texto va paralelo al eje y siempre legible: nunca cabeza abajo.
            if ang > 90 or ang < -90:
                ang += 180
            tp = axis.offset_point_at(d, t / 2.0 + text_height * 0.6)
            acad.call("create_text", {
                "text": etiqueta, "x": tp[0], "y": tp[1], "z": 0.0,
                "height": text_height, "layer": layer, "rotationDeg": ang,
                "lineweight": LW_TEXT, "colorIndex": 1,
            })
            marcas.append({"station": etiqueta, "distance": d})

        d += interval
        i += 1

    return {"length": axis.total_length, "interval": interval,
            "marks": len(marcas), "stations": marcas}


# --------------------------------------------------- corte por capas

def create_layer_section(x: float, y: float, width: float,
                         layers: list[dict[str, Any]], text_height: float,
                         title: str = "", leader_length: float = 0.0,
                         draw_scale: float = 1.0, dimension_side: bool = True,
                         layer: str = LAYER_SECTION) -> dict[str, Any]:
    """Corte transversal por capas, de arriba hacia abajo.

    Es el detalle típico de un pavimento o un firme: carpeta, base, subbase,
    terreno natural, cada una con su rayado y su espesor anotado al costado.

    (x, y) es la esquina SUPERIOR izquierda de la primera capa.
    layers: [{"name": "CARPETA ASFÁLTICA", "thickness": 0.05,
              "pattern": "ANSI31", "scale": 0.3, "color_index": 8}]

    thickness va SIEMPRE en medidas reales de obra (0.15 = 15 cm). draw_scale
    agranda el dibujo sin tocar lo que dicen los rótulos: en una lámina a 1:200
    un firme de 33 cm sería invisible, así que se dibuja con draw_scale=10 y
    igual queda rotulado "e=15 cm".
    """
    if not layers:
        raise ValueError("El corte necesita al menos una capa.")
    if draw_scale <= 0:
        raise ValueError("draw_scale tiene que ser > 0.")

    _layer(layer)
    lead = leader_length or width * 0.25
    cursor = y
    dibujadas = []
    dim_x = x - text_height * 0.8

    for capa in layers:
        try:
            espesor = float(capa["thickness"])
            nombre = str(capa.get("name", ""))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Cada capa necesita 'thickness' y 'name'. ({exc})")
        if espesor <= 0:
            raise ValueError(f"La capa '{capa.get('name')}' tiene espesor <= 0.")

        base = cursor - espesor * draw_scale
        handle = _rect(x, base, x + width, cursor, layer, LW_BOX,
                       capa.get("color_index"))
        pattern = capa.get("pattern")
        if pattern:
            _hatch(handle, str(pattern), float(capa.get("scale", 1.0)), layer,
                   capa.get("color_index"))

        # Línea guía y rótulo a la derecha, con el espesor real en centímetros.
        medio = (cursor + base) / 2.0
        _line((x + width, medio), (x + width + lead, medio), layer, LW_GRID)
        etiqueta = f"{nombre}  e={espesor * 100:.0f} cm"
        _text(etiqueta, x + width + lead + text_height * 0.5,
              medio - text_height / 2.0, text_height, layer, LW_TEXT)

        # Espesor acotado del lado izquierdo, como en un detalle de obra.
        if dimension_side:
            _line((dim_x, cursor), (x, cursor), layer, LW_GRID, 1)
            _line((dim_x, base), (x, base), layer, LW_GRID, 1)
            _line((dim_x, cursor), (dim_x, base), layer, LW_GRID, 1)
            acad.call("create_text", {
                "text": f"e={espesor * 100:.0f} cm",
                "x": dim_x - text_height * 0.4,
                "y": medio - text_height * 2.0, "z": 0.0,
                "height": text_height * 0.8, "layer": layer,
                "rotationDeg": 90.0, "lineweight": LW_TEXT, "colorIndex": 1,
            })

        dibujadas.append({"name": nombre, "thickness": espesor,
                          "top": cursor, "bottom": base})
        cursor = base

    total = sum(float(c["thickness"]) for c in layers)
    if title:
        _text(title.upper(), x, y + text_height * 1.2,
              text_height * 1.2, layer, LW_BOX)

    return {"x": x, "y": y, "width": width, "totalThickness": total,
            "bottom": cursor, "layers": dibujadas}
