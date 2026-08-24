"""Los simbolos de convencion que hacen que un plano se lea como un plano.

Son tres cosas que aparecen en cualquier juego profesional y que hasta ahora
habia que armar a mano con create_text + create_line sueltos:

  - la marca de nivel (N.P.T.) en cortes y fachadas,
  - el titulo de vista con su subrayado y su escala,
  - la marca de corte, que es lo unico que liga una planta con su seccion.

El motivo de que vivan aca y no en la cabeza de quien dibuja es el mismo de
siempre: un simbolo normalizado tiene que salir IGUAL en todas las laminas. La
marca de nivel armada a mano ya se encimo de verdad en un plano -dos
create_text con "N.P.T. +1.40" y "DESCANSO" uno arriba del otro-, que es el
caso que test_text_tracking.py dejo fijado.

Todo se compone con las tools basicas del plugin: se cambia sin recompilar.
Unidades: las del modelo (metros si dibujas en metros).
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad
import layers
import space

LAYER_LEVEL = "NIVELES"
LAYER_TITLE = "TITULOS"
LAYER_MARK = "MARCAS-CORTE"

# Grosores. La marca de corte es de los trazos mas gruesos del plano a
# proposito: tiene que saltar a la vista sobre la planta que la lleva.
LW_LEVEL = 18
LW_TITLE_TEXT = 35
LW_TITLE_RULE = 50
LW_MARK = 50
LW_MARK_TEXT = 25

# Azul acero, no el 5. Ver CLAUDE.md 6.ter: el azul puro imprime bien pero no
# se lee sobre el fondo del espacio modelo. El plano de referencia usa azul
# para los titulos de vista; este es el equivalente que se ve en los dos medios.
COLOR_TITLE = 152


def _layer(name: str, color: int, lineweight: int) -> None:
    layers.ensure(name, color, lineweight)
    layers.ensure_text_style()


def _line(x1: float, y1: float, x2: float, y2: float, layer: str,
          lineweight: int, color: Optional[int] = None) -> str:
    return acad.call("create_line", {
        "x1": x1, "y1": y1, "z1": 0.0, "x2": x2, "y2": y2, "z2": 0.0,
        "layer": layer, "lineweight": lineweight, "colorIndex": color,
    })["handle"]


def _poly(points: list[list[float]], closed: bool, layer: str,
          lineweight: int, color: Optional[int] = None) -> str:
    return acad.call("create_polyline", {
        "points": points, "closed": closed, "layer": layer,
        "lineweight": lineweight, "colorIndex": color,
    })["handle"]


def _text(content: str, x: float, y: float, height: float, layer: str,
          lineweight: int, color: Optional[int] = None,
          rotation: float = 0.0) -> Optional[str]:
    if not content:
        return None
    return acad.call("create_text", {
        "text": content, "x": x, "y": y, "z": 0.0, "height": height,
        "layer": layer, "rotationDeg": rotation,
        "lineweight": lineweight, "colorIndex": color,
    })["handle"]


def _solid(handle: str, layer: str, color: Optional[int] = None) -> Optional[str]:
    """Relleno solido de un contorno cerrado ya dibujado."""
    try:
        return acad.call("create_hatch", {
            "boundaryHandle": handle, "pattern": "SOLID", "scale": 1.0,
            "angleDeg": 0.0, "layer": layer,
            "lineweight": 5, "colorIndex": color,
        })["handle"]
    except acad.AutoCadError:
        # Un relleno que no sale no debe tumbar el simbolo entero: el
        # contorno ya esta dibujado y se lee igual.
        return None


def _w(text: str, height: float) -> float:
    """Ancho real del texto, preguntandole a AutoCAD (con respaldo estimado).

    Mismo criterio que annotation._w. El respaldo importa porque el ancho se
    usa para el largo del subrayado del titulo, y un subrayado que no llega
    hasta el final se ve peor que no tener subrayado.
    """
    try:
        return acad.call("measure_text", {
            "text": text, "height": height,
            "style": None, "widthFactor": None})["width"]
    except (acad.AutoCadError, KeyError, TypeError):
        return len(text) * height * 0.87


def _alto(height: float, mm_papel: float) -> float:
    """Altura de texto pedida, o la de norma para la escala de la lamina."""
    return height if height > 0 else space.paper(mm_papel)


# ------------------------------------------------------- marca de nivel

def _fmt_elevacion(elevation: float, decimals: int) -> str:
    """'+ 5.00', '- 1.20' o mas o menos 0.00.

    El cero lleva el signo mas-menos y no un '+': es la convencion para el
    nivel de referencia, y distinguirlo de un +0.00 cualquiera es el punto.
    """
    if abs(elevation) < 0.5 * 10 ** (-decimals):
        return "± " + ("%.*f" % (decimals, 0.0))
    signo = "+" if elevation > 0 else "-"
    return "%s %.*f" % (signo, decimals, abs(elevation))


def create_level_mark(x: float, y: float, elevation: float,
                      height: float = 0.0,
                      text: Optional[str] = None,
                      prefix: str = "N.P.T.",
                      suffix: str = "",
                      side: str = "right",
                      line_length: float = 0.0,
                      style: str = "triangulo",
                      decimals: int = 2,
                      layer: str = LAYER_LEVEL,
                      lineweight: int = LW_LEVEL,
                      color_index: Optional[int] = None) -> dict[str, Any]:
    """Marca de nivel (N.P.T.) sobre un corte o una fachada.

    x, y: el punto del nivel -- la cota REAL del dibujo, no donde quede
    lindo el texto. El simbolo se apoya ahi.
    elevation: el numero que se anota (5.00, -1.20, 0.0).
    text: si se pasa, reemplaza al armado con prefix/elevation/suffix.
    side: 'right' o 'left', hacia donde sale la linea y el texto.
    style: 'triangulo' (macizo, el mas legible) o 'circulo'.

    Devuelve los handles y la caja que ocupo, ya registrada en space para
    que place_labels y check_annotations no le escriban encima.
    """
    if side not in ("right", "left"):
        raise ValueError("side tiene que ser 'right' o 'left'.")
    if style not in ("triangulo", "circulo"):
        raise ValueError("style tiene que ser 'triangulo' o 'circulo'.")

    h = _alto(height, 2.5)
    _layer(layer,
           layers.COLOR_PRINCIPAL if color_index is None else color_index,
           lineweight)

    etiqueta = text if text is not None else " ".join(
        p for p in (prefix, _fmt_elevacion(elevation, decimals), suffix) if p)

    dir_x = 1.0 if side == "right" else -1.0
    s = h * 1.4                       # tamano del simbolo
    ancho_txt = _w(etiqueta, h)
    largo = line_length if line_length > 0 else ancho_txt + s * 2.0

    handles: list[str] = []

    # --- simbolo, con su punta EN el nivel -------------------------------
    if style == "triangulo":
        # Triangulo macizo apuntando abajo: la punta marca la cota exacta.
        tri = _poly([[x, y], [x - s * 0.5, y + s], [x + s * 0.5, y + s]],
                    True, layer, lineweight, color_index)
        handles.append(tri)
        relleno = _solid(tri, layer, color_index)
        if relleno:
            handles.append(relleno)
    else:
        r = s * 0.45
        handles.append(acad.call("create_circle", {
            "x": x, "y": y + r, "z": 0.0, "radius": r, "layer": layer,
            "lineweight": lineweight, "colorIndex": color_index})["handle"])
        # La horizontal que parte el circulo es lo que lo hace leerse como
        # nivel y no como un globo de eje.
        handles.append(_line(x - r, y + r, x + r, y + r, layer,
                             lineweight, color_index))

    # --- linea de referencia ---------------------------------------------
    x_fin = x + dir_x * largo
    handles.append(_line(x, y, x_fin, y, layer, lineweight, color_index))

    # --- texto, apoyado ARRIBA de la linea -------------------------------
    hueco = h * 0.35
    x_txt = (x + s * 0.8) if side == "right" else (x_fin + s * 0.4)
    y_txt = y + hueco
    t = _text(etiqueta, x_txt, y_txt, h, layer, lineweight, color_index)
    if t:
        handles.append(t)

    x0, x1 = min(x, x_fin), max(x, x_fin)
    caja = (x0, y, max(x1, x_txt + ancho_txt), y_txt + h)
    space.track(caja[0], caja[1], caja[2], caja[3],
                "%s%s" % (space.PREFIJO_TEXTO, etiqueta[:40]))

    return {"handles": handles, "text": etiqueta, "height": h,
            "box": [caja[0], caja[1], caja[2], caja[3]]}


# ------------------------------------------------------- titulo de vista

def create_view_title(x: float, y: float, title: str,
                      scale_text: Optional[str] = None,
                      height: float = 0.0,
                      spaced: bool = True,
                      underline: bool = True,
                      align: str = "left",
                      layer: str = LAYER_TITLE,
                      color_index: Optional[int] = COLOR_TITLE,
                      lineweight: int = LW_TITLE_TEXT,
                      rule_lineweight: int = LW_TITLE_RULE) -> dict[str, Any]:
    """Titulo de vista con la convencion completa: nombre, subrayado y escala.

    Es lo que convierte tres dibujos sueltos en una lamina. Un titulo escrito
    con create_text a secas queda del mismo tamano y del mismo peso que una
    nota al pie, y entonces la lamina no tiene jerarquia de lectura.

    title: 'PLANTA ESTRUCTURAL DE CUBIERTA'.
    scale_text: 'ESC. 1:100'. Va debajo, mas chico. None lo omite.
    spaced: separa las letras ('P L A N T A'), que es como se rotula una
    vista en la mayoria de las oficinas. False deja el texto tal cual.
    align: 'left' (x es el borde izquierdo) o 'center' (x es el centro).

    Devuelve la caja total, util para pasarsela a create_table en 'avoid'.
    """
    if align not in ("left", "center"):
        raise ValueError("align tiene que ser 'left' o 'center'.")
    if not title:
        raise ValueError("Un titulo de vista sin texto no sirve de nada.")

    h = _alto(height, 4.0)
    h_esc = h * 0.6
    _layer(layer, COLOR_TITLE if color_index is None else color_index,
           rule_lineweight)

    texto = " ".join(title) if spaced else title
    ancho = _w(texto, h)
    x0 = x if align == "left" else x - ancho / 2.0

    handles: list[str] = []
    t = _text(texto, x0, y, h, layer, lineweight, color_index)
    if t:
        handles.append(t)

    y_min = y
    if underline:
        y_regla = y - h * 0.45
        handles.append(_line(x0, y_regla, x0 + ancho, y_regla, layer,
                             rule_lineweight, color_index))
        y_min = y_regla

    if scale_text:
        ancho_esc = _w(scale_text, h_esc)
        # La escala se centra bajo el titulo, no se alinea a la izquierda:
        # asi el bloque entero lee como una unidad.
        x_esc = x0 + (ancho - ancho_esc) / 2.0
        y_esc = y_min - h_esc * 1.4
        e = _text(scale_text, x_esc, y_esc, h_esc, layer, lineweight,
                  color_index)
        if e:
            handles.append(e)
        y_min = y_esc

    caja = (x0, y_min, x0 + ancho, y + h)
    space.track(caja[0], caja[1], caja[2], caja[3],
                "%s%s" % (space.PREFIJO_TEXTO, title[:40]))

    return {"handles": handles, "width": ancho, "height": h,
            "box": [caja[0], caja[1], caja[2], caja[3]]}


# -------------------------------------------------------- marca de corte

def create_section_mark(x1: float, y1: float, x2: float, y2: float,
                        label: str = "A",
                        height: float = 0.0,
                        direction: str = "left",
                        tail: float = 0.0,
                        show_line: bool = False,
                        layer: str = LAYER_MARK,
                        lineweight: int = LW_MARK,
                        color_index: Optional[int] = None) -> dict[str, Any]:
    """Marca de corte: lo unico que liga una planta con su seccion.

    Sin esto, la planta y el corte son dos dibujos sueltos -- nada dice de
    donde se saco el corte ni hacia donde se mira, que es la mitad de la
    informacion.

    x1,y1 -> x2,y2: por donde pasa el plano de corte. Se dibujan los DOS
    extremos (cola gruesa + flecha + globo con la letra); el tramo del medio
    se omite, que es como se dibuja de verdad sobre una planta con contenido.
    direction: 'left' o 'right' respecto del sentido 1->2, hacia donde mira.
    show_line: True traza ademas la linea de corte completa.

    La capa por defecto es MARCAS-CORTE y no CORTES, que ya es el detalle de
    capas de pavimento (create_layer_section), ni SECCIONES, que ya son los
    cortes viales (create_cross_sections).
    """
    if direction not in ("left", "right"):
        raise ValueError("direction tiene que ser 'left' o 'right'.")
    dx, dy = x2 - x1, y2 - y1
    largo = math.hypot(dx, dy)
    if largo <= 0:
        raise ValueError(
            "La linea de corte tiene largo cero: (x1,y1) y (x2,y2) son el "
            "mismo punto.")

    h = _alto(height, 3.0)
    _layer(layer,
           layers.COLOR_PRINCIPAL if color_index is None else color_index,
           lineweight)

    ux, uy = dx / largo, dy / largo               # a lo largo del corte
    # Normal a izquierda del sentido 1->2; se invierte para 'right'.
    nx, ny = -uy, ux
    if direction == "right":
        nx, ny = -nx, -ny

    cola = tail if tail > 0 else h * 2.4
    flecha = h * 2.2
    r = h * 0.9

    handles: list[str] = []

    if show_line:
        handles.append(_line(x1, y1, x2, y2, layer, 13, color_index))

    def extremo(px: float, py: float, sx: float, sy: float) -> None:
        """Un extremo: cola hacia ADENTRO, flecha perpendicular y globo.

        (sx, sy) apunta hacia el otro extremo. La cola va para adentro y no
        para afuera a proposito: los extremos del corte caen fuera del
        edificio, asi que una cola hacia afuera deja la marca flotando lejos
        del dibujo, sin ninguna relacion visual con lo que corta. Hacia
        adentro, la cola entra en la planta y se lee de donde sale el corte.
        """
        cx, cy = px + sx * cola, py + sy * cola
        handles.append(_line(px, py, cx, cy, layer, lineweight, color_index))

        # Flecha perpendicular DESDE la esquina: indica hacia donde se mira.
        fx, fy = px + nx * flecha, py + ny * flecha
        handles.append(_line(px, py, fx, fy, layer, lineweight, color_index))
        punta = h * 0.55
        # Triangulo macizo en la punta, con la base atras sobre el eje.
        bx, by = fx - nx * punta * 1.8, fy - ny * punta * 1.8
        tri = _poly([[fx, fy],
                     [bx + ux * punta * 0.6, by + uy * punta * 0.6],
                     [bx - ux * punta * 0.6, by - uy * punta * 0.6]],
                    True, layer, lineweight, color_index)
        handles.append(tri)
        relleno = _solid(tri, layer, color_index)
        if relleno:
            handles.append(relleno)

        # Globo con la letra, mas alla de la flecha.
        gx, gy = fx + nx * r * 1.6, fy + ny * r * 1.6
        handles.append(acad.call("create_circle", {
            "x": gx, "y": gy, "z": 0.0, "radius": r, "layer": layer,
            "lineweight": lineweight, "colorIndex": color_index})["handle"])
        ancho_l = _w(label, h)
        t = _text(label, gx - ancho_l / 2.0, gy - h * 0.5, h, layer,
                  LW_MARK_TEXT, color_index)
        if t:
            handles.append(t)
        space.track(gx - r, gy - r, gx + r, gy + r, "marca de corte " + label)

    # Cada extremo mira hacia el otro: esa es la direccion 'hacia adentro'.
    extremo(x1, y1, ux, uy)
    extremo(x2, y2, -ux, -uy)

    return {"handles": handles, "label": label, "height": h,
            "direction": direction}


# --------------------------------------------------------------- norte

LAYER_NORTH = "NORTE"
LW_NORTH = 35


def create_north(x: float, y: float, radius: float = 0.0,
                 rotation_deg: float = 0.0,
                 label: str = "N",
                 style: str = "arrow",
                 layer: str = LAYER_NORTH,
                 lineweight: int = LW_NORTH,
                 color_index: Optional[int] = None) -> dict[str, Any]:
    """Simbolo de norte. TODO plano de terreno o de conjunto lleva uno.

    Sin norte, una planta no se puede orientar en el lote ni saber que
    fachada recibe el sol -- y en un plano que se entrega a licencia es de
    las primeras cosas que se revisan. Armarlo a mano con lineas sueltas da
    un norte distinto en cada lamina, que es la misma razon por la que la
    marca de nivel y el titulo de vista viven aca.

    x, y: CENTRO del simbolo.
    radius: radio en unidades del modelo. 0 lo toma de la escala de la
    lamina (12 mm de papel), que es el tamano usual.
    rotation_deg: hacia donde apunta el norte, medido desde arriba (+Y) y en
    sentido ANTIHORARIO -- 0 es norte hacia arriba, que es como se orienta
    un plano salvo que el terreno obligue a otra cosa.
    style: 'arrow' es la aguja clasica de dos mitades (una llena, una vacia)
    dentro de su circulo; 'simple' es solo la flecha, sin circulo, para un
    detalle chico.

    La huella queda registrada: place_labels no le escribe encima y
    check_annotations lo revisa."""
    if style not in ("arrow", "simple"):
        raise ValueError("style tiene que ser 'arrow' o 'simple'.")

    r = radius if radius > 0 else space.paper(12.0)
    _layer(layer, layers.COLOR_PRINCIPAL, lineweight)

    # 'rotation_deg' se mide desde +Y (norte arriba) y antihorario; la
    # geometria se arma con angulos desde +X, de ahi el +90.
    a = math.radians(rotation_deg + 90.0)
    ux, uy = math.cos(a), math.sin(a)      # hacia la punta
    vx, vy = -uy, ux                       # perpendicular

    handles: list[str] = []
    if style == "arrow":
        handles.append(acad.call("create_circle", {
            "x": x, "y": y, "z": 0.0, "radius": r,
            "layer": layer, "lineweight": lineweight,
            "colorIndex": color_index})["handle"])

    largo = r * (0.92 if style == "arrow" else 1.0)
    ancho = largo * 0.30
    punta = (x + ux * largo, y + uy * largo)
    cola = (x - ux * largo * 0.75, y - uy * largo * 0.75)
    izq = (x + vx * ancho, y + vy * ancho)
    der = (x - vx * ancho, y - vy * ancho)

    # Dos mitades: la izquierda hueca, la derecha rellena. Es la aguja
    # clasica -- el contraste es lo que la hace legible de lejos, y en
    # monocromo sigue funcionando porque no depende del color.
    mitad_hueca = _poly([[punta[0], punta[1]], [izq[0], izq[1]],
                         [cola[0], cola[1]]], True, layer, lineweight,
                        color_index)
    mitad_llena = _poly([[punta[0], punta[1]], [der[0], der[1]],
                         [cola[0], cola[1]]], True, layer, lineweight,
                        color_index)
    handles.extend([mitad_hueca, mitad_llena])
    relleno = _solid(mitad_llena, layer, color_index)
    if relleno:
        handles.append(relleno)

    if label:
        h = space.paper(3.5) if radius <= 0 else r * 0.29
        ancho_l = _w(label, h)
        # La letra va MAS ALLA de la punta, siguiendo la misma direccion:
        # asi acompana al norte aunque el simbolo este rotado.
        lx = x + ux * (r * 1.18) - ancho_l / 2.0
        ly = y + uy * (r * 1.18) - h / 2.0
        t = _text(label, lx, ly, h, layer, LW_TITLE_TEXT, color_index)
        if t:
            handles.append(t)

    space.track(x - r * 1.35, y - r * 1.35, x + r * 1.35, y + r * 1.35,
                "norte")

    return {"handles": handles, "radius": r, "center": [x, y],
            "rotation": rotation_deg,
            "box": [x - r * 1.35, y - r * 1.35, x + r * 1.35, y + r * 1.35]}
