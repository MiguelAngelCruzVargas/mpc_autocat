"""El canal entre AutoCAD y un agente que usa su propia sesión (Claude Code u otro): actividad en vivo y bandeja.

Con un proveedor de API, el chat del panel ES el agente: manda, ejecuta y muestra. Con una suscripción (Claude Code,
OpenCode...) el agente corre en su propio programa, con sus propios permisos y su propio modelo, y habla con AutoCAD
por este servidor MCP. Lo que el panel puede hacer entonces es dos cosas, y las dos pasan por archivos en
`%LOCALAPPDATA%\\AutoCadMcp` (varios procesos las comparten sin conocerse):

  actividad.jsonl  cada llamada a una tool: cuándo empezó, cuándo terminó, con qué argumentos y qué contestó.
                   El servidor MCP la escribe SOLO (instalar() envuelve la ejecución de toda tool) y el panel la lee
                   y la muestra en vivo. Es lo que se ve en AutoCAD mientras Claude trabaja.
  bandeja.jsonl    mensajes en los dos sentidos. La persona escribe en el panel; el agente los recibe de dos formas:
                   con la tool `panel_leer_mensajes`, y porque en el resultado de CUALQUIER tool que ejecute le llega un
                   aviso «hay N mensaje(s) en el panel» mientras haya sin leer. Y el agente le escribe a la persona
                   con `panel_decir`. Si el agente está quieto (sin ejecutar ninguna tool) nadie lo despierta desde
                   aquí: el mensaje espera a su próxima llamada.

Nada de esto toca AutoCAD ni abre una puerta nueva: son dos archivos de texto. Lo que se guarda de `run_code` es el
tamaño del código, no el código (igual que la bitácora del plugin).
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Optional

MAX_ARCHIVO = 1_000_000          # bytes: pasado esto se conservan solo las últimas líneas
LINEAS_QUE_QUEDAN = 300
MAX_LINEA = 3500
TOOLS_DEL_CANAL = ("panel_decir", "panel_leer_mensajes")
_lock = threading.Lock()


def carpeta() -> str:
    base = os.environ.get("AUTOCAD_IA_ESTADO") or os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AutoCadMcp")
    os.makedirs(base, exist_ok=True)
    return base


def _ruta(nombre: str) -> str:
    return os.path.join(carpeta(), nombre)


# ---------------------------------------------------------------------------------------------- archivos de líneas

def _agregar(nombre: str, obj: dict[str, Any]) -> None:
    linea = json.dumps(obj, ensure_ascii=False)
    if len(linea) > MAX_LINEA:                         # una línea enorme rompería la lectura de las demás
        obj = {**obj, **{k: (v[:300] + "…" if isinstance(v, str) and len(v) > 300 else v) for k, v in obj.items()}}
        linea = json.dumps(obj, ensure_ascii=False)[:MAX_LINEA]
    ruta = _ruta(nombre)
    with _lock:
        try:
            if os.path.getsize(ruta) > MAX_ARCHIVO:
                with open(ruta, encoding="utf-8", errors="replace") as fh:
                    cola = fh.readlines()[-LINEAS_QUE_QUEDAN:]
                with open(ruta, "w", encoding="utf-8") as fh:
                    fh.writelines(cola)
        except OSError:
            pass
        with open(ruta, "a", encoding="utf-8") as fh:
            fh.write(linea + "\n")


def _leer(nombre: str, desde: int = 0, limite: int = 500) -> tuple[list[dict[str, Any]], int]:
    """Las líneas completas posteriores al byte `desde`, y el byte desde donde seguir. Si el archivo se recortó
    (quedó más corto que `desde`) vuelve a empezar: el que lee no se queda mirando un final que ya no existe."""
    ruta = _ruta(nombre)
    try:
        tam = os.path.getsize(ruta)
    except OSError:
        return [], 0
    if desde > tam:
        desde = 0
    with open(ruta, "rb") as fh:
        fh.seek(desde)
        crudo = fh.read()
    fin = crudo.rfind(b"\n")
    if fin < 0:
        return [], desde
    eventos = []
    for linea in crudo[:fin + 1].splitlines():
        try:
            e = json.loads(linea.decode("utf-8", "replace"))
        except ValueError:
            continue
        if isinstance(e, dict):
            eventos.append(e)
    if len(eventos) > limite:                          # muchos de golpe: lo más reciente
        eventos = eventos[-limite:]
    return eventos, desde + fin + 1


# ---------------------------------------------------------------------------------------------- actividad

def _resumir_args(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool == "run_code":
        return {"código": f"({len(str((args or {}).get('code', '')))} caracteres de C#, no se guardan)"}
    salida: dict[str, Any] = {}
    for k, v in (args or {}).items():
        s = v if isinstance(v, (int, float, bool)) or v is None else json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
        salida[k] = s if not isinstance(s, str) or len(s) <= 120 else s[:117] + "…"
    texto = json.dumps(salida, ensure_ascii=False)
    return salida if len(texto) <= 600 else {"…": texto[:597] + "…"}


def _texto_de(resultado: Any) -> str:
    bloques = resultado[0] if isinstance(resultado, tuple) else resultado
    if isinstance(bloques, dict):
        return json.dumps(bloques, ensure_ascii=False)
    try:
        return "\n".join(getattr(b, "text", "") or "" for b in bloques)
    except TypeError:
        return str(resultado)


def registrar(evento: dict[str, Any]) -> None:
    try:
        _agregar("actividad.jsonl", {"ts": round(time.time(), 3), "pid": os.getpid(), **evento})
    except OSError:
        pass            # el registro es una comodidad: jamás tumba una tool


def leer_actividad(desde: int = 0) -> tuple[list[dict[str, Any]], int]:
    return _leer("actividad.jsonl", desde)


# ---------------------------------------------------------------------------------------------- bandeja

def enviar(de: str, texto: str, tipo: str = "info") -> dict[str, Any]:
    """`de`: 'usuario' (escribió en el panel) o 'claude' (el agente le habla a la persona)."""
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("El mensaje está vacío.")
    if de not in ("usuario", "claude"):
        raise ValueError("`de` es 'usuario' o 'claude'.")
    msg = {"id": uuid.uuid4().hex[:10], "ts": round(time.time(), 3), "de": de, "tipo": tipo, "texto": texto[:4000]}
    _agregar("bandeja.jsonl", msg)
    return msg


def leer_bandeja(desde: int = 0) -> tuple[list[dict[str, Any]], int]:
    return _leer("bandeja.jsonl", desde)


def _cursor() -> int:
    """Hasta dónde leyó el agente. Si la bandeja se recortó y quedó más corta, el cursor se acomoda al final: lo
    que quedó ya se entregó (no se reentregan mensajes viejos)."""
    try:
        with open(_ruta("bandeja_leida.txt"), encoding="utf-8") as fh:
            pos = int(fh.read().strip() or 0)
    except (OSError, ValueError):
        return 0
    try:
        tam = os.path.getsize(_ruta("bandeja.jsonl"))
    except OSError:
        return 0
    if pos > tam:
        pos = tam
        _guardar_cursor(pos)
    return pos


def _guardar_cursor(pos: int) -> None:
    with open(_ruta("bandeja_leida.txt"), "w", encoding="utf-8") as fh:
        fh.write(str(pos))


def mensajes_pendientes(marcar: bool = True) -> list[dict[str, Any]]:
    """Lo que la persona escribió en el panel y el agente todavía no leyó."""
    with _lock:
        msgs, pos = _leer("bandeja.jsonl", _cursor())
        if marcar:
            _guardar_cursor(pos)
    return [m for m in msgs if m.get("de") == "usuario"]


def hay_pendientes() -> int:
    """Cuántos mensajes de la persona esperan, SIN marcarlos: se mira en cada tool, tiene que ser barato."""
    ruta = _ruta("bandeja.jsonl")
    try:
        if os.path.getsize(ruta) <= _cursor():
            return 0
    except OSError:
        return 0
    return len([m for m in _leer("bandeja.jsonl", _cursor())[0] if m.get("de") == "usuario"])


# ---------------------------------------------------------------------------------------------- el envoltorio

def _aviso_pendientes() -> Optional[str]:
    n = hay_pendientes()
    if not n:
        return None
    return (f"📬 La persona dejó {n} mensaje(s) para ti en el panel de AutoCAD. Léelos con `panel_leer_mensajes` "
            "y contéstale con `panel_decir`.")


def _con_aviso(resultado: Any, aviso: str) -> Any:
    """Agrega el aviso como un bloque de texto más, sin tocar el resultado estructurado."""
    from mcp.types import TextContent
    extra = TextContent(type="text", text=aviso)
    if isinstance(resultado, tuple) and len(resultado) == 2 and isinstance(resultado[0], (list, tuple)):
        return (list(resultado[0]) + [extra], resultado[1])
    if isinstance(resultado, (list, tuple)):
        return list(resultado) + [extra]
    return resultado                                   # dict solo estructurado: no hay donde ponerlo sin alterarlo


def instalar(mcp: Any) -> None:
    """Envuelve la ejecución de TODA tool del servidor: registra su actividad y entrega el aviso de la bandeja."""
    if os.environ.get("AUTOCAD_IA_SIN_CANAL"):          # interruptor: apaga el registro y la bandeja sin tocar código
        return
    gestor = mcp._tool_manager
    if getattr(gestor, "_canal_panel", False):
        return
    original = gestor.call_tool

    async def con_canal(name, arguments, context=None, convert_result=False):
        ident = uuid.uuid4().hex[:8]
        t0 = time.monotonic()
        registrar({"t": "inicio", "id": ident, "tool": name, "args": _resumir_args(name, arguments)})
        try:
            resultado = await original(name, arguments, context=context, convert_result=convert_result)
        except Exception as exc:                       # noqa: BLE001
            registrar({"t": "fin", "id": ident, "tool": name, "ok": False, "ms": int((time.monotonic() - t0) * 1000),
                       "texto": str(exc)[:300]})
            raise
        texto = _texto_de(resultado)
        registrar({"t": "fin", "id": ident, "tool": name, "ok": True, "ms": int((time.monotonic() - t0) * 1000),
                   "texto": texto[:300]})
        if name not in TOOLS_DEL_CANAL and convert_result:
            try:
                aviso = _aviso_pendientes()
                if aviso:
                    resultado = _con_aviso(resultado, aviso)
            except Exception:                          # noqa: BLE001
                pass
        return resultado

    gestor.call_tool = con_canal
    gestor._canal_panel = True
