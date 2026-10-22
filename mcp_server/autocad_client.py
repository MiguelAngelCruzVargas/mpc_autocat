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

import ojos
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


# ------------------------------------------------------------------ lotes
#
# Cada comando cuesta ~0.5 s aunque no haga nada (la cola del plugin se vacía
# en Application.Idle). Un detalle constructivo son cientos de entidades: con
# un viaje por entidad, cada prueba en AutoCAD tardaba minutos y no se podía
# iterar mirando el dibujo. Dentro de `with lote():` los comandos que solo
# dibujan se encolan y viajan juntos (comando 'batch' del plugin, 1.8.7+):
# devuelven un handle provisorio ('$L12') que el plugin resuelve en el mismo
# lote y este módulo después (resolver()). Lo que necesita una respuesta real
# (medir texto, leer una entidad) vacía la cola antes de ir.

LOTEABLES = frozenset({
    "create_line", "create_polyline", "create_circle", "create_arc",
    "create_text", "create_mtext", "create_hatch", "create_dimension",
    "create_dimension_rotated", "create_leader", "delete_entity",
    "delete_entities", "set_layer",
})
_LOTE: list[Optional[list[dict[str, Any]]]] = [None]
_PROFUNDIDAD = [0]
_CONTADOR = [0]
_RESUELTOS: dict[str, str] = {}
LOTE_ERRORES: list[dict[str, Any]] = []
_TAMANO_VIAJE = 300

# Modo "ver dibujar": sin lotes, cada entidad viaja sola y AutoCAD la muestra
# en cuanto existe -- la planta se va armando en pantalla como si la dibujara
# una persona. Es más lento (~0.5 s por entidad) y es lo que se quiere para
# mirar el trabajo en vivo o grabar una demostración. MCP_VER_DIBUJAR=1 en el
# entorno, o ver_dibujar(True).
VER_DIBUJAR = [os.environ.get("MCP_VER_DIBUJAR", "") == "1"]


def ver_dibujar(activo: bool = True) -> None:
    VER_DIBUJAR[0] = bool(activo)


def batching() -> bool:
    return _LOTE[0] is not None


def resolver(obj: Any) -> Any:
    """Reemplaza los handles provisorios ('$L12') por los reales."""
    if isinstance(obj, str):
        return _RESUELTOS.get(obj, obj) if obj.startswith("$L") else obj
    if isinstance(obj, list):
        return [resolver(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(resolver(x) for x in obj)
    if isinstance(obj, dict):
        return {k: resolver(v) for k, v in obj.items()}
    return obj


def flush() -> list[dict[str, Any]]:
    """Manda lo encolado. Devuelve los errores (también en LOTE_ERRORES)."""
    cola = _LOTE[0]
    if not cola:
        return []
    _LOTE[0] = []
    errores: list[dict[str, Any]] = []
    for i in range(0, len(cola), _TAMANO_VIAJE):
        tramo = [dict(c, params=resolver(c["params"]),
                      **({"fallback": resolver(c["fallback"])} if c.get("fallback") else {}))
                 for c in cola[i:i + _TAMANO_VIAJE]]
        r = _do_call("batch", {"commands": tramo})
        for item, res in zip(tramo, r.get("results", [])):
            if res.get("ok") and isinstance(res.get("result"), dict)                     and res["result"].get("handle"):
                _RESUELTOS[item["id"]] = res["result"]["handle"]
            elif not res.get("ok"):
                errores.append({"id": item["id"], "cmd": item["cmd"],
                                "error": res.get("error")})
    LOTE_ERRORES.extend(errores)
    return errores


class lote:
    """with lote(): ... -- dibuja en pocos viajes. Anidable: solo el de
    afuera vacía la cola."""

    def __enter__(self):
        if _PROFUNDIDAD[0] == 0 and not VER_DIBUJAR[0]:
            _LOTE[0] = []
        _PROFUNDIDAD[0] += 1
        return self

    def __exit__(self, *exc):
        _PROFUNDIDAD[0] -= 1
        if _PROFUNDIDAD[0] == 0:
            try:
                if exc[0] is None:
                    flush()
            finally:
                _LOTE[0] = None
        return False


def call(cmd: str, params: Optional[dict[str, Any]] = None,
         fallback: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Envía un comando al plugin y devuelve su 'result'.

    Dentro de `with lote():` los comandos de dibujo se encolan (ver arriba);
    'fallback' son los params alternativos si el comando falla en el lote
    (el patrón de respaldo de un achurado). Fuera de un lote se ignora.

    Reintenta solo las fallas transitorias, y solo cuando repetir es seguro:
    siempre si la conexión ni se estableció (nada llegó a AutoCAD), y para
    comandos de lectura/plot si la falla fue del otro lado. Un comando que
    dibuja NUNCA se reintenta tras un timeout: pudo haber llegado, y
    repetirlo deja entidades duplicadas.
    """
    if cmd in ("create_text", "create_mtext") and params and params.get("lineweight"):
        # TODO texto con grosor 0: en una TrueType el grosor lo da la letra.
        # Con pluma (0.35 en un título) y la visualización de grosores
        # encendida, AutoCAD traza el CONTORNO de cada letra y, chica en
        # pantalla, sale hueca y deformada ("ESC. 1:20" se leía "CJO, 7:00").
        params = dict(params, lineweight=0)
    if _LOTE[0] is not None:
        if cmd in LOTEABLES:
            _CONTADOR[0] += 1
            pid = f"$L{_CONTADOR[0]}"
            item: dict[str, Any] = {"id": pid, "cmd": cmd, "params": params or {}}
            if fallback:
                item["fallback"] = fallback
            _LOTE[0].append(item)
            return {"handle": pid, "status": "queued", "area": 0.0, "length": 0.0,
                    "measurement": 0.0}
        flush()
    params = resolver(params) if params else params
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
    params = dict(params or {})
    if VER_DIBUJAR[0]:
        params["_live"] = True          # el plugin repinta tras cada comando
    request = {"id": str(uuid.uuid4()), "cmd": cmd, "params": params}
    payload = (json.dumps(request) + "\n").encode("utf-8")
    ficha = ojos.anotar_envio(cmd, params)

    # Se relee en cada llamada: si AutoCAD se reinició y quedó en otro puerto,
    # la siguiente llamada lo encuentra sin tener que reiniciar este proceso.
    port = _discover_port()

    try:
        sock = socket.create_connection((HOST, port), timeout=TIMEOUT)
    except (ConnectionRefusedError, socket.timeout, OSError) as exc:
        # Conexión jamás establecida: seguro de reintentar para todo comando.
        ojos.anotar_fin(ficha, "sin conexión", str(exc))
        raise AutoCadConnectionError(
            f"No se pudo conectar al plugin de AutoCAD en {HOST}:{port}. "
            "¿Está AutoCAD abierto con el plugin cargado? "
            "Si AutoCAD está abierto, fijate en su línea de comandos si el "
            "plugin avisó de un error al iniciar el servidor: el puerto puede "
            "estar ocupado por otro programa. "
            f"Detalle: {exc} " + ojos.resumen_para_error()
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
        ojos.anotar_fin(ficha, "cortado", str(exc))
        raise AutoCadError(
            f"Se cortó la conexión con el plugin de AutoCAD ({exc}). El "
            "comando pudo haberse ejecutado igual: verificá antes de repetir "
            "uno que dibuje. " + ojos.resumen_para_error()
        ) from exc

    if not buffer:
        ojos.anotar_fin(ficha, "sin respuesta")
        raise AutoCadError("El plugin de AutoCAD cerró la conexión sin responder. " + ojos.resumen_para_error())

    try:
        response = json.loads(buffer.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AutoCadError(
            "Respuesta incompleta o invalida del plugin de AutoCAD "
            f"(se recibieron {len(buffer)} bytes). Detalle: {exc}"
        ) from exc

    if not response.get("ok"):
        ojos.anotar_fin(ficha, "error", str(response.get("error", "")))
        raise AutoCadError(response.get("error", "Error desconocido en el plugin de AutoCAD."))
    ojos.anotar_fin(ficha, "ok")
    # session lleva la cuenta de lo dibujado sin guardar y avisa cruzado el
    # umbral — el aviso viaja en el resultado del propio comando que dibujó.
    return session.after_call(cmd, request["params"], response.get("result", {}))
