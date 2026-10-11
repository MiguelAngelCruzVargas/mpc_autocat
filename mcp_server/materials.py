"""Cómo se ve cada material CORTADO: la convención de dibujo, no la regla
de un plano.

Un detalle constructivo se lee por sus materiales antes que por sus cotas:
el concreto tiene su textura, la tierra su rayado, la piedra bola son
piedras de verdad, el block cortado un rayado más abierto. Esa convención
es la misma en cualquier detalle -- cimentación, muro de contención, corte
de banqueta, pila de puente -- así que vive acá una sola vez, y cada tool de
alto nivel se COMPONE con estas tres primitivas en vez de repetir
rectángulos con un patrón adivinado:

  - draw_material: un polígono cualquiera (no un rectángulo) con el
    contorno al grosor que le toca y el achurado del material a una escala
    que se calcula a partir de la lámina, no de una constante.
  - fill_stones: empaca piedras irregulares que NO se pisan dentro de
    cualquier contorno cerrado -- piedra bola, mampostería, enrocamiento.
  - soil_section: la masa de terreno alrededor de lo que sea que esté
    enterrado, con la línea del terreno natural y sin el borde exterior
    dibujado, que es como se lee "esto sigue".

Por qué la escala del achurado no puede ser una constante: los patrones de
acad.pat están definidos en pulgadas nominales (ANSI31 raya cada 0.125,
EARTH cada 0.25, AR-B816 es un block de 8x16). Dibujando en metros con
scale=1, ANSI31 raya cada 12.5 cm: en una plantilla de 10 cm entra una sola
línea y el achurado "no se ve" aunque se haya creado bien. Lo que se quiere
es una separación EN PAPEL (1.5-3 mm), y el número que la da depende de la
escala de la lámina: hatch_scale() hace esa cuenta.

Nada de esto sabe qué es una zapata. Sabe cómo se dibuja concreto.
Unidades: las del modelo (metros si se dibuja en metros).
"""
from __future__ import annotations

import math
import random as _random
from typing import Any, Optional

import autocad_client as acad
import geom
import layers
import space

LAYER_DETAIL = "DETALLES"
LAYER_SOIL = "TERRENO-CORTE"

LW_CUT = 50        # contorno de lo cortado: el trazo más grueso del detalle
LW_SEEN = 25       # contorno de lo visto
LW_GROUND = 35     # línea de terreno natural
LW_STONE = 25      # cada piedra
LW_HATCH = 9

# Repetición de cada patrón a scale=1, en unidades de acad.pat. Es lo que
# permite pedir "rayas cada 2 mm de papel" y que salga bien a 1:20 y a
# 1:100. Un patrón que no está acá se toma como módulo 1.0, que es el caso
# de casi todos los AR-* (definidos a tamaño real en pulgadas).
NATIVE_MODULE = {
    "ANSI31": 0.125, "ANSI32": 0.125, "ANSI33": 0.125, "ANSI34": 0.125,
    "ANSI35": 0.125, "ANSI36": 0.125, "ANSI37": 0.125, "ANSI38": 0.125,
    "EARTH": 0.25, "DOTS": 0.25, "NET": 0.125, "LINE": 0.125,
    "AR-CONC": 1.0, "AR-SAND": 1.0, "GRAVEL": 1.0, "INSUL": 1.0,
    "AR-B816": 16.0, "AR-B816C": 16.0, "AR-B88": 8.0,
    "AR-BRSTD": 8.0, "AR-BRELM": 8.0,
    "SOLID": 1.0,
}

# El catálogo. Cada entrada es una convención de dibujo:
#   pattern/paper_mm  : patrón simbólico y su módulo EN PAPEL.
#   real_size         : módulo a tamaño REAL del modelo (mampostería vista:
#                       el block mide 0.40, se dibuja de 0.40).
#   fallback          : si esta instalación no tiene el patrón.
#   procedural        : lo que AutoCAD no trae de fábrica se dibuja pieza
#                       por pieza (piedras).
#   lineweight        : contorno.
MATERIALS: dict[str, dict[str, Any]] = {
    "concreto": {
        "label": "CONCRETO", "pattern": "AR-CONC", "paper_mm": 1.2,
        "angle": 0.0, "fallback": "ANSI31", "fallback_mm": 1.5,
        "lineweight": LW_CUT},
    "concreto_pobre": {
        "label": "CONCRETO POBRE", "pattern": "AR-CONC", "paper_mm": 0.9,
        "angle": 0.0, "fallback": "ANSI37", "fallback_mm": 1.2,
        "lineweight": LW_CUT},
    "block": {
        # Block CORTADO: rayado abierto, no la textura de junta (esa es
        # para el paño visto en fachada, 'block_visto').
        "label": "BLOCK", "pattern": "ANSI31", "paper_mm": 3.0,
        "angle": 0.0, "fallback": "ANSI31", "fallback_mm": 3.0,
        "lineweight": LW_CUT},
    "tabique": {
        "label": "TABIQUE", "pattern": "ANSI31", "paper_mm": 2.0,
        "angle": 0.0, "fallback": "ANSI31", "fallback_mm": 2.0,
        "lineweight": LW_CUT},
    "block_visto": {
        "label": "BLOCK", "pattern": "AR-B816", "real_size": 0.40,
        "angle": 0.0, "fallback": "ANSI31", "fallback_mm": 3.0,
        "lineweight": LW_SEEN},
    "tabique_visto": {
        "label": "TABIQUE", "pattern": "AR-BRSTD", "real_size": 0.24,
        "angle": 0.0, "fallback": "ANSI31", "fallback_mm": 2.0,
        "lineweight": LW_SEEN},
    "tierra": {
        "label": "TERRENO NATURAL", "pattern": "EARTH", "paper_mm": 3.0,
        "angle": 45.0, "fallback": "ANSI31", "fallback_mm": 3.0,
        "lineweight": LW_GROUND, "color": layers.COLOR_SECUNDARIO},
    "relleno": {
        # Relleno compactado: el mismo rayado de tierra en la otra
        # diagonal, para que se distinga del terreno natural.
        "label": "RELLENO COMPACTADO", "pattern": "EARTH", "paper_mm": 2.5,
        "angle": 135.0, "fallback": "ANSI31", "fallback_mm": 3.0,
        "lineweight": LW_SEEN, "color": layers.COLOR_SECUNDARIO},
    "grava": {
        "label": "GRAVA", "pattern": "GRAVEL", "paper_mm": 2.0,
        "angle": 0.0, "fallback": "AR-SAND", "fallback_mm": 1.0,
        "lineweight": LW_SEEN},
    "arena": {
        "label": "ARENA", "pattern": "AR-SAND", "paper_mm": 1.0,
        "angle": 0.0, "fallback": "DOTS", "fallback_mm": 1.0,
        "lineweight": LW_SEEN},
    "acero": {
        "label": "ACERO", "pattern": "ANSI31", "paper_mm": 1.0,
        "angle": 0.0, "fallback": "ANSI31", "fallback_mm": 1.0,
        "lineweight": LW_CUT},
    "aislante": {
        "label": "AISLANTE", "pattern": "INSUL", "paper_mm": 2.0,
        "angle": 0.0, "fallback": "ANSI37", "fallback_mm": 2.0,
        "lineweight": LW_SEEN},
    "piedra_bola": {
        "label": "PIEDRA BOLA", "procedural": "stones", "shape": "redonda",
        "coverage": 0.68, "lineweight": LW_CUT},
    "mamposteria": {
        "label": "MAMPOSTERIA DE PIEDRA", "procedural": "stones",
        "shape": "angulosa", "coverage": 0.80, "lineweight": LW_CUT},
    "ciclopeo": {
        # Concreto con piedra bola embebida: textura de concreto y piedras
        # sueltas, al 35% -- es un concreto con piedra, no un relleno.
        "label": "CONCRETO CICLOPEO", "pattern": "AR-CONC", "paper_mm": 1.2,
        "angle": 0.0, "fallback": "ANSI31", "fallback_mm": 1.5,
        "procedural": "stones", "shape": "redonda", "coverage": 0.35,
        "lineweight": LW_CUT},
}

ALIASES = {
    "concreto_armado": "concreto", "hormigon": "concreto",
    "concrete": "concreto", "plantilla": "concreto_pobre",
    "lean_concrete": "concreto_pobre", "ladrillo": "tabique",
    "brick": "tabique", "cmu": "block", "terreno": "tierra",
    "suelo": "tierra", "earth": "tierra", "soil": "tierra",
    "relleno_compactado": "relleno", "backfill": "relleno",
    "gravel": "grava", "sand": "arena", "steel": "acero",
    "piedra": "piedra_bola", "canto_rodado": "piedra_bola",
    "piedra_braza": "mamposteria", "stone": "mamposteria",
}


def resolve_material(material: Any) -> dict[str, Any]:
    """El material como spec completo, venga del catálogo o inline.

    Un dict se acepta tal cual (con las mismas claves del catálogo), para
    que un material que no está listado no obligue a tocar el código:
    {"pattern": "AR-RROOF", "paper_mm": 2.0} es un material válido.
    """
    if isinstance(material, dict):
        spec = dict(material)
        spec.setdefault("label", str(spec.get("name", "MATERIAL")).upper())
        spec.setdefault("lineweight", LW_CUT)
        spec.setdefault("angle", 0.0)
        if "pattern" not in spec and "procedural" not in spec:
            raise ValueError(
                "Un material inline necesita 'pattern' (nombre de acad.pat) "
                "o 'procedural' ('stones').")
        return spec
    key = str(material or "").strip().lower().replace(" ", "_").replace("-", "_")
    key = ALIASES.get(key, key)
    if key not in MATERIALS:
        raise ValueError(
            f"Material {material!r} desconocido. Los del catálogo: "
            + ", ".join(sorted(MATERIALS)) + ". O pasá un dict inline con "
            "'pattern' y 'paper_mm' (o 'real_size').")
    spec = dict(MATERIALS[key])
    spec["name"] = key
    return spec


# En que unidades estan definidos los patrones de ESTE dibujo. AutoCAD trae
# dos archivos con los mismos nombres: acad.pat (pulgadas: ANSI31 raya cada
# 0.125) y acadiso.pat (milimetros: cada 3.175). Cual usa lo decide la
# plantilla con la que nacio el dibujo (MEASUREMENT), y un dibujo metrico
# (acadiso.dwt, INSUNITS en mm/cm/m) usa el metrico. Misma escala, texturas
# 25.4 veces mas grandes -- se vio en la primera prueba real: AR-CONC a
# 0.024 salia como relleno solido y EARTH como tres rayas sueltas.
#
# Se detecta una vez por dibujo con get_drawing_info (INSUNITS) y se cachea;
# reset() lo olvida al cambiar de documento. set_pattern_units() lo fuerza.
_PATTERN_UNITS: list[Optional[str]] = [None]
_METRIC_UNITS = ("millimeters", "centimeters", "meters", "kilometers",
                 "decimeters", "micrometers", "nanometers")


def reset() -> None:
    _PATTERN_UNITS[0] = None


def set_pattern_units(units: Optional[str]) -> None:
    """'inch' (acad.pat), 'mm' (acadiso.pat) o None para volver a detectar."""
    if units is not None and units not in ("inch", "mm"):
        raise ValueError("pattern_units tiene que ser 'inch', 'mm' o None.")
    _PATTERN_UNITS[0] = units


def pattern_units() -> str:
    if _PATTERN_UNITS[0] is None:
        detectado = "inch"
        try:
            info = acad.call("get_drawing_info", {})
            unidades = str(info.get("units", "")).lower()
            if unidades in _METRIC_UNITS:
                detectado = "mm"
        except (acad.AutoCadError, AttributeError, TypeError):
            pass
        _PATTERN_UNITS[0] = detectado
    return _PATTERN_UNITS[0]


def native_module(pattern: str) -> float:
    """Repetición del patrón a scale=1 EN ESTE DIBUJO."""
    base = NATIVE_MODULE.get(str(pattern).upper(), 1.0)
    return base * (25.4 if pattern_units() == "mm" else 1.0)


def hatch_scale(pattern: str, paper_mm: Optional[float] = None,
                real_size: Optional[float] = None,
                scale: float = 0.0) -> float:
    """El PatternScale que hace que un patrón se repita cada 'paper_mm' de
    papel (o cada 'real_size' unidades del modelo).

    scale: unidades del modelo por mm de papel; 0 toma la de la lámina.
    """
    native = native_module(pattern)
    if real_size and real_size > 0:
        return real_size / native
    mm = paper_mm if paper_mm and paper_mm > 0 else 2.0
    upm = scale if scale and scale > 0 else space.units_per_paper_mm()
    return mm * upm / native


# --------------------------------------------------------------- dibujo

def _layer(name: str, lineweight: int, color: Optional[int] = None) -> None:
    layers.ensure(name, layers.COLOR_PRINCIPAL if color is None else color,
                  lineweight)
    layers.ensure_text_style()


def _poly(points: list, closed: bool, layer: str, lineweight: int,
          bulges: Optional[list[float]] = None,
          color: Optional[int] = None) -> str:
    params: dict[str, Any] = {
        "points": [[float(p[0]), float(p[1])] for p in points],
        "closed": closed, "layer": layer,
        "lineweight": lineweight, "colorIndex": color,
    }
    if bulges:
        params["bulges"] = [float(b) for b in bulges]
    return acad.call("create_polyline", params)["handle"]


def _line(p0, p1, layer: str, lineweight: int,
          color: Optional[int] = None) -> str:
    return acad.call("create_line", {
        "x1": p0[0], "y1": p0[1], "z1": 0.0,
        "x2": p1[0], "y2": p1[1], "z2": 0.0,
        "layer": layer, "lineweight": lineweight, "colorIndex": color,
    })["handle"]


def apply_hatch(handle: str, spec: dict[str, Any], layer: str,
                scale: float = 0.0,
                island_handles: Optional[list[str]] = None,
                color: Optional[int] = None
                ) -> tuple[Optional[str], dict[str, Any], list[str]]:
    """Achura un contorno con el patrón del material, a la escala calibrada.

    Prueba el patrón principal y, si esta instalación no lo tiene, el de
    respaldo. Si NINGUNO sale, lo dice en los avisos: un contorno vacío
    donde tenía que haber concreto es un error que hay que ver, no un None
    silencioso -- así se perdió el achurado de todo un corte de cimentación
    sin que nadie se enterara.
    """
    avisos: list[str] = []
    intentos: list[tuple[str, float, float]] = []
    principal = spec.get("pattern")
    if principal:
        intentos.append((principal, spec.get("paper_mm") or 0.0,
                         spec.get("real_size") or 0.0))
    respaldo = spec.get("fallback")
    if respaldo and respaldo != principal:
        intentos.append((respaldo, spec.get("fallback_mm") or 2.0, 0.0))

    col = color if color is not None else spec.get("color", layers.COLOR_SECUNDARIO)
    if acad.batching():
        # En un lote no hay excepción que atrapar: el respaldo viaja junto y
        # el plugin lo prueba si el principal falla.
        def _params(patron, mm, real):
            return {"boundaryHandle": handle, "pattern": patron,
                    "scale": hatch_scale(patron, mm, real, scale),
                    "angleDeg": float(spec.get("angle", 0.0)), "layer": layer,
                    "islandHandles": island_handles or None,
                    "lineweight": LW_HATCH, "colorIndex": col}
        principal_p = _params(*intentos[0])
        respaldo_p = _params(*intentos[1]) if len(intentos) > 1 else None
        h = acad.call("create_hatch", principal_p, fallback=respaldo_p)["handle"]
        return h, {"pattern": intentos[0][0], "scale": round(principal_p["scale"], 5),
                   "angle": spec.get("angle", 0.0)}, avisos
    ultimo_error = ""
    for patron, mm, real in intentos:
        esc = hatch_scale(patron, mm, real, scale)
        try:
            h = acad.call("create_hatch", {
                "boundaryHandle": handle, "pattern": patron, "scale": esc,
                "angleDeg": float(spec.get("angle", 0.0)), "layer": layer,
                "islandHandles": island_handles or None,
                "lineweight": LW_HATCH, "colorIndex": col,
            })["handle"]
        except acad.AutoCadError as exc:
            ultimo_error = str(exc)
            if patron != principal:
                break
            avisos.append(
                f"El patrón {patron} no está en esta instalación "
                f"({ultimo_error.splitlines()[0][:80]}); se usó {respaldo}.")
            continue
        return h, {"pattern": patron, "scale": round(esc, 5),
                   "angle": spec.get("angle", 0.0)}, avisos
    avisos.append(
        f"NO se pudo achurar con {', '.join(p for p, _, _ in intentos)}: "
        f"{ultimo_error.splitlines()[0][:120] if ultimo_error else 'sin patrón'}. "
        "El contorno quedó vacío -- confirmá el nombre con "
        "list_hatch_patterns y volvé a achurar.")
    return None, {}, avisos


def _normalizar(points: list) -> list[tuple[float, float]]:
    pts = [(float(p[0]), float(p[1])) for p in points]
    if len(pts) >= 2 and math.dist(pts[0], pts[-1]) < 1e-9:
        pts = pts[:-1]
    if len(pts) < 3:
        raise ValueError("Un contorno necesita al menos 3 vértices distintos.")
    return pts


def _bbox(pts: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def draw_material(points: list, material: Any,
                  bulges: Optional[list[float]] = None,
                  layer: Optional[str] = None,
                  lineweight: int = 0,
                  outline: bool = True,
                  hatch: bool = True,
                  scale: float = 0.0,
                  stone_size: Optional[list[float]] = None,
                  seed: int = 4241,
                  island_handles: Optional[list[str]] = None,
                  color_index: Optional[int] = None) -> dict[str, Any]:
    """Un polígono de material cortado: contorno + textura.

    points: los vértices del contorno, en el orden que sea -- una zapata
    trapezoidal, una plantilla, una losa con pendiente, el paño de un muro.
    NO tiene que ser un rectángulo. bulges opcional, uno por vértice.
    material: nombre del catálogo (ver MATERIALS) o dict inline.
    lineweight: 0 toma el del material (cortado 50, visto 25).
    outline=False no dibuja el contorno (solo la textura), para cuando el
    borde ya está trazado por otra pieza.
    scale: unidades del modelo por mm de papel para calibrar la textura; 0
    toma la de la lámina.

    Devuelve el handle del contorno (lo que calculate_area mide para
    cuantificar), el del achurado, la superficie por shoelace, y 'points'
    tal como se dibujó -- eso es lo que soil_section necesita para saber
    dónde cortar la línea de terreno.
    """
    spec = resolve_material(material)
    pts = _normalizar(points)
    lyr = layer or LAYER_DETAIL
    lw = lineweight if lineweight > 0 else int(spec.get("lineweight", LW_CUT))
    _layer(lyr, lw)

    handle = _poly(pts, True, lyr, lw if outline else 5, bulges,
                   color=(color_index if outline else layers.COLOR_TENUE))
    avisos: list[str] = []
    hatch_handle = None
    hatch_info: dict[str, Any] = {}
    stones: dict[str, Any] = {}

    if hatch and spec.get("pattern"):
        hatch_handle, hatch_info, avisos_h = apply_hatch(
            handle, spec, lyr, scale, island_handles)
        avisos.extend(avisos_h)
    if hatch and spec.get("procedural") == "stones":
        stones = fill_stones(pts, stone_size=stone_size,
                             shape=spec.get("shape", "redonda"),
                             coverage=spec.get("coverage"),
                             seed=seed, layer=lyr)
        avisos.extend(stones.get("warnings", []))

    x0, y0, x1, y1 = _bbox(pts)
    space.track(x0, y0, x1, y1, f"material {spec.get('name', spec.get('label'))}")
    return {
        "handle": handle, "hatchHandle": hatch_handle, "hatch": hatch_info,
        "material": spec.get("name", spec.get("label")),
        "label": spec.get("label"),
        "points": [[p[0], p[1]] for p in pts],
        "area": round(geom.polygon_area(pts), 6),
        "perimeter": round(geom.polygon_perimeter(pts), 6),
        "box": [x0, y0, x1, y1],
        "stoneHandles": stones.get("handles", []),
        "stoneCount": stones.get("count", 0),
        "warnings": avisos,
    }


# -------------------------------------------------------------- piedras

def _polys_overlap(a: list[tuple[float, float]],
                   b: list[tuple[float, float]]) -> bool:
    """Dos polígonos convexos chicos se pisan: un vértice de uno adentro
    del otro, o un lado que cruza."""
    for x, y in a:
        if geom.point_in_polygon(x, y, b, 0.0):
            return True
    for x, y in b:
        if geom.point_in_polygon(x, y, a, 0.0):
            return True
    na, nb = len(a), len(b)
    for i in range(na):
        for j in range(nb):
            if geom.segments_cross(a[i], a[(i + 1) % na], b[j], b[(j + 1) % nb]):
                return True
    return False


def _inside(poly: list[tuple[float, float]],
            contour: list[tuple[float, float]]) -> bool:
    """El polígono entra ENTERO en el contorno (vértices adentro y ningún
    lado cruza -- hace falta lo segundo en un contorno cóncavo)."""
    for x, y in poly:
        if not geom.point_in_polygon(x, y, contour, 0.0):
            return False
    n, m = len(poly), len(contour)
    for i in range(n):
        for j in range(m):
            if geom.segments_cross(poly[i], poly[(i + 1) % n],
                                   contour[j], contour[(j + 1) % m]):
                return False
    return True


def fill_stones(points: list,
                stone_size: Optional[Any] = None,
                shape: str = "redonda",
                coverage: Optional[float] = None,
                gap: Optional[float] = None,
                seed: int = 4241,
                layer: Optional[str] = None,
                lineweight: int = LW_STONE,
                max_count: int = 400,
                color_index: Optional[int] = None) -> dict[str, Any]:
    """Empaca piedras irregulares que NO se pisan dentro de un contorno.

    Es la diferencia entre 'unos círculos tirados en una caja' y el bolsón
    de piedra que muestra cualquier detalle real: piedras grandes primero,
    chicas rellenando los huecos, apoyadas unas contra otras con la junta
    de mortero entre ellas, y recortadas al contorno -- que puede ser una
    zanja rectangular, un trapecio, un muro de mampostería inclinado, lo
    que sea.

    stone_size: [min, max] de diámetro en unidades del modelo, o un número
    (el máximo). Sin dato se deriva del contorno: la piedra más grande es
    ~40% de la dimensión menor, que es la proporción de una cimentación de
    piedra bola real (piedras de 15-25 cm en una zanja de 60).
    shape: 'redonda' (canto rodado: lados curvos) o 'angulosa' (piedra
    braza / mampostería: caras planas, junta fina).
    coverage: fracción del área a cubrir (0.68 redonda, 0.80 angulosa).
    gap: junta entre piedras; default proporcional al tamaño.

    Determinista: la misma semilla da el mismo dibujo. Devuelve los handles,
    cuántas entraron y la cobertura real.
    """
    if shape not in ("redonda", "angulosa"):
        raise ValueError("shape tiene que ser 'redonda' o 'angulosa'.")
    contour = _normalizar(points)
    area = geom.polygon_area(contour)
    bx0, by0, bx1, by1 = _bbox(contour)
    min_dim = min(bx1 - bx0, by1 - by0)
    if min_dim <= 0 or area <= 0:
        raise ValueError("El contorno no tiene área.")

    if stone_size is None:
        d_max = min_dim * 0.42
        d_min = d_max * 0.28
    elif isinstance(stone_size, (int, float)):
        d_max = float(stone_size)
        d_min = d_max * 0.28
    else:
        d_min, d_max = sorted(float(v) for v in stone_size[:2])
    if d_max <= 0:
        raise ValueError("stone_size tiene que ser > 0.")

    redonda = shape == "redonda"
    cov = coverage if coverage else (0.68 if redonda else 0.80)
    junta = gap if gap is not None else d_max * (0.02 if redonda else 0.012)
    lyr = layer or LAYER_DETAIL
    _layer(lyr, lineweight)

    avisos: list[str] = []
    if d_max > min_dim * 0.95 or area < d_min * d_min:
        avisos.append(
            f"El hueco ({bx1 - bx0:.2f} x {by1 - by0:.2f}) es más chico que "
            f"una piedra de {d_max:.2f}: no se dibujó ninguna.")
        return {"handles": [], "count": 0, "coverage": 0.0,
                "warnings": avisos}

    rng = _random.Random(seed)
    placed: list[dict[str, Any]] = []
    handles: list[str] = []
    objetivo = cov * area
    lleno = 0.0

    def perfil(d: float) -> dict[str, Any]:
        """Una piedra de diámetro d, relativa a su centro: sus vértices, los
        bulges, y el contorno inflado con el que se prueba el choque."""
        r = d / 2.0
        n = rng.randint(6, 9) if redonda else rng.randint(5, 7)
        angs = sorted(2.0 * math.pi * i / n + rng.uniform(-0.28, 0.28)
                      for i in range(n))
        radios = [r * rng.uniform(0.78, 1.0) for _ in range(n)]
        rel = [(rad * math.cos(a), rad * math.sin(a))
               for a, rad in zip(angs, radios)]
        if redonda:
            bulges = [rng.uniform(0.06, 0.14) for _ in range(n)]
            # El arco sobresale de la cuerda: sagita = bulge * cuerda / 2.
            sagita = max(bg * math.dist(rel[i], rel[(i + 1) % n]) / 2.0
                         for i, bg in enumerate(bulges))
        else:
            bulges = None
            sagita = 0.0
        # La candidata se prueba inflada por la junta entera; las ya
        # puestas se guardan infladas solo por su arco: así la junta entre
        # dos piedras es 'junta', no el doble.
        infl = junta + sagita
        return {
            "rel": rel, "bulges": bulges,
            "propia": [((rad + sagita) * math.cos(a), (rad + sagita) * math.sin(a))
                       for a, rad in zip(angs, radios)],
            "col": [((rad + infl) * math.cos(a), (rad + infl) * math.sin(a))
                    for a, rad in zip(angs, radios)],
            "r_out": max(radios) + infl,
            "r_propio": max(radios) + sagita,
        }

    def entra(pf: dict[str, Any], cx: float, cy: float) -> bool:
        col = [(cx + x, cy + y) for x, y in pf["col"]]
        if not _inside(col, contour):
            return False
        for p in placed:
            if math.dist((cx, cy), p["c"]) >= pf["r_out"] + p["r"]:
                continue
            if _polys_overlap(col, p["col"]):
                return False
        return True

    def poner(pf: dict[str, Any], cx: float, cy: float) -> None:
        nonlocal lleno
        verts = [(cx + x, cy + y) for x, y in pf["rel"]]
        handles.append(_poly(verts, True, lyr, lineweight, pf["bulges"],
                             color=color_index))
        placed.append({"c": (cx, cy), "r": pf["r_propio"],
                       "col": [(cx + x, cy + y) for x, y in pf["propia"]]})
        lleno += geom.polygon_area(verts)

    # --- 1. Caída: cada piedra cae por una columna al azar hasta apoyar
    #        sobre el fondo o sobre otra. Es lo que empaca como un bolsón
    #        real (piedras apoyadas unas en otras) en vez de flotar, y lo
    #        que sube la cobertura muy por encima de tirarlas al azar.
    seguidos = 0
    intentos = 0
    while lleno < objetivo and len(placed) < max_count             and intentos < 4000 and seguidos < 200:
        intentos += 1
        seguidos += 1
        d = rng.uniform(d_min, d_max) ** 0.5 * math.sqrt(d_max)  # sesgo a grandes
        d = min(max(d, d_min), d_max)
        pf = perfil(d)
        cx = rng.uniform(bx0 + d * 0.3, bx1 - d * 0.3)
        # Barrido grueso hacia arriba hasta el primer sitio libre, y
        # despues biseccion hacia abajo para apoyarla de verdad: asi queda
        # tocando lo de abajo sin pagar un barrido fino completo.
        paso = d * 0.15
        cy = by0 + d * 0.3
        tope = by1 - d * 0.3
        apoyo = None
        while cy <= tope:
            if entra(pf, cx, cy):
                apoyo = cy
                break
            cy += paso
        if apoyo is None:
            continue
        lo_y, hi_y = apoyo - paso, apoyo
        for _ in range(5):
            mid = (lo_y + hi_y) / 2.0
            if entra(pf, cx, mid):
                hi_y = mid
            else:
                lo_y = mid
        poner(pf, cx, hi_y)
        seguidos = 0

    # --- 2. Relleno de huecos: piedras chicas donde quedó lugar, sin
    #        caída, probando más chica en el mismo sitio si no entra.
    seguidos = 0
    intentos = 0
    while lleno < objetivo and len(placed) < max_count             and intentos < 3000 and seguidos < 500:
        intentos += 1
        seguidos += 1
        d = rng.uniform(d_min, d_max * 0.55)
        cx = rng.uniform(bx0 + d_min / 2.0, bx1 - d_min / 2.0)
        cy = rng.uniform(by0 + d_min / 2.0, by1 - d_min / 2.0)
        while d >= d_min:
            pf = perfil(d)
            if entra(pf, cx, cy):
                poner(pf, cx, cy)
                seguidos = 0
                break
            d *= 0.75

    cobertura = lleno / area if area > 0 else 0.0
    if cobertura < cov * 0.6:
        avisos.append(
            f"Solo se llegó al {cobertura:.0%} de cobertura (se pedía "
            f"{cov:.0%}): el hueco es angosto para piedras de "
            f"{d_min:.2f}-{d_max:.2f}. Bajá stone_size si tiene que verse "
            "más lleno.")
    return {"handles": handles, "count": len(handles),
            "coverage": round(cobertura, 3),
            "stoneSize": [round(d_min, 4), round(d_max, 4)],
            "warnings": avisos}


# --------------------------------------------------------------- terreno

def _cruces_horizontal(pts: list[tuple[float, float]],
                       y: float) -> list[float]:
    """Las x donde una horizontal a altura y corta los lados del polígono."""
    xs: list[float] = []
    n = len(pts)
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            xs.append(x0 + (y - y0) * (x1 - x0) / (y1 - y0))
    return xs


def soil_section(x0: float, x1: float, ground_level: float, bottom: float,
                 islands: Optional[list[dict[str, Any]]] = None,
                 material: Any = "tierra",
                 ground_extension: Optional[float] = None,
                 ground_line: bool = True,
                 scale: float = 0.0,
                 layer: Optional[str] = None,
                 lineweight: int = LW_GROUND,
                 color_index: Optional[int] = None) -> dict[str, Any]:
    """La masa de terreno alrededor de lo que esté enterrado.

    Sin esto un corte de cimentación se lee como piezas de concreto
    flotando. Pero dibujarlo como una CAJA cerrada alrededor tampoco sirve:
    la caja se lee como otra pieza. Lo que hace un corte de obra es
    achurar el terreno hasta el borde de cada pieza (islas), trazar la
    línea del terreno natural que sigue hacia los dos lados, y NO dibujar
    el borde exterior de la masa -- el contorno se usa para achurar y se
    borra.

    x0..x1 / bottom..ground_level: la zona de terreno que se muestra.
    islands: lo que desplaza tierra -- los dicts que devuelve
    draw_material (necesita 'handle' y 'points'). Todo lo demás dentro de
    la zona es terreno. La línea de terreno se interrumpe donde una pieza
    sale del suelo (el muro), y pasa de largo sobre lo que termina justo
    en el nivel (la cadena).
    ground_extension: cuánto sigue la línea de terreno más allá de la zona
    achurada, a cada lado.
    """
    if x1 <= x0:
        raise ValueError("x1 tiene que ser mayor que x0.")
    if ground_level <= bottom:
        raise ValueError("ground_level tiene que estar por encima de bottom.")
    spec = resolve_material(material)
    lyr = layer or LAYER_SOIL
    _layer(lyr, lineweight, spec.get("color"))
    avisos: list[str] = []

    dentro: list[dict[str, Any]] = []
    for isla in islands or []:
        pts = isla.get("points")
        if not isla.get("handle") or not pts:
            continue
        ix0, iy0, ix1, iy1 = _bbox(_normalizar(pts))
        if ix1 <= x0 or ix0 >= x1 or iy1 <= bottom or iy0 >= ground_level:
            continue     # afuera de la masa: no puede ser isla
        dentro.append(isla)

    # El contorno de la masa, solo para achurar.
    rect = _poly([(x0, bottom), (x1, bottom), (x1, ground_level),
                  (x0, ground_level)], True, lyr, 5, color=layers.COLOR_TENUE)
    hatch_handle, hatch_info, avisos_h = apply_hatch(
        rect, spec, lyr, scale, [i["handle"] for i in dentro],
        color=color_index)
    avisos.extend(avisos_h)
    borrado = False
    try:
        acad.call("delete_entity", {"handle": rect})
        borrado = True
    except acad.AutoCadError as exc:
        avisos.append(
            "No se pudo borrar el contorno auxiliar del terreno "
            f"({str(exc)[:80]}): quedó como línea fina gris, borralo a mano.")

    # La línea de terreno natural, cortada donde algo sale del suelo.
    ext = ground_extension if ground_extension is not None else (x1 - x0) * 0.15
    gl_handles: list[str] = []
    if ground_line:
        huecos: list[tuple[float, float]] = []
        for isla in islands or []:
            pts = _normalizar(isla["points"])
            _, iy0, _, iy1 = _bbox(pts)
            if iy1 > ground_level + 1e-6 and iy0 <= ground_level + 1e-6:
                xs = _cruces_horizontal(pts, ground_level + 1e-6)
                if len(xs) >= 2:
                    huecos.append((min(xs), max(xs)))
        huecos.sort()
        cursor = x0 - ext
        fin = x1 + ext
        for a, b in huecos:
            if a > cursor + 1e-9:
                gl_handles.append(_line((cursor, ground_level),
                                        (min(a, fin), ground_level), lyr,
                                        lineweight, color_index))
            cursor = max(cursor, b)
        if cursor < fin - 1e-9:
            gl_handles.append(_line((cursor, ground_level), (fin, ground_level),
                                    lyr, lineweight, color_index))

    space.track(x0 - ext, bottom, x1 + ext, ground_level, "terreno")
    return {"hatchHandle": hatch_handle, "hatch": hatch_info,
            "groundLineHandles": gl_handles,
            "boundaryDeleted": borrado,
            "boundaryHandle": None if borrado else rect,
            "islands": len(dentro),
            "box": [x0 - ext, bottom, x1 + ext, ground_level],
            "warnings": avisos}
