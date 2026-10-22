"""Tests de get_system_variables / set_system_variable / get_editor_state
(server.py) contra el socket mockeado. NO necesita AutoCAD.

El comportamiento de AutoCAD (qué variables existen, cuáles son de solo
lectura) se verifica en vivo; acá se verifica el puente: que cada tool mande
al plugin el comando y los parámetros correctos, y cómo las cuenta la sesión
(leer no ensucia el dibujo; cambiar una variable sí).

Uso:  python test_sysvars.py
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


def main() -> int:
    real = server.acad.call
    llamadas: list[tuple[str, dict]] = []

    def fake(cmd, params=None):
        llamadas.append((cmd, params or {}))
        if cmd == "get_system_variables":
            return {"values": {"LTSCALE": 1.0}, "errors": {"NOEXISTE": "no existe"}}
        if cmd == "set_system_variable":
            return {"name": params["name"].upper(), "previous": 1.0, "value": params["value"]}
        if cmd == "get_editor_state":
            return {"document": "x.dwg", "busy": False}
        raise AssertionError(f"comando no mockeado: {cmd}")

    server.acad.call = fake
    try:
        r = server.get_system_variables(["ltscale", "noexiste"])
        check("get manda los nombres", llamadas[-1], ("get_system_variables", {"names": ["ltscale", "noexiste"]}))
        check("get devuelve values y errors", sorted(r), ["errors", "values"])

        r = server.set_system_variable("ltscale", 50)
        check("set manda nombre y valor", llamadas[-1], ("set_system_variable", {"name": "ltscale", "value": 50}))
        check("set devuelve el valor anterior", r["previous"], 1.0)
        r = server.set_system_variable("dimscale", [1, 2])
        check("set acepta un punto", llamadas[-1][1]["value"], [1, 2])

        r = server.get_editor_state()
        check("estado sin parametros", llamadas[-1], ("get_editor_state", {}))
        check("estado devuelve busy", r["busy"], False)
    finally:
        server.acad.call = real

    # La sesión: leer no ensucia; cambiar una variable sí (muchas se guardan en el DWG).
    check("get_system_variables es de lectura", session.retry_safe("get_system_variables"), True)
    check("get_editor_state es de lectura", session.retry_safe("get_editor_state"), True)
    check("set_system_variable NO se reintenta", session.retry_safe("set_system_variable"), False)

    if FAILED:
        print("\nFALLARON:")
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
