"""Obra civil lineal: calles, banquetas, guarniciones.

Una calle es un eje con anchos a los lados: calzada, guarnición, banqueta. Todo
sale del mismo offset paralelo que usan los muros (geom.py), así que las curvas
y los quiebres cierran igual de bien.

Unidades: las del modelo (metros si dibujás en metros).
"""
from __future__ import annotations

import math
import re
from typing import Any, Optional

import autocad_client as acad
import geom
import layers
import space
from geom import Axis, Point, densify

LAYER_AXIS = "EJE-CALLE"
LAYER_PAVEMENT = "PAVIMENTO"
LAYER_CURB = "GUARNICION"
LAYER_SIDEWALK = "BANQUETA"

LW_AXIS = 13
LW_PAVEMENT = 35
LW_CURB = 50
LW_SIDEWALK = 25

AXIS_LINETYPE = "CENTER"
AXIS_COLOR = layers.COLOR_EJES


def _ensure(name: str, color: int, lineweight: int,
            linetype: Optional[str] = None) -> None:
    # Solo si no existe: una capa ya configurada en el dibujo manda sobre el
    # default de la tool (ver layers.py).
    layers.ensure(name, color, lineweight, linetype)


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
          samples: int = 0, cap_ends: bool = True) -> str:
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
    if not cap_ends:
        # Los dos bordes sueltos, sin la linea transversal que cierra la
        # franja. En un plano de infraestructura el tramo no termina ahi: la
        # calle sigue, y un remate transversal se lee como final de obra.
        # Sin contorno cerrado no hay achurado posible.
        return [acad.call("create_polyline", {
            "points": [[p[0], p[1]] for p in borde],
            "closed": False, "layer": layer,
            "lineweight": lineweight, "colorIndex": color,
        })["handle"] for borde in (a, b)]

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
    return [handle]




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
    cap_ends: bool = True,
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
    cap_ends: cerrar o no los extremos del tramo con la línea transversal. En
    un plano de infraestructura la calle SIGUE más allá del dibujo, así que el
    remate transversal se lee como final de obra; ahí va cap_ends=False y los
    bordes quedan abiertos (o se remata con una matchline). Sin contorno
    cerrado no se puede achurar la calzada.

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
        points = densify(points, bulges)

    axis = Axis([(p[0], p[1]) for p in points], closed=closed)
    half = width / 2.0
    result: dict[str, Any] = {}

    # --- Calzada ---
    _ensure(pavement_layer, layers.COLOR_SECUNDARIO, LW_PAVEMENT)
    if pavement_pattern and not cap_ends:
        raise ValueError(
            "No se puede achurar la calzada con cap_ends=False: el achurado "
            "necesita un contorno cerrado y los bordes quedan abiertos. "
            "Elegí uno de los dos.")
    calzada = _band(
        axis, -half, half, pavement_layer, LW_PAVEMENT, closed,
        pavement_pattern, pavement_scale,
        widths=widths, inner_factor=-0.5, outer_factor=0.5, cap_ends=cap_ends)
    result["pavementHandle"] = calzada[0]
    result["pavementHandles"] = calzada

    # --- Guarniciones ---
    # Por defecto van completas de los dos lados; con curb_segments se indica
    # que tramo lleva de que lado, que es lo normal cuando de un lado hay un
    # predio, un talud o una obra existente. Sin esto los metros lineales del
    # resumen salen siempre 2 x largo, y no es lo que se construye.
    ml_guarnicion = 0.0
    if curb_width > 0:
        _ensure(curb_layer, layers.COLOR_VEGETACION, LW_CURB)
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
            result["curbHandles"] = (
                _band(axis, half, half + curb_width, curb_layer, LW_CURB, closed,
                      widths=widths, inner_factor=0.5, outer_factor=0.5,
                      extra_inner=0.0, extra_outer=curb_width, cap_ends=cap_ends)
                + _band(axis, -half - curb_width, -half, curb_layer, LW_CURB,
                        closed, widths=widths, inner_factor=-0.5,
                        outer_factor=-0.5, extra_inner=-curb_width,
                        extra_outer=0.0, cap_ends=cap_ends))
            ml_guarnicion = largo_eje * 2

    # --- Banquetas ---
    if sidewalk_width > 0:
        _ensure(sidewalk_layer, layers.COLOR_TENUE, LW_SIDEWALK)
        base = half + curb_width
        result["sidewalkHandles"] = (
            _band(axis, base, base + sidewalk_width, sidewalk_layer,
                  LW_SIDEWALK, closed, cap_ends=cap_ends)
            + _band(axis, -base - sidewalk_width, -base, sidewalk_layer,
                    LW_SIDEWALK, closed, cap_ends=cap_ends))

    # --- Eje, al final para que quede por encima del relleno ---
    if draw_axis:
        _ensure(axis_layer, AXIS_COLOR, LW_AXIS, AXIS_LINETYPE)
        # El eje se dibuja con sus arcos reales, no con la version densificada.
        # ByLayer: el color lo manda la capa. Forzarlo por entidad hacia que
        # una capa configurada por el proyecto (VIAL_EJE en amarillo) se viera
        # igual roja, que es justo lo que la nomenclatura propia trata de
        # evitar. AXIS_COLOR queda solo como color con el que se CREA la capa
        # si no existe.
        result["axisHandle"] = acad.call("create_polyline", {
            "points": [[p[0], p[1]] for p in eje_dibujo],
            "bulges": bulges,
            "closed": closed, "layer": axis_layer,
            "lineweight": LW_AXIS, "colorIndex": None,
        })["handle"]

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
              closed: bool = False,
              bulges: Optional[list[float]] = None) -> list[list[float]]:
    """Los vértices de una paralela al eje, sin dibujar nada.

    Sirve para ubicar cosas respecto de la calle —un poste, el arranque de un
    ramal, dónde cae una cota— sin tener que recalcular el offset a mano.
    """
    if bulges and any(abs(b) > 1e-12 for b in bulges):
        points = densify(points, bulges)
    axis = Axis([(p[0], p[1]) for p in points], closed=closed)
    return [[p[0], p[1]] for p in axis.offset_vertices(offset)]


def point_on_road(points: list[list[float]], distance: float,
                  offset: float = 0.0, closed: bool = False,
                  bulges: Optional[list[float]] = None) -> dict[str, Any]:
    """Punto a una distancia dada del arranque del eje, y opcionalmente
    desplazado perpendicularmente. Es cómo se ubica algo por cadenamiento.

    bulges: si el eje tiene curvas, hay que pasarlos. Sin ellos la distancia
    se mide sobre la CUERDA y no sobre el arco, y todo lo que se ubique
    después del principio de curva queda corrido varios centímetros.
    """
    if bulges and any(abs(b) > 1e-12 for b in bulges):
        points = densify(points, bulges)
    axis = Axis([(p[0], p[1]) for p in points], closed=closed)
    p = axis.offset_point_at(distance, offset)
    seg, _ = axis.segment_at(distance)
    u = axis.dirs[seg]
    return {"x": p[0], "y": p[1], "dirX": u[0], "dirY": u[1],
            "totalLength": axis.total_length}


# ------------------------------------------------- alineamiento horizontal

def _spiral_points(radius: float, length: float, samples: int = 24
                   ) -> tuple[list[tuple[float, float]], float]:
    """Puntos de una clotoide en coordenadas locales, y su angulo final.

    La clotoide (o espiral de Euler) es la curva cuyo radio disminuye de forma
    lineal con el recorrido: es lo que permite entrar a una curva girando el
    volante de a poco en vez de de golpe. Arranca en el origen tangente al eje
    X, con radio infinito, y termina con radio 'radius' tras recorrer 'length'.

    Se usa la serie de la clotoide; con dos terminos alcanza de sobra para los
    angulos de una vialidad (el error queda muy por debajo del milimetro).
    """
    if radius <= 0 or length <= 0:
        raise ValueError("La espiral necesita radius y length > 0.")

    pts: list[tuple[float, float]] = []
    for i in range(samples + 1):
        l = length * i / samples
        l2 = l * l
        rl = radius * length
        x = l - (l2 * l2 * l) / (40.0 * rl * rl)
        y = (l2 * l) / (6.0 * rl) - (l2 * l2 * l2 * l) / (336.0 * rl * rl * rl)
        pts.append((x, y))

    # Angulo que gira el rumbo a lo largo de toda la espiral.
    theta = length / (2.0 * radius)
    return pts, theta


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

        elif kind in ("spiral", "espiral", "clothoid", "clotoide"):
            radio = float(el["radius"])
            largo = float(el["length"])
            izquierda = str(el.get("direction", "left")).lower() in (
                "left", "izq", "izquierda")
            signo = 1.0 if izquierda else -1.0
            # 'exit' invierte la espiral: de la curva de vuelta a la recta.
            salida = bool(el.get("exit", False))

            locales, theta = _spiral_points(radio, largo)
            if salida:
                # La de salida es la de entrada recorrida al reves: se refleja
                # y se reordena para que arranque tangente al rumbo actual.
                xf, yf = locales[-1]
                locales = [(xf - x0, -(yf - y0)) for x0, y0 in reversed(locales)]

            cos_b, sin_b = math.cos(bearing), math.sin(bearing)
            for lx, ly in locales[1:]:
                ly_s = ly * signo
                px = x + lx * cos_b - ly_s * sin_b
                py = y + lx * sin_b + ly_s * cos_b
                points.append([px, py])
                bulges.append(0.0)
            x, y = points[-1][0], points[-1][1]

            bearing += signo * theta
            estacion += largo
            puntos_notables.append({
                "type": "fin de espiral", "station": estacion, "x": x, "y": y,
                "radius": radio, "spiralLength": largo,
                "spiralAngleDeg": math.degrees(theta),
                "parameter": math.sqrt(radio * largo),
            })

        else:
            raise ValueError(
                f"Elemento #{i}: tipo {kind!r} desconocido. "
                "Usá 'tangent', 'curve' o 'spiral'.")

    # Un bulge por vertice: el ultimo no arrastra arco.
    while len(bulges) < len(points):
        bulges.append(0.0)
    bulges = bulges[:len(points)]

    return {
        "points": points,
        "bulges": bulges,
        "length": estacion,
        "endBearingDeg": math.degrees(bearing) % 360.0,
        "stations": puntos_notables,
    }


# ----------------------------------------------------------- intersecciones

def create_intersection(main_points: list[list[float]],
                        branch_points: list[list[float]],
                        main_width: float, branch_width: float,
                        radius: float = 6.0,
                        main_bulges: Optional[list[float]] = None,
                        branch_bulges: Optional[list[float]] = None,
                        layer: str = LAYER_CURB,
                        samples: int = 16) -> dict[str, Any]:
    """Radios de acuerdo en el encuentro de dos calles.

    Dos calles trazadas por separado se cruzan y sus guarniciones quedan
    chocando en escuadra, que no es como se construye ni por donde puede pasar
    un vehiculo. El acuerdo es el arco que empalma el borde de una con el de la
    otra.

    main_points / branch_points: los ejes de cada calle. El ramal tiene que
    ARRANCAR en el punto donde nace de la principal.
    radius: radio de giro del acuerdo (6 m en calle urbana; 10 o mas si entran
    camiones).

    Devuelve los handles de los dos arcos y su desarrollo, que se suma a los
    metros lineales de guarnicion.
    """
    if radius <= 0:
        raise ValueError("El radio de acuerdo tiene que ser > 0.")

    main = Axis([(p[0], p[1]) for p in (
        densify(main_points, main_bulges) if main_bulges else main_points)])
    branch = Axis([(p[0], p[1]) for p in (
        densify(branch_points, branch_bulges) if branch_bulges else branch_points)])

    # Donde nace el ramal, medido sobre la principal.
    origen = branch.points[0]
    d_nace = _closest_station(main, origen)

    _ensure(layer, layers.COLOR_VEGETACION, LW_CURB)
    arcos = []
    desarrollo_total = 0.0

    hm, hb = main_width / 2.0, branch_width / 2.0

    # Un acuerdo de cada lado del ramal.
    for signo in (1.0, -1.0):
        # Punto de tangencia sobre la principal: se aleja del cruce lo
        # suficiente como para que el arco entre.
        avance = radius + hb
        d_tan = d_nace + signo * avance
        d_tan = max(0.0, min(main.total_length, d_tan))

        lado = _side_of(main, branch, d_nace)
        p_main = main.offset_point_at(d_tan, hm * lado)

        # Punto de tangencia sobre el ramal, a la misma distancia del cruce.
        d_b = min(branch.total_length, radius + hm)
        p_branch = branch.offset_point_at(d_b, hb * signo)

        arco = _fillet_arc(p_main, p_branch, radius, samples)
        handle = acad.call("create_polyline", {
            "points": [[p[0], p[1]] for p in arco],
            "bulges": None, "closed": False, "layer": layer,
            "lineweight": LW_CURB, "colorIndex": None,
        })["handle"]
        largo = sum(math.dist(arco[i], arco[i + 1])
                    for i in range(len(arco) - 1))
        arcos.append({"handle": handle, "developedLength": round(largo, 2)})
        desarrollo_total += largo

    return {"arcs": arcos, "radius": radius,
            "branchStation": round(d_nace, 2),
            "curbLength": round(desarrollo_total, 2)}


def _closest_station(axis: Axis, point: Point) -> float:
    """A que distancia del arranque del eje cae el punto mas cercano."""
    mejor_d, mejor_dist = 0.0, float("inf")
    n = max(60, len(axis.points) * 6)
    for i in range(n + 1):
        d = axis.total_length * i / n
        p = axis.offset_point_at(d, 0.0)
        dist = math.dist(p, point)
        if dist < mejor_dist:
            mejor_dist, mejor_d = dist, d
    return mejor_d


def _side_of(main: Axis, branch: Axis, d: float) -> float:
    """De que lado de la principal se va el ramal: +1 izquierda, -1 derecha."""
    if len(branch.points) < 2:
        return 1.0
    i, _ = main.segment_at(d)
    u = main.dirs[i]
    p0 = branch.points[0]
    p1 = branch.points[min(2, len(branch.points) - 1)]
    vx, vy = p1[0] - p0[0], p1[1] - p0[1]
    cruz = u[0] * vy - u[1] * vx
    return 1.0 if cruz >= 0 else -1.0


def _fillet_arc(p0: Point, p1: Point, radius: float,
                samples: int) -> list[Point]:
    """Arco de radio dado que empalma dos puntos, por el lado corto."""
    cuerda = math.dist(p0, p1)
    if cuerda < 1e-9:
        return [p0, p1]

    # Si el radio no alcanza para unirlos, se usa el minimo posible.
    r = max(radius, cuerda / 2.0 + 1e-9)
    mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    dx, dy = (p1[0] - p0[0]) / cuerda, (p1[1] - p0[1]) / cuerda
    h = math.sqrt(max(r * r - (cuerda / 2.0) ** 2, 0.0))
    cx, cy = mx - dy * h, my + dx * h

    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    a1 = math.atan2(p1[1] - cy, p1[0] - cx)
    barrido = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi   # el lado corto

    return [(cx + r * math.cos(a0 + barrido * k / samples),
             cy + r * math.sin(a0 + barrido * k / samples))
            for k in range(samples + 1)]


# ------------------------------------------- retícula de coordenadas

LAYER_RETICULA = "RETICULA-UTM"
LW_RETICULA = 9


def create_coordinate_grid(
    min_x: float, min_y: float, max_x: float, max_y: float,
    spacing: float = 10.0,
    cross_mm: float = 2.5,
    text_mm: float = 1.8,
    label_x: bool = True,
    label_y: bool = True,
    decimals: int = 0,
    scale: Optional[float] = None,
    layer: str = LAYER_RETICULA,
    lineweight: int = LW_RETICULA,
) -> dict[str, Any]:
    """Retícula de coordenadas: las cruces de una vista topográfica.

    Es lo que permite ubicar CUALQUIER punto del plano en el terreno real:
    sin la retícula, un plano en coordenadas UTM tiene los números del
    cuadro de construcción pero nada con qué leerlos sobre el dibujo. Va en
    la vista "con coordenadas originales" (la topográfica); la vista de
    proyecto se dibuja sin ella, que es la convención que usa cualquier
    juego serio.

    min_x..max_y: la zona a reticular, en coordenadas del modelo.
    spacing: cada cuánto va una cruz, en unidades del modelo (10 m en un
    terreno urbano, 100 m en un conjunto). Las cruces caen en los MÚLTIPLOS
    exactos del espaciamiento — no en el borde de la zona: una retícula
    cuyos números no son redondos no se puede leer.
    cross_mm / text_mm: tamaño de la cruz y del rótulo en mm de PAPEL, así
    la retícula se ve igual a cualquier escala.
    label_x / label_y: rotular abajo las X y a la izquierda las Y.
    decimals: decimales del rótulo (0 en UTM, donde el metro ya es la
    precisión útil).

    Las cruces NO se registran como huella: son una malla de fondo y
    bloquear el plano entero dejaría a place_labels sin dónde escribir.
    Los rótulos del borde sí, que es lo que puede encimarse."""
    if spacing <= 0:
        raise ValueError("spacing tiene que ser > 0.")
    x0, x1 = min(min_x, max_x), max(min_x, max_x)
    y0, y1 = min(min_y, max_y), max(min_y, max_y)

    esc = scale if scale else space.units_per_paper_mm()
    brazo = cross_mm * esc / 2.0
    h = text_mm * esc

    xs = []
    k = math.ceil(x0 / spacing - 1e-9)
    while k * spacing <= x1 + 1e-9:
        xs.append(k * spacing)
        k += 1
    ys = []
    k = math.ceil(y0 / spacing - 1e-9)
    while k * spacing <= y1 + 1e-9:
        ys.append(k * spacing)
        k += 1

    if not xs or not ys:
        raise ValueError(
            "Con spacing=%g no cae ninguna cruz dentro de la zona "
            "(%g x %g). Bajá el espaciamiento." % (spacing, x1 - x0, y1 - y0))

    _ensure(layer, layers.COLOR_SECUNDARIO, lineweight)

    cruces = 0
    for gx in xs:
        for gy in ys:
            acad.call("create_line", {
                "x1": gx - brazo, "y1": gy, "z1": 0.0,
                "x2": gx + brazo, "y2": gy, "z2": 0.0,
                "layer": layer, "lineweight": lineweight, "colorIndex": None})
            acad.call("create_line", {
                "x1": gx, "y1": gy - brazo, "z1": 0.0,
                "x2": gx, "y2": gy + brazo, "z2": 0.0,
                "layer": layer, "lineweight": lineweight, "colorIndex": None})
            cruces += 1

    fmt = "%%.%df" % max(0, int(decimals))
    etiquetas = 0

    if label_x:
        for gx in xs:
            texto = fmt % gx
            ancho = len(texto) * h * 0.87
            tx, ty = gx - ancho / 2.0, y0 - h * 2.0
            acad.call("create_text", {
                "text": texto, "x": tx, "y": ty, "z": 0.0, "height": h,
                "layer": layer, "rotationDeg": 0.0, "style": None,
                "lineweight": lineweight, "colorIndex": None})
            space.track(tx, ty, tx + ancho, ty + h * 1.2,
                        "%s %s" % (space.PREFIJO_TEXTO, texto))
            etiquetas += 1

    if label_y:
        for gy in ys:
            texto = fmt % gy
            ancho = len(texto) * h * 0.87
            # Rotada 90°: una coordenada UTM son 7 dígitos y en horizontal
            # se mete adentro del dibujo.
            tx, ty = x0 - h * 2.0, gy - ancho / 2.0
            acad.call("create_text", {
                "text": texto, "x": tx, "y": ty, "z": 0.0, "height": h,
                "layer": layer, "rotationDeg": 90.0, "style": None,
                "lineweight": lineweight, "colorIndex": None})
            space.track(tx - h * 1.2, ty, tx, ty + ancho,
                        "%s %s" % (space.PREFIJO_TEXTO, texto))
            etiquetas += 1

    return {
        "crosses": cruces,
        "labels": etiquetas,
        "spacing": spacing,
        "xValues": xs,
        "yValues": ys,
        "box": [x0, y0, x1, y1],
    }


# ------------------------------------------- cuadro de construcción

LAYER_CUADRO = "CUADRO-CONSTRUCCION"
LW_CUADRO = 13

# Anchos de columna en mm de papel: LADO | RUMBO | DISTANCIA | V | X | Y.
# El rumbo es la columna ancha (N 89°59'59" W son 13 caracteres) y las
# coordenadas UTM llevan 6-7 enteros más 3 decimales.
_CUADRO_COLS_MM = (16.0, 30.0, 16.0, 8.0, 24.0, 24.0)


def _dms(grados: float) -> str:
    """45.5083° -> 45°30'30" (grados, minutos y segundos enteros)."""
    g = int(grados)
    resto = (grados - g) * 60.0
    m = int(resto)
    s = int(round((resto - m) * 60.0))
    if s == 60:
        s, m = 0, m + 1
    if m == 60:
        m, g = 0, g + 1
    return "%02d°%02d'%02d\"" % (g, m, s)


def rumbo(p0: Point, p1: Point) -> str:
    """Rumbo cuadrantal del lado p0->p1: N/S ángulo E/W desde el norte.

    Es la forma en que un cuadro de construcción mexicano expresa la
    dirección de cada lado del terreno — no un azimut de 0 a 360.
    """
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    if math.hypot(dx, dy) < 1e-9:
        raise ValueError("Dos vértices consecutivos son el mismo punto.")
    ns = "N" if dy >= 0 else "S"
    ew = "E" if dx >= 0 else "W"
    angulo = math.degrees(math.atan2(abs(dx), abs(dy)))
    return "%s %s %s" % (ns, _dms(angulo), ew)


def parse_rumbo(texto: str) -> float:
    """Un rumbo cuadrantal ("N 45°30'20\" W") a azimut en grados desde el norte.

    Es el inverso de rumbo(). Acepta lo que aparece en un cuadro de
    construcción impreso: los símbolos ° ' " o espacios/guiones, decimales o
    grados-minutos-segundos, y N/S/E/W o N/S/E/O (en castellano el oeste se
    escribe O y ese detalle rompía la lectura de planos mexicanos).
    """
    crudo = str(texto).strip().upper().replace("º", "°")
    if not crudo:
        raise ValueError("Rumbo vacío.")

    numeros = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", crudo)]
    letras = [c for c in re.findall(r"[NSEWO]", crudo)]
    if not numeros or len(letras) < 2:
        raise ValueError(
            "No se entiende el rumbo %r. Se espera algo como "
            "\"N 45°30'20\\\" W\" o \"S 12.5 E\"." % texto)

    grados = numeros[0]
    if len(numeros) > 1:
        grados += numeros[1] / 60.0
    if len(numeros) > 2:
        grados += numeros[2] / 3600.0
    if grados > 90.0 + 1e-9:
        raise ValueError(
            "El ángulo de un rumbo cuadrantal va de 0 a 90°, no %.4f. "
            "Si lo que tenés es un azimut de 0 a 360, pasalo como azimuth."
            % grados)

    ns, ew = letras[0], letras[-1]
    if ns not in ("N", "S") or ew not in ("E", "W", "O"):
        raise ValueError(
            "Un rumbo se escribe N/S ángulo E/W (o E/O), no %r." % texto)

    oeste = ew in ("W", "O")
    if ns == "N":
        return (360.0 - grados) % 360.0 if oeste else grados
    return 180.0 + grados if oeste else 180.0 - grados


def traverse(sides: list[dict[str, Any]],
             start_x: float = 0.0, start_y: float = 0.0) -> dict[str, Any]:
    """Del CUADRO DE CONSTRUCCIÓN a las coordenadas: rumbo + distancia por
    lado, recorrido lado a lado desde el vértice de arranque.

    Es el inverso exacto de create_construction_table, y con los dos se cierra
    el ciclo: de un plano ajeno se lee su cuadro impreso, se reconstruyen los
    vértices y se puede volver a dibujar el terreno. Sin esto, un terreno que
    llega descrito por rumbos hay que resolverlo a mano con trigonometría —
    y eso es exactamente lo que no debe pasar.

    sides: [{"bearing": "N 45°30'20\\" W", "distance": 26.00}, ...] — un
    elemento por lado, en orden de recorrido. En vez de 'bearing' se acepta
    'azimuth' en grados decimales desde el norte, sentido horario.

    Devuelve los vértices, la superficie por shoelace, el perímetro y —lo que
    de verdad importa en obra— el ERROR DE CIERRE: cuánto le falta al último
    lado para volver al punto de partida. Un cuadro copiado de un plano casi
    nunca cierra exacto por el redondeo de los segundos, y hay que saber
    cuánto: 2 cm en 170 m es redondeo, 2 m es un dato mal leído.
    """
    if not sides:
        raise ValueError("Hace falta al menos un lado en 'sides'.")

    puntos: list[list[float]] = [[float(start_x), float(start_y)]]
    for i, lado in enumerate(sides):
        try:
            distancia = float(lado["distance"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                "El lado %d necesita 'distance' numérica." % (i + 1))
        if distancia <= 0:
            raise ValueError(
                "El lado %d tiene distancia %s: tiene que ser > 0."
                % (i + 1, distancia))

        if lado.get("azimuth") is not None:
            azimut = float(lado["azimuth"]) % 360.0
        elif lado.get("bearing"):
            try:
                azimut = parse_rumbo(lado["bearing"])
            except ValueError as exc:
                raise ValueError("Lado %d: %s" % (i + 1, exc))
        else:
            raise ValueError(
                "El lado %d necesita 'bearing' (rumbo cuadrantal) o "
                "'azimuth' (grados desde el norte)." % (i + 1))

        # Azimut se mide DESDE EL NORTE y en sentido horario: el seno va en
        # x (este) y el coseno en y (norte). Al revés es el error clásico.
        rad = math.radians(azimut)
        x, y = puntos[-1]
        puntos.append([x + distancia * math.sin(rad),
                       y + distancia * math.cos(rad)])

    cierre_dx = puntos[-1][0] - puntos[0][0]
    cierre_dy = puntos[-1][1] - puntos[0][1]
    error = math.hypot(cierre_dx, cierre_dy)
    perimetro = sum(float(s["distance"]) for s in sides)

    # Los vértices del polígono son los de arranque de cada lado: el último
    # punto es el intento de volver al primero y no es un vértice nuevo.
    vertices = [[round(p[0], 4), round(p[1], 4)] for p in puntos[:-1]]

    resultado: dict[str, Any] = {
        "points": vertices,
        "closureError": round(error, 4),
        "closureBy": {"dx": round(cierre_dx, 4), "dy": round(cierre_dy, 4)},
        "perimeter": round(perimetro, 3),
        "sides": len(sides),
    }
    if len(vertices) >= 3:
        resultado["area"] = round(geom.polygon_area(vertices), 3)
    # 1/5000 es la tolerancia habitual de un levantamiento de predio urbano.
    tolerancia = perimetro / 5000.0
    resultado["closes"] = error <= max(tolerancia, 0.005)
    if not resultado["closes"]:
        resultado["warning"] = (
            "El polígono NO cierra: le faltan %.3f m para volver al punto de "
            "partida (%.0f veces la tolerancia de 1/5000, que acá son %.3f m)."
            " Revisá los rumbos y las distancias del cuadro antes de dibujar:"
            " un cuadro bien copiado cierra con centímetros."
            % (error, error / tolerancia if tolerancia else 0, tolerancia))
    return resultado


def create_construction_table(
    points: list[list[float]],
    x: float,
    y: float,
    title: str = "CUADRO DE CONSTRUCCIÓN",
    vertex_prefix: str = "V",
    row_mm: float = 6.0,
    text_mm: float = 2.0,
    scale: Optional[float] = None,
    layer: str = LAYER_CUADRO,
    mark_vertices: bool = True,
    avoid: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Cuadro de construcción del terreno: rumbos, distancias y coordenadas.

    Es LA tabla que acompaña a todo plano de terreno en México (la que
    CivilCAD llama cuadro de construcción): una fila por lado del polígono
    con su rumbo cuadrantal (N 45°30'20" W), su distancia y las coordenadas
    del vértice de llegada, más la superficie y el perímetro al pie. Sin
    ella el plano no se puede replantear en campo.

    points: vértices del polígono EN SUS COORDENADAS REALES (UTM o locales),
    en orden y sin repetir el primero al final — el cierre se agrega solo.
    Los rumbos, distancias y superficie se CALCULAN de esos vértices, no se
    escriben de memoria: el número que sale es el que mide el dibujo.

    x, y: esquina superior izquierda del cuadro.
    scale: unidades del modelo por mm de papel; sin él, rige la escala
    registrada de la lámina (create_sheet).
    mark_vertices: dibuja en cada vértice su círculo y su etiqueta V1, V2...
    corridas hacia AFUERA del polígono, para leer el cuadro contra el
    dibujo. Quedan registradas: check_annotations las ve.

    Devuelve las filas calculadas ('sides'), 'area', 'perimeter' y la caja
    del cuadro."""
    import annotation as ann

    if len(points) < 3:
        raise ValueError("Un polígono de terreno necesita al menos 3 vértices.")
    pts = [(float(p[0]), float(p[1])) for p in points]
    if math.dist(pts[0], pts[-1]) < 1e-9:
        pts = pts[:-1]      # vino cerrado: el cierre lo agregamos nosotros
        if len(pts) < 3:
            raise ValueError(
                "Un polígono de terreno necesita al menos 3 vértices.")

    esc = scale if scale else space.units_per_paper_mm()

    lados = []
    perimetro = 0.0
    area2 = 0.0
    n = len(pts)
    for i in range(n):
        p0, p1 = pts[i], pts[(i + 1) % n]
        dist = math.dist(p0, p1)
        perimetro += dist
        area2 += p0[0] * p1[1] - p1[0] * p0[1]
        lados.append({
            "side": "%s%d-%s%d" % (vertex_prefix, i + 1,
                                   vertex_prefix, (i + 1) % n + 1),
            "bearing": rumbo(p0, p1),
            "distance": round(dist, 3),
            "vertex": "%s%d" % (vertex_prefix, (i + 1) % n + 1),
            "x": round(p1[0], 3),
            "y": round(p1[1], 3),
        })
    area = abs(area2) / 2.0

    filas = [["LADO", "RUMBO", "DISTANCIA", "V", "X", "Y"]]
    for lado in lados:
        filas.append([lado["side"], lado["bearing"],
                      "%.2f" % lado["distance"], lado["vertex"],
                      "%.3f" % lado["x"], "%.3f" % lado["y"]])
    # El pie va en las columnas anchas (RUMBO y X): "60.00 m" no entra en
    # la columna V de 8 mm y la tabla entera se negaba a dibujarse.
    filas.append(["SUP.", "%.2f m2" % area, "PERIM.", "",
                  "%.2f m" % perimetro, ""])

    tabla = ann.create_table(
        x=x, y=y, rows=filas,
        col_widths=[w * esc for w in _CUADRO_COLS_MM],
        row_height=row_mm * esc, text_height=text_mm * esc,
        title=title, header=True, layer=layer, avoid=avoid)

    marcas = []
    if mark_vertices:
        _ensure(layer, layers.COLOR_COTAS, LW_CUADRO)
        cx = sum(p[0] for p in pts) / n
        cy = sum(p[1] for p in pts) / n
        r = 1.0 * esc
        for i, p in enumerate(pts):
            dx, dy = p[0] - cx, p[1] - cy
            d = math.hypot(dx, dy) or 1.0
            ux, uy = dx / d, dy / d
            acad.call("create_circle", {
                "x": p[0], "y": p[1], "z": 0.0, "radius": r,
                "layer": layer, "lineweight": LW_CUADRO,
                "colorIndex": None})
            tx = p[0] + ux * 3.0 * esc
            ty = p[1] + uy * 3.0 * esc
            etiqueta = "%s%d" % (vertex_prefix, i + 1)
            acad.call("create_text", {
                "text": etiqueta, "x": tx, "y": ty, "z": 0.0,
                "height": text_mm * esc, "layer": layer,
                "rotationDeg": 0.0, "style": None,
                "lineweight": LW_CUADRO, "colorIndex": None})
            ancho = len(etiqueta) * text_mm * esc * 0.87
            space.track(tx, ty, tx + ancho, ty + text_mm * esc * 1.2,
                        "%s %s" % (space.PREFIJO_TEXTO, etiqueta))
            marcas.append({"vertex": etiqueta, "x": p[0], "y": p[1]})

    resultado = {
        "sides": lados,
        "area": round(area, 3),
        "perimeter": round(perimetro, 3),
        "vertexMarks": marcas,
        "table": tabla,
    }
    if tabla.get("warning"):
        resultado["warning"] = tabla["warning"]
    return resultado
