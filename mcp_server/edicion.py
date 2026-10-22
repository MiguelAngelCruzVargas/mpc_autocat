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
import session

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
    if estado.get("state") in ("done", "error"):
        # Para que undo sepa cuántos pasos de AutoCAD ocupó (ver session.py).
        session.note_undo_weight(2 if estado.get("changed") else 1,
                                 estado if estado.get("changed") else None)
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


# ---------------------------------------------------------------- deshacer

_ESPERA_PASO_S = 3.0      # AutoCAD ejecuta el UNDO al procesar su cola, no al responder
_MAX_PASOS_NATIVA = 3   # esperado 1-2; más podría deshacer operaciones AJENAS


def _existe(handle: str) -> bool:
    try:
        acad.call("get_entity", {"handle": handle})
        return True
    except acad.AutoCadError:
        return False


def _caja(handle: str) -> Optional[list[float]]:
    try:
        e = acad.call("get_entity", {"handle": handle})
    except acad.AutoCadError:
        return None
    b = e.get("bbox")
    return [float(v) for v in b[:4]] if isinstance(b, (list, tuple)) and len(b) >= 4 else None


def _revertida(op: dict[str, Any]) -> bool:
    """¿Volvió todo lo que la operación cambió? Borradas existen otra vez,
    creadas ya no, y las modificadas con su caja de antes."""
    for h in (op.get("deleted") or [])[:50]:
        if not _existe(h):
            return False
    for c in (op.get("created") or [])[:50]:
        if _existe(c["handle"]):
            return False
    for m in (op.get("modified") or [])[:50]:
        antes, ahora = m.get("before"), _caja(m["handle"])
        if antes is None or ahora is None:
            return False
        if any(abs(float(a) - b) > 1e-6 for a, b in zip(antes, ahora)):
            return False
    return True


def deshacer(operaciones: int) -> dict[str, Any]:
    """Deshace las últimas `operaciones` de este MCP. Una tool de dibujo se
    revierte con UN paso de UNDO; una operación nativa se deshace de a un paso
    comprobando después de cada uno si ya volvió lo que cambió (ver session.py)."""
    hechas: list[dict[str, Any]] = []
    # Desde el plugin 1.10.1 las lecturas no dejan pasos vacíos en UNDO y la
    # verificación paso a paso converge. En uno anterior cada lectura de la
    # verificación agregaría pasos: se pide el conteo fijo (2) y se avisa.
    try:
        v = str(acad.call("ping", {}).get("pluginVersion", "0"))
        viejo = tuple(int(x) for x in v.split(".")[:3]) < (1, 10, 1)
    except (acad.AutoCadError, ValueError):
        viejo = False
    for pasos, nativa in session.pop_undo(operaciones):
        if nativa is not None and viejo:
            acad.call("undo", {"steps": 2})
            time.sleep(_ESPERA_PASO_S)
            hechas.append({"kind": "nativa", "op": nativa.get("op"), "autocadSteps": 2,
                           "reverted": None,
                           "warning": "Plugin anterior a 1.10.1: se pidieron 2 pasos sin poder verificarlo."})
            continue
        if nativa is None or not (nativa.get("modified") or nativa.get("deleted")):
            # Una tool de dibujo: un UNDO, sin verificar. Verificar con lecturas
            # dejaría un paso vacío por lectura en el historial y cada vuelta
            # deshacería también operaciones ajenas.
            r = acad.call("undo", {"steps": 1})
            hechas.append({"kind": "dibujo", "autocadSteps": 1, "result": r})
            time.sleep(1.0)
            continue
        usados, ok = 0, False
        while usados < _MAX_PASOS_NATIVA and not ok:
            acad.call("undo", {"steps": 1})
            usados += 1
            limite = time.monotonic() + _ESPERA_PASO_S
            while time.monotonic() < limite:
                time.sleep(0.5)
                if _revertida(nativa):
                    ok = True
                    break
        hechas.append({"kind": "nativa" if nativa.get("modified") or nativa.get("deleted") else "dibujo",
                       "op": nativa.get("op"), "autocadSteps": usados, "reverted": ok})
    todo_ok = all(h.get("reverted", True) is not False for h in hechas)
    out: dict[str, Any] = {"ok": todo_ok, "operations": operaciones, "done": hechas}
    if not todo_ok:
        out["warning"] = ("No se pudo confirmar que la operación nativa se haya revertido tras "
                          f"{_MAX_PASOS_NATIVA} pasos: revisá el dibujo (list_entities / query_entities).")
    return out
