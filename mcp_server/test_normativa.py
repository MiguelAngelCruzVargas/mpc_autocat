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


def test_investigar_y_valores_locales() -> None:
    p = normativa.resolver("Perú")
    check("no codificada trae plan para investigar", len(p["investigar"]) >= 4
          and "WebSearch" in p["investigar"][0])
    import rules
    rooms = [{"name": "RECAMARA", "x0": 0, "y0": 0, "x1": 2.6, "y1": 3.0}]
    base = rules.check_geometry(rooms, [])
    check("México: 2.6 m de lado pasa", not any(
        "dimension minima" == q["rule"] for q in base["problems"]))

    @normativa.con_pais()
    def revisa(rooms: list, doors: list) -> dict:
        return rules.check_geometry(rooms, doors)
    r = revisa(rooms, [], country="Perú", local_norms={
        "fuente": "Norma X art. 5 (2024) https://ejemplo", "minimos": {"recamara": {"lado": 2.8}}})
    check("el valor local manda sobre el de México", any(
        q["rule"] == "dimension minima" for q in r["problems"]), r["problems"])
    check("la fuente queda en el resultado",
          r["normativa"]["valores_locales"]["fuente"].startswith("Norma X"))
    check("el valor local no se filtra a la llamada siguiente", not any(
        q["rule"] == "dimension minima" for q in rules.check_geometry(rooms, [])["problems"]))
    for malo, motivo in (({"minimos": {}}, "sin fuente"),
                         ({"fuente": "x", "pasillo": 1.2}, "clave no soportada")):
        try:
            revisa(rooms, [], country="Perú", local_norms=malo)
            check(f"rechaza {motivo}", False)
        except ValueError:
            check(f"rechaza {motivo}", True)


def test_peru_sanitaria() -> None:
    import server
    check("Perú sanitaria codificada, eléctrica no",
          normativa.resolver("Perú", "sanitaria")["estado"] == "codificada"
          and normativa.resolver("Perú", "electrica")["estado"] == "no_codificada")
    r = server.suggest_layout(lot_width=9, lot_depth=16, bedrooms=3, bathrooms=2)
    pe = server.suggest_sanitary(rooms=r["rooms"], doors=r["doors"], country="Perú", draw=False)
    mx = server.suggest_sanitary(rooms=r["rooms"], doors=r["doors"], country="México", draw=False)
    pend = {p["diameter_mm"]: p["slope"] for p in pe["pipes"]}
    check("Perú: 1,5 % en Ø<=75 y 1 % en Ø>=100 (IS.010 6.2 c)",
          all(s == 0.015 for d, s in pend.items() if d <= 75)
          and all(s == 0.01 for d, s in pend.items() if d >= 100), pend)
    check("Perú: el inodoro llega con Ø100", any(d >= 100 for d in pend))
    check("Perú: registros cada 15 m y cajas CR", pe["criteria"]["registro_max_m"] == 15.0
          and pe["registers"][0]["name"].startswith("CR"))
    check("México no cambia: 2 %, albañal 150, R-n",
          mx["criteria"]["pendiente_drenaje"] == 0.02
          and mx["sewer"]["diameter_mm"] == 150 and mx["registers"][0]["name"] == "R-1")
    check("la fuente y lo por verificar viajan en el resultado",
          "IS.010" in pe["normativa"]["fuente"] and pe["normativa"]["verificar"])
    check("el perfil no se filtra a la llamada siguiente", normativa.perfil("sanitaria") is None)
    try:
        server.suggest_electrical(rooms=r["rooms"], doors=r["doors"], country="Perú")
        check("Perú eléctrica sigue sin dibujar", False)
    except ValueError:
        check("Perú eléctrica sigue sin dibujar", True)


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
