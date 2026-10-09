"""Detalle de armado de columna/castillo en corte: la sección de concreto,
el estribo y las varillas longitudinales como puntos -- el nivel de detalle
que un corte estructural real muestra y que hasta ahora esta biblioteca no
podía dibujar (solo calculaba la cuantía con check_column).

No inventa CUÁNTAS varillas van por cara: eso es una decisión de armado que
toma quien proyecta (o que sale de check_column + el área comercial de la
varilla elegida), igual que create_building_section no inventa qué muro está
cortado. Se compone con create_polyline/create_circle/create_hatch, como el
resto de arch.py/sections.py -- no hace falta tocar el plugin.

Unidades: las del modelo (metros si se dibuja en metros); bar_diameter y
cover en metros aunque las varillas se nombren en octavos de pulgada en obra
(un #4 son 0.0127 m, un #3 son 0.0095 m -- pasalo ya convertido).
"""
from __future__ import annotations

import math
from typing import Any, Optional

import annotation as ann_mod
import autocad_client as acad
import layers
import materials as mat_mod
import space
import symbols as sym_mod

LAYER_COLUMN = "ARMADO-COLUMNA"
LAYER_FOOTING = "ARMADO-ZAPATA"
LAYER_FOOTING_SECTION = "CIMENTACION-MURO"

LW_OUTLINE = 50
LW_STIRRUP = 25
LW_BAR = 18
LW_MAT = 18
LW_SUPPORT_REF = 13
LW_TEXT = 18
LW_LEADER = 13

DEFAULT_CONCRETE_HATCH = "AR-CONC"


def _layer(name: str, lineweight: int, linetype: Optional[str] = None) -> None:
    layers.ensure(name, layers.COLOR_PRINCIPAL, lineweight, linetype)
    layers.ensure_text_style()


def _text(content: str, x: float, y: float, height: float, layer: str,
         lineweight: int = LW_TEXT, rotation: float = 0.0) -> None:
    acad.call("create_text", {
        "text": content, "x": x, "y": y, "z": 0.0, "height": height,
        "layer": layer, "rotationDeg": rotation,
        "lineweight": lineweight, "colorIndex": None,
    })


def _rect(x0: float, y0: float, x1: float, y1: float, layer: str,
          lineweight: int) -> str:
    return acad.call("create_polyline", {
        "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        "closed": True, "layer": layer,
        "lineweight": lineweight, "colorIndex": None,
    })["handle"]


def _line(p0: tuple[float, float], p1: tuple[float, float], layer: str,
         lineweight: int) -> str:
    result = acad.call("create_line", {
        "x1": p0[0], "y1": p0[1], "z1": 0.0,
        "x2": p1[0], "y2": p1[1], "z2": 0.0,
        "layer": layer, "lineweight": lineweight, "colorIndex": None,
    })
    return result["handle"]


def _circle(cx: float, cy: float, radius: float, layer: str,
           lineweight: int) -> str:
    return acad.call("create_circle", {
        "x": cx, "y": cy, "z": 0.0, "radius": radius, "layer": layer,
        "lineweight": lineweight, "colorIndex": None,
    })["handle"]


def _hatch(handle: str, pattern: str, scale: float, layer: str,
          island_handles: Optional[list[str]] = None,
          color_index: Optional[int] = None) -> Optional[str]:
    try:
        return acad.call("create_hatch", {
            "boundaryHandle": handle, "pattern": pattern, "scale": scale,
            "angleDeg": 0.0, "layer": layer, "islandHandles": island_handles,
            "lineweight": 5,
            "colorIndex": color_index if color_index is not None
                         else layers.COLOR_SECUNDARIO,
        })["handle"]
    except acad.AutoCadError:
        # Un patron que no existe en esta instalacion no debe tumbar el detalle.
        return None


def _spaced_interior_points(p0: tuple[float, float], p1: tuple[float, float],
                            n: int) -> list[tuple[float, float]]:
    """n puntos repartidos en el INTERIOR del segmento (sin tocar las puntas,
    que ya llevan la varilla de esquina)."""
    if n <= 0:
        return []
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    return [(p0[0] + dx * (i / (n + 1)), p0[1] + dy * (i / (n + 1)))
            for i in range(1, n + 1)]


def create_column_section(x: float, y: float, width: float, depth: float,
                          bars_top_bottom: int = 0,
                          bars_left_right: int = 0,
                          bar_diameter: float = 0.0127,
                          cover: float = 0.03,
                          stirrup_diameter: float = 0.0095,
                          hatch_pattern: str = DEFAULT_CONCRETE_HATCH,
                          hatch_scale: float = 0.0,
                          layer: Optional[str] = None) -> dict[str, Any]:
    """Sección de una columna/castillo de concreto en corte, con estribo y
    varillas longitudinales -- el detalle que "30x30, típico" no dibuja y
    que un corte estructural real sí muestra.

    (x, y) es la esquina inferior izquierda de la sección (cara exterior de
    concreto). width/depth: dimensiones de la sección, m -- si vienen de
    check_column, usá 'width'/'depth' de ese resultado.

    Las varillas de esquina son automáticas (las 4 esquinas del estribo)
    igual que en cualquier columna real. bars_top_bottom/bars_left_right:
    varillas ADICIONALES repartidas parejo en el interior de cada cara
    horizontal/vertical (no en el total de la columna, por CADA cara --
    "2 en cada cara larga" se pasa como el número que corresponda según
    cuál par de caras sea la larga). No inventa una cuantía: si no le
    pasás nada, dibuja las 4 de esquina nomás.

    bar_diameter: diámetro de la varilla longitudinal, m (0.0127 = #4/
    1/2", un valor de referencia -- pasá el diámetro real especificado).
    cover: recubrimiento libre de la cara de concreto al estribo, m.
    stirrup_diameter: diámetro del estribo, m -- separa el estribo un poco
    más adentro de 'cover' (cover es a la cara del estribo, no al centro
    de la varilla longitudinal).
    hatch_pattern: 'AR-CONC' (textura de concreto, default) o 'SOLID'/
    'ANSI31' si esta instalación no tiene AR-CONC -- confirmalo con
    list_hatch_patterns si da error en silencio.
    hatch_scale: 0 la calibra a la escala de la lámina (1.2 mm de papel
    por módulo, ver materials.hatch_scale); un valor > 0 se usa tal cual.

    Devuelve 'stirrupHandle' (la Polyline cerrada del estribo, lista para
    pasar como stirrup_handle a calculate_quantities tipo steel_weight --
    mide su perímetro REAL, no lo recalcula), 'barCount' y
    'totalSteelArea_cm2' (para comparar contra lo que check_column pidió,
    no para reemplazarlo)."""
    if width <= 0 or depth <= 0:
        raise ValueError("width y depth tienen que ser mayores que 0.")
    if cover <= 0:
        raise ValueError("cover tiene que ser mayor que 0.")
    if width <= 2 * cover or depth <= 2 * cover:
        raise ValueError(
            f"cover ({cover:g}) es demasiado grande para una sección de "
            f"{width:g}x{depth:g} -- no queda espacio para el estribo.")
    if bar_diameter <= 0:
        raise ValueError("bar_diameter tiene que ser mayor que 0.")
    if bars_top_bottom < 0 or bars_left_right < 0:
        raise ValueError("bars_top_bottom y bars_left_right no pueden ser negativos.")

    lyr = layer or LAYER_COLUMN
    _layer(lyr, LW_OUTLINE)

    x0, y0, x1, y1 = x, y, x + width, y + depth
    outline_handle = _rect(x0, y0, x1, y1, lyr, LW_OUTLINE)
    esc = hatch_scale if hatch_scale > 0 else mat_mod.hatch_scale(hatch_pattern, 1.2)
    _hatch(outline_handle, hatch_pattern, esc, lyr)

    sx0, sy0 = x0 + cover, y0 + cover
    sx1, sy1 = x1 - cover, y1 - cover
    stirrup_handle = _rect(sx0, sy0, sx1, sy1, lyr, LW_STIRRUP)

    corners = [(sx0, sy0), (sx1, sy0), (sx1, sy1), (sx0, sy1)]
    bar_points = list(corners)
    bottom = _spaced_interior_points((sx0, sy0), (sx1, sy0), bars_top_bottom)
    top = _spaced_interior_points((sx0, sy1), (sx1, sy1), bars_top_bottom)
    left = _spaced_interior_points((sx0, sy0), (sx0, sy1), bars_left_right)
    right = _spaced_interior_points((sx1, sy0), (sx1, sy1), bars_left_right)
    bar_points.extend(bottom + top + left + right)

    bar_radius = bar_diameter / 2.0
    bar_handles: list[str] = []
    for bx, by in bar_points:
        h = _circle(bx, by, bar_radius, lyr, LW_BAR)
        _hatch(h, "SOLID", 1.0, lyr)
        bar_handles.append(h)

    space.track(x0, y0, x1, y1, f"columna {lyr}")

    bar_area_cm2 = 3.14159265 * (bar_diameter * 100.0 / 2.0) ** 2
    total_area_cm2 = bar_area_cm2 * len(bar_points)

    return {
        "outlineHandle": outline_handle,
        "stirrupHandle": stirrup_handle,
        "barHandles": bar_handles,
        "barCount": len(bar_points),
        "singleBarArea_cm2": round(bar_area_cm2, 3),
        "totalSteelArea_cm2": round(total_area_cm2, 2),
    }


def _mat_positions(start: float, end: float, spacing: float) -> tuple[list[float], float]:
    """Posiciones de varilla repartidas parejo entre start y end (incluyendo
    las dos puntas). 'spacing' es un MÁXIMO de obra ("varilla @15cm" no
    admite que el paso real se pase de 15) -- se redondea siempre hacia
    MÁS varillas (techo), nunca hacia menos, así el paso real que resulta
    de cerrar parejo queda <= spacing pedido, jamás por encima."""
    usable = end - start
    if usable <= 0:
        raise ValueError("El recubrimiento no deja espacio para la parrilla.")
    n = max(2, math.ceil(usable / spacing - 1e-9) + 1)
    paso = usable / (n - 1)
    return [start + i * paso for i in range(n)], paso


def create_footing_plan(x: float, y: float, width: float, length: float,
                        bar_spacing_x: float,
                        bar_spacing_y: Optional[float] = None,
                        bar_diameter: float = 0.0127,
                        cover: float = 0.05,
                        support_width: float = 0.0,
                        support_length: float = 0.0,
                        corner_bar_leg: float = 0.0,
                        layer: Optional[str] = None) -> dict[str, Any]:
    """Planta de una zapata aislada con parrilla de armado en DOS sentidos
    -- lo que create_column_section no dibuja, porque esa es una sección en
    elevación y esto es una vista en planta con una malla de varillas
    cruzadas, no un corte.

    (x, y) es la esquina inferior izquierda de la zapata. width/length:
    dimensiones en planta, m -- si vienen de check_footing, width=length=
    'side' (zapata cuadrada) es el caso típico, pero acepta rectangular.

    bar_spacing_x: separación de las varillas que CORREN en Y (repartidas
    a lo largo de X), m -- el dato de obra "varilla del #4 @ 15cm". Si
    bar_spacing_y es distinto, dobles espaciamientos por sentido; si se
    omite, usa el mismo que bar_spacing_x ("doble armado en ambos
    sentidos" con el mismo paso, el caso más común).
    bar_diameter: diámetro de la varilla, m. cover: recubrimiento libre
    del borde de la zapata a la primera varilla, m.

    support_width/support_length: si se pasan (>0), dibuja el contorno de
    referencia (línea fina, capa con linetype punteado) del elemento que
    apoya centrado encima -- columna o dado, para que la planta se lea
    junto con el corte sin tener que adivinar dónde cae.

    corner_bar_leg: si se pasa (>0), agrega una varilla diagonal
    ESQUEMÁTICA en cada esquina (a 45°, ese largo de pata) -- la práctica
    real de reforzar la esquina de una zapata con dos sentidos de momento.
    Esto NO calcula el gancho ni el desarrollo real del doblez: es la
    geometría que se ve en planta, la decisión de detallado (diámetro,
    longitud de anclaje) es de quien proyecta.

    Devuelve 'barCountX'/'barCountY' (cantidad real de varillas por
    sentido, con el paso ya ajustado para cerrar parejo) y
    'totalBarLength_m' (listo para pasar como 'length' a
    calculate_quantities tipo steel_weight -- mide la parrilla que se
    dibujó, no la vuelve a calcular)."""
    if width <= 0 or length <= 0:
        raise ValueError("width y length tienen que ser mayores que 0.")
    if cover <= 0:
        raise ValueError("cover tiene que ser mayor que 0.")
    if width <= 2 * cover or length <= 2 * cover:
        raise ValueError(
            f"cover ({cover:g}) es demasiado grande para una zapata de "
            f"{width:g}x{length:g}.")
    if bar_spacing_x <= 0:
        raise ValueError("bar_spacing_x tiene que ser mayor que 0.")
    spacing_y = bar_spacing_y if bar_spacing_y and bar_spacing_y > 0 else bar_spacing_x
    if bar_diameter <= 0:
        raise ValueError("bar_diameter tiene que ser mayor que 0.")
    if corner_bar_leg < 0:
        raise ValueError("corner_bar_leg no puede ser negativo.")

    lyr = layer or LAYER_FOOTING
    _layer(lyr, LW_OUTLINE)

    x0, y0, x1, y1 = x, y, x + width, y + length
    outline_handle = _rect(x0, y0, x1, y1, lyr, LW_OUTLINE)

    xs, paso_x = _mat_positions(x0 + cover, x1 - cover, bar_spacing_x)
    ys, paso_y = _mat_positions(y0 + cover, y1 - cover, spacing_y)

    bar_len_y = (y1 - cover) - (y0 + cover)  # largo de cada varilla vertical
    bar_len_x = (x1 - cover) - (x0 + cover)  # largo de cada varilla horizontal

    mat_handles: list[str] = []
    for xi in xs:
        mat_handles.append(_line((xi, y0 + cover), (xi, y1 - cover), lyr, LW_MAT))
    for yi in ys:
        mat_handles.append(_line((x0 + cover, yi), (x1 - cover, yi), lyr, LW_MAT))

    support_handle = None
    if support_width > 0 and support_length > 0:
        ref_layer = f"{lyr}-REF"
        _layer(ref_layer, LW_SUPPORT_REF, "HIDDEN")
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        support_handle = _rect(cx - support_width / 2.0, cy - support_length / 2.0,
                               cx + support_width / 2.0, cy + support_length / 2.0,
                               ref_layer, LW_SUPPORT_REF)

    corner_handles: list[str] = []
    if corner_bar_leg > 0:
        d = corner_bar_leg / 1.41421356  # componente x=y de una diagonal a 45 grados
        for cx, cy, sx, sy in [(x0 + cover, y0 + cover, 1, 1),
                               (x1 - cover, y0 + cover, -1, 1),
                               (x1 - cover, y1 - cover, -1, -1),
                               (x0 + cover, y1 - cover, 1, -1)]:
            corner_handles.append(_line((cx, cy), (cx + sx * d, cy + sy * d),
                                        lyr, LW_BAR))

    space.track(x0, y0, x1, y1, f"zapata {lyr}")

    total_length = len(xs) * bar_len_y + len(ys) * bar_len_x

    return {
        "outlineHandle": outline_handle,
        "matHandles": mat_handles,
        "supportRefHandle": support_handle,
        "cornerBarHandles": corner_handles,
        "barCountX": len(xs),
        "barCountY": len(ys),
        "actualSpacingX_m": round(paso_x, 4),
        "actualSpacingY_m": round(paso_y, 4),
        "totalBarLength_m": round(total_length, 2),
    }


# ------------------------------------------------ armado en ELEVACION

def _posiciones_estribos(inicio: float, fin: float, paso: float,
                         confinamiento: float = 0.0,
                         paso_confinamiento: float = 0.0
                         ) -> tuple[list[float], float, list[str]]:
    """Donde cae cada estribo entre inicio y fin.

    'paso' es un MAXIMO de obra, igual que en _mat_positions: "est. #3 @ 20"
    no admite que la separacion real se pase de 20 cm. Se redondea siempre
    hacia MAS estribos, nunca hacia menos.

    Con confinamiento, los extremos van mas juntos -- que es como se arma una
    columna de verdad: el cortante y el confinamiento mandan en los extremos,
    no en el centro. La zona central usa el paso normal.

    Devuelve las posiciones, el paso real de la zona central y los avisos.
    """
    largo = fin - inicio
    avisos: list[str] = []
    if largo <= 0:
        raise ValueError(
            "El recubrimiento no deja largo para estribar: la pieza mide "
            "menos que dos veces el recubrimiento.")
    if paso <= 0:
        raise ValueError(
            "stirrup_spacing tiene que ser > 0. Es la separacion de estribos "
            "que ESPECIFICA el proyecto ('est. #3 @ 20 cms' -> 0.20); no se "
            "inventa: pedila si no la tenes.")

    if confinamiento > 0 and paso_confinamiento > 0:
        if 2 * confinamiento >= largo:
            avisos.append(
                "Las dos zonas de confinamiento (%.2f m cada una) cubren toda "
                "la pieza (%.2f m): se estriba entera al paso cerrado."
                % (confinamiento, largo))
            confinamiento = largo / 2.0

        pos: list[float] = []
        # Extremo inferior, extremo superior y centro, cada uno cerrando
        # parejo dentro de su tramo.
        for a, b, p in ((inicio, inicio + confinamiento, paso_confinamiento),
                        (inicio + confinamiento, fin - confinamiento, paso),
                        (fin - confinamiento, fin, paso_confinamiento)):
            if b - a <= 1e-9:
                continue
            n = max(1, math.ceil((b - a) / p - 1e-9))
            real = (b - a) / n
            pos.extend(a + i * real for i in range(n + 1))
        # Los bordes de zona quedan repetidos: un estribo por posicion.
        unicas: list[float] = []
        for v in sorted(pos):
            if not unicas or v - unicas[-1] > 1e-6:
                unicas.append(v)
        n_centro = max(1, math.ceil((largo - 2 * confinamiento) / paso - 1e-9))
        paso_real = (largo - 2 * confinamiento) / n_centro
        return unicas, paso_real, avisos

    n = max(1, math.ceil(largo / paso - 1e-9))
    paso_real = largo / n
    if paso_real < paso - 1e-6:
        avisos.append(
            "La separacion real queda en %.3f m y no en los %.3f m pedidos: "
            "es lo que da cerrar parejo en %.2f m. Siempre hacia MENOS "
            "separacion, nunca hacia mas." % (paso_real, paso, largo))
    return [inicio + i * paso_real for i in range(n + 1)], paso_real, avisos


def create_rebar_elevation(x: float, y: float, width: float, height: float,
                           stirrup_spacing: float,
                           bars_interior: int = 0,
                           bar_diameter: float = 0.0127,
                           stirrup_diameter: float = 0.0095,
                           cover: float = 0.03,
                           depth: float = 0.0,
                           orientation: str = "vertical",
                           extend_start: float = 0.0,
                           extend_end: float = 0.0,
                           confinement_length: float = 0.0,
                           confinement_spacing: float = 0.0,
                           draw_outline: bool = True,
                           layer: Optional[str] = None) -> dict[str, Any]:
    """Armado VISTO EN ELEVACION: las varillas longitudinales y los estribos
    como escalera, dentro del contorno de concreto.

    Es lo que ocupa el 80% de un detalle de cimentacion real y lo que
    convierte un corte de cajas vacias en un detalle constructivo.
    create_column_section dibuja la seccion TRANSVERSAL (el estribo cerrado
    visto de punta y las varillas como puntos); esto es la otra vista.

    (x, y) es la esquina inferior izquierda del concreto. width/height: las
    dimensiones de la pieza EN EL PLANO DEL DIBUJO, m.
    orientation: 'vertical' (columna, dado, castillo) o 'horizontal' (trabe
    de liga, dala) -- cambia hacia donde corren las varillas.

    stirrup_spacing es OBLIGATORIO y no tiene default: es un dato del
    proyecto ('est. del no. 3 (3/8") @ 20 cms' -> 0.20), no algo que la tool
    pueda suponer. Se trata como un MAXIMO de obra: el paso real cierra
    parejo hacia MENOS separacion, nunca hacia mas.

    confinement_length + confinement_spacing: estribos mas juntos en los dos
    extremos, que es como se arma una columna de verdad. Van juntos o
    ninguno.
    depth: la dimension de la pieza FUERA del plano del dibujo (en una
    columna 0.40x0.40 vista de frente, el otro 0.40). Una elevacion no la
    ve, y sin ella no se puede calcular el perimetro del estribo -- se
    devuelve None y se avisa, en vez de inventar kilos de acero.
    extend_start / extend_end: cuanto sobresalen las varillas del concreto
    (anclaje en la zapata, traslape hacia arriba). Cuenta en el largo total
    que se devuelve.

    Devuelve el numero REAL de estribos y el largo REAL de varilla, para que
    calculate_quantities mida lo que quedo dibujado en vez de recalcularlo
    de memoria: es el mismo criterio de siempre, aplicado al armado.
    """
    if orientation not in ("vertical", "horizontal"):
        raise ValueError("orientation tiene que ser 'vertical' o 'horizontal'.")
    if width <= 0 or height <= 0:
        raise ValueError("width y height tienen que ser > 0.")
    if cover < 0:
        raise ValueError("cover no puede ser negativo.")
    if (confinement_length > 0) != (confinement_spacing > 0):
        raise ValueError(
            "confinement_length y confinement_spacing van los dos o ninguno: "
            "una zona de confinamiento sin su separacion no dice nada.")

    lyr = layer or LAYER_COLUMN
    _layer(lyr, LW_OUTLINE)

    handles: list[str] = []
    if draw_outline:
        handles.append(_rect(x, y, x + width, y + height, lyr, LW_OUTLINE))

    # Eje 'largo' = por donde corren las varillas; 'ancho' = donde se
    # reparten. Con orientation horizontal se intercambian.
    if orientation == "vertical":
        largo0, largo1 = y + cover, y + height - cover
        ancho0, ancho1 = x + cover, x + width - cover
    else:
        largo0, largo1 = x + cover, x + width - cover
        ancho0, ancho1 = y + cover, y + height - cover

    if ancho1 <= ancho0:
        raise ValueError(
            "El recubrimiento (%.3f m) se come el ancho de la pieza (%.3f m)."
            % (cover, width if orientation == "vertical" else height))

    pos, paso_real, avisos = _posiciones_estribos(
        largo0, largo1, stirrup_spacing, confinement_length,
        confinement_spacing)

    # --- estribos: una linea transversal por posicion ---------------------
    for t in pos:
        if orientation == "vertical":
            handles.append(_line((ancho0, t), (ancho1, t), lyr, LW_STIRRUP))
        else:
            handles.append(_line((t, ancho0), (t, ancho1), lyr, LW_STIRRUP))

    # --- varillas longitudinales -----------------------------------------
    # Las dos de los bordes son las de esquina del estribo; las interiores
    # se reparten parejo entre ellas, igual que en create_column_section.
    caras = [ancho0, ancho1]
    caras.extend(p[0] for p in _spaced_interior_points(
        (ancho0, 0.0), (ancho1, 0.0), bars_interior))
    caras.sort()

    a = largo0 - extend_start
    b = largo1 + extend_end
    for c in caras:
        if orientation == "vertical":
            handles.append(_line((c, a), (c, b), lyr, LW_BAR))
        else:
            handles.append(_line((a, c), (b, c), lyr, LW_BAR))

    largo_varilla = b - a

    # El estribo es un rectangulo cerrado en la SECCION, y una elevacion no
    # ve la dimension de afuera del plano. Sin 'depth' no hay forma de saber
    # su perimetro -- y un numero inventado ahi se convierte en kilos de
    # acero inventados en la cuantificacion. Se devuelve None y se dice.
    perimetro_estribo = None
    if depth > 0:
        if depth <= 2 * cover:
            raise ValueError(
                "depth (%.3f m) no le gana a dos recubrimientos (%.3f m): "
                "el estribo no entra." % (depth, 2 * cover))
        perimetro_estribo = 2 * ((ancho1 - ancho0) + (depth - 2 * cover))
    else:
        avisos.append(
            "Sin 'depth' (la dimension fuera del plano del dibujo) no se "
            "puede saber el perimetro del estribo: una elevacion no la ve. "
            "Pasala si vas a cuantificar el acero de estribo.")

    space.track(min(x, x - 0), min(y, y - 0), x + width, y + height,
                "armado en elevacion")

    return {
        "handles": handles,
        "stirrupCount": len(pos),
        "actualStirrupSpacing_m": round(paso_real, 4),
        "requestedStirrupSpacing_m": stirrup_spacing,
        "barCount": len(caras),
        "barLength_m": round(largo_varilla, 4),
        "totalBarLength_m": round(largo_varilla * len(caras), 3),
        "stirrupPerimeter_m": (round(perimetro_estribo, 4)
                               if perimetro_estribo else None),
        "totalStirrupLength_m": (round(perimetro_estribo * len(pos), 3)
                                 if perimetro_estribo else None),
        "warnings": avisos,
    }


# --------------------------------------------------- varilla por trayectoria

LAYER_REBAR = "ARMADO"
LW_REBAR = 35

# Extensión del gancho en diámetros de barra (ACI 318-19 25.3.1 y 25.3.2,
# que es lo que las NTC-Concreto toman): 12db para 90°, 6db para el gancho
# de estribo a 135°, 4db para 180°. Los mínimos absolutos (65/75 mm) van en
# 'hook_extension' si el proyecto los pide: la tool no sabe en qué unidad
# está dibujando.
HOOK_EXT_DB = {"90": 12.0, "135": 6.0, "180": 4.0}
HOOKS = tuple(HOOK_EXT_DB)


def _rot(v: tuple[float, float], ang: float) -> tuple[float, float]:
    c, s = math.cos(ang), math.sin(ang)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def _unit(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    d = math.dist(a, b)
    if d < 1e-12:
        raise ValueError(f"Dos puntos seguidos de la varilla coinciden: {a}.")
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)


def _hook_after(p: tuple[float, float], u: tuple[float, float], side: str,
                hook: str, ext: float, r: float
                ) -> tuple[float, list[tuple[float, float]]]:
    """Un gancho al final de una barra que llega a p viajando en dirección u.

    Devuelve (bulge del tramo que SALE de p, vértices que siguen a p). Para
    90° y 135° el bulge es 0 y el doblez lo resuelve después el paso de
    filetes; el de 180° es un semicírculo tangente ya resuelto (bulge ±1),
    y la pata vuelve hacia atrás."""
    s = 1.0 if side == "left" else -1.0
    n = (-u[1] * s, u[0] * s)              # hacia el lado del gancho
    if hook == "180":
        q = (p[0] + 2.0 * r * n[0], p[1] + 2.0 * r * n[1])
        e = (q[0] - u[0] * ext, q[1] - u[1] * ext)
        return s * 1.0, [q, e]
    ang = math.radians(float(hook)) * s
    v = _rot(u, ang)
    t = r * math.tan(math.radians(float(hook)) / 2.0)
    e = (p[0] + v[0] * (ext + t), p[1] + v[1] * (ext + t))
    return 0.0, [e]


def create_rebar(points: list, diameter: float,
                 start_hook: Optional[str] = None,
                 end_hook: Optional[str] = None,
                 hook_side: str = "left",
                 closed: bool = False,
                 bend_diameter_factor: float = 6.0,
                 hook_extension: float = 0.0,
                 layer: Optional[str] = None,
                 lineweight: int = LW_REBAR,
                 color_index: Optional[int] = None) -> dict[str, Any]:
    """UNA varilla dibujada por su trayectoria, con los dobleces a radio y
    los ganchos normalizados -- lo que separa 'una línea' de 'una varilla'.

    points: por dónde pasa el EJE de la barra, tramo recto a tramo recto:
    [[0,0],[1.2,0]] es una barra recta; [[0,0.6],[0,0.05],[0.25,0.05]] es
    un arranque en L anclado en la zapata. Cada quiebre sale doblado con el
    radio que le toca (bend_diameter_factor x diámetro de diámetro
    interior, 6db por defecto -- ACI 318 tabla 25.3.1; 4db para estribos).
    diameter: diámetro de la barra en unidades del modelo (0.0127 = #4).
    start_hook / end_hook: '90', '135', '180' o None. La extensión sale de
    la convención (12db / 6db / 4db) salvo que se pase hook_extension.
    hook_side: 'left' o 'right' respecto del sentido de avance de la
    trayectoria -- para una barra que va de izquierda a derecha, 'left' es
    gancho hacia ARRIBA.
    closed=True: la trayectoria vuelve al primer punto y las dos puntas
    llevan gancho a 135° hacia adentro -- un estribo. Recorré los vértices
    en sentido antihorario para que 'adentro' sea 'left'.

    Devuelve el handle, la longitud DESARROLLADA real (rectas + arcos +
    ganchos, para calculate_quantities tipo steel_weight) y los vértices
    con sus bulges tal como quedaron.
    """
    if diameter <= 0:
        raise ValueError("diameter tiene que ser > 0 (en unidades del modelo).")
    if hook_side not in ("left", "right"):
        raise ValueError("hook_side tiene que ser 'left' o 'right'.")
    for h in (start_hook, end_hook):
        if h is not None and str(h) not in HOOKS:
            raise ValueError(f"Gancho {h!r}: tiene que ser uno de {HOOKS}.")
    pts = [(float(p[0]), float(p[1])) for p in points]
    if closed:
        if len(pts) < 3:
            raise ValueError("Un estribo necesita al menos 3 vértices.")
        if math.dist(pts[0], pts[-1]) > 1e-9:
            pts.append(pts[0])
        if start_hook is None and end_hook is None:
            start_hook = end_hook = "135"
        if bend_diameter_factor == 6.0:
            bend_diameter_factor = 4.0     # estribos (ACI 25.3.2)
    if len(pts) < 2:
        raise ValueError("Una varilla necesita al menos 2 puntos.")

    db = float(diameter)
    r = (bend_diameter_factor / 2.0 + 0.5) * db      # radio al eje
    avisos: list[str] = []
    lyr = layer or LAYER_REBAR
    _layer(lyr, lineweight)

    # 1. Trayectoria cruda: cada elemento es (punto, bulge_fijo o None).
    #    Los ganchos entran como vértices más; el de 180° trae su arco.
    raw: list[list[Any]] = [[p, None, 0.0] for p in pts]

    def ext_of(hook: str) -> float:
        return hook_extension if hook_extension > 0 else HOOK_EXT_DB[hook] * db

    if end_hook:
        u = _unit(pts[-2], pts[-1])
        b, extra = _hook_after(pts[-1], u, hook_side, str(end_hook),
                               ext_of(str(end_hook)), r)
        if b:
            raw[-1][1], raw[-1][2] = "fixed", b   # el arco sale del último punto
        for i, q in enumerate(extra):
            raw.append([q, "fixed" if (b and i == 0) else None, 0.0])
    if start_hook:
        # El mismo gancho, construido sobre la trayectoria invertida (el
        # lado se invierte con ella) y vuelto a dar vuelta.
        u = _unit(pts[1], pts[0])
        lado = "right" if hook_side == "left" else "left"
        b, extra = _hook_after(pts[0], u, lado, str(start_hook),
                               ext_of(str(start_hook)), r)
        if b:
            q, e = extra
            # Orden original: e -> q (recto), q -> p0 (arco, sentido opuesto).
            raw = [[e, None, 0.0], [q, "fixed", -b]] + raw
            raw[2][1] = "fixed"
        else:
            raw = [[extra[0], None, 0.0]] + raw

    # 2. Filetes: cada vértice recto entre dos tramos rectos se reemplaza
    #    por los dos puntos de tangencia y el arco.
    salida: list[list[Any]] = [raw[0]]
    for i in range(1, len(raw) - 1):
        v = raw[i]
        prev_out = salida[-1]
        nxt = raw[i + 1]
        if v[1] == "fixed" or prev_out[2] or v[2]:
            salida.append(v)
            continue
        p_prev, p_v, p_next = prev_out[0], v[0], nxt[0]
        u1 = _unit(p_prev, p_v)
        u2 = _unit(p_v, p_next)
        cross = u1[0] * u2[1] - u1[1] * u2[0]
        dot = u1[0] * u2[0] + u1[1] * u2[1]
        if abs(cross) < 1e-9 and dot > 0:
            salida.append(v)      # recto: sin doblez
            continue
        phi = math.atan2(abs(cross), dot)         # ángulo de giro
        t = r * math.tan(phi / 2.0)
        disponible = 0.5 * min(math.dist(p_prev, p_v), math.dist(p_v, p_next))
        r_local = r
        if t > disponible:
            r_local = disponible / math.tan(phi / 2.0)
            t = disponible
            if r_local < r * 0.75:
                avisos.append(
                    "El tramo en (%.3f, %.3f) es más corto que el doblez a "
                    "%.1fdb: se dobló a radio %.3f en vez de %.3f."
                    % (p_v[0], p_v[1], bend_diameter_factor, r_local, r))
        p1 = (p_v[0] - u1[0] * t, p_v[1] - u1[1] * t)
        p2 = (p_v[0] + u2[0] * t, p_v[1] + u2[1] * t)
        bulge = math.tan(phi / 4.0) * (1.0 if cross > 0 else -1.0)
        salida.append([p1, "fixed", bulge])
        salida.append([p2, None, 0.0])
    salida.append(raw[-1])

    verts = [[e[0][0], e[0][1]] for e in salida]
    bulges = [float(e[2] or 0.0) for e in salida]

    # 3. Longitud desarrollada: rectas + arcos.
    largo = 0.0
    for i in range(len(verts) - 1):
        c = math.dist(verts[i], verts[i + 1])
        b = abs(bulges[i])
        if b < 1e-12:
            largo += c
        else:
            theta = 4.0 * math.atan(b)
            largo += c / (2.0 * math.sin(theta / 2.0)) * theta

    handle = acad.call("create_polyline", {
        "points": verts, "bulges": bulges, "closed": False, "layer": lyr,
        "lineweight": lineweight, "colorIndex": color_index,
    })["handle"]

    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    space.track(min(xs), min(ys), max(xs), max(ys), "varilla")
    return {"handle": handle, "length_m": round(largo, 4),
            "points": verts, "bulges": [round(b, 6) for b in bulges],
            "bendRadius": round(r, 4),
            "hooks": {"start": start_hook, "end": end_hook},
            "warnings": avisos}


def create_rebar_dots(points: list, diameter: float,
                      layer: Optional[str] = None,
                      lineweight: int = LW_BAR,
                      color_index: Optional[int] = None) -> dict[str, Any]:
    """Varillas vistas de punta (perpendiculares al plano del corte): un
    punto macizo por barra. Es lo que muestra un corte transversal de las
    barras longitudinales, sean de una trabe, una cadena o una zapata."""
    if diameter <= 0:
        raise ValueError("diameter tiene que ser > 0.")
    lyr = layer or LAYER_REBAR
    _layer(lyr, lineweight)
    handles: list[str] = []
    for p in points:
        h = _circle(float(p[0]), float(p[1]), diameter / 2.0, lyr, lineweight)
        _hatch(h, "SOLID", 1.0, lyr, color_index=color_index
               if color_index is not None else layers.COLOR_PRINCIPAL)
        handles.append(h)
    return {"handles": handles, "count": len(handles)}


# --------------------------------------- corte de cimentacion de muro

FOUNDATION_TYPES = ("zapata_concreto", "piedra_bola", "mamposteria", "ciclopeo")
FOUNDATION_MATERIAL = {"zapata_concreto": "concreto", "piedra_bola": "piedra_bola",
                       "mamposteria": "mamposteria", "ciclopeo": "ciclopeo"}
FOUNDATION_LABEL = {"zapata_concreto": "ZAPATA CORRIDA DE CONCRETO ARMADO",
                    "piedra_bola": "RELLENO DE PIEDRA BOLA",
                    "mamposteria": "MAMPOSTERIA DE PIEDRA BRAZA",
                    "ciclopeo": "CONCRETO CICLOPEO"}


def _bar_positions(a: float, b: float, count: int) -> list[float]:
    """count posiciones entre a y b: las 2 puntas si count>=2 (mas las
    interiores parejas), o el centro si count==1. Igual criterio que
    create_column_section, pero en una sola linea en vez de un perimetro."""
    if count <= 0:
        return []
    if count == 1:
        return [(a + b) / 2.0]
    interior = _spaced_interior_points((a, 0.0), (b, 0.0), count - 2)
    vistos = sorted({round(a, 6), round(b, 6), *(round(p[0], 6) for p in interior)})
    return vistos


def _label_right(text_content: str, x_edge: float, y_true: float,
                 y_label: float, lead: float, text_height: float,
                 layer: str) -> None:
    """Leader + rotulo a la derecha, como en annotation.create_layer_section
    -- el mismo criterio de "un corte por capas se lee de lo dibujado hacia
    su nombre, no al reves". y_true es el punto real que se señala; y_label
    es donde queda el texto -- distintos cuando _apilar_labels tuvo que
    correrlo para no chocar con el de al lado, y ahí el leader sale
    diagonal en vez de horizontal (igual que un leader real que evita otro
    rotulo)."""
    tx = x_edge + lead
    _line((x_edge, y_true), (tx, y_label), layer, LW_LEADER)
    _text(text_content, tx + text_height * 0.4, y_label - text_height / 2.0,
          text_height, layer)
    ancho = len(text_content) * text_height * 0.87
    space.track(tx, y_label - text_height, tx + ancho + text_height * 0.4,
                y_label + text_height * 0.5,
                f"{space.PREFIJO_TEXTO}{text_content[:40]}")


def _apilar_labels(entries: list[tuple[float, str]],
                   min_gap: float) -> list[float]:
    """Ajusta las posiciones Y de una lista de rotulos (ya en orden
    creciente) para que ninguno quede a menos de min_gap del anterior.

    Sin esto, dos capas mas finas que un texto (una zapata de 0.20 con una
    plantilla de 0.10 debajo, por ejemplo) quedan con las etiquetas
    literalmente pegadas -- paso de verdad en la primera prueba real de
    este corte. Es el mismo problema que resuelve place_labels para los
    nombres de ambiente, simplificado a una sola columna: aca los rotulos
    van siempre a la derecha, en el mismo orden vertical que sus capas."""
    y_labels: list[float] = []
    previo: Optional[float] = None
    for y_true, _ in entries:
        y = y_true if previo is None else max(y_true, previo + min_gap)
        y_labels.append(y)
        previo = y
    return y_labels


def _rect_pts(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def create_footing_section(
    x: float, y: float,
    foundation_type: str,
    wall_thickness: float,
    footing_width: float,
    footing_thickness: float,
    text_height: float,
    lean_concrete_thickness: float = 0.10,
    footing_edge_thickness: float = 0.0,
    pedestal_height: float = 0.0,
    pedestal_width: float = 0.0,
    grade_beam_height: float = 0.0,
    grade_beam_width: Optional[float] = None,
    grade_beam_bars: int = 0,
    wall_height: float = 0.6,
    dowel_count: int = 0,
    dowel_leg: float = 0.0,
    bar_diameter: float = 0.0127,
    stirrup_diameter: float = 0.0095,
    stirrup_spacing: float = 0.0,
    cover: float = 0.05,
    beam_cover: Optional[float] = None,
    footing_bar_count: int = 0,
    footing_hook: str = "90",
    ground_level: Optional[float] = None,
    excavation_margin: float = 0.30,
    soil_depth_below: float = 0.15,
    wall_material: str = "block",
    stone_size: Optional[list[float]] = None,
    specs: Optional[dict[str, str]] = None,
    dimension: bool = True,
    labels: bool = True,
    title: str = "",
    mark: str = "",
    scale: float = 0.0,
    layer: Optional[str] = None,
) -> dict[str, Any]:
    """Corte TRANSVERSAL de la cimentación de un muro corrido -- barda,
    muro de carga liviano -- de la excavación hacia arriba. Es una
    COMPOSICIÓN de las primitivas de detalle (materials.draw_material,
    fill_stones, soil_section, create_rebar): no sabe dibujar nada que
    esas no sepan, y cualquier cimentación que no entre en estos parámetros
    se compone con ellas directamente.

    (x, y): x es el EJE del muro; y es el nivel de desplante, la base de la
    plantilla -- el punto más bajo de todo el corte.

    foundation_type: 'zapata_concreto' (losa de concreto ARMADO),
    'piedra_bola' (relleno de piedra junteada, sin acero), 'mamposteria'
    (piedra braza) o 'ciclopeo' (concreto con piedra embebida).
    footing_edge_thickness: espesor de la zapata en el BORDE. 0 = zapata
    rectangular; menor que footing_thickness = zapata con talud, que sube
    del borde hasta el dado o el muro (la forma real de una zapata corrida
    de concreto).
    pedestal_height/pedestal_width: el dado entre la zapata y la cadena.
    grade_beam_height/grade_beam_width/grade_beam_bars: la cadena de
    desplante y sus varillas longitudinales, vistas de punta -- con bars>0
    se dibuja el estribo cerrado con ganchos a 135° y los puntos.
    dowel_count: varillas de arranque hacia el muro, ancladas en L dentro
    de la zapata (dowel_leg = pata horizontal; 0 = 12 diámetros).
    stirrup_spacing: separación de los estribos del dado (o de la cadena si
    no hay dado), vistos como líneas -- un MÁXIMO de obra. Pide dowels.
    footing_bar_count: varillas LONGITUDINALES de la zapata (de punta); con
    ellas se dibuja además la transversal doblada con gancho (footing_hook)
    en las dos puntas, que es lo que muestra un corte transversal.
    cover: recubrimiento de la zapata y los arranques (en contacto con el
    suelo, 5 cm es lo usual). beam_cover: el de la cadena y el dado; None
    toma cover. Un estribo de cadena de 20x20 con 5 cm de recubrimiento
    queda de 10x10: si el proyecto especifica 2.5-3 cm, pasalo acá.
    ground_level: cota del terreno natural (absoluta). Default: el tope de
    la cadena o del dado. excavation_margin: cuánta tierra se muestra a
    cada lado; soil_depth_below: cuánta debajo de la plantilla. 0 y 0
    omiten el terreno.
    specs: texto de especificación por pieza, se agrega al rótulo --
    {"plantilla": "f'c=100 kg/cm²", "footing": "f'c=200 kg/cm²",
    "stones": "JUNTEADA CON MORTERO CEMENTO-ARENA 1:5"}. Claves:
    plantilla, footing, pedestal, grade_beam, wall, stones, dowels, bars.
    title/mark: título de vista (sin separar letras) y la letra en globo
    ('A') a su izquierda.
    scale: unidades del modelo por mm de papel del DETALLE (un detalle
    va a 1:20 o 1:25 aunque la lámina sea 1:100); 0 toma el de la lámina.

    Devuelve los handles de cada pieza (para calculate_quantities), las
    longitudes reales de acero, 'levels' y 'warnings'.
    """
    if foundation_type not in FOUNDATION_TYPES:
        raise ValueError(
            f"foundation_type tiene que ser uno de {FOUNDATION_TYPES}, "
            f"no {foundation_type!r}.")
    if wall_thickness <= 0 or footing_width <= 0 or footing_thickness <= 0:
        raise ValueError(
            "wall_thickness, footing_width y footing_thickness tienen que "
            "ser > 0.")
    if lean_concrete_thickness <= 0:
        raise ValueError(
            "lean_concrete_thickness tiene que ser > 0: una zapata o un "
            "relleno apoyado directo en tierra suelta no es una cimentación.")
    if footing_width < wall_thickness:
        raise ValueError(
            f"footing_width ({footing_width:g}) no puede ser menor que "
            f"wall_thickness ({wall_thickness:g}): el muro no apoyaría.")
    if footing_bar_count > 0 and foundation_type != "zapata_concreto":
        raise ValueError(
            "footing_bar_count es acero de zapata de concreto armado: un "
            f"relleno de {foundation_type} no lleva armado.")
    if footing_edge_thickness < 0 or footing_edge_thickness > footing_thickness:
        raise ValueError(
            "footing_edge_thickness tiene que estar entre 0 y "
            "footing_thickness.")
    if (pedestal_height > 0) != (pedestal_width > 0):
        raise ValueError("pedestal_height y pedestal_width van los dos o ninguno.")
    if pedestal_width and pedestal_width < wall_thickness:
        raise ValueError("pedestal_width no puede ser menor que wall_thickness.")
    if stirrup_spacing > 0 and grade_beam_height <= 0 and pedestal_height <= 0:
        raise ValueError(
            "stirrup_spacing estriba el dado o la cadena de desplante, pero "
            "no hay ninguno de los dos (grade_beam_height/pedestal_height).")
    if stirrup_spacing > 0 and dowel_count <= 0:
        raise ValueError(
            "Estribos sin varilla de arranque no tienen qué amarrar: "
            "pasá dowel_count.")
    if str(footing_hook) not in HOOKS:
        raise ValueError(f"footing_hook tiene que ser uno de {HOOKS}.")
    if grade_beam_bars > 0 and grade_beam_height <= 0:
        raise ValueError("grade_beam_bars sin grade_beam_height: no hay cadena.")

    avisos: list[str] = []
    for nombre, val in (("footing_thickness", footing_thickness),
                        ("lean_concrete_thickness", lean_concrete_thickness),
                        ("wall_thickness", wall_thickness)):
        if val < 0.04:
            avisos.append(
                f"{nombre}={val:g}: menos de 4 cm si el dibujo está en metros. "
                "¿Está en la unidad correcta?")

    specs = specs or {}
    bc = beam_cover if beam_cover is not None and beam_cover > 0 else cover
    lyr = layer or LAYER_FOOTING_SECTION
    _layer(lyr, LW_OUTLINE)
    upm = scale if scale > 0 else space.units_per_paper_mm()
    gb_width = (grade_beam_width if grade_beam_width and grade_beam_width > 0
                else wall_thickness)
    if gb_width < wall_thickness:
        raise ValueError(
            f"grade_beam_width ({gb_width:g}) no puede ser menor que "
            f"wall_thickness ({wall_thickness:g}).")

    piezas: list[dict[str, Any]] = []
    half_w = footing_width / 2.0

    # --- 1. plantilla ------------------------------------------------------
    p_y0, p_y1 = y, y + lean_concrete_thickness
    plantilla = mat_mod.draw_material(
        _rect_pts(x - half_w, p_y0, x + half_w, p_y1), "concreto_pobre",
        layer=lyr, scale=upm)
    piezas.append(plantilla)

    # --- 2. zapata / relleno, rectangular o con talud ----------------------
    f_y0, f_y1 = p_y1, p_y1 + footing_thickness
    apoyo_w = pedestal_width if pedestal_height > 0 else max(gb_width, wall_thickness)
    if footing_edge_thickness > 0 and footing_edge_thickness < footing_thickness \
            and apoyo_w < footing_width:
        ye = f_y0 + footing_edge_thickness
        footing_pts = [[x - half_w, f_y0], [x + half_w, f_y0],
                       [x + half_w, ye], [x + apoyo_w / 2.0, f_y1],
                       [x - apoyo_w / 2.0, f_y1], [x - half_w, ye]]
    else:
        footing_pts = _rect_pts(x - half_w, f_y0, x + half_w, f_y1)
    footing = mat_mod.draw_material(
        footing_pts, FOUNDATION_MATERIAL[foundation_type], layer=lyr,
        scale=upm, stone_size=stone_size)
    piezas.append(footing)

    # --- 3. dado -------------------------------------------------------------
    top = f_y1
    pedestal = None
    if pedestal_height > 0:
        pedestal = mat_mod.draw_material(
            _rect_pts(x - pedestal_width / 2.0, top, x + pedestal_width / 2.0,
                      top + pedestal_height), "concreto", layer=lyr, scale=upm)
        piezas.append(pedestal)
        top += pedestal_height

    # --- 4. cadena de desplante ---------------------------------------------
    grade_beam = None
    gb_y0 = top
    if grade_beam_height > 0:
        grade_beam = mat_mod.draw_material(
            _rect_pts(x - gb_width / 2.0, top, x + gb_width / 2.0,
                      top + grade_beam_height), "concreto", layer=lyr, scale=upm)
        piezas.append(grade_beam)
        top += grade_beam_height
    top_before_wall = top

    # --- 5. muro (arranque) --------------------------------------------------
    wall = None
    if wall_height > 0:
        wall = mat_mod.draw_material(
            _rect_pts(x - wall_thickness / 2.0, top, x + wall_thickness / 2.0,
                      top + wall_height), wall_material, layer=lyr, scale=upm)
        piezas.append(wall)
        top += wall_height
    top_total = top
    for p in piezas:
        avisos.extend(p.get("warnings", []))

    # --- 6. terreno alrededor ------------------------------------------------
    nivel_terreno = ground_level if ground_level is not None else top_before_wall
    soil = None
    if excavation_margin > 0 or soil_depth_below > 0:
        e_x0 = x - half_w - max(excavation_margin, 0.0)
        e_x1 = x + half_w + max(excavation_margin, 0.0)
        soil = mat_mod.soil_section(
            e_x0, e_x1, nivel_terreno, y - max(soil_depth_below, 0.0),
            islands=piezas, scale=upm, ground_extension=excavation_margin * 0.6)
        avisos.extend(soil.get("warnings", []))

    # --- 7. acero --------------------------------------------------------------
    db = bar_diameter
    acero: dict[str, Any] = {"handles": [], "totalDowelLength_m": 0.0,
                             "footingBarLength_m": 0.0,
                             "stirrupLength_m": 0.0}
    footing_bar_handles: list[str] = []
    if footing_bar_count > 0:
        y_bar = f_y0 + cover + db / 2.0
        xs = _bar_positions(x - half_w + cover + db, x + half_w - cover - db,
                            footing_bar_count)
        dots = create_rebar_dots([[bx, y_bar] for bx in xs], db, layer=lyr)
        footing_bar_handles = dots["handles"]
        # La transversal: de borde a borde, con gancho hacia arriba. El
        # gancho tiene que caber en el espesor DEL BORDE (una zapata con
        # talud es más delgada ahí que al centro).
        espesor_borde = (footing_edge_thickness
                         if 0 < footing_edge_thickness < footing_thickness
                         and apoyo_w < footing_width else footing_thickness)
        alto_gancho = espesor_borde - 2 * cover - db
        if alto_gancho > 0:
            barra = create_rebar(
                [[x - half_w + cover, y_bar], [x + half_w - cover, y_bar]], db,
                start_hook=str(footing_hook), end_hook=str(footing_hook),
                hook_side="left", layer=lyr,
                hook_extension=min(alto_gancho, HOOK_EXT_DB[str(footing_hook)] * db))
            acero["handles"].append(barra["handle"])
            acero["footingBarLength_m"] = barra["length_m"]
            avisos.extend(barra.get("warnings", []))

    dowel_handles: list[str] = []
    if dowel_count > 0:
        band = (pedestal_width if pedestal_height > 0
                else gb_width if grade_beam_height > 0 else wall_thickness)
        d_x0, d_x1 = x - band / 2.0 + cover, x + band / 2.0 - cover
        if d_x1 <= d_x0:
            raise ValueError(
                f"cover ({cover:g}) no deja espacio para el arranque en un "
                f"ancho de {band:g}.")
        y_anchor = f_y0 + cover + db * 1.5      # sobre la parrilla de la zapata
        if foundation_type != "zapata_concreto":
            y_anchor = f_y0 + cover
        pata = dowel_leg if dowel_leg > 0 else HOOK_EXT_DB["90"] * db
        largo = 0.0
        for i, dx in enumerate(_bar_positions(d_x0, d_x1, dowel_count)):
            # Las patas miran hacia adentro: la de la izquierda a la
            # derecha, la de la derecha a la izquierda, alternando en medio.
            hacia = 1.0 if (dx < x - 1e-9 or (abs(dx - x) < 1e-9 and i % 2 == 0)) else -1.0
            pata_real = min(pata, half_w - cover - abs(dx - x) - db)
            barra = create_rebar(
                [[dx, top_total], [dx, y_anchor]], db,
                end_hook="90", hook_side="left" if hacia > 0 else "right",
                hook_extension=max(pata_real, db * 2), layer=lyr)
            dowel_handles.append(barra["handle"])
            largo += barra["length_m"]
            avisos.extend(barra.get("warnings", []))
        acero["totalDowelLength_m"] = round(largo, 3)

        if stirrup_spacing > 0:
            # Estribos del dado (o de la cadena), vistos de canto.
            if pedestal_height > 0:
                s_y0, s_y1, s_w = f_y1, f_y1 + pedestal_height, pedestal_width
            else:
                s_y0, s_y1, s_w = gb_y0, gb_y0 + grade_beam_height, gb_width
            pos, _paso, avisos_e = _posiciones_estribos(
                s_y0 + bc, s_y1 - bc, stirrup_spacing)
            avisos.extend(avisos_e)
            for t in pos:
                acero["handles"].append(
                    _line((x - s_w / 2.0 + bc, t), (x + s_w / 2.0 - bc, t),
                          lyr, LW_STIRRUP))
            acero["stirrupCount"] = len(pos)

    if grade_beam is not None and grade_beam_bars > 0:
        c = bc
        sx0, sy0 = x - gb_width / 2.0 + c, gb_y0 + c
        sx1, sy1 = x + gb_width / 2.0 - c, gb_y0 + grade_beam_height - c
        estribo = create_rebar([[sx0, sy0], [sx1, sy0], [sx1, sy1], [sx0, sy1]],
                               stirrup_diameter, closed=True, layer=lyr,
                               lineweight=LW_STIRRUP)
        acero["handles"].append(estribo["handle"])
        acero["stirrupLength_m"] = estribo["length_m"]
        avisos.extend(estribo.get("warnings", []))
        esquinas = [(sx0, sy0), (sx1, sy0), (sx1, sy1), (sx0, sy1)]
        pts_bars = list(esquinas[:grade_beam_bars]) if grade_beam_bars <= 4 else esquinas
        if grade_beam_bars > 4:
            extra = grade_beam_bars - 4
            arriba = (extra + 1) // 2
            abajo = extra - arriba
            pts_bars += _spaced_interior_points((sx0, sy1), (sx1, sy1), arriba)
            pts_bars += _spaced_interior_points((sx0, sy0), (sx1, sy0), abajo)
        ins = db / 2.0 + stirrup_diameter / 2.0
        centros = [[px + (ins if px < x else -ins), py + (ins if py < (sy0 + sy1) / 2 else -ins)]
                   for px, py in pts_bars]
        acero["handles"].extend(create_rebar_dots(centros, db, layer=lyr)["handles"])

    max_half = max(half_w + max(excavation_margin, 0.0), gb_width / 2.0,
                   wall_thickness / 2.0, pedestal_width / 2.0)
    space.track(x - max_half, y, x + max_half, top_total,
                f"cimentacion de muro {lyr}")

    # --- 8. rótulos ------------------------------------------------------------
    def con_spec(base: str, clave: str) -> str:
        s = specs.get(clave)
        return f"{base} {s}" if s else base

    x_edge = x + max_half
    lead = max(max_half * 0.5, text_height * 3.0)
    caja_titulo = None
    if labels:
        entries: list[tuple[float, str]] = [
            ((p_y0 + p_y1) / 2.0, con_spec("PLANTILLA DE CONCRETO POBRE", "plantilla")),
            ((f_y0 + f_y1) / 2.0, con_spec(FOUNDATION_LABEL[foundation_type],
                                           "stones" if foundation_type != "zapata_concreto" else "footing")),
        ]
        if footing_bar_count > 0:
            entries.append((f_y0 + cover + db, con_spec("ARMADO DE ZAPATA", "bars")))
        if pedestal is not None:
            entries.append(((f_y1 + f_y1 + pedestal_height) / 2.0,
                            con_spec("DADO DE CONCRETO", "pedestal")))
        if grade_beam is not None:
            entries.append(((gb_y0 + gb_y0 + grade_beam_height) / 2.0,
                            con_spec("CADENA DE DESPLANTE", "grade_beam")))
        if dowel_count > 0:
            entries.append((top_before_wall + (wall_height * 0.35 if wall else 0.0),
                            con_spec("ARMADO DE ARRANQUE", "dowels")))
        if wall is not None:
            entries.append((top_before_wall + wall_height * 0.75,
                            con_spec("MURO DE " + str(wall.get("label", "BLOCK")), "wall")))
        entries.sort(key=lambda e: e[0])
        y_labels = _apilar_labels(entries, text_height * 1.9)
        for (y_true, texto), y_label in zip(entries, y_labels):
            _label_right(texto, x_edge, y_true, y_label, lead, text_height, lyr)
        if title:
            techo = max(top_total, y_labels[-1] if y_labels else top_total,
                        nivel_terreno)
            t = sym_mod.create_view_title(
                x - max_half, techo + text_height * 3.0, title,
                scale_text="SIN ESCALA", height=text_height * 1.5,
                spaced=False, mark=mark)
            caja_titulo = t.get("box")

    # --- 9. cotas ----------------------------------------------------------------
    dims: dict[str, Any] = {}
    if dimension:
        niveles = {round(v, 6) for v in
                   [y, p_y1, f_y1]
                   + ([f_y1 + pedestal_height] if pedestal is not None else [])
                   + ([gb_y0 + grade_beam_height] if grade_beam is not None else [])
                   + ([top_total] if wall is not None else [])}
        ref_x = x - max_half
        if len(niveles) >= 2:
            dims["heights"] = ann_mod.create_dimension_chain(
                positions=sorted(niveles), side="left", reference=ref_x,
                scale=upm)
        bottom_ref = y - max(soil_depth_below, 0.0) if soil else y
        dims["width"] = ann_mod.create_dimension_chain(
            positions=[x - half_w, x + half_w], side="bottom",
            reference=bottom_ref, scale=upm)

    # La caja TOTAL, rótulos incluidos: es lo que hay que dejar libre antes
    # de dibujar el siguiente detalle al lado. Sin esto el rótulo largo de
    # uno se metía en las cotas del otro (pasó con dos cortes a 4 m).
    x_max_total = x_edge
    y_min_total = min(y, soil["box"][1] if soil else y)
    y_max_total = top_total
    for h in space.FOOTPRINTS:
        if str(h.get("what", "")).startswith(space.PREFIJO_TEXTO) \
                and h["x0"] >= x_edge - 1e-6 and h["y0"] >= y - text_height * 3:
            x_max_total = max(x_max_total, h["x1"])
            y_max_total = max(y_max_total, h["y1"])
    if caja_titulo:
        x_max_total = max(x_max_total, caja_titulo[2])
        y_max_total = max(y_max_total, caja_titulo[3])
    if dims.get("heights"):
        y_min_total = min(y_min_total, dims["heights"]["band"][1])
    if dims.get("width"):
        y_min_total = min(y_min_total, dims["width"]["band"][1])

    return {
        "box": [round(min(x - max_half, dims["heights"]["band"][0]
                          if dims.get("heights") else x - max_half), 4),
                round(y_min_total, 4), round(x_max_total, 4),
                round(y_max_total, 4)],
        "leanConcreteHandle": plantilla["handle"],
        "footingHandle": footing["handle"],
        "footingArea_m2": footing["area"],
        "footingBarHandles": footing_bar_handles,
        "stoneHandles": footing.get("stoneHandles", []),
        "stoneCount": footing.get("stoneCount", 0),
        "pedestalHandle": pedestal["handle"] if pedestal else None,
        "gradeBeamHandle": grade_beam["handle"] if grade_beam else None,
        "wallHandle": wall["handle"] if wall else None,
        "soil": soil,
        "dowelHandles": dowel_handles,
        "steelHandles": acero["handles"],
        "totalDowelLength_m": acero["totalDowelLength_m"],
        "footingBarLength_m": acero["footingBarLength_m"],
        "stirrupLength_m": acero["stirrupLength_m"],
        "stirrupCount": acero.get("stirrupCount", 0),
        "dimensions": dims,
        "titleBox": caja_titulo,
        "levels": {"desplante": y, "topPlantilla": p_y1, "topFooting": f_y1,
                   "topPedestal": f_y1 + pedestal_height if pedestal else None,
                   "topGradeBeam": gb_y0 + grade_beam_height if grade_beam else None,
                   "groundLevel": nivel_terreno, "top": top_total},
        "warnings": avisos,
    }
