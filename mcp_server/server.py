"""Servidor MCP que expone AutoCAD (vía el plugin .NET) como tools para Claude.

Corre por stdio: Claude Code / Claude Desktop lo lanza como subproceso.
Cada tool traduce a un comando JSON que viaja por TCP hasta el plugin
cargado dentro de AutoCAD (ver autocad_client.py).
"""
from __future__ import annotations

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

import arch as arch_mod
import autocad_client as acad
import sheet as sheet_mod

mcp = FastMCP("autocad")


def _style(lineweight: Optional[int], color_index: Optional[int]) -> dict[str, Any]:
    """Propiedades de trazo comunes a toda entidad que se crea.

    lineweight va en centésimas de mm (30 = 0.30mm) y pisa el grosor de la capa
    para esa entidad; None deja ByLayer. Valores válidos de AutoCAD: 0,5,9,13,
    15,18,20,25,30,35,40,50,53,60,70,80,90,100,106,120,140,158,200,211.
    """
    return {"lineweight": lineweight, "colorIndex": color_index}


# ------------------------------------------------- Lámina (cajón + rotulación)

@mcp.tool()
def create_sheet(
    sheet_format: str = "A1",
    scale_denominator: float = 100.0,
    model_units: str = "m",
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    project: str = "",
    location: str = "",
    client: str = "",
    content: str = "",
    drawn_by: str = "",
    reviewed_by: str = "",
    date: str = "",
    sheet_number: str = "",
    width_mm: float = 0.0,
    height_mm: float = 0.0,
) -> dict[str, Any]:
    """PRIMER PASO DE TODO PLANO: dibuja el cajón (marco de la hoja con sus
    márgenes) y el cuadro de rotulación con los datos de la obra, y devuelve el
    área útil donde va el dibujo. Llamala ANTES que cualquier otra tool de
    dibujo, y después ubicá todo adentro del 'drawArea' que devuelve.

    sheet_format: A0, A1, A2, A3 o A4 (apaisado). Para un formato a medida pasá
    width_mm y height_mm.
    scale_denominator: el denominador de la escala — 100 para 1:100, 50 para
    1:50. Decide qué tan grande sale el cajón en unidades del modelo.
    model_units: en qué unidad está dibujado el modelo, 'm' (lo normal en
    arquitectura), 'cm' o 'mm' (detalle/despiece). Un A1 a 1:100 en metros mide
    84.1 x 59.4 unidades; el mismo A1 a 1:100 en mm mide 84100 x 59400.
    origin_x/origin_y: esquina inferior izquierda de la hoja. Usá orígenes
    separados para poner varias láminas una al lado de la otra.

    Datos del rótulo: project (nombre de la obra), location (ubicación), client
    (propietario), content (qué muestra esta lámina, p.ej. 'PLANTA BAJA'),
    drawn_by (dibujó), reviewed_by (revisó), date (fecha), sheet_number
    (clave/número de lámina, p.ej. 'A-01'). Los que se dejen vacíos salen como
    celda en blanco para llenar a mano.

    Devuelve 'drawArea' con dos rectángulos: el conservador (x1,y1,x2,y2), que
    es la franja arriba del rótulo, y el completo (full_*), que además usa la
    banda a la izquierda del rótulo. Dibujá siempre dentro de alguno de los dos.
    """
    return sheet_mod.create_sheet(
        sheet_format=sheet_format,
        scale_denominator=scale_denominator,
        model_units=model_units,
        origin_x=origin_x,
        origin_y=origin_y,
        project=project,
        location=location,
        client=client,
        content=content,
        drawn_by=drawn_by,
        reviewed_by=reviewed_by,
        date=date,
        sheet_number=sheet_number,
        width_mm=width_mm or None,
        height_mm=height_mm or None,
    )


# ------------------------------------------------------- Arquitectura

@mcp.tool()
def create_walls(
    points: list[list[float]],
    thickness: float = 0.15,
    closed: bool = False,
    openings: Optional[list[dict[str, Any]]] = None,
    layer: str = "MUROS",
    lineweight: int = 50,
) -> dict[str, Any]:
    """Muros con ESPESOR REAL (doble línea) a lo largo de un eje, con los huecos
    de puertas y ventanas ya recortados. Es la tool para dibujar muros — no uses
    create_line, que da una línea sola sin espesor.

    points: el eje por donde pasa el CENTRO del muro, [[x,y], ...]. Las esquinas
    se resuelven a inglete, así que dos tramos que se cruzan cierran limpio.
    thickness: espesor en unidades del modelo (dibujando en metros, un muro de
    15cm es 0.15; un muro de tabique de 28cm, 0.28).
    closed: True para un perímetro cerrado (el último punto se une con el primero).
    layer / lineweight: los muros cortados son el trazo más grueso del plano
    después del cajón; 50 es lo normal.

    openings: lista de huecos, cada uno un dict:
      {"distance": 1.2, "width": 0.9, "type": "door", "swing": "left", "side": "left"}
      - distance: a qué distancia del ARRANQUE del eje está el CENTRO del hueco,
        medida a lo largo del muro (si el muro dobla, la distancia sigue la
        vuelta). Poné "centered": false para que sea el borde en vez del centro.
      - width: ancho del hueco (puerta de 0.90, ventana de 1.50...).
      - type: "door" dibuja hoja + arco de abatimiento; "window" dibuja el
        vidrio; "pass" deja el vano limpio sin símbolo.
      - swing: de qué jamba cuelga la puerta, "left" (la del arranque) o "right".
      - side: hacia qué lado abre, "left" o "right" respecto del sentido del eje.

    Devuelve los handles de cada tramo de muro y de cada símbolo. Si un hueco se
    sale del muro o dos huecos se pisan, tira un error explicando el problema en
    vez de dibujar algo roto."""
    return arch_mod.create_walls(
        points=points, thickness=thickness, closed=closed,
        openings=openings, layer=layer, lineweight=lineweight,
    )


@mcp.tool()
def create_axis_grid(
    x_positions: Optional[list[float]] = None,
    y_positions: Optional[list[float]] = None,
    x_min: float = 0.0, y_min: float = 0.0,
    x_max: float = 0.0, y_max: float = 0.0,
    extension: float = 0.0,
    bubble_radius: float = 0.0,
    text_height: float = 0.0,
    layer: str = "EJES",
) -> dict[str, Any]:
    """Ejes estructurales con sus globos: los verticales numerados 1, 2, 3... y
    los horizontales con letras A, B, C..., en línea de eje y trazo.

    x_positions: coordenadas X de los ejes verticales. y_positions: coordenadas
    Y de los horizontales. Se dibujan pasados del dibujo, con globo en los dos
    extremos.
    x_min/x_max/y_min/y_max: extensión del dibujo, si querés que los ejes lleguen
    más allá de lo que abarcan los propios ejes.
    extension, bubble_radius, text_height: en unidades del modelo. Si los dejás
    en 0 se calculan proporcionales al tamaño de la grilla, que suele estar bien.

    Llamala DESPUÉS de create_walls, con las coordenadas de los ejes de los
    muros portantes."""
    return arch_mod.create_axis_grid(
        x_positions=x_positions, y_positions=y_positions,
        x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max,
        extension=extension, bubble_radius=bubble_radius,
        text_height=text_height, layer=layer,
    )


# ---------------------------------------------------------------- Geometría

@mcp.tool()
def create_line(
    x1: float, y1: float, x2: float, y2: float,
    z1: float = 0.0, z2: float = 0.0, layer: Optional[str] = None,
    lineweight: Optional[int] = None, color_index: Optional[int] = None,
) -> dict[str, Any]:
    """Crea una línea en el espacio modelo activo entre dos puntos 3D.

    lineweight: grosor SOLO de esta línea, en centésimas de mm (50 = 0.50mm);
    si se omite hereda el de la capa. Para muros/cortes conviene 50-70, para
    ejes y auxiliares 13-18. color_index: color ACI 1-255 solo de esta línea."""
    return acad.call("create_line", {
        "x1": x1, "y1": y1, "z1": z1, "x2": x2, "y2": y2, "z2": z2, "layer": layer,
        **_style(lineweight, color_index),
    })


@mcp.tool()
def create_polyline(
    points: list[list[float]], closed: bool = False, layer: Optional[str] = None,
    lineweight: Optional[int] = None, color_index: Optional[int] = None,
) -> dict[str, Any]:
    """Crea una polilínea 2D a partir de una lista de puntos [[x, y], ...].

    lineweight: grosor SOLO de esta polilínea, en centésimas de mm (50 = 0.50mm);
    si se omite hereda el de la capa. color_index: color ACI 1-255."""
    return acad.call("create_polyline", {
        "points": points, "closed": closed, "layer": layer,
        **_style(lineweight, color_index),
    })


@mcp.tool()
def create_circle(
    x: float, y: float, radius: float, z: float = 0.0, layer: Optional[str] = None,
    lineweight: Optional[int] = None, color_index: Optional[int] = None,
) -> dict[str, Any]:
    """Crea un círculo dado su centro y radio.

    lineweight: grosor SOLO de este círculo, en centésimas de mm; si se omite
    hereda el de la capa. color_index: color ACI 1-255."""
    return acad.call("create_circle", {
        "x": x, "y": y, "z": z, "radius": radius, "layer": layer,
        **_style(lineweight, color_index),
    })


@mcp.tool()
def create_arc(
    x: float, y: float, radius: float, start_angle_deg: float, end_angle_deg: float,
    z: float = 0.0, layer: Optional[str] = None,
    lineweight: Optional[int] = None, color_index: Optional[int] = None,
) -> dict[str, Any]:
    """Crea un arco (centro, radio, ángulo inicial/final en grados, sentido antihorario).

    lineweight: grosor SOLO de este arco, en centésimas de mm; si se omite
    hereda el de la capa. color_index: color ACI 1-255."""
    return acad.call("create_arc", {
        "x": x, "y": y, "z": z, "radius": radius,
        "startAngleDeg": start_angle_deg, "endAngleDeg": end_angle_deg, "layer": layer,
        **_style(lineweight, color_index),
    })


# ------------------------------------------------------------------ Textos

@mcp.tool()
def create_text(
    text: str, x: float, y: float, height: float, z: float = 0.0,
    layer: Optional[str] = None, rotation_deg: float = 0.0,
    lineweight: Optional[int] = None, color_index: Optional[int] = None,
) -> dict[str, Any]:
    """Crea texto de una línea (DBText).

    lineweight: grosor del trazo del texto en centésimas de mm (los títulos
    suelen ir 35-50 para que "pesen" frente al cuerpo); si se omite hereda el
    de la capa. color_index: color ACI 1-255."""
    return acad.call("create_text", {
        "text": text, "x": x, "y": y, "z": z, "height": height,
        "layer": layer, "rotationDeg": rotation_deg,
        **_style(lineweight, color_index),
    })


@mcp.tool()
def create_mtext(
    text: str, x: float, y: float, height: float, width: float = 0.0,
    z: float = 0.0, layer: Optional[str] = None,
    lineweight: Optional[int] = None, color_index: Optional[int] = None,
) -> dict[str, Any]:
    """Crea texto multilínea (MText) que ajusta dentro de un ancho dado.

    lineweight: grosor del trazo del texto en centésimas de mm; si se omite
    hereda el de la capa. color_index: color ACI 1-255."""
    return acad.call("create_mtext", {
        "text": text, "x": x, "y": y, "z": z, "height": height, "width": width,
        "layer": layer, **_style(lineweight, color_index),
    })


@mcp.tool()
def create_dimension(
    x1: float, y1: float, x2: float, y2: float,
    dim_line_x: float, dim_line_y: float,
    layer: Optional[str] = None, scale: float = 1.0,
    lineweight: Optional[int] = None, color_index: Optional[int] = None,
) -> dict[str, Any]:
    """Crea una cota alineada entre dos puntos. dim_line_x/y ubica la línea de cota
    (define a qué distancia y de qué lado se dibuja). 'scale' multiplica el
    tamaño de texto/flechas del estilo activo — el estilo por defecto está
    calibrado para dibujos en milímetros; en zonas dibujadas a otra unidad
    (p.ej. 1 unidad = 1 metro) bajalo (p.ej. 0.05) para que el texto no salga
    gigante.

    lineweight: grosor de las líneas de cota en centésimas de mm (las cotas van
    finas, 13-18, para no competir con los muros). color_index: color ACI."""
    return acad.call("create_dimension", {
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "dimLineX": dim_line_x, "dimLineY": dim_line_y, "layer": layer, "scale": scale,
        **_style(lineweight, color_index),
    })


@mcp.tool()
def create_leader(
    points: list[list[float]], text: str, text_height: float = 2.5,
    layer: Optional[str] = None,
    lineweight: Optional[int] = None, color_index: Optional[int] = None,
) -> dict[str, Any]:
    """Crea una línea de referencia con flecha + texto (callout), típica para
    señalar un detalle. 'points' es la polilínea de la flecha (al menos 2 puntos);
    el texto arranca en el último punto.

    lineweight: grosor de la flecha y el texto en centésimas de mm (13-18 es lo
    habitual). color_index: color ACI 1-255."""
    return acad.call("create_leader", {
        "points": points, "text": text, "textHeight": text_height, "layer": layer,
        **_style(lineweight, color_index),
    })


@mcp.tool()
def create_hatch(
    boundary_handle: str, pattern: str = "SOLID", scale: float = 1.0,
    angle_deg: float = 0.0, layer: Optional[str] = None,
    lineweight: Optional[int] = None, color_index: Optional[int] = None,
) -> dict[str, Any]:
    """Rellena una entidad cerrada (Polyline cerrada o Circle, identificada por su
    handle) con un patrón de achurado. 'SOLID' para relleno sólido (p.ej. los
    cuadraditos de una leyenda); nombres de acad.pat como 'ANSI31' o 'AR-CONC'
    para simbología de materiales en un corte.

    lineweight: grosor de las líneas del patrón en centésimas de mm (los rellenos
    van finos, 5-13, para que no tapen el dibujo). color_index: color ACI."""
    return acad.call("create_hatch", {
        "boundaryHandle": boundary_handle, "pattern": pattern,
        "scale": scale, "angleDeg": angle_deg, "layer": layer,
        **_style(lineweight, color_index),
    })


# ---------------------------------------------------------- Bloques/símbolos

@mcp.tool()
def insert_block(name: str, x: float, y: float, z: float = 0.0, scale: float = 1.0,
                  rotation_deg: float = 0.0, layer: Optional[str] = None,
                  path: Optional[str] = None,
                  attributes: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Inserta un bloque (símbolo: puerta, ventana, columna, etc.) en un punto.

    Si el bloque todavía no existe en el dibujo, pasá 'path' con la ruta a un
    .dwg que lo defina — se importa una sola vez y queda disponible para
    próximas inserciones. 'attributes' setea atributos por tag si el bloque los tiene.
    """
    return acad.call("insert_block", {
        "name": name, "x": x, "y": y, "z": z, "scale": scale,
        "rotationDeg": rotation_deg, "layer": layer, "path": path, "attributes": attributes,
    })


@mcp.tool()
def define_block(name: str, handles: list[str], base_point_x: float, base_point_y: float,
                  base_point_z: float = 0.0) -> dict[str, Any]:
    """Convierte entidades ya dibujadas (por handle, de create_line/create_circle/etc.)
    en un bloque reutilizable — sin necesitar ningún archivo externo. Las entidades
    sueltas se borran del dibujo y quedan 'adentro' del bloque nuevo. Sirve para
    armar un símbolo con primitivos una sola vez (p.ej. una flecha de norte) y
    después insertarlo muchas veces con insert_block(name=...)."""
    return acad.call("define_block", {
        "name": name, "handles": handles,
        "basePointX": base_point_x, "basePointY": base_point_y, "basePointZ": base_point_z,
    })


@mcp.tool()
def attach_image(path: str, x: float, y: float, width: float,
                  height: Optional[float] = None, layer: Optional[str] = None) -> dict[str, Any]:
    """Inserta una imagen raster (logo, mapa de microlocalización, foto, etc.)
    desde un archivo QUE YA EXISTE en disco — esta tool no genera ni inventa
    el contenido de la imagen, solo la coloca en el dibujo. 'path' debe ser una
    ruta local válida (PNG/JPG/etc.); si falta 'height' respeta la proporción
    real del archivo."""
    return acad.call("attach_image", {
        "path": path, "x": x, "y": y, "width": width, "height": height, "layer": layer,
    })


# --------------------------------------------------- Capas (simbología/normas)

@mcp.tool()
def set_layer(name: str, color_index: Optional[int] = None, linetype: Optional[str] = None,
              lineweight_hundredths_mm: Optional[int] = None) -> dict[str, Any]:
    """Crea (si no existe) y configura una capa: color ACI (1-255), tipo de línea
    (se carga de acad.lin si hace falta) y grosor en centésimas de mm
    (valores válidos: 0,5,9,13,15,18,20,25,30,35,40,50,53,60,70,80,90,100,106,
    120,140,158,200,211 — p.ej. 30 = 0.30mm).

    Para que los grosores se VEAN en pantalla hace falta LWDISPLAY activado: el
    plugin lo prende solo al cargarse y al abrir cada dibujo, y se puede forzar
    con set_display_options(lineweight_display=True)."""
    return acad.call("set_layer", {
        "name": name, "colorIndex": color_index, "linetype": linetype,
        "lineweightHundredthsMm": lineweight_hundredths_mm,
    })


@mcp.tool()
def list_layers() -> dict[str, Any]:
    """Lista las capas del dibujo con su color, tipo de línea y estado."""
    return acad.call("list_layers", {})


# --------------------------------------------------------------- Edición

@mcp.tool()
def move_entity(handle: str, dx: float, dy: float, dz: float = 0.0) -> dict[str, Any]:
    """Mueve una entidad existente por su handle."""
    return acad.call("move_entity", {"handle": handle, "dx": dx, "dy": dy, "dz": dz})


@mcp.tool()
def copy_entity(handle: str, dx: float, dy: float, dz: float = 0.0) -> dict[str, Any]:
    """Copia una entidad existente desplazada dx/dy/dz. Devuelve el handle de la copia."""
    return acad.call("copy_entity", {"handle": handle, "dx": dx, "dy": dy, "dz": dz})


@mcp.tool()
def rotate_entity(handle: str, base_x: float, base_y: float, angle_deg: float) -> dict[str, Any]:
    """Rota una entidad alrededor de un punto base, en grados (antihorario)."""
    return acad.call("rotate_entity", {
        "handle": handle, "baseX": base_x, "baseY": base_y, "angleDeg": angle_deg,
    })


@mcp.tool()
def scale_entity(handle: str, base_x: float, base_y: float, factor: float) -> dict[str, Any]:
    """Escala una entidad respecto de un punto base."""
    return acad.call("scale_entity", {
        "handle": handle, "baseX": base_x, "baseY": base_y, "factor": factor,
    })


@mcp.tool()
def delete_entity(handle: str) -> dict[str, Any]:
    """Borra una entidad por su handle."""
    return acad.call("delete_entity", {"handle": handle})


@mcp.tool()
def offset_entity(handle: str, distance: float,
                   side_x: Optional[float] = None, side_y: Optional[float] = None) -> dict[str, Any]:
    """Crea una curva paralela a otra (Line, Arc, Circle o Polyline) a una
    distancia dada — típico para trazar una guarnición paralela al eje de una
    calle. side_x/side_y es un punto de referencia opcional para elegir de qué
    lado queda el offset cuando hay ambigüedad."""
    return acad.call("offset_entity", {
        "handle": handle, "distance": distance, "sideX": side_x, "sideY": side_y,
    })


# --------------------------------------------------------------- Consulta

@mcp.tool()
def list_entities(entity_type: Optional[str] = None, limit: int = 200) -> dict[str, Any]:
    """Lista entidades del espacio modelo activo (handle, tipo, capa).
    entity_type: filtro opcional por tipo exacto (p.ej. 'Line', 'Polyline', 'Circle')."""
    return acad.call("list_entities", {"type": entity_type, "limit": limit})


@mcp.tool()
def get_entity(handle: str) -> dict[str, Any]:
    """Devuelve las propiedades completas de una entidad (geometría, capa, color,
    texto/atributos si aplica) a partir de su handle."""
    return acad.call("get_entity", {"handle": handle})


@mcp.tool()
def calculate_area(handle: str) -> dict[str, Any]:
    """Calcula el área de una entidad cerrada (Polyline cerrada, Region o Circle)."""
    return acad.call("calculate_area", {"handle": handle})


@mcp.tool()
def get_drawing_info() -> dict[str, Any]:
    """Info general del dibujo activo: nombre de archivo, unidades, capa actual,
    cantidad de entidades en el espacio modelo."""
    return acad.call("get_drawing_info", {})


# ------------------------------------------------------- Vista / visualización

@mcp.tool()
def set_display_options(lineweight_display: Optional[bool] = None,
                         default_lineweight_hundredths_mm: Optional[int] = None) -> dict[str, Any]:
    """Controla si los grosores de línea se VEN en pantalla (LWDISPLAY) y cuál es
    el grosor por defecto del dibujo (LWDEFAULT, en centésimas de mm).

    Es la causa #1 de que un plano se vea "todo con trazos finos": AutoCAD trae
    LWDISPLAY apagado de fábrica y la variable se guarda por dibujo, así que un
    DWG viejo la puede traer apagada aunque el plugin la prenda al cargarse.
    Regenera la vista al terminar."""
    return acad.call("set_display_options", {
        "lineweightDisplay": lineweight_display,
        "defaultLineweightHundredthsMm": default_lineweight_hundredths_mm,
    })


@mcp.tool()
def zoom_extents() -> dict[str, Any]:
    """Hace zoom a la extensión completa del dibujo activo."""
    return acad.call("zoom_extents", {})


if __name__ == "__main__":
    mcp.run()
