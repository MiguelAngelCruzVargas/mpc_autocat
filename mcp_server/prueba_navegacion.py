"""Prueba en vivo: list_children + DATABASE + propiedades de objetos que no son entidades
(capas, estilos, layouts, bloques). Abre el DWG del pórtico en SOLO LECTURA para mirar
y trabaja los cambios en un dibujo NUEVO descartable.

Uso:  python prueba_navegacion.py [ruta.dwg]
"""
from __future__ import annotations

import os
import sys

import server as s

R: list[tuple[str, bool]] = []


def chk(n, ok, det=""):
    R.append((n, bool(ok)))
    print(("  ok   " if ok else " FALLA ") + n + (f"  [{det}]" if det and not ok else ""))


def props(h, *names):
    return s.get_object_properties([h], list(names) or None)["objects"][h]["properties"]


def main() -> int:
    dwg = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(r"~\Desktop\Portico_Barda_Mixtan\Portico_Barda_Mixtan.dwg")
    print("== version:", s.ping()["pluginVersion"])
    if os.path.exists(dwg):
        print("\n-- mirando", dwg, "(solo lectura)")
        s.open_document(path=dwg, read_only=True)
        raiz = s.list_children()
        chk("raiz: trae contenedores y nombres cortos", raiz["containers"] and "layers" in raiz["shortNames"], raiz)
        print("   contenedores:", sorted(raiz["containers"]))
        for corto in ("layers", "textstyles", "dimstyles", "linetypes", "blocks", "layouts", "mleaderstyles", "tablestyles", "materials"):
            try:
                r = s.list_children(corto)
                muestra = [i.get("name") for i in r["items"][:6]]
                print(f"   {corto:14} total {r['total']:3} ({r['type']}): {muestra}")
                chk(f"list_children('{corto}') responde", "items" in r)
            except Exception as e:  # noqa: BLE001
                chk(f"list_children('{corto}')", False, str(e)[:150])
        capas = s.list_children("layers")
        chk("hay capas con nombre y handle", capas["total"] > 3 and capas["items"][0]["handle"] and capas["items"][0]["name"], capas["total"])
        nombres = {i["name"]: i["handle"] for i in capas["items"]}
        h = nombres.get("PORT-CONCRETO") or next(iter(nombres.values()))
        pr = props(h)
        print(f"   capa {h}: {len(pr)} propiedades, p.ej.:", {k: pr.get(k) for k in ("Name", "Color", "IsFrozen", "IsLocked", "IsOff", "LineWeight", "Description") if k in pr})
        chk("una capa expone >20 propiedades", len(pr) > 20, len(pr))
        dim = s.list_children("dimstyles")["items"]
        if dim:
            pd = props(dim[0]["handle"])
            print(f"   estilo de cota {dim[0]['name']}: {len(pd)} propiedades; Dimtxt={pd.get('Dimtxt')} Dimasz={pd.get('Dimasz')} Dimscale={pd.get('Dimscale')}")
            chk("un estilo de cota expone >60 propiedades", len(pd) > 60, len(pd))
        bl = s.list_children("blocks")
        modelo = next((i for i in bl["items"] if i["name"] == "*Model_Space"), None)
        chk("*Model_Space esta entre los bloques", modelo is not None)
        if modelo:
            ents = s.list_children(modelo["handle"], 0, 5)
            print(f"   *Model_Space: {ents['total']} entidades; primeras:", [(i['type'], i['layer']) for i in ents["items"]])
            chk("el contenido del espacio modelo se lista", ents["total"] > 1000 and ents["hasMore"], ents["total"])
        lay = s.list_children("layouts")
        print("   layouts:", [i["name"] for i in lay["items"]])
        chk("layouts: Model + las laminas BP-*", lay["total"] >= 2, lay["total"])
        if lay["items"]:
            pl = props(lay["items"][-1]["handle"])
            print(f"   layout {lay['items'][-1]['name']}: {len(pl)} propiedades; TabOrder={pl.get('TabOrder')}")
        db = s.get_object_properties(["DATABASE"], ["Ltscale", "Insunits", "Dimscale", "Lunits", "Aunits"])["objects"]["DATABASE"]["properties"]
        print("   DATABASE:", db)
        chk("DATABASE: lee unidades y escalas", "Ltscale" in db and "Insunits" in db, db)
        todas = s.get_object_properties(["DATABASE"])["objects"]["DATABASE"]
        print(f"   DATABASE completo: {len(todas['properties'])} propiedades legibles, {len(todas.get('unreadable', {}))} no legibles")
        chk("DATABASE completo: >150 propiedades", len(todas["properties"]) > 150, len(todas["properties"]))
        s.new_document()          # AutoCAD no cierra el único dibujo abierto
        s.set_active_document(name=os.path.basename(dwg))
        s.close_document(discard_unsaved=True)

    print("\n-- cambios en un dibujo NUEVO descartable")
    s.new_document()
    s.set_layer("MUROS", color_index=7)
    capas = {i["name"]: i["handle"] for i in s.list_children("layers")["items"]}
    h = capas["MUROS"]
    r = s.set_object_properties([h], {"IsFrozen": False, "IsLocked": True, "Description": "capa de prueba", "LineWeight": "LineWeight050"})
    chk("set en una CAPA: bloquea y describe", props(h, "IsLocked", "Description")["IsLocked"] is True, r)
    try:
        s.set_object_properties([h], {"Color": [200, 0, 0]})
        chk("color RGB en la capa", props(h, "Color")["Color"] == [200, 0, 0])
    except Exception as e:  # noqa: BLE001
        chk("color RGB en la capa", False, str(e)[:150])
    dim = s.list_children("dimstyles")["items"][0]
    antes = props(dim["handle"], "Dimtxt")["Dimtxt"]
    s.set_object_properties([dim["handle"]], {"Dimtxt": 7.5, "Dimscale": 2.0})
    chk("set en un ESTILO DE COTA", abs(props(dim["handle"], "Dimtxt")["Dimtxt"] - 7.5) < 1e-9, antes)
    # DATABASE
    lt = s.get_object_properties(["DATABASE"], ["Ltscale"])["objects"]["DATABASE"]["properties"]["Ltscale"]
    s.set_object_properties(["DATABASE"], {"Ltscale": 3.5})
    chk("set en DATABASE (Ltscale)", abs(s.get_object_properties(["DATABASE"], ["Ltscale"])["objects"]["DATABASE"]["properties"]["Ltscale"] - 3.5) < 1e-9)
    s.set_object_properties(["DATABASE"], {"Ltscale": lt})
    # atomicidad entre DATABASE y un objeto
    c = s.create_circle(0, 0, 2)["handle"]
    try:
        s.set_object_properties(["DATABASE", c], {"Ltscale": 9.0, "Radius": 5})
        chk("DATABASE+objeto con propiedad inexistente falla", False)
    except Exception:  # noqa: BLE001
        chk("DATABASE+objeto con propiedad inexistente falla", True)
    chk("...y DATABASE no cambio (atomico)", abs(s.get_object_properties(["DATABASE"], ["Ltscale"])["objects"]["DATABASE"]["properties"]["Ltscale"] - lt) < 1e-9)
    try:
        s.set_object_properties(["DATABASE"], {"Dimtxt": "grande"})
        chk("valor invalido en DATABASE se rechaza", False)
    except Exception:  # noqa: BLE001
        chk("valor invalido en DATABASE se rechaza", True)
    # un no-contenedor
    try:
        s.list_children(c)
        chk("list_children de una entidad se rechaza con motivo", False)
    except Exception as e:  # noqa: BLE001
        chk("list_children de una entidad se rechaza con motivo", "no un contenedor" in str(e), str(e)[:100])

    n = sum(1 for _, ok in R if ok)
    print(f"\nRESULTADO: {n}/{len(R)} OK  (plugin {s.ping().get('pluginVersion')})")
    fallan = [x for x, ok in R if not ok]
    if fallan:
        print("FALLAN:", fallan)
    try:
        s.close_document(discard_unsaved=True)
    except Exception:  # noqa: BLE001
        pass
    return 0 if not fallan else 1


if __name__ == "__main__":
    sys.exit(main())
