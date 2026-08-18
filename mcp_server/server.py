"""Servidor MCP que expone AutoCAD (vía el plugin .NET) como tools para Claude.

Corre por stdio: Claude Code / Claude Desktop lo lanza como subproceso.
Cada tool traduce a un comando JSON que viaja por TCP hasta el plugin
cargado dentro de AutoCAD (ver autocad_client.py).
"""
from __future__ import annotations

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

import autocad_client as acad

mcp = FastMCP("autocad")


def _style(lineweight: Optional[int], color_index: Optional[int]) -> dict[str, Any]:
    """Propiedades de trazo comunes a toda entidad que se crea.

    lineweight va en centésimas de mm (30 = 0.30mm) y pisa el grosor de la capa
    para esa entidad; None deja ByLayer. Valores válidos de AutoCAD: 0,5,9,13,
    15,18,20,25,30,35,40,50,53,60,70,80,90,100,106,120,140,158,200,211.
    """
    return {"lineweight": lineweight, "colorIndex": color_index}


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
