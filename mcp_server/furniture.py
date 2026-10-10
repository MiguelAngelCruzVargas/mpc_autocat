"""Mobiliario esquemático en planta: camas, sillones, comedor, cocina, baño.

Son símbolos, no muebles reales: lo justo para que el cliente lea el uso de cada
espacio. Todo va en su propia capa con trazo fino, para poder apagarlo y quedarse
con la arquitectura sola.

Coordenadas en unidades del modelo (metros si dibujás en metros). Cada pieza se
define en coordenadas locales y se rota alrededor de su punto base, así se puede
apoyar contra cualquier muro.
"""
from __future__ import annotations

import json
import math
from typing import Any, Optional

import autocad_client as acad
import layers
import space

LAYER = "MOBILIARIO"
LW = 18
LW_SOFT = 13  # colchones, cojines: aún más liviano que el contorno

# Alto del texto de superficie relativo al del nombre del ambiente. Medido
# contra un rótulo real: separado para no repetir el mismo 0.72 sin nombre
# en label_rooms(), text_block_size() y label().
AREA_HEIGHT_RATIO = 0.72

# Separación entre las líneas de un nombre partido, en fracción de su altura.
INTERLINEA = 0.35

# Huella de todo lo dibujado, para que los rótulos de ambiente no caigan
# encima de un mueble. Cada entrada es un bounding box (x0, y0, x1, y1).
# El registro real vive en space.FOOTPRINTS: los rotulos de ambiente y los de
# cualquier otro elemento tienen que esquivar las mismas huellas.
OCCUPIED = space.FOOTPRINTS

# Ancho de caracter respecto de la altura. Solo se usa como respaldo si el
# plugin no puede medir: 0.62 se quedaba 40% corto y los rotulos terminaban
# cruzando los muros; 0.87 es lo medido contra AutoCAD real.
CHAR_W = 0.87


def reset_footprints() -> None:
    space.clear_footprints()


def track(x0: float, y0: float, x1: float, y1: float,
          what: str = "mobiliario") -> None:
    """Registra un rectángulo como ocupado."""
    space.track(x0, y0, x1, y1, what)


def _track_points(points: list[tuple[float, float]]) -> None:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    track(min(xs), min(ys), max(xs), max(ys))


def ensure_layer() -> None:
    layers.ensure(LAYER, 8, LW)


def _rot(p: tuple[float, float], base: tuple[float, float],
         deg: float) -> tuple[float, float]:
    if not deg:
        return p
    a = math.radians(deg)
    dx, dy = p[0] - base[0], p[1] - base[1]
    return (base[0] + dx * math.cos(a) - dy * math.sin(a),
            base[1] + dx * math.sin(a) + dy * math.cos(a))


def _poly(points: list[tuple[float, float]], base: tuple[float, float],
          deg: float, lineweight: int = LW, closed: bool = True) -> str:
    pts = [_rot(p, base, deg) for p in points]
    _track_points(pts)
    return acad.call("create_polyline", {
        "points": [[p[0], p[1]] for p in pts], "closed": closed,
        "layer": LAYER, "lineweight": lineweight, "colorIndex": None,
    })["handle"]


def _rect(x: float, y: float, w: float, h: float,
          base: tuple[float, float], deg: float,
          lineweight: int = LW) -> str:
    return _poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)],
                 base, deg, lineweight)


def _circle(cx: float, cy: float, r: float, base: tuple[float, float],
            deg: float, lineweight: int = LW) -> str:
    c = _rot((cx, cy), base, deg)
    track(c[0] - r, c[1] - r, c[0] + r, c[1] + r)
    return acad.call("create_circle", {
        "x": c[0], "y": c[1], "z": 0.0, "radius": r,
        "layer": LAYER, "lineweight": lineweight, "colorIndex": None,
    })["handle"]


def _line(p0: tuple[float, float], p1: tuple[float, float],
          base: tuple[float, float], deg: float,
          lineweight: int = LW) -> str:
    a, b = _rot(p0, base, deg), _rot(p1, base, deg)
    _track_points([a, b])
    return acad.call("create_line", {
        "x1": a[0], "y1": a[1], "z1": 0.0, "x2": b[0], "y2": b[1], "z2": 0.0,
        "layer": LAYER, "lineweight": lineweight, "colorIndex": None,
    })["handle"]


# ------------------------------------------------------------- dormitorio

def bed(x: float, y: float, width: float = 1.60, length: float = 2.00,
        rotation_deg: float = 0.0) -> None:
    """Cama vista en planta. (x,y) es la esquina de la cabecera, a la izquierda.

    Sin rotar, la cabecera queda abajo y la cama se extiende hacia +Y.
    """
    base = (x, y)
    _rect(x, y, width, length, base, rotation_deg)
    # Almohadas contra la cabecera.
    pillow_h = 0.35
    if width >= 1.40:
        gap = 0.06
        pw = (width - 3 * gap) / 2.0
        _rect(x + gap, y + 0.08, pw, pillow_h, base, rotation_deg, LW_SOFT)
        _rect(x + 2 * gap + pw, y + 0.08, pw, pillow_h, base, rotation_deg, LW_SOFT)
    else:
        _rect(x + 0.08, y + 0.08, width - 0.16, pillow_h, base, rotation_deg, LW_SOFT)
    # Doblez del cobertor.
    _line((x, y + length - 0.55), (x + width, y + length - 0.55),
          base, rotation_deg, LW_SOFT)


def nightstand(x: float, y: float, size: float = 0.45,
               rotation_deg: float = 0.0) -> None:
    _rect(x, y, size, size, (x, y), rotation_deg, LW_SOFT)


def closet(x: float, y: float, width: float, depth: float = 0.60,
           rotation_deg: float = 0.0) -> None:
    """Clóset: el mueble y la línea de puertas corredizas."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    _line((x, y + depth * 0.65), (x + width, y + depth * 0.65),
          base, rotation_deg, LW_SOFT)


# ------------------------------------------------------------------- sala

def sofa(x: float, y: float, width: float = 1.90, depth: float = 0.85,
         rotation_deg: float = 0.0) -> None:
    """Sillón. Sin rotar, el respaldo queda abajo y mira hacia +Y."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    back = 0.20
    _line((x, y + back), (x + width, y + back), base, rotation_deg, LW_SOFT)
    arm = 0.20
    _line((x + arm, y + back), (x + arm, y + depth), base, rotation_deg, LW_SOFT)
    _line((x + width - arm, y + back), (x + width - arm, y + depth),
          base, rotation_deg, LW_SOFT)


def armchair(x: float, y: float, size: float = 0.85,
             rotation_deg: float = 0.0) -> None:
    sofa(x, y, size, size * 0.95, rotation_deg)


def coffee_table(x: float, y: float, width: float = 1.10,
                 depth: float = 0.55, rotation_deg: float = 0.0) -> None:
    _rect(x, y, width, depth, (x, y), rotation_deg, LW_SOFT)


# ---------------------------------------------------------------- comedor

def dining_table(cx: float, cy: float, width: float = 1.60,
                 depth: float = 0.90, seats_per_side: int = 3,
                 rotation_deg: float = 0.0) -> None:
    """Mesa de comedor centrada en (cx,cy), con sillas a los cuatro lados."""
    base = (cx, cy)
    x, y = cx - width / 2.0, cy - depth / 2.0
    _rect(x, y, width, depth, base, rotation_deg)

    chair, gap = 0.45, 0.10
    for i in range(seats_per_side):
        step = width / seats_per_side
        cxx = x + step * (i + 0.5) - chair / 2.0
        _rect(cxx, y - gap - chair, chair, chair, base, rotation_deg, LW_SOFT)
        _rect(cxx, y + depth + gap, chair, chair, base, rotation_deg, LW_SOFT)
    for side_x in (x - gap - chair, x + width + gap):
        _rect(side_x, cy - chair / 2.0, chair, chair, base, rotation_deg, LW_SOFT)


# ----------------------------------------------------------------- cocina

def counter(x: float, y: float, width: float, depth: float = 0.60,
            rotation_deg: float = 0.0) -> None:
    """Mesada / barra de cocina."""
    _rect(x, y, width, depth, (x, y), rotation_deg, LW)


def stove(x: float, y: float, width: float = 0.60, depth: float = 0.60,
          rotation_deg: float = 0.0) -> None:
    """Estufa: el mueble y sus cuatro quemadores."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    r = min(width, depth) * 0.11
    for fx in (0.30, 0.70):
        for fy in (0.30, 0.70):
            _circle(x + width * fx, y + depth * fy, r, base, rotation_deg, LW_SOFT)


def kitchen_sink(x: float, y: float, width: float = 0.80, depth: float = 0.60,
                 rotation_deg: float = 0.0) -> None:
    """Fregadero: tarja y escurridor."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    _rect(x + 0.06, y + 0.10, width * 0.5, depth - 0.20, base, rotation_deg, LW_SOFT)


def fridge(x: float, y: float, width: float = 0.70, depth: float = 0.70,
           rotation_deg: float = 0.0) -> None:
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    _line((x + width * 0.5, y), (x + width * 0.5, y + depth),
          base, rotation_deg, LW_SOFT)


# --------------------------------------------------------------- lavado

def laundry_sink(x: float, y: float, width: float = 0.70, depth: float = 0.60,
                 rotation_deg: float = 0.0) -> None:
    """Tarja de lavado: pileta a un lado y lavadero con estrías al otro, que
    es lo que la distingue en planta de un fregadero de cocina."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    pileta = width * 0.45
    _rect(x + 0.05, y + 0.08, pileta - 0.05, depth - 0.16, base, rotation_deg, LW_SOFT)
    x0 = x + pileta + 0.05
    for k in range(1, 5):
        yy = y + 0.08 + (depth - 0.16) * k / 5.0
        _line((x0, yy), (x + width - 0.05, yy), base, rotation_deg, LW_SOFT)


def washer(x: float, y: float, width: float = 0.70, depth: float = 0.70,
           rotation_deg: float = 0.0) -> None:
    """Lavadora: el cuerpo y el tambor."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    _circle(x + width / 2.0, y + depth / 2.0, min(width, depth) * 0.32,
            base, rotation_deg)


# ------------------------------------------------------------------- baño

def wc(x: float, y: float, rotation_deg: float = 0.0) -> None:
    """Inodoro: tanque contra el muro y taza. (x,y) = esquina del tanque."""
    base = (x, y)
    w, tank = 0.38, 0.20
    _rect(x, y, w, tank, base, rotation_deg)
    _circle(x + w / 2.0, y + tank + 0.22, 0.19, base, rotation_deg)


def lavatory(x: float, y: float, width: float = 0.60, depth: float = 0.45,
             rotation_deg: float = 0.0) -> None:
    """Lavabo con su mueble."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    _circle(x + width / 2.0, y + depth * 0.55, min(width, depth) * 0.30,
            base, rotation_deg, LW_SOFT)


def shower(x: float, y: float, width: float = 0.90, depth: float = 0.90,
           rotation_deg: float = 0.0) -> None:
    """Regadera: el plato y las diagonales que la identifican en planta."""
    base = (x, y)
    _rect(x, y, width, depth, base, rotation_deg)
    _line((x, y), (x + width, y + depth), base, rotation_deg, LW_SOFT)
    _line((x + width, y), (x, y + depth), base, rotation_deg, LW_SOFT)


# --------------------------------------------------------------- despacho

# Que puede dibujar place_furniture, y con que medidas por defecto (en metros).
CATALOG = {
    "bed":          (bed,          {"width": 1.60, "length": 2.00}),
    "single_bed":   (bed,          {"width": 1.00, "length": 1.90}),
    "nightstand":   (nightstand,   {"size": 0.45}),
    "closet":       (closet,       {"width": 1.50, "depth": 0.60}),
    "sofa":         (sofa,         {"width": 1.90, "depth": 0.85}),
    "armchair":     (armchair,     {"size": 0.85}),
    "coffee_table": (coffee_table, {"width": 1.10, "depth": 0.55}),
    "dining_table": (dining_table, {"width": 1.60, "depth": 0.90,
                                    "seats_per_side": 3}),
    "counter":      (counter,      {"width": 2.40, "depth": 0.60}),
    "stove":        (stove,        {"width": 0.60, "depth": 0.60}),
    "kitchen_sink": (kitchen_sink, {"width": 0.80, "depth": 0.60}),
    "fridge":       (fridge,       {"width": 0.70, "depth": 0.70}),
    "laundry_sink": (laundry_sink, {"width": 0.70, "depth": 0.60}),
    "washer":       (washer,       {"width": 0.70, "depth": 0.70}),
    "wc":           (wc,           {}),
    "lavatory":     (lavatory,     {"width": 0.60, "depth": 0.45}),
    "shower":       (shower,       {"width": 0.90, "depth": 0.90}),
}

# dining_table se ubica por su CENTRO; el resto por su esquina inferior
# izquierda antes de rotar.
CENTERED = {"dining_table"}


def place(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Dibuja varias piezas de mobiliario de una sola pasada.

    Cada item es {"type": ..., "x": ..., "y": ..., "rotation_deg": ...} mas los
    parametros propios del tipo. Los que no se pasen toman el valor del
    CATALOG.
    """
    ensure_layer()
    placed = []
    # Dos piezas IDENTICAS (mismo tipo, mismo punto, mismas medidas) son
    # siempre un error de quien arma la lista: dibujarlas deja dos contornos
    # exactamente superpuestos, que no se ven en pantalla pero salen como
    # linea doble al plotear y como "entidades duplicadas" en
    # check_drawing_hygiene. Paso de verdad: un modelo mando la lista de
    # suggest_furniture dos veces en la misma llamada y quedaron 32
    # entidades encimadas en MOBILIARIO. Se dibuja la primera y se avisa.
    vistos: set[str] = set()
    repetidos: list[str] = []

    for i, item in enumerate(items):
        kind = str(item.get("type", "")).lower()
        if kind not in CATALOG:
            raise ValueError(
                f"Mueble #{i + 1}: tipo {kind!r} desconocido. "
                f"Disponibles: {', '.join(sorted(CATALOG))}."
            )
        fn, defaults = CATALOG[kind]

        if "x" not in item or "y" not in item:
            raise ValueError(f"Mueble #{i + 1} ({kind}): faltan 'x' y/o 'y'.")

        kwargs = dict(defaults)
        for key, value in item.items():
            if key in ("type", "x", "y"):
                continue
            if key == "rotation_deg":
                kwargs["rotation_deg"] = value
            elif key in defaults:
                kwargs[key] = value
            else:
                raise ValueError(
                    f"Mueble #{i + 1} ({kind}): no acepta {key!r}. "
                    f"Acepta: {', '.join(sorted(defaults) + ['rotation_deg'])}."
                )

        firma = json.dumps([kind, round(float(item["x"]), 4),
                            round(float(item["y"]), 4),
                            sorted((k, str(v)) for k, v in kwargs.items())],
                           sort_keys=True)
        if firma in vistos:
            repetidos.append(f"#{i + 1} {kind} en "
                             f"({item['x']}, {item['y']})")
            continue
        vistos.add(firma)

        fn(float(item["x"]), float(item["y"]), **kwargs)
        placed.append({"type": kind, "x": item["x"], "y": item["y"]})

    resultado: dict[str, Any] = {"placed": placed, "count": len(placed)}
    if repetidos:
        resultado["duplicates"] = repetidos
        resultado["warning"] = (
            "%d pieza(s) venian repetidas y NO se dibujaron de nuevo (%s%s). "
            "Dos muebles identicos en el mismo punto dejan contornos "
            "superpuestos: revisa si la lista se mando dos veces."
            % (len(repetidos), "; ".join(repetidos[:4]),
               "..." if len(repetidos) > 4 else ""))
    return resultado


# ------------------------------------------------- amueblado automatico
#
# La regla de oro del amueblado en planta: casi todo mueble se APOYA CONTRA
# UN MURO, y el muro elegido no puede ser el de la puerta. Con eso resuelto,
# el resto es elegir que pieza va en que ambiente y verificar que quepa.
#
# Todas las piezas del CATALOG se ubican por su esquina inferior izquierda
# ANTES de rotar y, sin rotar, "miran" hacia +Y (respaldo, cabecera o tanque
# abajo). De ahi salen las cuatro colocaciones de _contra_muro.

# Holgura de circulacion que se deja libre delante de un mueble.
PASO_MINIMO = 0.60

# Un muro con puerta no recibe mueble: la hoja barre ese tramo.
_MARGEN_PUERTA = 0.05


def _contra_muro(muro: str, caja: tuple[float, float, float, float],
                 centro: float, ancho: float,
                 fondo: float) -> tuple[float, float, float, tuple]:
    """Donde poner una pieza apoyada contra un muro del recinto.

    Devuelve (x, y, rotacion, huella) donde (x, y) es el punto que espera
    el CATALOG y 'huella' el rectangulo que va a ocupar de verdad.
    'centro' es la posicion a lo LARGO del muro donde va el centro de la
    pieza.
    """
    x0, y0, x1, y1 = caja
    a, f = ancho, fondo
    if muro == "bottom":
        return (centro - a / 2.0, y0, 0.0,
                (centro - a / 2.0, y0, centro + a / 2.0, y0 + f))
    if muro == "top":
        return (centro + a / 2.0, y1, 180.0,
                (centro - a / 2.0, y1 - f, centro + a / 2.0, y1))
    if muro == "left":
        return (x0, centro + a / 2.0, 270.0,
                (x0, centro - a / 2.0, x0 + f, centro + a / 2.0))
    if muro == "right":
        return (x1, centro - a / 2.0, 90.0,
                (x1 - f, centro - a / 2.0, x1, centro + a / 2.0))
    raise ValueError("muro tiene que ser bottom/top/left/right, no %r" % muro)


def _largo_muro(muro: str, caja: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = caja
    return (x1 - x0) if muro in ("bottom", "top") else (y1 - y0)


def _centro_muro(muro: str, caja: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = caja
    return (x0 + x1) / 2.0 if muro in ("bottom", "top") else (y0 + y1) / 2.0


def _fondo_disponible(muro: str,
                      caja: tuple[float, float, float, float]) -> float:
    """Cuanto mide el recinto en la direccion perpendicular a ese muro."""
    x0, y0, x1, y1 = caja
    return (y1 - y0) if muro in ("bottom", "top") else (x1 - x0)


def _muros_con_puerta(caja: tuple[float, float, float, float],
                      nombre: str,
                      doors: list[dict[str, Any]],
                      tol: float = 0.25) -> set[str]:
    """Que muros del recinto tienen una puerta encima."""
    x0, y0, x1, y1 = caja
    ocupados: set[str] = set()
    for d in doors or []:
        if "x" not in d or "y" not in d:
            continue
        nombres = (str(d.get("from", "")).upper(), str(d.get("to", "")).upper())
        if nombre.upper() not in nombres:
            continue
        px, py = float(d["x"]), float(d["y"])
        if abs(py - y0) <= tol and x0 - tol <= px <= x1 + tol:
            ocupados.add("bottom")
        if abs(py - y1) <= tol and x0 - tol <= px <= x1 + tol:
            ocupados.add("top")
        if abs(px - x0) <= tol and y0 - tol <= py <= y1 + tol:
            ocupados.add("left")
        if abs(px - x1) <= tol and y0 - tol <= py <= y1 + tol:
            ocupados.add("right")
    return ocupados


def _muros_libres(caja: tuple[float, float, float, float], nombre: str,
                  doors: list[dict[str, Any]]) -> list[str]:
    """Los muros sin puerta, del mas largo al mas corto."""
    ocupados = _muros_con_puerta(caja, nombre, doors)
    libres = [m for m in ("bottom", "top", "left", "right")
              if m not in ocupados]
    libres.sort(key=lambda m: -_largo_muro(m, caja))
    return libres


def _clase_ambiente(nombre: str) -> str:
    import rules
    return rules._clase(nombre)


def _caja_util(caja: tuple[float, float, float, float],
               limites: tuple[float, float, float, float],
               exterior: float, interior: float,
               tol: float = 1e-6) -> tuple[float, float, float, float]:
    """La caja del recinto medida a la CARA INTERIOR de sus muros.

    suggest_layout define los recintos por el EJE de los muros (dos cuartos
    vecinos comparten la frontera), asi que apoyar un mueble en x0 lo mete
    media pared adentro -- se ve la mesada cruzando el muro y saliendo del
    otro lado, que fue justo lo que aparecio en la primera casa amueblada.
    Hay que retirarse la mitad del espesor, y el espesor depende de si ese
    muro es del perimetro (grueso) o un divisorio (fino).
    """
    x0, y0, x1, y1 = caja
    gx0, gy0, gx1, gy1 = limites

    def mitad(coord: float, borde: float) -> float:
        return (exterior if abs(coord - borde) < tol else interior) / 2.0

    return (x0 + mitad(x0, gx0), y0 + mitad(y0, gy0),
            x1 - mitad(x1, gx1), y1 - mitad(y1, gy1))


def suggest_furniture(rooms: list[dict[str, Any]],
                      doors: Optional[list[dict[str, Any]]] = None,
                      draw: bool = True,
                      exterior_thickness: float = 0.15,
                      interior_thickness: float = 0.10) -> dict[str, Any]:
    """Amuebla la planta entera: qué va en cada ambiente y dónde.

    Es a `place_furniture` lo que `suggest_layout` es a `create_walls`: el
    servidor decide la posición en vez de que alguien la calcule. Un plano
    con los recintos vacíos se ve como un esquema; lo que lo convierte en
    plano de oficina es la cama contra el muro correcto, la estufa que no
    está pegada al fregadero y el WC que no bloquea la puerta.

    Reglas que aplica, todas de amueblado real:
      - ningún mueble contra el muro donde abre una puerta (la hoja barre
        ese tramo)
      - la pieza principal va contra el muro libre MÁS LARGO
      - cama matrimonial si el cuarto la admite con su paso de %.2f m; si
        no, individual; si tampoco, se reporta en 'skipped' en vez de meter
        a la fuerza un mueble que no cabe
      - en la cocina, la estufa y el fregadero nunca quedan pegados
      - lo que no entra NO se dibuja: sale en 'skipped' con el motivo
      - los muebles se apoyan en la CARA INTERIOR del muro, no en su eje:
        'rooms' viene en ejes (dos cuartos vecinos comparten la frontera) y
        apoyar ahi mete el mueble media pared adentro — se veia la mesada
        cruzando el muro y saliendo del otro lado

    rooms/doors: el mismo vocabulario de suggest_layout y draw_layout.
    draw=False devuelve la lista de piezas SIN dibujar, para revisarla o
    ajustarla antes de pasarla a place_furniture.

    Devuelve 'items' (listo para place_furniture), 'byRoom' y 'skipped'.
    """ % PASO_MINIMO
    items: list[dict[str, Any]] = []
    por_ambiente: dict[str, list[str]] = {}
    salteados: list[dict[str, str]] = []

    # Limites del conjunto: definen que muros son del perimetro (gruesos).
    cajas_todas = []
    for i, r in enumerate(rooms or []):
        try:
            cajas_todas.append((float(r["x0"]), float(r["y0"]),
                                float(r["x1"]), float(r["y1"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"El room #{i + 1} necesita name, x0, y0, x1, y1. ({exc})")
    if not cajas_todas:
        return {"items": [], "placements": [], "byRoom": {}, "count": 0,
                "skipped": []}
    limites = (min(c[0] for c in cajas_todas), min(c[1] for c in cajas_todas),
               max(c[2] for c in cajas_todas), max(c[3] for c in cajas_todas))

    for i, r in enumerate(rooms or []):
        nombre = str(r["name"])
        eje = cajas_todas[i]
        # Las puertas vienen en coordenadas de EJE, asi que se buscan sobre
        # la caja de eje; los muebles se ubican en la caja util.
        libres = _muros_libres(eje, nombre, doors or [])
        caja = _caja_util(eje, limites, exterior_thickness,
                          interior_thickness)
        clase = _clase_ambiente(nombre)
        piezas: list[dict[str, Any]] = []

        if clase == "recamara":
            piezas = _amueblar_recamara(caja, libres, nombre, salteados)
        elif clase == "bano":
            piezas = _amueblar_bano(caja, libres, nombre, salteados,
                                    _barridos(eje, caja, nombre, doors or []))
        elif "COCINA" in nombre.upper():
            piezas = _amueblar_cocina(caja, libres, nombre, salteados)
        elif "COMEDOR" in nombre.upper():
            piezas = _amueblar_comedor(caja, nombre, salteados)
        elif clase == "social":
            piezas = _amueblar_sala(caja, libres, nombre, salteados)
        else:
            continue        # pasillo, patio, lavado: sin mobiliario fijo

        piezas = _sin_choques(piezas, caja, _barridos(eje, caja, nombre, doors or []),
                              nombre, salteados)
        if piezas:
            for p in piezas:
                p["_room"] = nombre
            items.extend(piezas)
            por_ambiente[nombre] = [p["type"] for p in piezas]

    # 'items' va limpio para place_furniture (que rechaza claves que no
    # conoce); 'placements' lleva ademas a que ambiente pertenece cada
    # pieza y que caja ocupa -- sin eso, con dos banos y tres recamaras no
    # hay forma de saber cual es cual al verificar el resultado.
    limpios = [{k: v for k, v in p.items() if not k.startswith("_")}
               for p in items]
    resultado: dict[str, Any] = {
        "items": limpios,
        "placements": [{"room": p["_room"], "type": p["type"],
                        "x": p["x"], "y": p["y"],
                        "box": [round(c, 3) for c in p["_box"]]}
                       for p in items],
        "byRoom": por_ambiente,
        "count": len(items),
        "skipped": salteados,
    }
    if draw and items:
        resultado["placed"] = place(resultado["items"])
    return resultado


def _cabe(caja: tuple[float, float, float, float], muro: str,
          ancho: float, fondo: float, paso: float = PASO_MINIMO) -> bool:
    """Entra la pieza contra ese muro, dejando su paso de circulacion."""
    return (_largo_muro(muro, caja) >= ancho + _MARGEN_PUERTA * 2
            and _fondo_disponible(muro, caja) >= fondo + paso)


def _pieza(tipo: str, muro: str, caja, centro: float, ancho: float,
           fondo: float, **extra) -> dict[str, Any]:
    x, y, rot, huella = _contra_muro(muro, caja, centro, ancho, fondo)
    p = {"type": tipo, "x": round(x, 3), "y": round(y, 3),
         "rotation_deg": rot, "_box": huella,
         # Con esto se la puede volver a apoyar más allá sobre el mismo muro.
         "_muro": muro, "_centro": centro, "_dims": (ancho, fondo),
         "_extra": dict(extra)}
    p.update(extra)
    return p


def _barridos(eje: tuple[float, float, float, float],
              caja: tuple[float, float, float, float], nombre: str,
              doors: list[dict[str, Any]], tol: float = 0.25) -> list[tuple]:
    """El cuadrado que barre la hoja de cada puerta que abre HACIA este
    recinto (ancho × ancho, contra la cara interior del muro). Excluir el
    muro de la puerta no alcanzaba: una puerta en la esquina barre también
    el arranque del muro vecino, y ahí caía el buró de la cama."""
    x0, y0, x1, y1 = eje
    cx0, cy0, cx1, cy1 = caja
    out = []
    for d in doors or []:
        if "x" not in d or "y" not in d or d.get("open") \
                or str(d.get("type", "door")).lower() in ("pass", "vano", "opening"):
            continue
        if str(d.get("to", "")).upper() != nombre.upper():
            continue
        px, py, w = float(d["x"]), float(d["y"]), float(d.get("width", 0.80))
        if abs(py - y0) <= tol and x0 - tol <= px <= x1 + tol:
            out.append((px - w / 2.0, cy0, px + w / 2.0, cy0 + w))
        elif abs(py - y1) <= tol and x0 - tol <= px <= x1 + tol:
            out.append((px - w / 2.0, cy1 - w, px + w / 2.0, cy1))
        elif abs(px - x0) <= tol and y0 - tol <= py <= y1 + tol:
            out.append((cx0, py - w / 2.0, cx0 + w, py + w / 2.0))
        elif abs(px - x1) <= tol and y0 - tol <= py <= y1 + tol:
            out.append((cx1 - w, py - w / 2.0, cx1, py + w / 2.0))
    return out


def _sin_choques(piezas: list[dict[str, Any]], caja, obstaculos: list[tuple],
                 nombre: str, salteados: list[dict[str, str]]) -> list[dict]:
    """Ninguna pieza encima del barrido de una puerta ni de otra pieza.

    Cada una se queda donde la propuso su regla si está libre; si no, se
    corre a lo largo de SU muro hasta encontrar lugar. Un buró sigue a su
    cama (se recalcula desde donde quedó la cama) y si no entra se quita.
    Lo que no entra en ningún lado se reporta: dibujar la regadera encima
    del lavabo es peor que no dibujarla."""
    def dentro(b) -> bool:
        return (b[0] >= caja[0] - 1e-6 and b[1] >= caja[1] - 1e-6
                and b[2] <= caja[2] + 1e-6 and b[3] <= caja[3] + 1e-6)

    ocupado = list(obstaculos)
    finales: list[dict[str, Any]] = []
    cama_centro: Optional[float] = None
    # Lo grande elige primero: si el lavabo toma el centro del baño, la
    # regadera ya no tiene dónde ir; al revés, el lavabo se corre y entran
    # los dos. (La cama, mayor que sus burós, sigue yendo antes que ellos.)
    piezas = sorted(piezas, key=lambda p: -((p["_box"][2] - p["_box"][0])
                                            * (p["_box"][3] - p["_box"][1])))

    def libre(b) -> bool:
        return dentro(b) and not any(_overlaps(b, o, -1e-6) for o in ocupado)

    for p in piezas:
        elegido = None
        if "_muro" not in p:
            elegido = p if libre(p["_box"]) else None
        elif "_rel" in p:
            if cama_centro is not None:
                c = _pieza(p["type"], p["_muro"], caja, cama_centro + p["_rel"],
                           *p["_dims"], **p["_extra"])
                elegido = c if libre(c["_box"]) else None
        else:
            largo = _largo_muro(p["_muro"], caja)
            pasos = int(largo / 0.05) + 1
            for k in range(pasos + 1):
                for signo in ((0,) if k == 0 else (1, -1)):
                    c = _pieza(p["type"], p["_muro"], caja,
                               p["_centro"] + signo * k * 0.05,
                               *p["_dims"], **p["_extra"])
                    if libre(c["_box"]):
                        elegido = c
                        break
                if elegido:
                    break
        if elegido is None:
            salteados.append({"room": nombre,
                              "problem": f"{p['type']}: no entra sin pisar el "
                                         "abatimiento de una puerta u otra pieza"})
            continue
        if p["type"] in ("bed", "single_bed"):
            cama_centro = elegido.get("_centro")
        ocupado.append(elegido["_box"])
        finales.append(elegido)
    return finales


def _amueblar_recamara(caja, libres, nombre, salteados) -> list[dict]:
    piezas: list[dict[str, Any]] = []
    # Cama matrimonial si entra con su paso; si no, individual.
    for tipo, ancho, largo in (("bed", 1.60, 2.00),
                               ("single_bed", 1.00, 1.90)):
        muro = next((m for m in libres if _cabe(caja, m, ancho, largo)), None)
        if muro:
            centro = _centro_muro(muro, caja)
            piezas.append(_pieza(tipo, muro, caja, centro, ancho, largo,
                                 width=ancho, length=largo))
            # Buros a los lados, si sobra lugar contra el mismo muro.
            sobra = (_largo_muro(muro, caja) - ancho) / 2.0
            if sobra >= 0.50:
                for signo in (-1, 1):
                    c = centro + signo * (ancho / 2.0 + 0.225)
                    piezas.append(_pieza("nightstand", muro, caja, c,
                                         0.45, 0.45, size=0.45))
                    # El buró va pegado a la cama, donde sea que ella quede.
                    piezas[-1]["_rel"] = signo * (ancho / 2.0 + 0.225)
            # Closet contra otro muro libre.
            otros = [m for m in libres if m != muro]
            for m2 in otros:
                disponible = _largo_muro(m2, caja) - 0.20
                w = min(1.50, disponible)
                if w >= 0.90 and _cabe(caja, m2, w, 0.60):
                    piezas.append(_pieza("closet", m2, caja,
                                         _centro_muro(m2, caja), w, 0.60,
                                         width=round(w, 2), depth=0.60))
                    break
            return piezas
    salteados.append({"room": nombre,
                      "problem": "no entra ni una cama individual con su "
                                 "paso de circulación"})
    return piezas


# Zonas de USO de un baño, no solo el tamaño de la pieza: el WC necesita
# 0.375 m de su eje a lo que tenga al costado y 0.60 libres al frente; el
# lavabo, 0.65 de ancho. Pegados a la regadera "entran", pero no se usan.
ZONA_WC = 0.75
ZONA_LAVABO = 0.65
FONDO_REGADERA = 0.80
FRENTE_LIBRE = 0.60


def _bano_lineal(caja, barridos: list[tuple]) -> Optional[list[dict]]:
    """Regadera a todo el ancho en el extremo LEJOS de la puerta y, en fila
    sobre el muro largo, WC y lavabo con sus zonas de uso. Es el arreglo de
    un baño compacto bien resuelto; None si el cuarto no da para él."""
    x0, y0, x1, y1 = caja
    ancho, fondo = x1 - x0, y1 - y0
    largo, corto = max(ancho, fondo), min(ancho, fondo)
    if (largo < FONDO_REGADERA + ZONA_WC + ZONA_LAVABO - 0.05
            or corto < 0.60 + FRENTE_LIBRE + 0.20):
        return None
    if barridos:
        px = sum((b[0] + b[2]) / 2.0 for b in barridos) / len(barridos)
        py = sum((b[1] + b[3]) / 2.0 for b in barridos) / len(barridos)
    else:
        px, py = x0, y0
    if ancho >= fondo:
        extremo = "right" if px < (x0 + x1) / 2.0 else "left"
        muro = "top" if py < (y0 + y1) / 2.0 else "bottom"
        def a_lo_largo(d: float) -> float:
            return x1 - d if extremo == "right" else x0 + d
    else:
        extremo = "top" if py < (y0 + y1) / 2.0 else "bottom"
        muro = "right" if px < (x0 + x1) / 2.0 else "left"
        def a_lo_largo(d: float) -> float:
            return y1 - d if extremo == "top" else y0 + d
    return [
        _pieza("shower", extremo, caja, _centro_muro(extremo, caja), corto,
               FONDO_REGADERA, width=corto, depth=FONDO_REGADERA),
        _pieza("wc", muro, caja, a_lo_largo(FONDO_REGADERA + ZONA_WC / 2.0),
               0.38, 0.60),
        _pieza("lavatory", muro, caja,
               a_lo_largo(FONDO_REGADERA + ZONA_WC + ZONA_LAVABO / 2.0),
               0.60, 0.45, width=0.60, depth=0.45),
    ]


def _amueblar_bano(caja, libres, nombre, salteados,
                   barridos: Optional[list[tuple]] = None) -> list[dict]:
    lineal = _bano_lineal(caja, barridos or [])
    if lineal:
        return lineal
    piezas: list[dict[str, Any]] = []
    usados: set[str] = set()
    # WC y lavabo en muros distintos; la regadera en el muro mas largo que
    # quede. El paso de un bano es mas corto que el general.
    for tipo, ancho, fondo, extra in (
            ("wc", 0.38, 0.60, {}),
            ("lavatory", 0.60, 0.45, {"width": 0.60, "depth": 0.45}),
            ("shower", 0.90, 0.90, {"width": 0.90, "depth": 0.90})):
        muro = next((m for m in libres
                     if m not in usados and _cabe(caja, m, ancho, fondo, 0.45)),
                    None)
        if not muro:
            salteados.append({"room": nombre,
                              "problem": f"no entra {tipo} en ningún muro libre"})
            continue
        usados.add(muro)
        piezas.append(_pieza(tipo, muro, caja, _centro_muro(muro, caja),
                             ancho, fondo, **extra))
    return piezas


def _amueblar_cocina(caja, libres, nombre, salteados) -> list[dict]:
    piezas: list[dict[str, Any]] = []
    muro = next((m for m in libres if _cabe(caja, m, 2.40, 0.60)), None)
    if not muro:
        salteados.append({"room": nombre,
                          "problem": "no hay muro libre para la mesada"})
        return piezas
    largo = _largo_muro(muro, caja)
    x0, y0, x1, y1 = caja
    inicio = (x0 if muro in ("bottom", "top") else y0) + _MARGEN_PUERTA
    util = largo - _MARGEN_PUERTA * 2

    ancho_mesada = min(util, 2.40)
    fin = inicio + ancho_mesada

    # Fregadero y estufa SEPARADOS sobre la mesada: pegarlos es el error
    # clasico de cocina (no queda superficie de trabajo entre los dos).
    aparatos: list[tuple[float, float, str, float]] = []
    c_sink = inicio + ancho_mesada * 0.25
    aparatos.append((c_sink - 0.40, c_sink + 0.40, "kitchen_sink", 0.80))
    if ancho_mesada >= 1.80:
        c_stove = inicio + ancho_mesada * 0.75
        aparatos.append((c_stove - 0.30, c_stove + 0.30, "stove", 0.60))
    else:
        salteados.append({"room": nombre,
                          "problem": "la mesada es corta para separar la "
                                     "estufa del fregadero"})

    # La mesada se dibuja INTERRUMPIDA por los aparatos, no como un
    # rectangulo entero abajo de ellos. Dibujarla completa deja el contorno
    # del fregadero y el de la estufa encimados sobre el de la mesada: en
    # pantalla se ven lineas dobles y el plano parece mal dibujado -- fue
    # justo lo que se vio al acercarse a la cocina de la casa generada.
    tramos: list[tuple[float, float]] = []
    cursor = inicio
    for a0, a1, _t, _w in sorted(aparatos):
        if a0 - cursor > 0.05:
            tramos.append((cursor, a0))
        cursor = max(cursor, a1)
    if fin - cursor > 0.05:
        tramos.append((cursor, fin))

    for t0, t1 in tramos:
        piezas.append(_pieza("counter", muro, caja, (t0 + t1) / 2.0,
                             t1 - t0, 0.60,
                             width=round(t1 - t0, 3), depth=0.60))
    for a0, a1, tipo, ancho_ap in sorted(aparatos):
        piezas.append(_pieza(tipo, muro, caja, (a0 + a1) / 2.0,
                             ancho_ap, 0.60, width=ancho_ap, depth=0.60))
    # Refrigerador contra otro muro libre.
    for m2 in libres:
        if m2 != muro and _cabe(caja, m2, 0.70, 0.70):
            piezas.append(_pieza("fridge", m2, caja,
                                 _centro_muro(m2, caja), 0.70, 0.70,
                                 width=0.70, depth=0.70))
            break
    return piezas


def _amueblar_comedor(caja, nombre, salteados) -> list[dict]:
    x0, y0, x1, y1 = caja
    ancho, fondo = x1 - x0, y1 - y0
    # La mesa va CENTRADA, no contra un muro: se rodea por los cuatro lados.
    if ancho < 1.60 + PASO_MINIMO * 2 or fondo < 0.90 + PASO_MINIMO * 2:
        # Mesa chica de 4 lugares antes de rendirse.
        if ancho >= 1.20 + PASO_MINIMO * 2 and fondo >= 0.80 + PASO_MINIMO * 2:
            return [{"type": "dining_table", "x": round((x0 + x1) / 2.0, 3),
                     "y": round((y0 + y1) / 2.0, 3), "width": 1.20,
                     "depth": 0.80, "seats_per_side": 2,
                     "_box": ((x0 + x1) / 2.0 - 0.6, (y0 + y1) / 2.0 - 0.4,
                              (x0 + x1) / 2.0 + 0.6, (y0 + y1) / 2.0 + 0.4)}]
        salteados.append({"room": nombre,
                          "problem": "no entra una mesa con su paso "
                                     "alrededor"})
        return []
    return [{"type": "dining_table", "x": round((x0 + x1) / 2.0, 3),
             "y": round((y0 + y1) / 2.0, 3), "width": 1.60, "depth": 0.90,
             "seats_per_side": 3,
             "_box": ((x0 + x1) / 2.0 - 0.8, (y0 + y1) / 2.0 - 0.45,
                      (x0 + x1) / 2.0 + 0.8, (y0 + y1) / 2.0 + 0.45)}]


def _amueblar_sala(caja, libres, nombre, salteados) -> list[dict]:
    piezas: list[dict[str, Any]] = []
    muro = next((m for m in libres if _cabe(caja, m, 1.90, 0.85)), None)
    if not muro:
        salteados.append({"room": nombre,
                          "problem": "no hay muro libre para el sillón"})
        return piezas
    centro = _centro_muro(muro, caja)
    piezas.append(_pieza("sofa", muro, caja, centro, 1.90, 0.85,
                         width=1.90, depth=0.85))
    # Mesa de centro delante del sillon, a 0.45 m.
    x0, y0, x1, y1 = caja
    if _fondo_disponible(muro, caja) >= 0.85 + 0.45 + 0.55:
        dist = 0.85 + 0.45
        if muro == "bottom":
            piezas.append({"type": "coffee_table", "x": centro - 0.55,
                           "y": round(y0 + dist, 3), "rotation_deg": 0.0,
                           "width": 1.10, "depth": 0.55,
                           "_box": (centro - 0.55, y0 + dist,
                                    centro + 0.55, y0 + dist + 0.55)})
        elif muro == "top":
            piezas.append({"type": "coffee_table", "x": centro + 0.55,
                           "y": round(y1 - dist, 3), "rotation_deg": 180.0,
                           "width": 1.10, "depth": 0.55,
                           "_box": (centro - 0.55, y1 - dist - 0.55,
                                    centro + 0.55, y1 - dist)})
        elif muro == "left":
            piezas.append({"type": "coffee_table", "x": round(x0 + dist, 3),
                           "y": centro + 0.55, "rotation_deg": 270.0,
                           "width": 1.10, "depth": 0.55,
                           "_box": (x0 + dist, centro - 0.55,
                                    x0 + dist + 0.55, centro + 0.55)})
        else:
            piezas.append({"type": "coffee_table", "x": round(x1 - dist, 3),
                           "y": centro - 0.55, "rotation_deg": 90.0,
                           "width": 1.10, "depth": 0.55,
                           "_box": (x1 - dist - 0.55, centro - 0.55,
                                    x1 - dist, centro + 0.55)})
    return piezas


# Abreviaturas de rótulo como las escribe un dibujante. Se prefieren a
# achicar la letra: "REC. PPAL." se lee; un texto de 1 mm en papel, no.
ABREVIATURAS = {
    "RECÁMARA": "REC.", "RECAMARA": "REC.", "HABITACIÓN": "HAB.",
    "HABITACION": "HAB.", "DORMITORIO": "DORM.", "PRINCIPAL": "PPAL.",
    "SECUNDARIA": "SEC.", "SECUNDARIO": "SEC.", "ESTANCIA": "EST.",
    "COMEDOR": "COM.", "COCINA": "COC.", "SERVICIO": "SERV.",
    "LAVADO": "LAV.", "LAVANDERÍA": "LAV.", "LAVANDERIA": "LAV.",
    "VESTÍBULO": "VEST.", "VESTIBULO": "VEST.", "PASILLO": "PAS.",
    "ESTUDIO": "ESTUD.", "COCHERA": "COCH.", "VESTIDOR": "VEST.",
    "COMPLETO": "COMPL.", "INTERIOR": "INT.",
}


def _abreviar(nombre: str) -> Optional[str]:
    """'RECÁMARA PRINCIPAL' -> 'REC. PPAL.'; las palabras de enlace ('DE')
    se caen si quedan entre abreviaturas. None si no hay nada que abreviar."""
    palabras = nombre.split()
    nuevas = [ABREVIATURAS.get(p, p) for p in palabras]
    if nuevas == palabras:
        return None
    nuevas = [p for p in nuevas if p not in ("DE", "DEL", "LA", "EL")] or nuevas
    return " ".join(nuevas)


def _partir(nombre: str) -> Optional[str]:
    """El nombre en dos líneas, cortando en el espacio más cercano al medio
    ("RECÁMARA PRINCIPAL" -> "RECÁMARA\\nPRINCIPAL"). None si es una palabra."""
    espacios = [i for i, ch in enumerate(nombre) if ch == " "]
    if not espacios:
        return None
    corte = min(espacios, key=lambda i: abs(i - len(nombre) / 2.0))
    return nombre[:corte] + "\n" + nombre[corte + 1:]


def label_rooms(rooms: list[dict[str, Any]], height: float,
                area_height: float = 0.0, layer: str = "TEXTOS",
                show_area: bool = True, inset: float = 0.075) -> dict[str, Any]:
    """Rotula ambientes esquivando el mobiliario ya dibujado.

    Cada room es {"name":..., "x0":..., "y0":..., "x1":..., "y1":...}. Usa las
    huellas registradas por place() para no poner el texto encima de una cama.

    Los rooms vienen en EJES: el texto se mide contra la cara interior del
    muro ('inset' = medio espesor), no contra el eje. Si no entra, se prueba
    en este orden: partido en dos líneas, más chico (hasta 65 %, que en
    papel sigue legible) y por último sin la superficie. Antes, el segundo
    intento no verificaba nada: "RECÁMARA PRINCIPAL" en un cuarto de 2.2 m
    salía cruzando los dos muros. Si ni así entra, va en 'warnings'.
    """
    layers.ensure(layer, 7, 25)
    out = []
    avisos: list[str] = []
    ah = area_height or height * AREA_HEIGHT_RATIO

    for i, room in enumerate(rooms):
        try:
            name = str(room["name"]).upper()
            ejes = (float(room["x0"]), float(room["y0"]),
                    float(room["x1"]), float(room["y1"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Ambiente #{i + 1}: hace falta name, x0, y0, x1, y1. ({exc})")
        izq, abj, der, arr = _retiros(ejes, room.get("inset", inset))
        box = (ejes[0] + izq, ejes[1] + abj, ejes[2] - der, ejes[3] - arr)
        area = ((box[2] - box[0]) * (box[3] - box[1])) if show_area else None
        # Nivel de piso ("N.P.T. +0.15") como tercera línea del rótulo: suelto,
        # como texto aparte, terminaba sobre un muro o afuera del terreno.
        nivel = str(room["level"]) if room.get("level") else None

        partido = _partir(name)
        abrev = _abreviar(name)
        abrev_partido = _partir(abrev) if abrev else None
        # Orden de oficio: completo, partido, ABREVIADO (antes de achicar la
        # letra), y recién después más chico.
        variantes = [t for t in (name, partido, abrev, abrev_partido) if t]
        intentos = []
        for factor in (1.0, 0.8, 0.65):
            for texto in variantes:
                intentos.append((texto, height * factor, area, ah * factor))
        if area is not None:
            for texto in variantes:
                intentos.append((texto, height * 0.65, None, 0.0))

        # El aire alrededor (12 cm) es para que el rótulo respire en un cuarto
        # normal; en un baño de 1.35 m sobra, así que la última vuelta lo
        # baja a 3 cm antes de declarar que no entra.
        elegido = None
        for margen in (0.12, 0.03):
            for texto, hh, ar, ahh in intentos:
                spot, fitted = find_label_spot(box, texto, hh, ar, ahh,
                                               margin=margen, level=nivel)
                if fitted:
                    elegido = (texto, hh, ar, ahh, spot)
                    break
            if elegido:
                break
        if elegido is None:
            texto, hh, ar, ahh = intentos[-1]
            spot, _ = find_label_spot(box, texto, hh, ar, ahh, level=nivel)
            elegido = (texto, hh, ar, ahh, spot)
            avisos.append(
                f"El rótulo '{name}' no entra en su recinto ni partido ni "
                f"achicado (ancho libre {box[2] - box[0]:.2f} m): abreviá el "
                "nombre o rotulalo afuera con un leader.")

        texto, hh, ar, ahh, spot = elegido
        label(texto, spot[0], spot[1], height=hh, layer=layer,
              area=ar, area_height=ahh, level=nivel)
        out.append({"name": name, "x": spot[0], "y": spot[1],
                    "text": texto.replace("\n", " "),
                    "area": round(ar, 2) if ar else None,
                    "lines": texto.count("\n") + 1,
                    "height": round(hh, 4),
                    "cramped": elegido[0] != name or hh < height or ar is None})

    r: dict[str, Any] = {"labeled": out, "count": len(out)}
    if avisos:
        r["warnings"] = avisos
    return r


# ------------------------------------------------------------------ otros

_MEASURE_CACHE: dict[tuple[str, float], float] = {}
_MEASURE_OK = [True]


def measure(text: str, height: float) -> float:
    """Ancho real del texto. Le pregunta a AutoCAD y cachea la respuesta.

    La estimación por cantidad de caracteres se queda corta con fuentes anchas
    y el rótulo termina desbordando el ambiente, asi que solo se usa como
    respaldo si el plugin no sabe medir (version vieja o sin conexion).
    """
    key = (text, round(height, 6))
    if key in _MEASURE_CACHE:
        return _MEASURE_CACHE[key]

    width = len(text) * height * CHAR_W
    if _MEASURE_OK[0]:
        try:
            width = acad.call("measure_text", {
                "text": text, "height": height,
                "style": None, "widthFactor": None})["width"]
        except (Exception, KeyError):
            # Una sola vez: si el plugin no lo soporta, no reintentamos por
            # cada texto del plano.
            _MEASURE_OK[0] = False

    _MEASURE_CACHE[key] = width
    return width


def _sublineas(area: Optional[float], level: Optional[str]) -> list[str]:
    """Las líneas chicas debajo del nombre: superficie y nivel (N.P.T.)."""
    return ([f"{area:.2f} m2"] if area is not None else []) + ([level] if level else [])


def text_block_size(text: str, height: float, area: Optional[float] = None,
                    area_height: float = 0.0, level: Optional[str] = None
                    ) -> tuple[float, float]:
    """Cuánto mide el bloque nombre + superficie + nivel, en unidades del
    modelo. El nombre puede venir en varias líneas ('\\n')."""
    lineas = text.split("\n")
    w = max(measure(l, height) for l in lineas)
    h = height * len(lineas) + height * INTERLINEA * (len(lineas) - 1)
    ah = area_height or height * AREA_HEIGHT_RATIO
    for sub in _sublineas(area, level):
        w = max(w, measure(sub, ah))
        h += ah * 1.5
    return w, h


def label(text: str, cx: float, cy: float, height: float,
          layer: str = "TEXTOS", lineweight: int = 25,
          area: Optional[float] = None, area_height: float = 0.0,
          level: Optional[str] = None) -> None:
    """Nombre del ambiente, su superficie y su nivel, CENTRADOS en (cx, cy).

    DBText se ancla abajo a la izquierda, así que acá se calcula el ancla a
    partir del centro pedido: quien llama razona con el centro del bloque, que
    es lo que hace falta para ubicarlo en un hueco libre.
    """
    name = text.upper()
    _, block_h = text_block_size(name, height, area, area_height, level)
    top = cy + block_h / 2.0

    for k, linea in enumerate(name.split("\n")):
        acad.call("create_text", {
            "text": linea,
            "x": cx - measure(linea, height) / 2.0,
            "y": top - height - k * height * (1.0 + INTERLINEA), "z": 0.0,
            "height": height, "layer": layer, "rotationDeg": 0.0,
            "lineweight": lineweight, "colorIndex": None,
        })
    ah = area_height or height * AREA_HEIGHT_RATIO
    subs = _sublineas(area, level)
    for k, txt in enumerate(subs):
        # De abajo hacia arriba: la última sublínea apoya en el pie del bloque.
        acad.call("create_text", {
            "text": txt,
            "x": cx - measure(txt, ah) / 2.0,
            "y": cy - block_h / 2.0 + (len(subs) - 1 - k) * ah * 1.5, "z": 0.0,
            "height": ah, "layer": layer, "rotationDeg": 0.0,
            "lineweight": 13, "colorIndex": None,
        })


def _overlaps(a: tuple[float, float, float, float],
              b: tuple[float, float, float, float], gap: float) -> bool:
    return not (a[2] + gap <= b[0] or a[0] - gap >= b[2]
                or a[3] + gap <= b[1] or a[1] - gap >= b[3])


def _clearance(box: tuple[float, float, float, float],
               obstacles: list[tuple[float, float, float, float]]) -> float:
    """Distancia al obstáculo más cercano (0 si toca alguno)."""
    best = float("inf")
    for o in obstacles:
        dx = max(o[0] - box[2], box[0] - o[2], 0.0)
        dy = max(o[1] - box[3], box[1] - o[3], 0.0)
        best = min(best, (dx * dx + dy * dy) ** 0.5)
    return best


def _retiros(ejes: tuple[float, float, float, float],
             inset: float) -> tuple[float, float, float, float]:
    """Medio muro hacia adentro (izq, abajo, der, arriba), pero SOLO en los
    lados donde hay un muro registrado. Una cochera sin muros perdía medio
    muro por lado y salía 28.43 m2 en vez de 30.10: una superficie falsa en
    el rótulo. Si no hay ningún muro registrado (el plano lo dibujó otro
    proceso), se descuenta en los cuatro lados como antes."""
    muros = [b for b in space.barriers()]
    if not muros or inset <= 0:
        return (max(inset, 0.0),) * 4
    x0, y0, x1, y1 = ejes
    tol = max(inset, 1e-6) * 1.5

    def cubierto(vertical: bool, c: float, a0: float, a1: float) -> bool:
        largo = 0.0
        for b in muros:
            if vertical:
                if b["x0"] - tol <= c <= b["x1"] + tol:
                    largo += max(0.0, min(a1, b["y1"]) - max(a0, b["y0"]))
            elif b["y0"] - tol <= c <= b["y1"] + tol:
                largo += max(0.0, min(a1, b["x1"]) - max(a0, b["x0"]))
        return largo >= 0.3 * (a1 - a0)

    return (inset if cubierto(True, x0, y0, y1) else 0.0,
            inset if cubierto(False, y0, x0, x1) else 0.0,
            inset if cubierto(True, x1, y0, y1) else 0.0,
            inset if cubierto(False, y1, x0, x1) else 0.0)


def find_label_spot(room: tuple[float, float, float, float],
                    text: str, height: float,
                    area: Optional[float] = None, area_height: float = 0.0,
                    margin: float = 0.12, steps: int = 16,
                    level: Optional[str] = None
                    ) -> tuple[tuple[float, float], bool]:
    """Dónde poner el rótulo de un ambiente sin taparle el mobiliario.

    Barre posiciones dentro del ambiente y se queda con la que tiene más aire
    alrededor, prefiriendo las cercanas al centro cuando empatan. Devuelve
    ((cx, cy), cupo) — si `cupo` es False no había ningún lugar libre y se
    devuelve el centro del ambiente igual, para no dejar el ambiente sin
    rotular.
    """
    x0, y0, x1, y1 = room
    w, h = text_block_size(text.upper(), height, area, area_height, level)

    half_w, half_h = w / 2.0 + margin, h / 2.0 + margin
    min_cx, max_cx = x0 + half_w, x1 - half_w
    min_cy, max_cy = y0 + half_h, y1 - half_h
    room_cx, room_cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0

    if min_cx > max_cx or min_cy > max_cy:
        # Ni vacío entra: va al centro igual, para que el ambiente no quede sin
        # rotular, y que la persona lo mueva. Peor seria dejarlo afuera.
        return (room_cx, room_cy), False

    # Solo estorban las huellas que caen dentro de este ambiente: muebles,
    # muros y textos (OCCUPIED) Y las franjas de cotas (space.OCCUPIED). Sin
    # las segundas, el rótulo de un espacio sin muros (una cochera) caía
    # encima de la cadena de cotas que la cruza.
    obstacles = [(h["x0"], h["y0"], h["x1"], h["y1"])
                 for h in list(OCCUPIED) + list(space.OCCUPIED)
                 if _overlaps((h["x0"], h["y0"], h["x1"], h["y1"]),
                              (x0, y0, x1, y1), 0.0)]

    best = None
    for i in range(steps + 1):
        for j in range(steps + 1):
            cx = min_cx + (max_cx - min_cx) * (i / steps if steps else 0.5)
            cy = min_cy + (max_cy - min_cy) * (j / steps if steps else 0.5)
            box = (cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)
            if any(_overlaps(box, o, margin) for o in obstacles):
                continue
            clear = _clearance(box, obstacles)
            # Con holgura parecida, gana el más centrado.
            dist = abs(cx - room_cx) + abs(cy - room_cy)
            score = (round(clear, 2), -dist)
            if best is None or score > best[0]:
                best = (score, (cx, cy))

    if best is None:
        # Todo el ambiente esta ocupado: al centro, pero SIEMPRE clampeado
        # adentro del cuarto — un rotulo cruzando un muro no se entiende.
        cx = min(max(room_cx, min_cx), max_cx)
        cy = min(max(room_cy, min_cy), max_cy)
        return (cx, cy), False
    return best[1], True
