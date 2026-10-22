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
        return {"ok": True, "echo": cmd}

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
