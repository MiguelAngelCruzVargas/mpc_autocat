"""Reglas de proyecto arquitectónico, verificadas antes de dibujar.

Un plano puede estar impecable de dibujo y ser inconstruible: una puerta de
calle que abre a una recámara, un baño principal que da al pasillo, un patio de
servicio al que solo se llega cruzando un dormitorio. Eso no se ve mirando la
geometría — hay que preguntárselo al proyecto.

Acá viven esas reglas, para que el chequeo no dependa de que alguien se acuerde.
"""
from __future__ import annotations

from typing import Any, Optional

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
