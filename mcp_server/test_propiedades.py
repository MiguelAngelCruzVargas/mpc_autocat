"""Tests de get_object_properties / set_object_properties / list_object_properties
(propiedades.py + server.py) contra el socket mockeado. NO necesita AutoCAD.

La reflexión sobre la API de AutoCAD se verifica en vivo; acá se verifica lo
de este lado: que se rechace antes de tocar AutoCAD lo que no tiene sentido y
que cada tool mande al plugin el comando y los parámetros correctos.

Uso:  python test_propiedades.py
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
        return {"ok": True, "echo": cmd, "handle": "AB"}

    real = server.acad.call
    server.acad.call = fake
    try:
        return fn(), llamadas
    finally:
        server.acad.call = real


def rechazada(nombre, fn):
    r, llamadas = con_plugin(fn)
    check(f"{nombre}: se rechaza", r.get("ok"), False)
    check(f"{nombre}: dice por qué", bool(r.get("error")), True)
    check(f"{nombre}: no toca AutoCAD", llamadas, [])


def main() -> int:
    # ---- get
    r, ll = con_plugin(lambda: server.get_object_properties(["3e5c", "3E5C", "A1"], ["Layer", "Radius"]))
    check("get manda handles en mayúscula, sin repetir", ll[0], ("get_properties",
          {"handles": ["3E5C", "A1"], "names": ["Layer", "Radius"]}))
    r, ll = con_plugin(lambda: server.get_object_properties(["A1"]))
    check("get sin names lee todas", ll[0], ("get_properties", {"handles": ["A1"]}))
    rechazada("get sin handles", lambda: server.get_object_properties([]))
    rechazada("get con handle no hexadecimal", lambda: server.get_object_properties(["ZZ"]))
    rechazada("get con names vacío", lambda: server.get_object_properties(["A1"], []))
    rechazada("get con name no texto", lambda: server.get_object_properties(["A1"], [3]))
    rechazada("get con demasiados objetos", lambda: server.get_object_properties(["A%d" % i for i in range(501)]))
    rechazada("get con demasiadas propiedades", lambda: server.get_object_properties(["A1"], ["P%d" % i for i in range(61)]))

    # ---- set
    r, ll = con_plugin(lambda: server.set_object_properties(["a1", "b2"], {"Layer": "MUROS", "Color": 7}))
    check("set manda handles y propiedades", ll[0], ("set_properties",
          {"handles": ["A1", "B2"], "properties": {"Layer": "MUROS", "Color": 7}, "dry_run": False}))
    r, ll = con_plugin(lambda: server.set_object_properties(["A1"], {"Radius": 0.25}, dry_run=True))
    check("set con dry_run", ll[0][1]["dry_run"], True)
    r, ll = con_plugin(lambda: server.set_object_properties(["A1"], {"StartPoint": [0, 0, 0]}))
    check("set acepta un punto", ll[0][1]["properties"], {"StartPoint": [0, 0, 0]})
    rechazada("set sin propiedades", lambda: server.set_object_properties(["A1"], {}))
    rechazada("set con propiedades que no son un objeto", lambda: server.set_object_properties(["A1"], ["Layer"]))
    rechazada("set con valor null", lambda: server.set_object_properties(["A1"], {"Layer": None}))
    rechazada("set con nombre vacío", lambda: server.set_object_properties(["A1"], {"": 1}))
    rechazada("set sin handles", lambda: server.set_object_properties([], {"Layer": "0"}))
    rechazada("set con demasiadas propiedades",
              lambda: server.set_object_properties(["A1"], {"P%d" % i: 1 for i in range(61)}))

    # ---- list
    r, ll = con_plugin(lambda: server.list_object_properties("Polyline"))
    check("list por tipo", ll[0], ("list_properties", {"type": "Polyline"}))
    r, ll = con_plugin(lambda: server.list_object_properties(handle="a1"))
    check("list por handle", ll[0], ("list_properties", {"handle": "A1"}))
    rechazada("list sin nada", lambda: server.list_object_properties())
    rechazada("list con los dos", lambda: server.list_object_properties("Line", "A1"))
    rechazada("list con un nombre que no es de clase", lambda: server.list_object_properties("Line; DROP"))

    # ---- create_object
    r, ll = con_plugin(lambda: server.create_object("Circle", {"Center": [5, 5, 0], "Radius": 2.5}))
    check("create manda tipo y propiedades", ll[0], ("create_object",
          {"type": "Circle", "properties": {"Center": [5, 5, 0], "Radius": 2.5}}))
    r, ll = con_plugin(lambda: server.create_object("Solid3d"))
    check("create sin propiedades manda un objeto vacío", ll[0][1], {"type": "Solid3d", "properties": {}})
    r, ll = con_plugin(lambda: server.create_object("Solid3d", init_method="CreateBox", init_args=[10, 5, 3]))
    check("create con método: crea y luego llama", [c[0] for c in ll], ["create_object", "call_method"])
    check("el método se llama sobre la entidad nueva", ll[1][1]["method"], "CreateBox")
    rechazada("create con nombre de clase inválido", lambda: server.create_object("Circle; x"))
    rechazada("create con propiedades que no son un objeto", lambda: server.create_object("Circle", ["Radius"]))
    rechazada("create con valor null", lambda: server.create_object("Circle", {"Radius": None}))
    rechazada("create con demasiadas propiedades", lambda: server.create_object("Circle", {"P%d" % i: 1 for i in range(61)}))
    # si el método de inicio falla, se borra lo creado
    llamadas: list[tuple[str, dict]] = []

    def falla(cmd, params=None):
        llamadas.append((cmd, params or {}))
        if cmd == "create_object":
            return {"handle": "AB", "type": "Solid3d"}
        if cmd == "call_method":
            raise server.acad.AutoCadError("AutoCAD rechazó la llamada")
        return {}

    real = server.acad.call
    server.acad.call = falla
    try:
        try:
            server.create_object("Solid3d", init_method="CreateBox", init_args=[1, 1, 1])
            check("método que falla propaga el error", False, True)
        except server.acad.AutoCadError:
            check("método que falla propaga el error", True, True)
    finally:
        server.acad.call = real
    check("...y borra la entidad vacía", llamadas[-1], ("delete_entity", {"handle": "AB"}))

    # ---- list_children y el seudo-objeto DATABASE
    r, ll = con_plugin(lambda: server.list_children())
    check("list_children sin nada: la raiz", ll[0], ("list_children", {"target": "DATABASE", "skip": 0, "take": 500}))
    r, ll = con_plugin(lambda: server.list_children("Layers", 10, 50))
    check("nombre corto en minuscula", ll[0][1], {"target": "layers", "skip": 10, "take": 50})
    r, ll = con_plugin(lambda: server.list_children("3e5c"))
    check("handle en mayuscula", ll[0][1]["target"], "3E5C")
    r, ll = con_plugin(lambda: server.list_children("database"))
    check("database en cualquier caso", ll[0][1]["target"], "DATABASE")
    rechazada("list_children con un nombre desconocido", lambda: server.list_children("capas"))
    rechazada("list_children con skip negativo", lambda: server.list_children("layers", -1))
    rechazada("list_children con take enorme", lambda: server.list_children("layers", 0, 5000))
    rechazada("list_children con target vacio", lambda: server.list_children(""))
    r, ll = con_plugin(lambda: server.get_object_properties(["database", "A1"], ["Ltscale"]))
    check("get acepta DATABASE junto a handles", ll[0][1]["handles"], ["DATABASE", "A1"])
    r, ll = con_plugin(lambda: server.set_object_properties(["DATABASE"], {"Ltscale": 2.0}))
    check("set acepta DATABASE", ll[0][1]["handles"], ["DATABASE"])

    # ---- create/delete_database_object y container
    r, ll = con_plugin(lambda: server.create_database_object("Layer", "MUROS", {"Color": 7, "IsLocked": False}))
    check("create layer manda kind en minuscula, nombre y propiedades", ll[0], ("create_database_object",
          {"kind": "layer", "name": "MUROS", "properties": {"Color": 7, "IsLocked": False}}))
    r, ll = con_plugin(lambda: server.create_database_object("block", "MI-BLOQUE"))
    check("create sin propiedades manda objeto vacio", ll[0][1]["properties"], {})
    for k in ("layer", "textstyle", "dimstyle", "block", "regapp", "ucs"):
        r, ll = con_plugin(lambda k=k: server.create_database_object(k, "X1"))
        check(f"create acepta kind {k}", ll[0][1]["kind"], k)
    rechazada("create con kind desconocido", lambda: server.create_database_object("material", "X"))
    rechazada("create con nombre vacio", lambda: server.create_database_object("layer", ""))
    rechazada("create con espacios en los bordes", lambda: server.create_database_object("layer", " MUROS"))
    rechazada("create con caracter reservado", lambda: server.create_database_object("layer", "MUROS/1"))
    rechazada("create con dos puntos", lambda: server.create_database_object("layer", "A:B"))
    rechazada("create con nombre que empieza con *", lambda: server.create_database_object("block", "*Mio"))
    rechazada("create con nombre larguisimo", lambda: server.create_database_object("layer", "x" * 256))
    rechazada("create con el nombre en properties", lambda: server.create_database_object("layer", "A", {"Name": "B"}))
    rechazada("create con valor null", lambda: server.create_database_object("layer", "A", {"Color": None}))
    rechazada("create con properties que no es objeto", lambda: server.create_database_object("layer", "A", ["Color"]))
    r, ll = con_plugin(lambda: server.delete_database_object("layer", name="MUROS"))
    check("delete por nombre", ll[0], ("delete_database_object", {"kind": "layer", "name": "MUROS"}))
    r, ll = con_plugin(lambda: server.delete_database_object("block", handle="a1"))
    check("delete por handle", ll[0], ("delete_database_object", {"kind": "block", "handle": "A1"}))
    rechazada("delete sin nombre ni handle", lambda: server.delete_database_object("layer"))
    rechazada("delete con nombre y handle", lambda: server.delete_database_object("layer", "A", "A1"))
    rechazada("delete de DATABASE", lambda: server.delete_database_object("layer", handle="DATABASE"))
    rechazada("delete con kind desconocido", lambda: server.delete_database_object("layout", "BP-01"))
    r, ll = con_plugin(lambda: server.create_object("Line", {"StartPoint": [0, 0, 0]}, container="MI-BLOQUE"))
    check("create_object con container", ll[0][1].get("container"), "MI-BLOQUE")
    rechazada("create_object con container vacio", lambda: server.create_object("Line", None, container=" "))

    # ---- sesión: leer es de lectura; cambiar no se reintenta
    check("get_properties es de lectura", session.retry_safe("get_properties"), True)
    check("list_properties es de lectura", session.retry_safe("list_properties"), True)
    check("set_properties NO se reintenta", session.retry_safe("set_properties"), False)

    if FAILED:
        print("\nFALLARON:")
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
