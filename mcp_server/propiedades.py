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
SEUDO_DB = "DATABASE"


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
        if isinstance(h, str) and h.strip().upper() == SEUDO_DB:
            if SEUDO_DB not in salida:
                salida.append(SEUDO_DB)
            continue
        if not isinstance(h, str) or not _HANDLE.match(h.strip()):
            raise PropiedadesError(f"{h!r} no es un handle hexadecimal (el que devuelven los create_* y list_entities) ni 'DATABASE'.")
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


def create_object(entity_type: str, properties: Optional[dict[str, Any]] = None,
                  container: Optional[str] = None) -> dict[str, Any]:
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
    pars: dict[str, Any] = {"type": entity_type, "properties": properties}
    if container is not None:
        if not isinstance(container, str) or not container.strip():
            raise PropiedadesError("'container' es el nombre o el handle de un bloque.")
        pars["container"] = container.strip()
    return acad.call("create_object", pars)


_NOMBRES_CORTOS = ("layers", "textstyles", "dimstyles", "linetypes", "blocks", "regapps", "ucs", "views",
                   "viewports", "layouts", "mleaderstyles", "tablestyles", "mlinestyles", "materials",
                   "visualstyles", "groups", "named", "plotsettings", "plotstyles")


def list_children(target: str = SEUDO_DB, skip: int = 0, take: int = 500) -> dict[str, Any]:
    if not isinstance(target, str) or not target.strip():
        raise PropiedadesError("'target' es 'DATABASE', un nombre corto ('layers', 'blocks'...) o un handle.")
    target = target.strip()
    t = target.upper()
    if t != SEUDO_DB and target.lower() not in _NOMBRES_CORTOS and not _HANDLE.match(target):
        raise PropiedadesError(f"'{target}' no es 'DATABASE', ni un nombre corto ({', '.join(_NOMBRES_CORTOS)}), ni un handle.")
    if not isinstance(skip, int) or isinstance(skip, bool) or skip < 0:
        raise PropiedadesError("'skip' tiene que ser un entero >= 0.")
    if not isinstance(take, int) or isinstance(take, bool) or not 1 <= take <= 2000:
        raise PropiedadesError("'take' tiene que ser un entero entre 1 y 2000.")
    return acad.call("list_children", {"target": SEUDO_DB if t == SEUDO_DB else
                                       (target.lower() if target.lower() in _NOMBRES_CORTOS else target.upper()),
                                       "skip": skip, "take": take})


KINDS = ("layer", "textstyle", "dimstyle", "block", "regapp", "ucs", "tablestyle", "mleaderstyle")
_PROHIBIDOS = '<>/\\":;?*|,=`'


def _nombre(name: Any) -> str:
    if not isinstance(name, str) or not name or name != name.strip():
        raise PropiedadesError("'name' no puede estar vacío ni empezar o terminar con espacios.")
    if len(name) > 255:
        raise PropiedadesError("'name' no puede pasar de 255 caracteres.")
    mal = next((c for c in name if c in _PROHIBIDOS), None)
    if mal:
        raise PropiedadesError(f"'name' no puede llevar el carácter {mal!r} (AutoCAD lo reserva).")
    if name.startswith("*"):
        raise PropiedadesError("Los nombres que empiezan con * son de AutoCAD (bloques anónimos y espacios).")
    return name


def _kind(kind: Any) -> str:
    if not isinstance(kind, str) or kind.lower() not in KINDS:
        raise PropiedadesError(f"'kind' tiene que ser uno de: {', '.join(KINDS)}.")
    return kind.lower()


def create_database_object(kind: str, name: str,
                           properties: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    properties = {} if properties is None else properties
    if not isinstance(properties, dict):
        raise PropiedadesError("'properties' tiene que ser un objeto {nombre: valor}.")
    if len(properties) > MAX_PROPIEDADES:
        raise PropiedadesError(f"Máximo {MAX_PROPIEDADES} propiedades por llamada.")
    for k, v in properties.items():
        if not isinstance(k, str) or not k.strip():
            raise PropiedadesError("Los nombres de propiedad tienen que ser texto no vacío.")
        if k.strip().lower() == "name":
            raise PropiedadesError("El nombre va en 'name', no en 'properties'.")
        if v is None:
            raise PropiedadesError(f"'{k}': el valor no puede ser null.")
    return acad.call("create_database_object", {"kind": _kind(kind), "name": _nombre(name),
                                                "properties": properties})


def delete_database_object(kind: str, name: Optional[str] = None,
                           handle: Optional[str] = None) -> dict[str, Any]:
    if bool(name) == bool(handle):
        raise PropiedadesError("Pasá 'name' o 'handle', uno de los dos.")
    pars: dict[str, Any] = {"kind": _kind(kind)}
    if name:
        pars["name"] = _nombre(name)
    else:
        pars["handle"] = _handles([handle])[0]
        if pars["handle"] == SEUDO_DB:
            raise PropiedadesError("'DATABASE' no es un objeto que se pueda borrar.")
    return acad.call("delete_database_object", pars)
