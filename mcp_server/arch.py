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


# ------------------------------------------------- dibujar un partido entero

def _merge_intervalos(ivs: list[list[float]],
                      tol: float = 1e-6) -> list[list[float]]:
    """Une intervalos [a0, a1, ext] que se tocan. 'ext' se contagia: si un
    pedazo del muro da al exterior, todo el tramo fusionado sale exterior."""
    out: list[list[float]] = []
    for a0, a1, ext in sorted(ivs):
        if out and a0 <= out[-1][1] + tol:
            out[-1][1] = max(out[-1][1], a1)
            out[-1][2] = out[-1][2] or ext
        else:
            out.append([a0, a1, bool(ext)])
    return out


def draw_layout(rooms: list[dict[str, Any]],
                doors: Optional[list[dict[str, Any]]] = None,
                windows: Optional[list[dict[str, Any]]] = None,
                exterior_thickness: float = 0.15,
                interior_thickness: float = 0.10,
                window_width: float = 1.20,
                merge: bool = True,
                layer: str = LAYER_WALLS,
                lineweight: int = LW_WALL) -> dict[str, Any]:
    """Dibuja la muraria completa de una distribución de recintos.

    Toma el vocabulario de suggest_layout/check_layout (rooms como
    rectángulos, doors con su posición) y lo convierte en muros de verdad:
    cada frontera se dibuja UNA vez (dos recintos vecinos no duplican el
    muro), el perímetro y el frente al patio salen con espesor exterior, lo
    demás interior, y las puertas caen en el muro que les toca con la hoja
    abriendo hacia su recinto destino. Las ventanas se ubican solas en el
    hueco libre más grande del paño de su ambiente.

    Solo entiende recintos ortogonales (rectángulos alineados a los ejes),
    que es exactamente lo que produce suggest_layout.

    Devuelve los handles, los EJES dibujados (listos para check_walls) y
    los avisos de lo que no se pudo ubicar."""
    tol = 1e-4
    rects: list[dict[str, Any]] = []
    for i, r in enumerate(rooms or []):
        try:
            rects.append({"name": str(r["name"]),
                          "x0": float(r["x0"]), "y0": float(r["y0"]),
                          "x1": float(r["x1"]), "y1": float(r["y1"])})
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"El room #{i + 1} necesita name, x0, y0, x1, y1. ({exc})")
    if not rects:
        raise ValueError("draw_layout necesita al menos un room.")

    bx0 = min(r["x0"] for r in rects)
    bx1 = max(r["x1"] for r in rects)
    by0 = min(r["y0"] for r in rects)
    by1 = max(r["y1"] for r in rects)

    def _es_patio(nombre: str) -> bool:
        return "PATIO" in nombre.upper()

    # Cada recinto aporta sus 4 bordes; los compartidos se funden al unir
    # los intervalos de la misma línea. 'ext' = perímetro del lote o frente
    # a un patio: llevan el espesor exterior.
    lineas: dict[tuple[str, float], list[list[float]]] = {}

    def _edge(orient: str, c: float, a0: float, a1: float, ext: bool) -> None:
        lineas.setdefault((orient, round(c, 4)), []).append(
            [min(a0, a1), max(a0, a1), ext])

    for r in rects:
        patio = _es_patio(r["name"])
        _edge("v", r["x0"], r["y0"], r["y1"], patio or abs(r["x0"] - bx0) < tol)
        _edge("v", r["x1"], r["y0"], r["y1"], patio or abs(r["x1"] - bx1) < tol)
        _edge("h", r["y0"], r["x0"], r["x1"], patio or abs(r["y0"] - by0) < tol)
        _edge("h", r["y1"], r["x0"], r["x1"], patio or abs(r["y1"] - by1) < tol)

    segs: list[dict[str, Any]] = []
    for (orient, c), ivs in sorted(lineas.items()):
        for a0, a1, ext in _merge_intervalos(ivs):
            segs.append({"orient": orient, "c": c, "a0": a0, "a1": a1,
                         "ext": ext, "openings": []})

    por_nombre = {r["name"].upper(): r for r in rects}
    avisos: list[str] = []
    puertas_puestas = 0

    def _buscar_segmento(px: float, py: float) -> Optional[tuple]:
        mejor = None
        for s in segs:
            if s["orient"] == "v":
                d, a = abs(px - s["c"]), py
            else:
                d, a = abs(py - s["c"]), px
            if d < 0.03 and s["a0"] - 0.03 <= a <= s["a1"] + 0.03:
                if mejor is None or d < mejor[0]:
                    mejor = (d, s, a)
        return mejor

    for d in (doors or []):
        etiqueta = f"{d.get('from', '?')} -> {d.get('to', '?')}"
        if "x" not in d or "y" not in d:
            avisos.append(f"La puerta {etiqueta} no trae posición (x, y): "
                          "no se dibujó. Agregala a mano o pasale el punto.")
            continue
        px, py = float(d["x"]), float(d["y"])
        hallado = _buscar_segmento(px, py)
        if not hallado:
            avisos.append(f"La puerta {etiqueta} en ({px:g}, {py:g}) no cae "
                          "sobre ningún muro de la distribución: no se dibujó.")
            continue
        _, s, a = hallado
        ancho = float(d.get("width", 0.80))
        destino = por_nombre.get(str(d.get("to", "")).upper())
        side = "left"
        if destino:
            cx = (destino["x0"] + destino["x1"]) / 2.0
            cy = (destino["y0"] + destino["y1"]) / 2.0
            if s["orient"] == "v":
                side = "left" if cx < s["c"] else "right"
            else:
                side = "left" if cy > s["c"] else "right"
        total = s["a1"] - s["a0"]
        dist = min(max(a - s["a0"], ancho / 2.0), total - ancho / 2.0)
        s["openings"].append({"distance": dist, "width": ancho,
                              "type": str(d.get("type", "door")),
                              "side": side})
        puertas_puestas += 1

    # Ventanas: {"room": .., "wall": "fachada"|"patio"} (lo que devuelve
    # suggest_layout). Se ubican en el hueco libre más grande del paño.
    ventanas_puestas: list[dict[str, Any]] = []
    patio_room = next((r for r in rects if _es_patio(r["name"])), None)
    for wdef in (windows or []):
        nombre = str(wdef.get("room", ""))
        r = por_nombre.get(nombre.upper())
        muro = str(wdef.get("wall", "")).lower()
        if not r:
            avisos.append(f"Ventana de '{nombre}': el recinto no está en "
                          "'rooms'.")
            continue
        if muro in ("fachada", "frente", "front") and abs(r["y0"] - by0) < tol:
            c, i0, i1 = r["y0"], r["x0"], r["x1"]
        elif (muro == "patio" and patio_room is not None
              and abs(r["y1"] - patio_room["y0"]) < tol):
            c, i0, i1 = r["y1"], r["x0"], r["x1"]
        else:
            avisos.append(f"Ventana de '{nombre}' en muro '{muro}': no se "
                          "resuelve sola (colindancia o sin patio vecino). "
                          "Si va, dibujala a mano.")
            continue
        hallado = _buscar_segmento((i0 + i1) / 2.0, c)
        if not hallado:
            continue
        _, s, _a = hallado
        # El hueco libre más grande dentro del paño del recinto, dejando
        # 0.30 a cada esquina y 0.15 a cada puerta ya colocada.
        lim0, lim1 = i0 + 0.30, i1 - 0.30
        cortes = sorted(
            (s["a0"] + o["distance"] - o["width"] / 2.0 - 0.15,
             s["a0"] + o["distance"] + o["width"] / 2.0 + 0.15)
            for o in s["openings"])
        mejor_gap = None
        g0 = lim0
        for c0, c1 in cortes + [(lim1, lim1)]:
            g1 = min(c0, lim1)
            if g1 - g0 > (mejor_gap[1] - mejor_gap[0] if mejor_gap else 0):
                mejor_gap = (g0, g1)
            g0 = max(g0, c1)
        hueco = (mejor_gap[1] - mejor_gap[0]) if mejor_gap else 0.0
        ancho_v = window_width if hueco >= window_width else (
            hueco if hueco >= 0.90 else 0.0)
        if ancho_v <= 0:
            avisos.append(f"Ventana de '{nombre}': el paño libre mide "
                          f"{hueco:.2f} m y no entra ni una de 0.90.")
            continue
        centro = (mejor_gap[0] + mejor_gap[1]) / 2.0
        s["openings"].append({"distance": centro - s["a0"],
                              "width": ancho_v, "type": "window"})
        ventanas_puestas.append({"room": nombre, "width": round(ancho_v, 2),
                                 "x": round(centro if s["orient"] == "h"
                                            else s["c"], 3),
                                 "y": round(s["c"] if s["orient"] == "h"
                                            else centro, 3)})

    axes: list[dict[str, Any]] = []
    handles: list[str] = []
    tramos = 0
    for s in segs:
        if s["orient"] == "v":
            points = [[s["c"], s["a0"]], [s["c"], s["a1"]]]
        else:
            points = [[s["a0"], s["c"]], [s["a1"], s["c"]]]
        th = exterior_thickness if s["ext"] else interior_thickness
        r = create_walls(points=points, thickness=th,
                         openings=sorted(s["openings"],
                                         key=lambda o: o["distance"]),
                         layer=layer, lineweight=lineweight)
        tramos += 1
        handles.extend(r["wallHandles"])
        axes.append({"points": points,
                     "name": f"muro {s['orient']}={s['c']:g} "
                             f"({s['a0']:g}..{s['a1']:g})"})
        if r.get("warning"):
            avisos.append(f"{axes[-1]['name']}: {r['warning']}")

    resultado: dict[str, Any] = {
        "wallHandles": handles,
        "segments": tramos,
        "axes": axes,
        "doorsPlaced": puertas_puestas,
        "doorsTotal": len(doors or []),
        "windowsPlaced": ventanas_puestas,
        "thicknesses": {"exterior": exterior_thickness,
                        "interior": interior_thickness},
    }

    # Fusion de los contornos. SIN esto el plano se ve mal de verdad, y es
    # lo primero que nota alguien que dibuja: cada tramo es una polilinea
    # CERRADA, asi que donde un divisorio llega al muro del pasillo su
    # linea de cierre queda dibujada ATRAVESANDO el otro muro. El encuentro
    # se ve como un cajon en vez de la T limpia que corresponde -- parece
    # dibujado a mano y sin cuidado. La union booleana borra esas lineas
    # interiores y deja el perimetro real de la mamposteria.
    #
    # Va al final a proposito: el resultado es una Region y ya no admite
    # editar vertices (ver CLAUDE.md 5).
    if merge and len(handles) > 1:
        try:
            union = acad.call("union_regions", {
                "handles": handles, "deleteSources": True})
            resultado["merged"] = union
            # union_regions devuelve 'handle' EN SINGULAR (una Region con
            # todo adentro). Leer 'handles' devolvia None y dejaba en
            # wallHandles los 29 handles ORIGINALES, que deleteSources ya
            # borro: cualquiera que los usara despues se comia un
            # eUnknownHandle, y el conteo mentia sobre lo que se fusiono.
            nuevo = union.get("handle")
            if nuevo:
                resultado["wallHandles"] = [nuevo]
            resultado["mergedCount"] = union.get("merged", len(handles))
            if union.get("area"):
                resultado["masonryArea"] = union["area"]
            if union.get("perimeter"):
                resultado["masonryPerimeter"] = union["perimeter"]
        except acad.AutoCadError as exc:
            # Que la union falle no invalida el dibujo: los muros ya estan.
            avisos.append(
                "No se pudieron fusionar los contornos de muro (%s). Los "
                "encuentros van a verse como cajon en vez de T: proba "
                "union_regions a mano sobre 'wallHandles'." % exc)

    if avisos:
        resultado["warnings"] = avisos
    return resultado


def dimension_layout(rooms: list[dict[str, Any]],
                     sides: Optional[list[str]] = None,
                     detail: bool = True,
                     total: bool = True,
                     min_gap: float = 0.15,
                     scale: float = 0.0,
                     style: Optional[str] = None,
                     layer: str = "COTAS") -> dict[str, Any]:
    """Acota la planta entera a partir de los recintos, sin listar posiciones.

    Es la contraparte de draw_layout: los cortes de la cadena de cotas son
    exactamente las fronteras entre recintos, que ya están en 'rooms'. Que
    el agente las liste a mano es la clase de aritmética que sale mal —y si
    sale mal, el plano queda acotado con números que no son los del dibujo.

    Dibuja, por cada lado pedido:
      - una cadena de DETALLE con todas las fronteras de ese eje
      - una cadena TOTAL de punta a punta, un nivel más afuera

    El offset lo resuelve create_dimension_chain solo, apilándose afuera de
    lo que ya haya (incluidas las burbujas de eje). Como es la misma
    maquinaria de siempre, check_annotations sigue saliendo limpio.

    sides: cuáles acotar, de ("bottom", "top", "left", "right"). Por
    default 'bottom' e 'left', que es como se acota una planta salvo que
    algo del otro lado lo impida.
    min_gap: fronteras más juntas que esto se funden en un solo corte —dos
    cotas de 3 cm pegadas no se leen, y el número ni entra entre las
    flechas. Mismo criterio que la separación mínima de ejes.
    scale: 0 toma la escala registrada de la lámina.

    ACOTAR ES DESPUÉS DE DIBUJAR Y DE COMPONER: si las vistas se mueven
    (compose_sheet), lo que se reservó deja de valer."""
    import annotation as ann

    if not rooms:
        raise ValueError("dimension_layout necesita al menos un room.")
    lados = list(sides) if sides else ["bottom", "left"]
    for s in lados:
        if s not in space.SIDES:
            raise ValueError(
                f"side tiene que ser uno de {space.SIDES}, no {s!r}.")

    cajas = []
    for i, r in enumerate(rooms):
        try:
            cajas.append((float(r["x0"]), float(r["y0"]),
                          float(r["x1"]), float(r["y1"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"El room #{i + 1} necesita x0, y0, x1, y1. ({exc})")

    bx0 = min(c[0] for c in cajas)
    by0 = min(c[1] for c in cajas)
    bx1 = max(c[2] for c in cajas)
    by1 = max(c[3] for c in cajas)

    def _cortes(valores: list[float]) -> list[float]:
        """Ordena, deduplica y funde los que quedan más juntos que min_gap."""
        out: list[float] = []
        for v in sorted(valores):
            if not out or v - out[-1] > min_gap:
                out.append(v)
            else:
                # Se queda el ÚLTIMO del grupo: así el extremo del dibujo
                # nunca se pierde por fundirse con su vecino de adentro.
                out[-1] = v
        return out

    def _cortes_del_lado(s: str) -> list[float]:
        """Los cortes que se VEN desde ese lado.

        Tomar todas las fronteras del plano mete en la cadena de abajo
        divisiones que estan al fondo y no tienen nada que ver con ese pano:
        en la casa de prueba salian dos tramos de 0.50 (el pasillo partido
        por la frontera sala|comedor, que esta a 13 m de ahi) y los numeros
        se dibujaban uno encima del otro -- "0.500.50". Un plano se acota
        por pano: la cadena de abajo acota los recintos que APOYAN abajo.
        """
        if s == "bottom":
            propios = [c for c in cajas if abs(c[1] - by0) < 1e-6]
        elif s == "top":
            propios = [c for c in cajas if abs(c[3] - by1) < 1e-6]
        elif s == "left":
            propios = [c for c in cajas if abs(c[0] - bx0) < 1e-6]
        else:
            propios = [c for c in cajas if abs(c[2] - bx1) < 1e-6]
        if not propios:
            propios = cajas          # nada apoya ahi: mejor todo que nada
        if s in ("bottom", "top"):
            return _cortes([c[0] for c in propios] + [c[2] for c in propios])
        return _cortes([c[1] for c in propios] + [c[3] for c in propios])

    cortes_x = _cortes([c[0] for c in cajas] + [c[2] for c in cajas])
    cortes_y = _cortes([c[1] for c in cajas] + [c[3] for c in cajas])

    # Sin estilo propio, la cota toma el separador decimal de la config
    # REGIONAL de Windows y sale "3,5" en vez de "3.50".
    if style is None:
        style = ann.ensure_dim_style(scale=scale)

    cadenas: list[dict[str, Any]] = []
    for s in lados:
        horizontal = s in ("bottom", "top")
        cortes = _cortes_del_lado(s)
        if horizontal:
            referencia = by0 if s == "bottom" else by1
            extremos = [bx0, bx1]
        else:
            referencia = bx0 if s == "left" else bx1
            extremos = [by0, by1]

        if detail and len(cortes) > 2:
            cadenas.append({
                "side": s, "kind": "detalle", "cuts": len(cortes),
                "positions": cortes,
                "result": ann.create_dimension_chain(
                    positions=cortes, side=s, reference=referencia,
                    scale=scale, style=style, layer=layer)})
        if total:
            cadenas.append({
                "side": s, "kind": "total", "cuts": 2,
                "positions": extremos,
                "result": ann.create_dimension_chain(
                    positions=extremos, side=s, reference=referencia,
                    scale=scale, style=style, layer=layer)})

    avisos: list[str] = []
    for c in cadenas:
        w = c["result"].get("warning")
        if w:
            avisos.append("%s (%s): %s" % (c["side"], c["kind"], w))

    resultado: dict[str, Any] = {
        "chains": cadenas,
        "count": len(cadenas),
        "xCuts": cortes_x,
        "yCuts": cortes_y,
        "box": [bx0, by0, bx1, by1],
    }
    if avisos:
        resultado["warnings"] = avisos
    return resultado


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


def _resolver_distancia(axis: Axis, o: dict[str, Any]) -> float:
    """Donde cae el hueco a lo largo del eje, sin que el llamador sume tramos.

    Sumar 'distance' a mano —recorrer las vueltas del eje llevando la cuenta—
    es aritmetica que el dibujante delega y que sale mal a ojo. Formas
    aceptadas, ademas del 'distance' de siempre:

      {"segment": 1, "offset": 0.8}                — a 0.8 del arranque del
                                                     tramo points[1]→points[2]
      {"segment": 1, "offset": 0.8, "from": "end"} — a 0.8 del FINAL del tramo
      {"segment": 1, "at": "center"}               — centrado en el tramo

    Los tramos se numeran desde 0: el tramo i va de points[i] a points[i+1].
    """
    if "distance" in o:
        return float(o["distance"])
    if "segment" not in o:
        raise ValueError(
            "Cada hueco necesita 'distance' (a lo largo del eje desde el "
            "arranque) o la forma declarativa 'segment' + 'offset' / "
            "at='center'.")
    i = int(o["segment"])
    if not 0 <= i < len(axis.lengths):
        raise ValueError(
            f"El hueco pide el tramo {i}, pero el eje tiene "
            f"{len(axis.lengths)} tramo(s) (numerados desde 0), de largos "
            + ", ".join(f"{la:g}" for la in axis.lengths) + ".")
    base = axis.cumulative[i]
    largo = axis.lengths[i]
    if str(o.get("at", "")).lower() == "center":
        return base + largo / 2.0
    if "offset" not in o:
        raise ValueError(
            f"El hueco en el tramo {i} necesita 'offset' (distancia dentro "
            "del tramo) o at='center'.")
    offset = float(o["offset"])
    if not 0 <= offset <= largo + 1e-9:
        raise ValueError(
            f"El offset {offset:g} se sale del tramo {i}, que mide {largo:g}.")
    if str(o.get("from", "start")).lower() == "end":
        return base + largo - offset
    return base + offset


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
        distance = _resolver_distancia(axis, o)
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
    if holes:
        # La distancia resuelta de cada hueco (centro, a lo largo del eje):
        # con la forma declarativa el llamador no la calculó, y la necesita
        # para acotar o para check_geometry.
        resultado["openingDistances"] = [
            round((h["start"] + h["end"]) / 2.0, 6) for h in holes]
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
