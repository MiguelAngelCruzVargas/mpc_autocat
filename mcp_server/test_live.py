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

import math

import annotation as ann
import arch
import autocad_client as acad
import civil
import furniture as fur
import profile as prof
import rules
import sheet
import space

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


skipped: list[tuple[str, str]] = []


class Skip(Exception):
    """La prueba no se puede correr en esta maquina, y no es una falla.

    Algunas necesitan un archivo que depende de quien corra (una imagen, un
    DWG de bloque). Reportarlas como FALLA hace que una corrida sana se vea
    roja, y despues nadie mira las fallas de verdad porque "esas dos siempre
    estan en rojo".
    """


def run(name: str, fn) -> None:
    """Corre una prueba y anota el resultado sin cortar el resto."""
    try:
        detail = fn()
        results.append((name, True, str(detail)[:110]))
        print(f"  ok   {name}: {str(detail)[:100]}")
    except Skip as exc:
        skipped.append((name, str(exc)[:150]))
        print(f"  --   {name}: SALTEADA ({str(exc)[:90]})")
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


def t_mirror_entity():
    """copy=True deja el original y agrega el reflejo; verifica que se
    reflejo de verdad comparando los extremos."""
    line = track(acad.call("create_line", {
        "x1": BASE_X + 130, "y1": BASE_Y, "z1": 0,
        "x2": BASE_X + 135, "y2": BASE_Y + 3, "z2": 0,
        "layer": "PRUEBA", "lineweight": None, "colorIndex": None}))
    espejo = track(acad.call("mirror_entity", {
        "handle": line["handle"], "x1": BASE_X + 130, "y1": BASE_Y - 5,
        "x2": BASE_X + 130, "y2": BASE_Y + 5, "copy": True}))
    original_sigue = acad.call("get_entity", {"handle": line["handle"]})
    reflejo = acad.call("get_entity", {"handle": espejo["handle"]})
    if abs(original_sigue["startPoint"][0] - (BASE_X + 130)) > 1e-6:
        raise RuntimeError("el original se movio, deberia haber quedado igual")
    if reflejo["endPoint"][0] >= BASE_X + 130:
        raise RuntimeError("el reflejo no cruzo el eje de simetria")
    return f"original {line['handle']} intacto, reflejo -> {espejo['handle']}"


def t_array_entity_rectangular():
    c = track(acad.call("create_circle", {
        "x": BASE_X + 145, "y": BASE_Y, "z": 0, "radius": 0.5,
        "layer": "PRUEBA", "lineweight": None, "colorIndex": None}))
    r = acad.call("array_entity", {
        "handle": c["handle"], "mode": "rectangular",
        "rows": 2, "cols": 3, "rowSpacing": 3.0, "colSpacing": 3.0})
    for h in r["handles"]:
        track({"handle": h})
    esperadas = 2 * 3 - 1  # el original ya cuenta como [0,0]
    if len(r["handles"]) != esperadas:
        raise RuntimeError(f"esperaba {esperadas} copias, vinieron {len(r['handles'])}")
    return f"{len(r['handles'])} copias (2x3, original incluido)"


def t_array_entity_polar():
    ln = track(acad.call("create_line", {
        "x1": BASE_X + 160, "y1": BASE_Y, "z1": 0,
        "x2": BASE_X + 162, "y2": BASE_Y, "z2": 0,
        "layer": "PRUEBA", "lineweight": None, "colorIndex": None}))
    r = acad.call("array_entity", {
        "handle": ln["handle"], "mode": "polar",
        "centerX": BASE_X + 160, "centerY": BASE_Y + 5, "count": 4,
        "angleTotal": 360.0, "rotateItems": True})
    for h in r["handles"]:
        track({"handle": h})
    if len(r["handles"]) != 3:
        raise RuntimeError(f"esperaba 3 copias (count=4, original incluido), vinieron {len(r['handles'])}")
    return f"{len(r['handles'])} copias alrededor del centro"


def t_find_replace_text():
    a = track(acad.call("create_text", {
        "text": "LAMINA A-99 PROVISORIA", "x": BASE_X + 170, "y": BASE_Y,
        "z": 0, "height": 1.0, "layer": "PRUEBA", "rotationDeg": 0.0,
        "lineweight": None, "colorIndex": None, "style": None}))
    b = track(acad.call("create_text", {
        "text": "VER LAMINA A-99 PROVISORIA EN PLANTA", "x": BASE_X + 170,
        "y": BASE_Y + 2, "z": 0, "height": 1.0, "layer": "PRUEBA",
        "rotationDeg": 0.0, "lineweight": None, "colorIndex": None, "style": None}))
    r = acad.call("find_replace_text", {
        "find": "A-99 PROVISORIA", "replace": "A-01", "caseSensitive": False})
    if r["count"] < 2:
        raise RuntimeError(f"esperaba tocar 2 textos, toco {r['count']}")
    releido = acad.call("get_entity", {"handle": a["handle"]})
    if "A-01" not in releido["text"]:
        raise RuntimeError(f"no se reemplazo: {releido['text']!r}")
    return f"{r['count']} textos actualizados"


def t_xref_attach_list_detach():
    """Reusa el DWG que t_export_block ya dejo listo (ACAD_TEST_DWG)."""
    path = os.environ.get("ACAD_TEST_DWG")
    if not path:
        raise RuntimeError("sin DWG de prueba: deberia haberlo dejado t_export_block")
    nombre = f"XREF_PRUEBA_{os.getpid()}"
    att = track(acad.call("attach_xref", {
        "path": path, "name": nombre, "x": BASE_X + 190, "y": BASE_Y,
        "z": 0, "scale": 1.0, "rotationDeg": 0.0, "layer": "PRUEBA",
        "lineweight": None, "colorIndex": None}))
    listados = acad.call("list_xrefs", {})
    nombres = [x["name"] for x in listados["xrefs"]]
    if nombre not in nombres:
        raise RuntimeError(f"attach_xref no aparecio en list_xrefs: {nombres}")
    acad.call("detach_xref", {"name": nombre})
    listados2 = acad.call("list_xrefs", {})
    if any(x["name"] == nombre for x in listados2["xrefs"]):
        raise RuntimeError("detach_xref no lo saco de list_xrefs")
    created.remove(att["handle"])  # detach ya se lo llevo puesto
    return f"adjuntado, listado y desprendido: '{nombre}'"


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
        raise Skip("pone ACAD_TEST_DWG=<ruta a un .dwg> para probar esto")
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
        raise Skip("pone ACAD_TEST_IMAGE=<ruta a un .png> para probar esto")
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


def t_check_drawing_hygiene():
    """No afirma un resultado puntual (el dibujo de prueba cambia todo el
    tiempo): solo que corre contra AutoCAD real y devuelve la forma esperada.
    server.acad ES autocad_client (mismo modulo importado), asi que llama al
    plugin real sin mockear nada."""
    import server
    hig = server.check_drawing_hygiene()
    for campo in ("ok", "emptyLayers", "shxTextStyles", "duplicates", "problems"):
        if campo not in hig:
            raise RuntimeError(f"check_drawing_hygiene no devolvio '{campo}'")
    return f"ok={hig['ok']}, {len(hig['problems'])} problema(s)"


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


def t_export_pdf():
    """Exporta el layout de prueba a PDF por API, confirma que el archivo
    existe y que no dejo cambiado el layout activo (el bug real: AutoCAD
    exige que el layout ploteado sea el actual, 'eLayoutNotCurrent' si no)."""
    import tempfile
    activo_antes = acad.call("list_layouts", {})["current"]
    out = os.path.join(tempfile.gettempdir(), f"mcp_prueba_layout_{os.getpid()}.pdf")
    if os.path.exists(out):
        os.remove(out)
    r = acad.call("export_pdf", {"layout": LAYOUT["nombre"], "path": out, "device": None})
    if not os.path.exists(r["path"]) or os.path.getsize(r["path"]) == 0:
        raise RuntimeError("export_pdf dijo que si pero no hay archivo (o esta vacio)")
    size = os.path.getsize(r["path"])
    os.remove(r["path"])
    activo_despues = acad.call("list_layouts", {})["current"]
    if activo_despues != activo_antes:
        raise RuntimeError(
            f"export_pdf dejo cambiado el layout activo: era '{activo_antes}', "
            f"quedo '{activo_despues}'")
    return f"{r['device']} -> {size} bytes, layout activo sin cambios, borrado"


def t_capture_viewport():
    """Foto PNG del espacio activo (lo que este activo en ese momento)."""
    import tempfile
    out = os.path.join(tempfile.gettempdir(), f"mcp_prueba_captura_{os.getpid()}.png")
    if os.path.exists(out):
        os.remove(out)
    r = acad.call("capture_viewport", {"path": out, "layout": None})
    if not os.path.exists(r["path"]) or os.path.getsize(r["path"]) == 0:
        raise RuntimeError("capture_viewport dijo que si pero no hay archivo (o esta vacio)")
    size = os.path.getsize(r["path"])
    os.remove(r["path"])
    return f"espacio {r['space']} ({r['layout']}) -> {size} bytes, borrado"


def t_undo():
    """Dibuja un circulo, lo deshace, y confirma que ya no esta."""
    import time
    r = acad.call("create_circle", {
        "x": BASE_X + 300, "y": BASE_Y, "z": 0, "radius": 1.0,
        "layer": "PRUEBA", "lineweight": None, "colorIndex": None})
    handle = r["handle"]
    acad.call("undo", {"steps": 1})
    # SendStringToExecute encola: darle a AutoCAD un margen para procesarlo
    # antes de confirmar que el circulo ya no esta.
    for _ in range(20):
        try:
            acad.call("get_entity", {"handle": handle})
        except acad.AutoCadError:
            return "el circulo desapareció tras el undo"
        time.sleep(0.25)
    raise RuntimeError("el circulo sigue estando despues de esperar el undo")


def t_rebar_elevation():
    """El armado en elevacion, y CONTADO en el dibujo -- no creyendole al
    valor que devolvio la tool. Nunca corrio contra AutoCAD hasta que se
    verifico a mano, y ahi aparecio que el perimetro del estribo salia 4x."""
    import rebar
    r = rebar.create_rebar_elevation(
        x=BASE_X + 180, y=BASE_Y, width=0.40, height=2.40, depth=0.40,
        stirrup_spacing=0.20, bars_interior=1, cover=0.03,
        confinement_length=0.50, confinement_spacing=0.10)
    for h in r["handles"]:
        track({"handle": h})

    lineas = 0
    for h in r["handles"]:
        if acad.call("get_entity", {"handle": h})["type"] == "Line":
            lineas += 1
    esperado = r["stirrupCount"] + r["barCount"]
    if lineas != esperado:
        raise RuntimeError("hay %d lineas dibujadas y la tool dijo %d"
                           % (lineas, esperado))

    # 0.40x0.40 con 3 cm de recubrimiento: el estribo es 0.34x0.34.
    if abs(r["stirrupPerimeter_m"] - 1.36) > 1e-6:
        raise RuntimeError("el perimetro del estribo dio %.3f y son 1.360"
                           % r["stirrupPerimeter_m"])
    return ("%d estribos (confinados), %d varillas, perimetro %.3f m"
            % (r["stirrupCount"], r["barCount"], r["stirrupPerimeter_m"]))


def t_rebar_elevation_sin_depth_no_inventa():
    """Una elevacion no ve la dimension de afuera del plano."""
    import rebar
    r = rebar.create_rebar_elevation(
        x=BASE_X + 185, y=BASE_Y, width=0.30, height=1.0,
        stirrup_spacing=0.20)
    for h in r["handles"]:
        track({"handle": h})
    if r["stirrupPerimeter_m"] is not None:
        raise RuntimeError("invento un perimetro sin saber la profundidad")
    if not any("depth" in a for a in r["warnings"]):
        raise RuntimeError("no explico por que no lo da")
    return "sin depth devuelve None y lo explica"


def t_compose_sheet():
    """Acomodar dos vistas y verificar que quedaron alineadas EN EL DIBUJO."""
    import compose
    import space as space_mod
    a = track(acad.call("create_polyline", {
        "points": [[BASE_X + 200, BASE_Y], [BASE_X + 202, BASE_Y],
                   [BASE_X + 202, BASE_Y + 3], [BASE_X + 200, BASE_Y + 3]],
        "closed": True, "layer": "PRUEBA", "lineweight": None,
        "colorIndex": None}))["handle"]
    b = track(acad.call("create_polyline", {
        "points": [[BASE_X + 210, BASE_Y + 20], [BASE_X + 211, BASE_Y + 20],
                   [BASE_X + 211, BASE_Y + 21], [BASE_X + 210, BASE_Y + 21]],
        "closed": True, "layer": "PRUEBA", "lineweight": None,
        "colorIndex": None}))["handle"]

    escala = space_mod.units_per_paper_mm()
    r = compose.compose_sheet(
        [{"name": "grande", "box": [BASE_X + 200, BASE_Y,
                                    BASE_X + 202, BASE_Y + 3],
          "handles": [a]},
         {"name": "chica", "box": [BASE_X + 210, BASE_Y + 20,
                                   BASE_X + 211, BASE_Y + 21],
          "handles": [b], "below": "grande"}],
        area=[BASE_X + 230, BASE_Y, BASE_X + 260, BASE_Y + 30],
        scale=escala, draw_titles=False)

    # La verificacion de verdad: donde quedaron las entidades.
    cajas = {}
    for nombre, h in (("grande", a), ("chica", b)):
        pts = acad.call("get_entity", {"handle": h})["points"]
        xs = [p[0] for p in pts]
        cajas[nombre] = (min(xs) + max(xs)) / 2.0
    if abs(cajas["grande"] - cajas["chica"]) > 1e-6:
        raise RuntimeError("los centros no quedaron alineados: %s" % cajas)
    return "2 vistas apiladas, centros alineados en el dibujo"


def t_compose_sheet_avisa_huerfanas():
    """Con handles a mano es facil dejarse algo adentro de la caja."""
    import compose
    import space as space_mod
    p1 = track(acad.call("create_polyline", {
        "points": [[BASE_X + 300, BASE_Y], [BASE_X + 302, BASE_Y],
                   [BASE_X + 302, BASE_Y + 2], [BASE_X + 300, BASE_Y + 2]],
        "closed": True, "layer": "PRUEBA", "lineweight": None,
        "colorIndex": None}))["handle"]
    track(acad.call("create_line", {
        "x1": BASE_X + 300.5, "y1": BASE_Y + 0.5, "z1": 0,
        "x2": BASE_X + 301.5, "y2": BASE_Y + 1.5, "z2": 0,
        "layer": "PRUEBA", "lineweight": None, "colorIndex": None}))

    r = compose.compose_sheet(
        [{"name": "vista", "box": [BASE_X + 300, BASE_Y,
                                   BASE_X + 302, BASE_Y + 2],
          "handles": [p1]}],
        area=[BASE_X + 320, BASE_Y, BASE_X + 340, BASE_Y + 20],
        scale=space_mod.units_per_paper_mm(), draw_titles=False)
    if not r.get("orphaned"):
        raise RuntimeError("no aviso de la linea que se quedaba atras")
    return "aviso: %s" % r["orphaned"]


def t_compose_layout():
    """Un layout con su viewport, y se le LEE la escala al viewport."""
    import compose
    nombre = "MCP-VERIF"
    try:
        acad.call("delete_layout", {"name": nombre})
    except acad.AutoCadError:
        pass
    r = compose.compose_layout(
        nombre, views=[{"name": "detalle",
                        "box": [BASE_X + 180, BASE_Y, BASE_X + 183,
                                BASE_Y + 3],
                        "scale_denominator": 25, "title": "DETALLE"}],
        model_units="m", paper_size="A1", draw_titles=False)

    h = r["viewports"][0]["handle"]
    e = acad.call("get_entity", {"handle": h})
    cs = e.get("customScale") or 0
    if not cs:
        raise RuntimeError("el viewport no reporta escala")
    denom = 1000.0 / cs           # modelo en metros, papel en mm
    if abs(denom - 25) > 0.5:
        raise RuntimeError("quedo en 1:%.1f y se pidio 1:25" % denom)
    acad.call("delete_layout", {"name": nombre})
    return "layout %.0fx%.0f mm, viewport medido en 1:%.0f" % (
        r["paper"][0], r["paper"][1], denom)


def t_close_document():
    """Crear uno, cerrarlo, y que el descarte sea explicito."""
    antes = acad.call("list_documents", {})["count"]
    acad.call("new_document", {})
    try:
        acad.call("close_document", {"name": None, "save": False,
                                     "discardUnsaved": False})
        raise RuntimeError("cerro sin que nadie lo autorizara a descartar")
    except acad.AutoCadError as exc:
        if "discardUnsaved" not in str(exc):
            raise RuntimeError("el error no dice como autorizarlo: %s" % exc)
    r = acad.call("close_document", {"name": None, "save": False,
                                     "discardUnsaved": True})
    despues = acad.call("list_documents", {})["count"]
    if despues != antes:
        raise RuntimeError("quedaron %d dibujos y habia %d" % (despues, antes))
    return "descarte explicito, y volvio a %s" % r["active"]


def t_simbolos_de_convencion():
    """Nivel, titulo de vista y marca de corte contra AutoCAD real.

    Son composicion pura de Python, pero el relleno SOLID del triangulo y la
    marca de corte solo se puede confirmar contra el motor de hatch de verdad:
    un patron que el dibujo no acepta devuelve None en silencio.
    """
    import symbols
    x0, y0 = BASE_X + 150, BASE_Y
    h = 0.125

    niv = symbols.create_level_mark(x=x0, y=y0 + 5.0, elevation=5.0,
                                    height=h, side="left", suffix="MTS")
    for hd in niv["handles"]:
        track({"handle": hd})
    if "+ 5.00" not in niv["text"]:
        raise RuntimeError("el nivel no dice '+ 5.00': %r" % niv["text"])

    cero = symbols.create_level_mark(x=x0, y=y0, elevation=0.0, height=h,
                                     side="left", suffix="MTS")
    for hd in cero["handles"]:
        track({"handle": hd})
    if "±" not in cero["text"]:
        raise RuntimeError("el cero tiene que llevar mas-menos: %r" % cero["text"])

    tit = symbols.create_view_title(x=x0, y=y0 - 2.0, title="CORTE A-A",
                                    scale_text="ESC. 1:50", height=0.20)
    for hd in tit["handles"]:
        track({"handle": hd})
    if tit["width"] <= 0:
        raise RuntimeError("el titulo no midio su propio ancho")

    marca = symbols.create_section_mark(x1=x0 + 5, y1=y0 + 1, x2=x0 + 12,
                                        y2=y0 + 1, label="A", height=0.15)
    for hd in marca["handles"]:
        track({"handle": hd})

    return ("nivel +5.00 y +-0.00, titulo (%.2f de ancho) y marca de corte A"
            % tit["width"])


def t_familia_de_dimstyles():
    """La familia COTAS25/50/100/150 queda REALMENTE en el dibujo."""
    import annotation
    r = annotation.set_dim_style_family(model_units="m", paper_mm=2.0)
    esperado = {"COTAS25": 0.05, "COTAS50": 0.10,
                "COTAS100": 0.20, "COTAS150": 0.30}

    estilos = {e["name"]: e["textHeight"]
               for e in acad.call("list_styles", {})["dimStyles"]}
    faltan = [n for n in esperado if n not in estilos]
    if faltan:
        raise RuntimeError("no quedaron en el dibujo: %s" % faltan)
    for nombre, alto in esperado.items():
        if abs(estilos[nombre] - alto) > 1e-6:
            raise RuntimeError("%s quedo en %s y esperaba %s"
                               % (nombre, estilos[nombre], alto))
    return "%d estilos, alturas como el plano de referencia" % r["count"]


def t_list_documents():
    r = acad.call("list_documents", {})
    activos = [d["name"] for d in r["documents"] if d["isActive"]]
    return f"{r['count']} abierto(s), activo: {activos}"


def t_set_active_document():
    r = acad.call("list_documents", {})
    activo = next(d for d in r["documents"] if d["isActive"])
    vuelta = acad.call("set_active_document", {"name": activo["name"]})
    return f"reactivar el mismo: changed={vuelta.get('changed')}"


def _volver_a(nombre: str) -> None:
    """Deja activo el dibujo con el que venía corriendo la suite. Todo lo que
    sigue dibuja sobre el ACTIVO, así que un test que cambia de documento
    tiene que devolverlo o rompe a los que vienen atrás."""
    acad.call("set_active_document", {"name": nombre})


def t_new_document():
    """Verifica de paso el fix del lock: abrir o crear un dibujo teniendo
    tomado el lock de otro tira eLockViolation, por eso open_document y
    new_document corren fuera del lock (ver CommandDispatcher.RunsUnlocked).
    Si eso está mal, este test falla con 'eLockViolation'."""
    antes = acad.call("list_documents", {})
    original = next(d for d in antes["documents"] if d["isActive"])["name"]
    try:
        r = acad.call("new_document", {})
        if not r.get("active"):
            raise RuntimeError("new_document no devolvió el dibujo activo")
        despues = acad.call("list_documents", {})
        if despues["count"] != antes["count"] + 1:
            raise RuntimeError(
                f"esperaba {antes['count'] + 1} dibujos abiertos, "
                f"hay {despues['count']}")
        return f"creó {r['active']} (queda abierto, cerralo a mano)"
    finally:
        _volver_a(original)


def t_open_document():
    """Abre el DWG que dejó export_block más arriba en esta misma corrida.
    No inventa una ruta: si el archivo no está, es que falló export_block."""
    ruta = os.environ.get("ACAD_TEST_DWG")
    if not ruta or not os.path.exists(ruta):
        raise RuntimeError(
            "sin DWG de prueba: este caso va DESPUÉS de export_block, que es "
            "el que deja ACAD_TEST_DWG. Si export_block falló, arreglá eso.")

    antes = acad.call("list_documents", {})
    original = next(d for d in antes["documents"] if d["isActive"])["name"]
    try:
        r = acad.call("open_document", {"path": ruta, "readOnly": True})
        if not r.get("isReadOnly"):
            raise RuntimeError("se pidió readOnly y abrió para escritura")

        # Segunda vez sobre el mismo archivo: NO tiene que reabrirlo, porque
        # perdería los cambios sin guardar del que ya está abierto.
        otra = acad.call("open_document", {"path": ruta, "readOnly": True})
        if not otra.get("alreadyOpen"):
            raise RuntimeError(
                "reabrió un dibujo que ya estaba abierto (alreadyOpen=False)")
        return f"{r['active']} readOnly, y la 2da vez avisó alreadyOpen"
    finally:
        _volver_a(original)


def t_open_document_inexistente_da_error_claro():
    try:
        acad.call("open_document", {"path": "C:/no/existe/jamas_de_los_jamases.dwg"})
    except acad.AutoCadError as exc:
        if "no existe" not in str(exc).lower():
            raise RuntimeError(f"el error no dice que no existe: {exc}")
        return "avisa que el archivo no existe"
    raise RuntimeError("abrió un archivo que no existe")


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


# ================================================ geometria con arcos

def t_polilinea_con_bulge():
    """Un cuarto de circulo de R=10: el largo tiene que ser el del ARCO."""
    # bulge = tan(90/4) = 0.41421...
    b = math.tan(math.radians(90) / 4.0)
    r = track(acad.call("create_polyline", {
        "points": [[BASE_X, BASE_Y + 150], [BASE_X + 10, BASE_Y + 160]],
        "bulges": [b, 0.0], "closed": False, "layer": "PRUEBA",
        "lineweight": 25, "colorIndex": None}))
    esperado = math.pi * 10 / 2.0            # 15.708, no la cuerda de 14.142
    got = r.get("length", 0)
    if abs(got - esperado) > 0.05:
        raise RuntimeError(
            f"largo {got:.3f}, esperaba el arco {esperado:.3f} "
            f"(la cuerda seria {math.dist((0,0),(10,10)):.3f})")
    return f"arco de 90 grados: largo {got:.3f} (cuerda {14.142:.3f})"


def t_leer_bulges():
    """get_entity tiene que devolver el bulge con el que se dibujo."""
    b = 0.3
    r = track(acad.call("create_polyline", {
        "points": [[BASE_X + 20, BASE_Y + 150], [BASE_X + 30, BASE_Y + 150],
                   [BASE_X + 40, BASE_Y + 160]],
        "bulges": [b, 0.0, 0.0], "closed": False, "layer": "PRUEBA",
        "lineweight": 25, "colorIndex": None}))
    d = acad.call("get_entity", {"handle": r["handle"]})
    if "bulges" not in d:
        raise RuntimeError("get_entity no devolvio 'bulges'")
    if abs(d["bulges"][0] - b) > 1e-6:
        raise RuntimeError(f"bulge leido {d['bulges'][0]}, se dibujo {b}")
    if not d.get("hasArcs"):
        raise RuntimeError("hasArcs deberia ser True")
    return f"bulges {[round(x, 3) for x in d['bulges']]} hasArcs={d['hasArcs']}"


def t_leer_patron_de_hatch():
    pl = track(acad.call("create_polyline", {
        "points": [[BASE_X + 60, BASE_Y + 150], [BASE_X + 70, BASE_Y + 150],
                   [BASE_X + 70, BASE_Y + 160], [BASE_X + 60, BASE_Y + 160]],
        "bulges": None, "closed": True, "layer": "PRUEBA",
        "lineweight": 25, "colorIndex": None}))
    h = track(acad.call("create_hatch", {
        "boundaryHandle": pl["handle"], "pattern": "ANSI31", "scale": 0.5,
        "angleDeg": 0.0, "layer": "PRUEBA",
        "lineweight": None, "colorIndex": None}))
    d = acad.call("get_entity", {"handle": h["handle"]})
    if d.get("patternName", "").upper() != "ANSI31":
        raise RuntimeError(f"patron leido {d.get('patternName')!r}, se puso ANSI31")
    return f"{d['patternName']} escala {d.get('patternScale')}"


# ============================================================ cotas nuevas

def t_cota_rotada():
    """Proyectada a 0 grados mide la componente horizontal, no la diagonal."""
    r = track(acad.call("create_dimension_rotated", {
        "x1": BASE_X, "y1": BASE_Y + 170, "x2": BASE_X + 30, "y2": BASE_Y + 180,
        "dimLineX": BASE_X + 15, "dimLineY": BASE_Y + 190, "angleDeg": 0.0,
        "layer": "PRUEBA", "style": None, "scale": None, "text": None,
        "lineweight": 13, "colorIndex": None}))
    m = r.get("measurement", 0)
    if abs(m - 30.0) > 0.01:
        raise RuntimeError(f"midio {m:.3f}, la horizontal es 30 "
                           f"(la diagonal seria {math.hypot(30, 10):.3f})")
    return f"horizontal {m:.2f} (diagonal {math.hypot(30, 10):.2f})"


def t_cota_radial():
    c = track(acad.call("create_circle", {
        "x": BASE_X + 60, "y": BASE_Y + 180, "z": 0, "radius": 12,
        "layer": "PRUEBA", "lineweight": None, "colorIndex": None}))
    r = track(acad.call("create_dimension_radial", {
        "handle": c["handle"], "leaderLengthFactor": 1.5, "layer": "PRUEBA",
        "style": None, "scale": None, "text": None,
        "lineweight": 13, "colorIndex": None}))
    if abs(r.get("radius", 0) - 12.0) > 1e-6:
        raise RuntimeError(f"radio {r.get('radius')}, esperaba 12")
    return f"R={r['radius']}"


def t_cota_diametral():
    c = track(acad.call("create_circle", {
        "x": BASE_X + 95, "y": BASE_Y + 180, "z": 0, "radius": 8,
        "layer": "PRUEBA", "lineweight": None, "colorIndex": None}))
    r = track(acad.call("create_dimension_diametric", {
        "handle": c["handle"], "leaderLengthFactor": 1.5, "layer": "PRUEBA",
        "style": None, "scale": None, "text": None,
        "lineweight": 13, "colorIndex": None}))
    if abs(r.get("diameter", 0) - 16.0) > 1e-6:
        raise RuntimeError(f"diametro {r.get('diameter')}, esperaba 16")
    return f"D={r['diameter']}"


def t_cota_angular():
    r = track(acad.call("create_dimension_angular", {
        "vertexX": BASE_X, "vertexY": BASE_Y + 200,
        "x1": BASE_X + 20, "y1": BASE_Y + 200,
        "x2": BASE_X, "y2": BASE_Y + 220,
        "arcX": BASE_X + 8, "arcY": BASE_Y + 208,
        "layer": "PRUEBA", "style": None, "scale": None, "text": None,
        "lineweight": 13, "colorIndex": None}))
    grados = r.get("measurementDeg", 0)
    if abs(grados - 90.0) > 0.1:
        raise RuntimeError(f"midio {grados:.2f} grados, esperaba 90")
    return f"{grados:.1f} grados"


def t_cota_desarrollo():
    """El desarrollo de un arco es R*theta, no la cuerda."""
    a = track(acad.call("create_arc", {
        "x": BASE_X + 130, "y": BASE_Y + 180, "z": 0, "radius": 20,
        "startAngleDeg": 0, "endAngleDeg": 90,
        "layer": "PRUEBA", "lineweight": None, "colorIndex": None}))
    r = track(acad.call("create_dimension_arc_length", {
        "handle": a["handle"], "arcX": BASE_X + 155, "arcY": BASE_Y + 205,
        "layer": "PRUEBA", "style": None, "scale": None, "text": None,
        "lineweight": 13, "colorIndex": None}))
    esperado = math.pi * 20 / 2.0
    got = r.get("developedLength", 0)
    if abs(got - esperado) > 0.01:
        raise RuntimeError(f"desarrollo {got:.3f}, esperaba {esperado:.3f}")
    return f"{got:.2f} m con R=20 y 90 grados"


# ====================================================== obra civil

def t_alineamiento():
    a = civil.create_alignment(BASE_X + 200, BASE_Y, -90, [
        {"type": "tangent", "length": 40},
        {"type": "curve", "radius": 90, "length": 107, "direction": "left"}])
    if abs(a["length"] - 147.0) > 1e-6:
        raise RuntimeError(f"largo {a['length']}, esperaba 147")
    return f"147.00 m, {len(a['stations'])} puntos notables"


def t_alineamiento_con_espiral():
    a = civil.create_alignment(BASE_X + 320, BASE_Y, -90, [
        {"type": "tangent", "length": 20},
        {"type": "spiral", "radius": 60, "length": 24, "direction": "left"},
        {"type": "curve", "radius": 60, "length": 40, "direction": "left"}])
    if abs(a["length"] - 84.0) > 1e-6:
        raise RuntimeError(f"largo {a['length']}, esperaba 84")
    esp = [s for s in a["stations"] if s["type"] == "fin de espiral"][0]
    esperado_a = math.sqrt(60 * 24)
    if abs(esp["parameter"] - esperado_a) > 1e-6:
        raise RuntimeError(f"parametro A={esp['parameter']}, esperaba {esperado_a}")
    return f"84.00 m, espiral A={esp['parameter']:.2f}"


def t_calle_ancho_variable():
    a = civil.create_alignment(BASE_X + 420, BASE_Y, -90, [
        {"type": "tangent", "length": 100}])
    r = civil.create_road(points=a["points"], bulges=a["bulges"],
                          widths=[[0, 8.0], [100, 4.0]], curb_width=0.35)
    # Ancho medio de 8 a 4 sobre 100 m = 6 -> 600 m2.
    if abs(r["pavementArea"] - 600.0) > 5.0:
        raise RuntimeError(f"area {r['pavementArea']:.2f}, esperaba ~600")
    for h in r.get("curbHandles", []):
        created.append(h)
    created.append(r["pavementHandle"])
    return f"area {r['pavementArea']:.2f} m2 con ancho 8->4"


def t_guarnicion_por_tramo():
    a = civil.create_alignment(BASE_X + 460, BASE_Y, -90, [
        {"type": "tangent", "length": 100}])
    r = civil.create_road(points=a["points"], bulges=a["bulges"], width=7.0,
                          curb_width=0.35,
                          curb_segments=[{"side": "left"},
                                         {"side": "right", "from": 0, "to": 40}])
    if abs(r["curbLength"] - 140.0) > 0.5:
        raise RuntimeError(f"guarnicion {r['curbLength']:.2f} ml, esperaba 140")
    for h in r.get("curbHandles", []):
        created.append(h)
    created.append(r["pavementHandle"])
    return f"{r['curbLength']:.2f} ml (100 izq + 40 der)"


def t_interseccion():
    principal = civil.create_alignment(BASE_X + 520, BASE_Y, -90, [
        {"type": "tangent", "length": 80}])
    nace = civil.point_on_road(principal["points"], 40.0)
    ramal = civil.create_alignment(nace["x"], nace["y"], 0.0, [
        {"type": "tangent", "length": 30}])
    r = civil.create_intersection(
        main_points=principal["points"], branch_points=ramal["points"],
        main_width=7.0, branch_width=5.5, radius=6.0)
    if abs(r["branchStation"] - 40.0) > 2.0:
        raise RuntimeError(
            f"detecto el ramal en est {r['branchStation']}, nace en 40")
    for arc in r["arcs"]:
        created.append(arc["handle"])
    return (f"ramal en est {r['branchStation']}, "
            f"{len(r['arcs'])} acuerdos, {r['curbLength']:.2f} ml")


# ================================================ perfil y secciones

def t_rasante_en_pvi():
    """En un PVI sin curva vertical la cota tiene que ser exacta."""
    pvis = [{"station": 0, "elevation": 100.0},
            {"station": 100, "elevation": 105.0}]
    got = prof.grade_elevation(pvis, 50.0)
    if abs(got - 102.5) > 1e-9:
        raise RuntimeError(f"cota en est 50 = {got}, esperaba 102.5")
    if abs(prof.grade_elevation(pvis, 0.0) - 100.0) > 1e-9:
        raise RuntimeError("la cota en el PVI inicial no coincide")
    return "interpolacion lineal correcta"


def t_perfil():
    r = prof.create_profile(
        x=BASE_X + 200, y=BASE_Y + 240, length=100.0,
        pvis=[{"station": 0, "elevation": 100.0},
              {"station": 50, "elevation": 103.0, "curve_length": 20},
              {"station": 100, "elevation": 101.0}],
        ground=[[0, 99.5], [50, 103.5], [100, 100.5]],
        h_scale=1.0, v_exag=5.0, grid_station=25.0, grid_elevation=1.0,
        text_height=0.8)
    if len(r["grades"]) != 2:
        raise RuntimeError(f"{len(r['grades'])} tramos de pendiente, esperaba 2")
    p1 = r["grades"][0]["gradePercent"]
    if abs(p1 - 6.0) > 0.01:
        raise RuntimeError(f"primera pendiente {p1:.2f}%, esperaba 6.00")
    return (f"{len(r['grades'])} pendientes ({p1:+.2f}% y "
            f"{r['grades'][1]['gradePercent']:+.2f}%), datum {r['datum']}")


def t_secciones():
    r = prof.create_cross_section_series(
        x=BASE_X + 200, y=BASE_Y + 300, stations=[0, 50, 100], width=7.0,
        pvis=[{"station": 0, "elevation": 100.0},
              {"station": 100, "elevation": 102.0}],
        ground=[[0, 99.0], [50, 102.0], [100, 101.0]],
        columns=3, depth=0.30, text_height=0.6)
    if r["count"] != 3:
        raise RuntimeError(f"{r['count']} secciones, esperaba 3")
    # est 0: terreno 99 < rasante 100 -> terraplen; est 50: 102 > 101 -> corte
    if r["sections"][0]["type"] != "terraplen":
        raise RuntimeError(f"est 0 salio {r['sections'][0]['type']}, es terraplen")
    if r["sections"][1]["type"] != "corte":
        raise RuntimeError(f"est 50 salio {r['sections'][1]['type']}, es corte")
    esperado_vol = 7.0 * 0.30 * 100.0
    if abs(r["volume"] - esperado_vol) > 1.0:
        raise RuntimeError(f"volumen {r['volume']}, esperaba {esperado_vol}")
    return f"{r['count']} secciones, volumen {r['volume']} m3"


# ============================================== documentacion y lamina

def t_tabla():
    r = ann.create_table(
        x=BASE_X + 200, y=BASE_Y + 130, text_height=1.0, row_height=2.5,
        col_widths=[10.0, 20.0, 8.0], title="RESUMEN",
        rows=[["CLAVE", "CONCEPTO", "CANT"],
              ["01", "Pavimento", "925"],
              ["02", "Guarnicion", "210"]])
    if r["rows"] != 3:
        raise RuntimeError(f"{r['rows']} filas, esperaba 3")
    return f"{r['rows']} filas, ancho {r['width']:.1f}"


def t_leyenda():
    r = ann.create_legend(
        x=BASE_X + 260, y=BASE_Y + 130, text_height=1.0,
        items=[{"label": "PAVIMENTO", "pattern": "AR-CONC", "scale": 0.5},
               {"label": "BASE", "pattern": "ANSI31", "scale": 0.5},
               {"label": "EJE", "color_index": 1}])
    if r["items"] != 3:
        raise RuntimeError(f"{r['items']} items, esperaba 3")
    return f"{r['items']} items"


def t_cadenamiento_plain():
    a = civil.create_alignment(BASE_X + 600, BASE_Y, -90, [
        {"type": "tangent", "length": 60}])
    r = ann.create_stationing(points=a["points"], interval=20.0,
                              text_height=1.0, station_format="plain")
    etiquetas = [m["station"] for m in r["stations"]]
    if "20.00" not in etiquetas:
        raise RuntimeError(f"formato plain deberia dar '20.00', dio {etiquetas}")
    return f"{r['marks']} marcas: {etiquetas[:4]}"


def t_corte_por_capas():
    """El espesor rotulado es el REAL aunque el dibujo este exagerado."""
    r = ann.create_layer_section(
        x=BASE_X + 320, y=BASE_Y + 130, width=12.0, text_height=0.8,
        draw_scale=20.0,
        layers=[{"name": "CONCRETO", "thickness": 0.15, "pattern": "AR-CONC",
                 "scale": 0.3},
                {"name": "BASE", "thickness": 0.10, "pattern": "ANSI31",
                 "scale": 0.5}])
    if abs(r["totalThickness"] - 0.25) > 1e-9:
        raise RuntimeError(
            f"espesor real {r['totalThickness']}, esperaba 0.25 "
            "(draw_scale no debe afectar el valor rotulado)")
    return f"espesor real {r['totalThickness'] * 100:.0f} cm, dibujado 20x"


def t_lamina():
    r = sheet.create_sheet(
        sheet_format="A3", scale_denominator=100.0, model_units="m",
        project="PRUEBA", location="", client="", content="TEST",
        drawn_by="", reviewed_by="", date="", sheet_number="X-01",
        origin_x=BASE_X + 700, origin_y=BASE_Y)
    a = r["drawArea"]
    if a["x2"] <= a["x1"] or a["y2"] <= a["y1"]:
        raise RuntimeError("el area util salio invertida o vacia")
    return f"{r['format']} {r['scale']}, util {a['x2']-a['x1']:.1f} m"


def t_mobiliario_y_rotulos():
    fur.reset_footprints()
    cuarto = (BASE_X + 700, BASE_Y + 100, BASE_X + 710, BASE_Y + 108)
    fur.place([{"type": "bed", "x": cuarto[0] + 0.3, "y": cuarto[1] + 0.3,
                "width": 1.6, "length": 2.0}])
    r = fur.label_rooms(
        [{"name": "RECAMARA", "x0": cuarto[0], "y0": cuarto[1],
          "x1": cuarto[2], "y1": cuarto[3]}], height=0.5)
    et = r["labeled"][0]
    dentro = (cuarto[0] <= et["x"] <= cuarto[2]
              and cuarto[1] <= et["y"] <= cuarto[3])
    if not dentro:
        raise RuntimeError(f"el rotulo cayo fuera del cuarto: {et}")
    return f"rotulo dentro del ambiente, area {et['area']} m2"


def t_cadena_de_cotas():
    space.clear()
    space.set_scale(0.05)   # 1:50 en metros
    x0, y0 = BASE_X + 800, BASE_Y + 100
    huecos = ann.create_dimension_chain(
        [x0, x0 + 1.5, x0 + 2.4, x0 + 9.0], "bottom", y0, layer="PRUEBA")
    ejes = ann.create_dimension_chain(
        [x0, x0 + 4.0, x0 + 9.0], "bottom", y0, layer="PRUEBA", total=True)
    created.extend(huecos["handles"] + ejes["handles"]
                   + ejes["totalChain"]["handles"])
    niveles = [huecos["offset"], ejes["offset"], ejes["totalChain"]["offset"]]
    if niveles != sorted(niveles):
        raise RuntimeError(f"las cadenas no se apilaron hacia afuera: {niveles}")
    return "niveles a " + ", ".join(f"{n:.2f}" for n in niveles)


def t_cotas_y_burbujas_no_se_pisan():
    """El bug que motivo todo esto, contra el dibujo real."""
    space.clear()
    space.set_scale(0.05)
    x0, y0 = BASE_X + 830, BASE_Y + 100
    cadena = ann.create_dimension_chain(
        [x0, x0 + 4.0, x0 + 9.0], "bottom", y0, layer="PRUEBA", total=True)
    grid = arch.create_axis_grid(
        x_positions=[x0, x0 + 4.0, x0 + 9.0],
        y_positions=[y0, y0 + 12.0], layer="PRUEBA")
    created.extend(cadena["handles"] + cadena["totalChain"]["handles"]
                   + grid["handles"])
    r = rules.check_annotations()
    if not r["ok"]:
        raise RuntimeError(r["message"])
    burbuja = min(b["y"] for b in grid["bubbles"]) + grid["bubbleRadius"]
    cota = cadena["totalChain"]["band"][1]
    if burbuja >= cota:
        raise RuntimeError(
            f"la burbuja llega a {burbuja:.2f} y la cota arranca en {cota:.2f}")
    return f"{len(space.bands())} franjas, sin encimarse"


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
    ("mirror_entity", t_mirror_entity),
    ("array_entity rectangular", t_array_entity_rectangular),
    ("array_entity polar", t_array_entity_polar),
    ("find_replace_text", t_find_replace_text),
    ("define_block + insert_block", t_define_e_insert_block),
    ("export_block a DWG", t_export_block),
    ("attach_xref + list_xrefs + detach_xref", t_xref_attach_list_detach),
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
    ("check_drawing_hygiene", t_check_drawing_hygiene),
    ("create_layout", t_layout),
    ("list_layouts", t_list_layouts),
    ("create_viewport", t_viewport),
    ("viewport fuera de hoja -> error", t_viewport_fuera_de_hoja_da_error),
    ("export_pdf", t_export_pdf),
    ("capture_viewport", t_capture_viewport),
    ("undo", t_undo),
    ("simbolos de convencion", t_simbolos_de_convencion),
    ("armado en elevacion", t_rebar_elevation),
    ("armado sin depth -> no inventa", t_rebar_elevation_sin_depth_no_inventa),
    ("compose_sheet", t_compose_sheet),
    ("compose_sheet avisa huerfanas", t_compose_sheet_avisa_huerfanas),
    ("compose_layout", t_compose_layout),
    ("close_document", t_close_document),
    ("familia de dimstyles", t_familia_de_dimstyles),
    ("list_documents", t_list_documents),
    ("set_active_document", t_set_active_document),
    ("new_document", t_new_document),
    ("open_document", t_open_document),
    ("open_document inexistente -> error", t_open_document_inexistente_da_error_claro),

    # --- geometria con arcos ---
    ("polilinea con bulge (arco real)", t_polilinea_con_bulge),
    ("get_entity lee bulges", t_leer_bulges),
    ("get_entity lee patron de hatch", t_leer_patron_de_hatch),

    # --- cotas que no son la alineada ---
    ("cota rotada (proyectada)", t_cota_rotada),
    ("cota radial", t_cota_radial),
    ("cota diametral", t_cota_diametral),
    ("cota angular", t_cota_angular),
    ("cota de desarrollo de arco", t_cota_desarrollo),

    # --- obra civil ---
    ("alineamiento tangente+curva", t_alineamiento),
    ("alineamiento con espiral", t_alineamiento_con_espiral),
    ("calle de ancho variable", t_calle_ancho_variable),
    ("guarnicion por lado y tramo", t_guarnicion_por_tramo),
    ("interseccion con acuerdos", t_interseccion),

    # --- perfil y secciones ---
    ("rasante en un cadenamiento", t_rasante_en_pvi),
    ("perfil longitudinal", t_perfil),
    ("secciones transversales", t_secciones),

    # --- documentacion ---
    ("tabla", t_tabla),
    ("leyenda", t_leyenda),
    ("cadenamiento formato plain", t_cadenamiento_plain),
    ("corte por capas a escala", t_corte_por_capas),
    ("lamina con cajon y rotulo", t_lamina),
    ("mobiliario + rotulo que esquiva", t_mobiliario_y_rotulos),
    ("cadena de cotas que se apila sola", t_cadena_de_cotas),
    ("cotas y burbujas sin encimarse", t_cotas_y_burbujas_no_se_pisan),
]


def hay_conexion() -> bool:
    try:
        acad.call("ping", {})
        return True
    except acad.AutoCadError:
        return False


def limpiar() -> None:
    """Deja el dibujo como estaba: entidades, layout y bloque de esta corrida.

    Sin esto cada pasada acumula un layout y una definicion de bloque nuevos,
    porque llevan el PID en el nombre para poder repetir el test.
    """
    # Si AutoCAD se cayo a mitad no hay nada que limpiar, y hacerlo igual
    # llena la salida de errores de conexion que tapan la falla de verdad.
    if not hay_conexion():
        print("\nAutoCAD no responde: no se limpia "
              "(lo que quedo dibujado se va con el proceso).")
        return

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

    # Una cascada de "no se pudo conectar" no son N fallas: es UNA, y es que
    # AutoCAD se murio. Conviene decirlo asi para no perder tiempo mirando las
    # equivocadas.
    caidas = [n for n, good, d in results
              if not good and "no se pudo conectar" in d.lower()]
    if caidas:
        print(f"\n*** AutoCAD dejo de responder durante la corrida. "
              f"Las {len(caidas)} pruebas desde '{caidas[0]}' no llegaron a "
              f"ejecutarse; la falla real es la anterior. ***")

    if not KEEP:
        limpiar()

    print(f"\n{'=' * 60}")
    print(f"{ok}/{len(results)} pruebas OK")
    if skipped:
        print()
        print("%d salteadas (no son fallas):" % len(skipped))
        for n, d in skipped:
            print(f"  - {n}: {d}")
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
