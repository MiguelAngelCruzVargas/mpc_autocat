"""Tests de run_command (comandos.py + edicion.comando + server.run_command) contra el socket mockeado.
NO necesita AutoCAD.

Lo que se verifica es lo de este lado: que la lista negra rechace antes de tocar AutoCAD lo que no debe
correr, que lo permitido llegue al plugin tal cual (op "command" + tokens), que espere el resultado, y que
la lista negra de Python y la del plugin (C#) digan lo mismo.

Uso:  python test_comandos.py
"""
from __future__ import annotations

import os
import re

import comandos
import edicion
import server

FAILED: list[str] = []


def check(name: str, got, expected) -> None:
    ok = got == expected
    if not ok:
        FAILED.append(f"{name}: esperaba {expected!r}, obtuve {got!r}")
    print(("  ok  " if ok else " FALLA ") + name)


class Plugin:
    def __init__(self):
        self.llamadas: list[tuple[str, dict]] = []

    def __call__(self, cmd, params=None):
        self.llamadas.append((cmd, params or {}))
        if cmd == "native_op":
            return {"jobId": "op1", "state": "queued"}
        if cmd == "native_status":
            return {"state": "done", "jobId": "op1", "created": [{"handle": "2B0", "type": "Circle"}],
                    "deleted": [], "deletedCount": 0, "modified": [], "changed": True}
        raise AssertionError(f"comando no mockeado: {cmd}")


def con_plugin(p, fn):
    real, paso = server.acad.call, edicion._PASO_S
    server.acad.call, edicion._PASO_S = p, 0.0
    try:
        return fn()
    finally:
        server.acad.call, edicion._PASO_S = real, paso


def rechazado(nombre, tokens):
    p = Plugin()
    r = con_plugin(p, lambda: server.run_command(tokens))
    check(f"{nombre}: se rechaza", r.get("ok"), False)
    check(f"{nombre}: dice por qué", bool(r.get("error")), True)
    check(f"{nombre}: no toca AutoCAD", p.llamadas, [])


def test_lista_negra() -> None:
    print("test_lista_negra")
    for c in ("NETLOAD", "APPLOAD", "LISP", "SCRIPT", "SHELL", "STARTAPP", "BROWSER", "MENULOAD", "OPTIONS", "QUIT", "EXIT", "CLOSEALL"):
        rechazado(f"{c}", [c, "x"])
    rechazado("con prefijo nativo _.", ["_.NETLOAD", "a.dll"])
    rechazado("con guion (-OPTIONS)", ["-OPTIONS"])
    rechazado("en minúsculas", ["netload"])
    rechazado("con espacios", ["  quit  "])
    rechazado("variable de seguridad como comando", ["SECURELOAD", 0])
    rechazado("SETVAR de una protegida", ["SETVAR", "trustedpaths", "C:\\"])
    rechazado("LISP en el primer token", ["(command \"erase\")"])
    rechazado("LISP escondido en una respuesta", ["TEXT", "0,0", "2", "0", "(progn (startapp \"calc\"))"])
    rechazado("expresión ! de LISP", ["MOVE", "!x"])
    rechazado("sin tokens", [])
    rechazado("no es lista", "LINE 0,0 5,5")
    rechazado("primer token número", [5, "LINE"])
    rechazado("token booleano", ["LINE", True])
    rechazado("token objeto", ["LINE", {"x": 1}])
    rechazado("número NaN", ["CIRCLE", "0,0", float("nan")])
    rechazado("demasiados tokens", ["LINE"] + ["0,0"] * comandos.MAX_TOKENS)
    rechazado("token enorme", ["TEXT", "x" * (comandos.MAX_LARGO + 1)])
    rechazado("comando vacío", ["   "])
    # Encadenar comandos: Editor.Command corre los tokens que sobran como comandos nuevos.
    rechazado("SCRIPT encadenado tras REGEN", ["REGEN", "SCRIPT", r"C:\x.scr"])
    rechazado("APPLOAD encadenado", ["ZOOM", "Extents", "_.APPLOAD", "x"])
    rechazado("NETLOAD con prefijo en medio", ["REGEN", "'_NETLOAD"])
    rechazado("SCRIPT dentro de un token con espacio", ["REGEN", "0,0 SCRIPT"])
    rechazado("SCRIPT tras el nombre en el primer token", ["REGEN SCRIPT"])
    rechazado("variable protegida encadenada", ["REGEN", "SECURELOAD", 0])
    for c in ("OPEN", "SAVEAS", "WBLOCK", "-HYPERLINK", "XATTACH", "-XREF", "IMPORT", "EXPORT"):
        rechazado(f"{c} como comando", [c, "x"])
    rechazado("OPEN encadenado", ["REGEN", "OPEN", r"C:\a.dwg"])
    rechazado("ruta UNC", ["-INSERT", r"\\servidor\c\b.dwg", "0,0"])
    rechazado("archivo .lsp", ["-INSERT", r"C:\x\acad.lsp"])
    rechazado("archivo .dll", ["REGEN", r"C:\x\a.dll"])
    rechazado("archivo .scr con comillas", ["-INSERT", r'"C:\x.scr"'])


def test_permitido() -> None:
    print("test_lo_permitido_llega_al_plugin")
    p = Plugin()
    r = con_plugin(p, lambda: server.run_command(["CIRCLE", "0,0", 5]))
    check("manda native_op con op=command y los tokens", p.llamadas[0],
          ("native_op", {"op": "command", "tokens": ["CIRCLE", "0,0", 5]}))
    check("espera el resultado", r["state"], "done")
    check("ok=True", r["ok"], True)
    check("devuelve lo creado", r["created"][0]["handle"], "2B0")
    p = Plugin()
    con_plugin(p, lambda: server.run_command(["-LAYER", "Make", "MUROS", None]))
    check("null = Enter llega como null", p.llamadas[0][1]["tokens"], ["-LAYER", "Make", "MUROS", None])
    p = Plugin()
    con_plugin(p, lambda: server.run_command(["TEXT", "0,0", "2", "0", "Cocina (1)"]))
    check("paréntesis dentro del texto (no al inicio) se permite", p.llamadas[0][0], "native_op")
    p = Plugin()
    con_plugin(p, lambda: server.run_command(["ZOOM", "Extents"]))
    check("ZOOM, REGEN y compañía se permiten", p.llamadas[0][1]["tokens"], ["ZOOM", "Extents"])
    check("SETVAR de una variable normal se permite", comandos.motivo_denegado(["SETVAR", "LTSCALE", "50"]), None)
    check("UNDO Mark / Back del agente se permite", comandos.motivo_denegado(["UNDO", "Mark"]), None)
    check("PEDIT con eXit se permite", comandos.motivo_denegado(["PEDIT", "2B0", "Close", "eXit"]), None)
    check("-LAYER Estado Save se permite", comandos.motivo_denegado(["-LAYER", "State", "Save", "E1", "", ""]), None)
    check("texto con paréntesis y comas se permite", comandos.motivo_denegado(["-TEXT", "0,0", "2", "0", "Recámara 2 (3.5 x 4)"]), None)
    check("archivo .json no es .js", comandos.motivo_denegado(["-INSERT", r"C:\x\datos.json"]), None)
    check("-INSERT de un bloque local se permite", comandos.motivo_denegado(["-INSERT", "PUERTA", "0,0", "1", "1", "0"]), None)
    check("la tool está registrada en una categoría", "run_command" in server.mcp._tool_manager._tools, True)


def test_igual_que_el_plugin() -> None:
    print("test_la_lista_negra_es_igual_en_el_plugin")
    cs = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin", "AutoCadMcpPlugin", "Commands", "NativeOpsCommand.cs")
    src = open(cs, encoding="utf-8").read()
    bloque = re.search(r"ComandosDenegados\s*=\s*\{(.*?)\};", src, re.S).group(1)
    del_cs = tuple(re.findall(r'"([A-Z0-9]+)"', bloque))
    check("C# y Python niegan los mismos comandos", del_cs, comandos.DENEGADOS)
    bloque = re.search(r"EjecutanCodigo\s*=\s*\{(.*?)\};", src, re.S).group(1)
    check("y las mismas palabras dentro de un token", tuple(re.findall(r'"([A-Z0-9]+)"', bloque)), comandos.EJECUTAN_CODIGO)
    bloque = re.search(r"ExtensionesCodigo\s*=\s*\{(.*?)\};", src, re.S).group(1)
    check("y las mismas extensiones de código", tuple(re.findall(r'"(\.[a-z0-9]+)"', bloque)), comandos.EXTENSIONES_CODIGO)
    bloque = re.search(r"DenegadosEnCualquierToken\s*=.*?\);", src, re.S).group(0)
    fuera = tuple(re.findall(r'c != "([A-Z]+)"', bloque))
    check("y exceptúan las mismas en cualquier token", tuple(c for c in comandos.DENEGADOS if c not in fuera),
          comandos.DENEGADOS_EN_CUALQUIER_TOKEN)
    sv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin", "AutoCadMcpPlugin", "Commands", "SystemVariableCommands.cs")
    src = open(sv, encoding="utf-8").read()
    bloque = re.search(r"Protegidas\s*=\s*new HashSet<string>\((.*?)\};", src, re.S).group(1)
    protegidas_cs = set(re.findall(r'"([A-Z0-9]+)"', bloque))
    check("y protegen las mismas variables que set_system_variable", protegidas_cs, set(comandos.PROTEGIDAS))


if __name__ == "__main__":
    test_lista_negra()
    test_permitido()
    test_igual_que_el_plugin()
    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        raise SystemExit(1)
    print("\nOK: run_command rechaza lo prohibido antes de tocar AutoCAD y manda el resto como Editor.Command.")
