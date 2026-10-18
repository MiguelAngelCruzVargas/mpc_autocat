"""Registrar el servidor MCP de AutoCAD en los clientes de IA instalados.

El servidor MCP no se "descubre" solo: cada cliente (Claude Desktop, Claude
Code, OpenCode...) lee su propia lista de servidores en su propio archivo de
configuración. Este módulo escribe esa entrada, SIN pisar lo que ya haya:
lee el JSON existente, agrega o reemplaza solo la clave 'autocad', guarda una
copia '.bak-autocad-ia' la primera vez y escribe de vuelta.

    python tools/registrar_clientes.py --python <python.exe> --server <server.py>
    python tools/registrar_clientes.py --quitar

Clientes:
  claude-desktop  %APPDATA%\\Claude\\claude_desktop_config.json   -> mcpServers
  claude-code     CLI 'claude mcp add --scope user'
  opencode        ~/.config/opencode/opencode.json              -> mcp
                  (formato actual: mcp.<nombre>; si el archivo ya usa el
                  formato v2, mcp.servers.<nombre>, se respeta)

ChatGPT de escritorio NO está: no carga servidores MCP locales por stdio. Con
ese modelo se usa el panel web de AutoCAD IA con una clave de OpenAI.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import Any, Callable, Optional

NOMBRE = "autocad"
CLIENTES = ("claude-desktop", "claude-code", "opencode")


def _env(env: Optional[dict[str, str]]) -> dict[str, str]:
    return dict(os.environ) if env is None else env


def ruta_claude_desktop(env: Optional[dict[str, str]] = None) -> str:
    e = _env(env)
    base = e.get("APPDATA") or os.path.join(e.get("HOME", os.path.expanduser("~")), ".config")
    return os.path.join(base, "Claude", "claude_desktop_config.json")


def ruta_opencode(env: Optional[dict[str, str]] = None) -> str:
    e = _env(env)
    home = e.get("USERPROFILE") or e.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".config", "opencode", "opencode.json")


def detectar(env: Optional[dict[str, str]] = None) -> list[str]:
    """Clientes que parecen estar instalados (por su carpeta de configuración
    o su comando en el PATH)."""
    out = []
    if os.path.isdir(os.path.dirname(ruta_claude_desktop(env))):
        out.append("claude-desktop")
    if shutil.which("claude"):
        out.append("claude-code")
    if os.path.isdir(os.path.dirname(ruta_opencode(env))) or shutil.which("opencode"):
        out.append("opencode")
    return out


def _leer(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        txt = f.read().strip()
    if not txt:
        return {}
    try:
        data = json.loads(txt)
    except json.JSONDecodeError as ex:
        raise ValueError(
            f"{path} no es JSON válido ({ex}). No se toca: corregilo a mano o "
            "borralo, y volvé a correr el instalador.") from ex
    if not isinstance(data, dict):
        raise ValueError(f"{path}: se esperaba un objeto JSON.")
    return data


def _guardar(path: str, data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bak = path + ".bak-autocad-ia"
    if os.path.exists(path) and not os.path.exists(bak):
        shutil.copy2(path, bak)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _editar(path: str, fn: Callable[[dict[str, Any]], bool]) -> bool:
    data = _leer(path)
    cambio = fn(data)
    if cambio:
        _guardar(path, data)
    return cambio


def registrar_claude_desktop(py: str, server: str, env: Optional[dict[str, str]] = None) -> str:
    entrada = {"command": py, "args": [server]}

    def f(d: dict[str, Any]) -> bool:
        s = d.setdefault("mcpServers", {})
        if s.get(NOMBRE) == entrada:
            return False
        s[NOMBRE] = entrada
        return True
    return "registrado" if _editar(ruta_claude_desktop(env), f) else "ya estaba"


def quitar_claude_desktop(env: Optional[dict[str, str]] = None) -> str:
    def f(d: dict[str, Any]) -> bool:
        return d.get("mcpServers", {}).pop(NOMBRE, None) is not None
    p = ruta_claude_desktop(env)
    return "quitado" if os.path.exists(p) and _editar(p, f) else "no estaba"


def registrar_opencode(py: str, server: str, env: Optional[dict[str, str]] = None) -> str:
    def f(d: dict[str, Any]) -> bool:
        d.setdefault("$schema", "https://opencode.ai/config.json")
        mcp = d.setdefault("mcp", {})
        v2 = isinstance(mcp.get("servers"), dict)       # formato nuevo: mcp.servers.<n>
        destino = mcp["servers"] if v2 else mcp
        entrada: dict[str, Any] = {"type": "local", "command": [py, server]}
        if not v2:
            entrada["enabled"] = True
        if destino.get(NOMBRE) == entrada:
            return False
        destino[NOMBRE] = entrada
        return True
    return "registrado" if _editar(ruta_opencode(env), f) else "ya estaba"


def quitar_opencode(env: Optional[dict[str, str]] = None) -> str:
    def f(d: dict[str, Any]) -> bool:
        mcp = d.get("mcp", {})
        hecho = mcp.pop(NOMBRE, None) is not None
        if isinstance(mcp.get("servers"), dict):
            hecho = mcp["servers"].pop(NOMBRE, None) is not None or hecho
        return hecho
    p = ruta_opencode(env)
    return "quitado" if os.path.exists(p) and _editar(p, f) else "no estaba"


def comando_claude_code(py: str, server: str) -> list[str]:
    return ["claude", "mcp", "add", "--scope", "user", NOMBRE, "--", py, server]


def registrar_claude_code(py: str, server: str) -> str:
    import subprocess
    exe = shutil.which("claude")
    if not exe:
        return "no encontrado: corré  " + " ".join(comando_claude_code(py, server))
    subprocess.run([exe, "mcp", "remove", "--scope", "user", NOMBRE],
                   capture_output=True, text=True)
    r = subprocess.run([exe] + comando_claude_code(py, server)[1:],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return "falló: " + (r.stderr or r.stdout).strip()[:200]
    return "registrado"


def quitar_claude_code() -> str:
    import subprocess
    exe = shutil.which("claude")
    if not exe:
        return "no encontrado"
    r = subprocess.run([exe, "mcp", "remove", "--scope", "user", NOMBRE],
                       capture_output=True, text=True)
    return "quitado" if r.returncode == 0 else "no estaba"


def registrar(clientes: list[str], py: str, server: str,
              env: Optional[dict[str, str]] = None) -> dict[str, str]:
    res: dict[str, str] = {}
    for c in clientes:
        try:
            if c == "claude-desktop":
                res[c] = registrar_claude_desktop(py, server, env)
            elif c == "opencode":
                res[c] = registrar_opencode(py, server, env)
            elif c == "claude-code":
                res[c] = registrar_claude_code(py, server)
            else:
                res[c] = "cliente desconocido"
        except Exception as ex:                      # noqa: BLE001
            res[c] = f"falló: {ex}"
    return res


def quitar(clientes: list[str], env: Optional[dict[str, str]] = None) -> dict[str, str]:
    res: dict[str, str] = {}
    for c in clientes:
        try:
            res[c] = {"claude-desktop": lambda: quitar_claude_desktop(env),
                      "opencode": lambda: quitar_opencode(env),
                      "claude-code": quitar_claude_code}[c]()
        except Exception as ex:                      # noqa: BLE001
            res[c] = f"falló: {ex}"
    return res


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--python", help="python.exe del venv del servidor")
    ap.add_argument("--server", help="ruta a mcp_server/server.py")
    ap.add_argument("--clientes", default="auto",
                    help="auto (los detectados) o lista separada por comas: " + ", ".join(CLIENTES))
    ap.add_argument("--quitar", action="store_true", help="sacar la entrada 'autocad'")
    a = ap.parse_args(argv)
    clientes = detectar() if a.clientes == "auto" else [c.strip() for c in a.clientes.split(",") if c.strip()]
    if a.quitar:
        res = quitar(clientes or list(CLIENTES))
    else:
        if not a.python or not a.server:
            ap.error("--python y --server son obligatorios al registrar")
        if not clientes:
            print("No se detectó ningún cliente de IA (Claude Desktop, Claude Code, OpenCode). "
                  "Se puede usar el panel web igual.")
            return 0
        res = registrar(clientes, os.path.abspath(a.python), os.path.abspath(a.server))
    for c, estado in res.items():
        print(f"  {c}: {estado}")
    return 0 if not any(v.startswith("falló") for v in res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
