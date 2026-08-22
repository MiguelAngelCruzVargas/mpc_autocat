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
import compose as compose_mod
import electrical as elec_mod
import profile as profile_mod
import isometric as iso_mod
import quantities as qty_mod
import rebar as rebar_mod
import roof as roof_mod
import rules as rules_mod
import furniture as fur_mod
import layers as layers_mod
import sections as sect_mod
import sheet as sheet_mod
import space as space_mod
import symbols as sym_mod

mcp = FastMCP("autocad")


def _style(lineweight: Optional[int], color_index: Optional[int]) -> dict[str, Any]:
    """Propiedades de trazo comunes a toda entidad que se crea.

    lineweight va en centésimas de mm (30 = 0.30mm) y pisa el grosor de la capa
    para esa entidad; None deja ByLayer. Valores válidos de AutoCAD: 0,5,9,13,
    15,18,20,25,30,35,40,50,53,60,70,80,90,100,106,120,140,158,200,211.
    """
    return {"lineweight": lineweight, "colorIndex": color_index}


# Relación ancho/altura por carácter, misma constante que usa annotation._w
# como respaldo cuando no vale la pena una llamada a measure_text.
_CHAR_W_RATIO = 0.87


def _track_text(text: str, x: float, y: float, height: float,
                rotation_deg: float = 0.0, width: float = 0.0) -> None:
    """Registra la huella aproximada de un texto recién creado, para que
    check_annotations pueda avisar si otro texto (o una cota) lo pisa
    después -- sin esto, un create_text/create_mtext/create_leader llamado
    directo (en vez de con place_labels) queda invisible para el chequeo de
    cierre. Es a propósito una aproximación axis-aligned, no exacta: avisar
    de más ante un ángulo raro es mejor que no avisar nada."""
    if not text:
        return
    ancho = width if width > 0 else len(text) * height * _CHAR_W_RATIO
    alto = height * 1.2
    if rotation_deg % 180 < 45 or rotation_deg % 180 > 135:
        caja = (x, y, x + ancho, y + alto)
    else:
        caja = (x - alto, y, x, y + ancho)
    space_mod.track(*caja, f"{space_mod.PREFIJO_TEXTO} {text[:40]}")


def _reset_drawing_state(dibujo: str) -> list[str]:
    """Olvida lo que este proceso cacheaba del dibujo ANTERIOR.

    Varios módulos guardan estado de proceso que describe UN dibujo: las
    huellas de muebles y las franjas de anotación ya ocupadas (space), y el
    listado de capas que existen (layers, cacheado para no pedirlo en cada
    set_layer). Nada de eso vale para otro DWG.

    Sin este reset, con dos dibujos abiertos pasaba lo siguiente: place_labels
    esquivaba una cama que está en el OTRO plano y mandaba el rótulo a un
    lugar que acá está libre; y set_layer daba por existente —y por lo tanto
    ya configurada— una capa que solo existe allá, dejándola sin color ni
    grosor. Los dos son silenciosos: el dibujo sale mal sin ningún error.

    Devuelve los avisos que corresponda mostrarle a quien cambió de dibujo.
    """
    avisos: list[str] = []
    olvidadas = len(space_mod.OCCUPIED) + len(space_mod.FOOTPRINTS)

    space_mod.clear()
    fur_mod.reset_footprints()
    layers_mod.reset()

    if olvidadas:
        avisos.append(
            f"Se olvidaron {olvidadas} huellas/franjas del dibujo anterior: "
            "place_labels y check_annotations arrancan de cero en "
            f"'{dibujo}'. Lo que ya esté dibujado acá no lo conocen — si hace "
            "falta que lo esquiven, pasáselo en 'obstacles'.")

    # La escala (unidades del modelo por mm de papel) NO se toca: es un
    # número por lámina, no por dibujo, y ponerlo en un default sería tan
    # incorrecto como dejar el anterior. Pero hay que avisarlo, porque es
    # justo el que no da error cuando está mal.
    avisos.append(
        f"La escala en vigencia sigue siendo {space_mod.units_per_paper_mm()} "
        "unidades por mm de papel, la del dibujo anterior. Si esta lámina es "
        "otra escala, llamá create_sheet (o pasá 'scale' explícito al acotar) "
        "antes de anotar.")
    return avisos


# ------------------------------------------------- Lámina (cajón + rotulación)

@mcp.tool()
def check_walls(walls: list[dict[str, Any]], tolerance: float = 0.05,
                 min_length: float = 0.40) -> dict[str, Any]:
    """Verifica que la muraria cierre: sin extremos al aire ni tramos sueltos.

    Un muro que muere en el aire —el espolón en "L" que estrangula un paso— es
    válido como geometría y no se construye. No lo ve el grafo de ambientes ni
    lo arregla union_regions, que solo limpia los cruces.

    walls: [{"points": [[x,y], ...], "name": "divisorio cocina"}] con los EJES
    de cada muro, los mismos que le pasás a create_walls.

    Revisa, sirve para cualquier tipo de planta:
      - extremos libres: un arranque o final que no toca ningún otro muro
      - tramos por debajo del mínimo constructivo
      - muros duplicados o superpuestos sobre el mismo eje

    Llamala ANTES de trazar, con la lista de ejes que pensás dibujar."""
    return rules_mod.check_walls(walls=walls, tolerance=tolerance,
                                 min_length=min_length)


@mcp.tool()
def check_geometry(rooms: list[dict[str, Any]],
                    doors: list[dict[str, Any]]) -> dict[str, Any]:
    """Verifica que los recintos sean coherentes y construibles.

    check_layout revisa el GRAFO de accesos —quién comunica con quién— pero no
    que el dibujo lo cumpla. Esto revisa la geometría, que es donde aparecen los
    errores que el grafo no ve:
      - recintos por debajo del mínimo habitable (una recámara de 1.50 m de
        fondo no es una recámara, aunque el grafo diga que tiene puerta)
      - recintos que se pisan entre sí
      - dos puertas para el mismo par de ambientes
      - puertas entre recintos que NO comparten muro: el ambiente queda sellado
        aunque la puerta figure en el grafo

    doors puede llevar "x" e "y" con la posición del vano; con eso verifica
    además que caiga sobre la frontera común. Sin posición, esa parte se saltea.

    Llamala JUNTO CON check_layout antes de dibujar: una valida la lógica de
    uso, la otra que el espacio exista de verdad."""
    return rules_mod.check_geometry(rooms=rooms, doors=doors)


@mcp.tool()
def check_layout(rooms: list[dict[str, Any]], doors: list[dict[str, Any]],
                  lot_width: Optional[float] = None,
                  lot_depth: Optional[float] = None,
                  windows: Optional[list[dict[str, Any]]] = None
                  ) -> dict[str, Any]:
    """Verifica las reglas de zonificación de una planta ANTES de dibujarla.

    Un plano puede estar impecable de dibujo y ser inconstruible. Esto revisa lo
    que la geometría no muestra:
      - el acceso desde la calle NUNCA puede abrir a una recámara o un baño
      - el baño principal es en-suite: se entra desde la recámara principal
      - al patio de servicio no se llega cruzando un dormitorio
      - todo ambiente tiene al menos un acceso
      - la cocina comunica con el comedor y no es paso entre recámaras
      - no se abren ventanas sobre la colindancia

    rooms: [{"name": "SALA", "x0":.., "y0":.., "x1":.., "y1":..}]
    doors: [{"from": "EXTERIOR", "to": "VESTIBULO", "width": 0.90}] —
           from='EXTERIOR' marca la puerta de calle.
    windows: [{"room": "SALA", "wall": "izquierda"}] para colindancias.

    Devuelve 'ok' y, por cada problema, la regla que viola y cómo corregirlo."""
    return rules_mod.check_layout(rooms=rooms, doors=doors, lot_width=lot_width,
                                  lot_depth=lot_depth, windows=windows)


@mcp.tool()
def check_program(lot_width: float, lot_depth: float,
                   spaces: list[dict[str, Any]],
                   outdoor: Optional[list[dict[str, Any]]] = None,
                   wall_thickness: float = 0.15,
                   circulation_factor: float = 0.12,
                   model_units: str = "m") -> dict[str, Any]:
    """¿El programa que pidió el cliente entra en el terreno?

    LLAMALA ANTES DE DIBUJAR, siempre que te den un terreno y una lista de
    ambientes con medidas. Un programa que no cierra no se arregla dibujando
    con cuidado: hay que avisarlo con el número, para que la decisión de qué
    achicar la tome el cliente y no quede escondida en un plano que después no
    se puede construir.

    spaces: [{"name": "Recámara", "width": 3.85, "depth": 4.00}] o con
    "area" directamente.
    outdoor: áreas descubiertas que se restan del terreno (cochera, jardín,
    patio de servicio), mismo formato.
    circulation_factor: pasillos y vestíbulos como fracción del programa; 0.12
    es lo habitual en vivienda.

    Devuelve 'fits', el déficit en m2 y en porcentaje, y en 'options' por dónde
    podría salir (reducir la cochera, achicar el ambiente mayor, repartir)."""
    return sheet_mod.check_program(
        lot_width=lot_width, lot_depth=lot_depth, spaces=spaces,
        outdoor=outdoor, wall_thickness=wall_thickness,
        circulation_factor=circulation_factor, model_units=model_units)


@mcp.tool()
def check_annotations(items: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """¿El aparato de anotación se pisa entre sí? Cotas, burbujas de eje y rótulos.

    Los otros check_* miran el proyecto; este mira el plano COMO DIBUJO, que es
    donde aparece el error que no se ve hasta abrir el DWG: la cadena de cotas
    generales cruzando la fila de burbujas de eje.

    Normalmente sale limpio solo, porque create_dimension_chain y
    create_axis_grid reservan la franja que ocupan y se apilan una afuera de
    otra. Da problemas cuando algo se ubicó a mano eligiendo el offset de
    memoria — que es exactamente el caso que conviene verificar.

    items: rectángulos a verificar SIN dibujarlos, para preguntar ANTES de
    ubicar algo a mano: [{"x0":.., "y0":.., "x1":.., "y1":.., "what":".."}]."""
    return rules_mod.check_annotations(items=items)


@mcp.tool()
def check_drawing_hygiene(sample_limit: int = 2000,
                          max_duplicate_check: int = 800) -> dict[str, Any]:
    """Audita el ARCHIVO en sí — no el proyecto: capas creadas y nunca
    usadas, texto todavía en una fuente .shx (no mapea acentos ni Ø), y
    entidades duplicadas exactas superpuestas en la misma capa.

    Es un ángulo distinto de los demás check_*: esos validan que el proyecto
    tenga sentido (el programa entra, la zonificación cumple); este valida
    que el archivo no arrastre basura — capas fantasma que confunden a quien
    abre el DWG después, texto que se va a ver con cuadraditos, líneas
    encimadas que no se notan hasta que se selecciona una y aparecen dos.

    sample_limit: hasta cuántas entidades revisa (2000 alcanza para casi
    cualquier plano). max_duplicate_check: si hay más Line/Circle que esto,
    se saltea la revisión de duplicados en vez de hacer cientos de consultas
    de más — se avisa en 'problems' por qué."""
    capas = acad.call("list_layers", {})["layers"]
    entidades = acad.call("list_entities", {"limit": sample_limit})["entities"]

    usadas = {e["layer"] for e in entidades if e.get("layer")}
    capas_vacias = [c["name"] for c in capas
                   if c["name"] not in usadas
                   and c["name"] not in ("0", "Defpoints")]

    estilos = acad.call("list_styles", {})
    shx = [s["name"] for s in estilos.get("textStyles", [])
          if str(s.get("font", "")).lower().endswith(".shx")]

    problemas: list[str] = []
    candidatos = [e for e in entidades if e.get("type") in ("Line", "Circle")]
    duplicados: list[dict[str, Any]] = []
    if len(candidatos) > max_duplicate_check:
        problemas.append(
            f"se salteó la revisión de duplicados: hay {len(candidatos)} "
            f"Line/Circle, más que max_duplicate_check ({max_duplicate_check}). "
            "Subilo si igual querés que se revise.")
    else:
        firmas: dict[tuple, list[str]] = {}
        for e in candidatos:
            handle = e.get("handle")
            if not handle:
                continue
            detalle = acad.call("get_entity", {"handle": handle})
            if e["type"] == "Line":
                clave = ("Line", e.get("layer"),
                         round(detalle["startPoint"][0], 4), round(detalle["startPoint"][1], 4),
                         round(detalle["endPoint"][0], 4), round(detalle["endPoint"][1], 4))
            else:
                clave = ("Circle", e.get("layer"),
                         round(detalle["center"][0], 4), round(detalle["center"][1], 4),
                         round(detalle["radius"], 4))
            firmas.setdefault(clave, []).append(handle)
        duplicados = [{"type": clave[0], "layer": clave[1], "handles": hs}
                      for clave, hs in firmas.items() if len(hs) > 1]

    if capas_vacias:
        problemas.append(f"{len(capas_vacias)} capa(s) creada(s) y sin usar: "
                         + ", ".join(capas_vacias))
    if shx:
        problemas.append(f"{len(shx)} estilo(s) de texto todavía en fuente .shx "
                         "(no mapea acentos ni Ø): " + ", ".join(shx))
    if duplicados:
        total = sum(len(d["handles"]) for d in duplicados)
        problemas.append(f"{len(duplicados)} grupo(s) de entidades duplicadas "
                         f"exactas ({total} entidades en total)")

    return {
        "ok": not problemas,
        "emptyLayers": capas_vacias,
        "shxTextStyles": shx,
        "duplicates": duplicados,
        "problems": problemas,
    }


@mcp.tool()
def check_retaining_wall(height: float,
                         soil_unit_weight: float = 1800.0,
                         friction_angle_deg: float = 30.0,
                         surcharge: float = 0.0,
                         concrete_unit_weight: float = 2400.0,
                         friction_coefficient: float = 0.5,
                         min_fs_overturning: float = 1.5,
                         min_fs_sliding: float = 1.5,
                         stem_thickness: Optional[float] = None,
                         footing_thickness: Optional[float] = None,
                         max_base_width: Optional[float] = None) -> dict[str, Any]:
    """Proporción PRELIMINAR de un muro de contención por empuje activo de
    Rankine. LLAMALA ANTES DE DIBUJAR un muro que retiene tierra -- un muro
    de 3.5 m de altura no es un muro de 15 cm con más lineweight: necesita
    una base y un espesor que resistan volteo y deslizamiento, y hasta ahora
    esta biblioteca no tenía ninguna cuenta para eso.

    Modelo: cantiléver en T (vástago a base/3 del paño, talón del lado de
    la tierra cargando el peso del relleno que tiene encima) -- conservador
    en lo demás (ignora empuje pasivo y diente de cortante), pero con el
    talón puesto, porque sin él la base sale desproporcionada (un muro de
    gravedad puro sin talón necesita más de 12 m de base para 3.5 m de
    altura). Esto es lo que create_walls (vástago) + una zapata asimétrica
    dibujada con create_polyline (toe/heel según toeLength/heelLength)
    pueden trazar de verdad.

    height: altura de tierra retenida (desplante a corona), en metros.
    soil_unit_weight (kg/m3, default 1800), friction_angle_deg (default 30°)
    y surcharge (kg/m2, sobrecarga sobre el relleno) describen el suelo.
    concrete_unit_weight (kg/m3) y friction_coefficient (concreto-suelo en
    la base) describen el muro. min_fs_overturning/min_fs_sliding son los
    factores de seguridad mínimos exigidos (1.5 es lo habitual).

    Devuelve 'ok' y, si cumple, baseWidth/stemThickness/footingThickness ya
    verificados -- junto con activeThrust, overturningMoment y los factores
    de seguridad alcanzados, para poder revisar la cuenta sin recalcularla."""
    return rules_mod.check_retaining_wall(
        height=height, soil_unit_weight=soil_unit_weight,
        friction_angle_deg=friction_angle_deg, surcharge=surcharge,
        concrete_unit_weight=concrete_unit_weight,
        friction_coefficient=friction_coefficient,
        min_fs_overturning=min_fs_overturning, min_fs_sliding=min_fs_sliding,
        stem_thickness=stem_thickness, footing_thickness=footing_thickness,
        max_base_width=max_base_width)


@mcp.tool()
def check_footing(axial_load: float,
                  column_width: float = 0.30,
                  column_length: float = 0.30,
                  allow_bearing: float = 15000.0,
                  concrete_fc: float = 200.0,
                  concrete_unit_weight: float = 2400.0,
                  soil_unit_weight: float = 1700.0,
                  depth_to_footing: float = 1.0,
                  phi_shear: float = 0.85,
                  min_thickness: float = 0.20,
                  max_side: Optional[float] = None) -> dict[str, Any]:
    """Proporción PRELIMINAR de una zapata aislada. LLAMALA ANTES DE DIBUJAR
    una zapata bajo una columna cargada -- "1.00 x 1.00 x 0.30, típico de
    vivienda" es una frase que no dice si ESA columna con ESA carga entra
    ahí; esta tool contesta las dos preguntas que sí importan:

    - CARGA: el lado sale de repartir la carga (más el peso propio de la
      zapata y la tierra que le queda encima) sobre la capacidad admisible
      del suelo.
    - PUNZONAMIENTO: con el lado ya fijo, el peralte tiene que resistir el
      cortante que la columna punzona en el perímetro crítico a d/2 (ACI,
      vc=1.06·√f'c en kg/cm²) -- típicamente esto gobierna antes que la
      carga misma, y es justo lo que una proporción a ojo no revisa.

    axial_load: carga de servicio sobre la columna, kg. column_width /
    column_length: sección de la columna, m. allow_bearing: capacidad
    admisible del suelo, kg/m2 (15000 = 15 t/m2, moderado sin estudio de
    mecánica de suelos). concrete_fc: f'c del concreto, kg/cm2 (200 típico
    en vivienda). depth_to_footing: desplante, m.

    Devuelve 'ok' y, si cumple, side/thickness ya verificados, junto con la
    carga total, el cortante actuante y resistente -- para poder revisar la
    cuenta, no solo confiar en el número."""
    return rules_mod.check_footing(
        axial_load=axial_load, column_width=column_width,
        column_length=column_length, allow_bearing=allow_bearing,
        concrete_fc=concrete_fc, concrete_unit_weight=concrete_unit_weight,
        soil_unit_weight=soil_unit_weight, depth_to_footing=depth_to_footing,
        phi_shear=phi_shear, min_thickness=min_thickness, max_side=max_side)


@mcp.tool()
def check_slab_span(span: float,
                    live_load: float = 400.0,
                    width: float = 1.0,
                    concrete_fc: float = 250.0,
                    steel_fy: float = 4200.0,
                    concrete_unit_weight: float = 2400.0,
                    min_thickness: float = 0.12,
                    cover: float = 0.03,
                    max_steel_ratio: float = 0.016) -> dict[str, Any]:
    """Proporción PRELIMINAR de una losa maciza simplemente apoyada entre
    dos apoyos. Sirve tanto para una losa de entrepiso como para el
    tablero de un puente peatonal entre sus dos estribos -- es la misma
    cuenta: un claro, una carga viva distribuida, un peralte que aguante
    el momento sin pasarse de cuantía.

    span: claro libre entre apoyos, m. live_load: carga viva, kg/m2 (400
    es referencia para pasarela peatonal; una losa de entrepiso de
    vivienda va más baja, ~170-250 kg/m2). concrete_fc/steel_fy: kg/cm2
    (250 y 4200 típicos de obra en México).

    Método: peralte semilla L/20, momento w·L²/8, acero por flexión
    simplificada -- engorda el peralte solo si la cuantía se pasa de
    max_steel_ratio. Chequeo PRELIMINAR, no reemplaza cortante ni
    deflexión de un cálculo completo.

    Devuelve 'ok', 'thickness' y 'mainSteelArea_cm2_per_m' verificados."""
    return rules_mod.check_slab_span(
        span=span, live_load=live_load, width=width,
        concrete_fc=concrete_fc, steel_fy=steel_fy,
        concrete_unit_weight=concrete_unit_weight,
        min_thickness=min_thickness, cover=cover,
        max_steel_ratio=max_steel_ratio)


@mcp.tool()
def check_bridge_girder(span: float,
                        girder_spacing: float,
                        girder_width: float = 0.30,
                        slab_thickness: float = 0.20,
                        concrete_fc: float = 250.0,
                        steel_fy: float = 4200.0,
                        concrete_unit_weight: float = 2400.0,
                        min_depth: float = 0.5,
                        cover: float = 0.05,
                        max_steel_ratio: float = 0.016) -> dict[str, Any]:
    """Proporción PRELIMINAR de una trabe principal de puente bajo carga
    vehicular real -- un claro largo con tráfico pesado necesita un
    vehículo de diseño, no una carga viva inventada. Usa la CARGA DE
    CARRIL HS20-44 de AASHTO (uniforme + concentrada para momento), la
    alternativa que la propia norma permite en vez de mover el camión eje
    por eje a mano.

    span: claro libre entre apoyos, m. girder_spacing: separación entre
    ejes de trabe, m (define cuánta losa tributa a esta trabe y el factor
    de distribución). slab_thickness: espesor YA resuelto de la losa de
    rodadura (con check_slab_span) -- se toma como dato, no se recalcula.
    concrete_fc/steel_fy: kg/cm2 (250/4200 típicos en México).

    Método: DF=girder_spacing/1.83 (AASHTO S/6.0 convertido), impacto
    AASHTO 50/(125+L_pies) con tope 0.3, peralte semilla L/12. Chequeo
    PRELIMINAR -- no reemplaza el análisis de carga móvil completo
    (posición crítica de ejes), cortante, ni deflexión.

    Devuelve 'ok', 'depth' y 'mainSteelArea_cm2' verificados, junto con
    el factor de distribución, el de impacto y los momentos con los que
    se calculó."""
    return rules_mod.check_bridge_girder(
        span=span, girder_spacing=girder_spacing, girder_width=girder_width,
        slab_thickness=slab_thickness, concrete_fc=concrete_fc,
        steel_fy=steel_fy, concrete_unit_weight=concrete_unit_weight,
        min_depth=min_depth, cover=cover, max_steel_ratio=max_steel_ratio)


@mcp.tool()
def check_roof_truss(span: float,
                     truss_spacing: float,
                     rise: float,
                     roof_dead_load: float = 15.0,
                     roof_live_load: float = 40.0,
                     wind_uplift: float = 0.0,
                     dead_load_factor_uplift: float = 0.6) -> dict[str, Any]:
    """Reacción PRELIMINAR de una armadura de techo a dos aguas sobre sus
    dos apoyos -- lo que hace falta para dimensionar la columna y la
    zapata que la reciben (check_column/check_footing) en vez de inventar
    la carga axial a ojo. En una nave o cancha techada, con cubierta
    liviana y mucha área de techo, la succión de viento puede superar al
    peso propio: la reacción puede terminar siendo hacia ARRIBA, y el
    apoyo necesita anclaje a tensión, no un simple apoyo.

    span: distancia entre apoyos (columnas), m. truss_spacing: separación
    entre armaduras, m -- junto con span define el área tributaria de
    ESTA armadura. rise: altura de cumbrera sobre el apoyo, m.
    roof_dead_load/roof_live_load: kg/m2 de proyección horizontal (15/40
    son valores de referencia para lámina liviana sobre estructura
    ligera). wind_uplift: succión de viento, kg/m2 -- 0.0 no inventa una
    carga que el proyecto no dio; si el sitio la tiene, pasala.

    Método: viga simplemente apoyada sobre el área tributaria; reacción de
    gravedad (muerta+viva)/2 por apoyo; reacción de viento
    (0.6·muerta-succión)/2, negativa = levantamiento neto. Fuerza de
    cuerda equivalente = momento máximo / peralte de armadura. Chequeo
    PRELIMINAR -- no reemplaza el análisis por nudos ni el estudio de
    viento del reglamento aplicable.

    Devuelve 'ok' (False si hay levantamiento neto), 'gravityReaction_kg'
    (la carga para check_column) y 'windUpliftReaction_kg'."""
    return rules_mod.check_roof_truss(
        span=span, truss_spacing=truss_spacing, rise=rise,
        roof_dead_load=roof_dead_load, roof_live_load=roof_live_load,
        wind_uplift=wind_uplift, dead_load_factor_uplift=dead_load_factor_uplift)


@mcp.tool()
def check_column(axial_load: float,
                 height: float,
                 width: float = 0.30,
                 depth: float = 0.30,
                 concrete_fc: float = 200.0,
                 steel_fy: float = 4200.0,
                 k_factor: float = 1.0,
                 steel_ratio: float = 0.01,
                 phi: float = 0.65,
                 max_slenderness: float = 22.0,
                 max_side: Optional[float] = None) -> dict[str, Any]:
    """Proporción PRELIMINAR de una columna/castillo de concreto bajo carga
    axial. Lo que "30x30, típico" no contesta es si ESA columna, con ESA
    altura libre, sigue siendo columna corta o ya es esbelta -- una
    sección que sobra por capacidad pura puede fallar por pandeo antes de
    aplastarse, el caso típico de una nave/cancha techada con columnas de
    4 a 6 m sin apoyo intermedio.

    Dos chequeos independientes: CAPACIDAD AXIAL (Pn de columna estribada
    con excentricidad mínima, ACI 10.3.6.2, φ=0.65) y ESBELTEZ (k·lu/r,
    r=0.3·lado menor; por encima de max_slenderness=22 ya no es columna
    corta sin magnificar momentos).

    axial_load: carga de servicio, kg (sin factorizar; si viene de
    check_roof_truss, usá 'gravityReaction_kg'). height: altura libre sin
    arriostrar, m. width/depth: sección a probar, m. k_factor: factor de
    longitud efectiva (1.0 = articulada en los dos extremos).
    steel_ratio: cuantía de acero a probar (0.01 = 1%, mínimo ACI).

    Chequeo PRELIMINAR de proporción -- no reemplaza el diseño biaxial ni
    el análisis de columna esbelta con magnificación de momentos.

    Devuelve 'ok' y, si cumple, 'width'/'depth' ya verificados por los dos
    chequeos, junto con la capacidad axial y la esbeltez."""
    return rules_mod.check_column(
        axial_load=axial_load, height=height, width=width, depth=depth,
        concrete_fc=concrete_fc, steel_fy=steel_fy, k_factor=k_factor,
        steel_ratio=steel_ratio, phi=phi, max_slenderness=max_slenderness,
        max_side=max_side)


@mcp.tool()
def check_all(rooms: Optional[list[dict[str, Any]]] = None,
              doors: Optional[list[dict[str, Any]]] = None,
              windows: Optional[list[dict[str, Any]]] = None,
              lot_width: Optional[float] = None,
              lot_depth: Optional[float] = None,
              walls: Optional[list[dict[str, Any]]] = None,
              wall_tolerance: float = 0.05,
              wall_min_length: float = 0.40,
              annotation_items: Optional[list[dict[str, Any]]] = None,
              hygiene_sample_limit: int = 2000,
              hygiene_max_duplicate_check: int = 800) -> dict[str, Any]:
    """Corre TODOS los check_* de cierre en una sola llamada y devuelve un
    reporte único, en vez de tener que acordarse de invocar cada uno por
    separado y juntar los resultados a mano.

    No incluye check_program: ese responde una pregunta de otra etapa (¿el
    programa entra en el terreno?, ANTES de que haya rooms/walls) con un
    vocabulario distinto (spaces, no rooms con x0/y0/x1/y1) — se sigue
    llamando aparte, al arrancar.

    rooms/doors/windows/lot_width/lot_depth: si se pasan rooms Y doors, corre
    check_layout y check_geometry. walls: si se pasa, corre check_walls.
    Lo que no se pase se saltea (se avisa en 'skipped'), para poder llamarla
    también en un dibujo que todavía no tiene muros.

    check_annotations y check_drawing_hygiene SIEMPRE corren: leen el dibujo
    activo, no necesitan que se les describa el proyecto.

    Devuelve 'ok' (True solo si TODOS los checks corridos salieron limpios),
    'problems' con todos los problemas de todos los checks juntos en una
    sola lista plana (cada uno con 'check' diciendo de cuál vino), y 'checks'
    con el resultado completo de cada uno por separado para el detalle."""
    checks: dict[str, Any] = {}
    skipped: list[str] = []

    if rooms is not None and doors is not None:
        checks["layout"] = check_layout(rooms=rooms, doors=doors,
                                        lot_width=lot_width, lot_depth=lot_depth,
                                        windows=windows)
        checks["geometry"] = check_geometry(rooms=rooms, doors=doors)
    else:
        skipped.append("layout/geometry (falta rooms y/o doors)")

    if walls is not None:
        checks["walls"] = check_walls(walls=walls, tolerance=wall_tolerance,
                                      min_length=wall_min_length)
    else:
        skipped.append("walls (falta walls)")

    checks["annotations"] = check_annotations(items=annotation_items)
    checks["hygiene"] = check_drawing_hygiene(
        sample_limit=hygiene_sample_limit,
        max_duplicate_check=hygiene_max_duplicate_check)

    problems: list[dict[str, Any]] = []
    for nombre, resultado in checks.items():
        for p in resultado.get("problems", []):
            # check_drawing_hygiene devuelve strings sueltos; los demás,
            # dicts con rule/problem/fix -- se normalizan al mismo formato.
            entry = {"problem": p} if isinstance(p, str) else dict(p)
            entry["check"] = nombre
            problems.append(entry)

    return {"ok": not problems, "problems": problems, "count": len(problems),
           "checks": checks, "skipped": skipped}


@mcp.tool()
def fit_sheet(min_x: float, min_y: float, max_x: float, max_y: float,
               model_units: str = "m",
               sheet_format: Optional[str] = None,
               scale_denominator: Optional[float] = None,
               margin_mm: float = 15.0,
               allow_portrait: bool = True) -> dict[str, Any]:
    """Qué formato, escala y origen hacen falta para que un dibujo entre.

    ES EL PASO PREVIO A create_sheet CUANDO YA HAY ALGO DIBUJADO. El orden
    correcto es: dibujar -> get_extents -> fit_sheet -> create_sheet con lo que
    devuelve. Al revés (cajón primero) el dibujo se sale de la hoja en cuanto
    crece, que es el error más común.

    Sin scale_denominator elige la escala usual para ese tamaño —1:50 para una
    casa, 1:200 para una calle— y después el formato MÁS CHICO que la contenga,
    probando también el formato vertical. No es una cuenta: una planta de casa
    se dibuja a 1:50 aunque entrara a 1:100 en una hoja más chica, porque a
    1:100 no se leen los espesores ni las cotas de un baño.

    Devuelve sheet_format, orientation, scale_denominator y origin_x/origin_y
    para pasárselos tal cual a create_sheet. Si no entra en ningún formato, el
    error dice qué escala haría falta."""
    return sheet_mod.fit_sheet(
        min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y,
        model_units=model_units, sheet_format=sheet_format,
        scale_denominator=scale_denominator, margin_mm=margin_mm,
        allow_portrait=allow_portrait)


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
    orientation: str = "horizontal",
) -> dict[str, Any]:
    """PRIMER PASO DE TODO PLANO: dibuja el cajón (marco de la hoja con sus
    márgenes) y el cuadro de rotulación con los datos de la obra, y devuelve el
    área útil donde va el dibujo. Llamala ANTES que cualquier otra tool de
    dibujo, y después ubicá todo adentro del 'drawArea' que devuelve.

    sheet_format: A0, A1, A2, A3 o A4. Para un formato a medida pasá width_mm
    y height_mm.
    orientation: 'horizontal' (apaisado, el default) o 'vertical'. Si venís de
    fit_sheet, pasale el valor que devolvió — si no, la hoja sale acostada y el
    dibujo se te va a salir por arriba.
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
        orientation=orientation,
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
    min_segment: float = 0.40,
    draw_symbols: bool = True,
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
    vez de dibujar algo roto.

    draw_symbols: dibujar o no el símbolo de cada hueco (hoja, abatimiento,
    vidrio). Se apaga cuando la tool se usa para algo que no es un muro —una
    trabe de liga con el paso de los dados, por ejemplo, donde los "huecos" no
    son puertas.

    min_segment: avisa (en 'warning') cuando un hueco deja un tramo de muro más
    corto que esto — un machón de 30 cm entre la esquina y una puerta no se
    construye, y en el plano se ve como un rectangulito flotando. El muro se
    dibuja igual; el aviso es para corregir el proyecto."""
    return arch_mod.create_walls(
        draw_symbols=draw_symbols,
        points=points, thickness=thickness, closed=closed,
        openings=openings, layer=layer, lineweight=lineweight,
        min_segment=min_segment,
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
    min_spacing: float = 1.20,
    x_labels: str = "numbers",
    y_labels: str = "letters",
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

    min_spacing: ejes más próximos que esto se FUSIONAN en uno solo (1.20 m).
    Dos ejes a 0.65 m dan burbujas que se pisan y cotas ilegibles; en obra esos
    muros se replantean desde un mismo eje y la separación va como cota de
    detalle. Avisa en 'warning' cuáles fusionó.

    Llamala DESPUÉS de create_walls, con las coordenadas de los ejes de los
    muros portantes.
    x_labels / y_labels: 'numbers' o 'letters'. Por defecto los verticales van
    1,2,3 y los horizontales A,B,C, pero la convención no es universal: en
    mucho plano estructural las letras van en los ejes verticales. El nombre de
    cada intersección (B-2, A-1) sale de ahí, así que conviene fijarlo antes de
    rotular nada.
    """
    return arch_mod.create_axis_grid(
        x_labels=x_labels, y_labels=y_labels,
        x_positions=x_positions, y_positions=y_positions,
        x_min=x_min, y_min=y_min, x_max=x_max, y_max=y_max,
        extension=extension, bubble_radius=bubble_radius,
        text_height=text_height, layer=layer,
    )


@mcp.tool()
def create_stairs(start_x: float, start_y: float, total_rise: float,
                  width: float = 1.00, tread: float = 0.28, riser: float = 0.17,
                  direction_deg: float = 90.0, view: str = "planta",
                  handrail: bool = True, handrail_offset: float = 0.05,
                  bottom_level_label: str = "N.P.T. +0.00",
                  top_level_label: Optional[str] = None,
                  layer: str = "ESCALERAS",
                  lineweight: int = 30) -> dict[str, Any]:
    """Escalera de un tramo recto, en planta o en corte, con la cantidad de
    escalones resuelta por la fórmula de Blondel — no a ojo.

    view='planta': contorno del tramo (dos zancas), cada huella, baranda
    opcional y la flecha de sentido — rotulala vos con place_labels usando
    el punto que devuelve en 'upArrowTip' (texto "SUBE").
    view='corte': perfil en zigzag (contrahuella + huella de cada escalón)
    más los niveles de piso terminado abajo y arriba.

    total_rise: altura total a salvar (piso a piso). width: ancho libre del
    tramo. tread/riser: huella y contrahuella DESEADAS — la tool calcula
    cuántos escalones entran, recalcula la contrahuella real para que el
    reparto sea exacto, y valida contra la regla de Blondel
    (2×contrahuella + huella entre 0.60 y 0.64m): si no cumple, el error
    dice qué huella sí cumple en vez de dibujar una escalera incómoda o
    insegura.

    No arma tramos con descanso (en L o en U): un tramo recto por llamada,
    con el descanso dibujado aparte si hace falta doblar.

    Devuelve 'steps', 'riser' (la contrahuella REAL, no la pedida), 'tread',
    'totalRun', 'blondel' y 'formula' (el cálculo completo, p.ej. "17 CH x
    16.5cm = 2.80m ; 16 H x 28cm = 4.48m") para poner en el plano."""
    return arch_mod.create_stairs(
        start_x=start_x, start_y=start_y, total_rise=total_rise,
        width=width, tread=tread, riser=riser, direction_deg=direction_deg,
        view=view, handrail=handrail, handrail_offset=handrail_offset,
        bottom_level_label=bottom_level_label, top_level_label=top_level_label,
        layer=layer, lineweight=lineweight,
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
                 cap_ends: bool = True,
                 pavement_pattern: Optional[str] = None,
                 pavement_scale: float = 1.0,
                 axis_layer: str = "EJE",
                 pavement_layer: str = "PAVIMENTO",
                 curb_layer: str = "GUARNICION",
                 sidewalk_layer: str = "BANQUETA") -> dict[str, Any]:
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
    cap_ends: cerrar o no los extremos del tramo con la línea transversal. En
    un plano de infraestructura la calle SIGUE más allá del dibujo, así que ese
    remate se lee como final de obra; ahí va cap_ends=False y los bordes quedan
    abiertos. Con extremos abiertos no se puede achurar la calzada, porque el
    achurado necesita un contorno cerrado.
    pavement_pattern: rayado de la calzada, p.ej. 'AR-CONC' para concreto
    hidráulico. Sin patrón queda solo el contorno.
    axis_layer / pavement_layer / curb_layer / sidewalk_layer: en qué capa va
    cada elemento, para respetar la nomenclatura del proyecto (VIAL_EJE,
    VIAL_RODADURA...). Si la capa ya existe se usa tal cual está configurada;
    solo se crea con color y grosor propios cuando no existe.

    Devuelve el largo del eje y las cantidades de obra ya calculadas:
    pavementArea (m2), curbLength (ml de guarnición, contando los dos lados) y
    sidewalkArea — que es lo que va al resumen de obra."""
    return civil_mod.create_road(
        axis_layer=axis_layer, pavement_layer=pavement_layer,
        curb_layer=curb_layer, sidewalk_layer=sidewalk_layer,
        points=points, width=width, widths=widths, bulges=bulges,
        cap_ends=cap_ends,
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
                   offset: float = 0.0, closed: bool = False,
                   bulges: Optional[list[float]] = None) -> dict[str, Any]:
    """Dónde cae un punto ubicado por cadenamiento sobre un eje.

    distance: metros desde el arranque del eje, siguiendo las curvas.
    offset: desplazamiento perpendicular (+ es a la izquierda del sentido de
    avance). Con offset=3.5 caés justo en la guarnición de una calle de 7 m.

    bulges: OBLIGATORIO si el eje tiene curvas (los devuelve create_alignment).
    Sin ellos la distancia se mide sobre la cuerda y no sobre el arco, así que
    todo lo que ubiques después del principio de curva queda corrido.

    Sirve para ubicar un poste, un registro, el arranque de un ramal o una cota
    sin recalcular la geometría de la curva."""
    return civil_mod.point_on_road(points=points, distance=distance,
                                   offset=offset, closed=closed, bulges=bulges)


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
def place_devices(devices: list[dict[str, Any]],
                  light_layer: str = "ALUMBRADO",
                  outlet_layer: str = "CONTACTOS",
                  panel_layer: str = "CENTRO_CARGA",
                  hatch_layer: str = "",
                  lineweight: int = 25) -> dict[str, Any]:
    """Simbología eléctrica en planta: salidas, apagadores, contactos, tableros.

    Son símbolos normalizados y siempre iguales, así que NO los armes con
    create_circle + create_line: un círculo con cruz es una salida de techo en
    cualquier plano, y dibujarlo a mano cada vez es lo que hace que salga
    distinto en cada lámina.

    devices: cada uno {"type": ..., "x": .., "y": .., "angle": grados}
      - "lamp"   salida de techo: círculo de 0.30 con cruz interior.
      - "switch" apagador: círculo de 0.20 con línea radial; 'angle' apunta la
        línea hacia el ambiente.
      - "outlet" contacto: semicírculo de 0.15 apoyado en el muro; 'angle' es
        hacia dónde abre. "double": True agrega la barra del contacto doble.
      - "gfci"   contacto con falla a tierra.
      - "panel"  tablero: rectángulo de 0.40 x 0.15 con medio relleno sólido;
        'angle' lo alinea con el muro.
    Opcionales por dispositivo: "size" y "tag".

    Los tamaños son medidas REALES de obra en metros, no mm de papel.

    Devuelve el punto y la caja de cada uno: la caja es lo que necesita
    place_labels para rotularlos sin encimarse y create_conduit para saber de
    dónde sale la tubería. Cada dispositivo queda registrado como huella."""
    return elec_mod.place_devices(
        devices=devices, light_layer=light_layer, outlet_layer=outlet_layer,
        panel_layer=panel_layer, hatch_layer=hatch_layer,
        lineweight=lineweight)


@mcp.tool()
def create_conduit(points: list[list[float]], sag: float = 0.0,
                   conductors: str = "", layer: str = "TUBERIA",
                   lineweight: int = 20, mark_size: float = 0.0,
                   text_height: float = 0.0) -> dict[str, Any]:
    """Un tramo de canalización entre dispositivos, con sus conductores.

    En un plano eléctrico la tubería no va recta de aparato a aparato: se
    dibuja en arco suave para distinguirla de la muraria y para que dos
    circuitos que comparten trayecto no queden sobre la misma línea.

    points: por dónde pasa, normalmente el centro de cada dispositivo.
    sag: cuánto se arquea cada tramo respecto de la recta, como fracción de su
    largo (0.12 es un arco suave; 0 lo deja recto).
    conductors: qué va adentro, con la marca que lleva cada uno sobre el arco —
    '/' cada fase, '|' cada neutro, 'T' la tierra. '//|T' son dos fases, un
    neutro y tierra. Las marcas se dibujan sobre el tramo más largo, que es
    donde se leen."""
    return elec_mod.create_conduit(
        points=points, sag=sag, conductors=conductors, layer=layer,
        lineweight=lineweight, mark_size=mark_size, text_height=text_height)


@mcp.tool()
def create_table(x: float, y: float, rows: list[list[str]],
                  col_widths: list[float], row_height: float,
                  text_height: float, title: str = "",
                  header: bool = True, layer: str = "TABLAS",
                  avoid: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Tabla con grilla y texto: resumen de obra, cuadro de acabados,
    cuantificación, cuadro de construcción.

    (x, y) es la esquina SUPERIOR izquierda; la tabla crece hacia abajo.
    rows: las filas, con las celdas ya como texto. Con header=True la primera
    fila va centrada y separada por una línea más gruesa.
    col_widths: ancho de cada columna en unidades del modelo — define cuántas
    columnas tiene la tabla.
    row_height / text_height: en unidades del modelo. A 1:50 en metros, un
    texto de 2.5mm de papel es 0.125 y una fila cómoda es 0.35.

    Esta tool NO sabe qué más hay dibujado: (x, y) es una posición fija, así
    que si al lado va una ilustración (un detalle constructivo, una planta)
    puede terminar tapándola sin ningún aviso. Si ya sabés dónde está esa
    ilustración, pasala en avoid ([{"x0":.., "y0":.., "x1":.., "y1":..,
    "what":".."}]) y si la tabla cae encima vas a ver 'warning' en la
    respuesta en vez de descubrirlo al mirar el dibujo.

    Devuelve 'bottom' y 'right' para poder encadenar otra cosa debajo o al lado."""
    return ann_mod.create_table(x=x, y=y, rows=rows, col_widths=col_widths,
                                row_height=row_height, text_height=text_height,
                                title=title, header=header, layer=layer,
                                avoid=avoid)


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
                       layer: str = "CADENAMIENTO",
                       bulges: Optional[list[float]] = None,
                       label_offset: float = 0.0) -> dict[str, Any]:
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
    station_format: 'km' rotula 0+020.00 (carretera); 'short' rotula 0+020, sin
    decimales, que es lo que va sobre el eje cuando las marcas caen en metros
    justos; 'plain' rotula 20.00, como se marca una calle corta.
    bulges: OBLIGATORIO si el eje tiene curvas (los da create_alignment). Sin
    ellos el cadenamiento se mide sobre la cuerda y las marcas de la curva
    caen antes de donde van.
    label_offset: a qué distancia PERPENDICULAR del eje va el número. Por
    defecto queda apenas afuera de la marca, que alcanza cuando el eje va solo.
    Si sobre el eje corre algo más —un colector y su rótulo— hay que separarlo
    (p.ej. 1.50) y mandar lo otro al lado opuesto, o los textos se cruzan."""
    return ann_mod.create_stationing(
        points=points, interval=interval, text_height=text_height, tick=tick,
        start_station=start_station, closed=closed, label_every=label_every,
        station_format=station_format, layer=layer, bulges=bulges,
        label_offset=label_offset)


@mcp.tool()
def create_flow_arrow(points: list[list[float]], positions: list[float],
                      size: float = 0.0,
                      bulges: Optional[list[float]] = None,
                      closed: bool = False, reverse: bool = False,
                      layer: str = "HIDRO_RED_DRENAJE",
                      color_index: Optional[int] = None) -> dict[str, Any]:
    """Puntas de flecha SÓLIDAS sobre un eje: el sentido del escurrimiento.

    Un leader que diga "sentido del flujo" no cumple la misma función: en un
    plano de drenaje la flecha va SOBRE la tubería, repetida a lo largo del
    tramo, y se lee de un vistazo. Sin ella un colector se puede leer al revés.

    points / bulges: el eje de la tubería (o de la calle).
    positions: los cadenamientos donde va cada flecha, sobre ese eje.
    size: largo de la punta; por defecto 1/60 del eje.
    reverse: apunta contra el sentido de avance del eje."""
    return ann_mod.create_flow_arrow(
        points=points, positions=positions, size=size, bulges=bulges,
        closed=closed, reverse=reverse, layer=layer, color_index=color_index)


@mcp.tool()
def place_labels(labels: list[dict[str, Any]], height: float,
                 layer: str = "TEXTOS", gap: float = 0.0,
                 obstacles: Optional[list[list[float]]] = None,
                 lineweight: int = 18,
                 style: Optional[str] = None,
                 barriers: Optional[list[list[float]]] = None,
                 respect_walls: bool = True) -> dict[str, Any]:
    """Rotula elementos ubicando cada texto donde NO pise lo ya dibujado.

    ES LA TOOL PARA ROTULAR CUALQUIER COSA que no sea un ambiente (para eso
    está label_rooms). Usala en vez de calcular la posición del texto a mano:
    el rótulo encimado —el cadenamiento sobre la línea de eje, el dato de la
    tubería sobre el cadenamiento, la etiqueta de la zapata cruzada con la
    trabe— no es un error de cálculo, es no haber mirado lo que ya estaba.

    labels: cada uno
      {"text": "Z-2 / D-1", "box": [x0, y0, x1, y1]}  rotula al lado del elemento
      {"text": "0+020", "x": 20.0, "y": 0.0}          rotula al lado del punto
      Opcionales: "rotation" (grados) y "prefer" ('right', 'left', 'top',
      'bottom'...) para probar ese lado primero.
    gap: aire mínimo entre el texto y lo que esquiva; 0 usa medio alto de texto.
    obstacles: cajas extra a esquivar, además de los muros y muebles que las
    tools ya registraron solas.

    respect_walls: un muro separa ambientes, así que el rótulo NO se manda del
    otro lado aunque ahí haya lugar. No alcanza con que el texto no pise el
    muro: puede quedar entero del lado equivocado sin tocarlo —el rótulo del
    contacto del baño terminando adentro de la recámara— y eso se lee peor que
    si lo cruzara. Se descarta el lado cuando el segmento del elemento a su
    rótulo atraviesa un muro de los que create_walls ya registró.
    barriers: cajas extra que separan, además de esos muros.

    Cada rótulo colocado queda registrado, así que el siguiente tampoco se le
    encima. Los que no encuentren lugar salen igual —un elemento sin rotular es
    peor— y se listan en 'cramped' con un aviso."""
    return ann_mod.place_labels(
        labels=labels, height=height, layer=layer, gap=gap,
        obstacles=obstacles, lineweight=lineweight, style=style,
        barriers=barriers, respect_walls=respect_walls)


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


@mcp.tool()
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

    Un corte dibujado a mano pierde justo lo que distingue un corte de un
    esquema: qué muro está realmente cortado (banda gruesa achurada) versus
    qué se ve de fondo (línea fina), y los niveles se terminan acotando con
    el offset calculado a ojo. Esta tool resuelve las dos cosas.

    (x, y) es el extremo IZQUIERDO del corte, a la cota ±0.00 de stories[0].
    length es la extensión horizontal.

    stories: de ABAJO hacia arriba, uno por nivel:
      {"name": "PB", "height": 2.90, "slab_thickness": 0.12, "elements": [...]}
    height es piso a piso e INCLUYE el espesor de su propia losa superior:
    una azotea plana es simplemente el último nivel de la lista.

    elements por nivel, mismo estilo que 'openings' en create_walls:
      {"type": "cut_wall", "x": 0.15, "thickness": 0.15, "top": None} — un
        muro que el plano de corte SÍ atraviesa: banda achurada.
      {"type": "window", "x_start":.., "x_end":.., "sill":.., "head":..} /
      {"type": "door", "x_start":.., "x_end":.., "head":..} — aberturas del
        muro de FONDO, vistas más allá del plano de corte (el caso real: casi
        nunca se elige la línea de corte para que pase justo por un vano).
        sill/head en metros DESDE EL PISO de ese nivel, no cota absoluta.
      {"type": "seen_wall", "x_start":.., "x_end":..} — silueta de un muro
        visto de fondo, sin achurar.

    view: "corte" achura y dibuja losas; "fachada" nunca achura ni dibuja
    losas (una fachada no muestra espesores), y los cut_wall pasan a ser la
    envolvente exterior vista, no la banda cortada.

    dimension_stories: acota los niveles con la misma cadena de cotas que se
    usa en planta (create_dimension_chain), del lado dimension_side.

    Devuelve los niveles con su cota y su Y de modelo, los handles por nivel,
    y 'warning' si algún vano supera la altura libre de su nivel (se dibuja
    igual: puede ser una doble altura intencional)."""
    return sect_mod.create_building_section(
        x=x, y=y, length=length, stories=stories, view=view, datum=datum,
        dimension_stories=dimension_stories, dimension_side=dimension_side,
        level_labels=level_labels, hatch_pattern=hatch_pattern,
        hatch_scale=hatch_scale, layer_cut=layer_cut, layer_seen=layer_seen,
        text_height=text_height)


@mcp.tool()
def create_gable_roof(x: float, y: float, span: float, rise: float,
                      overhang: float = 0.0, layer: Optional[str] = None,
                      lineweight: int = roof_mod.LW_ROOF) -> dict[str, Any]:
    """Perfil de una cubierta a dos aguas (alero-cumbrera-alero), para un
    corte o una fachada -- lo que create_building_section no dibuja,
    porque ahí los niveles son horizontales y esto tiene pendiente.

    (x, y) es el apoyo IZQUIERDO (eje de columna o cara de muro), a la
    cota del alero. span es la distancia horizontal entre los dos apoyos;
    rise es la altura de la cumbrera SOBRE el alero (no cota absoluta: si
    el alero está a NPT+5.00 y la cumbrera a NPT+7.46, rise=2.46).
    overhang prolonga cada agua más allá del apoyo, en línea con la
    pendiente de esa agua -- 0 si el alero coincide con el eje de apoyo.

    Devuelve los handles de las dos aguas, el punto de cumbrera, la
    pendiente (m/m y grados) y el largo real de cada agua -- ese largo es
    el que hace falta para pedir la lámina con el desarrollo correcto, no
    la proyección horizontal del claro."""
    return roof_mod.create_gable_roof(x=x, y=y, span=span, rise=rise,
                                      overhang=overhang, layer=layer,
                                      lineweight=lineweight)


@mcp.tool()
def create_truss(x: float, y: float, span: float, rise: float,
                 panels: int = 3, layer: Optional[str] = None,
                 chord_lineweight: int = roof_mod.LW_ROOF,
                 web_lineweight: int = roof_mod.LW_TRUSS) -> dict[str, Any]:
    """Símbolo ESQUEMÁTICO de una armadura de techo a dos aguas: cuerda
    inferior horizontal, cuerda superior con pendiente y montantes
    verticales de alma -- para que un corte estructural se lea como corte
    estructural (con su "ARMADURA EST-1") y no como una cubierta sin nada
    debajo.

    Esto NO es un diseño de armadura -- no calcula fuerza por barra ni
    tamaño de perfil, es la geometría que se ve en el corte. Para la
    reacción que baja a la columna usá check_roof_truss; para verificar
    esa columna, check_column.

    (x, y) es el apoyo izquierdo, a la cota de la cuerda inferior (el
    alero). span: distancia entre apoyos. rise: altura de cumbrera sobre
    la cuerda inferior. panels: paños por CADA media armadura (3 es un
    valor de referencia razonable para una armadura chica).

    Devuelve los handles de cuerda inferior, cuerdas superiores y
    montantes, más la misma cumbrera/pendiente que create_gable_roof."""
    return roof_mod.create_truss(x=x, y=y, span=span, rise=rise,
                                 panels=panels, layer=layer,
                                 chord_lineweight=chord_lineweight,
                                 web_lineweight=web_lineweight)


@mcp.tool()
def create_column_section(x: float, y: float, width: float, depth: float,
                          bars_top_bottom: int = 0,
                          bars_left_right: int = 0,
                          bar_diameter: float = 0.0127,
                          cover: float = 0.03,
                          stirrup_diameter: float = 0.0095,
                          hatch_pattern: str = rebar_mod.DEFAULT_CONCRETE_HATCH,
                          hatch_scale: float = 1.0,
                          layer: Optional[str] = None) -> dict[str, Any]:
    """Sección de una columna/castillo de concreto en corte, con estribo y
    varillas longitudinales -- el detalle que "30x30, típico" no dibuja y
    que un corte estructural real sí muestra.

    (x, y) es la esquina inferior izquierda de la sección (cara exterior
    de concreto). width/depth: dimensiones de la sección, m -- si vienen
    de check_column, usá 'width'/'depth' de ese resultado.

    Las varillas de esquina son automáticas (las 4 esquinas del estribo).
    bars_top_bottom/bars_left_right: varillas ADICIONALES repartidas
    parejo en el interior de CADA cara horizontal/vertical (no un total,
    por cara) -- si no le pasás nada, dibuja las 4 de esquina nomás; no
    inventa una cuantía.

    bar_diameter: diámetro de la varilla longitudinal, m (0.0127 = #4).
    cover: recubrimiento libre de la cara de concreto al estribo, m.
    hatch_pattern: 'AR-CONC' (textura de concreto) por default -- si esta
    instalación no lo tiene, confirmá con list_hatch_patterns.

    Devuelve 'stirrupHandle' (la Polyline cerrada del estribo, lista para
    pasar como stirrup_handle a calculate_quantities tipo steel_weight),
    'barCount' y 'totalSteelArea_cm2' (para comparar contra lo que
    check_column pidió, no para reemplazarlo)."""
    return rebar_mod.create_column_section(
        x=x, y=y, width=width, depth=depth,
        bars_top_bottom=bars_top_bottom, bars_left_right=bars_left_right,
        bar_diameter=bar_diameter, cover=cover,
        stirrup_diameter=stirrup_diameter, hatch_pattern=hatch_pattern,
        hatch_scale=hatch_scale, layer=layer)


@mcp.tool()
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
    -- lo que create_column_section no dibuja, porque esa es una sección
    en elevación y esto es una vista en planta con una malla de varillas
    cruzadas.

    (x, y) es la esquina inferior izquierda de la zapata. width/length:
    dimensiones en planta, m -- si vienen de check_footing, width=length=
    'side' es el caso típico (zapata cuadrada), pero acepta rectangular.

    bar_spacing_x: separación de las varillas que corren en Y (repartidas
    a lo largo de X), m -- el dato de obra "varilla del #4 @ 15cm". Si
    bar_spacing_y se omite, usa el mismo paso ("doble armado en ambos
    sentidos", el caso más común).

    support_width/support_length: si se pasan (>0), dibuja el contorno de
    referencia (línea punteada) del elemento que apoya centrado encima --
    columna o dado, para leer la planta junto con el corte.

    corner_bar_leg: si se pasa (>0), agrega una varilla diagonal
    ESQUEMÁTICA en cada esquina (a 45°, ese largo de pata) -- no calcula
    gancho ni desarrollo real del doblez, esa decisión es de quien
    proyecta.

    Devuelve 'barCountX'/'barCountY' (con el paso ya ajustado para cerrar
    parejo, igual criterio que create_axis_grid) y 'totalBarLength_m',
    listo para pasar como 'length' a calculate_quantities tipo
    steel_weight -- mide la parrilla que se dibujó, no la recalcula."""
    return rebar_mod.create_footing_plan(
        x=x, y=y, width=width, length=length,
        bar_spacing_x=bar_spacing_x, bar_spacing_y=bar_spacing_y,
        bar_diameter=bar_diameter, cover=cover,
        support_width=support_width, support_length=support_length,
        corner_bar_leg=corner_bar_leg, layer=layer)


@mcp.tool()
def create_isometric_box(x: float, y: float, z: float,
                         dx: float, dy: float, dz: float,
                         layer: Optional[str] = None,
                         lineweight: int = iso_mod.LW_FACE,
                         hatch_pattern: Optional[str] = None,
                         hatch_scale: float = 1.0,
                         color_index: Optional[int] = None) -> dict[str, Any]:
    """Un prisma rectangular (columna, dado, trabe, zapata) en proyección
    ISOMÉTRICA (30° clásicos) -- las 3 caras visibles, sin geometría 3D
    real: este repo es 2D puro, esto proyecta cada vértice con
    x'=(X-Y)cos30°, y'=(X+Y)sin30°+Z y dibuja polígonos planos, el mismo
    truco de cualquier isométrico de obra dibujado en un CAD 2D.

    Para una cimentación completa (columna + dado + trabe de liga +
    zapata apilados), llamala una vez por elemento con el mismo (x, y) en
    planta y el 'z' real de arranque de cada uno -- dibujá de ABAJO hacia
    ARRIBA (zapata primero) para que el apilado se vea bien: lo que se
    dibuja último tapa a lo anterior, igual que en obra.

    (x, y, z): esquina de coordenadas MÍNIMAS del prisma, medidas reales
    (x, y en planta, z altura sobre el datum del isométrico). dx, dy, dz:
    dimensiones reales en cada eje.

    hatch_pattern: None deja solo contorno; 'SOLID' rellena de color --
    un color POR ELEMENTO es lo que hace legible un isométrico (evitá los
    puros 1-6, ver layers.EVITAR; la paleta 32/12/152/96/172 de
    layers.py ya sirve para distinguir elementos).

    Devuelve los 3 handles de cara y 'topCenter'/'frontBottomCorner' ya
    en coordenadas 2D de la lámina, para apuntar un leader con el nombre
    del elemento sin calcular la proyección a mano."""
    return iso_mod.create_isometric_box(
        x=x, y=y, z=z, dx=dx, dy=dy, dz=dz, layer=layer,
        lineweight=lineweight, hatch_pattern=hatch_pattern,
        hatch_scale=hatch_scale, color_index=color_index)


@mcp.tool()
def iso_project(x: float, y: float, z: float) -> dict[str, Any]:
    """Proyecta un punto 3D real (x, y en planta, z altura) al punto 2D de
    la lámina con la misma fórmula isométrica que create_isometric_box --
    para ubicar un leader o un texto apuntando a un punto preciso (una
    esquina, el punto medio de una arista) sin recalcular la proyección a
    mano."""
    px, py = iso_mod.iso_project(x, y, z)
    return {"x": px, "y": py}


# ---------------------------------------------------------------- Geometría

@mcp.tool()
def compose_sheet(views: list[dict[str, Any]],
                   area: list[float],
                   gutter_mm: float = 15.0,
                   title_block_mm: float = 11.0,
                   align: str = "bottom",
                   distribute: str = "center",
                   scale: Optional[float] = None,
                   draw_titles: bool = True,
                   dry_run: bool = False) -> dict[str, Any]:
    """Acomoda las vistas YA DIBUJADAS en la lámina y les pone su título.

    ES LO QUE FALTABA para que una lámina se vea compuesta y no con los
    dibujos tirados al azar. `space` evita que dos cosas se encimen;
    componer es alinear, repartir parejo y agrupar lo que se lee junto.

    El flujo: dibujá cada vista donde sea (apartadas entre sí), anotá la caja
    de cada una, y llamá esto con el `drawArea` de create_sheet.

    views: [{"name", "box": [x0,y0,x1,y1], "title"?, "scale_text"?,
             "below"?, "handles"?}]
      - box: dónde está dibujada AHORA. Sin 'handles', se seleccionan las
        entidades que caigan ENTERAS adentro de esa caja.
      - below: "corte" pone esta vista DEBAJO de esa otra y les alinea el
        centro en X. Es la alineación proyectiva — la planta bajo su corte,
        compartiendo los ejes verticales, que es como se leen una con otra.
        Las dos se acomodan como una sola unidad.

    align='bottom' deja las vistas de cada fila sobre una línea de base
    común, que es lo que hace que la lámina se vea alineada.
    distribute: 'center', 'left' o 'justify'.

    Si no entra lo dice en 'fits' y en 'warnings' — NO achica nada: una
    vista fuera de escala no es una lámina, es un error. Probá primero con
    dry_run=True y mirá el plan.

    OJO: al mover las vistas, todo lo que `space` tenía registrado deja de
    valer. Acotá y rotulá DESPUÉS de componer, no antes."""
    return compose_mod.compose_sheet(
        views=views, area=area, gutter_mm=gutter_mm,
        title_block_mm=title_block_mm, align=align, distribute=distribute,
        scale=scale, draw_titles=draw_titles, dry_run=dry_run)


@mcp.tool()
def compose_layout(name: str,
                    views: list[dict[str, Any]],
                    model_units: str = "m",
                    margin_mm: float = 15.0,
                    gutter_mm: float = 15.0,
                    title_block_mm: float = 11.0,
                    reserved_right_mm: float = 0.0,
                    padding_mm: float = 4.0,
                    align: str = "bottom",
                    distribute: str = "center",
                    plot_config: Optional[str] = None,
                    paper_size: Optional[str] = None,
                    create: bool = True,
                    locked: bool = True,
                    draw_titles: bool = True,
                    dry_run: bool = False) -> dict[str, Any]:
    """Arma una lámina en ESPACIO PAPEL: un viewport por vista, a su escala.

    ES EL FLUJO CORRECTO cuando el proyecto tiene varias láminas — que es casi
    siempre. El dibujo vive UNA sola vez en el modelo y cada layout lo recorta.
    El modelo se ve desordenado porque tiene todas las disciplinas encimadas;
    cada lámina sale limpia porque su viewport muestra solo su pedazo.

    A diferencia de compose_sheet, esto NO mueve nada del modelo: solo crea
    ventanas que lo miran.

    views: [{"name", "box": [x0,y0,x1,y1] del MODELO, "scale_denominator",
             "title"?, "scale_text"?, "below"?, "padding_mm"?}]
      - box: qué zona del modelo muestra esa vista.
      - scale_denominator: 100 para 1:100. Con eso se calcula cuánto papel
        ocupa — 16.60 m a 1:100 son 166 mm.
      - below: la apila debajo de otra alineándoles el centro en X.

    reserved_right_mm: franja derecha que NO se usa para vistas. Es donde va
    la columna fija de localización / simbología / rótulo que se repite igual
    en todas las láminas del juego.

    El tamaño de la hoja se le pregunta al dibujo, no se supone: create_layout
    elige el papel por nombre entre los del dispositivo y puede no salir el
    que tenías en la cabeza.

    OJO: crear el PRIMER layout de un dibujo puede disparar un diálogo modal
    de AutoCAD que bloquea el socket. Si se cuelga, mirá la pantalla.

    Probá con dry_run=True primero y revisá 'fits'."""
    return compose_mod.compose_layout(
        name=name, views=views, model_units=model_units,
        margin_mm=margin_mm, gutter_mm=gutter_mm,
        title_block_mm=title_block_mm, reserved_right_mm=reserved_right_mm,
        padding_mm=padding_mm, align=align, distribute=distribute,
        plot_config=plot_config, paper_size=paper_size, create=create,
        locked=locked, draw_titles=draw_titles, dry_run=dry_run)


@mcp.tool()
def move_entities(handles: list[str], dx: float, dy: float, dz: float = 0.0,
                   ignore_missing: bool = True) -> dict[str, Any]:
    """Mueve varias entidades de una pasada, todas por el mismo vector.

    Mucho más rápido que move_entity una por una: es una llamada al socket y
    una transacción, contra N y N. Acomodar una vista de detalle son fácil un
    par de cientos de entidades."""
    return acad.call("move_entities", {
        "handles": handles, "dx": dx, "dy": dy, "dz": dz,
        "ignoreMissing": ignore_missing})


@mcp.tool()
def create_level_mark(x: float, y: float, elevation: float,
                       height: float = 0.0,
                       text: Optional[str] = None,
                       prefix: str = "N.P.T.",
                       suffix: str = "",
                       side: str = "right",
                       line_length: float = 0.0,
                       style: str = "triangulo",
                       decimals: int = 2,
                       layer: str = "NIVELES",
                       lineweight: int = 18,
                       color_index: Optional[int] = None) -> dict[str, Any]:
    """Marca de nivel (N.P.T.) en un corte o una fachada.

    NO armar esto con create_text + create_line sueltos: es la falla que ya
    pasó de verdad -- dos niveles escritos a mano terminaron encimados y
    check_annotations no los vio porque nunca supo que existían.

    x, y: el punto del nivel REAL en el dibujo, no donde quede lindo el
    texto. El símbolo se apoya ahí y el texto sale al costado que diga 'side'.
    elevation: el número (5.00, -1.20, 0.0). El cero sale con ± porque es el
    nivel de referencia, no un +0.00 cualquiera.
    style: 'triangulo' (macizo, el más legible) o 'circulo'.

    Queda registrada en space, así que place_labels no le escribe encima."""
    return sym_mod.create_level_mark(
        x=x, y=y, elevation=elevation, height=height, text=text,
        prefix=prefix, suffix=suffix, side=side, line_length=line_length,
        style=style, decimals=decimals, layer=layer, lineweight=lineweight,
        color_index=color_index)


@mcp.tool()
def create_view_title(x: float, y: float, title: str,
                       scale_text: Optional[str] = None,
                       height: float = 0.0,
                       spaced: bool = True,
                       underline: bool = True,
                       align: str = "left",
                       layer: str = "TITULOS",
                       color_index: Optional[int] = 152,
                       lineweight: int = 35,
                       rule_lineweight: int = 50) -> dict[str, Any]:
    """Título de vista: nombre, subrayado grueso y escala debajo.

    TODA vista lleva el suyo. Es lo que convierte tres dibujos sueltos en una
    lámina: sin jerarquía de texto el nombre de la planta pesa lo mismo que
    una nota al pie y la lámina no se sabe leer.

    title: 'PLANTA ESTRUCTURAL DE CUBIERTA'.
    scale_text: 'ESC. 1:100', va abajo y más chico. None lo omite.
    spaced: separa las letras ('P L A N T A'), como se rotula en la mayoría
    de las oficinas. False lo deja tal cual.
    align: 'left' (x es el borde izquierdo) o 'center' (x es el centro).

    Devuelve la caja total — pasásela a create_table en 'avoid' para que un
    cuadro no le caiga encima."""
    return sym_mod.create_view_title(
        x=x, y=y, title=title, scale_text=scale_text, height=height,
        spaced=spaced, underline=underline, align=align, layer=layer,
        color_index=color_index, lineweight=lineweight,
        rule_lineweight=rule_lineweight)


@mcp.tool()
def create_section_mark(x1: float, y1: float, x2: float, y2: float,
                         label: str = "A",
                         height: float = 0.0,
                         direction: str = "left",
                         tail: float = 0.0,
                         show_line: bool = False,
                         layer: str = "MARCAS-CORTE",
                         lineweight: int = 50,
                         color_index: Optional[int] = None) -> dict[str, Any]:
    """Marca de corte: lo único que liga una planta con su sección.

    Una planta y un corte sin esto son dos dibujos sueltos — nada dice de
    dónde se sacó el corte ni hacia dónde se mira, que es la mitad de la
    información. Va en la planta, apuntando a la vista que le corresponde.

    x1,y1 -> x2,y2: por dónde pasa el plano de corte. Se dibujan los DOS
    extremos (cola gruesa + flecha + globo con la letra) y el tramo del medio
    se omite, que es como se dibuja sobre una planta con contenido.
    direction: 'left' o 'right' respecto del sentido 1->2, hacia dónde mira.
    show_line: True traza además la línea de corte completa.

    La capa es MARCAS-CORTE y no CORTES, que ya la usa create_layer_section."""
    return sym_mod.create_section_mark(
        x1=x1, y1=y1, x2=x2, y2=y2, label=label, height=height,
        direction=direction, tail=tail, show_line=show_line, layer=layer,
        lineweight=lineweight, color_index=color_index)


@mcp.tool()
def set_dim_style_family(scales: Optional[list[float]] = None,
                          model_units: str = "m",
                          paper_mm: float = 2.0,
                          arrow_paper_mm: float = 2.0,
                          prefix: str = "COTAS",
                          decimals: int = 2,
                          text_style: Optional[str] = None,
                          current_scale: Optional[float] = None
                          ) -> dict[str, Any]:
    """Crea un estilo de cota POR ESCALA, con nombre, dentro del dibujo.

    create_dimension_chain resuelve la altura al vuelo y funciona, pero no
    deja nada en el DWG: quien reciba el archivo y siga acotando no tiene con
    qué seguir la misma convención, y la segunda tanda sale de otro tamaño.

    Esto deja COTAS25/COTAS50/COTAS100/COTAS150 armados, cada uno con la
    altura de texto igual a los mismos mm de papel por su escala. Dibujando
    en metros con paper_mm=2.0: COTAS50 -> 0.10, COTAS100 -> 0.20.

    Llamalo UNA vez al empezar el dibujo, después pasá style='COTAS50' a
    create_dimension. paper_mm=2.0 es lo usual en obra; ISO admite 2.5."""
    return ann_mod.set_dim_style_family(
        scales=scales, model_units=model_units, paper_mm=paper_mm,
        arrow_paper_mm=arrow_paper_mm, prefix=prefix, decimals=decimals,
        text_style=text_style, current_scale=current_scale)


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
    resultado = acad.call("create_text", {
        "text": text, "x": x, "y": y, "z": z, "height": height,
        "layer": layer, "rotationDeg": rotation_deg, "style": style,
        **_style(lineweight, color_index),
    })
    _track_text(text, x, y, height, rotation_deg)
    return resultado


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
    resultado = acad.call("create_mtext", {
        "text": text, "x": x, "y": y, "z": z, "height": height, "width": width,
        "layer": layer, "style": style, **_style(lineweight, color_index),
    })
    _track_text(text, x, y, height, width=width)
    return resultado


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
def create_dimension_chain(side: str, reference: float,
                           positions: Optional[list[float]] = None,
                           segments: Optional[list[list[float]]] = None,
                           offset: float = 0.0, total: bool = False,
                           scale: float = 0.0,
                           style: Optional[str] = None,
                           layer: str = "COTAS",
                           lineweight: int = 13) -> dict[str, Any]:
    """Una CORRIDA de cotas seguidas sobre un lado del dibujo. Es la forma
    normal de acotar una planta: no cota por cota calculando el offset a mano,
    sino cadenas —los huecos, los ejes, el total— cada una en su nivel.

    El offset se resuelve SOLO: la cadena se apila afuera de lo que ya haya en
    ese lado, incluidas las burbujas de eje. Es lo que evita el choque clásico
    de la cota general cruzando los globos, que ningún offset fijo esquiva
    porque la burbuja se mueve con el tamaño del plano.

    positions: los cortes a lo largo del lado (x para 'bottom'/'top', y para
    'left'/'right'); sale una cota entre cada par consecutivo.
    segments: en vez de una corrida seguida, los tramos sueltos que van en esa
    MISMA línea de cota: [[3.65, 5.15], [-3.50, 3.50], [-5.15, -3.65]]. Es como
    se acota una sección tipo —banqueta, calzada, banqueta— salteando lo que a
    esa escala no se puede acotar. Con tres llamadas sueltas saldrían tres
    líneas de cota distintas, que es justo lo que no se quiere.
    side: bottom | top | left | right.
    reference: la coordenada del borde del dibujo desde donde se mide (la y del
    paño inferior para 'bottom', la x del izquierdo para 'left').
    offset: 0 = calculado. Ponerlo a mano solo si hay una razón.
    total: agrega, un nivel más afuera, la cota general de punta a punta.
    scale: DIMSCALE, unidades del modelo por mm de papel. 0 toma la de la
    lámina que create_sheet registró — que es lo correcto casi siempre.

    Avisa si un tramo queda tan corto que el número no entra entre las flechas."""
    return ann_mod.create_dimension_chain(
        positions=positions, segments=segments,
        side=side, reference=reference, offset=offset,
        total=total, scale=scale, style=style, layer=layer,
        lineweight=lineweight)


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
    arrow_size: Optional[float] = None,
    layer: Optional[str] = None,
    lineweight: Optional[int] = None, color_index: Optional[int] = None,
) -> dict[str, Any]:
    """Crea una línea de referencia con flecha + texto (callout), típica para
    señalar un detalle. 'points' es la polilínea de la flecha (al menos 2 puntos);
    el texto arranca en el último punto.

    arrow_size: tamaño de la flecha en unidades del modelo. Sin esto, toma el
    de set_dim_style (el DIMSTYLE activo), para que coincida con las cotas del
    mismo plano; si no hay ninguno configurado, cae a text_height * 0.6.
    lineweight: grosor de la flecha y el texto en centésimas de mm (13-18 es lo
    habitual). color_index: color ACI 1-255."""
    resultado = acad.call("create_leader", {
        "points": points, "text": text, "textHeight": text_height,
        "arrowSize": arrow_size, "layer": layer,
        **_style(lineweight, color_index),
    })
    if points:
        _track_text(text, points[-1][0], points[-1][1], text_height)
    return resultado


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


@mcp.tool()
def list_hatch_patterns(filter: Optional[str] = None) -> dict[str, Any]:
    """Patrones de achurado que existen DE VERDAD en el acad.pat/acadiso.pat
    de esta instalación de AutoCAD.

    Llamala ANTES de pasarle un nombre de patrón a create_hatch o create_legend
    que no sea 'SOLID', 'ANSI31' o 'AR-CONC' (esos tres son casi universales).
    El resto (texturas de piedra, ladrillo, techo...) varían de una instalación
    a otra, y create_hatch no avisa si el nombre está mal hasta que ya intentó
    dibujar — es mejor confirmar el nombre real que adivinar y reintentar.

    filter: substring para acotar la lista (p.ej. "AR-" o "BRICK"), sin
    importar mayúsculas. Sin esto devuelve TODOS los patrones (pueden ser 70+)."""
    return acad.call("list_hatch_patterns", {"filter": filter})


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
    con set_display_options(lineweight_display=True).

    QUÉ COLOR ELEGIR. Los índices 1 a 7 son los colores puros, pensados para la
    pantalla negra del modelo, y en un plano hay que evitar casi todos — por
    razones opuestas:
      - 2 amarillo, 4 cian, 3 verde: muy claros, se lavan al imprimir sobre
        papel blanco. El cian y el amarillo son los peores.
      - 5 azul: al revés — imprime bien, pero es tan oscuro que no se lee
        sobre el fondo del espacio modelo.
      - 7 (blanco/negro) y 8 (gris) son los únicos dos que se comportan igual
        en pantalla y en papel: son la base de cualquier plano.
    Del 10 al 249 están los tonos por matiz al 65% o 50% de intensidad, que se
    leen bien en los dos medios. Equivalencias recomendadas:
      ejes 32 (ámbar) · cotas 12 (rojo oscuro) · hidráulica 152 (azul acero) ·
      vegetación/guarniciones 96 (verde oliva) · registros 172 (violeta) ·
      achurados 8 o 253 (grises)
    Si la lámina se traza en MONOCROMO con un .ctb —lo habitual en obra— el
    color solo define el grosor y no afecta la impresión; igual conviene
    elegirlo bien porque el dibujo se trabaja en pantalla."""
    resultado = acad.call("set_layer", {
        "name": name, "colorIndex": color_index, "linetype": linetype,
        "lineweightHundredthsMm": lineweight_hundredths_mm,
    })
    # La capa se crea igual —el color lo elige quien dibuja— pero un indice
    # desaconsejado se avisa en el momento y no cuando el plano ya salio de
    # la impresora.
    motivo = layers_mod.EVITAR.get(color_index)
    if motivo:
        resultado["warning"] = (
            f"Capa '{name}' con colorIndex {color_index}: {motivo}. "
            "Se creo igual; ver la tabla de equivalencias en la descripcion "
            "de esta tool.")
    return resultado


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
                   side_x: Optional[float] = None, side_y: Optional[float] = None,
                   layer: Optional[str] = None, lineweight: Optional[int] = None,
                   color_index: Optional[int] = None) -> dict[str, Any]:
    """Crea una curva paralela a otra (Line, Arc, Circle o Polyline) a una
    distancia dada — típico para trazar una guarnición paralela al eje de una
    calle. side_x/side_y es un punto de referencia opcional para elegir de qué
    lado queda el offset cuando hay ambigüedad.

    layer: sin esto, la curva nueva hereda la capa de la original — pasalo
    cuando el offset represente otra cosa (la guarnición de un eje, por
    ejemplo) y tenga que ir a su propia capa."""
    return acad.call("offset_entity", {
        "handle": handle, "distance": distance, "sideX": side_x, "sideY": side_y,
        "layer": layer, **_style(lineweight, color_index),
    })


@mcp.tool()
def mirror_entity(handle: str, x1: float, y1: float, x2: float, y2: float,
                  copy: bool = True) -> dict[str, Any]:
    """Espeja una entidad respecto del eje que pasa por (x1,y1)-(x2,y2).

    copy=True (default) deja el original y agrega el reflejo como entidad
    nueva — lo normal para una planta simétrica (dos recámaras en espejo,
    una unidad dupla). copy=False transforma la entidad en el lugar, sin
    dejar el original.

    Es un espejo geométrico real: un texto espejado sale invertido (mismo
    criterio que MIRRTEXT=1 de AutoCAD), no "legible del otro lado". Si lo
    que hace falta es un rótulo legible en la posición reflejada, escribilo
    de nuevo con create_text en vez de espejar el existente."""
    return acad.call("mirror_entity", {
        "handle": handle, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "copy": copy,
    })


@mcp.tool()
def array_entity(handle: str, mode: str = "rectangular",
                 rows: int = 1, cols: int = 1,
                 row_spacing: float = 0.0, col_spacing: float = 0.0,
                 center_x: Optional[float] = None, center_y: Optional[float] = None,
                 count: Optional[int] = None, angle_total: float = 360.0,
                 rotate_items: bool = True) -> dict[str, Any]:
    """Arreglo rectangular o polar de una entidad ya dibujada: copias reales,
    cada una con su propio handle — no un objeto Array asociativo.

    mode='rectangular': rows x cols copias, separadas row_spacing/col_spacing
    (unidades del modelo). Sirve para una fila de columnas o ventanas.
    mode='polar': count copias repartidas alrededor de (center_x, center_y).
    angle_total=360 (default) reparte el círculo completo a partes iguales;
    un ángulo menor reparte ese arco entre count-1 tramos, así el último
    elemento cae justo en angle_total. rotate_items=False traslada cada
    copia al punto del arco sin girarla (para un símbolo que tiene que
    quedar siempre "parado", tipo columna).

    El original ya cuenta como la primera pieza: rows x cols o count es el
    TOTAL resultante, original incluido — no se duplica la posición [0,0]."""
    params: dict[str, Any] = {"handle": handle, "mode": mode}
    if mode == "rectangular":
        params.update({"rows": rows, "cols": cols,
                       "rowSpacing": row_spacing, "colSpacing": col_spacing})
    elif mode == "polar":
        if center_x is None or center_y is None or count is None:
            raise ValueError(
                "mode='polar' necesita center_x, center_y y count.")
        params.update({"centerX": center_x, "centerY": center_y, "count": count,
                       "angleTotal": angle_total, "rotateItems": rotate_items})
    else:
        raise ValueError(f"mode tiene que ser 'rectangular' o 'polar', no {mode!r}.")
    return acad.call("array_entity", params)


@mcp.tool()
def attach_xref(path: str, name: str, x: float, y: float, z: float = 0.0,
                scale: float = 1.0, rotation_deg: float = 0.0,
                layer: Optional[str] = None, lineweight: Optional[int] = None,
                color_index: Optional[int] = None) -> dict[str, Any]:
    """Adjunta OTRO dibujo como referencia externa (xref) — para coordinar
    disciplinas separadas (arquitectura, estructura, instalaciones) como
    archivos vinculados, en vez de copiar geometría con insert_block.

    La diferencia real con insert_block: un xref se puede recargar
    (reload_xref) cuando el archivo de origen cambia — un bloque importado
    queda congelado en el momento en que se insertó.

    path: ruta al .dwg de origen. name: cómo se lo referencia en este
    dibujo (list_xrefs, detach_xref, reload_xref lo usan)."""
    return acad.call("attach_xref", {
        "path": path, "name": name, "x": x, "y": y, "z": z, "scale": scale,
        "rotationDeg": rotation_deg, "layer": layer,
        **_style(lineweight, color_index),
    })


@mcp.tool()
def list_xrefs() -> dict[str, Any]:
    """Lista las referencias externas adjuntas a este dibujo, con su ruta y
    estado (Resolved, Unresolved, FileNotFound, Unloaded)."""
    return acad.call("list_xrefs", {})


@mcp.tool()
def detach_xref(name: str) -> dict[str, Any]:
    """Desprende un xref — borra la referencia Y todas sus inserciones en
    este dibujo. Para sacar geometría de otra disciplina sin que quede
    colgada, en vez de borrar la inserción a mano y dejar la definición
    huérfana."""
    return acad.call("detach_xref", {"name": name})


@mcp.tool()
def reload_xref(name: Optional[str] = None) -> dict[str, Any]:
    """Recarga un xref desde el archivo de origen (o todos, si se omite
    'name') — para traer los cambios que el otro consultor hizo en su
    disciplina sin tener que volver a adjuntar nada."""
    return acad.call("reload_xref", {"name": name})


@mcp.tool()
def find_replace_text(find: str, replace: str,
                      case_sensitive: bool = False) -> dict[str, Any]:
    """Busca y reemplaza texto en TODO el espacio activo: DBText, MText y
    atributos de bloque. Para corregir un dato repetido (un número de lámina,
    un nombre mal escrito) de una sola pasada, en vez de rótulo por rótulo.

    Devuelve 'changed': qué entidades tocó (handle, tipo, y el tag si era un
    atributo), para poder revisar qué cambió."""
    return acad.call("find_replace_text", {
        "find": find, "replace": replace, "caseSensitive": case_sensitive,
    })


# --------------------------------------------------------------- Consulta

@mcp.tool()
def list_entities(entity_type: Optional[str] = None, limit: int = 200) -> dict[str, Any]:
    """Lista entidades del espacio ACTIVO (el modelo, o el layout de papel si
    hay uno abierto con set_current_layout) (handle, tipo, capa).
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
def calculate_quantities(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Cuantifica materiales a partir de lo YA DIBUJADO, no de números de memoria.

    Un cuadro de cuantificación hecho a mano repite el error que esta
    biblioteca ya resolvió para áreas y rótulos: alguien calcula aparte y el
    número que pone en la tabla no es necesariamente el que mide el plano.
    Acá el área sale de calculate_area sobre los handles reales — nada se
    inventa salvo el acero, que el dibujo no puede mostrar a escala (una
    varilla en corte es un círculo esquemático de 1cm), así que ahí se toma
    la especificación que ya quedó anotada en el plano.

    No es un catálogo cerrado de materiales — son operaciones geométricas
    genéricas (área×profundidad, perímetro×longitud, módulo de pieza+merma)
    que sirven para cualquier concepto del proyecto, no solo los que
    aparecen de ejemplo acá.

    items: lista de conceptos, cada uno con 'type' y 'label':
      "concrete_volume": {"handles": [...], "depth": 0.15, "waste_pct": 5.0}
        — mide el área de cada handle y la multiplica por 'depth' (la
        profundidad que ESA vista no muestra, p.ej. el espesor hacia
        adentro del muro en una elevación); 'waste_pct' (default 0) es el
        desperdicio real de colado.
      "concrete_mix": {"handles": [...], "depth": 0.15} o, si el volumen
        ya se calculó en un item de concrete_volume, {"volume": 1.61} en
        vez de remedirlo — más "cement_bags_per_m3"/"sand_m3_per_m3"/
        "gravel_m3_per_m3" (default 7.5, 0.50, 0.80: referencia de obra
        para f'c≈200 kg/cm² ~1:2:3, reemplazable por el diseño de mezcla
        real del proyecto). Bolsas de cemento (50kg, redondeadas hacia
        arriba), arena y grava en m³ para colar ese volumen.
      "brick_count": {"handles": [...], "brick_w": 0.28, "brick_h": 0.07,
        "joint": 0.015, "waste_pct": 5.0} — piezas = área medida / módulo
        pieza+junta, con la merma.
      "mortar_volume": {"handles": [...], "thickness": 0.14, "brick_w":..,
        "brick_h":.., "brick_depth":.., "joint":.., "waste_pct": 5.0} —
        mortero = volumen del muro menos el volumen real que ocupan las
        piezas, más 'waste_pct' de sobrante de mezcla.
      "steel_weight": longitudinal + estribos + malla, sumables en el mismo
        item: {"count": 3, "length": 2.5, "long_bars": 4,
        "long_bar_size": "#3", "commercial_length": 9.0,
        "lap_diam_factor": 40, "stirrup_size": "#2", "stirrup_spacing": 0.15,
        "stirrup_handle": "466", "waste_pct": 5.0} — peso de varilla
        longitudinal + estribos; stirrup_handle mide el PERÍMETRO REAL del
        estribo ya dibujado (closed Polyline) en vez de recalcularlo a
        mano. 'commercial_length'+'lap_diam_factor' suman el traslape real
        cuando 'length' supera el largo comercial de la varilla. Para malla
        electrosoldada de losa: {"handles": [...], "mesh_kg_m2": 2.86,
        "waste_pct": 3.0} — kg = área medida × peso de catálogo de la malla.
      "earthwork": excavación —
        {"mode": "excavation", "handles": [...], "depth": 0.60,
        "swell_pct": 25.0} — volumen = área medida × depth;
        'swell_pct' (esponjamiento al sacarlo del banco) solo informa
        'volumeSwollen' para acarreo. Relleno —
        {"mode": "backfill", "handles": [...], "depth": 0.60,
        "structure_volume": 0.42} — volumen = (área medida × depth) menos
        el volumen YA calculado de la estructura que ocupa el mismo hueco.
      "formwork": cimbra/encofrado — cara ya dibujada directo:
        {"handles": [...], "faces": 1, "waste_pct": 5.0}; o por sección de
        elemento: {"count": 3, "length": 2.5, "section_handle": "h1",
        "waste_pct": 5.0} — área = count × perímetro MEDIDO de la sección
        × length, mismo criterio que el perímetro del estribo.
      "area_finish": acabados por área (aplanados, piso, pintura,
        impermeabilizante, lo que sea del proyecto) —
        {"material": "aplanado", "handles": [...], "coats": 1,
        "thickness": 0.015, "waste_pct": 5.0} — 'material' es texto libre y
        agrupa el total (aplanado_m2, pintura_m2, etc.); 'coats' (manos)
        escala el área a cubrir; 'thickness' opcional agrega el volumen.

    Devuelve 'items' (una fila resuelta por concepto, con el detalle de cómo
    se midió) y 'totals' (sumado por material: concreto_m3, ladrillo_piezas,
    mortero_m3, acero_kg, excavacion_m3, relleno_m3, cimbra_m2, y un
    <material>_m2/<material>_m3 por cada 'material' de area_finish). Pasale
    el resultado a create_quantities_table para dibujarlo."""
    return qty_mod.calculate_quantities(items)


@mcp.tool()
def create_quantities_table(x: float, y: float, result: dict[str, Any],
                            text_height: float,
                            title: str = "CUANTIFICACIÓN DE OBRA (MEDIDA DEL PLANO)",
                            layer: str = "TABLAS",
                            col_widths: Optional[list[float]] = None) -> dict[str, Any]:
    """Dibuja el resultado de calculate_quantities como tabla.

    No recalcula nada: toma 'result' tal cual lo devolvió calculate_quantities
    y lo tabula, con una columna que muestra CÓMO se llegó a cada número
    (área medida, módulo, fórmula) y no solo el resultado final — así quien
    lee la lámina puede verificar la cuenta sin abrir el DWG.

    col_widths: [concepto, medición], en unidades del modelo. Por defecto
    [5.5, 17.0] — la columna de medición trae la operación completa (cada
    área sumada, el módulo desglosado, el kg/m usado), así que sale ancha.
    Si algún texto no entra, el resultado avisa en 'warning' cuánto necesita."""
    return qty_mod.create_quantities_table(
        x=x, y=y, result=result, text_height=text_height, title=title,
        layer=layer, col_widths=col_widths)


@mcp.tool()
def export_quantities_csv(result: dict[str, Any], path: str) -> dict[str, Any]:
    """Vuelca el resultado de calculate_quantities a un .csv real en disco,
    para armar el presupuesto en Excel/Sheets afuera de AutoCAD.

    No recalcula nada — escribe los mismos números que ya devolvió
    calculate_quantities, uno por fila con su fórmula (columna 'MEDICIÓN Y
    CÁLCULO') y su cantidad ya en la unidad correspondiente, más las filas de
    'totals' al final. No necesita AutoCAD conectado: es un volcado del
    resultado en memoria.

    path: ruta absoluta de salida, p.ej. "C:/obra/cuantificacion.csv"."""
    return qty_mod.export_quantities_csv(result=result, path=path)


@mcp.tool()
def get_drawing_info() -> dict[str, Any]:
    """Info general del dibujo activo: nombre de archivo, unidades, capa actual,
    cantidad de entidades en el espacio modelo."""
    return acad.call("get_drawing_info", {})


# ------------------------------------------------------- Vista / visualización

@mcp.tool()
def set_display_options(lineweight_display: Optional[bool] = None,
                         default_lineweight_hundredths_mm: Optional[int] = None,
                         linetype_scale: Optional[float] = None) -> dict[str, Any]:
    """Controla si los grosores de línea se VEN en pantalla (LWDISPLAY) y cuál es
    el grosor por defecto del dibujo (LWDEFAULT, en centésimas de mm).

    Es la causa #1 de que un plano se vea "todo con trazos finos": AutoCAD trae
    LWDISPLAY apagado de fábrica y la variable se guarda por dibujo, así que un
    DWG viejo la puede traer apagada aunque el plugin la prenda al cargarse.

    linetype_scale (LTSCALE): cada cuánto se repite el patrón de un tipo de
    línea. Dibujando en METROS con el valor 1 por defecto, un eje con linetype
    CENTER se ve CONTINUO, porque el patrón es más largo que el propio eje. Un
    valor razonable en metros es 0.3 a 0.5; en milímetros, 20 a 50.

    Regenera la vista al terminar."""
    return acad.call("set_display_options", {
        "lineweightDisplay": lineweight_display,
        "defaultLineweightHundredthsMm": default_lineweight_hundredths_mm,
        "linetypeScale": linetype_scale,
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
    Alcanza con el nombre de archivo ('Casa.dwg'), sin la ruta completa.

    Al cambiar de dibujo se olvida lo cacheado del anterior (huellas de
    mobiliario, franjas de anotación ocupadas, capas existentes): son datos
    de ESE plano y no valen acá. Revisá los 'warnings' que devuelve."""
    r = acad.call("set_active_document", {"name": name})
    if r.get("changed"):
        avisos = _reset_drawing_state(r.get("active", name))
        if avisos:
            r = dict(r)
            r["warnings"] = avisos
    return r


@mcp.tool()
def open_document(path: str, read_only: bool = False) -> dict[str, Any]:
    """Abre un .dwg del disco y lo deja activo.

    Es la entrada para CORREGIR un plano ya entregado: hasta acá el MCP sabía
    guardar, plotear y exportar, pero el dibujo tenía que estar abierto a mano
    en AutoCAD. Con esto el ciclo cierra solo: open_document →
    select_entities → delete_entities → redibujar → save_drawing.

    Si el archivo ya está abierto en AutoCAD no lo reabre (perdería los
    cambios sin guardar): activa el que hay y lo avisa en 'alreadyOpen'.

    read_only=True para consultar un plano de otro consultor sin riesgo de
    pisarlo. Para vincular su geometría a ESTE dibujo no es el camino: eso es
    attach_xref.

    Olvida lo cacheado del dibujo anterior — ver los 'warnings'."""
    r = acad.call("open_document", {"path": path, "readOnly": read_only})
    avisos = _reset_drawing_state(r.get("active", path))
    if avisos:
        r = dict(r)
        r["warnings"] = avisos
    return r


@mcp.tool()
def new_document(template: Optional[str] = None) -> dict[str, Any]:
    """Crea un dibujo nuevo y lo deja activo.

    template: ruta a un .dwt propio (el de la oficina, con sus capas y
    estilos ya armados). Sin él sale la plantilla por defecto de AutoCAD.

    El dibujo nace sin nombre y vive SOLO en memoria: `save_drawing(path=...)`
    con ruta explícita antes de dibujar nada serio — ver la nota de
    save_drawing sobre dónde termina el archivo si no se le pasa path.

    Olvida lo cacheado del dibujo anterior — ver los 'warnings'."""
    r = acad.call("new_document", {"template": template})
    avisos = _reset_drawing_state(r.get("active", "dibujo nuevo"))
    if avisos:
        r = dict(r)
        r["warnings"] = avisos
    return r


@mcp.tool()
def close_document(name: Optional[str] = None, save: bool = False,
                    discard_unsaved: bool = False) -> dict[str, Any]:
    """Cierra un dibujo abierto. Sin 'name', el activo.

    Descartar es EXPLÍCITO: sin `save=True` ni `discard_unsaved=True` se
    niega y lo dice, porque tirar cambios sin guardar no es algo que deba
    hacer una tool por su cuenta.

    Se niega también a cerrar el último dibujo abierto — AutoCAD no puede
    quedarse sin ninguno.

    Después de cerrar, el estado cacheado del dibujo anterior se olvida."""
    r = acad.call("close_document", {"name": name, "save": save,
                                     "discardUnsaved": discard_unsaved})
    avisos = _reset_drawing_state(r.get("active", "?"))
    if avisos:
        r = dict(r)
        r["warnings"] = avisos
    return r


@mcp.tool()
def select_entities(x1: Optional[float] = None, y1: Optional[float] = None,
                     x2: Optional[float] = None, y2: Optional[float] = None,
                     layers: Optional[list[str]] = None,
                     types: Optional[list[str]] = None,
                     mode: str = "inside") -> dict[str, Any]:
    """Qué hay dentro de una zona, capa o tipo. Devuelve los handles.

    ES LA BASE PARA CORREGIR SIN REHACER. Si el cliente pide reacomodar una
    recámara, se selecciona lo que hay en ese rectángulo, se borra con
    delete_entities y se vuelve a dibujar SOLO eso — en vez de tirar el plano
    entero y empezar de cero.

    x1,y1,x2,y2: rectángulo de selección; sin ellos, todo el espacio ACTIVO
    (el modelo, o el layout de papel si hay uno abierto con set_current_layout).
    layers / types: filtros adicionales ('Line', 'Polyline', 'DBText'...).
    mode: 'inside' toma solo lo que entra ENTERO en el rectángulo (lo seguro,
    es el default); 'crossing' toma también lo que lo cruza — útil para agarrar
    los muros que limitan el ambiente, pero se lleva puestos los vecinos."""
    return acad.call("select_entities", {
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "layers": layers, "types": types, "mode": mode,
    })


@mcp.tool()
def delete_entities(handles: list[str],
                     ignore_missing: bool = True) -> dict[str, Any]:
    """Borra varias entidades de una sola pasada.

    Mucho más rápido que llamar delete_entity una por una: son N llamadas al
    socket contra una sola. Los handles que ya no existen se ignoran por
    defecto, porque al limpiar es normal que algo se haya borrado en cascada."""
    return acad.call("delete_entities", {
        "handles": handles, "ignoreMissing": ignore_missing,
    })


@mcp.tool()
def union_regions(handles: list[str],
                   delete_sources: bool = True) -> dict[str, Any]:
    """Fusiona contornos cerrados en uno solo (unión booleana).

    Es lo que limpia los encuentros de muros. Cada tramo se dibuja como un
    contorno cerrado propio, así que donde dos muros se cruzan quedan las
    líneas de ambos atravesando la unión: se ve un cajón en el cruce en vez de
    una T o una esquina limpia. Uniendo las regiones, esas líneas interiores
    desaparecen y queda el perímetro real de la mampostería.

    handles: polilíneas CERRADAS (las que devuelve create_walls en
    'wallHandles'). Los contornos que no se tocan quedan separados sin error.

    Devuelve el área y el perímetro reales de la mampostería, que sirven para
    cuantificar. Ojo: el resultado es una Region, no una polilínea, así que ya
    no se le pueden agregar vértices — conviene hacerlo al final."""
    return acad.call("union_regions", {
        "handles": handles, "deleteSources": delete_sources,
    })


@mcp.tool()
def get_extents(layers: Optional[list[str]] = None,
                 exclude_layers: Optional[list[str]] = None) -> dict[str, Any]:
    """Cuánto ocupa lo que ya está dibujado en el espacio ACTIVO (el modelo, o
    el layout de papel si hay uno abierto con set_current_layout), en unidades
    del modelo.

    Permite invertir el orden de trabajo: en vez de poner el cajón primero y
    confiar en que el dibujo entre, se dibuja, se mide y recién entonces se
    encuadra. Si el dibujo crece, el marco se adapta.

    layers: considerar solo esas capas. exclude_layers: dejar afuera otras —
    útil para excluir CAJON y ROTULO al reencuadrar una lámina existente.

    Devuelve minX/minY/maxX/maxY, ancho, alto y centro. Si no hay nada,
    'isEmpty' es True."""
    return acad.call("get_extents", {
        "layers": layers, "excludeLayers": exclude_layers,
    })


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


@mcp.tool()
def export_pdf(layout: str, path: str, device: Optional[str] = None) -> dict[str, Any]:
    """Plotea un layout a un archivo por API — sin tener que ir a AutoCAD y
    hacer PLOT a mano.

    layout: nombre del layout a plotear (el que armaste con create_layout).
    path: ruta absoluta de salida, p.ej. "C:/obra/casa_planta.pdf".
    device: dispositivo de impresión (.pc3). Por default "DWG To PDF.pc3" —
    el mismo que create_layout deja configurado si no le pasaste otro, así
    que en el caso normal ni hace falta pasarlo. Si el layout se armó con un
    plotter físico, pasá ese device o el PDF sale con el papel/escala de la
    impresora en vez de un tamaño de archivo razonable.

    Se plotea con la configuración YA guardada en el layout (papel, escala):
    no vuelve a calcular nada, solo manda a imprimir lo que create_layout +
    create_viewport ya dejaron armado."""
    return acad.call("export_pdf", {"layout": layout, "path": path, "device": device})


@mcp.tool()
def capture_viewport(path: str, layout: Optional[str] = None) -> dict[str, Any]:
    """Saca una imagen PNG de lo que hay dibujado, para poder MIRAR el
    resultado en vez de confiar solo en los números que devuelven las demás
    tools (get_extents, list_entities, los check_*).

    layout: qué capturar. Si se omite, captura el espacio ACTIVO (modelo o el
    layout que esté actual) — mismo criterio que usan las demás tools de
    inspección. Pasando un nombre, captura ese layout puntual sin cambiar cuál
    está activo.

    Si es el espacio modelo, encuadra a la extensión del dibujo (equivalente
    a un zoom_extents antes de la foto); si es un layout, captura la hoja
    completa tal como quedaría al imprimir.

    No sirve para nada 3D ni para depurar colores de pantalla — es una foto
    plana de lo que hay, pensada para chequear que nada se encimó o quedó
    fuera de lugar antes de dar un plano por terminado."""
    return acad.call("capture_viewport", {"path": path, "layout": layout})


@mcp.tool()
def undo(steps: int = 1) -> dict[str, Any]:
    """Deshace las últimas 'steps' operaciones del dibujo activo.

    Cada llamada de este MCP que modifica el dibujo queda como una operación
    de UNDO normal de AutoCAD, así que sirve para deshacer una serie de
    tool calls que salió mal sin tener que borrar entidad por entidad con
    delete_entity/delete_entities.

    Se encola en la línea de comandos (igual que zoom_extents), así que no
    devuelve confirmación de qué se deshizo — si hace falta verificar,
    segui con get_drawing_info o list_entities después."""
    if steps < 1:
        raise ValueError("steps tiene que ser >= 1.")
    return acad.call("undo", {"steps": steps})


if __name__ == "__main__":
    mcp.run()
