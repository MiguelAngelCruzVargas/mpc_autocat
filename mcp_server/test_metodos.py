"""Tests de list_object_methods / call_object_method (metodos.py + server.py)
contra el socket mockeado. NO necesita AutoCAD.

Qué métodos se admiten (la lista blanca de forma y la negra de nombres) lo
decide el plugin y se verifica en vivo; acá se verifica lo de este lado:
que se rechace antes de tocar AutoCAD lo que no tiene sentido y que cada tool
mande al plugin el comando y los parámetros correctos.

Uso:  python test_metodos.py
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


def main() -> int:
    r, ll = con_plugin(lambda: server.list_object_methods("Polyline"))
    check("list por tipo", ll[0], ("list_methods", {"type": "Polyline"}))
    r, ll = con_plugin(lambda: server.list_object_methods(handle="a1", filter="Offset"))
    check("list por handle con filtro", ll[0], ("list_methods", {"handle": "A1", "filter": "Offset"}))
    rechazada("list sin nada", lambda: server.list_object_methods())
    rechazada("list con los dos", lambda: server.list_object_methods("Line", "A1"))
    rechazada("list con nombre de clase inválido", lambda: server.list_object_methods("Line; x"))
    rechazada("list con filtro larguísimo", lambda: server.list_object_methods("Line", filter="x" * 61))

    r, ll = con_plugin(lambda: server.call_object_method("3e5c", "GetClosestPointTo", [[3, 4, 0], False]))
    check("call manda handle, método y argumentos", ll[0], ("call_method",
          {"handle": "3E5C", "method": "GetClosestPointTo", "args": [[3, 4, 0], False],
           "add_results_to_space": False}))
    r, ll = con_plugin(lambda: server.call_object_method("A1", "GetOffsetCurves", [0.5], add_results_to_space=True))
    check("call con add_results_to_space", ll[0][1]["add_results_to_space"], True)
    r, ll = con_plugin(lambda: server.call_object_method("A1", "Reverse"))
    check("call sin args manda lista vacía", ll[0][1]["args"], [])
    r, ll = con_plugin(lambda: server.call_object_method("A1", "Extend", [1.0], mode="write"))
    check("call con mode", ll[0][1]["mode"], "write")

    rechazada("call con handle inválido", lambda: server.call_object_method("zz", "Reverse"))
    rechazada("call con método vacío", lambda: server.call_object_method("A1", ""))
    rechazada("call con nombre que no es de método", lambda: server.call_object_method("A1", "Reverse(); x"))
    rechazada("call con método con punto", lambda: server.call_object_method("A1", "System.Diagnostics.Process.Start"))
    rechazada("call con args que no es lista", lambda: server.call_object_method("A1", "Reverse", "x"))
    rechazada("call con demasiados args", lambda: server.call_object_method("A1", "M", list(range(13))))
    rechazada("call con mode inválido", lambda: server.call_object_method("A1", "Reverse", [], mode="admin"))

    check("list_methods es de lectura", session.retry_safe("list_methods"), True)
    check("call_method NO se reintenta", session.retry_safe("call_method"), False)

    if FAILED:
        print("\nFALLARON:")
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
