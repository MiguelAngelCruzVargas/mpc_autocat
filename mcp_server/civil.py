"""Obra civil lineal: calles, banquetas, guarniciones.

Una calle es un eje con anchos a los lados: calzada, guarnición, banqueta. Todo
sale del mismo offset paralelo que usan los muros (geom.py), así que las curvas
y los quiebres cierran igual de bien.

Unidades: las del modelo (metros si dibujás en metros).
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad
from geom import Axis, Point

LAYER_AXIS = "EJE-CALLE"
LAYER_PAVEMENT = "PAVIMENTO"
LAYER_CURB = "GUARNICION"
LAYER_SIDEWALK = "BANQUETA"

LW_AXIS = 13
LW_PAVEMENT = 35
LW_CURB = 50
LW_SIDEWALK = 25

AXIS_LINETYPE = "CENTER"
AXIS_COLOR = 1


def _ensure(name: str, color: int, lineweight: int,
            linetype: Optional[str] = None) -> None:
    acad.call("set_layer", {"name": name, "colorIndex": color,
                            "linetype": linetype,
                            "lineweightHundredthsMm": lineweight})


def _interp_width(widths: list[list[float]], d: float) -> float:
    """Ancho en una distancia dada, interpolando entre los puntos de control.

    widths es [[distancia, ancho], ...] ordenado. Antes del primer punto vale
    el primer ancho y despues del ultimo, el ultimo: una calle que se angosta
    no tiene por que tener control en cada vertice.
    """
    if d <= widths[0][0]:
        return widths[0][1]
    if d >= widths[-1][0]:
        return widths[-1][1]
    for (d0, w0), (d1, w1) in zip(widths, widths[1:]):
        if d0 <= d <= d1:
            if d1 - d0 < 1e-9:
                return w1
            t = (d - d0) / (d1 - d0)
            return w0 + (w1 - w0) * t
    return widths[-1][1]


def _variable_edge(axis: Axis, widths: list[list[float]], factor: float,
                   samples: int) -> list[Point]:
    """Borde a una fraccion del ancho variable, muestreando a lo largo del eje.

    Con ancho constante alcanza el offset con inglete; con ancho variable hay
    que ir punto por punto, porque la distancia al eje cambia en el camino.
    """
    total = axis.total_length
    pts: list[Point] = []
    for i in range(samples + 1):
        d = total * i / samples
        pts.append(axis.offset_point_at(d, _interp_width(widths, d) * factor))
    return pts


def _edge_between(axis: Axis, d0: float, d1: float,
                  widths: Optional[list[list[float]]], factor: float,
                  extra: float, samples: int = 0) -> list[Point]:
    """Borde paralelo al eje entre dos distancias, con ancho constante o variable."""
    n = samples or max(8, int(abs(d1 - d0) / 2.0) + 8)
    pts: list[Point] = []
    for i in range(n + 1):
        d = d0 + (d1 - d0) * i / n
        w = _interp_width(widths, d) if widths else 0.0
        pts.append(axis.offset_point_at(d, w * factor + extra))
    return pts


def _curb_segment(axis: Axis, d0: float, d1: float, side: str,
                  curb_width: float, widths: Optional[list[list[float]]],
                  half: float, layer: str) -> Optional[str]:
    """Un tramo de guarnicion de un solo lado, entre dos cadenamientos."""
    if d1 - d0 < 1e-6:
        return None
    signo = 1.0 if side == "left" else -1.0
    factor = 0.5 * signo

    if widths:
        interior = _edge_between(axis, d0, d1, widths, factor, 0.0)
        exterior = _edge_between(axis, d0, d1, widths, factor, curb_width * signo)
    else:
        base = half * signo
        interior = _edge_between(axis, d0, d1, None, 0.0, base)
        exterior = _edge_between(axis, d0, d1, None, 0.0,
                                 base + curb_width * signo)

    pts = interior + list(reversed(exterior))
    return acad.call("create_polyline", {
        "points": [[p[0], p[1]] for p in pts], "bulges": None,
        "closed": True, "layer": layer,
        "lineweight": LW_CURB, "colorIndex": None,
    })["handle"]


def _band(axis: Axis, inner: float, outer: float, layer: str,
          lineweight: int, closed_axis: bool,
          pattern: Optional[str] = None, scale: float = 1.0,
          color: Optional[int] = None,
          widths: Optional[list[list[float]]] = None,
          inner_factor: float = 0.0, outer_factor: float = 0.0,
          extra_inner: float = 0.0, extra_outer: float = 0.0,
          samples: int = 0) -> str:
    """Franja paralela al eje entre dos distancias (con signo: + es izquierda).

    Con `widths` la franja sigue un ancho variable: inner/outer_factor son la
    fraccion del ancho (0.5 = borde de calzada) y extra_* una distancia fija
    que se suma por fuera (para la guarnicion).
    """
    if widths:
        n = samples or max(24, len(axis.points) * 8)
        a = [(p[0] + 0.0, p[1]) for p in _variable_edge(axis, widths, inner_factor, n)]
        b = [(p[0] + 0.0, p[1]) for p in _variable_edge(axis, widths, outer_factor, n)]
        if extra_inner or extra_outer:
            total = axis.total_length
            a = [axis.offset_point_at(
                    total * i / n,
                    _interp_width(widths, total * i / n) * inner_factor + extra_inner)
                 for i in range(n + 1)]
            b = [axis.offset_point_at(
                    total * i / n,
                    _interp_width(widths, total * i / n) * outer_factor + extra_outer)
                 for i in range(n + 1)]
    else:
        a = axis.offset_vertices(inner)
        b = axis.offset_vertices(outer)
    pts = a + list(reversed(b))

    handle = acad.call("create_polyline", {
        "points": [[p[0], p[1]] for p in pts],
        "closed": True, "layer": layer,
        "lineweight": lineweight, "colorIndex": color,
    })["handle"]

    if pattern:
        try:
            acad.call("create_hatch", {
                "boundaryHandle": handle, "pattern": pattern, "scale": scale,
                "angleDeg": 0.0, "layer": layer,
                "lineweight": 9, "colorIndex": color,
            })
        except acad.AutoCadError:
            pass   # un patrón inexistente no debe tumbar el trazo
    return handle


def _densify(points: list[list[float]], bulges: list[float],
             per_arc: int = 24) -> list[list[float]]:
    """Convierte una polilinea con arcos en una poligonal fina.

    Los offsets paralelos trabajan sobre segmentos rectos, asi que un arco hay
    que muestrearlo: con pocos puntos la guarnicion de una curva sale poligonal
    y se nota.
    """
    out: list[list[float]] = []
    for i in range(len(points) - 1):
        p0, p1 = points[i], points[i + 1]
        b = bulges[i] if i < len(bulges) else 0.0
        out.append(list(p0))
        if abs(b) < 1e-12:
            continue
        # De bulge a arco: barrido = 4*atan(b), y de ahi centro y radio.
        barrido = 4.0 * math.atan(b)
        cuerda = math.dist(p0, p1)
        if cuerda < 1e-9:
            continue
        radio = cuerda / (2.0 * math.sin(abs(barrido) / 2.0))
        mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
        dx, dy = (p1[0] - p0[0]) / cuerda, (p1[1] - p0[1]) / cuerda
        h = math.sqrt(max(radio * radio - (cuerda / 2.0) ** 2, 0.0))
        signo = 1.0 if barrido > 0 else -1.0
        cx, cy = mx - dy * h * signo, my + dx * h * signo
        a0 = math.atan2(p0[1] - cy, p0[0] - cx)
        for k in range(1, per_arc):
            a = a0 + barrido * k / per_arc
            out.append([cx + radio * math.cos(a), cy + radio * math.sin(a)])
    out.append(list(points[-1]))
    return out


def create_road(
    points: list[list[float]],
    width: float = 7.00,
    widths: Optional[list[list[float]]] = None,
    bulges: Optional[list[float]] = None,
    curb_width: float = 0.40,
    curb_segments: Optional[list[dict[str, Any]]] = None,
    sidewalk_width: float = 0.0,
    closed: bool = False,
    draw_axis: bool = True,
    pavement_pattern: Optional[str] = None,
    pavement_scale: float = 1.0,
    axis_layer: str = LAYER_AXIS,
    pavement_layer: str = LAYER_PAVEMENT,
    curb_layer: str = LAYER_CURB,
    sidewalk_layer: str = LAYER_SIDEWALK,
) -> dict[str, Any]:
    """Calle en planta a partir de su eje: calzada, guarniciones y banquetas.

    points: el eje por donde pasa el CENTRO de la calzada.
    width: ancho total de calzada (de guarnición a guarnición).
    curb_width: ancho de la guarnición, a cada lado, por fuera de la calzada.
    sidewalk_width: ancho de banqueta por fuera de la guarnición; 0 la omite.

    Devuelve el largo del eje, que es el dato con el que se cuantifica la obra
    (metros lineales de guarnición, metros cuadrados de pavimento).
    """
    if widths:
        widths = [[float(d), float(w)] for d, w in widths]
        widths.sort(key=lambda dw: dw[0])
        if any(w <= 0 for _, w in widths):
            raise ValueError("Todos los anchos de 'widths' tienen que ser > 0.")
    elif width <= 0:
        raise ValueError("width tiene que ser > 0.")
    if curb_width < 0 or sidewalk_width < 0:
        raise ValueError("Los anchos no pueden ser negativos.")

    eje_dibujo = points
    if bulges and any(abs(b) > 1e-12 for b in bulges):
        points = _densify(points, bulges)

    axis = Axis([(p[0], p[1]) for p in points], closed=closed)
    half = width / 2.0
    result: dict[str, Any] = {}

    # --- Calzada ---
    _ensure(pavement_layer, 8, LW_PAVEMENT)
    result["pavementHandle"] = _band(
        axis, -half, half, pavement_layer, LW_PAVEMENT, closed,
        pavement_pattern, pavement_scale,
        widths=widths, inner_factor=-0.5, outer_factor=0.5)

    # --- Guarniciones ---
    # Por defecto van completas de los dos lados; con curb_segments se indica
    # que tramo lleva de que lado, que es lo normal cuando de un lado hay un
    # predio, un talud o una obra existente. Sin esto los metros lineales del
    # resumen salen siempre 2 x largo, y no es lo que se construye.
    ml_guarnicion = 0.0
    if curb_width > 0:
        _ensure(curb_layer, 4, LW_CURB)
        largo_eje = axis.total_length

        if curb_segments:
            handles = []
            for i, seg in enumerate(curb_segments, start=1):
                lado = str(seg.get("side", "both")).lower()
                if lado in ("both", "ambos"):
                    lados = ["left", "right"]
                elif lado in ("left", "izq", "izquierda"):
                    lados = ["left"]
                elif lado in ("right", "der", "derecha"):
                    lados = ["right"]
                else:
                    raise ValueError(
                        f"Tramo de guarnicion #{i}: 'side' invalido ({lado!r}). "
                        "Usa 'left', 'right' o 'both'.")

                d0 = float(seg.get("from", 0.0))
                d1 = float(seg.get("to", largo_eje))
                if d1 <= d0:
                    raise ValueError(
                        f"Tramo de guarnicion #{i}: 'to' ({d1}) tiene que ser "
                        f"mayor que 'from' ({d0}).")
                if d0 < -1e-6 or d1 > largo_eje + 1e-6:
                    raise ValueError(
                        f"Tramo de guarnicion #{i}: va de {d0} a {d1} pero el "
                        f"eje mide {largo_eje:.2f} m.")

                for lado in lados:
                    h = _curb_segment(axis, d0, d1, lado, curb_width,
                                      widths, half, curb_layer)
                    if h:
                        handles.append(h)
                    ml_guarnicion += d1 - d0
            result["curbHandles"] = handles
        else:
            result["curbHandles"] = [
                _band(axis, half, half + curb_width, curb_layer, LW_CURB, closed,
                      widths=widths, inner_factor=0.5, outer_factor=0.5,
                      extra_inner=0.0, extra_outer=curb_width),
                _band(axis, -half - curb_width, -half, curb_layer, LW_CURB, closed,
                      widths=widths, inner_factor=-0.5, outer_factor=-0.5,
                      extra_inner=-curb_width, extra_outer=0.0),
            ]
            ml_guarnicion = largo_eje * 2

    # --- Banquetas ---
    if sidewalk_width > 0:
        _ensure(sidewalk_layer, 9, LW_SIDEWALK)
        base = half + curb_width
        result["sidewalkHandles"] = [
            _band(axis, base, base + sidewalk_width, sidewalk_layer,
                  LW_SIDEWALK, closed),
            _band(axis, -base - sidewalk_width, -base, sidewalk_layer,
                  LW_SIDEWALK, closed),
        ]

    # --- Eje, al final para que quede por encima del relleno ---
    if draw_axis:
        _ensure(axis_layer, AXIS_COLOR, LW_AXIS, AXIS_LINETYPE)
        # El eje se dibuja con sus arcos reales, no con la version densificada.
        acad.call("create_polyline", {
            "points": [[p[0], p[1]] for p in eje_dibujo],
            "bulges": bulges,
            "closed": closed, "layer": axis_layer,
            "lineweight": LW_AXIS, "colorIndex": AXIS_COLOR,
        })

    largo = axis.total_length
    if widths:
        # Area con ancho variable: se integra muestreando, no es largo x ancho.
        n = max(48, len(axis.points) * 8)
        area = sum(_interp_width(widths, largo * i / n) for i in range(n + 1))
        area = area / (n + 1) * largo
        ancho_medio = area / largo if largo else 0.0
    else:
        area = largo * width
        ancho_medio = width

    result.update({
        "length": largo,
        "width": ancho_medio,
        "pavementArea": area,
        "curbLength": ml_guarnicion,
        "sidewalkArea": largo * sidewalk_width * 2 if sidewalk_width > 0 else 0.0,
        "totalWidth": ancho_medio + 2 * curb_width + 2 * sidewalk_width,
        "variableWidth": bool(widths),
    })
    return result


def road_edge(points: list[list[float]], offset: float,
              closed: bool = False) -> list[list[float]]:
    """Los vértices de una paralela al eje, sin dibujar nada.

    Sirve para ubicar cosas respecto de la calle —un poste, el arranque de un
    ramal, dónde cae una cota— sin tener que recalcular el offset a mano.
    """
    axis = Axis([(p[0], p[1]) for p in points], closed=closed)
    return [[p[0], p[1]] for p in axis.offset_vertices(offset)]


def point_on_road(points: list[list[float]], distance: float,
                  offset: float = 0.0, closed: bool = False) -> dict[str, Any]:
    """Punto a una distancia dada del arranque del eje, y opcionalmente
    desplazado perpendicularmente. Es cómo se ubica algo por cadenamiento."""
    axis = Axis([(p[0], p[1]) for p in points], closed=closed)
    p = axis.offset_point_at(distance, offset)
    seg, _ = axis.segment_at(distance)
    u = axis.dirs[seg]
    return {"x": p[0], "y": p[1], "dirX": u[0], "dirY": u[1],
            "totalLength": axis.total_length}


# ------------------------------------------------- alineamiento horizontal

def create_alignment(start_x: float, start_y: float, start_bearing_deg: float,
                     elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Eje definido como se PROYECTA una vialidad: tangentes y curvas de radio.

    No hace falta conocer las coordenadas de los vértices: se describe el
    recorrido —"55 m recto, curva de radio 90 girando a la izquierda 68 grados,
    40 m recto"— y el alineamiento calcula la geometría exacta, con arcos
    reales (bulges), no una poligonal aproximada.

    start_bearing_deg: rumbo inicial en grados matemáticos (0 = hacia +X,
    90 = hacia +Y, antihorario).
    elements: en orden, cada uno
      {"type": "tangent", "length": 55}
      {"type": "curve", "radius": 90, "angle_deg": 68, "direction": "left"}
      {"type": "curve", "radius": 90, "length": 107, "direction": "right"}
        (con 'length' el ángulo sale del desarrollo: angulo = largo / radio)

    Devuelve 'points' y 'bulges' listos para create_polyline o create_road, más
    el cadenamiento de cada punto de inflexión (PC = principio de curva,
    PT = principio de tangente) que es lo que se replantea en obra.
    """
    if not elements:
        raise ValueError("El alineamiento necesita al menos un elemento.")

    x, y = float(start_x), float(start_y)
    bearing = math.radians(float(start_bearing_deg))

    points: list[list[float]] = [[x, y]]
    bulges: list[float] = []
    puntos_notables: list[dict[str, Any]] = [
        {"type": "inicio", "station": 0.0, "x": x, "y": y}]
    estacion = 0.0

    for i, el in enumerate(elements, start=1):
        kind = str(el.get("type", "")).lower()

        if kind in ("tangent", "recta", "line"):
            largo = float(el["length"])
            if largo <= 0:
                raise ValueError(f"Elemento #{i}: 'length' tiene que ser > 0.")
            x += largo * math.cos(bearing)
            y += largo * math.sin(bearing)
            bulges.append(0.0)
            points.append([x, y])
            estacion += largo
            puntos_notables.append(
                {"type": "fin de tangente", "station": estacion, "x": x, "y": y})

        elif kind in ("curve", "curva", "arc"):
            radio = float(el["radius"])
            if radio <= 0:
                raise ValueError(f"Elemento #{i}: 'radius' tiene que ser > 0.")

            if el.get("angle_deg") is not None:
                barrido = math.radians(float(el["angle_deg"]))
                largo = radio * barrido
            elif el.get("length") is not None:
                largo = float(el["length"])
                barrido = largo / radio
            else:
                raise ValueError(
                    f"Elemento #{i}: una curva necesita 'angle_deg' o 'length'.")
            if barrido <= 0:
                raise ValueError(f"Elemento #{i}: el barrido tiene que ser > 0.")

            izquierda = str(el.get("direction", "left")).lower() in (
                "left", "izq", "izquierda")
            signo = 1.0 if izquierda else -1.0

            # Centro perpendicular al rumbo actual, del lado del giro.
            cx = x + radio * math.cos(bearing + signo * math.pi / 2)
            cy = y + radio * math.sin(bearing + signo * math.pi / 2)

            # El punto final es el actual rotado alrededor del centro.
            giro = signo * barrido
            dx, dy = x - cx, y - cy
            x = cx + dx * math.cos(giro) - dy * math.sin(giro)
            y = cy + dx * math.sin(giro) + dy * math.cos(giro)

            # El bulge es tan(barrido/4), con el signo del sentido de giro.
            bulges.append(signo * math.tan(barrido / 4.0))
            points.append([x, y])
            bearing += giro
            estacion += largo
            puntos_notables.append({
                "type": "fin de curva", "station": estacion, "x": x, "y": y,
                "radius": radio, "sweepDeg": math.degrees(barrido),
                "developedLength": largo,
                "tangentLength": radio * math.tan(barrido / 2.0),
                "chordLength": 2 * radio * math.sin(barrido / 2.0),
            })

        else:
            raise ValueError(
                f"Elemento #{i}: tipo {kind!r} desconocido. "
                "Usá 'tangent' o 'curve'.")

    bulges.append(0.0)   # el ultimo vertice no arrastra arco

    return {
        "points": points,
        "bulges": bulges,
        "length": estacion,
        "endBearingDeg": math.degrees(bearing) % 360.0,
        "stations": puntos_notables,
    }
