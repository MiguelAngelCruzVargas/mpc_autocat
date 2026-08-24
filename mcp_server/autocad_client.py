"""Cliente TCP para hablar con el plugin de AutoCAD.

Protocolo: una línea de texto = un request JSON, una línea = un response JSON.
Ver plugin/AutoCadMcpPlugin/CommandDispatcher.cs para el lado servidor.
"""
from __future__ import annotations

import json
import os
import socket
import time
import uuid
from typing import Any, Optional

import session

HOST = os.environ.get("ACAD_MCP_HOST", "127.0.0.1")
DEFAULT_PORT = 8765

# El plugin anota acá el puerto en el que quedó escuchando. Hace falta porque
# el 8765 se lo puede haber quedado otro programa (Docker, un dev server), y
# entonces el plugin arranca en el siguiente libre.
PORT_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AutoCadMcp", "port")


def _discover_port() -> int:
    """Puerto a usar: el explícito si lo hay, si no el que anotó el plugin."""
    explicit = os.environ.get("ACAD_MCP_PORT")
    if explicit:
        return int(explicit)
    try:
        with open(PORT_FILE, encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return DEFAULT_PORT


PORT = _discover_port()
# Tiene que ser MAYOR que el timeout de ejecucion del plugin
# (ACAD_MCP_EXEC_TIMEOUT, 60s por defecto): si el cliente abandona
# primero, el plugin termina escribiendo sobre un socket ya cerrado.
TIMEOUT = float(os.environ.get("ACAD_MCP_TIMEOUT", "75"))


class AutoCadError(RuntimeError):
    """Error devuelto por el plugin de AutoCAD (o de conexión)."""


class AutoCadConnectionError(AutoCadError):
    """No se pudo NI conectar: nada llegó a AutoCAD.

    La distinción importa para los reintentos: si la conexión no se
    estableció, repetir CUALQUIER comando es seguro — no hay riesgo de que
    la primera vez haya dibujado algo."""


# Fallas que se resuelven solas esperando un momento: AutoCAD terminando un
# comando en curso, el motor de plot soltando el estado del plot anterior,
# el listener levantándose tras un documento cerrado. Reintentarlas acá
# adentro le ahorra al agente el ciclo fallar → releer → reintentar, que es
# puro tiempo y tokens gastados en nada.
_TRANSITORIOS = ("no procesó el comando a tiempo",
                 "ya hay un plot en curso",
                 "einvalidinput",
                 "cerró la conexión sin responder")

_REINTENTOS = 3
_ESPERA_BASE_S = 1.5


def _es_transitorio(exc: AutoCadError) -> bool:
    mensaje = str(exc).lower()
    return any(marca in mensaje for marca in _TRANSITORIOS)


def call(cmd: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Envía un comando al plugin y devuelve su 'result'.

    Reintenta solo las fallas transitorias, y solo cuando repetir es seguro:
    siempre si la conexión ni se estableció (nada llegó a AutoCAD), y para
    comandos de lectura/plot si la falla fue del otro lado. Un comando que
    dibuja NUNCA se reintenta tras un timeout: pudo haber llegado, y
    repetirlo deja entidades duplicadas.
    """
    for intento in range(_REINTENTOS):
        try:
            return _do_call(cmd, params)
        except AutoCadConnectionError:
            if intento == _REINTENTOS - 1:
                raise
        except AutoCadError as exc:
            if (intento == _REINTENTOS - 1 or not session.retry_safe(cmd)
                    or not _es_transitorio(exc)):
                raise
        time.sleep(_ESPERA_BASE_S * (intento + 1))
    raise AutoCadError("inalcanzable")  # el for siempre retorna o relanza


def _do_call(cmd: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Una llamada al plugin, sin reintentos. Abre una conexión nueva por
    llamada: más simple que mantener una persistente, y evita manejar
    reconexión cuando AutoCAD se cierra/abre entre una llamada y otra."""
    request = {"id": str(uuid.uuid4()), "cmd": cmd, "params": params or {}}
    payload = (json.dumps(request) + "\n").encode("utf-8")

    # Se relee en cada llamada: si AutoCAD se reinició y quedó en otro puerto,
    # la siguiente llamada lo encuentra sin tener que reiniciar este proceso.
    port = _discover_port()

    try:
        sock = socket.create_connection((HOST, port), timeout=TIMEOUT)
    except (ConnectionRefusedError, socket.timeout, OSError) as exc:
        # Conexión jamás establecida: seguro de reintentar para todo comando.
        raise AutoCadConnectionError(
            f"No se pudo conectar al plugin de AutoCAD en {HOST}:{port}. "
            "¿Está AutoCAD abierto con el plugin cargado? "
            "Si AutoCAD está abierto, fijate en su línea de comandos si el "
            "plugin avisó de un error al iniciar el servidor: el puerto puede "
            "estar ocupado por otro programa. "
            f"Detalle: {exc}"
        ) from exc

    try:
        with sock:
            sock.sendall(payload)
            sock.settimeout(TIMEOUT)
            buffer = b""
            while not buffer.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
    except (socket.timeout, OSError) as exc:
        # Acá el request pudo haber llegado: NO es un error "de conexión"
        # (reintentable a ciegas), aunque la causa sea de red.
        raise AutoCadError(
            f"Se cortó la conexión con el plugin de AutoCAD ({exc}). El "
            "comando pudo haberse ejecutado igual: verificá antes de repetir "
            "uno que dibuje."
        ) from exc

    if not buffer:
        raise AutoCadError("El plugin de AutoCAD cerró la conexión sin responder.")

    try:
        response = json.loads(buffer.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AutoCadError(
            "Respuesta incompleta o invalida del plugin de AutoCAD "
            f"(se recibieron {len(buffer)} bytes). Detalle: {exc}"
        ) from exc

    if not response.get("ok"):
        raise AutoCadError(response.get("error", "Error desconocido en el plugin de AutoCAD."))
    # session lleva la cuenta de lo dibujado sin guardar y avisa cruzado el
    # umbral — el aviso viaja en el resultado del propio comando que dibujó.
    return session.after_call(cmd, request["params"], response.get("result", {}))
