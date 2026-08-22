"""Elementos arquitectónicos: muros con espesor, puertas, ventanas y ejes.

Todo se compone con las tools básicas del plugin, así que se puede cambiar sin
recompilar el DLL. La geometría fina (offset con inglete) vive en geom.py.

Unidades: las mismas del modelo. Si dibujás en metros, un muro de 15cm es
thickness=0.15; si dibujás en milímetros, thickness=150.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad
import layers
import space
from geom import Axis, Point

LAYER_WALLS = "MUROS"
LAYER_OPENINGS = "PUERTAS-VENTANAS"
LAYER_GRID = "EJES"

LW_WALL = 50
LW_OPENING = 25
LW_GRID = 13

# Tipo de línea de los ejes: eje y trazo, como manda la simbología.
GRID_LINETYPE = "CENTER"
GRID_COLOR = layers.COLOR_EJES  # ambar oscuro: ver la paleta en layers.py


def _polyline(points: list[Point], layer: str, lineweight: int,
              closed: bool = True, track: str = "") -> str:
    result = acad.call("create_polyline", {
        "points": [[p[0], p[1]] for p in points],
        "closed": closed, "layer": layer,
        "lineweight": lineweight, "colorIndex": None,
    })
    if track and points:
        # Queda como huella para que place_labels no escriba encima.
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        space.track(min(xs), min(ys), max(xs), max(ys), track)
    return result["handle"]


def _line(p0: Point, p1: Point, layer: str, lineweight: int,
          color_index: Optional[int] = None) -> str:
    result = acad.call("create_line", {
        "x1": p0[0], "y1": p0[1], "z1": 0.0,
        "x2": p1[0], "y2": p1[1], "z2": 0.0,
        "layer": layer, "lineweight": lineweight, "colorIndex": color_index,
    })
    return result["handle"]


def _arc(center: Point, radius: float, start_deg: float, end_deg: float,
         layer: str, lineweight: int) -> str:
    result = acad.call("create_arc", {
        "x": center[0], "y": center[1], "z": 0.0, "radius": radius,
        "startAngleDeg": start_deg, "endAngleDeg": end_deg,
        "layer": layer, "lineweight": lineweight, "colorIndex": None,
    })
    return result["handle"]


def _ensure_layer(name: str, color: int, lineweight: int,
                  linetype: Optional[str] = None) -> None:
    # Solo si no existe: ver layers.py.
    layers.ensure(name, color, lineweight, linetype)
    layers.ensure_text_style()


# ----------------------------------------------------------------- muros

def _wall_segment(axis: Axis, d_start: float, d_end: float, half: float,
                  layer: str, lineweight: int) -> Optional[str]:
    """Un tramo de muro entre dos distancias, como contorno cerrado."""
    if d_end - d_start < 1e-9:
        return None
    left = axis.vertices_between(d_start, d_end, half)
    right = axis.vertices_between(d_start, d_end, -half)
    return _polyline(left + list(reversed(right)), layer, lineweight,
                     closed=True, track=f"muro {layer}")


# Tramo de muro por debajo del cual no hay mamposteria posible: queda un
# machon suelto que en obra no se levanta y en el plano se ve como un
# rectangulito flotando al lado de una puerta. 0.40 es el minimo
# con el que vale la pena levantar mamposteria.
MIN_TRAMO = 0.40


def create_walls(
    points: list[list[float]],
    thickness: float = 0.15,
    closed: bool = False,
    openings: Optional[list[dict[str, Any]]] = None,
    layer: str = LAYER_WALLS,
    lineweight: int = LW_WALL,
    draw_symbols: bool = True,
    min_segment: float = MIN_TRAMO,
) -> dict[str, Any]:
    """Muros de espesor real a lo largo de un eje, con sus huecos."""
    if thickness <= 0:
        raise ValueError("thickness tiene que ser > 0.")

    axis = Axis([(p[0], p[1]) for p in points], closed=closed)
    half = thickness / 2.0
    total = axis.total_length

    _ensure_layer(layer, 7, lineweight)

    holes = []
    for o in (openings or []):
        width = float(o["width"])
        distance = float(o["distance"])
        if width <= 0:
            raise ValueError("El ancho de un hueco tiene que ser > 0.")
        start = distance - width / 2.0 if o.get("centered", True) else distance
        end = start + width
        if start < -1e-9 or end > total + 1e-9:
            raise ValueError(
                f"El hueco en {distance} (ancho {width}) se sale del muro, "
                f"que mide {total:g}. Recordá que 'distance' se mide a lo largo "
                f"del eje desde el arranque."
            )
        holes.append({**o, "start": max(0.0, start), "end": min(total, end)})
    holes.sort(key=lambda h: h["start"])

    for a, b in zip(holes, holes[1:]):
        if b["start"] < a["end"] - 1e-9:
            raise ValueError(
                f"Dos huecos se pisan: uno termina en {a['end']:g} y el "
                f"siguiente arranca en {b['start']:g}."
            )

    wall_handles: list[str] = []

    if not holes:
        if closed:
            # Sin huecos, un muro cerrado son dos anillos: exterior e interior.
            wall_handles.append(_polyline(axis.offset_vertices(half), layer,
                                          lineweight, closed=True))
            wall_handles.append(_polyline(axis.offset_vertices(-half), layer,
                                          lineweight, closed=True))
        else:
            handle = _wall_segment(axis, 0.0, total, half, layer, lineweight)
            if handle:
                wall_handles.append(handle)
    else:
        cuts = [(0.0, holes[0]["start"])]
        for a, b in zip(holes, holes[1:]):
            cuts.append((a["end"], b["start"]))
        cuts.append((holes[-1]["end"], total))

        if closed and len(cuts) > 1:
            # En un muro cerrado, el último tramo y el primero son el mismo:
            # se unen dando la vuelta por el punto de arranque, si no quedaría
            # una junta falsa ahí.
            first_start, first_end = cuts[0]
            last_start, last_end = cuts[-1]
            merged_left = (axis.vertices_between(last_start, last_end, half)
                           + axis.vertices_between(first_start, first_end, half)[1:])
            merged_right = (axis.vertices_between(last_start, last_end, -half)
                            + axis.vertices_between(first_start, first_end, -half)[1:])
            if len(merged_left) > 1:
                wall_handles.append(_polyline(
                    merged_left + list(reversed(merged_right)),
                    layer, lineweight, closed=True))
            cuts = cuts[1:-1]

        for d0, d1 in cuts:
            handle = _wall_segment(axis, d0, d1, half, layer, lineweight)
            if handle:
                wall_handles.append(handle)

    # Tramos que quedaron demasiado cortos para construirse.
    machones = []
    if holes:
        limites = [(0.0, holes[0]["start"])]
        for a, b in zip(holes, holes[1:]):
            limites.append((a["end"], b["start"]))
        limites.append((holes[-1]["end"], total))
        for d0, d1 in limites:
            largo = d1 - d0
            if 1e-6 < largo < min_segment:
                machones.append({"from": round(d0, 3), "to": round(d1, 3),
                                 "length": round(largo, 3)})

    opening_handles: list[dict[str, Any]] = []
    if draw_symbols and holes:
        # Solo si algun hueco dibuja algo. Un vano 'pass' no tiene simbolo, y
        # crear la capa igual dejaba una PUERTAS-VENTANAS vacia en planos donde
        # no hay ni puertas ni ventanas -una cimentacion, por ejemplo, donde
        # los "huecos" son el paso del dado por la trabe de liga.
        con_simbolo = [h for h in holes
                       if str(h.get("type", "door")).lower()
                       not in ("pass", "vano", "opening")]
        if con_simbolo:
            _ensure_layer(LAYER_OPENINGS, 7, LW_OPENING)
        for hole in holes:
            opening_handles.append(_draw_opening(axis, hole, thickness))

    resultado = {
        "wallHandles": wall_handles,
        "openings": opening_handles,
        "axisLength": total,
        "thickness": thickness,
    }
    if machones:
        # No se falla: el muro se dibuja igual. Pero hay que decirlo, porque un
        # machon de 30 cm entre la esquina y una puerta no es un detalle de
        # dibujo, es un problema de proyecto.
        resultado["shortSegments"] = machones
        resultado["warning"] = (
            f"{len(machones)} tramo(s) de muro por debajo de {min_segment} m: "
            + ", ".join(f"{m['length']:.2f} m entre {m['from']:.2f} y {m['to']:.2f}"
                        for m in machones)
            + ". Corre el hueco o llevalo hasta la esquina.")
    return resultado


def _draw_opening(axis: Axis, hole: dict[str, Any],
                  thickness: float) -> dict[str, Any]:
    """Símbolo de puerta (hoja + abatimiento) o ventana (vidrio) en un hueco."""
    kind = str(hole.get("type", "door")).lower()
    d0, d1 = hole["start"], hole["end"]
    width = d1 - d0
    half = thickness / 2.0

    i, _ = axis.segment_at((d0 + d1) / 2.0)
    u = axis.dirs[i]
    angle = math.degrees(math.atan2(u[1], u[0]))

    result: dict[str, Any] = {"type": kind, "width": width,
                              "distance": (d0 + d1) / 2.0}

    if kind == "window":
        # Vidrio: dos líneas paralelas al muro cruzando el hueco.
        for off in (thickness / 6.0, -thickness / 6.0):
            _line(axis.offset_point_at(d0, off), axis.offset_point_at(d1, off),
                  LAYER_OPENINGS, LW_OPENING)
        result["handles"] = "vidrio"
        return result

    if kind in ("pass", "vano", "opening"):
        return result  # hueco limpio, sin símbolo

    # Puerta: la hoja cuelga de una jamba y abre 90° hacia un lado.
    hinge_at_start = str(hole.get("swing", "left")).lower() in ("left", "izq", "izquierda")
    side = 1.0 if str(hole.get("side", "left")).lower() in ("left", "izq", "izquierda") else -1.0

    hinge_d = d0 if hinge_at_start else d1
    hinge = axis.offset_point_at(hinge_d, 0.0)

    # La hoja abierta: perpendicular al muro, hacia el lado elegido.
    leaf_angle = angle + 90.0 * side
    leaf_end = (hinge[0] + width * math.cos(math.radians(leaf_angle)),
                hinge[1] + width * math.sin(math.radians(leaf_angle)))
    leaf = _line(hinge, leaf_end, LAYER_OPENINGS, LW_OPENING)

    # El barrido va entre la hoja abierta y la hoja cerrada (que apunta a lo
    # largo del muro, hacia el otro lado del hueco). Los arcos de AutoCAD van
    # SIEMPRE antihorario de start a end, asi que hay que elegir el orden que
    # da el arco chico: al reves barre 270 en vez de 90.
    along = angle if hinge_at_start else angle + 180.0
    if (leaf_angle - along) % 360.0 <= 180.0:
        start_deg, end_deg = along, leaf_angle
    else:
        start_deg, end_deg = leaf_angle, along
    arc = _arc(hinge, width, start_deg % 360.0, end_deg % 360.0,
               LAYER_OPENINGS, LW_OPENING)

    result["leafHandle"] = leaf
    result["arcHandle"] = arc
    return result


# ------------------------------------------------------------------ ejes

MIN_SEPARACION_EJES = 1.20

# Aire entre la burbuja y lo que ya estaba al margen, en mm de papel.
GRID_GAP_MM = 2.0


def _agrupar_ejes(posiciones: list[float], minimo: float) -> tuple[list[float], list[dict]]:
    """Junta ejes demasiado proximos en uno solo.

    Dos ejes a 0.65 m producen dos burbujas que se pisan y cotas ilegibles. En
    obra esos dos muros se replantean desde un mismo eje y la separacion va
    como cota de detalle, no como eje propio.
    """
    if not posiciones:
        return [], []
    orden = sorted(posiciones)
    grupos = [[orden[0]]]
    for p in orden[1:]:
        if p - grupos[-1][-1] < minimo:
            grupos[-1].append(p)
        else:
            grupos.append([p])

    finales, fusionados = [], []
    for g in grupos:
        finales.append(sum(g) / len(g))
        if len(g) > 1:
            fusionados.append({"merged": [round(v, 3) for v in g],
                               "at": round(sum(g) / len(g), 3),
                               "spread": round(g[-1] - g[0], 3)})
    return finales, fusionados


def create_axis_grid(
    x_positions: Optional[list[float]] = None,
    y_positions: Optional[list[float]] = None,
    x_min: float = 0.0, y_min: float = 0.0,
    x_max: float = 0.0, y_max: float = 0.0,
    extension: float = 0.0,
    bubble_radius: float = 0.0,
    text_height: float = 0.0,
    layer: str = LAYER_GRID,
    min_spacing: float = MIN_SEPARACION_EJES,
    x_labels: str = "numbers",
    y_labels: str = "letters",
) -> dict[str, Any]:
    """Ejes estructurales con globos: por defecto verticales 1,2,3 y horizontales A,B,C.

    x_labels / y_labels: 'numbers' o 'letters'. La convencion no es universal
    -en mucho plano estructural las letras van en los ejes verticales y los
    numeros en los horizontales-, y el nombre de cada interseccion (B-2, A-1)
    sale de ahi, asi que tiene que poder elegirse.
    """
    if not (x_positions or y_positions):
        raise ValueError("Hay que pasar x_positions y/o y_positions.")
    for nombre, modo in (("x_labels", x_labels), ("y_labels", y_labels)):
        if modo not in ("numbers", "letters"):
            raise ValueError(
                f"{nombre} tiene que ser 'numbers' o 'letters', no {modo!r}.")
    xs, fus_x = _agrupar_ejes(list(x_positions or []), min_spacing)
    ys, fus_y = _agrupar_ejes(list(y_positions or []), min_spacing)

    # Extensión del dibujo, para saber hasta dónde llegan los ejes.
    left = min(xs) if xs else x_min
    right = max(xs) if xs else x_max
    bottom = min(ys) if ys else y_min
    top = max(ys) if ys else y_max
    if x_min or x_max:
        left, right = min(left, x_min), max(right, x_max)
    if y_min or y_max:
        bottom, top = min(bottom, y_min), max(top, y_max)

    span = max(right - left, top - bottom, 1e-6)
    ext = extension or span * 0.08
    radius = bubble_radius or span * 0.025
    height = text_height or radius * 1.1

    aire = space.paper(GRID_GAP_MM)
    # Piso a la extension: con el eje mas corto que el radio, la burbuja del
    # eje 1 y la del eje A se juntan en la esquina, porque las dos salen del
    # mismo vertice en direcciones perpendiculares.
    ext = max(ext, radius + aire)

    # La burbuja tampoco puede caer encima de lo que ya haya al margen del
    # dibujo. Si se acoto antes (lo recomendable), el eje se estira hasta
    # pasar las cadenas de cota y el globo sale afuera, que es como se dibuja
    # de verdad: la linea de eje CRUZA las cotas, la burbuja no.
    if not extension:
        lados = []
        if xs:
            a0, a1 = xs[0] - radius, xs[-1] + radius
            lados.append(space.free_offset("bottom", bottom, a0, a1,
                                           2 * radius, aire, start=ext))
            lados.append(space.free_offset("top", top, a0, a1,
                                           2 * radius, aire, start=ext))
        if ys:
            a0, a1 = ys[0] - radius, ys[-1] + radius
            lados.append(space.free_offset("left", left, a0, a1,
                                           2 * radius, aire, start=ext))
            lados.append(space.free_offset("right", right, a0, a1,
                                           2 * radius, aire, start=ext))
        # Un solo ext para los cuatro lados: burbujas a distinta distancia
        # segun el lado se leen como un error de dibujo.
        ext = max(lados) if lados else ext

    _ensure_layer(layer, GRID_COLOR, LW_GRID, GRID_LINETYPE)

    bubbles: list[dict[str, Any]] = []
    handles: list[str] = []

    def bubble(center: Point, label: str) -> None:
        handles.append(acad.call("create_circle", {
            "x": center[0], "y": center[1], "z": 0.0, "radius": radius,
            "layer": layer, "lineweight": LW_GRID, "colorIndex": None,
        })["handle"])
        # DBText se ancla abajo a la izquierda: corremos el texto para que
        # quede ópticamente centrado en el globo.
        handles.append(acad.call("create_text", {
            "text": label,
            "x": center[0] - height * 0.3 * len(label),
            "y": center[1] - height * 0.5,
            "z": 0.0, "height": height, "layer": layer,
            "rotationDeg": 0.0, "lineweight": LW_GRID, "colorIndex": None,
        })["handle"])
        bubbles.append({"label": label, "x": center[0], "y": center[1]})

    etiquetas_x = [_rotulo(i, x_labels) for i in range(len(xs))]
    etiquetas_y = [_rotulo(i, y_labels) for i in range(len(ys))]

    for label, x in zip(etiquetas_x, xs):
        handles.append(_line((x, bottom - ext), (x, top + ext), layer,
                             LW_GRID, GRID_COLOR))
        bubble((x, top + ext + radius), label)
        bubble((x, bottom - ext - radius), label)

    for label, y in zip(etiquetas_y, ys):
        handles.append(_line((left - ext, y), (right + ext, y), layer,
                             LW_GRID, GRID_COLOR))
        bubble((left - ext - radius, y), label)
        bubble((right + ext + radius, y), label)

    # Queda tomado el anillo de las burbujas, para que una cadena de cotas
    # posterior se apile por afuera en vez de encimarse.
    if xs:
        a0, a1 = xs[0] - radius, xs[-1] + radius
        for lado, ref in (("bottom", bottom), ("top", top)):
            space.reserve(*space.band_box(lado, ref, ext, 2 * radius, a0, a1),
                          what="burbujas de eje " + lado)
    if ys:
        a0, a1 = ys[0] - radius, ys[-1] + radius
        for lado, ref in (("left", left), ("right", right)):
            space.reserve(*space.band_box(lado, ref, ext, 2 * radius, a0, a1),
                          what="burbujas de eje " + lado)

    resultado_extra = {}
    if fus_x or fus_y:
        resultado_extra["mergedAxes"] = {"x": fus_x, "y": fus_y}
        detalle = "; ".join(
            f"{f['merged']} -> {f['at']} (separacion {f['spread']} m)"
            for f in fus_x + fus_y)
        resultado_extra["warning"] = (
            f"Ejes a menos de {min_spacing} m fusionados para que las burbujas "
            f"no se pisen: {detalle}. Acota esa separacion como cota de detalle.")

    return {
        **resultado_extra,
        "verticalAxes": etiquetas_x,
        "horizontalAxes": etiquetas_y,
        "bubbles": bubbles,
        "handles": handles,
        "bubbleRadius": radius,
        "extension": ext,
    }


def _rotulo(index: int, modo: str) -> str:
    return str(index + 1) if modo == "numbers" else _letter(index)


def _letter(index: int) -> str:
    """0->A, 25->Z, 26->AA. Los ejes rara vez pasan de Z, pero no cuesta."""
    label = ""
    index += 1
    while index > 0:
        index, rem = divmod(index - 1, 26)
        label = chr(ord("A") + rem) + label
    return label


# ------------------------------------------------------------- escaleras

LAYER_STAIRS = "ESCALERAS"
LW_STAIRS = 30       # contorno visto: escalones, zanca (25-35 de la tabla)
LW_STAIRS_AUX = 18   # baranda, flecha de sentido, niveles (13-18 de la tabla)

# Regla de Blondel: 2 contrahuellas + 1 huella tiene que caer en este rango
# para que el paso sea cómodo -ni se acorta (escalera parada, insegura) ni se
# alarga de más (escalera tendida, cansadora). Referencia universal de diseño
# de escaleras, no un criterio propio de esta tool.
BLONDEL_MIN = 0.60
BLONDEL_MAX = 0.64

RISER_MIN = 0.13   # por debajo, deja de sentirse como escalón
RISER_MAX = 0.20   # por encima, incómodo/inseguro en uso residencial
TREAD_MIN = 0.24   # por debajo, no entra el pie apoyado


def _bbox(points: list[Point]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _arrowhead(tip: Point, dirv: Point, size: float, layer: str,
              lineweight: int) -> list[str]:
    """Punta de flecha SÓLIDA (triángulo relleno) con el vértice en 'tip',
    apuntando en la dirección 'dirv'. Mismo lenguaje visual que ya usa
    create_flow_arrow para el sentido de escurrimiento en obra vial."""
    perp = (-dirv[1], dirv[0])
    back = (tip[0] - dirv[0] * size, tip[1] - dirv[1] * size)
    p1 = (back[0] + perp[0] * size * 0.4, back[1] + perp[1] * size * 0.4)
    p2 = (back[0] - perp[0] * size * 0.4, back[1] - perp[1] * size * 0.4)
    tri = _polyline([tip, p1, p2], layer, lineweight, closed=True)
    fill = acad.call("create_hatch", {
        "boundaryHandle": tri, "pattern": "SOLID", "scale": 1.0,
        "angleDeg": 0.0, "layer": layer, "lineweight": lineweight,
        "colorIndex": None,
    })
    return [tri, fill["handle"]]


def create_stairs(
    start_x: float, start_y: float,
    total_rise: float,
    width: float = 1.00,
    tread: float = 0.28,
    riser: float = 0.17,
    direction_deg: float = 90.0,
    view: str = "planta",
    handrail: bool = True,
    handrail_offset: float = 0.05,
    bottom_level_label: str = "N.P.T. +0.00",
    top_level_label: Optional[str] = None,
    layer: str = LAYER_STAIRS,
    lineweight: int = LW_STAIRS,
) -> dict[str, Any]:
    """Escalera de un tramo recto, en planta o en corte, con la cantidad de
    escalones resuelta por la fórmula de Blondel -no a ojo, no copiada de
    otro plano.

    view='planta': el contorno del tramo (dos zancas), cada huella, la
    baranda opcional y la flecha de sentido con el rótulo "SUBE" -para eso
    hay que rotular el resultado con place_labels, esta tool deja el punto
    en 'upArrowTip'.
    view='corte': el perfil en zigzag (contrahuella + huella de cada
    escalón) más los niveles de piso terminado, abajo y arriba.

    La cantidad de escalones sale de dividir 'total_rise' por 'riser'
    (redondeado al entero más cercano) y RECALCULAR la contrahuella real
    para que el reparto sea exacto -17 pasos de 16.47cm, no 16 de 17cm y uno
    suelto de 8cm-. Se valida contra la regla de Blondel (2×contrahuella +
    huella entre 0.60 y 0.64m): si no cumple, se avisa con qué huella sí
    cumple en vez de dibujar una escalera incómoda o insegura. 'tread' y la
    contrahuella real resultante también se validan contra los mínimos de
    uso (contrahuella 0.13-0.20m, huella >= 0.24m).

    No arma tramos con descanso (en L o en U): un solo tramo recto de
    start_x,start_y en la dirección 'direction_deg'. Para una escalera que
    dobla, son dos llamadas -una por tramo- con el descanso dibujado aparte."""
    if total_rise <= 0:
        raise ValueError("total_rise tiene que ser > 0.")
    if width <= 0:
        raise ValueError("width tiene que ser > 0.")
    if tread <= 0 or riser <= 0:
        raise ValueError("tread y riser tienen que ser > 0.")
    if tread < TREAD_MIN - 1e-6:
        raise ValueError(
            f"tread={tread:g} es menor que el mínimo usable "
            f"({TREAD_MIN:g}m): no entra el pie apoyado en el escalón.")
    if view not in ("planta", "corte"):
        raise ValueError(f"view tiene que ser 'planta' o 'corte', no {view!r}.")

    n_risers = max(round(total_rise / riser), 1)
    if n_risers < 2:
        raise ValueError(
            f"total_rise={total_rise:g} con riser={riser:g} da {n_risers} "
            "escalón(es): muy poco para una escalera, revisá las unidades.")
    riser_real = total_rise / n_risers
    n_treads = n_risers - 1
    total_run = n_treads * tread

    if not (RISER_MIN - 1e-6 <= riser_real <= RISER_MAX + 1e-6):
        raise ValueError(
            f"La contrahuella real da {riser_real * 100:.1f}cm ({n_risers} "
            f"escalones para salvar {total_rise:g}m) -fuera del rango usable "
            f"{RISER_MIN * 100:.0f}-{RISER_MAX * 100:.0f}cm. Ajustá 'riser' "
            "para que total_rise/riser dé una cantidad de escalones distinta.")

    blondel = 2 * riser_real + tread
    if not (BLONDEL_MIN - 1e-6 <= blondel <= BLONDEL_MAX + 1e-6):
        tread_sugerido = (BLONDEL_MIN + BLONDEL_MAX) / 2.0 - 2 * riser_real
        raise ValueError(
            f"2×contrahuella + huella = {blondel * 100:.1f}cm, fuera de la "
            f"regla de Blondel ({BLONDEL_MIN * 100:.0f}-{BLONDEL_MAX * 100:.0f}cm "
            f"cómodo). Con contrahuella={riser_real * 100:.1f}cm probá una "
            f"huella cerca de {tread_sugerido * 100:.1f}cm.")

    _ensure_layer(layer, 7, lineweight)

    ang = math.radians(direction_deg)
    dirv = (math.cos(ang), math.sin(ang))
    perp = (-dirv[1], dirv[0])

    def along(d: float, off: float = 0.0) -> Point:
        return (start_x + dirv[0] * d + perp[0] * off,
                start_y + dirv[1] * d + perp[1] * off)

    handles: list[str] = []
    half = width / 2.0
    formula = (f"{n_risers} CH x {riser_real * 100:.1f}cm = {total_rise:.2f}m ; "
              f"{n_treads} H x {tread * 100:.0f}cm = {total_run:.2f}m")

    if view == "planta":
        handles.append(_line(along(0, half), along(total_run, half), layer, lineweight))
        handles.append(_line(along(0, -half), along(total_run, -half), layer, lineweight))
        for i in range(n_treads + 1):
            d = i * tread
            handles.append(_line(along(d, half), along(d, -half), layer, lineweight))

        space.track(*_bbox([along(0, half), along(0, -half),
                            along(total_run, half), along(total_run, -half)]),
                    "escalera")

        if handrail:
            r_off = half - handrail_offset
            handles.append(_line(along(0, r_off), along(total_run, r_off),
                                 layer, LW_STAIRS_AUX))

        arrow_tail = along(total_run * 0.20)
        arrow_tip = along(total_run * 0.75)
        handles.append(_line(arrow_tail, arrow_tip, layer, LW_STAIRS_AUX))
        handles.extend(_arrowhead(arrow_tip, dirv, width * 0.12, layer, LW_STAIRS_AUX))

        extra = {"upArrowTip": arrow_tip, "upArrowTail": arrow_tail,
                 "startEdge": [along(0, half), along(0, -half)],
                 "endEdge": [along(total_run, half), along(total_run, -half)]}
    else:
        pts: list[Point] = [(start_x, start_y)]
        x, y = start_x, start_y
        for i in range(n_risers):
            y += riser_real
            pts.append((x, y))
            if i < n_treads:
                x += tread
                pts.append((x, y))
        handles.append(_polyline(pts, layer, lineweight, closed=False,
                                 track="escalera (corte)"))

        margin = tread * 1.5
        top_y = start_y + total_rise
        handles.append(_line((start_x - margin, start_y),
                             (start_x + total_run + margin, start_y),
                             layer, LW_STAIRS_AUX))
        handles.append(_line((start_x - margin, top_y),
                             (start_x + total_run + margin, top_y),
                             layer, LW_STAIRS_AUX))

        extra = {
            "bottomLevel": {"x": start_x, "y": start_y, "label": bottom_level_label},
            "topLevel": {"x": start_x + total_run, "y": top_y,
                        "label": top_level_label or f"N.P.T. +{total_rise:.2f}"},
            "profile": pts,
        }

    return {
        "handles": handles,
        "view": view,
        "steps": n_risers,
        "treads": n_treads,
        "riser": round(riser_real, 4),
        "tread": tread,
        "totalRun": round(total_run, 4),
        "totalRise": total_rise,
        "blondel": round(blondel, 4),
        "formula": formula,
        **extra,
    }
