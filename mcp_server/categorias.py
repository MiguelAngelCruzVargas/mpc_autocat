"""Categorías de las tools, a la manera de AutoCAD, y flujos de trabajo por tipo de proyecto.

Un MCP con 260+ herramientas es un cajón revuelto: quien lo usa (una persona o una IA) pierde turnos buscando
cuál va. AutoCAD resolvió esto con la CINTA (pestaña > panel > comando: Dibujo, Modificar, Anotación, Capas,
Bloque...), y las suites de especialidad (Architecture, Civil 3D) con sus propios grupos. Acá cada tool está
en UNA categoría y declara qué comandos de AutoCAD cubre; con eso se genera el mapa de cobertura contra la
cinta real (`tools/cobertura_cinta.py`) y la tool `list_tool_categories`.

Dos familias de categorías:
  - las GENÉRICAS, con el nombre del panel de la cinta de AutoCAD (Dibujo 2D, Modificar, Anotación, Capas...);
  - las de PROYECTO, por tipo de trabajo (Arquitectura/casa, Estructura, Instalaciones, Civil y vial, Detalles
    constructivos, 3D de presentación, Cierre y entrega).

`FLUJOS` dice, por tipo de trabajo, qué tools van y en qué orden («qué se requiere para hacer una casa»).
Regla: una tool nueva SE AGREGA ACÁ (test_categorias.py falla si hay una tool sin categoría o una categoría
con una tool que ya no existe).
"""
from __future__ import annotations

from typing import Optional

# ------------------------------------------------------------------ categorías

GENERICAS = {
    "dibujo": "Dibujo 2D (panel Dibujo de la cinta)",
    "modificar": "Modificar y editar (panel Modificar)",
    "anotacion": "Anotación: texto, cotas, directrices, tablas (pestaña Anotar)",
    "capas": "Capas, estados de capa y estilos de visualización (panel Capas)",
    "bloques": "Bloques, atributos, grupos y datos propios (panels Bloque y Grupos)",
    "propiedades": "Propiedades, métodos y consulta de objetos (panel Propiedades, QSELECT)",
    "utilidades": "Utilidades: medir, calcular áreas y cuantificar (panel Utilidades)",
    "vista": "Vista y dibujos abiertos (pestaña Vista)",
    "modelado3d": "Modelado 3D: sólidos, booleanas, extrusión (pestaña Sólido)",
    "layouts": "Láminas, layouts, viewports e impresión (pestañas Presentación y Salida)",
    "xref": "Referencias externas e imágenes (pestaña Insertar)",
    "sistema": "Sistema, archivo, variables y diagnóstico (pestaña Administrar)",
}
PROYECTO = {
    "p_arq": "Proyecto — Arquitectura: de la distribución a la planta de una casa",
    "p_est": "Proyecto — Estructura: cargas, diseño y plantas estructurales",
    "p_inst": "Proyecto — Instalaciones: eléctrica, hidráulica, sanitaria",
    "p_civil": "Proyecto — Civil, vial y terreno",
    "p_det": "Proyecto — Detalles constructivos y armado",
    "p_3d": "Proyecto — 3D de presentación",
    "p_entrega": "Proyecto — Cierre, verificación y entrega",
}
CATEGORIAS = {**GENERICAS, **PROYECTO}

# nombre de tool -> (categoría, "COMANDOS DE AUTOCAD QUE CUBRE")
_T: dict[str, tuple[str, str]] = {}


def _r(cat: str, tools: str, cmds: str = "") -> None:
    """Registra varias tools (separadas por espacios) en una categoría. `cmds` solo con UNA tool."""
    nombres = tools.split()
    for n in nombres:
        _T[n] = (cat, cmds if len(nombres) == 1 else "")


# ---- dibujo 2D
_r("dibujo", "create_line", "LINE")
_r("dibujo", "create_polyline", "PLINE")
_r("dibujo", "create_circle", "CIRCLE")
_r("dibujo", "create_arc", "ARC")
_r("dibujo", "create_rectangle", "RECTANG")
_r("dibujo", "create_polygon", "POLYGON")
_r("dibujo", "create_ellipse", "ELLIPSE")
_r("dibujo", "create_spline", "SPLINE")
_r("dibujo", "create_construction_line", "XLINE RAY")
_r("dibujo", "create_point", "POINT")
_r("dibujo", "create_hatch", "HATCH GRADIENT")
_r("dibujo", "list_hatch_patterns")
_r("dibujo", "create_wipeout", "WIPEOUT")
_r("dibujo", "create_boundary", "BOUNDARY")
_r("dibujo", "divide_curve", "DIVIDE MEASURE")
_r("dibujo", "union_regions", "REGION UNION")
_r("dibujo", "create_object", "")          # cualquier entidad por reflexión (HELIX, 3DPOLY, WIPEOUT, DONUT...)
_r("dibujo", "arch_geometry create_arch create_arched_opening create_break_line create_crenellation create_facade_column "
              "create_balustrade create_lattice_panel create_steps create_isometric_box")
_r("dibujo", "create_parking_stalls create_car_symbol create_ramp_track create_ramp_arc")
_r("dibujo", "vectorize_image")

# ---- modificar
_r("modificar", "move_entity", "MOVE")
_r("modificar", "move_entities", "MOVE")
_r("modificar", "copy_entity", "COPY")
_r("modificar", "rotate_entity", "ROTATE")
_r("modificar", "scale_entity", "SCALE")
_r("modificar", "mirror_entity", "MIRROR")
_r("modificar", "offset_entity", "OFFSET")
_r("modificar", "array_entity", "ARRAYRECT ARRAYPOLAR ARRAYPATH")
_r("modificar", "trim_entity", "TRIM")
_r("modificar", "extend_entity", "EXTEND")
_r("modificar", "fillet_entities", "FILLET")
_r("modificar", "join_entities", "JOIN")
_r("modificar", "overkill_entities", "OVERKILL")
_r("modificar", "explode_entities", "EXPLODE")
_r("modificar", "break_curve", "BREAK BREAKATPOINT")
_r("modificar", "match_properties", "MATCHPROP")
_r("modificar", "chamfer_entities", "CHAMFER")
_r("modificar", "stretch_entities", "STRETCH")
_r("modificar", "lengthen_curve", "LENGTHEN")
_r("modificar", "align_entities", "ALIGN")
_r("modificar", "add_geometric_constraint", "GCHORIZONTAL GCVERTICAL GCPARALLEL GCPERPENDICULAR GCCOLLINEAR GCCOINCIDENT GCCONCENTRIC GCTANGENT GCEQUAL GCFIX")
_r("modificar", "add_dimensional_constraint", "DCALIGNED DCHORIZONTAL DCVERTICAL DCANGULAR DCLINEAR")
_r("modificar", "set_constraint_value list_constraints remove_constraints")
_r("modificar", "radius_constraint", "DCRADIUS DCDIAMETER")
_r("modificar", "delete_entity", "ERASE")
_r("modificar", "delete_entities", "ERASE")
_r("modificar", "undo", "UNDO")
_r("modificar", "find_replace_text", "FIND")
_r("modificar", "native_status")

# ---- anotación
_r("anotacion", "create_text", "TEXT")
_r("anotacion", "create_mtext", "MTEXT")
_r("anotacion", "create_leader", "MLEADER")
_r("anotacion", "create_table", "TABLE")
_r("anotacion", "create_dimension", "DIMALIGNED DIMLINEAR")
_r("anotacion", "create_dimension_rotated", "DIMLINEAR")
_r("anotacion", "create_dimension_angular", "DIMANGULAR")
_r("anotacion", "create_dimension_arc_length", "DIMARC")
_r("anotacion", "create_dimension_diametric", "DIMDIAMETER")
_r("anotacion", "create_dimension_radial", "DIMRADIUS")
_r("anotacion", "create_dimension_chain", "DIMCONTINUE DIMBASELINE")
_r("anotacion", "set_text_style", "STYLE")
_r("anotacion", "set_dim_style", "DIMSTYLE")
_r("anotacion", "set_dim_style_family")
_r("anotacion", "measure_text")
_r("anotacion", "place_labels create_legend create_callouts create_view_title create_level_mark create_section_mark create_north")
_r("anotacion", "list_annotation_scales add_annotation_scale set_current_annotation_scale remove_annotation_scale", "")
_r("anotacion", "list_styles")

# ---- capas
_r("capas", "set_layer", "LAYER")
_r("capas", "list_layers", "LAYER")
_r("capas", "merge_layers", "LAYMRG")
_r("capas", "delete_layer_with_objects", "LAYDEL")
_r("capas", "isolate_layers", "LAYISO LAYOFF LAYLCK")
_r("capas", "unisolate_layers", "LAYUNISO")
_r("capas", "save_layer_state restore_layer_state list_layer_states delete_layer_state", "")
_r("capas", "set_viewport_layers", "LAYVPI VPLAYER")
_r("capas", "set_current", "LAYMCUR LAYCUR")
_r("capas", "set_display_options")
_r("capas", "purge_database_objects", "PURGE")
_r("capas", "create_database_object delete_database_object")
_r("capas", "purge_block")

# ---- bloques, atributos y grupos
_r("bloques", "define_block", "BLOCK")
_r("bloques", "insert_block", "INSERT")
_r("bloques", "export_block", "WBLOCK")
_r("bloques", "get_block_attributes", "EATTEDIT")
_r("bloques", "set_block_attributes", "-ATTEDIT BATTMAN")
_r("bloques", "get_dynamic_block_properties set_dynamic_block_properties")
_r("bloques", "create_group", "GROUP")
_r("bloques", "delete_group", "UNGROUP")
_r("bloques", "modify_group", "GROUPEDIT")
_r("bloques", "get_xdata set_xdata clear_xdata get_custom_data set_custom_data delete_custom_data")

# ---- propiedades y consulta
_r("propiedades", "get_object_properties set_object_properties list_object_properties", "")
_r("propiedades", "list_object_methods call_object_method")
_r("propiedades", "get_entity")
_r("propiedades", "list_entities")
_r("propiedades", "select_entities", "SELECT")
_r("propiedades", "query_entities", "QSELECT")
_r("propiedades", "aggregate_entities describe_entity_fields")
_r("propiedades", "list_children")

# ---- utilidades
_r("utilidades", "calculate_area", "AREA MEASUREGEOM")
_r("utilidades", "calculate_properties", "MASSPROP")
_r("utilidades", "get_extents", "")
_r("utilidades", "calculate_quantities create_quantities_table export_quantities_csv export_concept_catalog")

# ---- vista y documentos
_r("vista", "zoom_extents", "ZOOM")
_r("vista", "zoom_window", "ZOOM")
_r("vista", "capture_viewport")
_r("vista", "live_drawing")
_r("vista", "list_documents set_active_document new_document open_document close_document", "")

# ---- modelado 3D
_r("modelado3d", "extrude_solid", "EXTRUDE")
_r("modelado3d", "revolve_solid", "REVOLVE")
_r("modelado3d", "sweep_solid", "SWEEP")
_r("modelado3d", "loft_solid", "LOFT")
_r("modelado3d", "solid_boolean", "UNION SUBTRACT INTERSECT")
_r("modelado3d", "fillet_solid_edges", "FILLETEDGE")
_r("modelado3d", "extrude_profile", "EXTRUDE")
_r("modelado3d", "set_3d_view", "3DORBIT")
_r("modelado3d", "iso_project")
_r("modelado3d", "create_surface", "PLANESURF RULESURF REVSURF TABSURF")
_r("modelado3d", "offset_surface", "SURFOFFSET")
_r("modelado3d", "create_nurb_surface")
_r("modelado3d", "create_mesh_from_faces")
_r("modelado3d", "create_mesh", "MESH")
_r("modelado3d", "mesh_smooth", "MESHSMOOTHMORE MESHSMOOTHLESS MESHREFINE MESHSMOOTH")
_r("modelado3d", "convert_mesh", "CONVTOSOLID CONVTOSURFACE")

# ---- láminas e impresión
_r("layouts", "create_layout", "LAYOUT")
_r("layouts", "list_layouts set_current_layout delete_layout rename_layout copy_layout", "")
_r("layouts", "create_viewport", "MVIEW")
_r("layouts", "configure_layout list_plot_options", "PAGESETUP")
_r("layouts", "export_pdf", "EXPORTPDF PLOT")
_r("layouts", "compose_layout compose_sheet")
_r("layouts", "create_sheet sheet_origin fit_sheet")

# ---- referencias externas
_r("xref", "attach_xref", "XATTACH")
_r("xref", "detach_xref", "XREF")
_r("xref", "reload_xref", "XREF")
_r("xref", "bind_xref", "XBIND")
_r("xref", "unload_xref", "XREF")
_r("xref", "list_xrefs")
_r("xref", "attach_image", "IMAGEATTACH")
_r("xref", "attach_pdf_underlay", "ATTACH PDFATTACH")

# ---- sistema y diagnóstico
_r("sistema", "save_drawing", "SAVE QSAVE")
_r("sistema", "export_copy", "SAVEAS EXPORT")
_r("sistema", "get_drawing_info")
_r("sistema", "get_drawing_properties set_drawing_properties", "DWGPROPS")
_r("sistema", "get_system_variables set_system_variable get_editor_state ping diagnose_autocad")
_r("sistema", "describe_api api_guide run_code")
_r("sistema", "get_normative")
_r("sistema", "list_tool_categories")

# ---- proyecto: arquitectura
_r("p_arq", "check_program suggest_layout check_layout check_geometry check_walls draw_layout create_wall_network create_walls")
_r("p_arq", "suggest_furniture place_furniture label_rooms dimension_layout create_stairs create_castillos create_axis_grid")
_r("p_arq", "create_building_section create_gable_roof create_truss")
_r("p_arq", "check_building_project check_drawing_set")

# ---- proyecto: estructura
_r("p_est", "design_frame_structure draw_structural_set design_two_way_slab panel_edge_loads continuous_beam design_beam design_footing")
_r("p_est", "design_lintel draw_lintel_detail draw_foundation_plan draw_framing_plan draw_footing_detail create_footing_plan create_footing_section")
_r("p_est", "check_footing check_column check_slab_span check_retaining_wall check_roof_truss check_bridge_girder check_masonry_arch")
_r("p_est", "design_pool")

# ---- proyecto: instalaciones
_r("p_inst", "suggest_electrical suggest_hydraulic suggest_sanitary place_devices create_conduit create_installation_legend")

# ---- proyecto: civil y terreno
_r("p_civil", "create_alignment create_road create_profile create_cross_sections create_stationing point_on_road grade_elevation")
_r("p_civil", "create_intersection create_flow_arrow create_layer_section create_construction_table traverse create_coordinate_grid")

# ---- proyecto: detalles constructivos
_r("p_det", "create_material_section create_stone_fill create_soil_section create_rebar create_rebar_dots create_rebar_elevation")
_r("p_det", "create_column_section create_construction_joint")

# ---- proyecto: 3D de presentación
_r("p_3d", "create_3d_model dress_3d_model create_phone_3d")

# ---- proyecto: cierre y entrega
_r("p_entrega", "check_all check_sheet check_annotations check_view_titles check_drawing_hygiene check_office_standard")
_r("p_entrega", "package_deliverables")


# ------------------------------------------------------------------ flujos de trabajo por tipo de proyecto

FLUJOS: dict[str, dict] = {
    "casa": {
        "titulo": "Una casa (vivienda entre medianeras)",
        "pasos": [
            ("Datos", "get_normative (país) y los datos de la obra: preguntarlos UNA vez (nombre, ubicación, propietario, quién dibuja)."),
            ("Guardar", "save_drawing(path=...) con nombre propio ANTES de dibujar."),
            ("Terreno", "traverse / create_construction_table (si hay cuadro de construcción); create_north."),
            ("Programa", "check_program: ¿el programa entra en el terreno? Si no, decirlo con el número."),
            ("Distribución", "suggest_layout → check_layout → check_geometry (ya validada)."),
            ("Muros", "draw_layout (o create_wall_network) → check_walls."),
            ("Mobiliario", "suggest_furniture → place_furniture → label_rooms."),
            ("Ejes y cotas", "create_axis_grid, dimension_layout / create_dimension_chain."),
            ("Estructura", "ver el flujo «estructura»."),
            ("Instalaciones", "ver el flujo «instalaciones»."),
            ("Cortes y fachadas", "create_building_section, create_level_mark, create_section_mark."),
            ("Cuantificación", "calculate_quantities → create_quantities_table → export_concept_catalog."),
            ("Láminas", "compose_layout (una por lámina, con su rótulo)."),
            ("Cierre", "check_all → export_pdf → save_drawing → package_deliverables."),
        ],
    },
    "estructura": {
        "titulo": "Estructura de marcos de concreto",
        "pasos": [
            ("Datos del proyecto", "capacidad del suelo (E.M.S.), f'c, desplante, cargas: SON DEL PROYECTO, se preguntan."),
            ("Todo en dos llamadas", "design_frame_structure → draw_structural_set."),
            ("O paso a paso", "design_two_way_slab → panel_edge_loads → continuous_beam → design_beam → design_footing."),
            ("Dibujo", "draw_foundation_plan, draw_framing_plan, draw_footing_detail, draw_lintel_detail."),
            ("Revisión previa", "check_footing, check_column, check_slab_span (antes de dibujar)."),
            ("Armado", "create_column_section, create_rebar_elevation, create_rebar."),
            ("Cuantificación", "calculate_quantities (acero, concreto, cimbra) → create_quantities_table."),
        ],
    },
    "instalaciones": {
        "titulo": "Instalaciones de la vivienda",
        "pasos": [
            ("Base", "draw_layout + suggest_furniture ya dibujados (las instalaciones se montan sobre eso)."),
            ("Eléctrica", "suggest_electrical (NOM-001-SEDE-2012)."),
            ("Hidráulica", "suggest_hydraulic."),
            ("Sanitaria", "suggest_sanitary."),
            ("Simbología", "create_installation_legend (si no se dibujó sola)."),
            ("Una pestaña", "corregir = borrar las capas de instalaciones y redibujar en el MISMO dibujo."),
        ],
    },
    "vial": {
        "titulo": "Obra vial y terreno",
        "pasos": [
            ("Eje", "create_alignment (devuelve points Y bulges: se usan los dos siempre)."),
            ("Calle", "create_road, create_intersection, create_stationing, create_flow_arrow."),
            ("Perfil y secciones", "create_profile, grade_elevation, create_cross_sections, create_layer_section."),
            ("Terreno", "traverse → create_construction_table; create_coordinate_grid; create_north."),
            ("Cuantificación", "calculate_quantities (movimiento de tierras, pavimento)."),
        ],
    },
    "3d": {
        "titulo": "Modelo 3D",
        "pasos": [
            ("De la planta", "create_3d_model → dress_3d_model → set_3d_view (isolate_3d=False antes de guardar)."),
            ("Pieza suelta", "create_object('Solid3d', init_method='CreateBox'...), extrude_solid / revolve_solid / sweep_solid / loft_solid."),
            ("Combinar", "solid_boolean (union, subtract, intersect), fillet_solid_edges."),
            ("Medir", "call_object_method(handle, 'MassProperties') da el volumen REAL."),
            ("Mirar", "capture_viewport no sirve en perspectiva: traer AutoCAD al frente y tomar la pantalla."),
        ],
    },
    "laminas": {
        "titulo": "Láminas y entrega (cualquier proyecto)",
        "pasos": [
            ("Un layout por lámina", "compose_layout(name, views=[...], sheet={...}); nunca dibujar el cajón sobre el plano."),
            ("Capas por viewport", "set_viewport_layers: cada lámina muestra su disciplina desde un único modelo."),
            ("Verificar", "check_all (incluye check_sheet, check_annotations, xrefs)."),
            ("Salida", "export_pdf por lámina → save_drawing → package_deliverables."),
        ],
    },
}


# ------------------------------------------------------------------ consulta

def categoria_de(tool: str) -> Optional[str]:
    return _T.get(tool, (None, ""))[0]


def comandos_de(tool: str) -> list[str]:
    return _T.get(tool, (None, ""))[1].split()


def tools_en(cat: str) -> list[str]:
    return sorted(n for n, (c, _) in _T.items() if c == cat)


def todas() -> dict[str, tuple[str, str]]:
    return dict(_T)


def comando_a_tools() -> dict[str, list[str]]:
    """Comando de AutoCAD -> tools que lo cubren."""
    m: dict[str, list[str]] = {}
    for n, (_, cmds) in _T.items():
        for c in cmds.split():
            m.setdefault(c.upper(), []).append(n)
    return m
