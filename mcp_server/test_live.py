"""Banco de pruebas contra AutoCAD REAL. Necesita el plugin cargado.

Ejercita todo lo que no se puede verificar sin AutoCAD: las tools que quedaron
sin probar (hatch, leader, offset, bloques, imagen raster) y las nuevas
(splines, layouts, viewports, estilos, documentos).

Dibuja en una zona lejana del origen (x=500) para no pisar lo que tengas, y al
terminar borra todo lo que creó salvo que le pases --keep.

Uso:
  python test_live.py            # prueba y limpia
  python test_live.py --keep     # deja el resultado para mirarlo
"""
from __future__ import annotations

import os
import sys
import traceback

import autocad_client as acad

KEEP = "--keep" in sys.argv
BASE_X, BASE_Y = 500.0, 0.0   # lejos de cualquier dibujo real

# Una definicion de bloque no se puede pisar ni borrar desde el MCP, asi que
# un nombre fijo hace que el test solo pase LA PRIMERA VEZ en cada dibujo: la
# segunda corrida choca con el bloque que dejo la anterior. Con el PID el
# nombre es distinto en cada corrida y el test se vuelve repetible.
BLOCK_NAME = f"PRUEBA_CRUZ_{os.getpid()}"

# Lo que t_layout deja para que t_viewport ubique la ventana sobre el papel real.
LAYOUT: dict[str, object] = {"nombre": "", "ancho": 0.0, "alto": 0.0}

created: list[str] = []
results: list[tuple[str, bool, str]] = []


def run(name: str, fn) -> None:
    """Corre una prueba y anota el resultado sin cortar el resto."""
    try:
        detail = fn()
        results.append((name, True, str(detail)[:110]))
        print(f"  ok   {name}: {str(detail)[:100]}")
    except Exception as exc:  # noqa: BLE001 - queremos seguir probando
        results.append((name, False, str(exc)[:200]))
        print(f" FALLA {name}: {str(exc)[:200]}")


def track(result: dict) -> dict:
    h = result.get("handle")
    if isinstance(h, str):
        created.append(h)
    return result


# ------------------------------------------------- tools que faltaba probar

def t_hatch_solid():
    pl = track(acad.call("create_polyline", {
        "points": [[BASE_X, BASE_Y], [BASE_X + 10, BASE_Y],
                   [BASE_X + 10, BASE_Y + 10], [BASE_X, BASE_Y + 10]],
        "closed": True, "layer": "PRUEBA", "lineweight": 50, "colorIndex": None}))
    h = track(acad.call("create_hatch", {
        "boundaryHandle": pl["handle"], "pattern": "SOLID",
        "scale": 1.0, "angleDeg": 0.0, "layer": "PRUEBA",
        "lineweight": None, "colorIndex": None}))
    return f"solido sobre {pl['handle']} -> {h['handle']}"


def t_hatch_pattern():
    pl = track(acad.call("create_polyline", {
        "points": [[BASE_X + 15, BASE_Y], [BASE_X + 25, BASE_Y],
                   [BASE_X + 25, BASE_Y + 10], [BASE_X + 15, BASE_Y + 10]],
        "closed": True, "layer": "PRUEBA", "lineweight": 50, "colorIndex": None}))
    h = track(acad.call("create_hatch", {
        "boundaryHandle": pl["handle"], "pattern": "ANSI31",
        "scale": 0.5, "angleDeg": 0.0, "layer": "PRUEBA",
        "lineweight": None, "colorIndex": None}))
    return f"ANSI31 -> {h['handle']}"


def t_hatch_circle():
    c = track(acad.call("create_circle", {
        "x": BASE_X + 35, "y": BASE_Y + 5, "z": 0, "radius": 5,
        "layer": "PRUEBA", "lineweight": 50, "colorIndex": None}))
    h = track(acad.call("create_hatch", {
        "boundaryHandle": c["handle"], "pattern": "AR-CONC",
        "scale": 0.1, "angleDeg": 0.0, "layer": "PRUEBA",
        "lineweight": None, "colorIndex": None}))
    return f"AR-CONC en circulo -> {h['handle']}"


def t_leader():
    r = track(acad.call("create_leader", {
        "points": [[BASE_X, BASE_Y + 15], [BASE_X + 5, BASE_Y + 20],
                   [BASE_X + 10, BASE_Y + 20]],
        "text": "DETALLE 1", "textHeight": 1.0, "layer": "PRUEBA",
        "lineweight": None, "colorIndex": None}))
    created.append(r["textHandle"])
    texto = acad.call("get_entity", {"handle": r["textHandle"]})
    if texto.get("text") != "DETALLE 1":
        raise RuntimeError(f"el texto del leader quedo mal: {texto.get('text')!r}")
    return f"leader {r['handle']} + texto asociado {r['textHandle']}"


def t_offset_line():
    ln = track(acad.call("create_line", {
        "x1": BASE_X, "y1": BASE_Y + 30, "z1": 0,
        "x2": BASE_X + 20, "y2": BASE_Y + 30, "z2": 0,
        "layer": "PRUEBA", "lineweight": None, "colorIndex": None}))
    off = track(acad.call("offset_entity", {
        "handle": ln["handle"], "distance": 2.0, "sideX": None, "sideY": None}))
    return f"linea {ln['handle']} -> paralela {off['handle']}"


def t_offset_circle_ambiguo():
    """Un circulo ofrece dos offsets (adentro y afuera): side elige cual.

    Este es el caso que GetOffsetCurves NO resuelve solo: devuelve un lado por
    llamada, asi que hay que pedir los dos y elegir por el punto de referencia.
    """
    c = track(acad.call("create_circle", {
        "x": BASE_X + 40, "y": BASE_Y + 30, "z": 0, "radius": 8,
        "layer": "PRUEBA", "lineweight": None, "colorIndex": None}))

    # side = el centro -> tiene que elegir el de ADENTRO, radio 6.
    dentro = track(acad.call("offset_entity", {
        "handle": c["handle"], "distance": 2.0,
        "sideX": BASE_X + 40, "sideY": BASE_Y + 30}))
    r_dentro = acad.call("get_entity", {"handle": dentro["handle"]}).get("radius")
    if abs(r_dentro - 6.0) > 1e-6:
        raise RuntimeError(
            f"con side en el centro esperaba radio 6 (hacia adentro), dio {r_dentro}")

    # side lejos -> tiene que elegir el de AFUERA, radio 10.
    fuera = track(acad.call("offset_entity", {
        "handle": c["handle"], "distance": 2.0,
        "sideX": BASE_X + 100, "sideY": BASE_Y + 30}))
    r_fuera = acad.call("get_entity", {"handle": fuera["handle"]}).get("radius")
    if abs(r_fuera - 10.0) > 1e-6:
        raise RuntimeError(
            f"con side lejos esperaba radio 10 (hacia afuera), dio {r_fuera}")

    return "adentro 6 / afuera 10, elige por el punto de referencia"


def t_offset_arc():
    a = track(acad.call("create_arc", {
        "x": BASE_X + 60, "y": BASE_Y + 30, "z": 0, "radius": 8,
        "startAngleDeg": 0, "endAngleDeg": 120,
        "layer": "PRUEBA", "lineweight": None, "colorIndex": None}))
    off = track(acad.call("offset_entity", {
        "handle": a["handle"], "distance": 1.5, "sideX": None, "sideY": None}))
    return f"arco -> {off['handle']}"


def t_offset_polilinea():
    pl = track(acad.call("create_polyline", {
        "points": [[BASE_X, BASE_Y + 40], [BASE_X + 10, BASE_Y + 40],
                   [BASE_X + 10, BASE_Y + 50]],
        "closed": False, "layer": "PRUEBA", "lineweight": None, "colorIndex": None}))
    off = track(acad.call("offset_entity", {
        "handle": pl["handle"], "distance": 1.0, "sideX": None, "sideY": None}))
    return f"polilinea -> {off['handle']}"


def t_define_e_insert_block():
    """define_block captura entidades y insert_block las repite."""
    a = acad.call("create_line", {
        "x1": BASE_X + 80, "y1": BASE_Y, "z1": 0,
        "x2": BASE_X + 84, "y2": BASE_Y, "z2": 0,
        "layer": "PRUEBA", "lineweight": None, "colorIndex": None})
    b = acad.call("create_line", {
        "x1": BASE_X + 82, "y1": BASE_Y - 2, "z1": 0,
        "x2": BASE_X + 82, "y2": BASE_Y + 2, "z2": 0,
        "layer": "PRUEBA", "lineweight": None, "colorIndex": None})
    acad.call("define_block", {
        "name": BLOCK_NAME, "handles": [a["handle"], b["handle"]],
        "basePointX": BASE_X + 82, "basePointY": BASE_Y, "basePointZ": 0})
    ins = track(acad.call("insert_block", {
        "name": BLOCK_NAME, "x": BASE_X + 90, "y": BASE_Y, "z": 0,
        "scale": 1.0, "rotationDeg": 0.0, "layer": "PRUEBA",
        "path": None, "attributes": None}))
    return f"bloque definido e insertado -> {ins['handle']}"


def t_insert_block_desde_dwg():
    """insert_block importando la definicion de un DWG externo."""
    path = os.environ.get("ACAD_TEST_DWG")
    if not path:
        raise RuntimeError(
            "sin DWG de prueba: pone ACAD_TEST_DWG=<ruta a un .dwg> para probar esto")
    if not os.path.exists(path):
        raise RuntimeError(f"no existe el DWG: {path}")
    ins = track(acad.call("insert_block", {
        "name": os.path.splitext(os.path.basename(path))[0],
        "x": BASE_X + 110, "y": BASE_Y, "z": 0, "scale": 1.0,
        "rotationDeg": 0.0, "layer": "PRUEBA", "path": path, "attributes": None}))
    return f"importado desde {os.path.basename(path)} -> {ins['handle']}"


def t_attach_image():
    path = os.environ.get("ACAD_TEST_IMAGE")
    if not path:
        raise RuntimeError(
            "sin imagen de prueba: pone ACAD_TEST_IMAGE=<ruta a un .png>")
    if not os.path.exists(path):
        raise RuntimeError(f"no existe la imagen: {path}")
    img = track(acad.call("attach_image", {
        "path": path, "x": BASE_X, "y": BASE_Y + 60, "width": 20,
        "height": None, "layer": "PRUEBA"}))
    return f"imagen colocada -> {img['handle']}"


# --------------------------------------------------------- tools nuevas

def t_ping():
    r = acad.call("ping", {})
    return f"plugin {r.get('pluginVersion')} sobre {r.get('activeDocument')}"


def t_spline():
    r = track(acad.call("create_spline", {
        "points": [[BASE_X, BASE_Y + 90], [BASE_X + 10, BASE_Y + 100],
                   [BASE_X + 20, BASE_Y + 85], [BASE_X + 30, BASE_Y + 95]],
        "closed": False, "layer": "PRUEBA", "lineweight": 35, "colorIndex": None}))
    return f"{r['numFitPoints']} puntos, largo {r.get('length', 0):.2f}"


def t_spline_cerrado():
    r = track(acad.call("create_spline", {
        "points": [[BASE_X + 40, BASE_Y + 90], [BASE_X + 50, BASE_Y + 100],
                   [BASE_X + 60, BASE_Y + 90], [BASE_X + 50, BASE_Y + 80]],
        "closed": True, "layer": "PRUEBA", "lineweight": 35, "colorIndex": None}))
    return f"cerrado, {r['numFitPoints']} puntos"


def t_text_style():
    r = acad.call("set_text_style", {
        "name": "MCP-ARIAL", "font": "arial.ttf", "height": 0.0,
        "widthFactor": 0.9, "oblique": 0.0, "setCurrent": False})
    return f"{r['name']} fuente {r['font']} ancho {r['widthFactor']}"


def t_texto_con_estilo():
    r = track(acad.call("create_text", {
        "text": "ESTILO CON NOMBRE", "x": BASE_X, "y": BASE_Y + 110, "z": 0,
        "height": 2.0, "layer": "PRUEBA", "rotationDeg": 0.0,
        "style": "MCP-ARIAL", "lineweight": None, "colorIndex": None}))
    info = acad.call("get_entity", {"handle": r["handle"]})
    return f"texto {r['handle']} tipo {info.get('type')}"


def t_dim_style():
    r = acad.call("set_dim_style", {
        "name": "MCP-1-50", "textHeight": 0.125, "arrowSize": 0.1,
        "scale": 1.0, "decimalPlaces": 2, "textStyle": "MCP-ARIAL",
        "unitsFactor": None, "extensionOffset": 0.05, "extensionBeyond": 0.05,
        "setCurrent": False})
    return f"{r['name']} texto {r['textHeight']} flecha {r['arrowSize']}"


def t_cota_con_estilo():
    r = track(acad.call("create_dimension", {
        "x1": BASE_X, "y1": BASE_Y + 120, "x2": BASE_X + 20, "y2": BASE_Y + 120,
        "dimLineX": BASE_X + 10, "dimLineY": BASE_Y + 123,
        "layer": "PRUEBA", "scale": None, "style": "MCP-1-50",
        "lineweight": None, "colorIndex": None}))
    return f"medida {r.get('measurement')}"


def t_estilo_inexistente_da_error_claro():
    try:
        acad.call("create_text", {
            "text": "x", "x": BASE_X, "y": BASE_Y, "z": 0, "height": 1,
            "layer": "PRUEBA", "rotationDeg": 0, "style": "NO_EXISTE_ESTE",
            "lineweight": None, "colorIndex": None})
    except acad.AutoCadError as exc:
        if "set_text_style" in str(exc):
            return "error explicativo correcto"
        raise RuntimeError(f"error poco claro: {exc}")
    raise RuntimeError("no dio error con un estilo inexistente")


def t_list_styles():
    r = acad.call("list_styles", {})
    return (f"{len(r['textStyles'])} estilos de texto, "
            f"{len(r['dimStyles'])} de cota")


def t_layout():
    """Crea el layout de prueba, con nombre unico para poder repetir el test."""
    nombre = f"MCP-PRUEBA-{os.getpid()}"
    r = acad.call("create_layout", {
        "name": nombre, "plotConfig": None, "paperSize": "A3"})
    LAYOUT["nombre"] = nombre
    LAYOUT["ancho"] = r["paperWidth"]
    LAYOUT["alto"] = r["paperHeight"]
    return (f"'{r['name']}' papel {r['paperWidth']:.0f}x{r['paperHeight']:.0f} "
            f"({r.get('orientation')}, {r.get('paperName')})")


def t_list_layouts():
    r = acad.call("list_layouts", {})
    nombres = [x["name"] for x in r["layouts"]]
    return f"{nombres}, activo: {r['current']}"


def t_viewport():
    """El viewport se calcula sobre el papel REAL, con margen de 15mm."""
    ancho, alto = LAYOUT["ancho"], LAYOUT["alto"]
    margen = 15.0
    r = acad.call("create_viewport", {
        "layout": LAYOUT["nombre"],
        "centerX": ancho / 2.0, "centerY": alto / 2.0,
        "width": ancho - 2 * margen, "height": alto - 2 * margen,
        "viewCenterX": BASE_X + 20, "viewCenterY": BASE_Y + 20,
        "scaleDenominator": 100.0, "modelUnitsPerMm": 1000.0, "locked": True})
    return (f"{r['width'] if 'width' in r else ancho - 2 * margen:.0f}mm de ancho "
            f"en hoja de {r['paperWidth']:.0f}, escala {r['customScale']}")


def t_viewport_fuera_de_hoja_da_error():
    """Un viewport que no entra tiene que frenarse, no dibujarse cruzando el borde."""
    try:
        acad.call("create_viewport", {
            "layout": LAYOUT["nombre"],
            "centerX": LAYOUT["ancho"], "centerY": LAYOUT["alto"] / 2.0,
            "width": LAYOUT["ancho"], "height": 100.0,
            "viewCenterX": 0, "viewCenterY": 0,
            "scaleDenominator": 100.0, "modelUnitsPerMm": 1000.0,
            "locked": True})
    except acad.AutoCadError as exc:
        if "no entra en la hoja" in str(exc):
            return "lo rechaza y explica por que"
        raise RuntimeError(f"error poco claro: {exc}")
    raise RuntimeError("acepto un viewport que se sale de la hoja")


def t_list_documents():
    r = acad.call("list_documents", {})
    activos = [d["name"] for d in r["documents"] if d["isActive"]]
    return f"{r['count']} abierto(s), activo: {activos}"


def t_set_active_document():
    r = acad.call("list_documents", {})
    activo = next(d for d in r["documents"] if d["isActive"])
    vuelta = acad.call("set_active_document", {"name": activo["name"]})
    return f"reactivar el mismo: changed={vuelta.get('changed')}"


# ------------------------------------------------------------------ main

def t_export_block():
    """Exporta un bloque a DWG; de paso deja el archivo para probar insert."""
    import tempfile
    out = os.path.join(tempfile.gettempdir(), "mcp_prueba_bloque.dwg")
    if os.path.exists(out):
        os.remove(out)
    r = acad.call("export_block", {
        "name": BLOCK_NAME, "path": out, "overwrite": True})
    if not os.path.exists(r["path"]):
        raise RuntimeError("export_block dijo que si pero no hay archivo")
    os.environ.setdefault("ACAD_TEST_DWG", r["path"])
    return f"{os.path.basename(r['path'])} ({r['sizeBytes']} bytes)"


def t_save_drawing():
    import tempfile
    out = os.path.join(tempfile.gettempdir(), "mcp_prueba_dibujo.dwg")
    if os.path.exists(out):
        os.remove(out)
    r = acad.call("save_drawing", {"path": out, "overwrite": True})
    if not os.path.exists(r["path"]):
        raise RuntimeError("save_drawing dijo que si pero no hay archivo")
    size = r["sizeBytes"]
    os.remove(r["path"])
    return f"guardado ({size} bytes) y borrado"


PRUEBAS = [
    ("ping", t_ping),
    ("create_hatch SOLID", t_hatch_solid),
    ("create_hatch ANSI31", t_hatch_pattern),
    ("create_hatch en circulo", t_hatch_circle),
    ("create_leader", t_leader),
    ("offset_entity linea", t_offset_line),
    ("offset_entity circulo (ambiguo)", t_offset_circle_ambiguo),
    ("offset_entity arco", t_offset_arc),
    ("offset_entity polilinea", t_offset_polilinea),
    ("define_block + insert_block", t_define_e_insert_block),
    ("export_block a DWG", t_export_block),
    ("insert_block desde DWG externo", t_insert_block_desde_dwg),
    ("save_drawing", t_save_drawing),
    ("attach_image", t_attach_image),
    ("create_spline", t_spline),
    ("create_spline cerrado", t_spline_cerrado),
    ("set_text_style", t_text_style),
    ("create_text con estilo", t_texto_con_estilo),
    ("set_dim_style", t_dim_style),
    ("create_dimension con estilo", t_cota_con_estilo),
    ("estilo inexistente -> error claro", t_estilo_inexistente_da_error_claro),
    ("list_styles", t_list_styles),
    ("create_layout", t_layout),
    ("list_layouts", t_list_layouts),
    ("create_viewport", t_viewport),
    ("viewport fuera de hoja -> error", t_viewport_fuera_de_hoja_da_error),
    ("list_documents", t_list_documents),
    ("set_active_document", t_set_active_document),
]


def limpiar() -> None:
    """Deja el dibujo como estaba: entidades, layout y bloque de esta corrida.

    Sin esto cada pasada acumula un layout y una definicion de bloque nuevos,
    porque llevan el PID en el nombre para poder repetir el test.
    """
    if created:
        print(f"\nlimpiando {len(created)} entidades...")
        for h in created:
            try:
                acad.call("delete_entity", {"handle": h})
            except acad.AutoCadError:
                pass

    if LAYOUT["nombre"]:
        try:
            acad.call("delete_layout", {"name": LAYOUT["nombre"]})
            print(f"layout {LAYOUT['nombre']} borrado")
        except acad.AutoCadError as exc:
            print(f"no se pudo borrar el layout: {str(exc)[:80]}")

    # El bloque solo se puede purgar despues de borrar sus inserciones.
    try:
        acad.call("purge_block", {"name": BLOCK_NAME})
        print(f"bloque {BLOCK_NAME} purgado")
    except acad.AutoCadError as exc:
        print(f"no se pudo purgar el bloque: {str(exc)[:80]}")


def main() -> int:
    try:
        info = acad.call("get_drawing_info")
    except acad.AutoCadError as exc:
        print(f"No hay conexion con AutoCAD: {exc}")
        return 2
    print(f"dibujo: {info['fileName']} ({info['entityCount']} entidades)\n")

    acad.call("set_layer", {"name": "PRUEBA", "colorIndex": 3,
                            "linetype": None, "lineweightHundredthsMm": 25})

    for nombre, fn in PRUEBAS:
        run(nombre, fn)

    ok = sum(1 for _, good, _ in results if good)
    fallas = [(n, d) for n, good, d in results if not good]

    if not KEEP:
        limpiar()

    print(f"\n{'=' * 60}")
    print(f"{ok}/{len(results)} pruebas OK")
    if fallas:
        print(f"\n{len(fallas)} fallas:")
        for n, d in fallas:
            print(f"  - {n}: {d}")
    return 1 if fallas else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
