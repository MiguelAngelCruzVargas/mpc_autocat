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
  codex           OpenAI Codex: CLI 'codex mcp add', o ~/.codex/config.toml
                  -> [mcp_servers.autocad]. Esa configuración la comparten la
                  terminal, la extensión del editor y Codex en la app de
                  ChatGPT: es la vía para quien tiene suscripción de ChatGPT.

ChatGPT (el chat normal) NO carga servidores MCP locales por stdio: con
suscripción de ChatGPT se usa Codex; sin suscripción, la IA incluida o una clave.
El asistente de Autodesk (AutoCAD 2027) tampoco: Autodesk no documenta cómo
agregarle servidores de terceros.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import Any, Callable, Optional

NOMBRE = "autocad"
CLIENTES = ("claude-desktop", "claude-code", "opencode", "codex")
# Bloque propio dentro del config.toml de Codex (cuando no está su CLI): se reemplaza entero, el resto no se toca.
_CODEX_INICIO = "# >>> Vigentra Architech (no editar este bloque a mano)"
_CODEX_FIN = "# <<< Vigentra Architech"


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


def ruta_codex(env: Optional[dict[str, str]] = None) -> str:
    e = _env(env)
    base = e.get("CODEX_HOME") or os.path.join(e.get("USERPROFILE") or e.get("HOME") or os.path.expanduser("~"), ".codex")
    return os.path.join(base, "config.toml")


def _comando(nombre: str, env: Optional[dict[str, str]]) -> Optional[str]:
    """El programa en el PATH. Con un `env` de prueba solo se busca en SU PATH: nunca se toca el claude/codex real."""
    if env is None:
        return shutil.which(nombre)
    return shutil.which(nombre, path=env.get("PATH", "")) if env.get("PATH") else None


def detectar(env: Optional[dict[str, str]] = None) -> list[str]:
    """Clientes que parecen estar instalados (por su carpeta de configuración
    o su comando en el PATH)."""
    out = []
    if os.path.isdir(os.path.dirname(ruta_claude_desktop(env))):
        out.append("claude-desktop")
    if _comando("claude", env):
        out.append("claude-code")
    if os.path.isdir(os.path.dirname(ruta_opencode(env))) or _comando("opencode", env):
        out.append("opencode")
    if os.path.isdir(os.path.dirname(ruta_codex(env))) or _comando("codex", env):
        out.append("codex")
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


def _toml_texto(valor: str) -> str:
    return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'


def bloque_codex(py: str, server: str) -> str:
    return (f"{_CODEX_INICIO}\n[mcp_servers.{NOMBRE}]\ncommand = {_toml_texto(py)}\n"
            f"args = [{_toml_texto(server)}]\n{_CODEX_FIN}\n")


def _sin_bloque_codex(texto: str) -> tuple[str, bool]:
    i, j = texto.find(_CODEX_INICIO), texto.find(_CODEX_FIN)
    if i < 0 or j < i:
        return texto, False
    j = texto.find("\n", j)
    return texto[:i] + (texto[j + 1:] if j >= 0 else ""), True


def registrar_codex(py: str, server: str, env: Optional[dict[str, str]] = None) -> str:
    """Con el CLI de Codex, como él lo quiere; sin él, un bloque propio en config.toml."""
    import subprocess
    exe = shutil.which("codex") if env is None else None
    if exe:
        subprocess.run([exe, "mcp", "remove", NOMBRE], capture_output=True, text=True)
        r = subprocess.run([exe, "mcp", "add", NOMBRE, "--", py, server], capture_output=True, text=True)
        return "registrado" if r.returncode == 0 else "falló: " + (r.stderr or r.stdout).strip()[:200]
    ruta = ruta_codex(env)
    texto = open(ruta, encoding="utf-8").read() if os.path.exists(ruta) else ""
    limpio, _ = _sin_bloque_codex(texto)
    if f"[mcp_servers.{NOMBRE}]" in limpio:
        return "ya hay otro servidor «autocad» en " + ruta + ": no se toca"
    nuevo = limpio.rstrip("\n") + ("\n\n" if limpio.strip() else "") + bloque_codex(py, server)
    if nuevo == texto:
        return "ya estaba"
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    if os.path.exists(ruta) and not os.path.exists(ruta + ".bak-autocad-ia"):
        shutil.copy2(ruta, ruta + ".bak-autocad-ia")
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(nuevo)
    return "registrado"


def quitar_codex(env: Optional[dict[str, str]] = None) -> str:
    import subprocess
    exe = shutil.which("codex") if env is None else None
    if exe:
        r = subprocess.run([exe, "mcp", "remove", NOMBRE], capture_output=True, text=True)
        return "quitado" if r.returncode == 0 else "no estaba"
    ruta = ruta_codex(env)
    if not os.path.exists(ruta):
        return "no estaba"
    limpio, habia = _sin_bloque_codex(open(ruta, encoding="utf-8").read())
    if not habia:
        return "no estaba"
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(limpio)
    return "quitado"


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
                # Con un env de prueba no se ejecuta el CLI real (registraría en la PC de quien corre la prueba).
                res[c] = registrar_claude_code(py, server) if env is None else "omitido (entorno de prueba)"
            elif c == "codex":
                res[c] = registrar_codex(py, server, env)
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
                      "codex": lambda: quitar_codex(env),
                      "claude-code": quitar_claude_code}[c]()
        except Exception as ex:                      # noqa: BLE001
            res[c] = f"falló: {ex}"
    return res


NOMBRES = {"claude-desktop": "Claude (app de escritorio)", "claude-code": "Claude Code",
           "codex": "Codex (ChatGPT)", "opencode": "OpenCode"}


def _amigable(py: Optional[str], server: Optional[str], env: Optional[dict[str, str]] = None) -> int:
    """Lo que ve el cliente al hacer doble clic en CONECTAR_MI_SUSCRIPCION.bat: qué se conectó y qué sigue."""
    if not py or not server or not os.path.isfile(server):
        print("No encuentro el servidor de Architech. Reinstala con INSTALAR.bat y vuelve a intentarlo.")
        return 1
    clientes = detectar(env)
    if not clientes:
        print("No encontré ningún programa de IA con suscripción en esta computadora.\n")
        print("Instala UNO de estos (con la cuenta de tu suscripción) y vuelve a hacer doble clic aquí:")
        print("  - Suscripción de Claude (Pro o Max):  la app de escritorio de Claude  -> https://claude.ai/download")
        print("  - Suscripción de ChatGPT (Plus o Pro): Codex                           -> https://developers.openai.com/codex")
        print("\nSi no tienes suscripción, no hace falta: usa la «IA incluida en tu plan» en el chat de AutoCAD.")
        return 0
    res = registrar(clientes, os.path.abspath(py), os.path.abspath(server), env)
    listos = [c for c, e in res.items() if e in ("registrado", "ya estaba")]
    for c, estado in res.items():
        marca = "LISTO" if c in listos else "NO SE PUDO"
        print(f"  [{marca}]  {NOMBRES.get(c, c)}" + ("" if c in listos else f"  ({estado})"))
    if not listos:
        print("\nNo se pudo conectar. Manda una captura de esta ventana a soporte de Vigentra.")
        return 1
    print("\nYa está. Ahora:")
    print("  1. Abre AutoCAD (con Architech instalado).")
    if "claude-desktop" in listos:
        print("  2. Cierra por completo la app de Claude (también del icono junto al reloj) y vuelve a abrirla.")
        print("     En el chat verás las herramientas de AutoCAD. Pídele, por ejemplo:")
    else:
        print("  2. Abre tu agente (Claude Code o Codex) y pídele, por ejemplo:")
    print("       «Revisa el plano abierto en AutoCAD y dime qué contiene»")
    print("       «Dibuja la planta de una casa de 8 x 20 con 2 recámaras»")
    print("  3. Para ver lo que hace desde AutoCAD: en el chat de AutoCAD elige «En vivo».")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--python", help="python.exe del venv del servidor")
    ap.add_argument("--server", help="ruta a mcp_server/server.py")
    ap.add_argument("--clientes", default="auto",
                    help="auto (los detectados) o lista separada por comas: " + ", ".join(CLIENTES))
    ap.add_argument("--quitar", action="store_true", help="sacar la entrada 'autocad'")
    ap.add_argument("--amigable", action="store_true",
                    help="mensajes para el cliente (lo usa CONECTAR_MI_SUSCRIPCION.bat)")
    a = ap.parse_args(argv)
    if a.amigable and not a.quitar:
        return _amigable(a.python, a.server)
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
