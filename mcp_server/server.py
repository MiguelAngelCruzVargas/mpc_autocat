"""Servidor MCP que expone AutoCAD (vía el plugin .NET) como tools para Claude.

Corre por stdio: Claude Code / Claude Desktop lo lanza como subproceso.
Cada tool traduce a un comando JSON que viaja por TCP hasta el plugin
cargado dentro de AutoCAD (ver autocad_client.py).
"""
from __future__ import annotations

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

import annotation as ann_mod
import arch as arch_mod
import autocad_client as acad
import civil as civil_mod
import profile as profile_mod
import furniture as fur_mod
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


@mcp.tool()
def place_furniture(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Dibuja mobiliario en planta: varias piezas en UNA sola llamada.

    items: lista de {"type": ..., "x": ..., "y": ..., "rotation_deg": 0, ...}.
    (x, y) es la esquina inferior izquierda de la pieza antes de rotar, salvo
    dining_table que se ubica por su centro. rotation_deg gira alrededor de ese
    punto, para apoyar el mueble contra cualquier muro (180 = cabecera arriba).

    Tipos y sus medidas propias (todas opcionales, en unidades del modelo):
      bed / single_bed  width, length      cama matrimonial / individual
      nightstand        size               buró
      closet            width, depth       clóset con puertas corredizas
      sofa              width, depth       sillón
      armchair          size               sillón individual
      coffee_table      width, depth       mesa de centro
      dining_table      width, depth, seats_per_side   comedor con sillas
      counter           width, depth       mesada de cocina
      stove             width, depth       estufa con quemadores
      kitchen_sink      width, depth       fregadero
      fridge            width, depth       refrigerador
      wc                -                  inodoro
      lavatory          width, depth       lavabo
      shower            width, depth       regadera

    Todo va a la capa MOBILIARIO con trazo fino, para poder apagarla y quedarse
    con la arquitectura sola. Cada pieza registra su huella, así que llamar
    después a label_rooms ubica los textos sin taparlos."""
    return fur_mod.place(items)


@mcp.tool()
def label_rooms(rooms: list[dict[str, Any]], height: float,
                 area_height: float = 0.0, show_area: bool = True,
                 layer: str = "TEXTOS") -> dict[str, Any]:
    """Rotula ambientes con su nombre y superficie, ESQUIVANDO el mobiliario.

    rooms: lista de {"name": "SALA", "x0":..., "y0":..., "x1":..., "y1":...},
    donde el rectángulo son los bordes útiles del ambiente (cara interior de
    los muros). El área se calcula sola a partir de esas medidas.

    Busca dentro de cada ambiente la posición con más aire alrededor en vez de
    poner el texto en el centro geométrico, que suele ser justo donde está la
    cama. Llamala DESPUÉS de place_furniture. Si a un ambiente no le entra el
    bloque completo, cae a solo el nombre en chico y lo marca como 'cramped'.

    height: altura del nombre en unidades del modelo — en un plano 1:50 en
    metros, un texto de 3mm de papel es 0.15."""
    return fur_mod.label_rooms(rooms, height=height, area_height=area_height,
                               layer=layer, show_area=show_area)


# --------------------------------------------------- Obra civil (calles)

@mcp.tool()
def create_road(points: list[list[float]], width: float = 7.00,
                 widths: Optional[list[list[float]]] = None,
                 bulges: Optional[list[float]] = None,
                 curb_width: float = 0.40,
                 curb_segments: Optional[list[dict[str, Any]]] = None,
                 sidewalk_width: float = 0.0,
                 closed: bool = False, draw_axis: bool = True,
                 pavement_pattern: Optional[str] = None,
                 pavement_scale: float = 1.0) -> dict[str, Any]:
    """Calle en planta desde su eje: calzada, guarniciones y banquetas.

    Es la tool para trazar una vialidad — no dibujes las paralelas a mano, que
    en curva no cierran. Usa el mismo offset con inglete que los muros.

    points: el eje por donde pasa el CENTRO de la calzada. Para una calle curva
    lo correcto es sacarlo de create_alignment y pasar también sus 'bulges', en
    vez de aproximar la curva con muchos puntos.
    bulges: un valor por vértice (de create_alignment). Con bulges el eje se
    dibuja con arcos reales y el largo es el verdadero, no el de la poligonal.
    width: ancho de calzada constante (7.00 es lo típico en calle urbana).
    widths: para calle que se angosta, [[distancia, ancho], ...] medido a lo
    largo del eje — p.ej. [[0, 7.0], [100, 4.5], [147, 4.0]] interpola entre
    esos puntos. Si lo pasás, ignora 'width' y el área se integra de verdad en
    vez de multiplicar largo por ancho.
    curb_width: ancho de la guarnición a cada lado, por fuera de la calzada.
    curb_segments: qué tramo lleva guarnición y de qué lado, cuando no va
    completa de los dos — lo normal si de un lado hay un predio, un talud o una
    obra existente:
      [{"side": "left"}, {"side": "right", "from": 0, "to": 105}]
    'side' es 'left', 'right' o 'both'; 'from'/'to' son cadenamientos sobre el
    eje y por defecto abarcan todo. Sin esto los metros lineales del resumen
    salen siempre 2 x largo, que casi nunca es lo que se construye.
    sidewalk_width: banqueta por fuera de la guarnición; 0 la omite.
    pavement_pattern: rayado de la calzada, p.ej. 'AR-CONC' para concreto
    hidráulico. Sin patrón queda solo el contorno.

    Devuelve el largo del eje y las cantidades de obra ya calculadas:
    pavementArea (m2), curbLength (ml de guarnición, contando los dos lados) y
    sidewalkArea — que es lo que va al resumen de obra."""
    return civil_mod.create_road(
        points=points, width=width, widths=widths, bulges=bulges,
        curb_width=curb_width, curb_segments=curb_segments,
        sidewalk_width=sidewalk_width, closed=closed, draw_axis=draw_axis,
        pavement_pattern=pavement_pattern, pavement_scale=pavement_scale)


@mcp.tool()
def create_alignment(start_x: float, start_y: float, start_bearing_deg: float,
                      elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Eje definido como se PROYECTA una vialidad: tangentes y curvas de radio.

    No hace falta saber las coordenadas de los vértices. Se describe el
    recorrido y el alineamiento calcula la geometría exacta, con arcos reales
    (bulges), no una poligonal aproximada a ojo.

    start_bearing_deg: rumbo inicial en grados matemáticos (0 = hacia +X,
    90 = hacia +Y, -90 = hacia abajo), antihorario.
    elements, en orden:
      {"type": "tangent", "length": 40}
      {"type": "curve", "radius": 90, "length": 107, "direction": "left"}
      {"type": "curve", "radius": 90, "angle_deg": 68, "direction": "right"}
      {"type": "spiral", "radius": 90, "length": 30, "direction": "left"}
      {"type": "spiral", "radius": 90, "length": 30, "direction": "left",
       "exit": True}

    Una 'spiral' es una curva de transición (clotoide): el radio baja de forma
    gradual de infinito hasta 'radius' a lo largo de 'length'. Es lo que
    permite entrar a una curva girando el volante de a poco; se pone una a la
    entrada y otra con exit=True a la salida. Devuelve su parámetro A.

    Devuelve 'points' y 'bulges' para pasarle a create_road o create_polyline,
    el largo total, y el cadenamiento de cada punto notable con el radio, el
    desarrollo, la tangente y la cuerda de cada curva — que es lo que se
    replantea en obra."""
    return civil_mod.create_alignment(
        start_x=start_x, start_y=start_y,
        start_bearing_deg=start_bearing_deg, elements=elements)


@mcp.tool()
def point_on_road(points: list[list[float]], distance: float,
                   offset: float = 0.0, closed: bool = False) -> dict[str, Any]:
    """Dónde cae un punto ubicado por cadenamiento sobre un eje.

    distance: metros desde el arranque del eje, siguiendo las curvas.
    offset: desplazamiento perpendicular (+ es a la izquierda del sentido de
    avance). Con offset=3.5 caés justo en la guarnición de una calle de 7 m.

    Sirve para ubicar un poste, un registro, el arranque de un ramal o una cota
    sin recalcular la geometría de la curva."""
    return civil_mod.point_on_road(points=points, distance=distance,
                                   offset=offset, closed=closed)


@mcp.tool()
def create_intersection(main_points: list[list[float]],
                         branch_points: list[list[float]],
                         main_width: float, branch_width: float,
                         radius: float = 6.0,
                         main_bulges: Optional[list[float]] = None,
                         branch_bulges: Optional[list[float]] = None
                         ) -> dict[str, Any]:
    """Radios de acuerdo donde una calle nace de otra.

    Dos calles trazadas por separado se cruzan y sus guarniciones quedan
    chocando en escuadra — ni se construye así ni podría girar un vehículo. El
    acuerdo es el arco que empalma el borde de una con el de la otra.

    branch_points tiene que ARRANCAR en el punto donde el ramal nace de la
    principal. radius: 6 m en calle urbana, 10 o más si entran camiones.

    Devuelve el desarrollo de los arcos, que se suma a los metros lineales de
    guarnición del resumen de obra."""
    return civil_mod.create_intersection(
        main_points=main_points, branch_points=branch_points,
        main_width=main_width, branch_width=branch_width, radius=radius,
        main_bulges=main_bulges, branch_bulges=branch_bulges)


# ------------------------------------------- Perfil y secciones transversales

@mcp.tool()
def create_profile(x: float, y: float, length: float,
                    pvis: list[dict[str, Any]],
                    ground: Optional[list[list[float]]] = None,
                    h_scale: float = 1.0, v_exag: float = 10.0,
                    datum: Optional[float] = None,
                    grid_station: float = 20.0, grid_elevation: float = 1.0,
                    text_height: float = 0.5, step: float = 2.0
                    ) -> dict[str, Any]:
    """Perfil longitudinal: terreno natural, rasante de proyecto y grilla.

    La planta dice por dónde va la obra; el perfil dice a qué altura. Sin él no
    hay cotas de rasante ni volúmenes de corte y terraplén.

    (x, y) es la esquina inferior izquierda del cuadro.
    pvis: los puntos de inflexión vertical, o sea la rasante:
      [{"station": 0, "elevation": 100.0},
       {"station": 60, "elevation": 103.2, "curve_length": 30},
       {"station": 147, "elevation": 101.0}]
    Entre dos PVI la rasante es recta; con 'curve_length' se mete una curva
    vertical parabólica que suaviza el cambio de pendiente.
    ground: terreno natural [[estacion, cota], ...]; opcional.
    v_exag: exageración vertical (10 = 10:1). Sin exagerar, una pendiente del
    2% es invisible en el dibujo.

    Devuelve la cota de rasante y de terreno en cada estación de la grilla, y
    el desnivel entre ambas — de ahí salen los volúmenes."""
    return profile_mod.create_profile(
        x=x, y=y, length=length, pvis=pvis, ground=ground, h_scale=h_scale,
        v_exag=v_exag, datum=datum, grid_station=grid_station,
        grid_elevation=grid_elevation, text_height=text_height, step=step)


@mcp.tool()
def grade_elevation(pvis: list[dict[str, Any]], station: float) -> dict[str, Any]:
    """Cota de la rasante en un cadenamiento, con las curvas verticales.

    Sirve para ubicar cualquier cosa a la altura correcta —un registro, un
    brocal, el arranque de una obra de drenaje— sin dibujar el perfil entero."""
    return {"station": station,
            "elevation": profile_mod.grade_elevation(pvis, station)}


@mcp.tool()
def create_cross_sections(x: float, y: float, stations: list[float],
                           width: float, pvis: list[dict[str, Any]],
                           ground: Optional[list[list[float]]] = None,
                           columns: int = 3, spacing_x: float = 0.0,
                           spacing_y: float = 0.0, crown: float = 0.02,
                           side_slope: float = 1.5, depth: float = 0.33,
                           scale: float = 1.0, text_height: float = 0.3
                           ) -> dict[str, Any]:
    """Secciones transversales en una tanda de cadenamientos, en cuadrícula.

    Cada sección sale con su calzada, el bombeo, el paquete estructural y los
    taludes, y con el corte o terraplén ya resuelto a partir de la rasante
    (pvis) y el terreno (ground).

    crown: bombeo, la pendiente transversal que saca el agua al borde (0.02 =
    2%, lo normal). side_slope: talud expresado H:V (1.5 = 1.5 horizontal por
    1 vertical). depth: espesor del paquete estructural.

    Devuelve el volumen estimado por el método de las áreas medias, que es con
    el que se cuantifica el movimiento de tierras."""
    return profile_mod.create_cross_section_series(
        x=x, y=y, stations=stations, width=width, pvis=pvis, ground=ground,
        columns=columns, spacing_x=spacing_x, spacing_y=spacing_y, crown=crown,
        side_slope=side_slope, depth=depth, scale=scale,
        text_height=text_height)


# ------------------------------------------- Documentación (obra lineal, etc.)

@mcp.tool()
def create_table(x: float, y: float, rows: list[list[str]],
                  col_widths: list[float], row_height: float,
                  text_height: float, title: str = "",
                  header: bool = True, layer: str = "TABLAS") -> dict[str, Any]:
    """Tabla con grilla y texto: resumen de obra, cuadro de acabados,
    cuantificación, cuadro de construcción.

    (x, y) es la esquina SUPERIOR izquierda; la tabla crece hacia abajo.
    rows: las filas, con las celdas ya como texto. Con header=True la primera
    fila va centrada y separada por una línea más gruesa.
    col_widths: ancho de cada columna en unidades del modelo — define cuántas
    columnas tiene la tabla.
    row_height / text_height: en unidades del modelo. A 1:50 en metros, un
    texto de 2.5mm de papel es 0.125 y una fila cómoda es 0.35.

    Devuelve 'bottom' y 'right' para poder encadenar otra cosa debajo o al lado."""
    return ann_mod.create_table(x=x, y=y, rows=rows, col_widths=col_widths,
                                row_height=row_height, text_height=text_height,
                                title=title, header=header, layer=layer)


@mcp.tool()
def create_legend(x: float, y: float, items: list[dict[str, Any]],
                   text_height: float, swatch_width: float = 0.0,
                   swatch_height: float = 0.0, row_height: float = 0.0,
                   title: str = "LEYENDA",
                   layer: str = "LEYENDA") -> dict[str, Any]:
    """Leyenda de simbología: una muestra del rayado y su descripción al lado.

    (x, y) es la esquina superior izquierda; crece hacia abajo.
    items: [{"label": "PAVIMENTO DE CONCRETO", "pattern": "AR-CONC",
             "scale": 0.5, "color_index": 8}]
    - pattern: nombre de acad.pat ('SOLID', 'ANSI31', 'AR-CONC'...). Si se
      omite, el cuadro queda solo con contorno, que es lo correcto para
      simbología de línea (ejes, guarniciones).
    - color_index: color ACI del cuadro y su relleno.

    Los cuadros y textos se dimensionan solos a partir de text_height si no
    pasás swatch_width/height/row_height."""
    return ann_mod.create_legend(x=x, y=y, items=items, text_height=text_height,
                                 swatch_width=swatch_width,
                                 swatch_height=swatch_height,
                                 row_height=row_height, title=title, layer=layer)


@mcp.tool()
def create_stationing(points: list[list[float]], interval: float,
                       text_height: float, tick: float = 0.0,
                       start_station: float = 0.0, closed: bool = False,
                       label_every: int = 1, station_format: str = "km",
                       layer: str = "CADENAMIENTO") -> dict[str, Any]:
    """Cadenamiento: marcas cada N metros sobre un eje, rotuladas 0+000.

    Es cómo se referencia una obra lineal (calle, carretera, colector): cada
    marca dice a qué distancia del arranque está. El texto sale paralelo al eje
    y siempre legible, nunca de cabeza.

    points: el MISMO eje que usaste para trazar la calle.
    interval: cada cuánto va una marca (20 m es lo habitual en calle urbana).
    label_every: rotula 1 de cada N marcas, para no saturar cuando el intervalo
    es corto.
    start_station: cadenamiento del punto de arranque, por si el tramo no
    empieza en 0.
    station_format: 'km' rotula 0+020.00 (carretera); 'plain' rotula 20.00, que
    es como se marca una calle corta."""
    return ann_mod.create_stationing(points=points, interval=interval,
                                     text_height=text_height, tick=tick,
                                     start_station=start_station, closed=closed,
                                     label_every=label_every,
                                     station_format=station_format, layer=layer)


@mcp.tool()
def create_layer_section(x: float, y: float, width: float,
                          layers: list[dict[str, Any]], text_height: float,
                          title: str = "", leader_length: float = 0.0,
                          draw_scale: float = 1.0, dimension_side: bool = True,
                          layer: str = "CORTES") -> dict[str, Any]:
    """Corte transversal por capas, con su rayado y el espesor anotado.

    Es el detalle de un pavimento o un firme: carpeta, base hidráulica,
    subbase, terreno natural. Cada capa sale con su patrón y una guía a la
    derecha que dice el nombre y el espesor en centímetros.

    (x, y) es la esquina SUPERIOR izquierda de la primera capa; el corte crece
    hacia abajo en el orden en que pases las capas.
    layers: [{"name": "CARPETA ASFÁLTICA", "thickness": 0.05,
              "pattern": "ANSI31", "scale": 0.3, "color_index": 8}]
    thickness va SIEMPRE en medidas reales de obra (0.15 = 15 cm).
    draw_scale agranda el dibujo sin tocar los rótulos: en una lámina a 1:200
    un firme de 33 cm sería invisible, así que se dibuja con draw_scale=10 y
    los textos igual dicen "e=15 cm". Es la forma de meter un detalle a 1:20 en
    una lámina a 1:200 sin usar viewports.
    dimension_side: acota el espesor de cada capa del lado izquierdo, como en
    un detalle constructivo."""
    return ann_mod.create_layer_section(x=x, y=y, width=width, layers=layers,
                                        text_height=text_height, title=title,
                                        leader_length=leader_length,
                                        draw_scale=draw_scale,
                                        dimension_side=dimension_side, layer=layer)


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
    bulges: Optional[list[float]] = None,
) -> dict[str, Any]:
    """Crea una polilínea 2D a partir de una lista de puntos [[x, y], ...].

    bulges: opcional, UN valor por vértice — la tangente de un cuarto del ángulo
    del arco que va de ese vértice al siguiente; 0 es tramo recto. Es la forma
    de trazar una polilínea con curvas reales (un eje de calle, una curva de
    nivel) en lugar de aproximarla con muchos segmentos rectos. El bulge de un
    arco de 90° es 0.4142 (tan(90/4)); positivo gira antihorario.

    lineweight: grosor SOLO de esta polilínea, en centésimas de mm (50 = 0.50mm);
    si se omite hereda el de la capa. color_index: color ACI 1-255."""
    return acad.call("create_polyline", {
        "points": points, "closed": closed, "layer": layer, "bulges": bulges,
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
    style: Optional[str] = None,
) -> dict[str, Any]:
    """Crea texto de una línea (DBText).

    lineweight: grosor del trazo del texto en centésimas de mm (los títulos
    suelen ir 35-50 para que "pesen" frente al cuerpo); si se omite hereda el
    de la capa. color_index: color ACI 1-255."""
    return acad.call("create_text", {
        "text": text, "x": x, "y": y, "z": z, "height": height,
        "layer": layer, "rotationDeg": rotation_deg, "style": style,
        **_style(lineweight, color_index),
    })


@mcp.tool()
def create_mtext(
    text: str, x: float, y: float, height: float, width: float = 0.0,
    z: float = 0.0, layer: Optional[str] = None,
    lineweight: Optional[int] = None, color_index: Optional[int] = None,
    style: Optional[str] = None,
) -> dict[str, Any]:
    """Crea texto multilínea (MText) que ajusta dentro de un ancho dado.

    lineweight: grosor del trazo del texto en centésimas de mm; si se omite
    hereda el de la capa. color_index: color ACI 1-255."""
    return acad.call("create_mtext", {
        "text": text, "x": x, "y": y, "z": z, "height": height, "width": width,
        "layer": layer, "style": style, **_style(lineweight, color_index),
    })


@mcp.tool()
def create_dimension(
    x1: float, y1: float, x2: float, y2: float,
    dim_line_x: float, dim_line_y: float,
    layer: Optional[str] = None, scale: Optional[float] = None,
    lineweight: Optional[int] = None, color_index: Optional[int] = None,
    style: Optional[str] = None,
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
        "dimLineX": dim_line_x, "dimLineY": dim_line_y, "layer": layer,
        "scale": scale, "style": style,
        **_style(lineweight, color_index),
    })


@mcp.tool()
def create_dimension_rotated(x1: float, y1: float, x2: float, y2: float,
                              dim_line_x: float, dim_line_y: float,
                              angle_deg: float = 0.0,
                              layer: Optional[str] = None,
                              style: Optional[str] = None,
                              scale: Optional[float] = None,
                              text: Optional[str] = None,
                              lineweight: Optional[int] = None) -> dict[str, Any]:
    """Cota lineal PROYECTADA sobre una dirección: mide solo la componente en
    ese ángulo, no la distancia recta entre los puntos.

    angle_deg=0 mide la separación horizontal, 90 la vertical. Es la que se usa
    para acotar anchos y separaciones en planta cuando los puntos no están
    alineados con el eje que interesa — create_dimension (alineada) daría la
    hipotenusa.

    text: sobrescribe el número medido, para poner "VARIABLE" o un valor de
    proyecto."""
    return acad.call("create_dimension_rotated", {
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "dimLineX": dim_line_x, "dimLineY": dim_line_y, "angleDeg": angle_deg,
        "layer": layer, "style": style, "scale": scale, "text": text,
        "lineweight": lineweight, "colorIndex": None,
    })


@mcp.tool()
def create_dimension_radial(handle: str, leader_length_factor: float = 1.5,
                             layer: Optional[str] = None,
                             style: Optional[str] = None,
                             scale: Optional[float] = None,
                             text: Optional[str] = None,
                             lineweight: Optional[int] = None) -> dict[str, Any]:
    """Cota de radio sobre un Arc o Circle existente, por su handle.

    En un eje de calle o una curva de nivel el radio es EL dato de proyecto:
    sin él, el plano no se puede replantear en obra."""
    return acad.call("create_dimension_radial", {
        "handle": handle, "leaderLengthFactor": leader_length_factor,
        "layer": layer, "style": style, "scale": scale, "text": text,
        "lineweight": lineweight, "colorIndex": None,
    })


@mcp.tool()
def create_dimension_diametric(handle: str, leader_length_factor: float = 1.5,
                                layer: Optional[str] = None,
                                style: Optional[str] = None,
                                scale: Optional[float] = None,
                                text: Optional[str] = None,
                                lineweight: Optional[int] = None) -> dict[str, Any]:
    """Cota de diámetro sobre un Circle o Arc existente. Es como se acota un
    tubo, un registro o una perforación — por diámetro, no por radio."""
    return acad.call("create_dimension_diametric", {
        "handle": handle, "leaderLengthFactor": leader_length_factor,
        "layer": layer, "style": style, "scale": scale, "text": text,
        "lineweight": lineweight, "colorIndex": None,
    })


@mcp.tool()
def create_dimension_angular(vertex_x: float, vertex_y: float,
                              x1: float, y1: float, x2: float, y2: float,
                              arc_x: float, arc_y: float,
                              layer: Optional[str] = None,
                              style: Optional[str] = None,
                              scale: Optional[float] = None,
                              text: Optional[str] = None,
                              lineweight: Optional[int] = None) -> dict[str, Any]:
    """Cota angular entre dos rectas que salen de un vértice común.

    vertex_x/y es el vértice; (x1,y1) y (x2,y2) un punto sobre cada recta;
    arc_x/y por dónde pasa el arco de la cota (define el lado y el radio).
    Es el ángulo entre tangentes de una curva, o la deflexión de un eje."""
    return acad.call("create_dimension_angular", {
        "vertexX": vertex_x, "vertexY": vertex_y,
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "arcX": arc_x, "arcY": arc_y,
        "layer": layer, "style": style, "scale": scale, "text": text,
        "lineweight": lineweight, "colorIndex": None,
    })


@mcp.tool()
def create_dimension_arc_length(handle: str, arc_x: float, arc_y: float,
                                 layer: Optional[str] = None,
                                 style: Optional[str] = None,
                                 scale: Optional[float] = None,
                                 text: Optional[str] = None,
                                 lineweight: Optional[int] = None) -> dict[str, Any]:
    """Cota de DESARROLLO de un arco: cuánto mide recorrido, no en línea recta.

    Es el dato con el que se cuantifica una curva — los metros de guarnición de
    una curva de calle son su desarrollo, no la cuerda. Devuelve además el radio
    y el ángulo de barrido."""
    return acad.call("create_dimension_arc_length", {
        "handle": handle, "arcX": arc_x, "arcY": arc_y,
        "layer": layer, "style": style, "scale": scale, "text": text,
        "lineweight": lineweight, "colorIndex": None,
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
    texto/atributos si aplica) a partir de su handle.

    En una Polyline devuelve además 'bulges' (uno por vértice), 'hasArcs' y
    'length'. Sin los bulges una polilínea curva se leería como una quebrada y
    el largo no daría — que es lo que pasa al leer casi cualquier plano de obra
    civil hecho por otra persona.

    En un Hatch devuelve 'patternName', 'patternScale' y 'patternAngleDeg', que
    es lo que hace falta para replicar con qué textura está resuelto un material
    en un plano ajeno."""
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
def create_spline(points: list[list[float]], closed: bool = False,
                   layer: Optional[str] = None,
                   lineweight: Optional[int] = None,
                   color_index: Optional[int] = None) -> dict[str, Any]:
    """Curva suave que pasa por los puntos dados (spline por puntos de ajuste).

    Para trazos curvos que no son arcos de círculo: curvas de nivel, ejes de
    calle, límites irregulares de terreno. Si el trazo es un arco de radio
    constante usá create_arc, que es más liviano y acotable."""
    return acad.call("create_spline", {
        "points": points, "closed": closed, "layer": layer,
        **_style(lineweight, color_index),
    })


# ------------------------------------------------- Layouts / espacio papel

@mcp.tool()
def create_layout(name: str, plot_config: Optional[str] = None,
                   paper_size: Optional[str] = None) -> dict[str, Any]:
    """Crea un layout (espacio papel): una lámina imprimible de verdad, donde la
    escala la controla el viewport en vez de dibujar el marco en el modelo.

    plot_config: dispositivo de impresión, p.ej. 'DWG To PDF.pc3' (el default).
    paper_size: parte del nombre del papel, p.ej. 'A2' o 'A3' — busca el
    primero que lo contenga entre los del dispositivo. Si no encuentra ninguno,
    el error lista los disponibles.

    Después: create_viewport para poner la ventana al modelo."""
    return acad.call("create_layout", {
        "name": name, "plotConfig": plot_config, "paperSize": paper_size,
    })


@mcp.tool()
def list_layouts() -> dict[str, Any]:
    """Lista los layouts del dibujo con su tamaño de papel, y cuál está activo."""
    return acad.call("list_layouts", {})


@mcp.tool()
def set_current_layout(name: str) -> dict[str, Any]:
    """Cambia la pestaña activa a ese layout (o 'Model' para el espacio modelo)."""
    return acad.call("set_current_layout", {"name": name})


@mcp.tool()
def create_viewport(layout: str, center_x: float, center_y: float,
                     width: float, height: float,
                     view_center_x: float = 0.0, view_center_y: float = 0.0,
                     scale_denominator: float = 50.0,
                     model_units_per_mm: float = 1.0,
                     locked: bool = True) -> dict[str, Any]:
    """Ventana dentro de un layout que muestra una zona del espacio modelo a
    escala fija. Es la forma correcta de armar una lámina: el dibujo vive una
    sola vez en el modelo y cada viewport lo muestra a la escala que necesita.

    center_x/center_y, width, height: posición y tamaño de la ventana en
    MILÍMETROS DE PAPEL, con origen en la esquina inferior izquierda de la hoja.
    view_center_x/y: qué punto del MODELO queda en el centro de la ventana.
    scale_denominator: 50 para 1:50, 100 para 1:100.
    model_units_per_mm: cuántos milímetros reales mide 1 unidad del modelo —
    1000 si dibujás en metros, 10 en centímetros, 1 en milímetros. Sin esto la
    escala del viewport sale mil veces mal.
    locked: deja el viewport bloqueado para que un zoom accidental no le cambie
    la escala. Es lo que querés casi siempre."""
    return acad.call("create_viewport", {
        "layout": layout, "centerX": center_x, "centerY": center_y,
        "width": width, "height": height,
        "viewCenterX": view_center_x, "viewCenterY": view_center_y,
        "scaleDenominator": scale_denominator,
        "modelUnitsPerMm": model_units_per_mm, "locked": locked,
    })


# ----------------------------------------------------- Estilos con nombre

@mcp.tool()
def set_text_style(name: str, font: Optional[str] = None, height: float = 0.0,
                    width_factor: float = 1.0, oblique: float = 0.0,
                    set_current: bool = False) -> dict[str, Any]:
    """Crea o configura un estilo de texto con nombre, y opcionalmente lo deja
    como el activo del dibujo.

    font: 'arial.ttf' / 'romans.shx' / 'txt.shx'. Las .ttf se aplican como
    TrueType y las .shx como fuente vectorial de AutoCAD.
    height: 0 deja la altura libre (la fija cada texto), que es lo habitual —
    poner un valor acá la clava para todos los textos del estilo.
    width_factor: <1 comprime las letras, útil en rótulos angostos.

    Sin estilos con nombre todo sale con el 'Standard' de la plantilla, que
    cambia de un DWG a otro: el mismo plano se ve distinto según con qué
    archivo arrancaste."""
    return acad.call("set_text_style", {
        "name": name, "font": font, "height": height,
        "widthFactor": width_factor, "oblique": oblique,
        "setCurrent": set_current,
    })


@mcp.tool()
def set_dim_style(name: str, text_height: Optional[float] = None,
                   arrow_size: Optional[float] = None,
                   scale: Optional[float] = None,
                   decimal_places: Optional[int] = None,
                   text_style: Optional[str] = None,
                   units_factor: Optional[float] = None,
                   extension_offset: Optional[float] = None,
                   extension_beyond: Optional[float] = None,
                   set_current: bool = False) -> dict[str, Any]:
    """Crea o configura un estilo de cota con nombre.

    text_height / arrow_size: en unidades del modelo.
    scale: DIMSCALE, multiplica texto y flechas de una sola vez.
    decimal_places: decimales del número (2 para '3.45', 0 para '3').
    units_factor: DIMLFAC, multiplica el valor medido — dibujando en metros,
    poné 100 para que la cota diga centímetros o 1000 para milímetros.
    text_style: nombre de un estilo creado con set_text_style.

    Después pasá style='<nombre>' a create_dimension para usarlo."""
    return acad.call("set_dim_style", {
        "name": name, "textHeight": text_height, "arrowSize": arrow_size,
        "scale": scale, "decimalPlaces": decimal_places,
        "textStyle": text_style, "unitsFactor": units_factor,
        "extensionOffset": extension_offset, "extensionBeyond": extension_beyond,
        "setCurrent": set_current,
    })


@mcp.tool()
def list_styles() -> dict[str, Any]:
    """Lista los estilos de texto y de cota del dibujo, marcando los activos."""
    return acad.call("list_styles", {})


# ------------------------------------------------------ Documentos abiertos

@mcp.tool()
def list_documents() -> dict[str, Any]:
    """Lista los dibujos abiertos en AutoCAD y marca cuál está activo.

    Todas las demás tools trabajan sobre el ACTIVO."""
    return acad.call("list_documents", {})


@mcp.tool()
def set_active_document(name: str) -> dict[str, Any]:
    """Cambia el dibujo activo, sobre el que van a operar las demás tools.
    Alcanza con el nombre de archivo ('Casa.dwg'), sin la ruta completa."""
    return acad.call("set_active_document", {"name": name})


@mcp.tool()
def measure_text(text: str, height: float, style: Optional[str] = None,
                  width_factor: Optional[float] = None) -> dict[str, Any]:
    """Cuánto va a medir un texto ANTES de dibujarlo, en unidades del modelo.

    Estimar el ancho por cantidad de caracteres falla: depende de la fuente y
    de qué letras sean, y un rótulo mal medido termina cruzando un muro. Esto
    mide con la misma geometría que usa AutoCAD al dibujar.

    Sirve para centrar textos, decidir si un rótulo entra en un espacio, o
    elegir la altura para que un título quepa en un ancho dado."""
    return acad.call("measure_text", {
        "text": text, "height": height, "style": style,
        "widthFactor": width_factor,
    })


@mcp.tool()
def delete_layout(name: str) -> dict[str, Any]:
    """Borra un layout del dibujo. No se puede borrar 'Model' ni dejar el
    dibujo sin ninguna lámina. Si es el layout activo, primero cambia a Model."""
    return acad.call("delete_layout", {"name": name})


@mcp.tool()
def purge_block(name: str) -> dict[str, Any]:
    """Borra una definición de bloque del dibujo.

    Falla si todavía quedan inserciones de ese bloque: hay que borrarlas antes
    con delete_entity, si no quedarían referencias colgadas. Sirve para limpiar
    símbolos que se definieron y ya no se usan."""
    return acad.call("purge_block", {"name": name})


@mcp.tool()
def save_drawing(path: Optional[str] = None,
                  overwrite: bool = False) -> dict[str, Any]:
    """Guarda el dibujo activo en disco.

    path: ruta .dwg destino. Si se omite, guarda sobre el archivo actual — y si
    el dibujo nunca se guardó, avisa que hace falta pasarlo.
    overwrite: hace falta en True para pisar un archivo que ya existe (salvo
    que sea el archivo del propio dibujo).

    Escribe el archivo por API: AutoCAD puede seguir mostrando el nombre viejo
    en la pestaña hasta que lo reabras, pero en disco queda bien."""
    return acad.call("save_drawing", {"path": path, "overwrite": overwrite})


@mcp.tool()
def export_block(name: str, path: str,
                  overwrite: bool = False) -> dict[str, Any]:
    """Exporta una definición de bloque de este dibujo a su propio archivo DWG.

    Sirve para armar una biblioteca de símbolos: definís el bloque una vez con
    define_block, lo exportás, y después lo insertás en cualquier otro dibujo
    con insert_block(name=..., path=...)."""
    return acad.call("export_block", {
        "name": name, "path": path, "overwrite": overwrite,
    })


@mcp.tool()
def ping() -> dict[str, Any]:
    """Confirma que el plugin responde, sobre qué dibujo está parado y qué
    versión del plugin está cargada en AutoCAD.

    Útil para saber si el DLL cargado es el mismo que el código actual: si
    agregaste comandos y el plugin devuelve 'Comando no soportado', la versión
    que devuelve esto te lo confirma."""
    return acad.call("ping", {})


@mcp.tool()
def zoom_extents() -> dict[str, Any]:
    """Hace zoom a la extensión completa del dibujo activo."""
    return acad.call("zoom_extents", {})


if __name__ == "__main__":
    mcp.run()
