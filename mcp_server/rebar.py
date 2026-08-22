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

import autocad_client as acad
import layers
import space

LAYER_COLUMN = "ARMADO-COLUMNA"
LAYER_FOOTING = "ARMADO-ZAPATA"

LW_OUTLINE = 50
LW_STIRRUP = 25
LW_BAR = 18
LW_MAT = 18
LW_SUPPORT_REF = 13

DEFAULT_CONCRETE_HATCH = "AR-CONC"


def _layer(name: str, lineweight: int, linetype: Optional[str] = None) -> None:
    layers.ensure(name, layers.COLOR_PRINCIPAL, lineweight, linetype)
    layers.ensure_text_style()


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


def _hatch(handle: str, pattern: str, scale: float, layer: str) -> Optional[str]:
    try:
        return acad.call("create_hatch", {
            "boundaryHandle": handle, "pattern": pattern, "scale": scale,
            "angleDeg": 0.0, "layer": layer,
            "lineweight": 5, "colorIndex": layers.COLOR_SECUNDARIO,
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
                          hatch_scale: float = 1.0,
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
    _hatch(outline_handle, hatch_pattern, hatch_scale, lyr)

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
