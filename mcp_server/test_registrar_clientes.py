"""Tests de tools/registrar_clientes.py (alta del MCP en Claude Desktop,
OpenCode y Claude Code) sobre carpetas temporales. NO toca la configuración
real ni necesita AutoCAD.

Uso:  python test_registrar_clientes.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import registrar_clientes as rc  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name + (f" -- {detalle}" if not ok else ""))


PY, SRV = r"C:\app\.venv\Scripts\python.exe", r"C:\app\mcp_server\server.py"


def entorno(d: str) -> dict[str, str]:
    return {"APPDATA": os.path.join(d, "AppData"), "USERPROFILE": os.path.join(d, "home"),
            "HOME": os.path.join(d, "home")}


def test_claude_desktop() -> None:
    with tempfile.TemporaryDirectory() as d:
        env = entorno(d)
        p = rc.ruta_claude_desktop(env)
        os.makedirs(os.path.dirname(p))
        json.dump({"theme": "dark", "mcpServers": {"otro": {"command": "x"}}}, open(p, "w"))
        check("registra", rc.registrar_claude_desktop(PY, SRV, env) == "registrado")
        data = json.load(open(p))
        check("agrega autocad", data["mcpServers"]["autocad"] == {"command": PY, "args": [SRV]})
        check("no pisa lo que había", data["theme"] == "dark" and "otro" in data["mcpServers"])
        check("hace copia de seguridad", os.path.exists(p + ".bak-autocad-ia"))
        check("idempotente", rc.registrar_claude_desktop(PY, SRV, env) == "ya estaba")
        check("quita solo lo suyo", rc.quitar_claude_desktop(env) == "quitado"
              and "otro" in json.load(open(p))["mcpServers"]
              and "autocad" not in json.load(open(p))["mcpServers"])
        check("quitar de nuevo no falla", rc.quitar_claude_desktop(env) == "no estaba")


def test_claude_desktop_sin_archivo() -> None:
    with tempfile.TemporaryDirectory() as d:
        env = entorno(d)
        check("crea el archivo si no existe", rc.registrar_claude_desktop(PY, SRV, env) == "registrado"
              and os.path.exists(rc.ruta_claude_desktop(env)))


def test_json_roto_no_se_toca() -> None:
    with tempfile.TemporaryDirectory() as d:
        env = entorno(d)
        p = rc.ruta_claude_desktop(env)
        os.makedirs(os.path.dirname(p))
        open(p, "w").write("{ esto no es json")
        r = rc.registrar(["claude-desktop"], PY, SRV, env)
        check("un JSON roto se informa y no se pisa",
              r["claude-desktop"].startswith("falló") and open(p).read() == "{ esto no es json")


def test_opencode() -> None:
    with tempfile.TemporaryDirectory() as d:
        env = entorno(d)
        p = rc.ruta_opencode(env)
        check("formato actual: mcp.autocad", rc.registrar_opencode(PY, SRV, env) == "registrado"
              and json.load(open(p))["mcp"]["autocad"] == {
                  "type": "local", "command": [PY, SRV], "enabled": True})
        check("idempotente", rc.registrar_opencode(PY, SRV, env) == "ya estaba")
        rc.quitar_opencode(env)
        check("quitar", "autocad" not in json.load(open(p))["mcp"])
    with tempfile.TemporaryDirectory() as d:
        env = entorno(d)
        p = rc.ruta_opencode(env)
        os.makedirs(os.path.dirname(p))
        json.dump({"mcp": {"servers": {"x": {"type": "local", "command": ["y"]}}}}, open(p, "w"))
        rc.registrar_opencode(PY, SRV, env)
        data = json.load(open(p))
        check("formato v2 se respeta (mcp.servers)", "autocad" in data["mcp"]["servers"]
              and "autocad" not in data["mcp"] and "x" in data["mcp"]["servers"])


def test_claude_code_y_deteccion() -> None:
    cmd = rc.comando_claude_code(PY, SRV)
    check("comando de claude code", cmd[:6] == ["claude", "mcp", "add", "--scope", "user", "autocad"]
          and cmd[-2:] == [PY, SRV], cmd)
    with tempfile.TemporaryDirectory() as d:
        env = entorno(d)
        os.makedirs(os.path.dirname(rc.ruta_claude_desktop(env)))
        check("detecta Claude Desktop por su carpeta", "claude-desktop" in rc.detectar(env))
    check("cliente desconocido se informa",
          rc.registrar(["chatgpt"], PY, SRV, {"APPDATA": "x"})["chatgpt"] == "cliente desconocido")


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
