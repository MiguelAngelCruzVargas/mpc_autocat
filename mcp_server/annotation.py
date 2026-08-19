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
import layers
import space
from geom import Axis, Point, densify

LAYER_TABLE = "TABLAS"
LAYER_LEGEND = "LEYENDA"
LAYER_STATION = "CADENAMIENTO"
LAYER_SECTION = "CORTES"

LW_BOX = 25
LW_GRID = 13
LW_TEXT = 18


def _layer(name: str, color: int = 7, lineweight: int = LW_BOX) -> None:
    # Solo si no existe: ver layers.py.
    layers.ensure(name, color, lineweight)


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
                      layer: str = LAYER_STATION,
                      bulges: Optional[list[float]] = None,
                      label_offset: float = 0.0) -> dict[str, Any]:
    """Marcas de cadenamiento cada 'interval' metros sobre un eje.

    Es cómo se referencia una obra lineal: cada marca dice a qué distancia del
    arranque está, con el formato 0+000 que se usa en carreteras y calles.

    points: el eje (el mismo que usaste para la calle).
    tick: largo de la marca perpendicular; por defecto 3x la altura de texto.
    label_every: rotula 1 de cada N marcas, para no saturar en intervalos cortos.
    station_format: 'km' da 0+020.00, 'short' da 0+020 (metros cerrados) y
    'plain' da 20.00, para una calle corta donde el formato de carretera sobra.
    bulges: obligatorio si el eje tiene curvas. Sin ellos el cadenamiento se
    mide sobre la cuerda: el 0+060 de una curva cae metros antes de donde va,
    que es el error que después no cierra contra el replanteo.
    label_offset: a qué distancia PERPENDICULAR del eje va el número. Por
    defecto queda apenas afuera de la marca, que alcanza cuando el eje va
    solo; si sobre el eje corre algo más —una tubería y su rótulo— hay que
    separarlo y mandar lo otro al lado opuesto, o los dos textos se cruzan.
    """
    if interval <= 0:
        raise ValueError("interval tiene que ser > 0.")

    if bulges and any(abs(b) > 1e-12 for b in bulges):
        points = densify(points, bulges)
    axis = Axis([(p[0], p[1]) for p in points], closed=closed)
    _layer(layer, color=1, lineweight=LW_GRID)

    t = tick or text_height * 3.0
    marcas = []
    d = 0.0
    i = 0
    # 1 mm de tolerancia: el eje viene de muestrear arcos y queda unas
    # decimas de milimetro mas corto que su desarrollo. Sin esto, la marca
    # del final del tramo -la que cierra el cadenamiento- no se dibujaba.
    while d <= axis.total_length + 1e-3:
        p0 = axis.offset_point_at(d, -t / 2.0)
        p1 = axis.offset_point_at(d, t / 2.0)
        _line(p0, p1, layer, LW_GRID)

        if i % max(1, label_every) == 0:
            estacion = start_station + d
            if station_format == "plain":
                # Como se rotula una calle corta: 0.00, 20.00, 40.00...
                etiqueta = f"{estacion:.2f}"
            elif station_format == "short":
                # 0+020: el cadenamiento cerrado, sin decimales. Es lo que se
                # rotula sobre el eje cuando las marcas caen en metros justos
                # y los decimales solo ensucian.
                etiqueta = f"{int(estacion // 1000)}+{round(estacion % 1000):03d}"
            else:
                etiqueta = f"{int(estacion // 1000)}+{estacion % 1000:06.2f}"
            seg, _ = axis.segment_at(d)
            u = axis.dirs[seg]
            ang = math.degrees(math.atan2(u[1], u[0]))
            # El texto va paralelo al eje y siempre legible: nunca cabeza abajo.
            if ang > 90 or ang < -90:
                ang += 180
            tp = axis.offset_point_at(
                d, label_offset or (t / 2.0 + text_height * 0.6))
            acad.call("create_text", {
                "text": etiqueta, "x": tp[0], "y": tp[1], "z": 0.0,
                "height": text_height, "layer": layer, "rotationDeg": ang,
                "lineweight": LW_TEXT, "colorIndex": None,
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


# ------------------------------------------------------ cadenas de cotas

LAYER_DIMS = "COTAS"
LW_DIM = 13

# Todo esto se piensa en milimetros de PAPEL, que es donde vive la
# legibilidad: una cadena de cotas ocupa lo mismo en la hoja se dibuje en
# metros a 1:50 o en milimetros a 1:20. space.paper() lo pasa a unidades del
# modelo con la escala de la lamina.
BAND_MM = 6.0        # lo que ocupa una cadena: el numero, la linea y las flechas
LINE_IN_BAND_MM = 4.0  # donde cae la linea de cota dentro de esa franja
GAP_MM = 2.0         # aire entre una cadena y lo que ya estaba
FIRST_GAP_MM = 6.0   # aire entre el dibujo y la primera cadena
MIN_TRAMO_MM = 9.0   # abajo de esto el numero no entra entre las flechas


def create_dimension_chain(
    positions: Optional[list[float]] = None,
    side: str = "bottom",
    reference: float = 0.0,
    segments: Optional[list[list[float]]] = None,
    offset: float = 0.0,
    total: bool = False,
    scale: float = 0.0,
    style: Optional[str] = None,
    layer: str = LAYER_DIMS,
    lineweight: int = LW_DIM,
) -> dict[str, Any]:
    """Una corrida de cotas seguidas sobre un mismo lado del dibujo.

    Es como se acota una planta de verdad: no cota por cota con el offset
    calculado a mano, sino cadenas —los huecos, los ejes, el total— cada una
    en su nivel. El offset se resuelve solo: la cadena se apila afuera de lo
    que ya haya en ese lado, incluidas las burbujas de eje, que es lo que
    evita el choque clasico de la cota general cruzando los globos.

    positions: los cortes a lo largo del lado (x si side es bottom/top, y si
    es left/right). Entre cada par consecutivo sale una cota.
    segments: en vez de una corrida seguida, los tramos sueltos que van en esa
    MISMA linea de cota: [[3.65, 5.15], [-3.50, 3.50]]. Es como se acota una
    seccion tipo —banqueta, calzada, banqueta— salteando lo que a esa escala
    no se puede acotar (una guarnicion de 0.15 m). Con tres llamadas sueltas
    saldrian tres lineas distintas, que es justo lo que no se quiere.
    reference: la coordenada del borde del dibujo desde donde se mide el
    offset (y del paño inferior para 'bottom', x del izquierdo para 'left').
    offset: separacion hasta la linea de cota. 0 = calculada.
    total: agrega, un nivel mas afuera, la cota general de punta a punta.
    scale: DIMSCALE — unidades del modelo por mm de papel. 0 toma la de la
    lamina que create_sheet dejo registrada.
    """
    if side not in space.SIDES:
        raise ValueError(f"side tiene que ser uno de {space.SIDES}, no {side!r}.")
    if positions and segments:
        raise ValueError("Pasá 'positions' (corrida seguida) o 'segments' "
                         "(tramos sueltos en la misma linea), no los dos.")

    if segments:
        pares = []
        for i, par in enumerate(segments, start=1):
            if len(par) != 2:
                raise ValueError(f"El tramo #{i} necesita exactamente 2 valores.")
            a, b = sorted((round(float(par[0]), 6), round(float(par[1]), 6)))
            if b - a < 1e-9:
                raise ValueError(f"El tramo #{i} mide 0; no hay nada que medir.")
            pares.append((a, b))
        pares.sort()
        for (a0, a1), (b0, _) in zip(pares, pares[1:]):
            if b0 < a1 - 1e-9:
                raise ValueError(
                    f"Dos tramos se pisan: uno termina en {a1:g} y el "
                    f"siguiente arranca en {b0:g}.")
        cortes = [pares[0][0], pares[-1][1]]
    else:
        cortes = sorted(set(round(float(p), 6) for p in positions or []))
        if len(cortes) < 2:
            raise ValueError("Una cadena de cotas necesita al menos 2 posiciones "
                             "distintas; con una sola no hay nada que medir.")
        pares = list(zip(cortes, cortes[1:]))

    upm = float(scale) if scale else space.units_per_paper_mm()
    banda = space.paper(BAND_MM, upm)
    aire = space.paper(GAP_MM, upm)

    if offset:
        # A mano: se respeta lo pedido, pero la franja se reserva igual para
        # que lo que venga despues no se le encime.
        linea = float(offset)
        inicio = max(0.0, linea - space.paper(LINE_IN_BAND_MM, upm))
    else:
        inicio = space.free_offset(side, reference, cortes[0], cortes[-1],
                                   banda, aire,
                                   start=space.paper(FIRST_GAP_MM, upm))
        linea = inicio + space.paper(LINE_IN_BAND_MM, upm)

    horizontal = side in ("bottom", "top")
    angulo = 0.0 if horizontal else 90.0
    afuera = -1.0 if side in ("bottom", "left") else 1.0
    coord_linea = reference + afuera * linea

    def punto(pos: float) -> tuple[float, float]:
        return (pos, reference) if horizontal else (reference, pos)

    _layer(layer, color=7, lineweight=lineweight)

    handles, tramos, apretados = [], [], []
    minimo = space.paper(MIN_TRAMO_MM, upm)
    for a, b in pares:
        p0, p1 = punto(a), punto(b)
        medio = (a + b) / 2.0
        dim_x, dim_y = (medio, coord_linea) if horizontal else (coord_linea, medio)
        handles.append(acad.call("create_dimension_rotated", {
            "x1": p0[0], "y1": p0[1], "x2": p1[0], "y2": p1[1],
            "dimLineX": dim_x, "dimLineY": dim_y, "angleDeg": angulo,
            "layer": layer, "style": style, "scale": upm, "text": None,
            "lineweight": lineweight, "colorIndex": None,
        })["handle"])
        largo = b - a
        tramos.append(round(largo, 3))
        if largo < minimo:
            apretados.append({"from": round(a, 3), "to": round(b, 3),
                              "length": round(largo, 3)})

    caja = space.band_box(side, reference, inicio, banda, cortes[0], cortes[-1])
    space.reserve(*caja, what=f"cotas {side} ({len(handles)} tramos)")

    resultado: dict[str, Any] = {
        "side": side, "offset": round(linea, 4),
        "dimLineCoord": round(coord_linea, 4),
        "band": [round(v, 4) for v in caja],
        "handles": handles, "segments": tramos,
        "unitsPerPaperMm": upm,
    }

    if total:
        general = create_dimension_chain(
            [cortes[0], cortes[-1]], side, reference, offset=0.0, total=False,
            scale=upm, style=style, layer=layer, lineweight=lineweight)  # noqa: E501
        resultado["totalChain"] = general
        resultado["total"] = round(cortes[-1] - cortes[0], 3)

    if apretados:
        # No se falla: la cota se dibuja igual, porque el dato es correcto.
        # Pero el numero no entra entre las flechas y AutoCAD lo va a tirar
        # afuera pisando al vecino, asi que hay que decirlo.
        resultado["tightSegments"] = apretados
        resultado["warning"] = (
            f"{len(apretados)} tramo(s) por debajo de {MIN_TRAMO_MM:g} mm de "
            "papel: el numero no entra entre las flechas y va a salirse "
            "encima de la cota de al lado ("
            + ", ".join(f"{t['length']:.2f} entre {t['from']:.2f} y {t['to']:.2f}"
                        for t in apretados)
            + "). Sacalos a una cadena de detalle o resolvelos con un leader.")
    return resultado


# ------------------------------------------------------- flecha de flujo

LAYER_FLOW = "HIDRO_RED_DRENAJE"


def create_flow_arrow(points: list[list[float]], positions: list[float],
                      size: float = 0.0, bulges: Optional[list[float]] = None,
                      closed: bool = False, reverse: bool = False,
                      layer: str = LAYER_FLOW,
                      color_index: Optional[int] = None) -> dict[str, Any]:
    """Puntas de flecha SOLIDAS sobre un eje, marcando el sentido de escurrimiento.

    Un leader con el texto "sentido del flujo" no es lo mismo: en un plano de
    drenaje la flecha va SOBRE la tuberia, repetida a lo largo del tramo, y se
    lee de un vistazo sin buscar el rotulo. Es el simbolo que dice para donde
    corre el agua, y sin el un colector se puede leer al reves.

    points / bulges: el eje de la tuberia (o la calle). positions: los
    cadenamientos donde va cada flecha, medidos sobre ese eje.
    size: largo de la punta; por defecto 1/60 del eje, acotado a un rango
    razonable. reverse: la flecha apunta contra el sentido de avance.
    """
    if not positions:
        raise ValueError("Hay que decir en que cadenamientos van las flechas.")

    if bulges and any(abs(b) > 1e-12 for b in bulges):
        points = densify(points, bulges)
    axis = Axis([(p[0], p[1]) for p in points], closed=closed)
    largo = axis.total_length
    s = size or min(3.0, max(0.5, largo / 60.0))
    signo = -1.0 if reverse else 1.0

    _layer(layer, color=4, lineweight=LW_GRID)

    dibujadas = []
    for d in positions:
        d = float(d)
        if d < -1e-9 or d > largo + 1e-9:
            raise ValueError(
                f"La flecha en {d:g} se sale del eje, que mide {largo:.2f}.")
        i, _ = axis.segment_at(min(max(d, 0.0), largo))
        ux, uy = axis.dirs[i]
        ux, uy = ux * signo, uy * signo

        punta = axis.point_at(min(max(d, 0.0), largo))
        base = (punta[0] - ux * s, punta[1] - uy * s)
        # Perpendicular, para abrir la punta: media flecha a cada lado.
        ala = s * 0.32
        p1 = (base[0] - uy * ala, base[1] + ux * ala)
        p2 = (base[0] + uy * ala, base[1] - ux * ala)

        handle = acad.call("create_polyline", {
            "points": [[punta[0], punta[1]], [p1[0], p1[1]], [p2[0], p2[1]]],
            "closed": True, "layer": layer,
            "lineweight": LW_GRID, "colorIndex": color_index,
        })["handle"]
        # Rellena: una punta hueca se confunde con un detalle del dibujo.
        _hatch(handle, "SOLID", 1.0, layer, color_index)
        dibujadas.append({"distance": round(d, 3),
                          "x": round(punta[0], 4), "y": round(punta[1], 4),
                          "handle": handle})

    return {"arrows": dibujadas, "size": s, "axisLength": largo,
            "reversed": bool(reverse)}
