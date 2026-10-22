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
