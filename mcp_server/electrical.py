"""Simbologia electrica en planta: salidas, apagadores, contactos, tableros
y la canalizacion que los une.

Son simbolos normalizados y siempre iguales -un circulo con cruz es una salida
de techo en cualquier plano del pais-, asi que dibujarlos con create_circle y
create_line cada vez es la definicion de lo que NO tiene que pasar: la
capacidad es reutilizable y va a la biblioteca.

Cada dispositivo registra su huella en space.FOOTPRINTS, asi que place_labels
puede rotularlos sin escribir encima y la canalizacion sabe de que punto sale.

Unidades: las del modelo. Los tamanos de simbolo son medidas REALES de obra
(un contacto se dibuja de 0.15 m de radio), no milimetros de papel.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad
from geom import densify
import layers
import space

LAYER_LIGHT = "ALUMBRADO"
LAYER_OUTLET = "CONTACTOS"
LAYER_PANEL = "CENTRO_CARGA"
LAYER_CONDUIT = "TUBERIA"

LW_SYMBOL = 25
LW_PANEL = 40
LW_CONDUIT = 20

# Tamanos normalizados, en metros de obra.
D_LAMPARA = 0.30
D_APAGADOR = 0.20
R_CONTACTO = 0.15
PANEL_W, PANEL_H = 0.40, 0.15

TIPOS = ("lamp", "switch", "outlet", "gfci", "panel")


def _line(p0, p1, layer: str, lw: int) -> str:
    return acad.call("create_line", {
        "x1": p0[0], "y1": p0[1], "z1": 0.0,
        "x2": p1[0], "y2": p1[1], "z2": 0.0,
        "layer": layer, "lineweight": lw, "colorIndex": None})["handle"]


def _circle(c, r: float, layer: str, lw: int) -> str:
    return acad.call("create_circle", {
        "x": c[0], "y": c[1], "z": 0.0, "radius": r,
        "layer": layer, "lineweight": lw, "colorIndex": None})["handle"]


def _arc(c, r: float, a0: float, a1: float, layer: str, lw: int) -> str:
    return acad.call("create_arc", {
        "x": c[0], "y": c[1], "z": 0.0, "radius": r,
        "startAngleDeg": a0 % 360.0, "endAngleDeg": a1 % 360.0,
        "layer": layer, "lineweight": lw, "colorIndex": None})["handle"]


def _poly(points, layer: str, lw: int, closed: bool = True,
          bulges: Optional[list[float]] = None) -> str:
    return acad.call("create_polyline", {
        "points": [[p[0], p[1]] for p in points], "bulges": bulges,
        "closed": closed, "layer": layer,
        "lineweight": lw, "colorIndex": None})["handle"]


def _hatch(handle: str, layer: str) -> None:
    try:
        acad.call("create_hatch", {
            "boundaryHandle": handle, "pattern": "SOLID", "scale": 1.0,
            "angleDeg": 0.0, "layer": layer, "lineweight": 9,
            "colorIndex": None})
    except acad.AutoCadError:
        pass


# ------------------------------------------------------- dispositivos

def place_devices(devices: list[dict[str, Any]],
                  light_layer: str = LAYER_LIGHT,
                  outlet_layer: str = LAYER_OUTLET,
                  panel_layer: str = LAYER_PANEL,
                  hatch_layer: str = "",
                  lineweight: int = LW_SYMBOL) -> dict[str, Any]:
    """Dibuja la simbologia de una instalacion electrica en planta.

    devices: cada uno {"type": ..., "x": .., "y": .., "angle": grados, ...}
      - "lamp"   salida de techo: circulo de 0.30 con cruz interior.
      - "switch" apagador: circulo de 0.20 con la linea radial que lo
        identifica. 'angle' apunta la linea hacia el ambiente.
      - "outlet" contacto: semicirculo de 0.15 apoyado en el muro; 'angle'
        es hacia donde abre (hacia el ambiente). "double": True le agrega la
        barra del contacto doble.
      - "gfci"   igual que outlet, con el circuito de falla a tierra marcado.
      - "panel"  tablero: rectangulo de 0.40 x 0.15 con medio relleno solido.
        'angle' lo alinea con el muro donde se monta.
    Opcionales: "size" para cambiar el tamano de ese simbolo, y "tag" que se
    devuelve tal cual para poder rotularlo despues con place_labels.

    Devuelve, por dispositivo, su punto y su caja: es lo que necesitan
    create_conduit para salir del borde del simbolo y place_labels para no
    escribirle encima.
    """
    if not devices:
        raise ValueError("No hay dispositivos que dibujar.")

    dibujados = []
    for i, d in enumerate(devices, start=1):
        tipo = str(d.get("type", "")).lower()
        if tipo not in TIPOS:
            raise ValueError(
                f"Dispositivo #{i}: tipo {tipo!r} desconocido. "
                f"Usa uno de {', '.join(TIPOS)}.")
        try:
            x, y = float(d["x"]), float(d["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Dispositivo #{i} necesita 'x' e 'y'. ({exc})")
        ang = float(d.get("angle", 0.0))

        if tipo == "lamp":
            caja = _lamp(x, y, float(d.get("size", D_LAMPARA)),
                         light_layer, lineweight)
        elif tipo == "switch":
            caja = _switch(x, y, ang, float(d.get("size", D_APAGADOR)),
                           light_layer, lineweight)
        elif tipo in ("outlet", "gfci"):
            caja = _outlet(x, y, ang, float(d.get("size", R_CONTACTO)),
                           outlet_layer, lineweight,
                           double=bool(d.get("double", False)),
                           gfci=(tipo == "gfci"))
        else:
            caja = _panel(x, y, ang, panel_layer, hatch_layer or panel_layer,
                          LW_PANEL)

        space.track(*caja, what=f"{tipo} {d.get('tag', '')}".strip())
        dibujados.append({"type": tipo, "tag": d.get("tag", ""),
                          "x": round(x, 4), "y": round(y, 4),
                          "box": [round(v, 4) for v in caja]})

    return {"devices": dibujados, "count": len(dibujados)}


def _lamp(x: float, y: float, d: float, layer: str, lw: int):
    r = d / 2.0
    _circle((x, y), r, layer, lw)
    # La cruz va inscrita: es lo que distingue una salida de techo de un
    # circulo cualquiera.
    _line((x - r, y), (x + r, y), layer, lw)
    _line((x, y - r), (x, y + r), layer, lw)
    return (x - r, y - r, x + r, y + r)


def _switch(x: float, y: float, ang: float, d: float, layer: str, lw: int):
    r = d / 2.0
    _circle((x, y), r, layer, lw)
    a = math.radians(ang)
    largo = r * 1.8
    p1 = (x + math.cos(a) * r, y + math.sin(a) * r)
    p2 = (x + math.cos(a) * (r + largo), y + math.sin(a) * (r + largo))
    _line(p1, p2, layer, lw)
    xs = [x - r, x + r, p2[0]]
    ys = [y - r, y + r, p2[1]]
    return (min(xs), min(ys), max(xs), max(ys))


def _outlet(x: float, y: float, ang: float, r: float, layer: str, lw: int,
            double: bool, gfci: bool):
    # El semicirculo abre hacia el ambiente y la cuerda apoya en el muro.
    _arc((x, y), r, ang - 90.0, ang + 90.0, layer, lw)
    a = math.radians(ang)
    nx, ny = -math.sin(a), math.cos(a)
    c0 = (x - nx * r, y - ny * r)
    c1 = (x + nx * r, y + ny * r)
    _line(c0, c1, layer, lw)
    if double:
        # La barra del contacto doble, paralela a la cuerda y adentro.
        f = r * 0.45
        _line((c0[0] + math.cos(a) * f, c0[1] + math.sin(a) * f),
              (c1[0] + math.cos(a) * f, c1[1] + math.sin(a) * f), layer, lw)
    if gfci:
        # Falla a tierra: la marca radial que lo separa de un contacto comun.
        _line((x, y), (x + math.cos(a) * r, y + math.sin(a) * r), layer, lw)
    return (x - r, y - r, x + r, y + r)


def _panel(x: float, y: float, ang: float, layer: str, hatch_layer: str,
           lw: int):
    a = math.radians(ang)
    ux, uy = math.cos(a), math.sin(a)          # a lo largo del muro
    nx, ny = -uy, ux                           # hacia el ambiente
    hw, hh = PANEL_W / 2.0, PANEL_H / 2.0

    def esquina(su, sn):
        return (x + ux * hw * su + nx * hh * sn,
                y + uy * hw * su + ny * hh * sn)

    _poly([esquina(-1, -1), esquina(1, -1), esquina(1, 1), esquina(-1, 1)],
          layer, lw)
    # Medio relleno solido: es como se distingue un tablero de un registro.
    mitad = _poly([esquina(-1, -1), esquina(0, -1), esquina(0, 1),
                   esquina(-1, 1)], layer, lw)
    _hatch(mitad, hatch_layer)

    xs = [esquina(su, sn)[0] for su in (-1, 1) for sn in (-1, 1)]
    ys = [esquina(su, sn)[1] for su in (-1, 1) for sn in (-1, 1)]
    return (min(xs), min(ys), max(xs), max(ys))


# ------------------------------------------------------- canalizacion

def create_conduit(points: list[list[float]], sag: float = 0.0,
                   conductors: str = "", layer: str = LAYER_CONDUIT,
                   lineweight: int = LW_CONDUIT,
                   mark_size: float = 0.0,
                   text_height: float = 0.0) -> dict[str, Any]:
    """Un tramo de canalizacion entre dispositivos, con sus conductores.

    En un plano electrico la tuberia no se dibuja recta de aparato a aparato:
    va en arco suave, para que se distinga de la muraria y para que dos
    circuitos que comparten trayecto no se superpongan en la misma linea.

    points: por donde pasa, normalmente el centro de cada dispositivo.
    sag: cuanto se arquea cada tramo respecto de la recta, como fraccion de su
    largo. 0.12 es un arco suave; 0 lo deja recto.
    conductors: los conductores que van adentro, como se marcan sobre la
    tuberia: '/' cada fase, '|' cada neutro, 'T' la tierra. '//|T' son dos
    fases, un neutro y tierra.
    mark_size: largo de las marcas; por defecto proporcional al tramo.
    """
    if len(points) < 2:
        raise ValueError("Una canalizacion necesita al menos 2 puntos.")
    for c in conductors:
        if c not in "/|T":
            raise ValueError(
                f"Conductor {c!r} desconocido: usa '/' fase, '|' neutro, "
                "'T' tierra.")

    layers.ensure(layer, layers.COLOR_HIDRAULICA, lineweight)
    pts = [(float(p[0]), float(p[1])) for p in points]
    # tan(barrido/4): un bulge de 0.12 es una flecha del 12% de la cuerda.
    bulges = [sag if i < len(pts) - 1 else 0.0 for i in range(len(pts))]
    handle = _poly(pts, layer, lineweight, closed=False, bulges=bulges)

    # El recorrido REAL, siguiendo los arcos. Medir sobre la cuerda daria un
    # largo menor que el tubo que se instala, y -peor- pondria las marcas de
    # conductores sobre la recta y no sobre el arco: en un tramo de 5.76 m con
    # sag 0.10 quedaban 29 cm afuera del tubo, flotando en el dibujo.
    fino = densify([[p[0], p[1]] for p in pts], bulges) if sag else         [[p[0], p[1]] for p in pts]
    largo = sum(math.dist(a, b) for a, b in zip(fino, fino[1:]))

    marcas = []
    if conductors:
        # Sobre el tramo mas largo, que es donde se leen.
        i = max(range(len(pts) - 1), key=lambda k: math.dist(pts[k], pts[k + 1]))
        sub = _tramo_fino(fino, pts, i, bool(sag))
        tramo = sum(math.dist(a, b) for a, b in zip(sub, sub[1:]))
        s = mark_size or min(0.22, max(0.10, tramo * 0.10))
        paso = min(s * 0.75, tramo / (len(conductors) + 1))
        d0 = tramo / 2.0 - paso * (len(conductors) - 1) / 2.0
        for k, c in enumerate(conductors):
            (px, py), (ux, uy) = _sobre(sub, d0 + paso * k)
            nx, ny = -uy, ux
            if c == "/":
                dx, dy = (ux + nx) / math.sqrt(2), (uy + ny) / math.sqrt(2)
            else:
                dx, dy = nx, ny
            _line((px - dx * s / 2, py - dy * s / 2),
                  (px + dx * s / 2, py + dy * s / 2), layer, lineweight)
            if c == "T":
                h = text_height or s * 0.7
                acad.call("create_text", {
                    "text": "T", "x": px + nx * (s / 2 + h * 0.2) - h * 0.3,
                    "y": py + ny * (s / 2 + h * 0.2), "z": 0.0, "height": h,
                    "layer": layer, "rotationDeg": 0.0,
                    "lineweight": lineweight, "colorIndex": None})
            marcas.append({"kind": c, "x": round(px, 4), "y": round(py, 4)})

    return {"handle": handle, "length": round(largo, 4),
            "sag": sag, "conductors": conductors, "marks": marcas}


def _tramo_fino(fino: list[list[float]], pts: list, i: int,
                hay_arco: bool) -> list[list[float]]:
    """Los puntos muestreados que corresponden al tramo i del recorrido."""
    if not hay_arco:
        return [list(pts[i]), list(pts[i + 1])]
    # densify conserva los vertices originales en orden: se corta entre el
    # que coincide con pts[i] y el que coincide con pts[i+1].
    def idx(p):
        return min(range(len(fino)),
                   key=lambda k: math.dist(fino[k], (p[0], p[1])))
    a, b = idx(pts[i]), idx(pts[i + 1])
    return fino[min(a, b):max(a, b) + 1]


def _sobre(path: list[list[float]], d: float):
    """Punto y tangente a una distancia d recorriendo la poligonal fina."""
    acum = 0.0
    for a, b in zip(path, path[1:]):
        largo = math.dist(a, b)
        if largo < 1e-12:
            continue
        if acum + largo >= d or b is path[-1]:
            t = max(0.0, min(1.0, (d - acum) / largo))
            u = ((b[0] - a[0]) / largo, (b[1] - a[1]) / largo)
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), u
        acum += largo
    a, b = path[-2], path[-1]
    largo = math.dist(a, b) or 1.0
    return (b[0], b[1]), ((b[0] - a[0]) / largo, (b[1] - a[1]) / largo)
