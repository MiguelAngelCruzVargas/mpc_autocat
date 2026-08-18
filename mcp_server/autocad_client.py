"""Cliente TCP para hablar con el plugin de AutoCAD.

Protocolo: una línea de texto = un request JSON, una línea = un response JSON.
Ver plugin/AutoCadMcpPlugin/CommandDispatcher.cs para el lado servidor.
"""
from __future__ import annotations

import json
import os
import socket
import uuid
from typing import Any, Optional

HOST = os.environ.get("ACAD_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("ACAD_MCP_PORT", "8765"))
# Tiene que ser MAYOR que el timeout de ejecucion del plugin
# (ACAD_MCP_EXEC_TIMEOUT, 60s por defecto): si el cliente abandona
# primero, el plugin termina escribiendo sobre un socket ya cerrado.
TIMEOUT = float(os.environ.get("ACAD_MCP_TIMEOUT", "75"))


class AutoCadError(RuntimeError):
    """Error devuelto por el plugin de AutoCAD (o de conexión)."""


def call(cmd: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Envía un comando al plugin y devuelve su 'result'.

    Abre una conexión nueva por llamada: más simple que mantener una conexión
    persistente, y evita tener que manejar reconexión cuando AutoCAD se
    cierra/abre entre una llamada y otra.
    """
    request = {"id": str(uuid.uuid4()), "cmd": cmd, "params": params or {}}
    payload = (json.dumps(request) + "\n").encode("utf-8")

    try:
        with socket.create_connection((HOST, PORT), timeout=TIMEOUT) as sock:
            sock.sendall(payload)
            sock.settimeout(TIMEOUT)
            buffer = b""
            while not buffer.endswith(b"\n"):
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
    except (ConnectionRefusedError, socket.timeout, OSError) as exc:
        raise AutoCadError(
            f"No se pudo conectar al plugin de AutoCAD en {HOST}:{PORT}. "
            "¿Está AutoCAD abierto con el plugin cargado (NETLOAD)? "
            f"Detalle: {exc}"
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
    return response.get("result", {})
