"""Prueba en vivo: create/delete_database_object (capas, estilos de texto y de cota, bloques)
y create_object(container=...). Dibujo NUEVO descartable.
"""
from __future__ import annotations

import sys

import server as s

R: list[tuple[str, bool]] = []


def chk(n, ok, det=""):
    R.append((n, bool(ok)))
    print(("  ok   " if ok else " FALLA ") + n + (f"  [{det}]" if det and not ok else ""))


def rechaza(n, f, contiene=""):
    """Rechazo = una excepción del plugin o {'ok': False, 'error': ...} de la validación previa."""
    try:
        r = f()
    except Exception as e:  # noqa: BLE001
        chk(n, contiene.lower() in str(e).lower(), str(e)[:140])
        return
    if isinstance(r, dict) and r.get("ok") is False:
        chk(n, contiene.lower() in str(r.get("error", "")).lower(), str(r)[:140])
    else:
        chk(n, False, "no rechazó")


def nombres(corto):
    return {i["name"]: i["handle"] for i in s.list_children(corto)["items"]}


def p(h, *n):
    return s.get_object_properties([h], list(n))["objects"][h]["properties"]


def main() -> int:
    s.new_document()
    print("== version:", s.ping()["pluginVersion"])

    print("\n-- capas")
    n0 = len(nombres("layers"))
    r = s.create_database_object("layer", "MUROS-NUEVA", {"Color": [0, 120, 255], "LineWeight": "LineWeight050", "Description": "muros de carga", "IsLocked": False})
    chk("crear capa devuelve handle y tipo", r["handle"] and r["type"] == "LayerTableRecord", r)
    capas = nombres("layers")
    chk("la capa aparece en list_children", "MUROS-NUEVA" in capas and len(capas) == n0 + 1)
    pr = p(r["handle"], "Name", "Color", "LineWeight", "Description")
    chk("con sus propiedades", pr["Name"] == "MUROS-NUEVA" and pr["Color"] == [0, 120, 255] and pr["LineWeight"] == "LineWeight050" and pr["Description"] == "muros de carga", pr)
    ln = s.create_object("Line", {"StartPoint": [0, 0, 0], "EndPoint": [5, 0, 0], "Layer": "MUROS-NUEVA"})
    chk("se puede dibujar en la capa nueva", p(ln["handle"], "Layer")["Layer"] == "MUROS-NUEVA")
    rechaza("capa repetida", lambda: s.create_database_object("layer", "MUROS-NUEVA"), "ya existe")
    rechaza("capa con nombre invalido", lambda: s.create_database_object("layer", "A/B"), "carácter")
    rechaza("propiedad inexistente no deja nada", lambda: s.create_database_object("layer", "FANTASMA", {"Foo": 1}), "propiedad")
    chk("...y la capa FANTASMA no existe", "FANTASMA" not in nombres("layers"))
    rechaza("propiedad con valor invalido no deja nada", lambda: s.create_database_object("layer", "FANTASMA2", {"LineWeight": "Gordisima"}), "valores válidos")
    chk("...tampoco FANTASMA2", "FANTASMA2" not in nombres("layers"))
    rechaza("borrar una capa con objetos", lambda: s.delete_database_object("layer", "MUROS-NUEVA"), "no se borr")
    chk("...y sigue existiendo", "MUROS-NUEVA" in nombres("layers"))
    s.delete_entity(ln["handle"])
    rechaza("borrar la capa 0", lambda: s.delete_database_object("layer", "0"), "sistema")
    rechaza("borrar Defpoints (no existe en un dibujo nuevo)", lambda: s.delete_database_object("layer", "Defpoints"), "")
    cur = s.get_system_variables(["CLAYER"])["values"]["CLAYER"]
    rechaza("borrar la capa actual", lambda: s.delete_database_object("layer", cur), "")
    s.set_layer("TEMP-USO")
    b = s.delete_database_object("layer", "MUROS-NUEVA")
    chk("borrar la capa ya vacia", b["deleted"] and "MUROS-NUEVA" not in nombres("layers"), b)
    rechaza("borrar una que no existe", lambda: s.delete_database_object("layer", "NO-EXISTE"), "no hay")

    print("\n-- estilo de texto y de cota")
    t = s.create_database_object("textstyle", "ROTULOS-ARIAL", {"FileName": "arial.ttf", "TextSize": 2.5})
    pt = p(t["handle"], "Name", "FileName", "TextSize")
    chk("estilo de texto con fuente y altura", pt["Name"] == "ROTULOS-ARIAL" and pt["FileName"].lower().endswith("arial.ttf"), pt)
    tx = s.create_text("hola", 0, 10, 2.5, style="ROTULOS-ARIAL")
    chk("se puede escribir con el estilo nuevo", tx["handle"])
    d = s.create_database_object("dimstyle", "COTAS-PRUEBA", {"Dimtxt": 3.0, "Dimasz": 2.0, "Dimscale": 50.0})
    pd = p(d["handle"], "Name", "Dimtxt", "Dimasz", "Dimscale")
    chk("estilo de cota con sus variables", pd["Dimtxt"] == 3.0 and pd["Dimasz"] == 2.0 and pd["Dimscale"] == 50.0, pd)
    rechaza("borrar el estilo Standard", lambda: s.delete_database_object("textstyle", "Standard"), "sistema")
    chk("borrar el estilo de cota nuevo", s.delete_database_object("dimstyle", "COTAS-PRUEBA")["deleted"] and "COTAS-PRUEBA" not in nombres("dimstyles"))
    s.delete_entity(tx["handle"])
    try:
        s.delete_database_object("textstyle", "ROTULOS-ARIAL")
        chk("borrar el estilo de texto sin uso", "ROTULOS-ARIAL" not in nombres("textstyles"))
    except Exception as e:  # noqa: BLE001
        chk("borrar el estilo de texto sin uso", False, str(e)[:150])

    print("\n-- bloque completo")
    bl = s.create_database_object("block", "MI-COLUMNA")
    chk("la definicion nace vacia", s.list_children(bl["handle"])["total"] == 0, bl)
    for ent, props in (("Line", {"StartPoint": [0, 0, 0], "EndPoint": [1, 0, 0]}), ("Line", {"StartPoint": [1, 0, 0], "EndPoint": [1, 1, 0]}),
                       ("Circle", {"Center": [0.5, 0.5, 0], "Radius": 0.25})):
        s.create_object(ent, props, container="MI-COLUMNA")
    hijos = s.list_children("MI-COLUMNA") if False else s.list_children(bl["handle"])
    chk("sus 3 entidades viven en la definicion", hijos["total"] == 3 and [i["type"] for i in hijos["items"]].count("Line") == 2, hijos)
    chk("...y NO en el espacio modelo", s.list_entities()["count"] == 0)
    ins = s.insert_block("MI-COLUMNA", 10, 10)
    chk("se inserta el bloque nuevo", ins.get("handle"), ins)
    rechaza("borrar un bloque insertado", lambda: s.delete_database_object("block", "MI-COLUMNA"), "insertado")
    rechaza("borrar *Model_Space", lambda: s.delete_database_object("block", "*Model_Space"), "")
    rechaza("crear un bloque con *", lambda: s.create_database_object("block", "*X"), "*")
    s.delete_entity(ins["handle"])
    chk("sin referencias, el bloque se borra", s.delete_database_object("block", "MI-COLUMNA")["deleted"] and "MI-COLUMNA" not in nombres("blocks"))
    rechaza("container inexistente", lambda: s.create_object("Line", {"StartPoint": [0, 0, 0]}, container="NO-EXISTE"), "")
    chk("...y no dejó una línea suelta", s.list_entities(entity_type="Line")["count"] == 0)

    print("\n-- otros tipos")
    ra = s.create_database_object("regapp", "MI-APP-PRUEBA")
    chk("aplicacion registrada", ra["handle"])
    chk("se borra", s.delete_database_object("regapp", handle=ra["handle"])["deleted"])
    u = s.create_database_object("ucs", "UCS-PRUEBA", {"Origin": [10, 20, 0]})
    chk("sistema de coordenadas con origen", p(u["handle"], "Origin")["Origin"] == [10, 20, 0], p(u["handle"], "Origin"))
    chk("se borra", s.delete_database_object("ucs", "UCS-PRUEBA")["deleted"])
    rechaza("kind desconocido", lambda: s.create_database_object("layout", "X"), "kind")

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
