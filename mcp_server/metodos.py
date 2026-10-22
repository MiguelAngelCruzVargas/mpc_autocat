"""Métodos de los objetos del dibujo, por reflexión (plugin 1.12.0+).

La otra mitad de la API (las propiedades están en propiedades.py): una curva
sabe calcular su desfase (GetOffsetCurves), partirse (GetSplitCurves), decir su
punto más cercano a otro (GetClosestPointTo), cortarse con otra entidad
(IntersectWith), dar el punto de un parámetro (GetPointAtParameter), transformarse
(TransformBy)... Son cientos de operaciones que AutoCAD ya resuelve.

Qué se admite está acotado del lado del plugin (MethodsCommands.cs): solo
métodos de instancia de la API, con parámetros simples o un objeto del dibujo
por su handle, sin rutas, sin ciclo de vida, sin guardar/exportar/cargar. Acá se
validan los argumentos antes de tocar AutoCAD.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import autocad_client as acad

_HANDLE = re.compile(r"^[0-9A-Fa-f]{1,16}$")
_NOMBRE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_ARGUMENTOS = 12


class MetodosError(ValueError):
    """Argumento inválido: se informa antes de tocar AutoCAD."""


def _handle(h: Any, cual: str = "handle") -> str:
    if not isinstance(h, str) or not _HANDLE.match(h.strip()):
        raise MetodosError(f"'{cual}' tiene que ser un handle hexadecimal, no {h!r}.")
    return h.strip().upper()


def list_methods(entity_type: Optional[str] = None, handle: Optional[str] = None,
                 filter: Optional[str] = None) -> dict[str, Any]:
    if bool(entity_type) == bool(handle):
        raise MetodosError("Pasá 'entity_type' (p.ej. 'Polyline') o 'handle', uno de los dos.")
    pars: dict[str, Any] = {}
    if handle:
        pars["handle"] = _handle(handle)
    else:
        if not _NOMBRE.match(entity_type or ""):
            raise MetodosError(f"'{entity_type}' no es un nombre de clase.")
        pars["type"] = entity_type
    if filter:
        if not isinstance(filter, str) or len(filter) > 60:
            raise MetodosError("'filter' tiene que ser un texto corto.")
        pars["filter"] = filter
    return acad.call("list_methods", pars)


def call_method(handle: str, method: str, args: Optional[list[Any]] = None,
                add_results_to_space: bool = False,
                mode: Optional[str] = None) -> dict[str, Any]:
    if not isinstance(method, str) or not _NOMBRE.match(method):
        raise MetodosError(f"'{method}' no es un nombre de método.")
    args = [] if args is None else args
    if not isinstance(args, (list, tuple)):
        raise MetodosError("'args' tiene que ser una lista (puede ir vacía).")
    if len(args) > MAX_ARGUMENTOS:
        raise MetodosError(f"Máximo {MAX_ARGUMENTOS} argumentos.")
    if mode not in (None, "read", "write"):
        raise MetodosError("'mode' es 'read' o 'write' (o se omite y se infiere por el nombre).")
    pars: dict[str, Any] = {"handle": _handle(handle), "method": method, "args": list(args),
                            "add_results_to_space": bool(add_results_to_space)}
    if mode:
        pars["mode"] = mode
    return acad.call("call_method", pars)
