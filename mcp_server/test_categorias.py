"""Toda tool del MCP está en UNA categoría, y toda categoría apunta a tools que existen. Sin AutoCAD.

Uso:  python test_categorias.py
"""
from __future__ import annotations

import asyncio

import categorias as cat
import server

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name + (f" -- {detalle}" if not ok and detalle else ""))


def main() -> int:
    tools = {t.name for t in asyncio.run(server.mcp.list_tools())}
    cats = set(cat.todas())
    sin = sorted(tools - cats)
    check("toda tool tiene categoría", not sin, f"sin categoría: {sin}")
    fantasmas = sorted(cats - tools)
    check("toda categoría apunta a una tool que existe", not fantasmas, f"no existen: {fantasmas}")
    malas = sorted({c for c, _ in cat.todas().values()} - set(cat.CATEGORIAS))
    check("las categorías usadas están declaradas", not malas, str(malas))
    for k in cat.CATEGORIAS:
        check(f"categoría {k} no está vacía", len(cat.tools_en(k)) > 0)
    for f, d in cat.FLUJOS.items():
        check(f"flujo {f} tiene pasos", len(d["pasos"]) >= 4)
    r = server.list_tool_categories()
    check("sin argumentos lista categorías y flujos", len(r["categorias"]) == len(cat.CATEGORIAS) and "casa" in r["flujos"], str(r)[:200])
    r = server.list_tool_categories(category="p_arq")
    check("category lista sus tools con descripción", r["tools"] and all("que_hace" in t for t in r["tools"]), str(r)[:200])
    r = server.list_tool_categories(workflow="casa")
    check("workflow casa da pasos numerados", r["pasos"][0]["n"] == 1 and len(r["pasos"]) >= 10, str(r)[:200])
    r = server.list_tool_categories(query="zapata")
    check("query encuentra las tools de zapata", any(t["tool"] == "design_footing" for t in r["resultados"]), str(r)[:200])
    check("category inválida se rechaza", server.list_tool_categories(category="nada").get("ok") is False)
    check("workflow inválido se rechaza", server.list_tool_categories(workflow="nada").get("ok") is False)
    if FAILED:
        print("\nFALLARON:")
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
