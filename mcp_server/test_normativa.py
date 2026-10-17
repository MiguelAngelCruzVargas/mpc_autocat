"""Tests de normativa.py (país y norma aplicada). NO necesita AutoCAD.

Uso:  python test_normativa.py
"""
from __future__ import annotations

import asyncio
import inspect
import sys

import normativa

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def test_resolver() -> None:
    check("México con acento", normativa.resolver("México")["estado"] == "codificada")
    check("mexico sin acento y mayúsculas", normativa.resolver(" MEXICO ")["codigo"] == "MX")
    p = normativa.resolver("Perú")
    check("Perú no codificada, con orientación", p["estado"] == "no_codificada"
          and p["orientacion"] and "NO son válidos" in p["advertencia"], p)
    check("país desconocido no inventa nada",
          normativa.resolver("Bolivia")["estado"] == "no_codificada")
    check("sin país pide el dato", normativa.resolver(None)["estado"] == "sin_pais"
          and "país" in normativa.resolver("")["advertencia"])


@normativa.con_pais(dibuja="draw")
def _tool_dibuja(a: int, draw: bool = True) -> dict:
    return {"a": a, "draw": draw}


@normativa.con_pais()
def _tool_calcula(a: int) -> dict:
    return {"a": a}


def test_decorador() -> None:
    r = _tool_dibuja(1, country="México")
    check("MX dibuja y anota normativa", r["a"] == 1 and r["normativa"]["estado"] == "codificada")
    try:
        _tool_dibuja(1, country="Perú")
        check("otro país no dibuja", False, "no tiró")
    except ValueError as e:
        check("otro país no dibuja con norma ajena", "no está codificada" in str(e))
    r = _tool_dibuja(1, country="Perú", accept_reference=True)
    check("accept_reference deja pasar y avisa",
          r["normativa"]["estado"] == "no_codificada" and r["warnings"])
    r = _tool_dibuja(1, country="Perú", draw=False)
    check("draw=False deja ver el proyecto", r["a"] == 1)
    r = _tool_calcula(2, country="Colombia")
    check("lo que no dibuja pasa con advertencia", r["normativa"]["advertencia"])
    r = _tool_calcula(3)
    check("sin país: pasa pero pide el dato", r["normativa"]["estado"] == "sin_pais")
    sig = inspect.signature(_tool_calcula)
    check("la firma expone country y accept_reference",
          "country" in sig.parameters and "accept_reference" in sig.parameters)


def test_tools_del_servidor() -> None:
    import server
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    check("get_normative expuesta", "get_normative" in tools)
    for n in ("suggest_layout", "check_program", "check_layout", "check_geometry",
              "suggest_electrical", "suggest_hydraulic", "suggest_sanitary",
              "design_footing"):
        props = tools[n].inputSchema["properties"]
        check(f"{n} pide country", "country" in props and "accept_reference" in props)
    q = server.get_normative()
    check("get_normative sin país pregunta", "pregunta" in q and q["paises"])
    try:
        server.suggest_electrical(rooms=[], doors=[], country="Perú")
        check("suggest_electrical no dibuja para Perú", False)
    except ValueError:
        check("suggest_electrical no dibuja para Perú", True)


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_") and callable(fn):
            print(n)
            fn()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" -", f)
        sys.exit(1)
    print("\nOK")
