"""Cortes y fachadas de un edificio: corte vertical por niveles.

Un corte necesita saber, en cada nivel, qué muros corta de verdad el plano de
corte (se dibujan CORTADOS: banda gruesa achurada) y cuáles quedan vistos de
fondo (línea fina sin achurar). Esa decisión es de criterio de quien proyecta
—no se puede derivar del eje en planta de `create_walls`, porque en este
repo no existe ningún concepto de nivel/Z (todo es 2D, Z siempre 0.0)—, así
que esta tool recibe la lista de niveles ya resuelta, igual que
`annotation.create_layer_section` recibe sus capas ya resueltas en vez de
inferirlas de otra cosa.

Se compone igual que `profile.py` (perfiles de calle): una proyección simple
X = distancia a lo largo del corte, Y = cota, sin exagerar nunca la vertical
—a diferencia de un perfil vial, un corte de edificio se dibuja siempre 1:1
en los dos ejes.

Unidades: las del modelo (metros si se dibuja en metros). Alturas SIEMPRE
piso a piso reales de obra, nunca mm de papel.
"""
from __future__ import annotations

from typing import Any, Optional

import annotation as ann_mod
import autocad_client as acad
import layers
import space

LAYER_CUT = "CORTES-ARQ"          # no "CORTES": ya lo usa annotation.py
LAYER_SEEN = "CORTES-ARQ-VISTO"   # ni "SECCIONES": ya lo usa profile.py
LAYER_FACADE = "FACHADAS"

LW_CUT = 50     # muros/losas cortados: el trazo más grueso del corte
LW_SEEN = 25    # contornos vistos: aberturas, muros de fondo, envolvente
LW_HATCH = 9
LW_TEXT = 18

VALID_VIEWS = ("corte", "fachada")
VALID_ELEMENT_TYPES = ("cut_wall", "window", "door", "seen_wall")


def _layer(name: str, lineweight: int) -> None:
    layers.ensure(name, layers.COLOR_PRINCIPAL, lineweight)
    layers.ensure_text_style()


def _rect(x0: float, y0: float, x1: float, y1: float, layer: str,
          lineweight: int) -> str:
    return acad.call("create_polyline", {
        "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        "closed": True, "layer": layer,
        "lineweight": lineweight, "colorIndex": None,
    })["handle"]


def _hatch(handle: str, pattern: str, scale: float, layer: str) -> Optional[str]:
    try:
        return acad.call("create_hatch", {
            "boundaryHandle": handle, "pattern": pattern, "scale": scale,
            "angleDeg": 0.0, "layer": layer,
            "lineweight": LW_HATCH, "colorIndex": layers.COLOR_SECUNDARIO,
        })["handle"]
    except acad.AutoCadError:
        # Un patrón que no existe en acad.pat no debe tumbar el corte entero.
        return None


def _text(content: str, x: float, y: float, height: float, layer: str) -> Optional[str]:
    if not content:
        return None
    return acad.call("create_text", {
        "text": content, "x": x, "y": y, "z": 0.0, "height": height,
        "layer": layer, "rotationDeg": 0.0,
        "lineweight": LW_TEXT, "colorIndex": None,
    })["handle"]


def _w(text: str, height: float) -> float:
    """Ancho real del texto, preguntándole a AutoCAD (con respaldo estimado)."""
    try:
        return acad.call("measure_text", {
            "text": text, "height": height,
            "style": None, "widthFactor": None})["width"]
    except (acad.AutoCadError, KeyError, TypeError):
        return len(text) * height * 0.87


def _fmt_level(elev: float) -> str:
    if elev > 1e-9:
        return f"N.P.T. +{elev:.2f}"
    if elev < -1e-9:
        return f"N.P.T. -{abs(elev):.2f}"
    return "N.P.T. ±0.00"


def create_building_section(
    x: float, y: float, length: float,
    stories: list[dict[str, Any]],
    view: str = "corte",
    datum: float = 0.0,
    dimension_stories: bool = True,
    dimension_side: str = "left",
    level_labels: bool = True,
    hatch_pattern: str = "ANSI31",
    hatch_scale: float = 1.0,
    layer_cut: Optional[str] = None,
    layer_seen: Optional[str] = None,
    text_height: float = 0.0,
) -> dict[str, Any]:
    """Corte vertical (o fachada) de un edificio, por niveles.

    (x, y) es el extremo IZQUIERDO del corte, a la cota ±0.00 de stories[0].
    length es la extensión horizontal del corte.

    stories: de ABAJO hacia arriba, uno por nivel:
      {"name": "PB", "height": 2.90, "slab_thickness": 0.12, "elements": [...]}
    height es piso a piso e INCLUYE el espesor de su propia losa superior, así
    una azotea plana es simplemente el último nivel de la lista (con
    slab_thickness = espesor de la losa de azotea), sin caso especial.

    elements, por nivel — mismo estilo que 'openings' en create_walls:
      {"type": "cut_wall", "x": 0.15, "thickness": 0.15, "top": None}
          Un muro que el plano de corte SÍ atraviesa: banda achurada, el
          trazo más grueso del corte. 'x' es el eje; 'top' opcional para
          cortarlo antes del cielo raso (hueco de escalera, doble altura).
      {"type": "window", "x_start":.., "x_end":.., "sill":.., "head":..}
      {"type": "door",   "x_start":.., "x_end":.., "head":..}
          Aberturas del muro de FONDO, vistas más allá del plano de corte
          (el caso real: casi nunca se elige la línea de corte para que pase
          justo por un vano). sill/head en metros DESDE EL PISO de ese nivel,
          no cota absoluta. head por defecto, la altura libre del nivel.
      {"type": "seen_wall", "x_start":.., "x_end":..}
          Silueta de un muro visto de fondo, sin achurar.

    view: "corte" achura y dibuja losas; "fachada" nunca achura ni dibuja
    losas (una fachada no muestra espesores), y los cut_wall pasan a ser la
    envolvente exterior vista (línea fina, no la banda cortada).

    datum: cota del arranque de stories[0] (para un semisótano en -1.50, por
    ejemplo, sin tocar la aritmética de los niveles).

    dimension_stories: acota los niveles con create_dimension_chain (side=
    dimension_side) en vez de tener que calcular el offset a mano. Los
    rótulos de nivel (level_labels) se ubican del lado OPUESTO a la cadena de
    cotas, para no encimarse con ella.

    Devuelve los niveles con su cota y su Y de modelo, los handles por nivel,
    y 'warning' si algún vano supera la altura libre de su nivel (se dibuja
    igual: puede ser una doble altura intencional)."""
    if view not in VALID_VIEWS:
        raise ValueError(f"view tiene que ser uno de {VALID_VIEWS}, no {view!r}.")
    if length <= 0:
        raise ValueError("length tiene que ser > 0.")
    if not stories:
        raise ValueError("Hay que pasar al menos un nivel en 'stories'.")
    if dimension_side not in ("left", "right"):
        raise ValueError("dimension_side tiene que ser 'left' o 'right'.")

    es_fachada = view == "fachada"
    cut_layer = layer_cut or (LAYER_FACADE if es_fachada else LAYER_CUT)
    seen_layer = layer_seen or (LAYER_FACADE if es_fachada else LAYER_SEEN)
    _layer(cut_layer, LW_SEEN if es_fachada else LW_CUT)
    _layer(seen_layer, LW_SEEN)

    th = text_height if text_height > 0 else space.paper(2.5)

    def PX(d: float) -> float:
        return x + d

    def PY(elev: float) -> float:
        return y + elev

    # --- Niveles acumulados: levels[i] = cota del piso de stories[i]; el
    # último valor es la cota de remate (arriba del último nivel). ---
    levels = [0.0]
    for i, story in enumerate(stories):
        try:
            height = float(story["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Nivel #{i + 1}: hace falta 'height'. ({exc})")
        if height <= 0:
            raise ValueError(
                f"Nivel #{i + 1} ('{story.get('name', '?')}'): height tiene "
                "que ser > 0.")
        levels.append(levels[-1] + height)

    story_handles: list[dict[str, Any]] = []
    warnings: list[str] = []

    for i, story in enumerate(stories):
        nombre = str(story.get("name", f"N{i + 1}"))
        bottom, top = levels[i], levels[i + 1]
        try:
            espesor = float(story.get("slab_thickness", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Nivel '{nombre}': slab_thickness inválido. ({exc})")
        if espesor < 0:
            raise ValueError(f"Nivel '{nombre}': slab_thickness no puede ser negativo.")
        wall_top = top - espesor
        if wall_top <= bottom:
            raise ValueError(
                f"Nivel '{nombre}': slab_thickness ({espesor:g}) es mayor o "
                f"igual que la altura del nivel ({top - bottom:g}).")
        altura_libre = wall_top - bottom

        elementos = story.get("elements", [])

        # --- Pasada 1: validar TODO antes de dibujar nada de este nivel,
        # igual que create_walls valida los huecos antes de trazar el muro. ---
        bandas_muro: list[tuple[float, float, float]] = []
        for j, el in enumerate(elementos):
            tipo = el.get("type")
            if tipo not in VALID_ELEMENT_TYPES:
                raise ValueError(
                    f"Nivel '{nombre}' elemento #{j + 1}: type tiene que ser "
                    f"uno de {VALID_ELEMENT_TYPES}, no {tipo!r}.")

            if tipo == "cut_wall":
                cx = float(el["x"])
                thickness = float(el.get("thickness", 0.15))
                if thickness <= 0:
                    raise ValueError(
                        f"Nivel '{nombre}': cut_wall en x={cx:g} tiene "
                        "thickness <= 0.")
                x0, x1 = cx - thickness / 2.0, cx + thickness / 2.0
                if x0 < -1e-9 or x1 > length + 1e-9:
                    raise ValueError(
                        f"Nivel '{nombre}': cut_wall en x={cx:g} se sale del "
                        f"corte, que mide {length:g}.")
                wtop = el.get("top")
                if wtop is not None and float(wtop) <= bottom:
                    raise ValueError(
                        f"Nivel '{nombre}': cut_wall en x={cx:g}: 'top' tiene "
                        "que ser mayor que la cota del piso de ese nivel.")
                bandas_muro.append((x0, x1, cx))

            elif tipo in ("window", "door"):
                x0, x1 = float(el["x_start"]), float(el["x_end"])
                if x1 <= x0:
                    raise ValueError(
                        f"Nivel '{nombre}': {tipo} necesita x_end > x_start.")
                if x0 < -1e-9 or x1 > length + 1e-9:
                    raise ValueError(
                        f"Nivel '{nombre}': {tipo} entre x={x0:g} y x={x1:g} "
                        f"se sale del corte, que mide {length:g}.")
                head = float(el.get("head", altura_libre))
                sill = float(el.get("sill", 0.0)) if tipo == "window" else 0.0
                if sill >= head:
                    raise ValueError(
                        f"Nivel '{nombre}': {tipo} en x={x0:g}..{x1:g}: sill "
                        "tiene que ser menor que head.")
                if head > altura_libre + 1e-6:
                    warnings.append(
                        f"nivel '{nombre}' {tipo} x={x0:g}..{x1:g}: head "
                        f"({head:.2f}) supera la altura libre del nivel "
                        f"({altura_libre:.2f}) -- ¿doble altura intencional?")

            else:  # seen_wall
                x0, x1 = float(el["x_start"]), float(el["x_end"])
                if x1 <= x0:
                    raise ValueError(
                        f"Nivel '{nombre}': seen_wall necesita x_end > x_start.")
                if x0 < -1e-9 or x1 > length + 1e-9:
                    raise ValueError(
                        f"Nivel '{nombre}': seen_wall entre x={x0:g} y "
                        f"x={x1:g} se sale del corte, que mide {length:g}.")

        bandas_muro.sort()
        for (a0, a1, _), (b0, _, bcx) in zip(bandas_muro, bandas_muro[1:]):
            if b0 < a1 - 1e-9:
                raise ValueError(
                    f"Nivel '{nombre}': dos cut_wall se pisan (uno termina en "
                    f"{a1:.2f}, el siguiente arranca en {b0:.2f}, cerca de "
                    f"x={bcx:g}).")

        # --- Pasada 2: dibujar. ---
        slab_handle = None
        if espesor > 0 and not es_fachada:
            h = _rect(PX(0), PY(wall_top), PX(length), PY(top), cut_layer, LW_CUT)
            _hatch(h, hatch_pattern, hatch_scale, cut_layer)
            space.track(PX(0), PY(wall_top), PX(length), PY(top),
                       what=f"corte losa {nombre}")
            slab_handle = h

        cut_handles: list[str] = []
        seen_handles: list[str] = []
        for el in elementos:
            tipo = el["type"]
            if tipo == "cut_wall":
                cx = float(el["x"])
                thickness = float(el.get("thickness", 0.15))
                x0, x1 = cx - thickness / 2.0, cx + thickness / 2.0
                wtop = el.get("top")
                wtop = wall_top if wtop is None else float(wtop)
                if es_fachada:
                    h = _rect(PX(x0), PY(bottom), PX(x1), PY(wtop), seen_layer, LW_SEEN)
                    seen_handles.append(h)
                    space.track(PX(x0), PY(bottom), PX(x1), PY(wtop),
                               what=f"fachada muro {nombre}")
                else:
                    h = _rect(PX(x0), PY(bottom), PX(x1), PY(wtop), cut_layer, LW_CUT)
                    _hatch(h, hatch_pattern, hatch_scale, cut_layer)
                    cut_handles.append(h)
                    space.track(PX(x0), PY(bottom), PX(x1), PY(wtop),
                               what=f"corte muro {nombre}")

            elif tipo in ("window", "door"):
                x0, x1 = float(el["x_start"]), float(el["x_end"])
                head = float(el.get("head", altura_libre))
                sill = float(el.get("sill", 0.0)) if tipo == "window" else 0.0
                h = _rect(PX(x0), PY(bottom + sill), PX(x1), PY(bottom + head),
                         seen_layer, LW_SEEN)
                seen_handles.append(h)
                space.track(PX(x0), PY(bottom + sill), PX(x1), PY(bottom + head),
                           what=f"{tipo} {nombre}")

            else:  # seen_wall
                x0, x1 = float(el["x_start"]), float(el["x_end"])
                h = _rect(PX(x0), PY(bottom), PX(x1), PY(wall_top), seen_layer, LW_SEEN)
                seen_handles.append(h)
                space.track(PX(x0), PY(bottom), PX(x1), PY(wall_top),
                           what=f"visto {nombre}")

        story_handles.append({
            "story": nombre, "slabHandle": slab_handle,
            "cutWallHandles": cut_handles, "seenHandles": seen_handles,
        })

    # --- Rótulos de nivel, del lado OPUESTO a la cadena de cotas. ---
    niveles: list[dict[str, Any]] = []
    for i, elev in enumerate(levels):
        if i == 0:
            nombre = str(stories[0].get("name", "N1"))
        elif i == len(levels) - 1:
            nombre = "REMATE"
        else:
            nombre = str(stories[i].get("name", f"N{i + 1}"))
        niveles.append({"name": nombre, "elevation": round(datum + elev, 4),
                        "y": PY(elev)})
        if level_labels:
            texto = _fmt_level(datum + elev)
            gap = th * 0.6
            if dimension_side == "left":
                tx = PX(length) + gap
            else:
                tx = PX(0) - gap - _w(texto, th)
            _text(texto, tx, PY(elev) + th * 0.2, th, seen_layer)

    story_dims = None
    if dimension_stories:
        story_dims = ann_mod.create_dimension_chain(
            positions=[PY(l) for l in levels],
            side=dimension_side,
            reference=PX(0) if dimension_side == "left" else PX(length),
        )

    resultado: dict[str, Any] = {
        "levels": niveles,
        "storyHandles": story_handles,
        "storyDimensions": story_dims,
        "totalHeight": round(levels[-1], 4),
    }
    if warnings:
        resultado["warning"] = "; ".join(warnings)
    return resultado
