# Cobertura de este MCP contra la cinta de AutoCAD

Generado por `python tools/cobertura_cinta.py` (cinta real de AutoCAD 2027 × `mcp_server/categorias.py`). No se edita a mano: se corrige `categorias.py` o este script.

**360 comandos distintos en la cinta.** 159 con tool propia, 56 alcanzables hoy con las tools genéricas (reflexión), 67 que solo tienen sentido con una persona frente a la pantalla, 24 fuera de alcance (render, geolocalización, nubes de puntos), 53 candidatos a implementar y 1 sin clasificar. De los 269 que tienen sentido automatizar, 215 están cubiertos (79 %).

Leyenda: ✔ tool propia · ◐ por reflexión (`create_object`, `call_object_method`, `set_object_properties`) · ○ solo interfaz · ▫ fuera de alcance · ✖ pendiente · ? sin clasificar

## Anotar

- **Texto**: ✔ MTEXT → `create_mtext` · ✔ TEXT → `create_text` · ○ SPELL · ◐ TEXTALIGN → `set_object_properties` · ◐ JUSTIFYTEXT → `set_object_properties` · ✔ SCALETEXT → `scale_entity`
- **Cotas**: ✔ DIM → `create_dimension` · ◐ DIMBREAK → `call_object_method` · ✔ DIMSPACE → `create_dimension_chain` · ◐ DIMJOGLINE → `call_object_method` · ◐ DIMINSPECT → `create_object` · ✔ -DIMSTYLE → `set_dim_style` · ◐ DIMREASSOCIATE → `call_object_method` · ✔ DIMLINEAR → `create_dimension, create_dimension_rotated` · ✔ DIMALIGNED → `create_dimension` · ✔ DIMANGULAR → `create_dimension_angular` · ✔ DIMARC → `create_dimension_arc_length` · ✔ DIMRADIUS → `create_dimension_radial` · ✔ DIMDIAMETER → `create_dimension_diametric` · ✔ DIMJOGGED → `create_dimension` · ✔ DIMORDINATE → `create_dimension` · ✔ QDIM → `create_dimension_chain` · ✔ DIMCONTINUE → `create_dimension_chain` · ✔ DIMBASELINE → `create_dimension_chain` · ◐ TOLERANCE → `create_object` · ✔ DIMEDIT → `set_dim_style` · ◐ DIMTEDIT → `set_object_properties` · ✔ DIMOVERRIDE → `set_dim_style`
- **Líneas de centro**: ◐ CENTERMARK → `create_object` · ◐ CENTERLINE → `create_object`
- **Directrices**: ✔ MLEADER → `create_leader` · ◐ MLEADERALIGN → `call_object_method` · ◐ MLEADERCOLLECT → `call_object_method` · ✖ AIMLEADEREDITADD · ✖ AIMLEADEREDITREMOVE
- **Tablas**: ✔ TABLE → `create_table` · ✖ DATALINKUPDATE · ✔ DATAEXTRACTION → `calculate_quantities` · ✖ DATALINK
- **Marca de revisión**: ✔ WIPEOUT → `create_wipeout` · ◐ REVCLOUD → `create_object`
- **Escala de anotación**: ✔ AIOBJECTSCALEADD → `add_annotation_scale` · ✔ AIOBJECTSCALEREMOVE → `remove_annotation_scale` · ✔ SCALELISTEDIT → `add_annotation_scale` · ✔ OBJECTSCALE → `set_current_annotation_scale` · ◐ ANNORESET → `call_object_method`

## Inicio

- **Dibujo**: ✔ LINE → `create_line` · ✔ PLINE → `create_polyline` · ✔ CIRCLE → `create_circle` · ✔ ARC → `create_arc` · ✔ RECTANG → `create_rectangle` · ✔ POLYGON → `create_polygon` · ✔ ELLIPSE → `create_ellipse` · ✔ HATCH → `create_hatch` · ✔ GRADIENT → `create_hatch` · ✔ BOUNDARY → `create_boundary` · ✔ SPLINE → `create_spline` · ✔ XLINE → `create_construction_line` · ✔ RAY → `create_construction_line` · ✔ POINT → `create_point` · ✔ DIVIDE → `divide_curve` · ✔ MEASURE → `divide_curve` · ✔ REGION → `union_regions` · ✔ WIPEOUT → `create_wipeout` · ◐ 3DPOLY → `create_object` · ◐ HELIX → `create_object` · ◐ DONUT → `create_object` · ◐ REVCLOUD → `create_object`
- **Modificar**: ✔ TRIM → `trim_entity` · ✔ EXTEND → `extend_entity` · ✔ FILLET → `fillet_entities` · ✔ CHAMFER → `chamfer_entities` · ✖ BLEND · ✔ ARRAYRECT → `array_entity` · ✔ ARRAYPATH → `array_entity` · ✔ ARRAYPOLAR → `array_entity` · ✔ ERASE → `delete_entities, delete_entity` · ✔ EXPLODE → `explode_entities` · ✔ OFFSET → `offset_entity` · ◐ SETBYLAYER → `set_object_properties` · ◐ CHSPACE → `set_object_properties` · ✔ LENGTHEN → `lengthen_curve` · ◐ PEDIT → `set_object_properties` · ◐ SPLINEDIT → `set_object_properties` · ◐ HATCHEDIT → `set_object_properties` · ◐ ARRAYEDIT → `call_object_method` · ✔ ALIGN → `align_entities` · ✔ BREAK → `break_curve` · ✔ BREAKATPOINT → `break_curve` · ✔ JOIN → `join_entities` · ◐ REVERSE → `call_object_method` · ✔ NCOPY → `copy_entity` · ✔ OVERKILL → `overkill_entities` · ◐ AI_DRAWORDER → `call_object_method` · ◐ TEXTTOFRONT → `call_object_method` · ◐ HATCHTOBACK → `call_object_method` · ◐ MIRROR3D → `call_object_method` · ◐ 3DMOVE → `call_object_method` · ◐ 3DALIGN → `call_object_method` · ◐ 3DROTATE → `call_object_method` · ◐ 3DSCALE → `call_object_method` · ✔ 3DARRAY → `array_entity` · ✔ ARRAY → `array_entity`
- **Anotación**: ✔ MTEXT → `create_mtext` · ✔ TEXT → `create_text` · ✔ DIM → `create_dimension` · ✔ DIMLINEAR → `create_dimension, create_dimension_rotated` · ✔ DIMALIGNED → `create_dimension` · ✔ DIMANGULAR → `create_dimension_angular` · ✔ DIMARC → `create_dimension_arc_length` · ✔ DIMRADIUS → `create_dimension_radial` · ✔ DIMDIAMETER → `create_dimension_diametric` · ✔ DIMORDINATE → `create_dimension` · ✔ DIMJOGGED → `create_dimension` · ✔ MLEADER → `create_leader` · ✖ AIMLEADEREDITADD · ✖ AIMLEADEREDITREMOVE · ◐ MLEADERALIGN → `call_object_method` · ◐ MLEADERCOLLECT → `call_object_method` · ✔ TABLE → `create_table` · ✔ STYLE → `set_text_style` · ✔ DIMSTYLE → `set_dim_style` · ✔ MLEADERSTYLE → `create_database_object` · ✔ TABLESTYLE → `create_database_object`
- **Capas**: ✔ LAYOFF → `isolate_layers` · ✔ LAYISO → `isolate_layers` · ✔ LAYFRZ → `set_layer` · ✔ LAYLCK → `isolate_layers` · ✔ LAYMCUR → `set_current` · ✔ LAYON → `set_layer` · ✔ LAYUNISO → `unisolate_layers` · ✔ LAYTHW → `set_layer` · ✔ LAYULK → `set_layer` · ✔ LAYMCH → `match_properties` · ✔ LAYERP → `undo` · ✔ LAYCUR → `set_current` · ◐ COPYTOLAYER → `set_object_properties` · ✔ LAYWALK → `list_layers` · ✔ LAYVPI → `set_viewport_layers` · ✔ LAYMRG → `merge_layers` · ✔ LAYDEL → `delete_layer_with_objects`
- **Bloque**: ✖ BDETECT · ◐ BSEARCH → `list_children` · ✔ BLOCK → `define_block` · ✔ BEDIT → `define_block` · ✔ EATTEDIT → `get_block_attributes` · ✔ -ATTEDIT → `set_block_attributes` · ✔ BREPLACE → `insert_block` · ◐ ATTDEF → `create_object` · ✔ BATTMAN → `set_block_attributes` · ✖ ATTSYNC · ◐ BASE → `set_system_variable`
- **Propiedades**: ✔ MATCHPROP → `match_properties` · ◐ LIST → `get_object_properties`
- **Grupos**: ✔ GROUP → `create_group` · ✔ UNGROUP → `delete_group` · ✔ GROUPEDIT → `modify_group` · ○ CLASSICGROUP
- **Utilidades**: ✔ MEASUREGEOM → `calculate_area` · ✔ QSELECT → `query_entities` · ✔ AI_SELALL → `select_entities` · ◐ ID → `get_object_properties` · ◐ PTYPE → `set_system_variable`
- **Portapapeles**: ○ PASTECLIP · ○ PASTEBLOCK · ○ PASTEASHYPERLINK · ○ PASTEORIG · ○ PASTESPEC · ○ CUTCLIP · ○ CUTBASE · ○ COPYCLIP · ○ COPYBASE
- **Modelado**: ◐ BOX → `create_object` · ◐ CYLINDER → `create_object` · ◐ CONE → `create_object` · ◐ SPHERE → `create_object` · ◐ PYRAMID → `create_object` · ◐ WEDGE → `create_object` · ◐ TORUS → `create_object` · ✔ EXTRUDE → `extrude_profile, extrude_solid` · ✔ LOFT → `loft_solid` · ✔ REVOLVE → `revolve_solid` · ✔ SWEEP → `sweep_solid` · ◐ POLYSOLID → `create_object` · ◐ PRESSPULL → `call_object_method` · ✖ SOLVIEW · ✖ SOLDRAW · ✖ SOLPROF
- **Malla**: ✔ MESHSMOOTH → `mesh_smooth` · ✔ MESHSMOOTHMORE → `mesh_smooth` · ✔ MESHSMOOTHLESS → `mesh_smooth` · ✔ MESHREFINE → `mesh_smooth`
- **Editar sólidos**: ✔ UNION → `solid_boolean, union_regions` · ◐ INTERFERE → `call_object_method` · ✔ SUBTRACT → `solid_boolean` · ◐ SLICE → `call_object_method` · ✔ INTERSECT → `solid_boolean` · ◐ THICKEN → `call_object_method` · ◐ XEDGES → `call_object_method` · ◐ IMPRINT → `call_object_method` · ✔ SOLIDEDIT → `edit_solid_faces` · ✔ CONVTOSOLID → `convert_mesh` · ✔ CONVTOSURFACE → `convert_mesh`
- **Sección**: ◐ SECTIONPLANE → `create_object` · ○ LIVESECTION · ✖ SECTIONPLANEJOG · ✖ SECTIONPLANETOBLOCK · ✖ FLATSHOT · ◐ XEDGES → `call_object_method`
- **Coordenadas**: ◐ UCSICON → `set_system_variable` · ✔ UCS → `create_database_object`
- **Vista**: ○ -VPORTS · ○ AI_EMPTYPRINC
- **Crear**: ◐ BOX → `create_object` · ◐ CYLINDER → `create_object` · ◐ CONE → `create_object` · ◐ SPHERE → `create_object` · ◐ PYRAMID → `create_object` · ◐ WEDGE → `create_object` · ◐ TORUS → `create_object` · ◐ POLYSOLID → `create_object` · ✔ EXTRUDE → `extrude_profile, extrude_solid` · ✔ REVOLVE → `revolve_solid` · ✔ LOFT → `loft_solid` · ✔ SWEEP → `sweep_solid` · ✖ SURFNETWORK · ✔ PLANESURF → `create_surface` · ✖ SURFBLEND · ✖ SURFPATCH · ✔ SURFOFFSET → `offset_surface` · ✖ SURFSCULPT · ✔ MESH → `create_mesh` · ✖ EDGE · ✖ EDGESURF · ✔ RULESURF → `create_surface` · ✔ TABSURF → `create_surface`
- **Editar**: ◐ PRESSPULL → `call_object_method` · ✔ UNION → `solid_boolean, union_regions` · ✔ SUBTRACT → `solid_boolean` · ✔ INTERSECT → `solid_boolean` · ✔ FILLETEDGE → `fillet_solid_edges` · ✔ CHAMFEREDGE → `chamfer_solid_edges` · ◐ XEDGES → `call_object_method` · ◐ SLICE → `call_object_method` · ◐ THICKEN → `call_object_method` · ✔ SOLIDEDIT → `edit_solid_faces` · ◐ INTERFERE → `call_object_method` · ✔ SURFFILLET → `fillet_surfaces` · ✔ SURFTRIM → `trim_surface` · ✖ SURFUNTRIM · ✔ SURFEXTEND → `extend_surface` · ✔ MESHSMOOTH → `mesh_smooth` · ✔ MESHSMOOTHMORE → `mesh_smooth` · ✔ MESHSMOOTHLESS → `mesh_smooth` · ✔ MESHREFINE → `mesh_smooth` · ✔ MESHCREASE → `edit_mesh_faces` · ✖ MESHUNCREASE

## Inserción

- **Referencia**: ✔ ATTACH → `attach_pdf_underlay` · ✖ CLIP · ✖ ADJUST · ○ ULAYERS
- **Bloque**: ✖ BDETECT · ◐ BSEARCH → `list_children` · ✔ EATTEDIT → `get_block_attributes` · ✔ -ATTEDIT → `set_block_attributes` · ✔ BREPLACE → `insert_block`
- **Definición de bloque**: ✔ BLOCK → `define_block` · ✔ WBLOCK → `export_block` · ◐ ATTDEF → `create_object` · ✔ BATTMAN → `set_block_attributes` · ✔ BEDIT → `define_block` · ◐ BASE → `set_system_variable` · ✖ ATTSYNC
- **Importar**: ✖ PDFIMPORT · ▫ PDFSHXTEXT · ▫ PDFSHXTEXTSETTINGS
- **Datos**: ✖ FIELD · ✖ UPDATEFIELD · ▫ INSERTOBJ · ▫ HYPERLINK
- **Vinculación y extracción**: ✖ DATALINK · ✖ DATALINKUPDATE · ✔ DATAEXTRACTION → `calculate_quantities`
- **Ubicación**: ▫ GEOGRAPHICLOCATION

## Administrar

- **Personalización**: ○ CUI · ○ AI_EDITCUSTFILE
- **Aplicaciones**: ○ APPLOAD · ○ SCRIPT · ○ VBAIDE · ○ VLIDE · ○ VBARUN · ○ VBALOAD · ○ VBAMAN
- **Normas de CAD**: ✖ LAYTRANS · ✔ CHECKSTANDARDS → `check_office_standard` · ✔ STANDARDS → `check_office_standard`
- **Limpieza**: ○ AUDIT · ✔ OVERKILL → `overkill_entities`
- **Rendimiento**: ○ PERFANALYZER

## Malla

- **Primitivas**: ✔ MESH → `create_mesh` · ✔ REVSURF → `create_surface` · ✖ EDGESURF · ✔ RULESURF → `create_surface` · ✔ TABSURF → `create_surface`
- **Malla**: ✔ MESHSMOOTH → `mesh_smooth` · ✔ MESHSMOOTHMORE → `mesh_smooth` · ✔ MESHSMOOTHLESS → `mesh_smooth` · ✔ MESHREFINE → `mesh_smooth` · ✔ MESHCREASE → `edit_mesh_faces` · ✖ MESHUNCREASE
- **Editar malla**: ✔ MESHEXTRUDE → `edit_mesh_faces` · ✔ MESHSPLIT → `edit_mesh_faces` · ✔ MESHMERGE → `edit_mesh_faces` · ✔ MESHCAP → `edit_mesh_faces` · ✔ MESHCOLLAPSE → `edit_mesh_faces` · ✔ MESHSPIN → `edit_mesh_faces`
- **Convertir malla**: ✔ CONVTOSOLID → `convert_mesh` · ✔ CONVTOSURFACE → `convert_mesh`
- **Sección**: ◐ SECTIONPLANE → `create_object` · ○ LIVESECTION · ✖ SECTIONPLANEJOG · ✖ SECTIONPLANETOBLOCK · ✖ FLATSHOT · ◐ XEDGES → `call_object_method`
- **Suavizar**: ✔ MESHSMOOTHMORE → `mesh_smooth` · ✔ MESHSMOOTHLESS → `mesh_smooth` · ✔ MESHREFINE → `mesh_smooth`

## Salida

- **Trazar**: ✔ PLOT → `export_pdf` · ○ PUBLISH · ○ PREVIEW · ✔ PAGESETUP → `configure_layout` · ○ VIEWPLOTDETAILS · ✔ PLOTTERMANAGER → `configure_layout`
- **Exportar a DWF/PDF**: ✔ EXPORTSETTINGS → `configure_layout` · ○ 3DDWF

## Paramétrico

- **Geométricas**: ✖ AUTOCONSTRAIN · ✔ GCCOINCIDENT → `add_geometric_constraint` · ✔ GCCOLLINEAR → `add_geometric_constraint` · ✔ GCCONCENTRIC → `add_geometric_constraint` · ✔ GCFIX → `add_geometric_constraint` · ✔ GCPARALLEL → `add_geometric_constraint` · ✔ GCPERPENDICULAR → `add_geometric_constraint` · ✔ GCHORIZONTAL → `add_geometric_constraint` · ✔ GCVERTICAL → `add_geometric_constraint` · ✔ GCTANGENT → `add_geometric_constraint` · ✖ GCSMOOTH · ✖ GCSYMMETRIC · ✔ GCEQUAL → `add_geometric_constraint` · ✖ CONSTRAINTBAR
- **Por cota**: ✔ DCLINEAR → `add_dimensional_constraint` · ✔ DCHORIZONTAL → `add_dimensional_constraint` · ✔ DCVERTICAL → `add_dimensional_constraint` · ✔ DCALIGNED → `add_dimensional_constraint` · ✔ DCRADIUS → `radius_constraint` · ✔ DCDIAMETER → `radius_constraint` · ✔ DCANGULAR → `add_dimensional_constraint` · ✖ DCCONVERT · ✖ DCDISPLAY
- **Administrar**: ✖ DELCONSTRAINT

## Visualizar

- **Vistas guardadas**: ○ NEWVIEW · ○ VIEW
- **Coordenadas**: ◐ UCSICON → `set_system_variable` · ✔ UCS → `create_database_object`
- **Estilos visuales**: ○ HIDE
- **Ventanas gráficas de modelo**: ○ -VPORTS
- **Luces**: ▫ POINTLIGHT · ▫ SPOTLIGHT · ○ DISTANTLIGHT · ▫ WEBLIGHT
- **Sol y ubicación**: ▫ GEOGRAPHICLOCATION
- **Materiales**: ▫ MATERIALMAP · ▫ MATERIALATTACH
- **Cámara**: ○ CAMERA
- **Animaciones**: ○ ANIPATH · ○ 3DWALK · ○ 3DFLY · ○ WALKFLYSETTINGS
- **Render**: ○ RENDERONLINE · ○ SHOWRENDERGALLERY · ○ RENDERWINDOW

## Sólido

- **Primitiva**: ◐ BOX → `create_object` · ◐ CYLINDER → `create_object` · ◐ SPHERE → `create_object` · ◐ POLYSOLID → `create_object` · ◐ WEDGE → `create_object` · ◐ CONE → `create_object` · ◐ PYRAMID → `create_object` · ◐ TORUS → `create_object`
- **Sólido**: ✔ EXTRUDE → `extrude_profile, extrude_solid` · ◐ PRESSPULL → `call_object_method` · ✔ REVOLVE → `revolve_solid` · ✔ SWEEP → `sweep_solid` · ✔ LOFT → `loft_solid`
- **Booleano**: ✔ UNION → `solid_boolean, union_regions` · ✔ SUBTRACT → `solid_boolean` · ✔ INTERSECT → `solid_boolean`
- **Editar sólidos**: ◐ SLICE → `call_object_method` · ◐ THICKEN → `call_object_method` · ◐ IMPRINT → `call_object_method` · ◐ INTERFERE → `call_object_method` · ◐ XEDGES → `call_object_method` · ✖ OFFSETEDGE · ✔ FILLETEDGE → `fillet_solid_edges` · ✔ CHAMFEREDGE → `chamfer_solid_edges` · ✔ SOLIDEDIT → `edit_solid_faces`
- **Sección**: ◐ SECTIONPLANE → `create_object` · ○ LIVESECTION · ✖ SECTIONPLANEJOG · ✖ SECTIONPLANETOBLOCK · ✖ FLATSHOT · ◐ XEDGES → `call_object_method`

## Superficie

- **Crear**: ✖ SURFNETWORK · ✔ LOFT → `loft_solid` · ✔ SWEEP → `sweep_solid` · ✔ PLANESURF → `create_surface` · ✔ EXTRUDE → `extrude_profile, extrude_solid` · ✔ REVOLVE → `revolve_solid` · ✖ SURFBLEND · ✖ SURFPATCH · ✔ SURFOFFSET → `offset_surface`
- **Editar**: ✔ SURFFILLET → `fillet_surfaces` · ✔ SURFTRIM → `trim_surface` · ✖ SURFUNTRIM · ✔ SURFEXTEND → `extend_surface` · ✖ SURFSCULPT · ✔ SELECT → `select_entities` · ✖ OFFSETEDGE
- **Vértices de control**: ○ 3DEDITBAR · ✖ CONVTONURBS · ✖ CVSHOW · ✖ CVHIDE · ✖ CVREBUILD · ✖ CVADD · ✖ CVREMOVE
- **Curvas**: ✔ SPLINE → `create_spline` · ○ SKETCH · ✖ SURFEXTRACTCURVE · ◐ 3DPOLY → `create_object` · ✔ PLINE → `create_polyline` · ✔ LINE → `create_line` · ✖ BLEND · ✔ ARC → `create_arc` · ✔ CIRCLE → `create_circle` · ✔ ELLIPSE → `create_ellipse` · ✔ POINT → `create_point` · ✔ DIVIDE → `divide_curve` · ✔ MEASURE → `divide_curve` · ✔ RECTANG → `create_rectangle` · ✔ POLYGON → `create_polygon` · ✔ EXTEND → `extend_entity` · ✔ JOIN → `join_entities` · ✔ BREAK → `break_curve` · ✔ BREAKATPOINT → `break_curve`
- **Proyectar geometría**: ✖ PROJECTGEOMETRY
- **Análisis**: ▫ ANALYSISOPTIONS · ▫ ANALYSISZEBRA · ▫ ANALYSISCURVATURE · ▫ ANALYSISDRAFT

## Herramientas 3D

- **Modelado**: ◐ BOX → `create_object` · ◐ CYLINDER → `create_object` · ◐ CONE → `create_object` · ◐ SPHERE → `create_object` · ◐ PYRAMID → `create_object` · ◐ WEDGE → `create_object` · ◐ TORUS → `create_object` · ◐ POLYSOLID → `create_object` · ✔ MESH → `create_mesh` · ✖ EDGE · ✖ EDGESURF · ✔ RULESURF → `create_surface` · ✔ TABSURF → `create_surface`
- **Editar sólidos**: ◐ PRESSPULL → `call_object_method` · ✖ OFFSETEDGE · ✔ FILLETEDGE → `fillet_solid_edges` · ✔ CHAMFEREDGE → `chamfer_solid_edges` · ◐ SLICE → `call_object_method` · ◐ INTERFERE → `call_object_method` · ✔ SOLIDEDIT → `edit_solid_faces` · ✔ UNION → `solid_boolean, union_regions` · ✔ SUBTRACT → `solid_boolean` · ✔ INTERSECT → `solid_boolean` · ◐ XEDGES → `call_object_method` · ◐ IMPRINT → `call_object_method`
- **Superficies**: ✖ SURFBLEND · ✖ SURFPATCH · ✖ SURFNETWORK · ✔ SURFOFFSET → `offset_surface` · ✔ SURFEXTEND → `extend_surface` · ✔ SURFFILLET → `fillet_surfaces` · ✔ SURFTRIM → `trim_surface` · ✖ SURFUNTRIM · ✔ PLANESURF → `create_surface` · ◐ THICKEN → `call_object_method` · ✖ SURFSCULPT · ✖ PROJECTGEOMETRY · ▫ ANALYSISOPTIONS · ▫ ANALYSISZEBRA · ▫ ANALYSISCURVATURE · ▫ ANALYSISDRAFT
- **Malla**: ✔ MESHSMOOTH → `mesh_smooth` · ✔ MESHSMOOTHMORE → `mesh_smooth` · ✔ MESHSMOOTHLESS → `mesh_smooth` · ✔ MESHREFINE → `mesh_smooth` · ✔ MESHEXTRUDE → `edit_mesh_faces` · ✔ MESHMERGE → `edit_mesh_faces` · ✔ MESHCAP → `edit_mesh_faces`
- **Sección**: ◐ SECTIONPLANE → `create_object` · ○ LIVESECTION · ✖ SECTIONPLANEJOG · ✖ SECTIONPLANETOBLOCK · ✖ FLATSHOT · ◐ XEDGES → `call_object_method`
- **Coordenadas**: ✔ UCS → `create_database_object`

## Editar matriz asociativa

- **Editar matriz**: ✔ -ARRAYCLOSE → `array_entity`

## Editor de bloques - Cerrar

- **Cerrar**: ○ BCLOSE

## Editor de bloques

- **Abrir/guardar**: ✔ BEDIT → `define_block` · ○ BSAVE · ○ BTESTBLOCK · ○ BSAVEAS
- **Geométricas**: ✖ AUTOCONSTRAIN · ✔ GCCOINCIDENT → `add_geometric_constraint` · ✔ GCCOLLINEAR → `add_geometric_constraint` · ✔ GCCONCENTRIC → `add_geometric_constraint` · ✔ GCFIX → `add_geometric_constraint` · ✔ GCPARALLEL → `add_geometric_constraint` · ✔ GCPERPENDICULAR → `add_geometric_constraint` · ✔ GCHORIZONTAL → `add_geometric_constraint` · ✔ GCVERTICAL → `add_geometric_constraint` · ✔ GCTANGENT → `add_geometric_constraint` · ✖ GCSMOOTH · ✖ GCSYMMETRIC · ✔ GCEQUAL → `add_geometric_constraint` · ✖ CONSTRAINTBAR
- **Por cota**: ✖ BCPARAMETER · ✖ BTABLE
- **Administrar**: ✖ DELCONSTRAINT · ✖ BCONSTRUCTION
- **Parámetros de acción**: ✖ BPARAMETER · ○ BACTIONTOOL · ◐ ATTDEF → `create_object` · ○ BACTIONBAR

## Calco subyacente DGN

- **Delimitación**: ✖ DGNCLIP
- **Capas DGN**: ○ ULAYERS

## Calco subyacente DWF

- **Delimitación**: ✖ DWFCLIP
- **Capas DWF**: ○ ULAYERS

## Editar referencia

- **Editar referencia**: ○ REFCLOSE · ○ REFSET

## Referencia externa

- **Delimitación**: ✖ XCLIP

## Editor de sombreado de la vista de dibujo

- **Cerrar**: ◐ -HATCHEDIT → `set_object_properties`

## Editor de sombreado

- **Cerrar**: ◐ -HATCHEDIT → `set_object_properties`

## Imagen

- **Delimitación**: ✖ IMAGECLIP

## Subobjeto de malla

- **Aplanar**: ✔ MESHCREASE → `edit_mesh_faces` · ✖ MESHUNCREASE
- **Editar cara**: ✔ MESHSPLIT → `edit_mesh_faces` · ✔ MESHEXTRUDE → `edit_mesh_faces` · ✔ MESHMERGE → `edit_mesh_faces` · ✔ MESHREFINE → `mesh_smooth`

## Calco subyacente de PDF

- **Delimitación**: ✖ PDFCLIP
- **Capas PDF**: ○ ULAYERS

## Plano de sección

- **Modificar**: ✖ SECTIONPLANEJOG
- **Generar**: ✖ SECTIONPLANETOBLOCK · ▫ PCEXTRACTSECTION

## Probar bloque

- **Cerrar**: ○ CLOSE

## Celda de tabla

- **Fusionar**: ✖ EDITTABLECELL

## Matriz

- **Propiedades**: ◐ ARRAYEDIT → `call_object_method`
- **Opciones**: ◐ ARRAYEDIT → `call_object_method`
- **Cerrar**: ◐ ARRAYEDIT → `call_object_method`

## Creación de matriz

- **Propiedades**: ◐ BASE → `set_system_variable`

## Ubicación geográfica

- **Ubicación**: ▫ GEOGRAPHICLOCATION · ▫ GEOREORIENTMARKER · ▫ GEOREMOVE
- **Herramientas**: ▫ GEOMARKLATLONG · ▫ GEOMARKME · ▫ GEOMARKPOINT

## Presentación

- **Presentación**: ✔ LAYOUT → `create_layout` · ✔ PAGESETUP → `configure_layout`
- **Ventanas gráficas de presentación**: ○ -VPORTS · ? VPCLIP

## Nube de puntos

- **Visualizar**: ✔ 3DORBIT → `set_3d_view` · ○ 3DSWIVEL · ○ 3DWALK
- **Visualización**: ○ POINTCLOUDCOLORMAP
- **Delimitación**: ○ POINTCLOUDCROPSTATE
- **Extraer**: ▫ PCEXTRACTEDGE · ▫ PCEXTRACTCORNER · ▫ PCEXTRACTCENTERLINE · ▫ PCEXTRACTSECTION

## Modelo de coordinación

- **Visualizar**: ✔ 3DORBIT → `set_3d_view` · ○ 3DSWIVEL · ○ 3DWALK

## Colaborar

- **Compartir**: ○ SHARE
- **Comparar**: ○ COMPARE
- **Trazos**: ○ MARKUPIMPORT · ○ CHECKOUT

## Imagen de mapa

- **Actualizar**: ▫ GEOMAPIMAGEUPDATE

## Vista

- **Vistas guardadas**: ○ NEWVIEW · ○ VIEW
- **Estilos visuales**: ○ HIDE
- **Ventanas gráficas de modelo**: ○ -VPORTS
- **Coordenadas**: ◐ UCSICON → `set_system_variable` · ✔ UCS → `create_database_object`
- **Paletas**: ○ TEXTSCR
- **Navegar**: ○ VIEWBACK · ○ VIEWFORWARD · ○ PAN · ✔ 3DORBIT → `set_3d_view` · ○ 3DFORBIT · ○ 3DCORBIT · ✔ ZOOM → `zoom_extents, zoom_window` · ○ NAVSWHEELMODE
- **Revisar**: ○ COMPARE

## Para hacer (pendientes y sin clasificar)

- **datos de tablas, campos, atributos y traductor de capas**: ATTSYNC, BDETECT, EDITTABLECELL, LAYTRANS, UPDATEFIELD
- **pendientes sin nota (o sin clasificar)**: AIMLEADEREDITADD, AIMLEADEREDITREMOVE, BLEND, DATALINK, DATALINKUPDATE, FIELD, FLATSHOT, SECTIONPLANEJOG, SECTIONPLANETOBLOCK, SOLDRAW, SOLPROF, SOLVIEW, VPCLIP
- **recortes y calcos subyacentes (underlays)**: ADJUST, CLIP, DGNCLIP, DWFCLIP, IMAGECLIP, PDFCLIP, PDFIMPORT, XCLIP
- **restricciones: faltan SIMETRÍA/SUAVE/PUNTO-CURVA (GCSYMMETRIC, GCSMOOTH), DCCONVERT, AUTOCONSTRAIN y las de bloque (BPARAMETER, BTABLE)**: AUTOCONSTRAIN, BCONSTRUCTION, BCPARAMETER, BPARAMETER, BTABLE, CONSTRAINTBAR, DCCONVERT, DCDISPLAY, DELCONSTRAINT, GCSMOOTH, GCSYMMETRIC
- **superficies y mallas que faltan: SURFBLEND, SURFPATCH, SURFNETWORK, SURFSCULPT, SURFUNTRIM, EDGESURF, MESHUNCREASE, CONVTONURBS y los vértices de control (CV*)**: CONVTONURBS, CVADD, CVHIDE, CVREBUILD, CVREMOVE, CVSHOW, EDGE, EDGESURF, MESHUNCREASE, OFFSETEDGE, PROJECTGEOMETRY, SURFBLEND, SURFEXTRACTCURVE, SURFNETWORK, SURFPATCH, SURFSCULPT, SURFUNTRIM
