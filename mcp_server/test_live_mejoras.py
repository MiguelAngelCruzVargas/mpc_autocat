"""Pruebas EN VIVO, contra AutoCAD real, de las mejoras de octubre 2026.

Las suites offline mockean el socket: dicen que la matemática y las reglas
están bien, no que el dibujo salga. Esto ejercita cada mejora en AutoCAD de
verdad y verifica el resultado LEYÉNDOLO de vuelta del DWG (get_entity,
list_layers, list_layouts, el PDF en disco), no confiando en lo que la tool
dijo que hizo.

Seguro con el plano del usuario: trabaja en un dibujo NUEVO, guarda en una
carpeta temporal y al final cierra ese dibujo sin tocar los demás.

Uso (con AutoCAD abierto y el plugin cargado):
    python test_live_mejoras.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from typing import Any

import autocad_client as acad
import server

FAILED: list[str] = []
VERSION_MINIMA = (1, 8, 1)


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def _entidades(tipo: str | None = None) -> list[dict[str, Any]]:
    return server.list_entities(entity_type=tipo, limit=100000).get("entities", [])


def _textos() -> dict[str, dict[str, Any]]:
    """Texto -> entidad, de los DBText del espacio activo."""
    salida = {}
    for e in _entidades("DBText"):
        d = acad.call("get_entity", {"handle": e["handle"]})
        salida[str(d.get("text", ""))] = d
    return salida


# ----------------------------------------------------------------- pruebas

def test_plugin_actualizado(tmp: str) -> None:
    v = acad.call("ping", {}).get("pluginVersion", "0")
    tupla = tuple(int(x) for x in re.findall(r"\d+", v)[:3])
    check(f"plugin cargado >= {'.'.join(map(str, VERSION_MINIMA))} (hay {v})",
          tupla >= VERSION_MINIMA, v)


def test_guardar_sobre_el_mismo_archivo(tmp: str) -> None:
    """eFilerError: guardar un plano ABIERTO desde disco sobre sí mismo."""
    ruta = os.path.join(tmp, "guardado.dwg")
    server.save_drawing(path=ruta)
    server.create_line(0, 0, 1, 0, layer="PRUEBA")
    try:
        server.save_drawing(path=ruta)
        ok, detalle = True, ""
    except acad.AutoCadError as exc:
        ok, detalle = False, str(exc)
    check("dibujo NUEVO guardado otra vez en su mismo archivo (sin overwrite)",
          ok, detalle)
    server.create_line(0, 0.5, 1, 0.5, layer="PRUEBA")
    try:
        r = server.save_drawing()
        ok, detalle = os.path.samefile(r.get("path", ""), ruta), str(r)
    except acad.AutoCadError as exc:
        ok, detalle = False, str(exc)
    check("save_drawing() sin ruta reusa ese archivo", ok, detalle)
    server.close_document(save=False, discard_unsaved=True)
    server.open_document(path=ruta)
    server.create_line(0, 1, 1, 1, layer="PRUEBA")
    antes = os.path.getmtime(ruta)
    time.sleep(1.1)
    try:
        server.save_drawing(path=ruta)
        ok, detalle = os.path.getmtime(ruta) > antes, "el archivo no cambió"
    except acad.AutoCadError as exc:
        ok, detalle = False, str(exc)
    check("abierto desde disco, corregido y guardado encima (sin eFilerError)",
          ok, detalle)
    check("y sigue existiendo el .dwg (no quedó solo el .bak)",
          os.path.exists(ruta), str(os.listdir(tmp)))


def test_red_de_muros(tmp: str) -> None:
    r = server.create_wall_network(walls=[
        {"points": [[0, 0], [6, 0], [6, 4], [0, 4]], "thickness": 0.15,
         "closed": True,
         "openings": [{"segment": 0, "offset": 1.5, "width": 0.9}]},
        {"points": [[3, 0], [3, 4]], "thickness": 0.10}])
    medido = 0.0
    for h in r["wallHandles"]:
        e = acad.call("get_entity", {"handle": h})
        medido += e.get("area", 0.0) * (1 if e.get("closed") else 0)
    # Los lazos interiores (huecos) restan: la suma con signo la da Python.
    areas = sorted((acad.call("calculate_area", {"handle": h}).get("area", 0)
                    for h in r["wallHandles"]), reverse=True)
    neto = areas[0] - sum(areas[1:]) if len(areas) > 1 else areas[0]
    check("red de muros: AutoCAD mide la misma mampostería que Python",
          abs(neto - r["masonryArea"]) < 1e-3,
          f"AutoCAD {neto:.4f} vs Python {r['masonryArea']:.4f}")
    check("todos los contornos son polilíneas cerradas",
          all(acad.call("get_entity", {"handle": h}).get("closed")
              for h in r["wallHandles"]))


def test_cotas(tmp: str) -> None:
    import space
    space.set_scale(0.075)
    r = server.create_dimension_chain(
        positions=[0.0, 0.425, 1.925, 3.0], side="bottom", reference=0.0)
    cotas = [acad.call("get_entity", {"handle": h}) for h in r["handles"]]
    corta = next((c for c in cotas if abs(c["measurement"] - 0.425) < 1e-6), None)
    check("la cota corta va SIN número entre las flechas",
          corta is not None and corta.get("dimensionText") == " ",
          str(corta and corta.get("dimensionText")))
    textos = _textos()
    check("su número va aparte, redondeado como AutoCAD (0.43)",
          "0.43" in textos, str(list(textos)[:10]))
    if "0.43" in textos:
        check("y por fuera de la línea de cota (debajo, en una cadena inferior)",
              textos["0.43"]["position"][1] < r["dimLineCoord"],
              f"{textos['0.43']['position']} vs línea {r['dimLineCoord']}")
    normal = next(c for c in cotas if abs(c["measurement"] - 1.5) < 1e-6)
    check("número encima de la línea (DIMTAD 1)", normal.get("textAbove") == 1,
          str(normal.get("textAbove")))
    check("número alineado con la cota (DIMTIH falso)",
          normal.get("textInsideHorizontal") is False,
          str(normal.get("textInsideHorizontal")))
    check("las cotas NO salen en txt.shx",
          "txt" not in str(normal.get("textFont", "")).lower(),
          f"{normal.get('textStyle')} / {normal.get('textFont')}")


def test_rotulo_y_lamina_y_pdf(tmp: str) -> None:
    r = server.create_layout(name="PRUEBA-01", paper_size="A3")
    lay = next(l for l in acad.call("list_layouts", {})["layouts"]
               if l["name"] == "PRUEBA-01")
    check("create_layout: rotación de plot 0 (no hereda 90)",
          lay.get("plotRotation") == "Degrees000", str(lay))
    server.set_current_layout("PRUEBA-01")
    hoja = server.create_sheet(sheet_format="A3", scale_denominator=1,
                               model_units="mm", scale_label="1:75",
                               project="PRUEBA EN VIVO")
    check("create_sheet en layout: el rótulo dice la escala real",
          hoja.get("scale") == "1:75" and "1:75" in _textos(),
          str(hoja.get("scale")))
    sin = server.create_sheet(sheet_format="A3", scale_denominator=1,
                              model_units="mm", origin_x=500)
    check("y sin scale_label avisa que 1:1 no es la escala del dibujo",
          "scale_label" in str(sin.get("warning", "")), str(sin.get("warning")))
    server.create_viewport(layout="PRUEBA-01", center_x=150, center_y=170,
                           width=200, height=150, view_center_x=3,
                           view_center_y=2, scale_denominator=50,
                           model_units_per_mm=1000)
    capas = {c["name"]: c for c in acad.call("list_layers", {})["layers"]}
    vp = capas.get("MCP-VIEWPORTS", {})
    check("el marco del viewport va en MCP-VIEWPORTS y NO se imprime",
          vp and vp.get("plottable") is False, str(vp))
    pdf = os.path.join(tmp, "prueba.pdf")
    server.export_pdf(layout="PRUEBA-01", path=pdf)
    datos = open(pdf, "rb").read() if os.path.exists(pdf) else b""
    caja = re.search(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)",
                     datos)
    if caja:
        w, h = float(caja.group(3)), float(caja.group(4))
        mm = (round(max(w, h) * 25.4 / 72), round(min(w, h) * 25.4 / 72))
    else:
        mm = None
    check("el PDF sale en el papel de la lámina (A3 = 420x297), no en el "
          "papel por defecto del dispositivo", mm == (420, 297), str(mm))
    server.set_current_layout("Model")


def test_rotulo_sin_muros(tmp: str) -> None:
    import furniture
    import space
    space.clear()
    server.create_wall_network(walls=[
        {"points": [[20, 4.3], [27, 4.3], [27, 8.7], [20, 8.7]],
         "thickness": 0.15, "closed": True}])
    r = furniture.label_rooms(
        [{"name": "COCHERA", "x0": 20, "y0": 0, "x1": 27, "y1": 4.3}],
        height=0.18)
    area = r["labeled"][0]["area"]
    check("espacio sin muros: solo descuenta medio muro donde HAY muro",
          abs(area - 7.0 * (4.3 - 0.075)) < 0.01, str(area))
    check("y el número que quedó escrito en el DWG es ese",
          f"{area:.2f} m2" in _textos(), str(area))


def test_estandar_de_oficina(tmp: str) -> None:
    server.set_layer(name="MUROS", color_index=7, lineweight_hundredths_mm=25)
    server.set_layer(name="CHILLON", color_index=1)
    server.create_line(0, 10, 1, 10, layer="0")
    server.create_line(0, 11, 1, 11, layer="CHILLON")
    server.create_line(0, 12, 1, 12, layer="MUROS")
    r = server.check_office_standard(standard={
        "capas": {"MUROS": {"color": 7, "grosor": 50}},
        "capas_obligatorias": ["TEXTOS-OFICINA"]})
    reglas = {p["rule"] for p in r["problems"]}
    for regla in ("capa 0", "color puro", "grosor de capa", "capa obligatoria"):
        check(f"estándar de oficina detecta '{regla}' en el DWG real",
              regla in reglas, str(sorted(reglas)))
    # Con una LÁMINA activa tiene que ver igual lo dibujado en el modelo:
    # mirando solo el espacio activo no lo veía (falló en vivo).
    server.set_current_layout("PRUEBA-01")
    r2 = server.check_office_standard(standard={"capas": {}})
    reglas2 = {p["rule"] for p in r2["problems"]}
    check("con una lámina activa sigue viendo la capa 0 y el color puro del modelo",
          {"capa 0", "color puro"} <= reglas2, str(sorted(reglas2)))
    server.set_current_layout("Model")
    todo = server.check_all()
    check("check_all incluye el estándar de oficina",
          "office_standard" in todo.get("checks", {}), str(todo.get("skipped")))


def test_panel_web_en_vivo(tmp: str) -> None:
    """Las rutas nuevas del panel contra AutoCAD real (servidor en un puerto
    aparte, sin abrir ningún navegador)."""
    # El panel opera sobre el dibujo ACTIVO de AutoCAD (es lo correcto: el
    # que la persona tiene al frente). La prueba deja activo el suyo.
    server.set_active_document(name="guardado.dwg")
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, raiz)
    from agent import web
    puerto = 8795
    srv = web._ServidorExclusivo(("127.0.0.1", puerto), web.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def pedir(ruta: str, cuerpo: Any = None) -> tuple[int, Any]:
        req = urllib.request.Request(
            f"http://127.0.0.1:{puerto}{ruta}",
            data=None if cuerpo is None else json.dumps(cuerpo).encode(),
            method="GET" if cuerpo is None else "POST",
            headers={"Content-Type": "application/json",
                     "Origin": f"http://127.0.0.1:{puerto}"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    try:
        st, r = pedir("/api/layouts")
        check("panel: /api/layouts lista la lámina del dibujo real",
              st == 200 and "PRUEBA-01" in r.get("layouts", []), str(r))
        st, r = pedir("/api/revisar", {})
        check("panel: 'Revisar plano' corre check_all en AutoCAD real",
              st == 200 and "office_standard" in r.get("checks", []), str(r)[:200])
        st, r = pedir("/api/captura", {"layout": "PRUEBA-01"})
        png = os.path.join(web.CAPTURAS, "vista.png")
        check("panel: el visor captura la LÁMINA (no solo el modelo)",
              st == 200 and r.get("ok") and os.path.getsize(png) > 1000,
              str(r)[:200])
    finally:
        srv.shutdown()
        srv.server_close()


# ----------------------------------------------------------------- correr

def main() -> int:
    try:
        acad.call("ping", {})
    except acad.AutoCadError as exc:
        print(f"AutoCAD no responde: {exc}")
        return 1
    tmp = tempfile.mkdtemp(prefix="acad_mejoras_")
    # Lo que ya estaba abierto (el plano del usuario) no se toca; todo lo
    # demás lo abrió esta corrida y se cierra al final, pase o falle: una
    # corrida que falló a mitad dejaba guardado.dwg abierto en AutoCAD.
    previos = {d["name"].lower() for d in
               acad.call("list_documents", {}).get("documents", [])}
    server.new_document()
    try:
        for t in (test_plugin_actualizado, test_guardar_sobre_el_mismo_archivo,
                  test_red_de_muros, test_cotas, test_rotulo_y_lamina_y_pdf,
                  test_rotulo_sin_muros, test_estandar_de_oficina,
                  test_panel_web_en_vivo):
            print(t.__name__)
            try:
                t(tmp)
            except Exception as exc:                    # noqa: BLE001
                FAILED.append(f"{t.__name__}: {exc}")
                print(" FALLA " + t.__name__ + " -- " + repr(exc))
                traceback.print_exc()
    finally:
        for d in acad.call("list_documents", {}).get("documents", []):
            if d["name"].lower() not in previos:
                try:
                    acad.call("close_document", {"name": d["name"], "save": False,
                                                 "discardUnsaved": True})
                except acad.AutoCadError:
                    pass
        shutil.rmtree(tmp, ignore_errors=True)
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" - " + f)
        return 1
    print("\nOK: las mejoras funcionan en AutoCAD real.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
