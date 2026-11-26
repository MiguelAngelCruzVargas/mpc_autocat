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


def test_codex() -> None:
    """Codex sin su CLI: un bloque propio en ~/.codex/config.toml, sin tocar lo demás."""
    with tempfile.TemporaryDirectory() as d:
        env = entorno(d)
        ruta = rc.ruta_codex(env)
        os.makedirs(os.path.dirname(ruta))
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write('model = "gpt-6"\n\n[mcp_servers.otro]\ncommand = "npx"\n')
        check("codex: registra", rc.registrar(["codex"], PY, SRV, env)["codex"] == "registrado")
        texto = open(ruta, encoding="utf-8").read()
        check("codex: conserva lo que había", 'model = "gpt-6"' in texto and "[mcp_servers.otro]" in texto)
        check("codex: su tabla con las rutas escapadas", "[mcp_servers.autocad]" in texto
              and 'command = "C:\\\\app\\\\.venv' in texto, texto)
        try:
            import tomllib  # type: ignore
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore
            except ImportError:
                tomllib = None
        if tomllib is not None:
            datos = tomllib.loads(texto)
            check("codex: TOML válido con las rutas exactas",
                  datos["mcp_servers"]["autocad"] == {"command": PY, "args": [SRV]}, str(datos))
        check("codex: repetir no duplica", rc.registrar(["codex"], PY, SRV, env)["codex"] == "ya estaba"
              and open(ruta, encoding="utf-8").read().count("[mcp_servers.autocad]") == 1)
        check("codex: quitar deja lo demás", rc.quitar(["codex"], env)["codex"] == "quitado"
              and "[mcp_servers.autocad]" not in open(ruta, encoding="utf-8").read()
              and "[mcp_servers.otro]" in open(ruta, encoding="utf-8").read())
        with open(ruta, "a", encoding="utf-8") as fh:
            fh.write('\n[mcp_servers.autocad]\ncommand = "mio"\n')
        check("codex: un «autocad» ajeno no se pisa", "no se toca" in rc.registrar(["codex"], PY, SRV, env)["codex"])
        check("codex: se detecta por su carpeta", "codex" in rc.detectar(env))


def test_modo_amigable_para_el_cliente() -> None:
    """Lo que ve el cliente con CONECTAR_MI_SUSCRIPCION.bat: qué quedó conectado y qué sigue, sin jerga."""
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as d:
        env = entorno(d)
        server = os.path.join(d, "server.py")
        open(server, "w").close()
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            codigo = rc._amigable(PY, server, env)
        texto = salida.getvalue()
        check("sin programas: dice qué instalar y que la IA incluida no necesita nada",
              codigo == 0 and "claude.ai/download" in texto and "IA incluida" in texto, texto)
        os.makedirs(os.path.dirname(rc.ruta_claude_desktop(env)))
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            codigo = rc._amigable(PY, server, env)
        texto = salida.getvalue()
        check("con Claude de escritorio: LISTO y los pasos que siguen",
              codigo == 0 and "[LISTO]  Claude (app de escritorio)" in texto and "Cierra por completo" in texto, texto)
        check("y quedó escrito en su configuración", '"autocad"' in open(rc.ruta_claude_desktop(env), encoding="utf-8").read())
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            codigo = rc._amigable(PY, os.path.join(d, "no-existe.py"), env)
        check("sin servidor: pide reinstalar", codigo == 1 and "INSTALAR.bat" in salida.getvalue())


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
