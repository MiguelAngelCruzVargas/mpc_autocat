"""Consulta y agregados sobre las entidades de un dibujo.

Responde preguntas como «cuántas líneas hay por capa», «qué polilíneas cerradas
miden más de 12 m²» o «cuánto suman los largos de la capa MUROS» SIN escribir
un script ni contar a mano. Lo que sale es lo que mide el dibujo, no un número
recordado (misma regla que calculate_quantities).

El motor es puro: no habla con AutoCAD. Recibe dos funciones,
`listar(params) -> dict` (el comando list_entities del plugin) y
`detallar(handles) -> {handle: dict}` (get_entity, de a cientos por viaje), y
las tools de server.py le pasan las reales. Así se prueba sin AutoCAD.

Tres capas de campos, de la más barata a la más cara:
  1. base (list_entities): handle, type, layer, space.
  2. caja y texto (list_entities con includeExtents/includeText): minX, minY,
     maxX, maxY, width, height, bboxArea, centerX, centerY, text.
  3. detalle (get_entity, un viaje de ~0.5 s por lote): length, area, radius,
     closed, blockName, patternName, measurement, colorIndex, ...
Solo se pide el detalle de lo que sobrevive a los filtros baratos, y si hay
más candidatos que `hydrate_limit` NO se corta en silencio: se informa.

Filtro (lenguaje propio, no hay paréntesis): `=  !=  <  >  <=  >=  contains
startswith  endswith`, unidos con AND / OR (AND liga más fuerte). El texto no
distingue mayúsculas. `= null` / `!= null` miran si el campo falta. Un campo
que falta NO cumple ninguna comparación (salvo `= null`): no se inventa.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

BASE = ("handle", "type", "layer", "space")
CAJA = ("minX", "minY", "maxX", "maxY", "width", "height", "bboxArea",
        "centerX", "centerY")
TEXTO = ("text",)
BARATOS = frozenset(BASE + CAJA + TEXTO)

# Lo que devuelve get_entity (plugin GetEntityCommand), por tipo. Es la
# «descripción de esquemas»: que quien consulta sepa qué campos existen antes
# de pedirlos, en vez de adivinar.
DETALLE_COMUN = ("colorIndex", "linetype", "bbox")
DETALLE_POR_TIPO: dict[str, tuple[str, ...]] = {
    "Line": ("startPoint", "endPoint", "length"),
    "Circle": ("center", "radius", "area"),
    "Arc": ("center", "radius", "startAngleDeg", "endAngleDeg"),
    "Polyline": ("closed", "area", "length", "points", "bulges", "hasArcs"),
    "DBText": ("text", "position", "height"),
    "MText": ("text", "location"),
    "Hatch": ("patternName", "patternType", "patternScale", "patternAngleDeg",
              "isSolid", "loops", "hatchArea"),
    "BlockReference": ("blockName", "position", "attributes"),
    "Dimension": ("measurement", "dimensionText", "overridden", "styleName",
                  "textPosition", "textHeight", "textAbove", "textStyle",
                  "dimScale"),
    "Viewport": ("centerPoint", "width", "height", "viewCenter", "viewHeight"),
}
AGREGACIONES = ("count", "sum", "avg", "min", "max", "minabs", "maxabs")

_OPERADORES = ("<=", ">=", "!=", "=", "<", ">")
_PALABRAS = ("contains", "startswith", "endswith")


class ConsultaError(ValueError):
    """Filtro o parámetros inválidos: se informan, no se adivinan."""


# ------------------------------------------------------------------ filtro

def _partir(texto: str, palabra: str) -> list[str]:
    """Parte por ' AND ' / ' OR ' fuera de comillas."""
    partes: list[str] = []
    actual: list[str] = []
    comilla = ""
    i = 0
    clave = f" {palabra} "
    while i < len(texto):
        c = texto[i]
        if comilla:
            if c == comilla:
                comilla = ""
            actual.append(c)
            i += 1
            continue
        if c in "'\"":
            comilla = c
            actual.append(c)
            i += 1
            continue
        if texto[i:i + len(clave)].upper() == clave:
            partes.append("".join(actual))
            actual = []
            i += len(clave)
            continue
        actual.append(c)
        i += 1
    if comilla:
        raise ConsultaError(f"Comilla sin cerrar en el filtro: {texto!r}")
    partes.append("".join(actual))
    return partes


def _valor(texto: str) -> Any:
    t = texto.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        return t[1:-1]
    bajo = t.lower()
    if bajo == "null":
        return None
    if bajo in ("true", "false"):
        return bajo == "true"
    try:
        return float(t)
    except ValueError:
        return t   # texto sin comillas: se toma literal


def _clausula(texto: str) -> tuple[str, str, Any]:
    t = texto.strip()
    if not t:
        raise ConsultaError("Condición vacía en el filtro (¿un AND/OR de más?).")
    if re.search(r"(?i)\s(AND|OR)$", t) or re.match(r"(?i)^(AND|OR)\s", t):
        raise ConsultaError(f"AND/OR sin condición al lado en {t!r}.")
    m = re.match(r"^([A-Za-z_][\w.\[\]]*)\s+(contains|startswith|endswith)\s+(.+)$",
                 t, re.IGNORECASE)
    if m:
        return m.group(1), m.group(2).lower(), _valor(m.group(3))
    m = re.match(r"^([A-Za-z_][\w.\[\]]*)\s*(<=|>=|!=|=|<|>)\s*(.+)$", t)
    if m:
        return m.group(1), m.group(2), _valor(m.group(3))
    raise ConsultaError(
        f"No entiendo la condición {t!r}. Formato: campo operador valor "
        f"(operadores: {', '.join(_OPERADORES + _PALABRAS)}).")


def parsear_filtro(filtro: Optional[str]) -> list[list[tuple[str, str, Any]]]:
    """'a = 1 AND b > 2 OR c contains x' -> [[a=1, b>2], [c contains x]]
    (lista de grupos OR; cada grupo es una lista de condiciones AND)."""
    if filtro is None or not filtro.strip():
        return []
    return [[_clausula(c) for c in _partir(grupo, "AND")]
            for grupo in _partir(filtro, "OR")]


def campo(ent: dict[str, Any], ruta: str) -> Any:
    """Valor de un campo con ruta de puntos ('center.0', 'attributes.TAG').
    Devuelve None si no existe."""
    ruta = ruta.replace("[", ".").replace("]", "")
    cur: Any = ent
    for parte in ruta.split("."):
        if isinstance(cur, dict):
            if parte in cur:
                cur = cur[parte]
                continue
            # los nombres de campo no distinguen mayúsculas
            alt = next((k for k in cur if k.lower() == parte.lower()), None)
            if alt is None:
                return None
            cur = cur[alt]
        elif isinstance(cur, (list, tuple)) and parte.lstrip("-").isdigit():
            i = int(parte)
            if not -len(cur) <= i < len(cur):
                return None
            cur = cur[i]
        else:
            return None
    return cur


def _num(x: Any) -> Optional[float]:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x.strip())
        except ValueError:
            return None
    return None


def cumple(ent: dict[str, Any], cond: tuple[str, str, Any]) -> bool:
    ruta, op, esperado = cond
    real = campo(ent, ruta)
    if esperado is None:                      # = null / != null
        if op == "=":
            return real is None
        if op == "!=":
            return real is not None
        raise ConsultaError(f"'{op} null' no tiene sentido; usá = null o != null.")
    if real is None:
        return False                           # lo que falta no se compara
    if op in _PALABRAS:
        a, b = str(real).lower(), str(esperado).lower()
        return (b in a if op == "contains"
                else a.startswith(b) if op == "startswith" else a.endswith(b))
    nr, ne = _num(real), _num(esperado)
    if nr is not None and ne is not None:
        a, b = nr, ne
    elif isinstance(real, bool) or isinstance(esperado, bool):
        a, b = str(real).lower(), str(esperado).lower()
    else:
        a, b = str(real).lower(), str(esperado).lower()
        if op in ("<", ">", "<=", ">="):
            raise ConsultaError(
                f"'{op}' compara números y {ruta!r} vale {real!r}; "
                "usá = / != / contains para texto.")
    return {"=": a == b, "!=": a != b, "<": a < b, ">": a > b,
            "<=": a <= b, ">=": a >= b}[op]


def pasa(ent: dict[str, Any], grupos: list[list[tuple[str, str, Any]]]) -> bool:
    return not grupos or any(all(cumple(ent, c) for c in g) for g in grupos)


# ------------------------------------------------------------------ datos

def con_caja(ent: dict[str, Any]) -> dict[str, Any]:
    """Agrega minX..centerY a partir de 'box' [minX, minY, maxX, maxY]."""
    box = ent.get("box") or ent.get("bbox")
    if isinstance(box, (list, tuple)) and len(box) >= 4:
        x0, y0, x1, y1 = (float(v) for v in box[:4])
        ent = dict(ent)
        ent.update(minX=x0, minY=y0, maxX=x1, maxY=y1, width=x1 - x0,
                   height=y1 - y0, bboxArea=(x1 - x0) * (y1 - y0),
                   centerX=(x0 + x1) / 2, centerY=(y0 + y1) / 2)
    return ent


def _raiz(ruta: str) -> str:
    return re.split(r"[.\[]", ruta, 1)[0]


def campos_usados(grupos, fields, aggs) -> set[str]:
    usados = {_raiz(c[0]) for g in grupos for c in g}
    usados |= {_raiz(f) for f in (fields or [])}
    for a in aggs or []:
        for k in ("field", "group_by"):
            if a.get(k):
                usados.add(_raiz(a[k]))
    return usados


def _clave_baja(nombre: str) -> str:
    return nombre.lower()


def necesita_detalle(usados: set[str]) -> bool:
    bajos = {_clave_baja(b) for b in BARATOS}
    return any(_clave_baja(u) not in bajos for u in usados)


def necesita_texto(usados: set[str]) -> bool:
    return any(u.lower() == "text" for u in usados)


def necesita_caja(usados: set[str]) -> bool:
    return any(u.lower() in {c.lower() for c in CAJA} for u in usados)


def cargar(listar: Callable[[dict[str, Any]], dict[str, Any]],
           detallar: Callable[[list[str]], dict[str, dict[str, Any]]],
           entity_type: Optional[str], grupos, fields, aggs,
           *, todos_los_espacios: bool = False, scan_limit: int = 20000,
           hydrate_limit: int = 500) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Devuelve (entidades que cumplen el filtro, meta). Nunca corta en
    silencio: lo que se acotó va en meta['notices']."""
    usados = campos_usados(grupos, fields, aggs)
    meta: dict[str, Any] = {"notices": []}
    if entity_type is None and len(grupos) == 1:
        # `type = Polyline` en un filtro AND se resuelve en el plugin: no se
        # traen las demás entidades para descartarlas acá.
        for ruta, op, val in grupos[0]:
            if ruta.lower() == "type" and op == "=" and isinstance(val, str):
                entity_type = val
                break
    pars: dict[str, Any] = {"type": entity_type, "limit": scan_limit}
    if necesita_caja(usados):
        pars["includeExtents"] = True
    if necesita_texto(usados):
        pars["includeText"] = True
    if todos_los_espacios:
        pars["allSpaces"] = True
    r = listar(pars)
    ents = [con_caja(e) for e in r.get("entities", [])]
    meta["scanned"] = len(ents)
    if len(ents) >= scan_limit:
        meta["notices"].append(
            f"Se leyeron {scan_limit} entidades, el tope del escaneo: puede haber "
            "más. Acotá con entity_type o subí scan_limit.")

    if necesita_detalle(usados):
        baratos = {b.lower() for b in BARATOS}
        # Con un solo grupo AND, las condiciones baratas se aplican primero
        # (es seguro: si una falla, el grupo entero falla). Con OR no se puede
        # descartar nada sin leer el detalle.
        if len(grupos) == 1:
            previas = [c for c in grupos[0] if _raiz(c[0]).lower() in baratos]
            ents = [e for e in ents if all(cumple(e, c) for c in previas)]
        if len(ents) > hydrate_limit:
            meta["notices"].append(
                f"{len(ents)} entidades necesitan leerse en detalle y el tope es "
                f"{hydrate_limit} (cada lote cuesta ~0.5 s). Resultado PARCIAL: se "
                f"leyeron las primeras {hydrate_limit}. Acotá con entity_type o con "
                "condiciones sobre layer / bboxArea, o subí hydrate_limit.")
            meta["partial"] = True
            ents = ents[:hydrate_limit]
        det = detallar([e["handle"] for e in ents]) if ents else {}
        meta["detailed"] = len(det)
        fusion = []
        for e in ents:
            d = det.get(e["handle"])
            if d is None:
                meta["notices"].append(f"No se pudo leer {e['handle']}; se omite.")
                continue
            fusion.append({**d, **{k: v for k, v in e.items() if k not in d}})
        ents = fusion
    return [e for e in ents if pasa(e, grupos)], meta


# ------------------------------------------------------------------ salida

def proyectar(ent: dict[str, Any], fields: Optional[list[str]]) -> dict[str, Any]:
    if not fields:
        return {k: ent[k] for k in BASE if k in ent}
    out = {"handle": ent.get("handle")}
    for f in fields:
        out[f] = campo(ent, f)
    return out


def consultar(listar, detallar, *, entity_type: Optional[str] = None,
              fields: Optional[list[str]] = None, filtro: Optional[str] = None,
              skip: int = 0, take: int = 200, todos_los_espacios: bool = False,
              scan_limit: int = 20000, hydrate_limit: int = 500) -> dict[str, Any]:
    if skip < 0 or take < 0:
        raise ConsultaError("skip y take no pueden ser negativos.")
    grupos = parsear_filtro(filtro)
    ents, meta = cargar(listar, detallar, entity_type, grupos, fields, None,
                        todos_los_espacios=todos_los_espacios,
                        scan_limit=scan_limit, hydrate_limit=hydrate_limit)
    pagina = ents[skip:skip + take]
    return {"matches": len(ents), "returned": len(pagina), "skip": skip,
            "entities": [proyectar(e, fields) for e in pagina], **meta}


def _agregar(valores: list[float], tipo: str) -> Optional[float]:
    if not valores:
        return None
    if tipo == "sum":
        return sum(valores)
    if tipo == "avg":
        return sum(valores) / len(valores)
    if tipo == "min":
        return min(valores)
    if tipo == "max":
        return max(valores)
    if tipo == "minabs":
        return min(valores, key=abs)
    return max(valores, key=abs)                 # maxabs


def _clave_grupo(v: Any) -> Any:
    if isinstance(v, (list, dict)):
        return str(v)
    return v


def agregar(listar, detallar, *, aggregations: Optional[list[dict[str, Any]]] = None,
            entity_type: Optional[str] = None, filtro: Optional[str] = None,
            todos_los_espacios: bool = False, scan_limit: int = 20000,
            hydrate_limit: int = 500) -> dict[str, Any]:
    """aggregations: [{type, field?, group_by?, order_by?, ascending?}]. Sin
    lista, un solo conteo. count no pide field; el resto sí."""
    specs = aggregations or [{"type": "count"}]
    for s in specs:
        t = str(s.get("type", "")).lower()
        if t not in AGREGACIONES:
            raise ConsultaError(f"Agregación {s.get('type')!r} desconocida; "
                                f"válidas: {', '.join(AGREGACIONES)}.")
        if t != "count" and not s.get("field"):
            raise ConsultaError(f"'{t}' necesita 'field' (el campo numérico a operar).")
    grupos = parsear_filtro(filtro)
    ents, meta = cargar(listar, detallar, entity_type, grupos, None, specs,
                        todos_los_espacios=todos_los_espacios,
                        scan_limit=scan_limit, hydrate_limit=hydrate_limit)
    resultados = []
    for s in specs:
        t = str(s["type"]).lower()
        fld, gb = s.get("field"), s.get("group_by")
        saltados = 0
        grupos_v: dict[Any, list[float]] = {}
        cuenta: dict[Any, int] = {}
        for e in ents:
            g = _clave_grupo(campo(e, gb)) if gb else "__todo"
            cuenta[g] = cuenta.get(g, 0) + 1
            if t == "count":
                continue
            n = _num(campo(e, fld))
            if n is None:
                saltados += 1
                continue
            grupos_v.setdefault(g, []).append(n)
        filas = []
        for g in cuenta:
            valor = cuenta[g] if t == "count" else _agregar(grupos_v.get(g, []), t)
            filas.append({"group": g, "value": valor,
                          **({"n": cuenta[g]} if t != "count" else {})})
        res: dict[str, Any] = {"type": t, **({"field": fld} if fld else {}),
                               **({"group_by": gb} if gb else {})}
        if gb:
            orden = s.get("order_by")
            asc = bool(s.get("ascending", False))
            clave = "group" if orden and orden == gb else "value"
            filas.sort(key=lambda f: (f[clave] is None, f[clave] if f[clave] is not None else 0),
                       reverse=not asc)
            res["groups"] = filas
        else:
            res["value"] = filas[0]["value"] if filas else (0 if t == "count" else None)
        if saltados:
            res["skippedNonNumeric"] = saltados
        resultados.append(res)
    return {"matches": len(ents), "results": resultados, **meta}


def esquema(entity_type: Optional[str] = None) -> dict[str, Any]:
    """Qué campos se pueden consultar y a qué costo."""
    out: dict[str, Any] = {
        "base": {"campos": list(BASE), "costo": "gratis (una llamada para todo el espacio)"},
        "caja": {"campos": list(CAJA), "costo": "gratis; se pide solo si el filtro los usa"},
        "texto": {"campos": list(TEXTO), "costo": "gratis; solo DBText y MText"},
        "detalle": {"costo": "un lote de lecturas por cada 300 entidades que sobreviven "
                             "a los filtros baratos (~0.5 s por lote)",
                    "comunes": list(DETALLE_COMUN)},
        "operadores": list(_OPERADORES + _PALABRAS) + ["AND", "OR"],
        "agregaciones": list(AGREGACIONES),
    }
    por_tipo = DETALLE_POR_TIPO
    if entity_type:
        clave = next((k for k in por_tipo if k.lower() == entity_type.lower()), None)
        if clave is None and entity_type.lower().endswith("dimension"):
            clave = "Dimension"
        if clave is None:
            out["detalle"]["aviso"] = (
                f"No hay lista de campos para el tipo {entity_type!r}: sirve la base, "
                "la caja y los campos comunes.")
        else:
            por_tipo = {clave: por_tipo[clave]}
    out["detalle"]["por_tipo"] = {k: list(v) for k, v in por_tipo.items()}
    return out
