"""Puentes: usar desde el chat un agente que ya tiene tu sesión (Claude Code), en vez de una clave de API.

Los proveedores de `providers.py` son un modelo al que ESTE programa le habla (con clave) y cuyo bucle de tools corre
en `loop.py`. Un puente es lo contrario: se le entrega el pedido a un agente completo que ya existe en el equipo
—hoy Claude Code (`claude -p`)— y ese agente decide qué herramientas usar. El chat solo muestra lo que pasa. La
ventaja es usar la suscripción de la persona; el costo es que el bucle, los permisos y el modelo los manda ese
agente, no este programa.

Cómo se le da AutoCAD a Claude Code: se le pasa un `--mcp-config` temporal que lanza el mismo `mcp_server/server.py`
que usa todo lo demás, y se le quitan las herramientas propias (`--tools ""`: ni Bash ni Edit) y todo lo que no sea
de AutoCAD (`--permission-mode dontAsk`: lo que no esté permitido se niega solo). `run_code` queda negado.

Lo que se sabe y lo que no (leer antes de confiar):
  - El formato de los eventos (`system/init`, `assistant`, `result`) está confirmado con la salida real de Claude Code
    2.1.310. Los eventos `user` con `tool_result` se escribieron según el formato documentado del SDK, SIN verlos.
  - En la máquina donde se escribió esto Claude Code contestó «Your organization has disabled Claude subscription
    access for Claude Code»: ningún modelo respondió de verdad por este puente. Ese mensaje, como cualquier error del
    CLI, le llega a la persona en el chat tal cual.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any, Callable, Optional

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVIDOR_MCP = os.path.join(_RAIZ, "mcp_server", "server.py")

PREFIJO_TOOLS = "mcp__autocad__"
NO_PERMITIDAS = ["mcp__autocad__run_code"]

PUENTES: dict[str, dict[str, Any]] = {
    "claude-code": {
        "nombre": "Claude Code (tu sesión)",
        "ejecutable": "claude",
        "variable": "AUTOCAD_IA_CLAUDE_BIN",     # para apuntar a otro binario (y para las pruebas)
        "modelos": ["sonnet", "opus", "haiku"],  # alias que entiende `--model`
        "ayuda": "Instala Claude Code e inicia sesión con `claude` en una terminal.",
    },
}

Emitir = Callable[[str, dict], None]


def es_puente(proveedor: str) -> bool:
    return proveedor in PUENTES


def buscar_ejecutable(puente: str) -> Optional[str]:
    """Ruta del CLI del puente, o None si no está instalado."""
    cfg = PUENTES[puente]
    explicito = os.environ.get(cfg["variable"])
    if explicito:
        return explicito if os.path.exists(explicito) else None
    return shutil.which(cfg["ejecutable"])


def estado(puente: str) -> dict[str, Any]:
    """Lo que la interfaz muestra del puente: si se puede usar y, si no, qué hacer."""
    ruta = buscar_ejecutable(puente)
    cfg = PUENTES[puente]
    if ruta:
        return {"disponible": True, "ruta": ruta, "detalle": f"{cfg['nombre']}: listo ({os.path.basename(ruta)})"}
    return {"disponible": False, "ruta": None, "detalle": f"No encuentro `{cfg['ejecutable']}`. {cfg['ayuda']}"}


# ---------------------------------------------------------------------------------------------- armado del comando

def _python_del_servidor() -> str:
    """El intérprete para el servidor MCP: `python.exe` (stdio) aunque este proceso corra con pythonw."""
    exe = sys.executable
    base = os.path.basename(exe).lower()
    if base == "pythonw.exe":
        candidato = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(candidato):
            return candidato
    return exe


def escribir_mcp_config(carpeta: str) -> str:
    """El JSON que le dice a Claude Code cómo lanzar el servidor MCP de AutoCAD."""
    ruta = os.path.join(carpeta, "autocad_mcp.json")
    config = {"mcpServers": {"autocad": {"command": _python_del_servidor(), "args": [SERVIDOR_MCP]}}}
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(config, fh)
    return ruta


def armar_comando(ejecutable: str, mcp_config: str, modelo: str = "", sesion: str = "",
                  archivo_sistema: str = "") -> list[str]:
    """Los argumentos de `claude`. El pedido va por stdin y las reglas de dibujo (decenas de miles de caracteres)
    por archivo: en Windows la línea de comandos tiene tope, y un `claude.cmd` de npm pasa por cmd.exe, que se
    traga los `&` y los saltos de línea."""
    cmd = [ejecutable, "-p", "--output-format", "stream-json", "--verbose",
           "--mcp-config", mcp_config, "--strict-mcp-config",
           "--tools", "",
           "--permission-mode", "dontAsk",
           "--allowedTools", "mcp__autocad",
           "--disallowedTools", *NO_PERMITIDAS,
           "--setting-sources", ""]
    if modelo:
        cmd += ["--model", modelo]
    if sesion:
        cmd += ["--resume", sesion]
    if archivo_sistema:
        cmd += ["--append-system-prompt-file", archivo_sistema]
    return cmd


def entorno_limpio(base: Optional[dict[str, str]] = None) -> dict[str, str]:
    """El entorno del CLI sin las variables de OTRA sesión de Claude Code.

    Si este servidor lo arrancó una sesión de Claude Code (o su app), el proceso hijo hereda su autenticación y su
    modo; el CLI debe usar la sesión de la PERSONA. Se conserva ANTHROPIC_API_KEY: es una elección de la persona."""
    env = dict(os.environ if base is None else base)
    for k in list(env):
        if k.startswith("CLAUDE") or (k.startswith("ANTHROPIC_") and k != "ANTHROPIC_API_KEY"):
            del env[k]
    return env


# ---------------------------------------------------------------------------------------------- eventos

class Traductor:
    """De los eventos stream-json de Claude Code a los eventos que la interfaz ya sabe mostrar
    (`texto`, `tool`, `resultado`, `aviso`, `uso`, `inicio`)."""

    def __init__(self) -> None:
        self.sesion = ""
        self.herramientas: dict[str, str] = {}      # id de tool_use -> nombre corto
        self.mostrados: set[str] = set()
        self.turnos = 0
        self.hubo_error = False

    @staticmethod
    def _corto(nombre: str) -> str:
        return nombre[len(PREFIJO_TOOLS):] if nombre.startswith(PREFIJO_TOOLS) else nombre

    @staticmethod
    def _texto_resultado(contenido: Any) -> str:
        if isinstance(contenido, str):
            return contenido
        if isinstance(contenido, list):
            return "\n".join(str(b.get("text", "")) for b in contenido if isinstance(b, dict))
        return str(contenido)

    def traducir(self, ev: dict[str, Any]) -> list[tuple[str, dict]]:
        tipo = ev.get("type")
        salida: list[tuple[str, dict]] = []
        if tipo == "system" and ev.get("subtype") == "init":
            self.sesion = ev.get("session_id") or self.sesion
            mcp = {m.get("name"): m.get("status") for m in ev.get("mcp_servers") or []}
            n = sum(1 for t in ev.get("tools") or [] if str(t).startswith(PREFIJO_TOOLS))
            salida.append(("inicio", {"tools": n, "modelo": "claude-code · " + str(ev.get("model", ""))}))
            if mcp.get("autocad") not in (None, "connected"):
                salida.append(("aviso", {"texto": "Claude Code no pudo conectar con el servidor MCP de AutoCAD "
                                                  f"({mcp.get('autocad')})."}))
        elif tipo == "assistant":
            self.sesion = ev.get("session_id") or self.sesion
            self.turnos += 1
            msg = ev.get("message") or {}
            es_error = bool(ev.get("is_api_error_message") or ev.get("error"))
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text"):
                    self.mostrados.add(b["text"])
                    if es_error:
                        self.hubo_error = True
                        salida.append(("aviso", {"texto": b["text"]}))
                    else:
                        salida.append(("texto", {"texto": b["text"]}))
                elif b.get("type") == "tool_use":
                    nombre = self._corto(str(b.get("name", "")))
                    self.herramientas[str(b.get("id", ""))] = nombre
                    salida.append(("tool", {"nombre": nombre, "args": b.get("input") or {}}))
        elif tipo == "user":
            msg = ev.get("message") or {}
            contenido = msg.get("content")
            for b in contenido if isinstance(contenido, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    nombre = self.herramientas.get(str(b.get("tool_use_id", "")), "?")
                    salida.append(("resultado", {"nombre": nombre, "texto": self._texto_resultado(b.get("content")),
                                                 "error": bool(b.get("is_error"))}))
        elif tipo == "result":
            self.sesion = ev.get("session_id") or self.sesion
            u = ev.get("usage") or {}
            entrada = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            salida_t = int(u.get("output_tokens") or 0)
            salida.append(("uso", {"entrada": entrada, "salida": salida_t, "total": entrada + salida_t,
                                   "vueltas": int(ev.get("num_turns") or self.turnos)}))
            texto = str(ev.get("result") or "")
            if ev.get("is_error") and texto not in self.mostrados:
                self.hubo_error = True
                salida.append(("aviso", {"texto": texto or "Claude Code terminó con un error."}))
        return salida


# ---------------------------------------------------------------------------------------------- ejecución

def _matar(proc: subprocess.Popen) -> None:
    """Termina el CLI y lo que lanzó (el servidor MCP): en Windows hace falta matar el árbol."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=15)
        else:
            proc.kill()
    except (OSError, subprocess.SubprocessError):
        pass


def correr(puente: str, pedido: str, emitir: Emitir, cancelado: Callable[[], bool], sesion: str = "",
           modelo: str = "", sistema: str = "", tiempo_max: float = 1800.0) -> dict[str, Any]:
    """Le entrega `pedido` al agente y emite sus eventos. Devuelve {"sesion": id para seguir, "error": bool}."""
    info = estado(puente)
    if not info["disponible"]:
        emitir("aviso", {"texto": info["detalle"]})
        return {"sesion": sesion, "error": True}

    carpeta = tempfile.mkdtemp(prefix="autocad_puente_")
    tr = Traductor()
    tr.sesion = sesion
    proc: Optional[subprocess.Popen] = None
    try:
        archivo_sistema = ""
        if sistema:
            archivo_sistema = os.path.join(carpeta, "reglas.md")
            with open(archivo_sistema, "w", encoding="utf-8") as fh:
                fh.write(sistema)
        cmd = armar_comando(info["ruta"], escribir_mcp_config(carpeta), modelo, sesion, archivo_sistema)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=entorno_limpio(), cwd=carpeta, creationflags=flags)
        except OSError as exc:
            emitir("aviso", {"texto": f"No pude lanzar {info['ruta']}: {exc}"})
            return {"sesion": sesion, "error": True}

        try:
            proc.stdin.write(pedido.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass

        lineas: "queue.Queue[Optional[bytes]]" = queue.Queue()
        errores: list[bytes] = []
        threading.Thread(target=lambda: ([lineas.put(l) for l in proc.stdout], lineas.put(None)), daemon=True).start()
        threading.Thread(target=lambda: errores.extend(proc.stderr), daemon=True).start()

        import time
        limite = time.monotonic() + tiempo_max
        while True:
            try:
                crudo = lineas.get(timeout=0.3)
            except queue.Empty:
                if cancelado():
                    _matar(proc)
                    emitir("aviso", {"texto": "Cancelado. Lo que ya se dibujó queda en el DWG: revísalo antes de seguir."})
                    return {"sesion": tr.sesion, "error": False}
                if time.monotonic() > limite:
                    _matar(proc)
                    emitir("aviso", {"texto": f"Claude Code no terminó en {int(tiempo_max // 60)} minutos; se cortó."})
                    return {"sesion": tr.sesion, "error": True}
                continue
            if crudo is None:
                break
            try:
                ev = json.loads(crudo.decode("utf-8", "replace"))
            except ValueError:
                continue                      # una línea que no es JSON (avisos del CLI): no es un evento
            if not isinstance(ev, dict):
                continue
            for tipo, cuerpo in tr.traducir(ev):
                emitir(tipo, cuerpo)
            if cancelado():
                _matar(proc)
                emitir("aviso", {"texto": "Cancelado. Lo que ya se dibujó queda en el DWG: revísalo antes de seguir."})
                return {"sesion": tr.sesion, "error": False}

        codigo = proc.wait(timeout=30)
        if codigo != 0 and not tr.hubo_error:
            cola = b"".join(errores).decode("utf-8", "replace").strip()[-500:]
            emitir("aviso", {"texto": f"Claude Code terminó con código {codigo}." + (f" {cola}" if cola else "")})
            tr.hubo_error = True
        return {"sesion": tr.sesion, "error": tr.hubo_error}
    finally:
        if proc is not None and proc.poll() is None:
            _matar(proc)
        shutil.rmtree(carpeta, ignore_errors=True)
