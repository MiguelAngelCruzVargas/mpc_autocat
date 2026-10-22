"""Operaciones nativas de la base de datos (plugin 1.17.0+): purgar, fijar el actual, grupos,
datos propios de un objeto (XData y diccionario de extensión), atributos de bloque y escalas
de anotación.

Acá solo se validan los argumentos antes de tocar AutoCAD; las reglas de fondo viven del lado
del plugin (DatabaseExtraCommands.cs). Nada escribe archivos ni ejecuta código.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import autocad_client as acad

_HANDLE = re.compile(r"^[0-9A-Fa-f]{1,16}$")
_PROHIBIDOS = '<>/\\":;?*|,=`'
PURGABLES = ("layer", "textstyle", "dimstyle", "linetype", "block", "regapp", "ucs", "view")
ACTUALES = ("layer", "textstyle", "dimstyle", "linetype")
TIPOS_XDATA = ("text", "layer", "handle", "point", "real", "distance", "scale", "int16", "int")
TIPOS_XRECORD = ("text", "point", "real", "int16", "int", "bool")


class BdError(ValueError):
    """Argumento inválido: se informa antes de tocar AutoCAD."""


def _handle(h: Any, cual: str = "handle") -> str:
    if not isinstance(h, str) or not _HANDLE.match(h.strip()):
        raise BdError(f"'{cual}' tiene que ser un handle hexadecimal, no {h!r}.")
    return h.strip().upper()


def _nombre(n: Any, cual: str = "name", maximo: int = 255) -> str:
    if not isinstance(n, str) or not n or n != n.strip():
        raise BdError(f"'{cual}' no puede estar vacío ni empezar o terminar con espacios.")
    if len(n) > maximo:
        raise BdError(f"'{cual}' no puede pasar de {maximo} caracteres.")
    mal = next((c for c in n if c in _PROHIBIDOS), None)
    if mal:
        raise BdError(f"'{cual}' no puede llevar el carácter {mal!r} (AutoCAD lo reserva).")
    if n.startswith("*"):
        raise BdError(f"'{cual}': los nombres que empiezan con * son de AutoCAD.")
    return n


def _handles(hs: Any, cual: str, minimo: int = 1, maximo: int = 2000) -> list[str]:
    if not isinstance(hs, (list, tuple)) or len(hs) < minimo:
        raise BdError(f"'{cual}' necesita una lista de al menos {minimo} handle(s).")
    if len(hs) > maximo:
        raise BdError(f"'{cual}': máximo {maximo} handles.")
    salida: list[str] = []
    for h in hs:
        h = _handle(h, cual)
        if h not in salida:
            salida.append(h)
    return salida


def _valor(v: Any, tipos: tuple[str, ...], cual: str, usar_bool: bool = False) -> Any:
    """Un valor de XData o de dato propio: texto, número, bool (según el caso), [x,y,z] o {tipo: valor}."""
    if isinstance(v, dict):
        if len(v) != 1:
            raise BdError(f"{cual}: un valor con tipo tiene un solo campo, p.ej. {{'text': '...'}}.")
        (t, x), = v.items()
        if t not in tipos:
            raise BdError(f"{cual}: tipo {t!r} desconocido. Válidos: {', '.join(tipos)}.")
        return v
    if v is None:
        raise BdError(f"{cual}: el valor no puede ser null.")
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (v != v or abs(v) == float("inf")):
            raise BdError(f"{cual}: número inválido (NaN o infinito).")
        return v
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        if len(v) != 3 or not all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in v):
            raise BdError(f"{cual}: un punto es [x, y, z] con tres números.")
        return list(v)
    raise BdError(f"{cual}: valor no soportado: {v!r}.")


def _valores(values: Any, tipos: tuple[str, ...], maximo: int) -> list[Any]:
    if not isinstance(values, (list, tuple)) or not values:
        raise BdError("'values' tiene que ser una lista con al menos un valor.")
    if len(values) > maximo:
        raise BdError(f"Máximo {maximo} valores.")
    return [_valor(v, tipos, f"values[{i}]") for i, v in enumerate(values)]


# ------------------------------------------------------------------ purgar / actual

def purge_database_objects(kinds: Optional[list[str]] = None, dry_run: bool = False) -> dict[str, Any]:
    pars: dict[str, Any] = {"dry_run": bool(dry_run)}
    if kinds is not None:
        if not isinstance(kinds, (list, tuple)) or not kinds:
            raise BdError("'kinds' es una lista o se omite (todos).")
        malos = [k for k in kinds if not isinstance(k, str) or k.lower() not in PURGABLES]
        if malos:
            raise BdError(f"No se purga {malos!r}. Válidos: {', '.join(PURGABLES)}.")
        pars["kinds"] = [k.lower() for k in kinds]
    return acad.call("purge_database_objects", pars)


def set_current(kind: str, name: str) -> dict[str, Any]:
    if not isinstance(kind, str) or kind.lower() not in ACTUALES:
        raise BdError(f"'kind' es uno de: {', '.join(ACTUALES)}.")
    return acad.call("set_current", {"kind": kind.lower(), "name": _nombre(name)})


# ------------------------------------------------------------------ grupos

def create_group(name: str, handles: list[str], description: str = "",
                 selectable: bool = True) -> dict[str, Any]:
    if not isinstance(description, str) or len(description) > 255:
        raise BdError("'description' es un texto de hasta 255 caracteres.")
    return acad.call("create_group", {"name": _nombre(name), "handles": _handles(handles, "handles"),
                                      "description": description, "selectable": bool(selectable)})


def delete_group(name: str) -> dict[str, Any]:
    return acad.call("delete_group", {"name": _nombre(name)})


def modify_group(name: str, add: Optional[list[str]] = None, remove: Optional[list[str]] = None,
                 description: Optional[str] = None,
                 selectable: Optional[bool] = None) -> dict[str, Any]:
    pars: dict[str, Any] = {"name": _nombre(name)}
    if add is not None:
        pars["add"] = _handles(add, "add")
    if remove is not None:
        pars["remove"] = _handles(remove, "remove")
    if description is not None:
        if not isinstance(description, str) or len(description) > 255:
            raise BdError("'description' es un texto de hasta 255 caracteres.")
        pars["description"] = description
    if selectable is not None:
        pars["selectable"] = bool(selectable)
    if len(pars) == 1:
        raise BdError("No hay nada que cambiar: pasá add, remove, description o selectable.")
    return acad.call("modify_group", pars)


# ------------------------------------------------------------------ XData y datos propios

def _app(app: Any) -> str:
    app = _nombre(app, "app", 31)
    if app.upper() == "ACAD":
        raise BdError("ACAD es una aplicación de AutoCAD: no se escribe.")
    return app


def get_xdata(handle: str, app: Optional[str] = None) -> dict[str, Any]:
    pars: dict[str, Any] = {"handle": _handle(handle)}
    if app is not None:
        pars["app"] = _nombre(app, "app", 31)
    return acad.call("get_xdata", pars)


def set_xdata(handle: str, app: str, values: list[Any]) -> dict[str, Any]:
    return acad.call("set_xdata", {"handle": _handle(handle), "app": _app(app),
                                   "values": _valores(values, TIPOS_XDATA, 200)})


def clear_xdata(handle: str, app: str) -> dict[str, Any]:
    return acad.call("clear_xdata", {"handle": _handle(handle), "app": _app(app)})


def get_custom_data(handle: str, key: Optional[str] = None) -> dict[str, Any]:
    pars: dict[str, Any] = {"handle": _handle(handle)}
    if key is not None:
        pars["key"] = _nombre(key, "key")
    return acad.call("get_custom_data", pars)


def set_custom_data(handle: str, key: str, values: list[Any]) -> dict[str, Any]:
    return acad.call("set_custom_data", {"handle": _handle(handle), "key": _nombre(key, "key"),
                                         "values": _valores(values, TIPOS_XRECORD, 1000)})


def delete_custom_data(handle: str, key: str) -> dict[str, Any]:
    return acad.call("delete_custom_data", {"handle": _handle(handle), "key": _nombre(key, "key")})


# ------------------------------------------------------------------ atributos de bloque

def get_block_attributes(handle: str) -> dict[str, Any]:
    return acad.call("get_block_attributes", {"handle": _handle(handle)})


def set_block_attributes(handle: str, values: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(values, dict) or not values:
        raise BdError("'values' tiene que ser un objeto {ETIQUETA: texto} con al menos una.")
    if len(values) > 100:
        raise BdError("Máximo 100 atributos por llamada.")
    limpio: dict[str, Any] = {}
    for k, v in values.items():
        if not isinstance(k, str) or not k.strip():
            raise BdError("Las etiquetas tienen que ser texto no vacío.")
        if v is None:
            raise BdError(f"'{k}': el valor no puede ser null.")
        if isinstance(v, (dict, list)):
            raise BdError(f"'{k}': el valor de un atributo es un texto o un número.")
        limpio[k.strip()] = v
    return acad.call("set_block_attributes", {"handle": _handle(handle), "values": limpio})


# ------------------------------------------------------------------ escalas de anotación

def list_annotation_scales() -> dict[str, Any]:
    return acad.call("list_annotation_scales", {})


def add_annotation_scale(name: str, paper_units: float, drawing_units: float) -> dict[str, Any]:
    for cual, v in (("paper_units", paper_units), ("drawing_units", drawing_units)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v <= 0 or abs(v) == float("inf"):
            raise BdError(f"'{cual}' tiene que ser un número > 0 (para 1:50: paper_units=1, drawing_units=50).")
    if not isinstance(name, str) or not name.strip() or len(name) > 255:
        raise BdError("'name' es un texto no vacío (p.ej. '1:50').")
    return acad.call("add_annotation_scale", {"name": name, "paper_units": float(paper_units),
                                              "drawing_units": float(drawing_units)})


def set_current_annotation_scale(name: str) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise BdError("'name' es el nombre de una escala existente.")
    return acad.call("set_current_annotation_scale", {"name": name})


def remove_annotation_scale(name: str) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise BdError("'name' es el nombre de una escala existente.")
    return acad.call("remove_annotation_scale", {"name": name})


# ------------------------------------------------------------------ layouts e impresión

def list_plot_options(layout: Optional[str] = None) -> dict[str, Any]:
    pars: dict[str, Any] = {}
    if layout is not None:
        if not isinstance(layout, str) or not layout.strip():
            raise BdError("'layout' es el nombre de un layout existente.")
        pars["layout"] = layout.strip()
    return acad.call("list_plot_options", pars)


_ROTACIONES = ("Degrees000", "Degrees090", "Degrees180", "Degrees270")
_TIPOS_AREA = ("Display", "Extents", "Limits", "View", "Window", "Layout")
_UNIDADES = ("Inches", "Millimeters", "Pixels")


def configure_layout(layout: str, device: Optional[str] = None, media: Optional[str] = None,
                     style_sheet: Optional[str] = None, plot_type: Optional[str] = None,
                     rotation: Optional[str] = None, centered: Optional[bool] = None,
                     paper_units: Optional[str] = None, scale: Any = None,
                     window: Optional[list[list[float]]] = None) -> dict[str, Any]:
    if not isinstance(layout, str) or not layout.strip():
        raise BdError("'layout' es el nombre de un layout existente.")
    pars: dict[str, Any] = {"layout": layout.strip()}
    for k, v in (("device", device), ("media", media), ("style_sheet", style_sheet)):
        if v is not None:
            if not isinstance(v, str) or not v.strip():
                raise BdError(f"'{k}' es un texto no vacío (mirá list_plot_options).")
            pars[k] = v.strip()
    if plot_type is not None:
        if plot_type not in _TIPOS_AREA:
            raise BdError(f"'plot_type' es uno de: {', '.join(_TIPOS_AREA)}.")
        pars["plot_type"] = plot_type
    if rotation is not None:
        if rotation not in _ROTACIONES:
            raise BdError(f"'rotation' es uno de: {', '.join(_ROTACIONES)}.")
        pars["rotation"] = rotation
    if centered is not None:
        pars["centered"] = bool(centered)
    if paper_units is not None:
        if paper_units not in _UNIDADES:
            raise BdError(f"'paper_units' es uno de: {', '.join(_UNIDADES)}.")
        pars["paper_units"] = paper_units
    if scale is not None:
        if isinstance(scale, dict):
            ok = set(scale) == {"paper", "drawing"} and all(
                isinstance(scale[k], (int, float)) and not isinstance(scale[k], bool) and scale[k] > 0 and scale[k] == scale[k]
                for k in scale)
            if not ok:
                raise BdError("'scale' como razón es {'paper': n > 0, 'drawing': n > 0}, p.ej. 1 y 100 para 1:100.")
            pars["scale"] = {"paper": float(scale["paper"]), "drawing": float(scale["drawing"])}
        elif isinstance(scale, str) and scale.strip():
            pars["scale"] = scale.strip()
        else:
            raise BdError("'scale' es 'fit', el nombre de una escala estándar o {'paper': 1, 'drawing': 100}.")
    if window is not None:
        ok = (isinstance(window, (list, tuple)) and len(window) == 2 and
              all(isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(c, (int, float)) and not isinstance(c, bool) and c == c for c in p)
                  for p in window) and window[0][0] != window[1][0] and window[0][1] != window[1][1])
        if not ok:
            raise BdError("'window' es [[x1, y1], [x2, y2]] con área.")
        pars["window"] = [list(map(float, window[0])), list(map(float, window[1]))]
    if len(pars) == 1:
        raise BdError("No hay nada que configurar: pasá device, media, style_sheet, plot_type, rotation, centered, paper_units, scale o window.")
    return acad.call("configure_layout", pars)


# ------------------------------------------------------------------ bloques dinámicos

def get_dynamic_block_properties(handle: str) -> dict[str, Any]:
    return acad.call("get_dynamic_block_properties", {"handle": _handle(handle)})


def set_dynamic_block_properties(handle: str, values: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(values, dict) or not values:
        raise BdError("'values' tiene que ser un objeto {propiedad: valor} con al menos una.")
    if len(values) > 60:
        raise BdError("Máximo 60 propiedades por llamada.")
    limpio: dict[str, Any] = {}
    for k, v in values.items():
        if not isinstance(k, str) or not k.strip():
            raise BdError("Los nombres de propiedad tienen que ser texto no vacío.")
        if v is None or isinstance(v, (dict, list, bool)):
            raise BdError(f"'{k}': el valor es un número o un texto.")
        if isinstance(v, float) and (v != v or abs(v) == float("inf")):
            raise BdError(f"'{k}': número inválido (NaN o infinito).")
        limpio[k.strip()] = v
    return acad.call("set_dynamic_block_properties", {"handle": _handle(handle), "values": limpio})


# ------------------------------------------------------------------ herramientas de capas (plugin 1.18.0)

PROPS_ESTADO = ("on", "frozen", "locked", "plot", "color", "linetype", "lineweight", "plotstyle", "transparency")


def _capas(capas: Any, cual: str, minimo: int = 1, maximo: int = 200) -> list[str]:
    if not isinstance(capas, (list, tuple)) or len(capas) < minimo:
        raise BdError(f"'{cual}' necesita una lista de al menos {minimo} nombre(s) de capa.")
    if len(capas) > maximo:
        raise BdError(f"'{cual}': máximo {maximo} capas.")
    vistos: list[str] = []
    for c in capas:
        c = _nombre(c, cual)
        if c.lower() not in [v.lower() for v in vistos]:
            vistos.append(c)
    return vistos


def merge_layers(sources: list[str], target: str) -> dict[str, Any]:
    fuentes = _capas(sources, "sources")
    destino = _nombre(target, "target")
    if destino.lower() in [f.lower() for f in fuentes]:
        raise BdError("'target' no puede estar también en 'sources'.")
    if any(f.lower() in ("0", "defpoints") for f in fuentes):
        raise BdError("Las capas 0 y Defpoints son del sistema: no se fusionan.")
    return acad.call("merge_layers", {"sources": fuentes, "target": destino})


def delete_layer_with_objects(name: str, confirm: bool = False) -> dict[str, Any]:
    n = _nombre(name)
    if n.lower() in ("0", "defpoints"):
        raise BdError("Las capas 0 y Defpoints son del sistema: no se borran.")
    return acad.call("delete_layer_with_objects", {"name": n, "confirm": confirm is True})


def _props_estado(properties: Optional[list[str]]) -> Optional[list[str]]:
    if properties is None:
        return None
    if not isinstance(properties, (list, tuple)) or not properties:
        raise BdError("'properties' es una lista o se omite (todas).")
    malas = [p for p in properties if not isinstance(p, str) or p.lower() not in PROPS_ESTADO]
    if malas:
        raise BdError(f"Propiedad(es) {malas!r} desconocida(s). Válidas: {', '.join(PROPS_ESTADO)}.")
    return [p.lower() for p in properties]


def save_layer_state(name: str, description: str = "", properties: Optional[list[str]] = None,
                     replace: bool = False) -> dict[str, Any]:
    n = _nombre(name, maximo=100)
    if n.upper().startswith("_MCP_"):
        raise BdError("Los nombres que empiezan con _MCP_ son internos.")
    if not isinstance(description, str) or len(description) > 255:
        raise BdError("'description' es un texto de hasta 255 caracteres.")
    pars: dict[str, Any] = {"name": n, "description": description, "replace": replace is True}
    p = _props_estado(properties)
    if p is not None:
        pars["properties"] = p
    return acad.call("save_layer_state", pars)


def restore_layer_state(name: str, properties: Optional[list[str]] = None,
                        turn_off_others: bool = False) -> dict[str, Any]:
    pars: dict[str, Any] = {"name": _nombre(name, maximo=100), "turn_off_others": turn_off_others is True}
    p = _props_estado(properties)
    if p is not None:
        pars["properties"] = p
    return acad.call("restore_layer_state", pars)


def list_layer_states() -> dict[str, Any]:
    return acad.call("list_layer_states", {})


def delete_layer_state(name: str) -> dict[str, Any]:
    n = _nombre(name, maximo=100)
    if n.upper().startswith("_MCP_"):
        raise BdError("Ese estado es interno (aislar capas): usá unisolate_layers.")
    return acad.call("delete_layer_state", {"name": n})


def isolate_layers(layers: list[str], mode: str = "off") -> dict[str, Any]:
    if mode not in ("off", "lock"):
        raise BdError("'mode' es 'off' (apagar las demás) o 'lock' (bloquearlas).")
    return acad.call("isolate_layers", {"layers": _capas(layers, "layers"), "mode": mode})


def unisolate_layers() -> dict[str, Any]:
    return acad.call("unisolate_layers", {})


def set_viewport_layers(handle: str, freeze: Optional[list[str]] = None, thaw: Optional[list[str]] = None,
                        thaw_all: bool = False, freeze_all_except: Optional[list[str]] = None) -> dict[str, Any]:
    pars: dict[str, Any] = {"handle": _handle(handle)}
    if freeze is not None and freeze_all_except is not None:
        raise BdError("Usá 'freeze' o 'freeze_all_except', no los dos.")
    if freeze is not None:
        pars["freeze"] = _capas(freeze, "freeze")
    if thaw is not None:
        pars["thaw"] = _capas(thaw, "thaw")
    if freeze_all_except is not None:
        pars["freeze_all_except"] = _capas(freeze_all_except, "freeze_all_except")
    if thaw_all:
        pars["thaw_all"] = True
    return acad.call("set_viewport_layers", pars)


# ------------------------------------------------------------------ copias y layouts (plugin 1.18.0)

VERSIONES_COPIA = ("2018", "2013", "2010", "2007", "2004", "2000")


def export_copy(path: str, version: str = "2018", precision: int = 16, overwrite: bool = False) -> dict[str, Any]:
    if not isinstance(path, str) or not path.strip():
        raise BdError("'path' es la ruta del archivo .dwg o .dxf a escribir.")
    if not path.lower().endswith((".dwg", ".dxf")):
        raise BdError("La extensión del archivo tiene que ser .dwg o .dxf.")
    version = str(version)
    if version not in VERSIONES_COPIA:
        raise BdError(f"'version' es una de: {', '.join(VERSIONES_COPIA)}.")
    if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 16:
        raise BdError("'precision' son los decimales del DXF: un entero de 0 a 16.")
    return acad.call("export_copy", {"path": path.strip(), "version": version, "precision": precision,
                                     "overwrite": overwrite is True})


def _layout(n: Any, cual: str) -> str:
    if not isinstance(n, str) or not n or n != n.strip():
        raise BdError(f"'{cual}' no puede estar vacío ni empezar o terminar con espacios.")
    if len(n) > 255:
        raise BdError(f"'{cual}' no puede pasar de 255 caracteres.")
    mal = next((c for c in n if c in _PROHIBIDOS), None)
    if mal:
        raise BdError(f"'{cual}' no puede llevar el carácter {mal!r}.")
    return n


def rename_layout(name: str, new_name: str) -> dict[str, Any]:
    a, b = _layout(name, "name"), _layout(new_name, "new_name")
    if a.lower() == "model" or b.lower() == "model":
        raise BdError("«Model» es el espacio modelo: ni se renombra ni se usa como nombre de lámina.")
    return acad.call("rename_layout", {"name": a, "new_name": b})


def copy_layout(name: str, new_name: str) -> dict[str, Any]:
    a, b = _layout(name, "name"), _layout(new_name, "new_name")
    if a.lower() == "model":
        raise BdError("«Model» no es una lámina: no se copia.")
    if b.lower() == "model":
        raise BdError("«Model» está reservado para el espacio modelo.")
    return acad.call("copy_layout", {"name": a, "new_name": b})


# ------------------------------------------------------------------ xrefs y propiedades del dibujo (plugin 1.18.0)

def _xrefs(name: Optional[str], names: Optional[list[str]]) -> dict[str, Any]:
    if name is not None and names is not None:
        raise BdError("Usá 'name' o 'names', no los dos.")
    pars: dict[str, Any] = {}
    if name is not None:
        pars["names"] = [_nombre(name)]
    if names is not None:
        pars["names"] = _capas(names, "names")
    return pars


def bind_xref(name: Optional[str] = None, names: Optional[list[str]] = None, insert: bool = True) -> dict[str, Any]:
    pars = _xrefs(name, names)
    pars["insert"] = insert is not False
    return acad.call("bind_xref", pars)


def unload_xref(name: Optional[str] = None, names: Optional[list[str]] = None) -> dict[str, Any]:
    return acad.call("unload_xref", _xrefs(name, names))


PROPS_DIBUJO = ("title", "subject", "author", "keywords", "comments", "hyperlink_base")


def get_drawing_properties() -> dict[str, Any]:
    return acad.call("get_drawing_properties", {})


def set_drawing_properties(title: Optional[str] = None, subject: Optional[str] = None,
                           author: Optional[str] = None, keywords: Optional[str] = None,
                           comments: Optional[str] = None, hyperlink_base: Optional[str] = None,
                           custom: Optional[dict[str, Optional[str]]] = None) -> dict[str, Any]:
    pars: dict[str, Any] = {}
    for k, v in (("title", title), ("subject", subject), ("author", author), ("keywords", keywords),
                 ("comments", comments), ("hyperlink_base", hyperlink_base)):
        if v is None:
            continue
        if not isinstance(v, str) or len(v) > 1000:
            raise BdError(f"'{k}' es un texto de hasta 1000 caracteres.")
        pars[k] = v
    if custom is not None:
        if not isinstance(custom, dict) or not custom:
            raise BdError("'custom' es un objeto {nombre: valor}; un valor null borra la propiedad.")
        if len(custom) > 100:
            raise BdError("Máximo 100 propiedades personalizadas por llamada.")
        limpio: dict[str, Optional[str]] = {}
        for k, v in custom.items():
            if not isinstance(k, str) or not k or k != k.strip() or len(k) > 255:
                raise BdError("El nombre de una propiedad personalizada no puede estar vacío ni tener espacios en los bordes.")
            if v is not None and (not isinstance(v, str) or len(v) > 1000):
                raise BdError(f"'{k}': el valor es un texto de hasta 1000 caracteres (o null para borrarla).")
            limpio[k] = v
        pars["custom"] = limpio
    if not pars:
        raise BdError("No hay nada que cambiar: pasá title, subject, author, keywords, comments, hyperlink_base o custom.")
    return acad.call("set_drawing_properties", pars)


# ------------------------------------------------------------------ edición con la API (plugin 1.18.0)

PROPS_IGUALAR = ("layer", "color", "linetype", "linetype_scale", "lineweight", "transparency")


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def _punto2(p: Any, cual: str) -> list[float]:
    if not isinstance(p, (list, tuple)) or len(p) not in (2, 3) or not all(_num(c) for c in p):
        raise BdError(f"'{cual}' es un punto [x, y] (o [x, y, z]) con números.")
    return [float(c) for c in p]


def explode_entities(handles: list[str], delete_original: bool = True) -> dict[str, Any]:
    return acad.call("explode_entities", {"handles": _handles(handles, "handles", maximo=500),
                                          "delete_original": delete_original is not False})


def break_curve(handle: str, points: list[list[float]]) -> dict[str, Any]:
    if not isinstance(points, (list, tuple)) or not points:
        raise BdError("'points' es una lista de puntos [x, y] donde cortar.")
    if len(points) > 200:
        raise BdError("Máximo 200 puntos de corte.")
    return acad.call("break_curve", {"handle": _handle(handle),
                                     "points": [_punto2(p, f"points[{i}]") for i, p in enumerate(points)]})


def divide_curve(handle: str, count: Optional[int] = None, distance: Optional[float] = None,
                 block: Optional[str] = None, align: bool = True, layer: Optional[str] = None) -> dict[str, Any]:
    if (count is None) == (distance is None):
        raise BdError("Pasá 'count' (dividir en N partes) o 'distance' (marcar cada tanto), uno de los dos.")
    pars: dict[str, Any] = {"handle": _handle(handle), "align": align is not False}
    if count is not None:
        if isinstance(count, bool) or not isinstance(count, int) or not 2 <= count <= 5000:
            raise BdError("'count' es un entero de 2 a 5000.")
        pars["count"] = count
    if distance is not None:
        if not _num(distance) or distance <= 0:
            raise BdError("'distance' tiene que ser un número mayor que cero.")
        pars["distance"] = float(distance)
    if block is not None:
        pars["block"] = _nombre(block, "block")
    if layer is not None:
        pars["layer"] = _nombre(layer, "layer")
    return acad.call("divide_curve", pars)


def create_boundary(point: list[float], islands: bool = True, layer: Optional[str] = None) -> dict[str, Any]:
    pars: dict[str, Any] = {"point": _punto2(point, "point"), "islands": islands is not False}
    if layer is not None:
        pars["layer"] = _nombre(layer, "layer")
    return acad.call("create_boundary", pars)


def match_properties(source: str, targets: list[str], properties: Optional[list[str]] = None) -> dict[str, Any]:
    pars: dict[str, Any] = {"source": _handle(source, "source"), "targets": _handles(targets, "targets", maximo=500)}
    if pars["source"] in pars["targets"]:
        pars["targets"] = [t for t in pars["targets"] if t != pars["source"]]
        if not pars["targets"]:
            raise BdError("'targets' no puede ser solo la entidad de origen.")
    if properties is not None:
        if not isinstance(properties, (list, tuple)) or not properties:
            raise BdError("'properties' es una lista o se omite (todas).")
        malas = [p for p in properties if not isinstance(p, str) or p.lower() not in PROPS_IGUALAR]
        if malas:
            raise BdError(f"Propiedad(es) {malas!r} desconocida(s). Válidas: {', '.join(PROPS_IGUALAR)}.")
        pars["properties"] = [p.lower() for p in properties]
    return acad.call("match_properties", pars)


# ------------------------------------------------------------------ sólidos desde perfiles dibujados (plugin 1.18.0)

def _punto3(p: Any, cual: str) -> list[float]:
    if not isinstance(p, (list, tuple)) or len(p) not in (2, 3) or not all(_num(c) for c in p):
        raise BdError(f"'{cual}' es [x, y] o [x, y, z] con números.")
    return [float(c) for c in p] + ([0.0] if len(p) == 2 else [])


def _vector(p: Any, cual: str) -> list[float]:
    v = _punto3(p, cual)
    if all(abs(c) < 1e-12 for c in v):
        raise BdError(f"'{cual}' no puede ser un vector nulo.")
    return v


def _opt_num(v: Any, cual: str, minimo: Optional[float] = None, maximo: Optional[float] = None) -> float:
    if not _num(v):
        raise BdError(f"'{cual}' tiene que ser un número finito.")
    if minimo is not None and v < minimo:
        raise BdError(f"'{cual}' no puede ser menor que {minimo}.")
    if maximo is not None and v > maximo:
        raise BdError(f"'{cual}' no puede ser mayor que {maximo}.")
    return float(v)


def _capa_opcional(pars: dict[str, Any], layer: Optional[str]) -> None:
    if layer is not None:
        pars["layer"] = _nombre(layer, "layer")


def extrude_solid(profile: str, height: Optional[float] = None, direction: Optional[list[float]] = None,
                  taper_deg: float = 0.0, delete_profile: bool = False, layer: Optional[str] = None) -> dict[str, Any]:
    if (height is None) == (direction is None):
        raise BdError("Pasá 'height' (a lo largo de la normal del perfil) o 'direction' [x, y, z], uno de los dos.")
    pars: dict[str, Any] = {"profile": _handle(profile, "profile"), "taper_deg": _opt_num(taper_deg, "taper_deg", -89.0, 89.0),
                            "delete_profile": delete_profile is True}
    if height is not None:
        h = _opt_num(height, "height")
        if h == 0:
            raise BdError("'height' no puede ser 0.")
        pars["height"] = h
    else:
        pars["direction"] = _vector(direction, "direction")
    _capa_opcional(pars, layer)
    return acad.call("extrude_solid", pars)


def revolve_solid(profile: str, axis_point: list[float], axis_dir: list[float], angle_deg: float = 360.0,
                  start_angle_deg: float = 0.0, twist_deg: float = 0.0, draft_deg: float = 0.0,
                  close_to_axis: bool = False, delete_profile: bool = False, layer: Optional[str] = None) -> dict[str, Any]:
    a = _opt_num(angle_deg, "angle_deg", -360.0, 360.0)
    if a == 0:
        raise BdError("'angle_deg' va de -360 a 360 y no puede ser 0.")
    pars: dict[str, Any] = {
        "profile": _handle(profile, "profile"), "axis_point": _punto3(axis_point, "axis_point"),
        "axis_dir": _vector(axis_dir, "axis_dir"), "angle_deg": a,
        "start_angle_deg": _opt_num(start_angle_deg, "start_angle_deg"), "twist_deg": _opt_num(twist_deg, "twist_deg"),
        "draft_deg": _opt_num(draft_deg, "draft_deg", -89.0, 89.0), "close_to_axis": close_to_axis is True,
        "delete_profile": delete_profile is True}
    _capa_opcional(pars, layer)
    return acad.call("revolve_solid", pars)


def sweep_solid(profile: str, path: str, twist_deg: float = 0.0, scale: float = 1.0, align: bool = True,
                bank: bool = False, delete_profile: bool = False, delete_path: bool = False,
                layer: Optional[str] = None) -> dict[str, Any]:
    p, t = _handle(profile, "profile"), _handle(path, "path")
    if p == t:
        raise BdError("El perfil y la trayectoria no pueden ser la misma entidad.")
    pars: dict[str, Any] = {"profile": p, "path": t, "twist_deg": _opt_num(twist_deg, "twist_deg"),
                            "scale": _opt_num(scale, "scale"), "align": align is not False, "bank": bank is True,
                            "delete_profile": delete_profile is True, "delete_path": delete_path is True}
    if pars["scale"] <= 0:
        raise BdError("'scale' tiene que ser mayor que cero.")
    _capa_opcional(pars, layer)
    return acad.call("sweep_solid", pars)


def loft_solid(sections: list[str], guides: Optional[list[str]] = None, path: Optional[str] = None,
               ruled: bool = False, closed: bool = False, delete_sources: bool = False,
               layer: Optional[str] = None) -> dict[str, Any]:
    secs = _handles(sections, "sections", minimo=2, maximo=50)
    pars: dict[str, Any] = {"sections": secs, "ruled": ruled is True, "closed": closed is True,
                            "delete_sources": delete_sources is True}
    if guides is not None:
        pars["guides"] = _handles(guides, "guides", maximo=50)
    if path is not None:
        pars["path"] = _handle(path, "path")
    if guides and path is not None:
        raise BdError("Un loft lleva guías O trayectoria, no las dos.")
    _capa_opcional(pars, layer)
    return acad.call("loft_solid", pars)
