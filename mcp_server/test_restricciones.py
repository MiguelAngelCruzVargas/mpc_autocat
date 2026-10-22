"""Tests de las tools de restricciones paramétricas (bd_extra.py + server.py) contra el socket mockeado. Sin AutoCAD.

Uso:  python test_restricciones.py
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
    check(f"{nombre}: no toca AutoCAD", ll, [])


def main() -> int:
    r, ll = con_plugin(lambda: server.add_geometric_constraint("horizontal", ["a1"]))
    check("horizontal con un handle", ll[0], ("add_geometric_constraint", {"type": "horizontal", "targets": [{"handle": "A1"}]}))
    r, ll = con_plugin(lambda: server.add_geometric_constraint("coincident", [{"handle": "a1", "point": "end"}, {"handle": "b2", "point": "start"}]))
    check("coincident con puntos", ll[0][1]["targets"], [{"handle": "A1", "point": "end"}, {"handle": "B2", "point": "start"}])
    r, ll = con_plugin(lambda: server.add_geometric_constraint("tangent", [{"handle": "a1"}, {"handle": "b2", "segment": 2}]))
    check("segmento de polilinea", ll[0][1]["targets"][1], {"handle": "B2", "segment": 2})
    rechazada("tipo inexistente", lambda: server.add_geometric_constraint("magica", ["a1"]))
    rechazada("parallel con un solo objetivo", lambda: server.add_geometric_constraint("parallel", ["a1"]))
    rechazada("coincident sin puntos", lambda: server.add_geometric_constraint("coincident", ["a1", "b2"]))
    rechazada("punto inexistente", lambda: server.add_geometric_constraint("coincident", [{"handle": "a1", "point": "arriba"}, {"handle": "b2", "point": "end"}]))
    rechazada("campo desconocido", lambda: server.add_geometric_constraint("fix", [{"handle": "a1", "color": 3}]))
    rechazada("handle invalido", lambda: server.add_geometric_constraint("fix", ["zz"]))
    rechazada("segmento negativo", lambda: server.add_geometric_constraint("fix", [{"handle": "a1", "segment": -1}]))
    rechazada("demasiados objetivos", lambda: server.add_geometric_constraint("equal_length", ["a1"] * 1 + [f"{i:X}" for i in range(1, 12)]))

    r, ll = con_plugin(lambda: server.add_dimensional_constraint("distance", ["a1"], 20, "largo"))
    check("distancia de una linea", ll[0][1], {"kind": "distance", "targets": [{"handle": "A1"}], "value": 20.0, "dimension": True, "name": "largo"})
    r, ll = con_plugin(lambda: server.add_dimensional_constraint("horizontal", [{"handle": "a1", "point": "start"}, {"handle": "b2", "point": "end"}], 5, dimension=False, offset=0.5))
    check("horizontal entre dos puntos sin cota", (ll[0][1]["dimension"], ll[0][1]["offset"]), (False, 0.5))
    r, ll = con_plugin(lambda: server.add_dimensional_constraint("angle", ["a1", "b2"], 60))
    check("angulo entre dos lineas", ll[0][1]["targets"], [{"handle": "A1"}, {"handle": "B2"}])
    rechazada("kind inexistente", lambda: server.add_dimensional_constraint("radius", ["a1"], 3))
    rechazada("valor 0", lambda: server.add_dimensional_constraint("distance", ["a1"], 0))
    rechazada("valor negativo", lambda: server.add_dimensional_constraint("distance", ["a1"], -3))
    rechazada("angulo de 360", lambda: server.add_dimensional_constraint("angle", ["a1", "b2"], 360))
    rechazada("angulo con una linea", lambda: server.add_dimensional_constraint("angle", ["a1"], 45))
    rechazada("dos objetivos sin puntos", lambda: server.add_dimensional_constraint("distance", ["a1", "b2"], 5))
    rechazada("nombre con espacio", lambda: server.add_dimensional_constraint("distance", ["a1"], 5, "mi variable"))
    rechazada("nombre que empieza con numero", lambda: server.add_dimensional_constraint("distance", ["a1"], 5, "1largo"))
    rechazada("offset 0", lambda: server.add_dimensional_constraint("distance", ["a1"], 5, offset=0))

    r, ll = con_plugin(lambda: server.set_constraint_value("largo", 25))
    check("set_constraint_value", ll[0], ("set_constraint_value", {"name": "largo", "value": 25.0}))
    rechazada("valor de variable 0", lambda: server.set_constraint_value("largo", 0))
    rechazada("variable sin nombre", lambda: server.set_constraint_value("", 5))
    r, ll = con_plugin(lambda: server.list_constraints())
    check("list_constraints", ll[0], ("list_constraints", {}))
    r, ll = con_plugin(lambda: server.remove_constraints(["a1", "b2"]))
    check("remove_constraints por handles", ll[0][1], {"handles": ["A1", "B2"]})
    r, ll = con_plugin(lambda: server.remove_constraints(all=True))
    check("remove_constraints todas", ll[0][1], {"all": True})
    rechazada("remove sin nada", lambda: server.remove_constraints())
    rechazada("remove con las dos", lambda: server.remove_constraints(["a1"], all=True))
    check("list_constraints es de lectura", session.retry_safe("list_constraints"), True)
    for cambio in ("add_geometric_constraint", "add_dimensional_constraint", "set_constraint_value", "remove_constraints"):
        check(f"{cambio} NO se reintenta", session.retry_safe(cambio), False)

    if FAILED:
        print("\nFALLARON:")
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
