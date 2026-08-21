"""Reglas de proyecto arquitectónico, verificadas antes de dibujar.

Un plano puede estar impecable de dibujo y ser inconstruible: una puerta de
calle que abre a una recámara, un baño principal que da al pasillo, un patio de
servicio al que solo se llega cruzando un dormitorio. Eso no se ve mirando la
geometría — hay que preguntárselo al proyecto.

Acá viven esas reglas, para que el chequeo no dependa de que alguien se acuerde.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import space

# Ambientes a los que una puerta de calle NUNCA debe abrir directo.
PRIVADOS = ("recamara", "recámara", "dormitorio", "baño", "bano", "closet",
            "clóset", "vestidor")
# Espacios que sí pueden recibir el acceso exterior.
SOCIALES = ("sala", "comedor", "estar", "vestibulo", "vestíbulo", "recibidor",
            "hall", "cocina")
SERVICIO = ("patio", "lavado", "servicio", "tendido")


def _clase(nombre: str) -> str:
    n = nombre.lower()
    if any(p in n for p in ("baño", "bano")):
        return "bano"
    if any(p in n for p in ("recamara", "recámara", "dormitorio")):
        return "recamara"
    if any(p in n for p in SERVICIO):
        return "servicio"
    if any(p in n for p in ("pasillo", "circulacion", "circulación", "distribuidor")):
        return "circulacion"
    if any(p in n for p in SOCIALES):
        return "social"
    return "otro"


def _es_privado(nombre: str) -> bool:
    return _clase(nombre) in ("recamara", "bano")


def check_layout(rooms: list[dict[str, Any]],
                 doors: list[dict[str, Any]],
                 lot_width: Optional[float] = None,
                 lot_depth: Optional[float] = None,
                 windows: Optional[list[dict[str, Any]]] = None
                 ) -> dict[str, Any]:
    """Verifica las reglas de zonificación de una planta ANTES de dibujarla.

    rooms: [{"name": "SALA", "x0":.., "y0":.., "x1":.., "y1":..}]
    doors: [{"from": "EXTERIOR", "to": "VESTIBULO", "width": 0.90}]
           'from' = "EXTERIOR" marca la puerta de acceso desde la calle.
    windows: [{"room": "SALA", "wall": "izquierda"}] para revisar colindancias.

    Devuelve ok y una lista de problemas, cada uno con la regla que viola y qué
    habría que cambiar. No dibuja nada.
    """
    problemas: list[dict[str, str]] = []
    nombres = {r["name"].upper(): r for r in rooms}

    # --- 1. El acceso exterior no puede dar a un privado ---
    accesos = [d for d in doors
               if str(d.get("from", "")).upper() in ("EXTERIOR", "CALLE", "FACHADA")]
    if not accesos:
        problemas.append({
            "rule": "acceso",
            "problem": "No hay ninguna puerta marcada como acceso exterior.",
            "fix": "Marcá la puerta de calle con from='EXTERIOR'."})
    for d in accesos:
        destino = str(d.get("to", ""))
        if _es_privado(destino):
            problemas.append({
                "rule": "acceso",
                "problem": f"El acceso desde la calle abre a '{destino}', que es "
                           f"un espacio privado.",
                "fix": "La puerta de calle tiene que desembocar en sala, comedor "
                       "o vestíbulo. Moové el acceso o interponé un recibidor."})

    # --- 2. El baño principal va DENTRO de la recámara principal ---
    banos = [r["name"] for r in rooms if _clase(r["name"]) == "bano"]
    principal = next((r["name"] for r in rooms
                      if "principal" in r["name"].lower()
                      and _clase(r["name"]) == "recamara"), None)
    bano_ppal = next((b for b in banos if "principal" in b.lower()
                      or "suite" in b.lower()), None)
    if bano_ppal and principal:
        entra_de = [str(d.get("from", "")) for d in doors
                    if str(d.get("to", "")).upper() == bano_ppal.upper()]
        if entra_de and not any(principal.upper() == e.upper() for e in entra_de):
            problemas.append({
                "rule": "bano en suite",
                "problem": f"'{bano_ppal}' se entra desde {entra_de}, no desde "
                           f"'{principal}'.",
                "fix": "Un baño principal es en-suite: su única puerta abre "
                       "dentro de la recámara principal."})

    # --- 3. Al servicio no se entra por un dormitorio ---
    for r in rooms:
        if _clase(r["name"]) != "servicio":
            continue
        entra_de = [str(d.get("from", "")) for d in doors
                    if str(d.get("to", "")).upper() == r["name"].upper()]
        privados = [e for e in entra_de if _es_privado(e)]
        if privados:
            problemas.append({
                "rule": "acceso a servicio",
                "problem": f"A '{r['name']}' solo se llega cruzando {privados}.",
                "fix": "El patio de servicio se entra desde la cocina o desde "
                       "una circulación común."})

    # --- 4. Todo ambiente tiene que ser accesible ---
    conectados = set()
    for d in doors:
        conectados.add(str(d.get("from", "")).upper())
        conectados.add(str(d.get("to", "")).upper())
    for r in rooms:
        if r["name"].upper() not in conectados:
            problemas.append({
                "rule": "accesibilidad",
                "problem": f"'{r['name']}' no tiene ninguna puerta ni vano.",
                "fix": "Todo ambiente necesita al menos un acceso."})

    # --- 5. La cocina tiene que ver al comedor ---
    cocina = next((r["name"] for r in rooms if "cocina" in r["name"].lower()), None)
    if cocina:
        vecinos = set()
        for d in doors:
            a, b = str(d.get("from", "")).upper(), str(d.get("to", "")).upper()
            if a == cocina.upper():
                vecinos.add(b)
            elif b == cocina.upper():
                vecinos.add(a)
        if not any("COMEDOR" in v or "SALA" in v for v in vecinos):
            problemas.append({
                "rule": "cocina-comedor",
                "problem": f"'{cocina}' no comunica con el comedor "
                           f"(da a {sorted(vecinos) or 'nada'}).",
                "fix": "La cocina necesita relación directa con el comedor, y no "
                       "quedar como paso entre recámaras."})

    # --- 6. Ventanas sobre la colindancia ---
    if windows and lot_width and lot_depth:
        for w in windows:
            muro = str(w.get("wall", "")).lower()
            if muro in ("izquierda", "left", "derecha", "right", "fondo", "back"):
                problemas.append({
                    "rule": "colindancia",
                    "problem": f"Ventana de '{w.get('room','?')}' sobre el muro "
                               f"{muro}, que es límite de predio.",
                    "fix": "En colindancia no se abren vanos salvo patio de luz "
                           "o retiro reglamentario. Pasala a fachada o al patio."})

    return {
        "ok": not problemas,
        "problems": problemas,
        "count": len(problemas),
        "message": ("La distribución cumple las reglas de zonificación."
                    if not problemas else
                    f"{len(problemas)} problema(s) de proyecto: "
                    + "; ".join(p["problem"] for p in problemas)),
    }


# ------------------------------------------- dimensiones minimas habitables

# Lado y superficie por debajo de los cuales el recinto no se puede usar.
MINIMOS = {
    "recamara": {"lado": 2.40, "area": 7.00, "nombre": "recámara"},
    "bano":     {"lado": 1.10, "area": 2.20, "nombre": "baño"},
    "social":   {"lado": 2.40, "area": 8.00, "nombre": "espacio social"},
    "circulacion": {"lado": 0.90, "area": 0.00, "nombre": "circulación"},
    "servicio": {"lado": 1.20, "area": 2.00, "nombre": "área de servicio"},
}


def _solapan(a: dict[str, Any], b: dict[str, Any], tol: float = 0.01) -> float:
    """Superficie en la que dos recintos se pisan."""
    dx = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
    dy = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
    if dx <= tol or dy <= tol:
        return 0.0
    return dx * dy


def _en_frontera(puerta: dict[str, Any], a: dict[str, Any], b: dict[str, Any],
                 tol: float = 0.35) -> bool:
    """¿La puerta cae sobre el muro que separa esos dos recintos?"""
    if "x" not in puerta or "y" not in puerta:
        return True          # sin posicion declarada no hay nada que verificar
    px, py = float(puerta["x"]), float(puerta["y"])

    def toca(r: dict[str, Any]) -> bool:
        return (r["x0"] - tol <= px <= r["x1"] + tol
                and r["y0"] - tol <= py <= r["y1"] + tol)

    return toca(a) and toca(b)


def check_geometry(rooms: list[dict[str, Any]],
                   doors: list[dict[str, Any]]) -> dict[str, Any]:
    """Verifica que los recintos sean coherentes y construibles.

    check_layout revisa el GRAFO de accesos —quién comunica con quién— pero no
    que el dibujo lo cumpla. Se puede declarar "PASILLO -> BAÑO" y dibujar esa
    puerta en un muro que no toca el baño: el grafo da por buena la conexión y
    el baño queda sellado. Esto revisa la geometría.
    """
    problemas: list[dict[str, str]] = []
    por_nombre = {r["name"].upper(): r for r in rooms}

    # --- 1. Dimensiones minimas segun el uso ---
    for r in rooms:
        w = float(r["x1"]) - float(r["x0"])
        h = float(r["y1"]) - float(r["y0"])
        area = w * h
        m = MINIMOS.get(_clase(r["name"]))
        if not m:
            continue
        lado_menor = min(w, h)
        if lado_menor < m["lado"] - 1e-6:
            problemas.append({
                "rule": "dimension minima",
                "problem": f"'{r['name']}' mide {w:.2f} x {h:.2f} m: el lado "
                           f"menor ({lado_menor:.2f} m) no llega al mínimo de "
                           f"{m['lado']:.2f} m para una {m['nombre']}.",
                "fix": f"Una {m['nombre']} de {lado_menor:.2f} m de lado no se "
                       "puede usar. Reacomodá la distribución."})
        elif area < m["area"] - 1e-6:
            problemas.append({
                "rule": "superficie minima",
                "problem": f"'{r['name']}' tiene {area:.2f} m2, por debajo de "
                           f"{m['area']:.2f} m2 para una {m['nombre']}.",
                "fix": "Agrandá el recinto o cambiale el uso."})

    # --- 2. Recintos que se pisan ---
    for i, a in enumerate(rooms):
        for b in rooms[i + 1:]:
            s = _solapan(a, b)
            if s > 0.05:
                problemas.append({
                    "rule": "solape",
                    "problem": f"'{a['name']}' y '{b['name']}' se superponen en "
                               f"{s:.2f} m2.",
                    "fix": "Dos recintos no pueden ocupar el mismo espacio."})

    # --- 3. Puertas duplicadas entre el mismo par ---
    pares: dict[tuple, int] = {}
    for d in doors:
        par = tuple(sorted((str(d.get("from", "")).upper(),
                            str(d.get("to", "")).upper())))
        pares[par] = pares.get(par, 0) + 1
    for par, n in pares.items():
        if n > 1:
            problemas.append({
                "rule": "puerta duplicada",
                "problem": f"Hay {n} puertas entre {par[0]} y {par[1]}.",
                "fix": "Dos recintos se comunican con UN vano."})

    # --- 4. La puerta tiene que caer en la frontera comun ---
    for d in doors:
        origen = str(d.get("from", "")).upper()
        destino = str(d.get("to", "")).upper()
        if origen in ("EXTERIOR", "CALLE", "FACHADA"):
            continue
        a, b = por_nombre.get(origen), por_nombre.get(destino)
        if not a or not b:
            problemas.append({
                "rule": "puerta huerfana",
                "problem": f"La puerta {origen} -> {destino} menciona un recinto "
                           "que no está en la lista.",
                "fix": "Los nombres tienen que coincidir con los de 'rooms'."})
            continue

        dx = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
        dy = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
        if dx < -0.35 or dy < -0.35:
            problemas.append({
                "rule": "puerta imposible",
                "problem": f"'{origen}' y '{destino}' no se tocan, y se declaró "
                           "una puerta entre ellos.",
                "fix": "No comparten muro: el recinto va a quedar sellado. "
                       "Revisá la distribución."})
        elif not _en_frontera(d, a, b):
            problemas.append({
                "rule": "puerta fuera de lugar",
                "problem": f"La puerta {origen} -> {destino} está en "
                           f"({d.get('x')}, {d.get('y')}), fuera del muro que "
                           "los separa.",
                "fix": "Poné el vano sobre la frontera común; si no, el recinto "
                       "queda sellado aunque la puerta figure en el grafo."})

    return {
        "ok": not problemas,
        "problems": problemas,
        "count": len(problemas),
        "message": ("La geometría de los recintos es coherente."
                    if not problemas else
                    f"{len(problemas)} problema(s) de geometría: "
                    + "; ".join(p["problem"] for p in problemas)),
    }


# ------------------------------------------------ coherencia de la muraria

def _dist_punto_segmento(p, a, b) -> float:
    """Distancia de un punto al segmento a-b."""
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    largo2 = dx * dx + dy * dy
    if largo2 < 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / largo2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def check_walls(walls: list[dict[str, Any]],
                tolerance: float = 0.05,
                min_length: float = 0.40) -> dict[str, Any]:
    """Verifica que la muraria cierre: sin extremos al aire ni tramos sueltos.

    Un muro que muere en el aire —el clásico espolón en "L" que estrangula un
    paso— es válido como geometría y no se construye. Tampoco se ve en el grafo
    de ambientes ni lo detecta la unión booleana, que solo limpia los cruces.

    walls: [{"points": [[x,y], [x,y], ...], "name": "muro cocina"}] con los EJES
    de cada muro, los mismos que se le pasan a create_walls.

    Revisa, para cualquier tipo de planta:
      - extremos libres: un arranque o final que no toca ningún otro muro
      - tramos por debajo del mínimo constructivo
      - muros duplicados o superpuestos sobre el mismo eje

    tolerance: cuánto puede faltar para considerar que dos muros se tocan.
    """
    problemas: list[dict[str, str]] = []

    segmentos = []       # (indice_muro, nombre, p0, p1)
    extremos = []        # (indice_muro, nombre, punto, "inicio"/"final")
    for i, w in enumerate(walls):
        pts = [(float(p[0]), float(p[1])) for p in w.get("points", [])]
        nombre = w.get("name") or f"muro #{i + 1}"
        if len(pts) < 2:
            problemas.append({
                "rule": "muro invalido",
                "problem": f"'{nombre}' tiene menos de 2 puntos.",
                "fix": "Un muro necesita al menos un tramo."})
            continue

        for a, b in zip(pts, pts[1:]):
            largo = math.hypot(b[0] - a[0], b[1] - a[1])
            if largo < min_length:
                problemas.append({
                    "rule": "tramo corto",
                    "problem": f"'{nombre}' tiene un tramo de {largo:.2f} m, por "
                               f"debajo de {min_length:.2f} m.",
                    "fix": "Un tramo así no se levanta en obra: llevalo hasta la "
                           "esquina o eliminalo."})
            segmentos.append((i, nombre, a, b))

        # Una polilinea cerrada no tiene extremos libres: su arranque y su
        # final son el mismo punto. Reportarlos seria un falso positivo, y un
        # validador que grita de mas enseña a ignorar los avisos.
        cerrado = math.hypot(pts[-1][0] - pts[0][0],
                             pts[-1][1] - pts[0][1]) <= tolerance
        if not cerrado:
            extremos.append((i, nombre, pts[0], "arranque"))
            extremos.append((i, nombre, pts[-1], "final"))

    # --- extremos que no tocan ningun otro muro ---
    for idx, nombre, punto, cual in extremos:
        toca = False
        for j, _, a, b in segmentos:
            # Los tramos del propio muro que arrancan o terminan en ese punto
            # no cuentan como apoyo: es el muro sosteniendose a si mismo.
            if j == idx:
                propio_extremo = (
                    math.hypot(punto[0] - a[0], punto[1] - a[1]) <= tolerance
                    or math.hypot(punto[0] - b[0], punto[1] - b[1]) <= tolerance)
                if propio_extremo:
                    continue
            if _dist_punto_segmento(punto, a, b) <= tolerance:
                toca = True
                break
        if not toca:
            problemas.append({
                "rule": "muro huerfano",
                "problem": f"El {cual} de '{nombre}' en "
                           f"({punto[0]:.2f}, {punto[1]:.2f}) no toca ningún otro "
                           "muro: queda al aire.",
                "fix": "Prolongalo hasta el muro perimetral o hasta el divisorio "
                       "vecino. Un muro que muere en el aire no se construye."})

    # --- muros superpuestos sobre el mismo eje ---
    for i in range(len(segmentos)):
        ia, na, a0, a1 = segmentos[i]
        for j in range(i + 1, len(segmentos)):
            ib, nb, b0, b1 = segmentos[j]
            if ia == ib:
                continue
            # Superpuestos: los dos extremos de uno caen sobre el otro.
            if (_dist_punto_segmento(b0, a0, a1) <= tolerance
                    and _dist_punto_segmento(b1, a0, a1) <= tolerance):
                problemas.append({
                    "rule": "muro duplicado",
                    "problem": f"'{nb}' se superpone con '{na}' sobre el mismo eje.",
                    "fix": "Hay dos muros dibujados en el mismo lugar: dejá uno."})

    return {
        "ok": not problemas,
        "problems": problemas,
        "count": len(problemas),
        "walls": len(walls),
        "segments": len(segmentos),
        "message": ("La muraria cierra: sin extremos al aire ni tramos sueltos."
                    if not problemas else
                    f"{len(problemas)} problema(s) en los muros: "
                    + "; ".join(p["problem"] for p in problemas)),
    }


# --------------------------------------------- el aparato de anotacion

def check_annotations(items: Optional[list[dict[str, Any]]] = None,
                      tolerance: float = 1e-6) -> dict[str, Any]:
    """Que las cotas, las burbujas y los rotulos no se pisen entre si.

    Los otros check_* miran el proyecto; este mira el plano como dibujo. Es el
    problema que no se ve hasta abrir el DWG: la cadena de cotas generales
    cruzando la fila de burbujas de eje, o dos cotas en el mismo nivel.

    Cada tool de anotacion reserva la franja que ocupa (ver space.py), asi que
    normalmente esto sale limpio solo. Da problemas cuando algo se ubico a
    mano con create_dimension o create_text eligiendo el offset de memoria.

    items: rectangulos extra a verificar SIN dibujarlos, para preguntar antes
    de ubicar algo a mano: [{"x0":.., "y0":.., "x1":.., "y1":.., "what":".."}].
    """
    extra = []
    for i, it in enumerate(items or []):
        try:
            extra.append({"x0": min(float(it["x0"]), float(it["x1"])),
                          "y0": min(float(it["y0"]), float(it["y1"])),
                          "x1": max(float(it["x0"]), float(it["x1"])),
                          "y1": max(float(it["y0"]), float(it["y1"])),
                          "what": str(it.get("what", f"item {i + 1}"))})
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"El item {i + 1} necesita x0, y0, x1, y1 numericos. ({exc})")

    choques = space.overlaps(extra, tolerance)
    problemas = [{
        "rule": "anotacion encimada",
        "problem": (f"'{c['a']}' y '{c['b']}' se pisan en "
                    f"{c['overlapX']:.2f} x {c['overlapY']:.2f}."),
        "fix": ("Usa create_dimension_chain sin offset y la cadena se apila "
                "sola afuera de lo que ya haya; si el offset va a mano, "
                "sacala mas afuera."),
        "box": c["box"],
    } for c in choques]

    franjas = space.bands()
    return {
        "ok": not problemas,
        "problems": problemas,
        "count": len(problemas),
        "bands": franjas,
        "message": (f"El margen esta limpio: {len(franjas)} franja(s) de "
                    "anotacion sin encimarse."
                    if not problemas else
                    f"{len(problemas)} encimadura(s): "
                    + "; ".join(p["problem"] for p in problemas)),
    }


# ------------------------------------------------------- muro de contencion

def check_retaining_wall(height: float,
                         soil_unit_weight: float = 1800.0,
                         friction_angle_deg: float = 30.0,
                         surcharge: float = 0.0,
                         concrete_unit_weight: float = 2400.0,
                         friction_coefficient: float = 0.5,
                         min_fs_overturning: float = 1.5,
                         min_fs_sliding: float = 1.5,
                         stem_thickness: Optional[float] = None,
                         footing_thickness: Optional[float] = None,
                         max_base_width: Optional[float] = None) -> dict[str, Any]:
    """Proporción PRELIMINAR de un muro de contención por empuje activo de
    Rankine, para el paso ANTES de dibujar -- un muro de 3.5 m de tierra no
    se resuelve con la misma pared de 15 cm de un tabique interior, pero
    hasta ahora esta biblioteca no tenía forma de decir CUÁNTO ancho de base
    hace falta: quien pedía el dibujo terminaba poniendo una proporción a
    ojo, sin ninguna cuenta atrás que la respalde.

    Modelo: cantiléver en T, vástago apoyado a un tercio de la base desde el
    paño (talón = 2/3 de la base, del lado de la tierra retenida) -- la
    proporción de libro de texto para este tipo de muro. El talón cuenta con
    el peso de la tierra que carga encima para resistir el volteo, que es
    la diferencia entre un resultado defendible y uno que no: un muro de
    gravedad puro (sin talón, solo el concreto) necesita una base
    absurdamente ancha porque le falta ese peso -- la primera versión de
    este chequeo lo hacía así y daba 12.68 m de base para 3.5 m de altura,
    un número que ningún ingeniero construiría. Sigue siendo conservador
    (ignora el empuje pasivo del lado del paño y cualquier diente de
    cortante), pero no al punto de ser inútil. El resultado es un chequeo
    PRELIMINAR de proporción -- no reemplaza el estudio de mecánica de
    suelos del proyecto ni el diseño a flexión/cortante del vástago y la
    zapata.

    height: altura de tierra retenida, del desplante (base de la zapata) a
    la corona del muro, en metros.
    soil_unit_weight: peso volumétrico del suelo retenido, kg/m3 (1800 es un
    relleno compactado típico; bajalo si el suelo es más suelto).
    friction_angle_deg: ángulo de fricción interna del suelo (30° es un
    valor conservador típico sin estudio de mecánica de suelos).
    surcharge: sobrecarga uniforme sobre el relleno, kg/m2 (una banqueta,
    una cochera encima) -- 0 si no hay nada cargando por arriba.
    concrete_unit_weight: peso volumétrico del concreto, kg/m3 (2400 típico).
    friction_coefficient: fricción concreto-suelo en la base, para el
    deslizamiento (0.5 es un valor conservador usual).
    min_fs_overturning / min_fs_sliding: factores de seguridad mínimos
    exigidos (1.5 es lo habitual en un chequeo preliminar).
    stem_thickness / footing_thickness: si no se pasan, arrancan en H/12
    (mínimo 0.20 m) -- la proporción usual para un muro de esta altura.
    max_base_width: tope de ancho de base a probar antes de rendirse y
    avisar que no cierra con estas proporciones (por default, sin tope).

    Devuelve 'ok', las dimensiones que SÍ cumplen los dos factores de
    seguridad (baseWidth, stemThickness, footingThickness), el empuje activo
    y el momento de volteo con los que se calculó, y 'method' explicando el
    modelo -- para que quien lea el plano pueda verificar la cuenta, no solo
    confiar en el número."""
    if height <= 0:
        raise ValueError("height tiene que ser mayor que 0.")

    phi = math.radians(friction_angle_deg)
    ka = math.tan(math.pi / 4.0 - phi / 2.0) ** 2

    empuje_suelo = 0.5 * ka * soil_unit_weight * height ** 2
    empuje_sobrecarga = ka * surcharge * height
    empuje_total = empuje_suelo + empuje_sobrecarga
    momento_volteo = empuje_suelo * (height / 3.0) + empuje_sobrecarga * (height / 2.0)

    ts = stem_thickness if stem_thickness is not None else max(0.20, round(height / 12.0, 2))
    tf = footing_thickness if footing_thickness is not None else max(0.20, round(height / 12.0, 2))
    base = max(0.90, round(0.55 * height, 2))
    if max_base_width is not None:
        # Si la semilla ya se pasa del tope, arrancar directo en el tope: lo
        # que importa es si el tope alcanza, no un valor que ni se puede
        # construir.
        base = min(base, max_base_width)

    # Vastago a un tercio de la base desde el paño (el toe, del lado de
    # afuera); el resto, menos el propio espesor del vastago, es el talon
    # que queda del lado de la tierra retenida.
    toe_ratio = 1.0 / 3.0
    altura_suelo_talon = height - tf
    toe = heel = 0.0
    fs_volteo = fs_deslizamiento = 0.0
    for _ in range(400):
        toe = base * toe_ratio
        heel = max(0.0, base - ts - toe)
        peso_vastago = ts * altura_suelo_talon * concrete_unit_weight
        peso_zapata = base * tf * concrete_unit_weight
        peso_talon = heel * altura_suelo_talon * soil_unit_weight
        n = peso_vastago + peso_zapata + peso_talon
        # Momentos resistentes respecto del paño (x=0, el borde de afuera).
        momento_resistente = (peso_zapata * (base / 2.0)
                              + peso_vastago * (toe + ts / 2.0)
                              + peso_talon * (base - heel / 2.0))
        fs_volteo = (momento_resistente / momento_volteo) if momento_volteo > 0 else float("inf")
        fs_deslizamiento = ((friction_coefficient * n) / empuje_total) if empuje_total > 0 else float("inf")
        if fs_volteo >= min_fs_overturning and fs_deslizamiento >= min_fs_sliding:
            break
        if max_base_width is not None and base >= max_base_width:
            break
        base = round(base + 0.05, 2)

    ok = fs_volteo >= min_fs_overturning and fs_deslizamiento >= min_fs_sliding
    problemas: list[dict[str, str]] = []
    if not ok:
        if fs_volteo < min_fs_overturning:
            problemas.append({
                "rule": "volteo",
                "problem": f"Con base de {base:.2f} m el factor de seguridad al "
                           f"volteo da {fs_volteo:.2f}, por debajo de "
                           f"{min_fs_overturning:g}.",
                "fix": "Subí max_base_width para seguir probando, agregá un "
                       "talón real con el peso de la tierra encima (este "
                       "chequeo es conservador y no lo cuenta), o bajá la "
                       "altura retenida."})
        if fs_deslizamiento < min_fs_sliding:
            problemas.append({
                "rule": "deslizamiento",
                "problem": f"El factor de seguridad al deslizamiento da "
                           f"{fs_deslizamiento:.2f}, por debajo de "
                           f"{min_fs_sliding:g}.",
                "fix": "Agregá un diente o llave de cortante en la base, o "
                       "subí friction_coefficient si hay dato real del "
                       "estudio de suelos."})

    return {
        "ok": ok,
        "problems": problemas,
        "ka": round(ka, 4),
        "activeThrust_kg_per_m": round(empuje_total, 1),
        "overturningMoment_kgm_per_m": round(momento_volteo, 1),
        "baseWidth": base,
        "stemThickness": ts,
        "footingThickness": tf,
        "toeLength": round(toe, 2),
        "heelLength": round(heel, 2),
        "fsOverturning": round(fs_volteo, 2),
        "fsSliding": round(fs_deslizamiento, 2),
        "method": ("Rankine, cantiléver en T con el vástago a base/3 del "
                   "paño y el talón cargando el peso de la tierra que tiene "
                   "encima -- conservador: ignora el empuje pasivo del lado "
                   "del paño y cualquier diente de cortante. Chequeo "
                   "PRELIMINAR de proporción, no reemplaza el estudio de "
                   "mecánica de suelos ni el diseño a flexión/cortante del "
                   "vástago y la zapata."),
    }


# ------------------------------------------------------- zapata aislada

def check_footing(axial_load: float,
                  column_width: float = 0.30,
                  column_length: float = 0.30,
                  allow_bearing: float = 15000.0,
                  concrete_fc: float = 200.0,
                  concrete_unit_weight: float = 2400.0,
                  soil_unit_weight: float = 1700.0,
                  depth_to_footing: float = 1.0,
                  phi_shear: float = 0.85,
                  min_thickness: float = 0.20,
                  max_side: Optional[float] = None) -> dict[str, Any]:
    """Proporción PRELIMINAR de una zapata aislada: cuánto lado hace falta
    por capacidad de carga del suelo, y cuánto peralte para que no punzone
    -- las dos preguntas que "1.00 x 1.00 x 0.30, típico de vivienda" no
    contesta. Esa frase fue justo lo que se usó a ojo antes de tener esta
    función: sirve de punto de partida, pero no dice si ESA columna, con
    ESA carga, realmente cabe en esa zapata.

    Dos chequeos independientes, porque cada uno gobierna una dimensión
    distinta:
      - CARGA: el lado de la zapata sale de repartir la carga (más el peso
        propio de la zapata y la tierra que le queda encima) sobre la
        capacidad admisible del suelo -- esto define el LARGO/ANCHO.
      - PUNZONAMIENTO: una vez que el lado está fijo, el peralte tiene que
        aguantar el cortante que la columna punzona contra la zapata en el
        perímetro crítico a d/2 de la columna (ACI, vc = 1.06·√f'c en
        kg/cm²) -- esto define el PERALTE, y typicamente gobierna antes que
        la carga misma.

    axial_load: carga de servicio sobre la columna, kg (sin factorizar).
    column_width / column_length: sección de la columna, m.
    allow_bearing: capacidad de carga admisible del suelo, kg/m2 (15000 =
    15 t/m2, un valor moderado típico sin estudio de mecánica de suelos).
    concrete_fc: f'c del concreto, kg/cm2 (200 es lo típico en vivienda).
    concrete_unit_weight / soil_unit_weight: kg/m3.
    depth_to_footing: desplante, de la superficie a la base de la zapata,
    m -- define cuánta tierra carga encima para el chequeo de capacidad.
    phi_shear: factor de reducción para cortante (0.85 es el valor usual).
    min_thickness: peralte mínimo a probar, m.
    max_side: tope de lado a probar antes de avisar que no cierra.

    Devuelve 'ok' y, si cumple, 'side'/'thickness' ya verificados por los
    dos chequeos, junto con la carga total (con peso propio incluido), el
    cortante actuante y resistente por punzonamiento, y 'method' explicando
    el criterio -- no reemplaza el estudio de mecánica de suelos ni el
    diseño a flexión del armado."""
    if axial_load <= 0:
        raise ValueError("axial_load tiene que ser mayor que 0.")

    # --- Lado: por capacidad de carga, incluyendo peso propio + sobrecarga
    # de tierra sobre la zapata (no solo la carga de la columna sola).
    lado = max(0.60, round(math.sqrt(axial_load / allow_bearing), 2))
    carga_total = axial_load
    for _ in range(200):
        peso_zapata = lado * lado * min_thickness * concrete_unit_weight
        peso_tierra = lado * lado * depth_to_footing * soil_unit_weight
        carga_total = axial_load + peso_zapata + peso_tierra
        lado_necesario = math.sqrt(carga_total / allow_bearing)
        if lado_necesario <= lado:
            break
        lado = round(lado_necesario + 0.05, 2)
        if max_side is not None and lado >= max_side:
            lado = max_side
            break

    presion_actuante = carga_total / (lado * lado)
    ok_carga = presion_actuante <= allow_bearing * 1.001

    # --- Peralte: por punzonamiento (cortante en dos direcciones), ACI.
    espesor = max(min_thickness, round((lado - max(column_width, column_length)) / 3.0, 2))
    d = peri = vu = vc_resistente = 0.0
    ok_punzonamiento = False
    for _ in range(200):
        d = max(espesor - 0.08, 0.05)
        peri = 2.0 * (column_width + d) + 2.0 * (column_length + d)
        area_critica = (column_width + d) * (column_length + d)
        vu = carga_total * (1.0 - area_critica / (lado * lado))
        vc_resistente = phi_shear * 1.06 * math.sqrt(concrete_fc) * (peri * 100.0) * (d * 100.0)
        if vu <= vc_resistente:
            ok_punzonamiento = True
            break
        espesor = round(espesor + 0.05, 2)

    ok = ok_carga and ok_punzonamiento
    problemas: list[dict[str, str]] = []
    if not ok_carga:
        problemas.append({
            "rule": "capacidad de carga",
            "problem": f"Con lado {lado:.2f} m la presión sobre el suelo da "
                       f"{presion_actuante:.0f} kg/m2, por encima de los "
                       f"{allow_bearing:g} kg/m2 admisibles (se llegó al "
                       f"tope max_side).",
            "fix": "Subí max_side, o pedí un estudio de mecánica de suelos "
                   "si esta capacidad admisible es solo un supuesto."})
    if not ok_punzonamiento:
        problemas.append({
            "rule": "punzonamiento",
            "problem": f"El cortante actuante ({vu:.0f} kg) supera al "
                       f"resistente ({vc_resistente:.0f} kg) incluso con "
                       f"{espesor:.2f} m de peralte.",
            "fix": "Agrandá el lado de la zapata (reduce la presión y el "
                   "cortante actuante), subí f'c, o revisá si hace falta "
                   "un dado/pedestal que reparta la carga en un perímetro "
                   "mayor."})

    return {
        "ok": ok,
        "problems": problemas,
        "side": lado,
        "thickness": espesor,
        "totalLoad_kg": round(carga_total, 1),
        "bearingPressure_kg_m2": round(presion_actuante, 1),
        "effectiveDepth_m": round(d, 3),
        "criticalPerimeter_m": round(peri, 2),
        "punchingShearDemand_kg": round(vu, 1),
        "punchingShearCapacity_kg": round(vc_resistente, 1),
        "method": ("Lado por capacidad de carga admisible (incluye peso "
                   "propio de la zapata y la tierra que le queda encima); "
                   "peralte por punzonamiento en dos direcciones (ACI, "
                   "vc=1.06·√f'c en kg/cm², perímetro crítico a d/2 de la "
                   "columna). Chequeo PRELIMINAR -- no reemplaza el "
                   "estudio de mecánica de suelos ni el diseño a flexión "
                   "del armado de la zapata."),
    }
