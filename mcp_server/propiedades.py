"""Propiedades de cualquier objeto del dibujo, por reflexión (plugin 1.11.0+).

Lo que hace posible controlar miles de propiedades sin escribir una tool por
cada una: el plugin descubre en tiempo de ejecución las propiedades públicas de
la clase real del objeto (Line, Polyline, DBText, Hatch, Solid3d, una capa, un
estilo...) en la versión de AutoCAD instalada. Acá se validan los argumentos
antes de tocar AutoCAD.

Tipos de valor: números, texto, booleanos, puntos [x,y(,z)], vectores,
escalas [x,y,z], colores (índice 1-255, "ByLayer", "ByBlock" o [r,g,b]) y
enumeraciones (por nombre o número). Lo que no es de esos tipos no se maneja
(colecciones, objetos anidados) y el plugin lo dice con el nombre y el tipo.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import autocad_client as acad

_HANDLE = re.compile(r"^[0-9A-Fa-f]{1,16}$")
MAX_OBJETOS = 500
MAX_PROPIEDADES = 60


class PropiedadesError(ValueError):
    """Argumento inválido: se informa antes de tocar AutoCAD."""


def _handles(handles: Any, un_handle: Any = None) -> list[str]:
    if handles is None and un_handle is not None:
        handles = [un_handle]
    if isinstance(handles, str):
        handles = [handles]
    if not isinstance(handles, (list, tuple)) or not handles:
        raise PropiedadesError("Falta 'handles': una lista con al menos un handle.")
    if len(handles) > MAX_OBJETOS:
        raise PropiedadesError(f"Máximo {MAX_OBJETOS} objetos por llamada (llegaron {len(handles)}).")
    salida: list[str] = []
    for h in handles:
        if not isinstance(h, str) or not _HANDLE.match(h.strip()):
            raise PropiedadesError(f"{h!r} no es un handle hexadecimal (el que devuelven los create_* y list_entities).")
        h = h.strip().upper()
        if h not in salida:
            salida.append(h)
    return salida


def get_properties(handles: Any, names: Optional[list[str]] = None) -> dict[str, Any]:
    pars: dict[str, Any] = {"handles": _handles(handles)}
    if names is not None:
        if not isinstance(names, (list, tuple)) or not names:
            raise PropiedadesError("'names' tiene que ser una lista de nombres, o omitirse para leer todas.")
        if len(names) > MAX_PROPIEDADES:
            raise PropiedadesError(f"Máximo {MAX_PROPIEDADES} propiedades por llamada.")
        if not all(isinstance(n, str) and n.strip() for n in names):
            raise PropiedadesError("Cada nombre de propiedad tiene que ser un texto no vacío.")
        pars["names"] = [n.strip() for n in names]
    return acad.call("get_properties", pars)


def set_properties(handles: Any, properties: dict[str, Any],
                   dry_run: bool = False) -> dict[str, Any]:
    if not isinstance(properties, dict) or not properties:
        raise PropiedadesError("'properties' tiene que ser un objeto {nombre: valor} con al menos una propiedad.")
    if len(properties) > MAX_PROPIEDADES:
        raise PropiedadesError(f"Máximo {MAX_PROPIEDADES} propiedades por llamada.")
    for k, v in properties.items():
        if not isinstance(k, str) or not k.strip():
            raise PropiedadesError("Los nombres de propiedad tienen que ser texto no vacío.")
        if v is None:
            raise PropiedadesError(f"'{k}': el valor no puede ser null.")
    return acad.call("set_properties", {"handles": _handles(handles), "properties": properties,
                                        "dry_run": bool(dry_run)})


def list_properties(entity_type: Optional[str] = None,
                    handle: Optional[str] = None) -> dict[str, Any]:
    if bool(entity_type) == bool(handle):
        raise PropiedadesError("Pasá 'entity_type' (p.ej. 'Polyline') o 'handle', uno de los dos.")
    if handle:
        return acad.call("list_properties", {"handle": _handles([handle])[0]})
    if not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", entity_type or ""):
        raise PropiedadesError(f"'{entity_type}' no es un nombre de clase.")
    return acad.call("list_properties", {"type": entity_type})


def create_object(entity_type: str, properties: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if not isinstance(entity_type, str) or not re.match(r"^[A-Za-z][A-Za-z0-9_]*$", entity_type):
        raise PropiedadesError(f"'{entity_type}' no es un nombre de clase de entidad.")
    properties = {} if properties is None else properties
    if not isinstance(properties, dict):
        raise PropiedadesError("'properties' tiene que ser un objeto {nombre: valor}.")
    if len(properties) > MAX_PROPIEDADES:
        raise PropiedadesError(f"Máximo {MAX_PROPIEDADES} propiedades por llamada.")
    for k, v in properties.items():
        if not isinstance(k, str) or not k.strip():
            raise PropiedadesError("Los nombres de propiedad tienen que ser texto no vacío.")
        if v is None:
            raise PropiedadesError(f"'{k}': el valor no puede ser null.")
    return acad.call("create_object", {"type": entity_type, "properties": properties})
