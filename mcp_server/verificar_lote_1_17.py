"""Verificación EN VIVO de los lotes 1.17.0 y 1.18.0 (purga, actual, grupos, XData, datos propios, atributos,
escalas de anotación, impresión de layouts, bloques dinámicos, estilos de tabla/directriz; y de la 1.18.0: fusionar/borrar/aislar capas, estados de capa, capas por viewport, copiar/renombrar layouts y exportar copias DWG/DXF).

Estas tools se escribieron sin AutoCAD a mano: compilan en 2019-2027 pero NO se habían probado.
Trabaja en un dibujo NUEVO descartable y lo cierra. NO usarlo con un plano en curso.

Imprime una línea por comprobación; al final el resumen y, si algo falla, qué. Sale con 1 si falla.

Uso:  python verificar_lote_1_17.py            (con AutoCAD abierto y el plugin 1.17.0 cargado)
"""
from __future__ import annotations

import json
import sys

import server as s

R: list[tuple[str, bool]] = []


def chk(n, ok, det=""):
    R.append((n, bool(ok)))
    print(("  ok   " if ok else " FALLA ") + n + (f"  [{str(det)[:300]}]" if det and not ok else ""))


def bueno(r):
    return isinstance(r, dict) and r.get("ok") is not False and "error" not in r


def txt(r):
    return json.dumps(r, ensure_ascii=False, default=str)


def intento(n, f):
    try:
        return f()
    except Exception as e:  # noqa: BLE001
        chk(n, False, "EXCEPCION: " + str(e)[:250])
        return None


def rechaza(n, f, pista=""):
    """La tool debe NEGARSE (excepción o ok=False); si hace el cambio, es una falla."""
    try:
        r = f()
    except Exception as e:  # noqa: BLE001
        chk(n, pista.lower() in str(e).lower(), str(e)[:200])
        return
    chk(n, (not bueno(r)) and pista.lower() in txt(r).lower(), r)


def main() -> int:
    s.new_document()
    info = s.ping()
    print("== version:", info)
    chk("plugin >= 1.17.0", tuple(int(x) for x in str(info.get("pluginVersion", "0")).split(".")[:3]) >= (1, 17, 0), info)

    L = s.create_line(0, 0, 10, 0)["handle"]
    C = s.create_circle(20, 0, 3)["handle"]
    T = s.create_text("x", 0, 5, 1.0)["handle"]

    # ---------------------------------------------------------------- set_current
    r = intento("create_database_object layer", lambda: s.create_database_object("layer", "PRUEBA17", {}))
    chk("capa PRUEBA17 creada", bueno(r), r)
    r = intento("set_current layer", lambda: s.set_current("layer", "PRUEBA17"))
    chk("set_current capa", bueno(r), r)
    v = intento("clayer", lambda: s.get_system_variables(["CLAYER"]))
    chk("CLAYER quedó en PRUEBA17", v and v["values"].get("CLAYER") == "PRUEBA17", v)
    rechaza("set_current capa inexistente se rechaza", lambda: s.set_current("layer", "NO_EXISTE_XX"), "")
    s.set_current("layer", "0")
    r = intento("set_current textstyle", lambda: s.set_current("textstyle", "Standard"))
    chk("set_current textstyle", bueno(r), r)

    # ---------------------------------------------------------------- grupos
    g = intento("create_group", lambda: s.create_group("G17", [L, C], "grupo de prueba", True))
    chk("create_group", bueno(g), g)
    ch = intento("list_children groups", lambda: s.list_children("groups"))
    chk("el grupo G17 aparece", ch and "G17" in txt(ch), ch)
    m = intento("modify_group add", lambda: s.modify_group("G17", add=[T]))
    chk("modify_group agrega", bueno(m), m)
    m = intento("modify_group remove+desc", lambda: s.modify_group("G17", remove=[C], description="nueva"))
    chk("modify_group saca y cambia descripción", bueno(m), m)
    rechaza("create_group repetido se rechaza", lambda: s.create_group("G17", [L]), "")
    rechaza("create_group con handle inexistente se rechaza", lambda: s.create_group("G18", ["FFFFF"]), "")
    d = intento("delete_group", lambda: s.delete_group("G17"))
    chk("delete_group", bueno(d), d)
    ex = intento("la línea sobrevive al borrar el grupo", lambda: s.get_entity(L))
    chk("la línea sigue ahí", ex and "error" not in txt(ex).lower()[:80], ex)

    # ---------------------------------------------------------------- XData
    r = intento("set_xdata", lambda: s.set_xdata(L, "MCP_PRUEBA", ["texto", 42, 2.5, [1, 2, 3], {"layer": "0"}, {"int16": 7}]))
    chk("set_xdata", bueno(r), r)
    r = intento("get_xdata", lambda: s.get_xdata(L, "MCP_PRUEBA"))
    t = txt(r)
    chk("get_xdata devuelve lo guardado", r and "texto" in t and "42" in t and "2.5" in t, r)
    r = intento("get_xdata sin app", lambda: s.get_xdata(L))
    chk("get_xdata sin app lista MCP_PRUEBA", r and "MCP_PRUEBA" in txt(r), r)
    rechaza("set_xdata con app ACAD se rechaza", lambda: s.set_xdata(L, "ACAD", ["x"]), "")
    r = intento("clear_xdata", lambda: s.clear_xdata(L, "MCP_PRUEBA"))
    chk("clear_xdata", bueno(r), r)
    r = intento("get_xdata tras borrar", lambda: s.get_xdata(L, "MCP_PRUEBA"))
    chk("ya no queda XData", r and "texto" not in txt(r), r)

    # ---------------------------------------------------------------- datos propios (Xrecord)
    r = intento("set_custom_data", lambda: s.set_custom_data(C, "PARTIDA", ["muro", 12, 3.75, True, [1, 2, 3]]))
    chk("set_custom_data", bueno(r), r)
    r = intento("get_custom_data", lambda: s.get_custom_data(C, "PARTIDA"))
    t = txt(r)
    chk("get_custom_data devuelve lo guardado", r and "muro" in t and "3.75" in t, r)
    r = intento("set_custom_data texto largo", lambda: s.set_custom_data(C, "LARGO", ["a" * 1000]))
    chk("texto largo (1000) entra", bueno(r), r)
    r = intento("get_custom_data todas", lambda: s.get_custom_data(C))
    chk("get_custom_data sin clave lista ambas", r and "PARTIDA" in txt(r) and "LARGO" in txt(r), r)
    r = intento("delete_custom_data", lambda: s.delete_custom_data(C, "PARTIDA"))
    chk("delete_custom_data", bueno(r), r)
    r = intento("get_custom_data tras borrar", lambda: s.get_custom_data(C, "PARTIDA"))
    chk("la clave ya no está", r and "muro" not in txt(r), r)

    # ---------------------------------------------------------------- atributos de bloque
    # No hay tool para definir un atributo: se arma con create_object sobre el bloque.
    b = intento("bloque con atributo", lambda: s.create_database_object("block", "BLQ17", {}))
    if bueno(b):
        a = intento("AttributeDefinition", lambda: s.create_object(
            "AttributeDefinition", {"Tag": "NUMERO", "Prompt": "Numero", "TextString": "0", "Height": 1.0,
                                    "Position": [0, 0, 0]}, container="BLQ17"))
        chk("AttributeDefinition dentro del bloque", bueno(a), a)
        if bueno(a):
            ins = intento("insert_block BLQ17", lambda: s.insert_block("BLQ17", 50, 0))
            hb = (ins or {}).get("handle")
            chk("bloque insertado", bool(hb), ins)
            if hb:
                r = intento("get_block_attributes", lambda: s.get_block_attributes(hb))
                chk("get_block_attributes ve NUMERO", r and "NUMERO" in txt(r), r)
                r = intento("set_block_attributes", lambda: s.set_block_attributes(hb, {"NUMERO": "A-12"}))
                chk("set_block_attributes", bueno(r), r)
                r = intento("get_block_attributes tras set", lambda: s.get_block_attributes(hb))
                chk("el atributo vale A-12", r and "A-12" in txt(r), r)
                rechaza("etiqueta inexistente se rechaza", lambda: s.set_block_attributes(hb, {"NOEXISTE": "x"}), "")
                # un bloque no dinámico no tiene propiedades dinámicas: no debe tumbar nada
                r = intento("get_dynamic_block_properties en bloque estático",
                            lambda: s.get_dynamic_block_properties(hb))
                chk("get_dynamic_block_properties responde (vacío o aviso, sin caer)", isinstance(r, dict), r)
                rechaza("set_dynamic en bloque estático se rechaza", lambda: s.set_dynamic_block_properties(hb, {"X": 1}), "")
    else:
        chk("crear bloque BLQ17", False, b)

    # ---------------------------------------------------------------- escalas de anotación
    r = intento("list_annotation_scales", lambda: s.list_annotation_scales())
    chk("list_annotation_scales trae escalas", r and bueno(r) and len(txt(r)) > 40, r)
    r = intento("add_annotation_scale", lambda: s.add_annotation_scale("1:77", 1, 77))
    chk("add_annotation_scale", bueno(r), r)
    r = intento("list tras agregar", lambda: s.list_annotation_scales())
    chk("1:77 está en la lista", r and "1:77" in txt(r), r)
    r = intento("set_current_annotation_scale", lambda: s.set_current_annotation_scale("1:77"))
    chk("set_current_annotation_scale", bueno(r), r)
    rechaza("no se borra la escala actual", lambda: s.remove_annotation_scale("1:77"), "")
    s.set_current_annotation_scale("1:1")
    r = intento("remove_annotation_scale", lambda: s.remove_annotation_scale("1:77"))
    chk("remove_annotation_scale", bueno(r), r)
    rechaza("add con paper_units 0 se rechaza", lambda: s.add_annotation_scale("1:0", 0, 5), "")

    # ---------------------------------------------------------------- impresión de layouts
    s.create_layout("PL17")
    po = intento("list_plot_options", lambda: s.list_plot_options("PL17"))
    chk("list_plot_options trae dispositivos y papeles", po and bueno(po) and "DWG To PDF" in txt(po), po)
    c = intento("configure_layout", lambda: s.configure_layout(
        "PL17", plot_type="Extents", rotation="Degrees090", centered=True, paper_units="Millimeters",
        scale={"paper": 1, "drawing": 100}))
    chk("configure_layout escala 1:100, rotación, centrado", bueno(c), c)
    c = intento("configure_layout fit", lambda: s.configure_layout("PL17", scale="fit"))
    chk("configure_layout scale=fit", bueno(c), c)
    c = intento("configure_layout ventana", lambda: s.configure_layout("PL17", window=[[0, 0], [100, 100]]))
    chk("configure_layout ventana", bueno(c), c)
    rechaza("papel inexistente se rechaza", lambda: s.configure_layout("PL17", media="PAPEL_QUE_NO_EXISTE"), "")
    rechaza("dispositivo inexistente se rechaza", lambda: s.configure_layout("PL17", device="NO_EXISTE.pc3"), "")
    rechaza("layout inexistente se rechaza", lambda: s.configure_layout("NO_EXISTE_LAYOUT", scale="fit"), "")
    after = intento("el layout sigue sano tras los rechazos", lambda: s.list_plot_options("PL17"))
    chk("estado del layout tras rechazos", after and bueno(after), after)
    s.delete_layout("PL17")

    # ---------------------------------------------------------------- estilos de tabla y de directriz
    r = intento("tablestyle", lambda: s.create_database_object("tablestyle", "TBL17", {}))
    chk("create tablestyle", bueno(r), r)
    ch = intento("list_children tablestyles", lambda: s.list_children("tablestyles"))
    chk("TBL17 aparece", ch and "TBL17" in txt(ch), ch)
    r = intento("delete tablestyle", lambda: s.delete_database_object("tablestyle", "TBL17"))
    chk("delete tablestyle", bueno(r), r)
    rechaza("tablestyle Standard no se borra", lambda: s.delete_database_object("tablestyle", "Standard"), "")
    r = intento("mleaderstyle", lambda: s.create_database_object("mleaderstyle", "ML17", {}))
    chk("create mleaderstyle", bueno(r), r)
    r = intento("delete mleaderstyle", lambda: s.delete_database_object("mleaderstyle", "ML17"))
    chk("delete mleaderstyle", bueno(r), r)

    # ---------------------------------------------------------------- 1.18.0: herramientas de capas
    def capa(nombre):
        for c in s.list_layers().get("layers", []):
            if c.get("name", "").lower() == nombre.lower():
                return c
        return None

    for n in ("LA17", "LB17", "LD17", "LX17"):
        s.create_database_object("layer", n, {})
    s.create_line(0, 200, 5, 200, layer="LA17")
    s.create_line(0, 201, 5, 201, layer="LB17")
    s.create_line(0, 202, 5, 202, layer="LB17")
    m = intento("merge_layers", lambda: s.merge_layers(["LA17", "LB17"], "LD17"))
    chk("merge_layers mueve 3 objetos", m and bueno(m) and m.get("objectsMoved") == 3, m)
    chk("las capas de origen ya no existen", capa("LA17") is None and capa("LB17") is None)
    rechaza("merge_layers a una capa inexistente se rechaza", lambda: s.merge_layers(["LD17"], "NO_EXISTE_17"), "")
    rechaza("merge_layers capa 0 se rechaza", lambda: s.merge_layers(["0"], "LD17"), "")
    d = intento("delete_layer_with_objects sin confirmar", lambda: s.delete_layer_with_objects("LD17"))
    chk("sin confirmar cuenta 3 y no borra", d and d.get("objects") == 3 and d.get("deleted") is False and capa("LD17") is not None, d)
    s.set_current("layer", "LD17")
    rechaza("no se borra la capa actual", lambda: s.delete_layer_with_objects("LD17", True), "")
    s.set_current("layer", "0")
    d = intento("delete_layer_with_objects confirmado", lambda: s.delete_layer_with_objects("LD17", True))
    chk("confirmado borra la capa y sus 3 objetos", d and d.get("deleted") is True and capa("LD17") is None, d)

    # estados de capa (administrador nativo)
    s.create_database_object("layer", "LS17", {})
    r = intento("save_layer_state", lambda: s.save_layer_state("E17", "prueba", ["on", "frozen"]))
    chk("save_layer_state", bueno(r), r)
    l = intento("list_layer_states", lambda: s.list_layer_states())
    chk("E17 aparece en la lista", l and "E17" in txt(l), l)
    r = intento("restore_layer_state", lambda: s.restore_layer_state("E17"))
    chk("restore_layer_state", bueno(r), r)
    rechaza("save_layer_state repetido sin replace se rechaza", lambda: s.save_layer_state("E17"), "")
    r = intento("replace", lambda: s.save_layer_state("E17", replace=True))
    chk("replace=True reemplaza", bueno(r), r)
    r = intento("delete_layer_state", lambda: s.delete_layer_state("E17"))
    chk("delete_layer_state", bueno(r), r)
    rechaza("restore de un estado inexistente se rechaza", lambda: s.restore_layer_state("NO_EXISTE_17"), "")

    # aislar / desaislar con comprobación del encendido real
    s.create_database_object("layer", "LY17", {})
    iso = intento("isolate_layers", lambda: s.isolate_layers(["LS17"], "off"))
    chk("isolate_layers", iso and bueno(iso), iso)
    ly = capa("LY17")
    chk("LY17 quedó apagada", ly and ly.get("off") is True, ly)
    rechaza("no se anida el aislamiento", lambda: s.isolate_layers(["LY17"]), "")
    un = intento("unisolate_layers", lambda: s.unisolate_layers())
    chk("unisolate_layers", un and bueno(un), un)
    ly = capa("LY17")
    chk("LY17 volvió a encenderse", ly and ly.get("off") is False, ly)
    rechaza("unisolate sin aislamiento se rechaza", lambda: s.unisolate_layers(), "")
    iso = intento("isolate lock", lambda: s.isolate_layers(["LS17"], "lock"))
    ly = capa("LY17")
    chk("modo lock bloquea (no apaga)", ly and ly.get("locked") is True and ly.get("off") is False, ly)
    s.unisolate_layers()
    chk("tras unisolate vuelve a desbloquearse", (capa("LY17") or {}).get("locked") is False)

    # capas por viewport
    s.create_layout("VP17")
    vpr = intento("create_viewport", lambda: s.create_viewport("VP17", 150, 100, 100, 80, 0, 0, 100, 1000))
    hv = (vpr or {}).get("handle")
    if hv:
        r = intento("set_viewport_layers congela", lambda: s.set_viewport_layers(hv, freeze=["LS17"]))
        chk("LS17 congelada en el viewport", r and bueno(r) and "LS17" in txt(r), r)
        r = intento("solo informa", lambda: s.set_viewport_layers(hv))
        chk("sin acción informa lo congelado", r and "LS17" in txt(r) and r.get("changed") is False, r)
        chk("la capa NO se congeló en el modelo", (capa("LS17") or {}).get("frozen") is False, capa("LS17"))
        r = intento("set_viewport_layers descongela", lambda: s.set_viewport_layers(hv, thaw_all=True))
        chk("thaw_all la descongela", r and "LS17" not in txt(r.get("frozen", [])), r)
        r = intento("freeze_all_except", lambda: s.set_viewport_layers(hv, freeze_all_except=["LY17"]))
        chk("freeze_all_except congela las otras", r and bueno(r) and r.get("frozenCount", 0) >= 2, r)
        rechaza("capa inexistente en el viewport se rechaza", lambda: s.set_viewport_layers(hv, freeze=["NO_EXISTE_17"]), "")
    else:
        chk("viewport de prueba creado", False, vpr)

    # layouts: copiar y renombrar
    r = intento("copy_layout", lambda: s.copy_layout("VP17", "VP17-COPIA"))
    chk("copy_layout", bueno(r), r)
    lay = s.list_layouts()
    chk("la copia aparece", "VP17-COPIA" in txt(lay), lay)
    r = intento("rename_layout", lambda: s.rename_layout("VP17-COPIA", "VP17-B"))
    chk("rename_layout", bueno(r), r)
    rechaza("rename a un nombre que existe se rechaza", lambda: s.rename_layout("VP17-B", "VP17"), "")
    rechaza("copy_layout de uno inexistente se rechaza", lambda: s.copy_layout("NO_EXISTE_17", "X17"), "")
    s.delete_layout("VP17-B")
    s.delete_layout("VP17")

    # copias en otra versión y en DXF (el dibujo de prueba se guarda primero)
    import os, tempfile
    carpeta = tempfile.mkdtemp(prefix="mcp17_")
    base = os.path.join(carpeta, "base17.dwg")
    s.save_drawing(path=base, overwrite=True)
    for ver in ("2018", "2013"):
        ruta = os.path.join(carpeta, f"copia{ver}.dwg")
        r = intento(f"export_copy {ver}", lambda ruta=ruta, ver=ver: s.export_copy(ruta, ver))
        chk(f"export_copy DWG {ver} escribe y coincide", r and bueno(r) and os.path.exists(ruta) and (r.get("verify") or {}).get("match") is True, r)
    r = intento("export_copy dxf", lambda: s.export_copy(os.path.join(carpeta, "copia.dxf")))
    chk("export_copy DXF escribe", r and bueno(r) and os.path.exists(os.path.join(carpeta, "copia.dxf")), r)
    rechaza("export_copy no pisa sin overwrite", lambda: s.export_copy(os.path.join(carpeta, "copia.dxf")), "")
    rechaza("export_copy sobre el propio dibujo se rechaza", lambda: s.export_copy(base, overwrite=True), "")
    nombre_ok = s.get_drawing_info()
    chk("el dibujo abierto sigue siendo base17.dwg", "base17" in txt(nombre_ok).lower(), nombre_ok)

    # ---------------------------------------------------------------- purga (al final: borra cosas)
    s.create_database_object("layer", "SOBRA17", {})
    s.create_database_object("textstyle", "SOBRA17", {"FileName": "arial.ttf"})
    p = intento("purge dry_run", lambda: s.purge_database_objects(["layer", "textstyle"], dry_run=True))
    chk("dry_run lista SOBRA17 y no borra", p and "SOBRA17" in txt(p), p)
    ly = s.list_layers()
    chk("tras dry_run la capa sigue", "SOBRA17" in txt(ly), ly)
    s.set_current("layer", "0")
    p = intento("purge layer+textstyle", lambda: s.purge_database_objects(["layer", "textstyle"]))
    chk("purge devuelve total >= 2", p and bueno(p) and p.get("total", 0) >= 2, p)
    ly = s.list_layers()
    chk("SOBRA17 ya no está", "SOBRA17" not in txt(ly), ly)
    chk("la capa 0 sobrevive", '"0"' in txt(ly) or "'0'" in txt(ly), ly)
    s.create_line(0, 100, 10, 100)
    s.create_database_object("layer", "USADA17", {})
    s.set_current("layer", "USADA17")
    e = s.create_line(0, 110, 10, 110)["handle"]
    s.set_current("layer", "0")
    p = intento("purge no toca capa con objetos", lambda: s.purge_database_objects(["layer"]))
    ly = s.list_layers()
    chk("USADA17 (con una línea) sobrevive a la purga", "USADA17" in txt(ly), ly)
    rechaza("kind inválido se rechaza", lambda: s.purge_database_objects(["pizza"]), "")

    n = sum(1 for _, ok in R if ok)
    print(f"\nRESULTADO LOTE 1.17.0: {n}/{len(R)} verificaciones OK  (AutoCAD {s.ping().get('pluginVersion')})")
    fallan = [x for x, ok in R if not ok]
    if fallan:
        print("FALLAN:")
        for f in fallan:
            print("  -", f)
    try:
        s.close_document(discard_unsaved=True)
    except Exception:  # noqa: BLE001
        pass
    return 0 if not fallan else 1


if __name__ == "__main__":
    sys.exit(main())
