"""Tests de purge_database_objects, set_current, grupos, XData, datos propios, atributos de
bloque y escalas de anotación (bd_extra.py + server.py) contra el socket mockeado.
NO necesita AutoCAD.

La conducta contra AutoCAD (qué purga de verdad, cómo guarda el XData...) se verifica en vivo;
acá se verifica lo de este lado: que se rechace antes de tocar AutoCAD lo que no tiene sentido y
que cada tool mande al plugin el comando y los parámetros correctos.

Uso:  python test_bd_extra.py
"""
from __future__ import annotations

import server
import session

FAILED: list[str] = []


def check(name: str, got, expected) -> None:
    ok = got == expected
    if not ok:
        FAILED.append(f"{name}: esperaba {expected!r}, obtuve {got!r}")
    print(("  ok  " if ok else " FALLA ") + name)


def con_plugin(fn):
    llamadas: list[tuple[str, dict]] = []

    def fake(cmd, params=None):
        llamadas.append((cmd, params or {}))
        return {"ok": True}

    real = server.acad.call
    server.acad.call = fake
    try:
        return fn(), llamadas
    finally:
        server.acad.call = real


def rechazada(nombre, fn):
    r, ll = con_plugin(fn)
    check(f"{nombre}: se rechaza", r.get("ok"), False)
    check(f"{nombre}: dice por qué", bool(r.get("error")), True)
    check(f"{nombre}: no toca AutoCAD", ll, [])


def manda(nombre, fn, comando, params):
    r, ll = con_plugin(fn)
    check(nombre, ll[0] if ll else None, (comando, params))


def main() -> int:
    # ---- purga y actual
    manda("purge sin nada: todos, de verdad", lambda: server.purge_database_objects(),
          "purge_database_objects", {"dry_run": False})
    manda("purge con tipos en mayuscula", lambda: server.purge_database_objects(["Layer", "BLOCK"], True),
          "purge_database_objects", {"dry_run": True, "kinds": ["layer", "block"]})
    rechazada("purge de un tipo desconocido", lambda: server.purge_database_objects(["layout"]))
    rechazada("purge con lista vacia", lambda: server.purge_database_objects([]))
    manda("set_current", lambda: server.set_current("Layer", "MUROS"), "set_current", {"kind": "layer", "name": "MUROS"})
    rechazada("set_current de un tipo no permitido", lambda: server.set_current("block", "X"))
    rechazada("set_current sin nombre", lambda: server.set_current("layer", ""))
    rechazada("set_current con caracter reservado", lambda: server.set_current("layer", "A/B"))

    # ---- grupos
    manda("create_group", lambda: server.create_group("COLUMNAS", ["a1", "B2", "a1"], "las del eje A", False),
          "create_group", {"name": "COLUMNAS", "handles": ["A1", "B2"], "description": "las del eje A", "selectable": False})
    rechazada("create_group sin entidades", lambda: server.create_group("G", []))
    rechazada("create_group con handle invalido", lambda: server.create_group("G", ["zz"]))
    rechazada("create_group con nombre invalido", lambda: server.create_group("G*", ["A1"]))
    rechazada("create_group con descripcion enorme", lambda: server.create_group("G", ["A1"], "x" * 256))
    manda("delete_group", lambda: server.delete_group("COLUMNAS"), "delete_group", {"name": "COLUMNAS"})
    manda("modify_group", lambda: server.modify_group("COLUMNAS", add=["c3"], remove=["a1"], selectable=True),
          "modify_group", {"name": "COLUMNAS", "add": ["C3"], "remove": ["A1"], "selectable": True})
    rechazada("modify_group sin nada que cambiar", lambda: server.modify_group("COLUMNAS"))

    # ---- XData
    manda("get_xdata de una app", lambda: server.get_xdata("a1", "MI-APP"), "get_xdata", {"handle": "A1", "app": "MI-APP"})
    manda("get_xdata de todas", lambda: server.get_xdata("a1"), "get_xdata", {"handle": "A1"})
    manda("set_xdata con valores mixtos", lambda: server.set_xdata("a1", "MI-APP", ["P-12", 3, 2.5, True, [1, 2, 3], {"layer": "MUROS"}]),
          "set_xdata", {"handle": "A1", "app": "MI-APP", "values": ["P-12", 3, 2.5, True, [1, 2, 3], {"layer": "MUROS"}]})
    rechazada("set_xdata con la app ACAD", lambda: server.set_xdata("A1", "acad", ["x"]))
    rechazada("set_xdata con app de mas de 31 caracteres", lambda: server.set_xdata("A1", "x" * 32, ["x"]))
    rechazada("set_xdata sin valores", lambda: server.set_xdata("A1", "APP", []))
    rechazada("set_xdata con demasiados valores", lambda: server.set_xdata("A1", "APP", list(range(201))))
    rechazada("set_xdata con tipo desconocido", lambda: server.set_xdata("A1", "APP", [{"color": 3}]))
    rechazada("set_xdata con dos campos en un valor tipado", lambda: server.set_xdata("A1", "APP", [{"text": "a", "real": 1}]))
    rechazada("set_xdata con un punto de 2 coordenadas", lambda: server.set_xdata("A1", "APP", [[1, 2]]))
    rechazada("set_xdata con NaN", lambda: server.set_xdata("A1", "APP", [float("nan")]))
    rechazada("set_xdata con null", lambda: server.set_xdata("A1", "APP", [None]))
    manda("clear_xdata", lambda: server.clear_xdata("a1", "MI-APP"), "clear_xdata", {"handle": "A1", "app": "MI-APP"})
    rechazada("clear_xdata con handle invalido", lambda: server.clear_xdata("zz", "APP"))

    # ---- datos propios
    manda("set_custom_data", lambda: server.set_custom_data("a1", "CANTIDADES", ["concreto", 12.5, {"int": 3}, {"bool": True}]),
          "set_custom_data", {"handle": "A1", "key": "CANTIDADES", "values": ["concreto", 12.5, {"int": 3}, {"bool": True}]})
    manda("get_custom_data con clave", lambda: server.get_custom_data("a1", "CANTIDADES"), "get_custom_data", {"handle": "A1", "key": "CANTIDADES"})
    manda("get_custom_data de todas", lambda: server.get_custom_data("a1"), "get_custom_data", {"handle": "A1"})
    manda("delete_custom_data", lambda: server.delete_custom_data("a1", "CANTIDADES"), "delete_custom_data", {"handle": "A1", "key": "CANTIDADES"})
    rechazada("set_custom_data con tipo de XData (layer)", lambda: server.set_custom_data("A1", "K", [{"layer": "X"}]))
    rechazada("set_custom_data con clave invalida", lambda: server.set_custom_data("A1", "a:b", ["x"]))
    rechazada("set_custom_data con demasiados valores", lambda: server.set_custom_data("A1", "K", list(range(1001))))

    # ---- atributos
    manda("get_block_attributes", lambda: server.get_block_attributes("a1"), "get_block_attributes", {"handle": "A1"})
    manda("set_block_attributes", lambda: server.set_block_attributes("a1", {"NUMERO": "A-12", "AREA": 45.2}),
          "set_block_attributes", {"handle": "A1", "values": {"NUMERO": "A-12", "AREA": 45.2}})
    rechazada("set_block_attributes sin valores", lambda: server.set_block_attributes("A1", {}))
    rechazada("set_block_attributes con null", lambda: server.set_block_attributes("A1", {"N": None}))
    rechazada("set_block_attributes con un valor que no es texto", lambda: server.set_block_attributes("A1", {"N": ["x"]}))
    rechazada("set_block_attributes con etiqueta vacia", lambda: server.set_block_attributes("A1", {" ": "x"}))

    # ---- escalas
    manda("list_annotation_scales", lambda: server.list_annotation_scales(), "list_annotation_scales", {})
    manda("add_annotation_scale", lambda: server.add_annotation_scale("1:50", 1, 50), "add_annotation_scale",
          {"name": "1:50", "paper_units": 1.0, "drawing_units": 50.0})
    rechazada("add_annotation_scale con unidades cero", lambda: server.add_annotation_scale("1:0", 1, 0))
    rechazada("add_annotation_scale con unidades negativas", lambda: server.add_annotation_scale("x", -1, 50))
    rechazada("add_annotation_scale con unidades que no son numero", lambda: server.add_annotation_scale("x", "1", 50))
    rechazada("add_annotation_scale sin nombre", lambda: server.add_annotation_scale("", 1, 50))
    manda("set_current_annotation_scale", lambda: server.set_current_annotation_scale("1:50"), "set_current_annotation_scale", {"name": "1:50"})
    manda("remove_annotation_scale", lambda: server.remove_annotation_scale("1:50"), "remove_annotation_scale", {"name": "1:50"})
    rechazada("remove_annotation_scale sin nombre", lambda: server.remove_annotation_scale(""))

    # ---- layouts e impresión
    manda("list_plot_options del layout activo", lambda: server.list_plot_options(), "list_plot_options", {})
    manda("list_plot_options de un layout", lambda: server.list_plot_options(" BP-01 "), "list_plot_options", {"layout": "BP-01"})
    manda("configure_layout completo", lambda: server.configure_layout(
        "BP-01", device="DWG To PDF.pc3", media="ISO_A1_(841.00_x_594.00_MM)", style_sheet="monochrome.ctb",
        plot_type="Layout", rotation="Degrees090", centered=True, paper_units="Millimeters", scale="fit"),
        "configure_layout", {"layout": "BP-01", "device": "DWG To PDF.pc3", "media": "ISO_A1_(841.00_x_594.00_MM)",
                              "style_sheet": "monochrome.ctb", "plot_type": "Layout", "rotation": "Degrees090",
                              "centered": True, "paper_units": "Millimeters", "scale": "fit"})
    manda("configure_layout con escala 1:100", lambda: server.configure_layout("BP-01", scale={"paper": 1, "drawing": 100}),
          "configure_layout", {"layout": "BP-01", "scale": {"paper": 1.0, "drawing": 100.0}})
    manda("configure_layout con ventana", lambda: server.configure_layout("BP-01", window=[[0, 0], [10, 5]]),
          "configure_layout", {"layout": "BP-01", "window": [[0.0, 0.0], [10.0, 5.0]]})
    rechazada("configure_layout sin nada que configurar", lambda: server.configure_layout("BP-01"))
    rechazada("configure_layout sin layout", lambda: server.configure_layout(""))
    rechazada("configure_layout con rotacion invalida", lambda: server.configure_layout("BP-01", rotation="45"))
    rechazada("configure_layout con tipo de area invalido", lambda: server.configure_layout("BP-01", plot_type="Todo"))
    rechazada("configure_layout con unidades invalidas", lambda: server.configure_layout("BP-01", paper_units="Metros"))
    rechazada("configure_layout con escala cero", lambda: server.configure_layout("BP-01", scale={"paper": 1, "drawing": 0}))
    rechazada("configure_layout con escala incompleta", lambda: server.configure_layout("BP-01", scale={"paper": 1}))
    rechazada("configure_layout con escala que no es nada", lambda: server.configure_layout("BP-01", scale=5))
    rechazada("configure_layout con ventana sin area", lambda: server.configure_layout("BP-01", window=[[0, 0], [0, 5]]))
    rechazada("configure_layout con ventana mal formada", lambda: server.configure_layout("BP-01", window=[[0, 0]]))
    rechazada("configure_layout con dispositivo vacio", lambda: server.configure_layout("BP-01", device=" "))

    # ---- bloques dinamicos
    manda("get_dynamic_block_properties", lambda: server.get_dynamic_block_properties("a1"),
          "get_dynamic_block_properties", {"handle": "A1"})
    manda("set_dynamic_block_properties", lambda: server.set_dynamic_block_properties("a1", {"Visibilidad": "Abierta", "Ancho": 0.9}),
          "set_dynamic_block_properties", {"handle": "A1", "values": {"Visibilidad": "Abierta", "Ancho": 0.9}})
    rechazada("set_dynamic_block_properties sin valores", lambda: server.set_dynamic_block_properties("A1", {}))
    rechazada("set_dynamic_block_properties con null", lambda: server.set_dynamic_block_properties("A1", {"Ancho": None}))
    rechazada("set_dynamic_block_properties con una lista", lambda: server.set_dynamic_block_properties("A1", {"Ancho": [1]}))
    rechazada("set_dynamic_block_properties con un booleano", lambda: server.set_dynamic_block_properties("A1", {"Ancho": True}))
    rechazada("set_dynamic_block_properties con NaN", lambda: server.set_dynamic_block_properties("A1", {"Ancho": float("nan")}))

    # ---- estilos de tabla y de directriz (kinds nuevos de create/delete_database_object)
    manda("create tablestyle", lambda: server.create_database_object("TableStyle", "TABLA-CUADROS", {"Description": "cuadros"}),
          "create_database_object", {"kind": "tablestyle", "name": "TABLA-CUADROS", "properties": {"Description": "cuadros"}})
    manda("create mleaderstyle", lambda: server.create_database_object("mleaderstyle", "DIRECTRIZ-NOTAS"),
          "create_database_object", {"kind": "mleaderstyle", "name": "DIRECTRIZ-NOTAS", "properties": {}})
    manda("delete tablestyle", lambda: server.delete_database_object("tablestyle", "TABLA-CUADROS"),
          "delete_database_object", {"kind": "tablestyle", "name": "TABLA-CUADROS"})

    # ---- herramientas de capas (1.18.0)
    manda("merge_layers", lambda: server.merge_layers(["MUROS-VIEJOS", "muros-viejos", "TEMP"], "MUROS"),
          "merge_layers", {"sources": ["MUROS-VIEJOS", "TEMP"], "target": "MUROS"})
    rechazada("merge_layers destino entre los origenes", lambda: server.merge_layers(["A", "B"], "a"))
    rechazada("merge_layers capa 0", lambda: server.merge_layers(["0"], "MUROS"))
    rechazada("merge_layers sin origenes", lambda: server.merge_layers([], "MUROS"))
    manda("delete_layer_with_objects sin confirmar cuenta", lambda: server.delete_layer_with_objects("TEMP"),
          "delete_layer_with_objects", {"name": "TEMP", "confirm": False})
    manda("delete_layer_with_objects confirmado", lambda: server.delete_layer_with_objects("TEMP", True),
          "delete_layer_with_objects", {"name": "TEMP", "confirm": True})
    manda("delete_layer_with_objects: 'si' no es confirmar", lambda: server.delete_layer_with_objects("TEMP", "si"),
          "delete_layer_with_objects", {"name": "TEMP", "confirm": False})
    rechazada("delete_layer_with_objects Defpoints", lambda: server.delete_layer_with_objects("Defpoints", True))
    manda("save_layer_state", lambda: server.save_layer_state("ESTADO-A", "base", ["On", "FROZEN"], True),
          "save_layer_state", {"name": "ESTADO-A", "description": "base", "replace": True, "properties": ["on", "frozen"]})
    rechazada("save_layer_state interno", lambda: server.save_layer_state("_MCP_X"))
    rechazada("save_layer_state propiedad desconocida", lambda: server.save_layer_state("A", properties=["magia"]))
    rechazada("save_layer_state lista vacia", lambda: server.save_layer_state("A", properties=[]))
    manda("restore_layer_state", lambda: server.restore_layer_state("ESTADO-A", turn_off_others=True),
          "restore_layer_state", {"name": "ESTADO-A", "turn_off_others": True})
    manda("list_layer_states", lambda: server.list_layer_states(), "list_layer_states", {})
    manda("delete_layer_state", lambda: server.delete_layer_state("ESTADO-A"), "delete_layer_state", {"name": "ESTADO-A"})
    rechazada("delete_layer_state interno", lambda: server.delete_layer_state("_MCP_ISOLATE"))
    manda("isolate_layers", lambda: server.isolate_layers(["MUROS", "EJES"], "lock"),
          "isolate_layers", {"layers": ["MUROS", "EJES"], "mode": "lock"})
    rechazada("isolate_layers modo invalido", lambda: server.isolate_layers(["MUROS"], "borrar"))
    manda("unisolate_layers", lambda: server.unisolate_layers(), "unisolate_layers", {})
    manda("set_viewport_layers congela", lambda: server.set_viewport_layers("5a", freeze=["COTAS"], thaw=["MUROS"], thaw_all=True),
          "set_viewport_layers", {"handle": "5A", "freeze": ["COTAS"], "thaw": ["MUROS"], "thaw_all": True})
    manda("set_viewport_layers solo informa", lambda: server.set_viewport_layers("5A"),
          "set_viewport_layers", {"handle": "5A"})
    rechazada("set_viewport_layers freeze y freeze_all_except", lambda: server.set_viewport_layers("5A", freeze=["A"], freeze_all_except=["B"]))
    rechazada("set_viewport_layers handle invalido", lambda: server.set_viewport_layers("zz", freeze=["A"]))
    for lectura in ("list_layer_states",):
        check(f"{lectura} es de lectura", session.retry_safe(lectura), True)
    for cambio in ("merge_layers", "delete_layer_with_objects", "save_layer_state", "restore_layer_state",
                   "isolate_layers", "unisolate_layers", "set_viewport_layers"):
        check(f"{cambio} NO se reintenta", session.retry_safe(cambio), False)
        check(f"{cambio}: el docstring avisa PENDIENTE", "PENDIENTE" in (getattr(server, cambio).__doc__ or ""), True)

    # ---- copias y layouts (1.18.0)
    manda("export_copy dwg 2013", lambda: server.export_copy("C:/tmp/plano.dwg", "2013"),
          "export_copy", {"path": "C:/tmp/plano.dwg", "version": "2013", "precision": 16, "overwrite": False})
    manda("export_copy dxf", lambda: server.export_copy("C:/tmp/plano.DXF", "2018", 8, True),
          "export_copy", {"path": "C:/tmp/plano.DXF", "version": "2018", "precision": 8, "overwrite": True})
    rechazada("export_copy extension rara", lambda: server.export_copy("C:/tmp/plano.pdf"))
    rechazada("export_copy version inexistente", lambda: server.export_copy("C:/tmp/p.dwg", "1999"))
    rechazada("export_copy precision fuera de rango", lambda: server.export_copy("C:/tmp/p.dxf", precision=17))
    rechazada("export_copy sin path", lambda: server.export_copy(""))
    check("export_copy no cuenta como dibujo sin guardar", session.retry_safe("export_copy"), True)
    manda("rename_layout", lambda: server.rename_layout("A-01", "A-02"), "rename_layout", {"name": "A-01", "new_name": "A-02"})
    rechazada("rename_layout Model", lambda: server.rename_layout("Model", "X"))
    rechazada("rename_layout a Model", lambda: server.rename_layout("A-01", "model"))
    rechazada("rename_layout nombre con caracter reservado", lambda: server.rename_layout("A-01", "A/02"))
    manda("copy_layout", lambda: server.copy_layout("A-01", "A-03"), "copy_layout", {"name": "A-01", "new_name": "A-03"})
    rechazada("copy_layout de Model", lambda: server.copy_layout("Model", "X"))
    for cambio in ("rename_layout", "copy_layout"):
        check(f"{cambio} NO se reintenta", session.retry_safe(cambio), False)

    # ---- xrefs y propiedades del dibujo (1.18.0)
    manda("bind_xref uno", lambda: server.bind_xref("ARQ"), "bind_xref", {"names": ["ARQ"], "insert": True})
    manda("bind_xref varios en modo unir", lambda: server.bind_xref(names=["ARQ", "EST"], insert=False),
          "bind_xref", {"names": ["ARQ", "EST"], "insert": False})
    manda("bind_xref todos", lambda: server.bind_xref(), "bind_xref", {"insert": True})
    rechazada("bind_xref name y names", lambda: server.bind_xref("A", ["B"]))
    manda("unload_xref", lambda: server.unload_xref("ARQ"), "unload_xref", {"names": ["ARQ"]})
    manda("get_drawing_properties", lambda: server.get_drawing_properties(), "get_drawing_properties", {})
    manda("set_drawing_properties", lambda: server.set_drawing_properties(title="Casa 9x12", author="J. D. DIAZ PEREZ", custom={"Obra": "Casa", "Viejo": None}),
          "set_drawing_properties", {"title": "Casa 9x12", "author": "J. D. DIAZ PEREZ", "custom": {"Obra": "Casa", "Viejo": None}})
    rechazada("set_drawing_properties sin nada", lambda: server.set_drawing_properties())
    rechazada("set_drawing_properties custom vacio", lambda: server.set_drawing_properties(custom={}))
    rechazada("set_drawing_properties titulo enorme", lambda: server.set_drawing_properties(title="x" * 1001))
    rechazada("set_drawing_properties nombre custom con espacios", lambda: server.set_drawing_properties(custom={" a": "b"}))
    check("get_drawing_properties es de lectura", session.retry_safe("get_drawing_properties"), True)
    for cambio in ("bind_xref", "unload_xref", "set_drawing_properties"):
        check(f"{cambio} NO se reintenta", session.retry_safe(cambio), False)

    # ---- edición con la API (1.18.0)
    manda("explode_entities", lambda: server.explode_entities(["a1", "B2", "a1"]),
          "explode_entities", {"handles": ["A1", "B2"], "delete_original": True})
    manda("explode_entities conservando", lambda: server.explode_entities(["A1"], False),
          "explode_entities", {"handles": ["A1"], "delete_original": False})
    rechazada("explode_entities sin handles", lambda: server.explode_entities([]))
    rechazada("explode_entities handle invalido", lambda: server.explode_entities(["xx"]))
    manda("break_curve", lambda: server.break_curve("a1", [[1, 2], [3, 4, 0]]),
          "break_curve", {"handle": "A1", "points": [[1.0, 2.0], [3.0, 4.0, 0.0]]})
    rechazada("break_curve sin puntos", lambda: server.break_curve("A1", []))
    rechazada("break_curve punto mal formado", lambda: server.break_curve("A1", [[1]]))
    rechazada("break_curve punto NaN", lambda: server.break_curve("A1", [[1, float("nan")]]))
    manda("divide_curve en partes", lambda: server.divide_curve("A1", count=4),
          "divide_curve", {"handle": "A1", "align": True, "count": 4})
    manda("divide_curve con bloque", lambda: server.divide_curve("A1", distance=2.5, block="ARBOL", align=False, layer="VEG"),
          "divide_curve", {"handle": "A1", "align": False, "distance": 2.5, "block": "ARBOL", "layer": "VEG"})
    rechazada("divide_curve sin count ni distance", lambda: server.divide_curve("A1"))
    rechazada("divide_curve con los dos", lambda: server.divide_curve("A1", count=3, distance=2))
    rechazada("divide_curve count 1", lambda: server.divide_curve("A1", count=1))
    rechazada("divide_curve distancia 0", lambda: server.divide_curve("A1", distance=0))
    manda("create_boundary", lambda: server.create_boundary([5, 5], True, "AREAS"),
          "create_boundary", {"point": [5.0, 5.0], "islands": True, "layer": "AREAS"})
    rechazada("create_boundary punto invalido", lambda: server.create_boundary("5,5"))
    manda("match_properties", lambda: server.match_properties("a1", ["b2", "C3", "a1"], ["Layer", "COLOR"]),
          "match_properties", {"source": "A1", "targets": ["B2", "C3"], "properties": ["layer", "color"]})
    rechazada("match_properties propiedad desconocida", lambda: server.match_properties("A1", ["B2"], ["magia"]))
    rechazada("match_properties solo el origen", lambda: server.match_properties("A1", ["A1"]))
    for cambio in ("explode_entities", "break_curve", "divide_curve", "create_boundary", "match_properties"):
        check(f"{cambio} NO se reintenta", session.retry_safe(cambio), False)

    # ---- sólidos desde perfiles (1.18.0)
    manda("extrude_solid con altura", lambda: server.extrude_solid("a1", height=3.0),
          "extrude_solid", {"profile": "A1", "taper_deg": 0.0, "delete_profile": False, "height": 3.0})
    manda("extrude_solid con direccion", lambda: server.extrude_solid("A1", direction=[0, 0, 2.5], taper_deg=5, delete_profile=True, layer="3D"),
          "extrude_solid", {"profile": "A1", "taper_deg": 5.0, "delete_profile": True, "direction": [0.0, 0.0, 2.5], "layer": "3D"})
    rechazada("extrude_solid sin altura ni direccion", lambda: server.extrude_solid("A1"))
    rechazada("extrude_solid con las dos", lambda: server.extrude_solid("A1", height=1, direction=[0, 0, 1]))
    rechazada("extrude_solid altura 0", lambda: server.extrude_solid("A1", height=0))
    rechazada("extrude_solid direccion nula", lambda: server.extrude_solid("A1", direction=[0, 0, 0]))
    rechazada("extrude_solid ahusado imposible", lambda: server.extrude_solid("A1", height=1, taper_deg=90))
    manda("revolve_solid", lambda: server.revolve_solid("A1", [0, 0], [0, 1, 0], 180),
          "revolve_solid", {"profile": "A1", "axis_point": [0.0, 0.0, 0.0], "axis_dir": [0.0, 1.0, 0.0], "angle_deg": 180.0,
                            "start_angle_deg": 0.0, "twist_deg": 0.0, "draft_deg": 0.0, "close_to_axis": False, "delete_profile": False})
    rechazada("revolve_solid angulo 0", lambda: server.revolve_solid("A1", [0, 0], [0, 1], 0))
    rechazada("revolve_solid angulo mayor que una vuelta", lambda: server.revolve_solid("A1", [0, 0], [0, 1], 400))
    rechazada("revolve_solid eje nulo", lambda: server.revolve_solid("A1", [0, 0], [0, 0, 0]))
    manda("sweep_solid", lambda: server.sweep_solid("a1", "b2", scale=0.5, delete_path=True),
          "sweep_solid", {"profile": "A1", "path": "B2", "twist_deg": 0.0, "scale": 0.5, "align": True, "bank": False,
                          "delete_profile": False, "delete_path": True})
    rechazada("sweep_solid perfil igual a trayectoria", lambda: server.sweep_solid("A1", "a1"))
    rechazada("sweep_solid escala 0", lambda: server.sweep_solid("A1", "B2", scale=0))
    manda("loft_solid", lambda: server.loft_solid(["a1", "b2", "C3"], ruled=True),
          "loft_solid", {"sections": ["A1", "B2", "C3"], "ruled": True, "closed": False, "delete_sources": False})
    rechazada("loft_solid con una sola seccion", lambda: server.loft_solid(["A1"]))
    rechazada("loft_solid con guias y trayectoria", lambda: server.loft_solid(["A1", "B2"], guides=["C3"], path="D4"))
    for cambio in ("extrude_solid", "revolve_solid", "sweep_solid", "loft_solid"):
        check(f"{cambio} NO se reintenta", session.retry_safe(cambio), False)

    # ---- sesión
    for lectura in ("get_xdata", "get_custom_data", "get_block_attributes", "list_annotation_scales",
                    "list_plot_options", "get_dynamic_block_properties"):
        check(f"{lectura} es de lectura", session.retry_safe(lectura), True)
    for cambio in ("purge_database_objects", "set_current", "create_group", "set_xdata", "set_custom_data",
                   "set_block_attributes", "add_annotation_scale", "remove_annotation_scale"):
        check(f"{cambio} NO se reintenta", session.retry_safe(cambio), False)

    # ---- los docstrings avisan que falta la prueba en vivo
    for t in ("purge_database_objects", "set_xdata", "create_group", "add_annotation_scale"):
        check(f"{t}: el docstring avisa PENDIENTE", "PENDIENTE" in (getattr(server, t).__doc__ or ""), True)

    if FAILED:
        print("\nFALLARON:")
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
