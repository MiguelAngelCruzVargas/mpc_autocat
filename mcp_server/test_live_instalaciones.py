"""Instalaciones EN VIVO: eléctrica, hidráulica y sanitaria en AutoCAD real.

Dibuja una casa de suggest_layout tres veces lado a lado (una por
instalación), con muros, muebles y rótulos, y verifica las reglas de norma
LEYENDO EL DWG: entidades en sus capas, líneas que de verdad llegan a cada
mueble, textos del cuadro de cargas y de los registros, tipo de línea del
agua caliente.

Trabaja sobre UN SOLO dibujo, el plano de prueba
(pruebas/planos/instalaciones_casa_8x20.dwg, o ACAD_GUARDAR_INSTALACIONES):
si ya está abierto usa esa pestaña, si no lo abre, y solo si no existe
arranca uno nuevo. Si la base arquitectónica ya está dibujada NO la rehace:
borra únicamente las capas de instalaciones y las vuelve a dibujar, como se
corrige un plano. Al final lo guarda y lo deja abierto — nunca deja
pestañas sueltas (pasó: cada corrida abría un Drawing nuevo y quedaban
cuatro pestañas en AutoCAD).

Uso (con AutoCAD abierto):  python test_live_instalaciones.py
"""
from __future__ import annotations

import math
import os
import sys
import traceback
from typing import Any

import autocad_client as acad
import electrical
import furniture
import instalaciones as ins
import rules
import server
import space

FAILED: list[str] = []
ANCHO_LOTE, FONDO_LOTE = 8.0, 20.0
SEPARACION = 21.0       # entre una planta y la siguiente (con su simbología)
PLANO = os.environ.get("ACAD_GUARDAR_INSTALACIONES") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "pruebas", "planos", "instalaciones_casa_8x20.dwg")
CAPAS_INSTALACION = {c.upper() for c in (
    electrical.LAYER_LIGHT, electrical.LAYER_OUTLET, electrical.LAYER_PANEL,
    electrical.LAYER_CONDUIT, ins.CAPA_AF, ins.CAPA_AC, ins.CAPA_HID_SIMB,
    ins.CAPA_DRENAJE, ins.CAPA_REGISTRO, ins.CAPA_TEXTO_INST)}


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def _corrida(plan: dict[str, Any], dx: float) -> tuple[list, list]:
    rooms = [{**r, "x0": r["x0"] + dx, "x1": r["x1"] + dx} for r in plan["rooms"]]
    doors = [{**d, "x": d["x"] + dx} if "x" in d else dict(d) for d in plan["doors"]]
    return rooms, doors


def _base(rooms, doors, windows, titulo: str) -> None:
    """Muros, muebles y rótulos: la base arquitectónica de cada planta."""
    server.draw_layout(rooms=rooms, doors=doors, windows=windows, label=False)
    furniture.suggest_furniture(rooms, doors)
    furniture.label_rooms([r for r in rooms if r["name"] != "PASILLO"],
                          height=space.paper(2.5))
    x0 = min(r["x0"] for r in rooms)
    server.create_view_title(x=x0, y=FONDO_LOTE + 1.2, title=titulo,
                             scale_text="ESC. 1:75")


def _registrar_base(rooms, doors) -> None:
    """La base ya está en el DWG pero la sesión no la conoce: se le cuentan
    los muros (barreras de place_labels) y la huella de los muebles, sin
    volver a dibujarlos."""
    for r in rooms:
        t = 0.075
        for x0, y0, x1, y1 in ((r["x0"], r["y0"], r["x1"], r["y0"]),
                               (r["x0"], r["y1"], r["x1"], r["y1"]),
                               (r["x0"], r["y0"], r["x0"], r["y1"]),
                               (r["x1"], r["y0"], r["x1"], r["y1"])):
            space.track(x0 - t, y0 - t, x1 + t, y1 + t, "muro MUROS")
    for m in furniture.suggest_furniture(rooms, doors, draw=False)["items"]:
        a = math.radians(m.get("rotation_deg", 0.0))
        esq = [(u * math.cos(a) - v * math.sin(a), u * math.sin(a) + v * math.cos(a))
               for u, v in ((0, 0), (m["width"], 0), (m["width"], m["depth"]), (0, m["depth"]))]
        xs = [m["x"] + e[0] for e in esq]
        ys = [m["y"] + e[1] for e in esq]
        space.track(min(xs), min(ys), max(xs), max(ys), f"mueble {m['type']}")


def _abrir_plano() -> bool:
    """Deja activo el plano de prueba, en UNA pestaña. Devuelve si ya tenía
    la base dibujada."""
    abiertos = acad.call("list_documents", {})["documents"]
    mio = next((d for d in abiertos
                if os.path.normcase(str(d.get("fullPath", ""))) == os.path.normcase(PLANO)), None)
    if mio and mio.get("isReadOnly"):
        # Abierto solo para mirar: no se puede guardar encima. Se cierra (no
        # tiene nada que perder) y se abre para escribir. AutoCAD no se
        # queda sin dibujos: si era el único, una pestaña de paso que se
        # cierra apenas el plano está abierto.
        temporal = (server.new_document().get("active")
                    if len(abiertos) == 1 else None)
        acad.call("close_document", {"name": mio["name"], "save": False,
                                     "discardUnsaved": True})
        server.open_document(path=PLANO)
        if temporal:
            acad.call("close_document", {"name": temporal, "save": False,
                                         "discardUnsaved": True})
        server.set_active_document(name=os.path.basename(PLANO))
        mio = {"name": os.path.basename(PLANO)}
    if mio:
        server.set_active_document(name=mio["name"])
    elif os.path.exists(PLANO):
        server.open_document(path=PLANO)
    else:
        os.makedirs(os.path.dirname(PLANO), exist_ok=True)
        server.new_document()
        server.save_drawing(path=PLANO)
        return False
    # La base sirve solo si es ESTA base: si cambió la separación entre
    # plantas, los muros están en otro lado y se rehace (una vez) en la
    # misma pestaña.
    muros = server.get_extents(layers=["MUROS"])
    esperado = 2 * SEPARACION + ANCHO_LOTE
    if muros.get("isEmpty", True) or abs(muros["maxX"] - esperado) > 0.5:
        ents = acad.call("list_entities", {"limit": 200000, "allSpaces": True})["entities"]
        if ents:
            server.delete_entities(handles=[e["handle"] for e in ents])
        space.clear()
        space.clear_footprints()
        return False
    return True


def _borrar_instalaciones() -> int:
    ents = acad.call("list_entities", {"limit": 200000, "allSpaces": True})["entities"]
    handles = [e["handle"] for e in ents if e["layer"].upper() in CAPAS_INSTALACION]
    if handles:
        server.delete_entities(handles=handles)
    return len(handles)


def _por_capa(capa: str) -> list[dict[str, Any]]:
    return [e for e in acad.call("list_entities", {"limit": 200000, "allSpaces": True})
            ["entities"] if e["layer"].upper() == capa.upper()]


_TEXTO_DE: dict[str, str] = {}


def _textos() -> list[str]:
    """Cada get_entity cuesta ~0.5 s: con las simbologías hay cientos de
    textos y leerlos todos en cada fase pasaba los 10 minutos. Un texto ya
    leído no cambia: se cachea por handle."""
    salida = []
    for e in acad.call("list_entities", {"limit": 200000, "allSpaces": True})["entities"]:
        if e["type"] in ("DBText", "MText"):
            if e["handle"] not in _TEXTO_DE:
                d = acad.call("get_entity", {"handle": e["handle"]})
                _TEXTO_DE[e["handle"]] = str(d.get("text", ""))
            salida.append(_TEXTO_DE[e["handle"]])
    return salida


def _extremos(capa: str) -> list[tuple[float, float]]:
    pts = []
    for e in _por_capa(capa):
        if e["type"] != "Line":
            continue
        d = acad.call("get_entity", {"handle": e["handle"]})
        pts += [tuple(d["startPoint"][:2]), tuple(d["endPoint"][:2])]
    return pts


def _leyenda(r, rooms, textos, titulo: str) -> None:
    """La simbología: dibujada, con sus notas, y AL LADO de la planta."""
    ley = r.get("legend") or {}
    check(f"DWG: simbología de {titulo} con símbolos y notas",
          ley.get("symbols", 0) >= 5 and ley.get("notes", 0) >= 4, str(ley))
    check(f"DWG: simbología de {titulo} escrita en el plano",
          any(t.startswith("SIMBOLOGÍA") and titulo in t for t in textos)
          and "NOTAS:" in textos)
    caja = ley.get("box") or [0, 0, 0, 0]
    check(f"la simbología de {titulo} no pisa la planta",
          caja[0] > max(x["x1"] for x in rooms), str(caja))


# --------------------------------------------------------------- pruebas

def probar_electrica(rooms, doors) -> dict[str, Any]:
    r = server.suggest_electrical(rooms=rooms, doors=doors,
                                  table_x=min(x["x0"] for x in rooms),
                                  table_y=-2.5)
    dev = r["devices"]
    muebles = ins._muebles(rooms, doors, None)
    # 210-70: cada recinto habitable, baño y pasillo con su salida.
    for room in rooms:
        if "PATIO" in room["name"]:
            continue
        luces = [d for d in dev if d["type"] == "lamp" and d["tag"] == room["name"]]
        check(f"210-70 salida de alumbrado en {room['name']}", len(luces) >= 1,
              str(len(luces)))
    # 210-52(d) + 210-8: contacto con falla a tierra a ≤0.90 m de cada lavabo.
    for lav in [m for m in muebles if m["type"] == "lavatory"]:
        gf = [d for d in dev if d["type"] == "gfci" and d["tag"] == lav["room"]]
        dist = min((math.dist((d["x"], d["y"]), lav["conexion"]) for d in gf),
                   default=99)
        check(f"210-52(d) contacto GFCI a ≤0.90 m del lavabo ({lav['room']})",
              dist <= ins.NORMA["lavabo_contacto_m"] + 1e-6, f"{dist:.2f} m")
    # 210-52(a): ningún punto del muro libre a más de 1.80 m de un contacto.
    cajas = ins._cajas_utiles(rooms, 0.15, 0.10)
    for room in rooms:
        u = room["name"].upper()
        if any(p in u for p in ("BAÑO", "PASILLO", "LAVADO", "PATIO", "COCINA")):
            continue
        conts = [(d["x"], d["y"]) for d in dev if d["type"] in ("outlet", "gfci")
                 and d["tag"] == room["name"]]
        peor = 0.0
        for t in ins.geo.tramos_de_muro(cajas[room["name"]],
                                        ins._huecos(room["name"], cajas[room["name"]], doors)):
            if t["a1"] - t["a0"] < ins.NORMA["muro_min_contacto_m"]:
                continue
            a = t["a0"]
            while a <= t["a1"]:
                p = t["punto"](a)
                peor = max(peor, min((math.dist(p, c) for c in conts), default=99))
                a += 0.1
        check(f"210-52(a) todo el muro de {room['name']} a ≤1.80 m de un contacto",
              peor <= ins.NORMA["contacto_max_m"] + 0.06, f"peor punto a {peor:.2f} m")
    # 210-52(e): exterior al frente y atrás.
    ext = [d for d in dev if d["type"] == "gfci"
           and ("EXTERIOR" in d["tag"] or "PATIO" in d["tag"])]
    check("210-52(e) contactos exteriores al frente Y atrás (GFCI)", len(ext) >= 2,
          str([d["tag"] for d in ext]))
    # "Atrás" es atrás de la VIVIENDA: el del patio va sobre la fachada de la
    # casa, no en la barda del fondo (quedaba a 11 m y la canalización
    # cruzaba el patio entero).
    patio = next((x for x in rooms if "PATIO" in x["name"]), None)
    if patio:
        del_patio = [d for d in dev if d["tag"] == patio["name"]]
        lejos = max((d["y"] - patio["y0"] for d in del_patio), default=99)
        check("210-52(e) lo del patio sobre la fachada de la casa (≤1 m)",
              bool(del_patio) and lejos <= 1.0, f"a {lejos:.2f} m de la fachada")
    # 210-11(c): circuitos de 20 A exigidos.
    nombres = {c["name"]: c for c in r["circuits"]}
    check("210-11(c)(1) dos circuitos de pequeños aparatos de 20 A",
          nombres.get("PA-1", {}).get("amps") == 20 and nombres.get("PA-2", {}).get("amps") == 20,
          str(list(nombres)))
    check("210-11(c)(2)(3) circuito de lavado y de baño de 20 A",
          nombres.get("LAV", {}).get("amps") == 20 and nombres.get("BAÑO", {}).get("amps") == 20)
    tope = 15 * ins.NORMA["tension_v"] * ins.NORMA["factor_continua"]
    generales = [c for c in r["circuits"] if c["amps"] == 15]
    check("circuitos de 15 A al 80 % como máximo (210-19/210-20)",
          all(c["va"] <= tope + 1e-6 for c in generales),
          str([(c["name"], c["va"]) for c in generales]))
    # En el DWG: símbolos en sus capas y el cuadro de cargas escrito.
    n_luces = sum(1 for d in dev if d["type"] == "lamp")
    circ_luz = [e for e in _por_capa(electrical.LAYER_LIGHT) if e["type"] == "Circle"]
    check("DWG: un círculo de salida por cada salida de alumbrado (o más)",
          len(circ_luz) >= n_luces, f"{len(circ_luz)} vs {n_luces}")
    check("DWG: contactos dibujados en su capa",
          len(_por_capa(electrical.LAYER_OUTLET)) > 0)
    textos = _textos()
    check("DWG: el cuadro de cargas está escrito, con sus circuitos",
          any("CUADRO DE CARGAS" in t for t in textos)
          and all(any(c["name"] == t.strip() for t in textos) for c in r["circuits"]),
          str([c["name"] for c in r["circuits"]]))
    _leyenda(r, rooms, textos, "INSTALACIÓN ELÉCTRICA")
    return r


def probar_hidraulica(rooms, doors) -> dict[str, Any]:
    r = server.suggest_hydraulic(rooms=rooms, doors=doors)
    pts_af = _extremos(ins.CAPA_AF)
    for f in r["fixtures"]:
        llega = min((math.dist(tuple(f["point"]), p) for p in pts_af), default=99)
        check(f"DWG: el agua fría llega al {ins.NOMBRES_MUEBLE[f['type']]} de {f['room']}",
              llega < 1e-3, f"a {llega:.3f} m")
    troncal = next(t for t in r["coldPipes"] if t["from"] == [round(v, 3) for v in r["supply"]])
    check("INIFED 2.3: la troncal lleva todos los muebles UNA vez (8 UM -> 25 mm)",
          troncal["load"] == r["totalUM"] == 8 and troncal["diameter_mm"] == 25,
          str(troncal))
    capas = {c["name"]: c for c in acad.call("list_layers", {})["layers"]}
    lt = str(capas.get(ins.CAPA_AC, {}).get("linetype", "")).upper()
    check("DWG: agua caliente con línea discontinua",
          any(k in lt for k in ("HIDDEN", "OCULT", "DASH", "TRAZO")), lt)
    check("DWG: líneas de agua caliente dibujadas",
          # +1: la muestra de línea de la simbología
          len(_por_capa(ins.CAPA_AC)) == len(r["hotPipes"]) + 1,
          f"{len(_por_capa(ins.CAPA_AC))} vs {len(r['hotPipes'])}")
    textos = _textos()
    check("DWG: diámetros rotulados (AF Ø.. / AC Ø..)",
          any(t.startswith("AF Ø") for t in textos) and any(t.startswith("AC Ø") for t in textos))
    check("DWG: BAF y calentador señalados",
          "BAF" in textos and "CAL" in textos)
    _leyenda(r, rooms, textos, "INSTALACIÓN HIDRÁULICA")
    return r


def probar_sanitaria(rooms, doors) -> dict[str, Any]:
    r = server.suggest_sanitary(rooms=rooms, doors=doors)
    for t in r["pipes"]:
        if "WC" in t["drains"]:
            if t["diameter_mm"] < 100:
                check("INIFED 3.1: todo tramo que drena un WC es de 100 mm", False, str(t))
                break
    else:
        check("INIFED 3.1: todo tramo que drena un WC es de 100 mm", True)
    check("NTC 6.1.3.1: ningún desagüe menor de 32 mm",
          min(t["diameter_mm"] for t in r["pipes"]) >= 32)
    check("NTC 6.1.3.1: pendiente 2 %", all(t["slope"] == 0.02 for t in r["pipes"]))
    check("NTC 6.1.3.2-I: albañal de 150 mm a la red municipal",
          r["sewer"]["diameter_mm"] == 150)
    pts = _extremos(ins.CAPA_DRENAJE)
    muebles = ins._muebles(rooms, doors, None)
    sin = [m["type"] for m in muebles
           if min((math.dist(m["conexion"], p) for p in pts), default=99) > 1e-3]
    check("DWG: cada mueble tiene su desagüe dibujado", not sin, str(sin))
    regs = [e for e in _por_capa(ins.CAPA_REGISTRO) if e["type"] == "Polyline"]
    check("DWG: registros dibujados (uno por registro, más la doble tapa)",
          len(regs) >= len(r["registers"]), f"{len(regs)} vs {len(r['registers'])}")
    textos = _textos()
    check("DWG: registros rotulados R-n 40x60",
          all(any(t.startswith(f"{g['name']} 40x60") for t in textos) for g in r["registers"]))
    check("NTC 6.1.3.2-III: tubo ventilador Ø50 en el origen del albañal",
          r["vent"] and any(t.startswith("TV Ø50") for t in textos), str(r["vent"]))
    check("DWG: albañal rotulado", any("ALBAÑAL Ø150" in t for t in textos))
    check("NTC 6.1.3.2-VII: registro bajo local habitable con doble tapa",
          all(g.get("double_lid") for g in r["registers"]
              if g.get("room") and "PATIO" not in g["room"]))
    _leyenda(r, rooms, textos, "INSTALACIÓN SANITARIA")
    return r


def main() -> int:
    try:
        acad.call("ping", {})
    except acad.AutoCadError as exc:
        print(f"AutoCAD no responde: {exc}")
        return 1
    space.set_scale(0.075)              # 1:75: alturas de texto en papel
    con_base = _abrir_plano()
    activo = acad.call("ping", {})["activeDocument"]
    if con_base:
        print(f"  {_borrar_instalaciones()} entidades de instalaciones borradas; "
              "la base arquitectónica se conserva")
    plan = rules.suggest_layout(ANCHO_LOTE, FONDO_LOTE, bedrooms=3, bathrooms=2)
    for i, (titulo, probar) in enumerate((
            ("INSTALACION ELECTRICA", probar_electrica),
            ("INSTALACION HIDRAULICA", probar_hidraulica),
            ("INSTALACION SANITARIA", probar_sanitaria))):
        print(probar.__name__)
        rooms, doors = _corrida(plan, i * SEPARACION)
        # AutoCAD opera sobre el dibujo ACTIVO: si el foco se va a otra
        # pestaña, la capa se crea en uno y la entidad en otro.
        server.set_active_document(name=activo)
        try:
            if con_base:
                _registrar_base(rooms, doors)
            else:
                _base(rooms, doors, plan["windows"] and
                      [dict(w) for w in plan["windows"]], titulo)
            probar(rooms, doors)
        except Exception as exc:                        # noqa: BLE001
            FAILED.append(f"{probar.__name__}: {exc!r}")
            print(" FALLA " + probar.__name__ + " -- " + repr(exc))
            traceback.print_exc()
    server.set_active_document(name=activo)
    server.save_drawing(path=PLANO, overwrite=True)
    print(f"  plano guardado en {PLANO} (queda abierto, una sola pestaña)")
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" - " + f)
        return 1
    print("\nOK: las tres instalaciones salen y cumplen en AutoCAD real.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
