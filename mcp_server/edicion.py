"""Edición con el motor nativo de AutoCAD: trim, extend, fillet, join, overkill.

Cada operación tiene su comando FIJO en el plugin (NativeOpsCommand.cs) y
acá solo se validan los argumentos y se espera el resultado. No hay forma de
pedir «otro comando»: no existe un parámetro para eso.

Por qué existen si ya hay offset/mirror/etc.: recortar contra bordes, extender,
empalmar con radio y unir tramos son problemas de intersección con muchos
casos (arcos, bulges, bordes implícitos). AutoCAD ya los resuelve; reescribirlos
es la forma de dibujar un plano con una esquina mal cerrada.

El plugin ejecuta la operación dentro de un comando registrado (Editor.Command
no anda desde el evento Idle), así que devuelve un jobId y acá se consulta
native_status hasta que termina.
"""
from __future__ import annotations

import re
import time
from typing import Any, Optional

import autocad_client as acad

_HANDLE = re.compile(r"^[0-9A-Fa-f]{1,16}$")
_ESPERA_S = 30.0
_PASO_S = 0.4


class EdicionError(ValueError):
    """Argumento inválido: se informa antes de tocar AutoCAD."""


def _handle(h: Any, cual: str) -> str:
    if not isinstance(h, str) or not _HANDLE.match(h.strip()):
        raise EdicionError(f"'{cual}' tiene que ser un handle hexadecimal (el que devuelven los create_*), no {h!r}.")
    return h.strip().upper()


def _handles(hs: Any, cual: str, minimo: int) -> list[str]:
    if not isinstance(hs, (list, tuple)) or len(hs) < minimo:
        raise EdicionError(f"'{cual}' necesita una lista de al menos {minimo} handle(s).")
    visto: list[str] = []
    for h in hs:
        h = _handle(h, cual)
        if h not in visto:
            visto.append(h)
    if len(visto) < minimo:
        raise EdicionError(f"'{cual}' repite handles: quedan menos de {minimo} distintos.")
    return visto


def _punto(p: Any, cual: str) -> list[float]:
    if not isinstance(p, (list, tuple)) or len(p) not in (2, 3):
        raise EdicionError(f"'{cual}' tiene que ser [x, y] o [x, y, z].")
    try:
        v = [float(x) for x in p]
    except (TypeError, ValueError) as exc:
        raise EdicionError(f"'{cual}' tiene coordenadas que no son números: {p!r}.") from exc
    if any(x != x or abs(x) == float("inf") for x in v):
        raise EdicionError(f"'{cual}' tiene coordenadas inválidas (NaN o infinito).")
    return v


def _ejecutar(params: dict[str, Any], esperar_s: float) -> dict[str, Any]:
    """Manda la operación y espera su resultado (hasta esperar_s)."""
    r = acad.call("native_op", params)
    job = r.get("jobId")
    if not job:
        return r
    limite = time.monotonic() + max(esperar_s, 0.0)
    estado: dict[str, Any] = {"state": "queued", "jobId": job}
    while time.monotonic() < limite:
        estado = acad.call("native_status", {"jobId": job})
        if estado.get("state") in ("done", "error"):
            break
        time.sleep(_PASO_S)
    if estado.get("state") not in ("done", "error"):
        estado = dict(estado)
        estado["note"] = (f"Sigue en curso pasados {esperar_s:g} s: pedí el resultado con "
                          f"native_status(job_id='{job}'). NO repitas la operación.")
    elif estado.get("state") == "error":
        estado = dict(estado)
        estado["ok"] = False
    else:
        estado = dict(estado)
        estado["ok"] = True
    return estado


def trim(edges: list[str], target: str, point: list[float],
         extend_edges: bool = False, wait_s: float = _ESPERA_S) -> dict[str, Any]:
    return _ejecutar({"op": "trim", "edges": _handles(edges, "edges", 1),
                      "target": _handle(target, "target"), "point": _punto(point, "point"),
                      "extend_edges": bool(extend_edges)}, wait_s)


def extend(boundaries: list[str], target: str, point: list[float],
           extend_edges: bool = False, wait_s: float = _ESPERA_S) -> dict[str, Any]:
    return _ejecutar({"op": "extend", "edges": _handles(boundaries, "boundaries", 1),
                      "target": _handle(target, "target"), "point": _punto(point, "point"),
                      "extend_edges": bool(extend_edges)}, wait_s)


def fillet(first: str, second: str, radius: float, point1: list[float],
           point2: list[float], wait_s: float = _ESPERA_S) -> dict[str, Any]:
    try:
        r = float(radius)
    except (TypeError, ValueError) as exc:
        raise EdicionError(f"'radius' tiene que ser un número, no {radius!r}.") from exc
    if r != r or r < 0 or abs(r) == float("inf"):
        raise EdicionError("'radius' tiene que ser un número >= 0 (0 = esquina viva).")
    a, b = _handle(first, "first"), _handle(second, "second")
    if a == b:
        raise EdicionError("'first' y 'second' son la misma entidad.")
    return _ejecutar({"op": "fillet", "first": a, "second": b, "radius": r,
                      "point1": _punto(point1, "point1"), "point2": _punto(point2, "point2")}, wait_s)


def join(handles: list[str], wait_s: float = _ESPERA_S) -> dict[str, Any]:
    return _ejecutar({"op": "join", "handles": _handles(handles, "handles", 2)}, wait_s)


def overkill(handles: Optional[list[str]] = None, all: bool = False,
             wait_s: float = _ESPERA_S) -> dict[str, Any]:
    if all and handles:
        raise EdicionError("Pasá 'handles' o all=True, no las dos.")
    if all:
        return _ejecutar({"op": "overkill", "all": True}, wait_s)
    return _ejecutar({"op": "overkill", "handles": _handles(handles, "handles", 2)}, wait_s)
