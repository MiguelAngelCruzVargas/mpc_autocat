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


# ------------------------------------------- generador de partido (V1)

# Medidas del esquema, en metros. Salen de proporciones usuales de vivienda
# entre medianeras, no de ninguna norma: son el punto de partida que después
# se ajusta a mano si el proyecto lo pide.
ANCHO_PASILLO = 1.00
FONDO_SOCIAL = 4.00          # banda de sala + comedor, al frente
FONDO_SERVICIOS = 3.00       # banda de cocina + baño + lavado
FONDO_RECAMARA = 3.20
FONDO_BANO_PPAL = 1.50
FONDO_PATIO_MIN = 2.00
# Con el pasillo central de 1.00, cada media crujía mide (frente-1)/2; la
# cocina (social: 8 m2 minimos a 3.00 de fondo) es la que fija el frente.
FRENTE_MIN = 6.40


def suggest_layout(lot_width: float, lot_depth: float,
                   bedrooms: int = 2, bathrooms: int = 1) -> dict[str, Any]:
    """Propone una distribución completa para un lote entre medianeras, YA
    validada contra check_layout y check_geometry antes de devolverla.

    Es la inversa de los check_*: en vez de validar una zonificación que
    alguien inventó, la produce el servidor con un esquema determinístico y
    la pasa por sus propias reglas. El que llama recibe rooms/doors/windows
    listos para dibujar, no una sugerencia a medio verificar.

    El esquema (V1, un nivel, acceso por el frente en y=0):
      - banda social al frente: SALA + COMEDOR
      - banda de servicios: COCINA (derecha), BAÑO y ÁREA DE LAVADO
        (izquierda), PASILLO central de 1.00 que corre hasta el fondo
      - recámaras a ambos lados del pasillo, de a pares
      - PATIO DE SERVICIO al fondo, con acceso desde el pasillo (una
        circulación común, como manda la regla)
      - con bathrooms=2, el BAÑO PRINCIPAL sale en-suite de la recámara
        principal, que es como manda la regla

    Si el programa NO entra (frente menor a 6.40 m, o el fondo no alcanza),
    lo dice con los números en 'problems' en vez de forzar recintos fuera de
    mínimo — un programa que no cierra no se arregla dibujando con cuidado.

    bedrooms: 1 a 6. bathrooms: 1 o 2 (2 = agrega el baño principal
    en-suite). Todo en metros, el frente sobre X y el fondo sobre Y.

    Devuelve rooms/doors/windows (el vocabulario de check_layout), 'areas'
    por recinto, 'builtDepth' (hasta dónde llega lo construido) y
    'validation' con el resultado completo de los checks — 'ok' solo si
    salieron limpios."""
    if not 1 <= int(bedrooms) <= 6:
        raise ValueError("bedrooms va de 1 a 6 en este esquema (V1).")
    if int(bathrooms) not in (1, 2):
        raise ValueError("bathrooms es 1 o 2 (2 = baño principal en-suite).")
    if lot_width <= 0 or lot_depth <= 0:
        raise ValueError("lot_width y lot_depth tienen que ser > 0.")
    bedrooms, bathrooms = int(bedrooms), int(bathrooms)

    problemas: list[dict[str, str]] = []
    if lot_width < FRENTE_MIN - 1e-9:
        problemas.append({
            "rule": "frente insuficiente",
            "problem": f"Con {lot_width:.2f} m de frente no cierran los "
                       f"mínimos habitables: este esquema necesita "
                       f"{FRENTE_MIN:.2f} m (la cocina de 8 m2 es la que "
                       "manda).",
            "fix": "Conseguí más frente, o pedí un esquema a medida: esto "
                   "no se arregla achicando recintos por debajo del mínimo."})
        return {"ok": False, "problems": problemas, "rooms": [],
                "doors": [], "windows": [],
                "minLotWidth": FRENTE_MIN}

    w = float(lot_width)
    xm = w / 2.0
    xc0 = xm - ANCHO_PASILLO / 2.0          # borde izquierdo del pasillo
    xc1 = xm + ANCHO_PASILLO / 2.0          # borde derecho
    y_social = FONDO_SOCIAL
    y_serv = FONDO_SOCIAL + FONDO_SERVICIOS

    rooms: list[dict[str, Any]] = [
        {"name": "SALA", "x0": 0.0, "y0": 0.0, "x1": xm, "y1": y_social},
        {"name": "COMEDOR", "x0": xm, "y0": 0.0, "x1": w, "y1": y_social},
        {"name": "COCINA", "x0": xc1, "y0": y_social, "x1": w, "y1": y_serv},
        {"name": "BAÑO", "x0": 0.0, "y0": y_social, "x1": xc0, "y1": y_social + 1.8},
        {"name": "ÁREA DE LAVADO", "x0": 0.0, "y0": y_social + 1.8,
         "x1": xc0, "y1": y_serv},
    ]
    doors: list[dict[str, Any]] = [
        # El acceso va descentrado a propósito: deja un paño entero libre
        # para la ventana de la sala en la fachada.
        {"from": "EXTERIOR", "to": "SALA", "width": 0.90,
         "x": xm * 0.75, "y": 0.0},
        # Sala-comedor es un vano abierto, no una puerta con hoja.
        {"from": "SALA", "to": "COMEDOR", "width": 1.20, "type": "pass",
         "x": xm, "y": y_social / 2.0},
        {"from": "COMEDOR", "to": "PASILLO", "width": 0.90,
         "x": (xm + xc1) / 2.0, "y": y_social},
        {"from": "COMEDOR", "to": "COCINA", "width": 0.80,
         "x": (xc1 + w) / 2.0, "y": y_social},
        {"from": "PASILLO", "to": "BAÑO", "width": 0.70,
         "x": xc0, "y": y_social + 0.9},
        {"from": "PASILLO", "to": "ÁREA DE LAVADO", "width": 0.80,
         "x": xc0, "y": y_social + 2.4},
    ]

    # Recámaras a ambos lados del pasillo, llenando la columna más corta.
    # La principal va primero, a la izquierda; su baño en-suite (si hay dos
    # baños) la sigue en la misma columna, así comparten muro.
    cursor = {"izq": y_serv, "der": y_serv}
    col_x = {"izq": (0.0, xc0), "der": (xc1, w)}

    def _colocar(nombre: str, fondo: float, col: str) -> dict[str, Any]:
        x0, x1 = col_x[col]
        r = {"name": nombre, "x0": x0, "y0": cursor[col],
             "x1": x1, "y1": cursor[col] + fondo}
        cursor[col] += fondo
        rooms.append(r)
        return r

    ppal = _colocar("RECÁMARA PRINCIPAL", FONDO_RECAMARA, "izq")
    doors.append({"from": "PASILLO", "to": "RECÁMARA PRINCIPAL", "width": 0.80,
                  "x": xc0, "y": (ppal["y0"] + ppal["y1"]) / 2.0})
    if bathrooms >= 2:
        bp = _colocar("BAÑO PRINCIPAL", FONDO_BANO_PPAL, "izq")
        doors.append({"from": "RECÁMARA PRINCIPAL", "to": "BAÑO PRINCIPAL",
                      "width": 0.70, "x": xc0 / 2.0, "y": bp["y0"]})

    for i in range(2, bedrooms + 1):
        col = "der" if cursor["der"] <= cursor["izq"] else "izq"
        r = _colocar(f"RECÁMARA {i}", FONDO_RECAMARA, col)
        lado = xc0 if col == "izq" else xc1
        doors.append({"from": "PASILLO", "to": r["name"], "width": 0.80,
                      "x": lado, "y": (r["y0"] + r["y1"]) / 2.0})

    y_fin = max(cursor["izq"], cursor["der"])

    # Sin huecos muertos: la columna corta se completa. Si quedó vacía del
    # lado derecho (una sola recámara), ahí va un estudio; si solo quedó
    # corta, el último recinto de esa columna se estira hasta el fondo.
    for col in ("izq", "der"):
        falta = y_fin - cursor[col]
        if falta < 1e-9:
            continue
        propios = [r for r in rooms
                   if (r["x0"], r["x1"]) == col_x[col] and r["y0"] >= y_serv]
        if propios:
            ultimo = propios[-1]
            if _clase(ultimo["name"]) == "bano" and len(propios) >= 2:
                # Estirar un baño a 11 m2 no es un partido, es un desperdicio:
                # crece la recámara y el baño se corre al fondo con su mismo
                # tamaño (la puerta en-suite se muda con él).
                previo = propios[-2]
                previo["y1"] += falta
                ultimo["y0"] += falta
                ultimo["y1"] = y_fin
                for d in doors:
                    if str(d.get("to")) == ultimo["name"]:
                        d["y"] = ultimo["y0"]
            else:
                ultimo["y1"] = y_fin
        else:
            x0, x1 = col_x[col]
            rooms.append({"name": "ESTUDIO", "x0": x0, "y0": y_serv,
                          "x1": x1, "y1": y_fin})
            lado = xc0 if col == "izq" else xc1
            doors.append({"from": "PASILLO", "to": "ESTUDIO", "width": 0.80,
                          "x": lado, "y": (y_serv + y_fin) / 2.0})
        cursor[col] = y_fin

    rooms.append({"name": "PASILLO", "x0": xc0, "y0": y_social,
                  "x1": xc1, "y1": y_fin})

    fondo_necesario = y_fin + FONDO_PATIO_MIN
    if lot_depth < fondo_necesario - 1e-9:
        problemas.append({
            "rule": "fondo insuficiente",
            "problem": f"Este programa ({bedrooms} recámara(s), "
                       f"{bathrooms} baño(s)) necesita {fondo_necesario:.2f} m "
                       f"de fondo y el lote tiene {lot_depth:.2f}.",
            "fix": "Quitá una recámara, o pedí el esquema en dos niveles — "
                   "achicar recintos por debajo del mínimo no es opción."})
        return {"ok": False, "problems": problemas, "rooms": rooms,
                "doors": doors, "windows": [],
                "neededDepth": round(fondo_necesario, 2)}

    rooms.append({"name": "PATIO DE SERVICIO", "x0": 0.0, "y0": y_fin,
                  "x1": w, "y1": float(lot_depth)})
    doors.append({"from": "PASILLO", "to": "PATIO DE SERVICIO",
                  "width": 0.80, "x": xm, "y": y_fin})

    windows = [{"room": "SALA", "wall": "fachada"},
               {"room": "COMEDOR", "wall": "fachada"}]
    avisos: list[str] = []
    for r in rooms:
        if r["name"] in ("PATIO DE SERVICIO", "PASILLO"):
            continue
        if abs(r["y1"] - y_fin) < 1e-9:
            windows.append({"room": r["name"], "wall": "patio"})
        elif r["y0"] >= y_serv:
            avisos.append(
                f"'{r['name']}' queda interior: necesita patio de luz o "
                "ventilación cenital si la normativa local la exige.")

    validation = {
        "layout": check_layout(rooms=rooms, doors=doors,
                               lot_width=w, lot_depth=float(lot_depth),
                               windows=windows),
        "geometry": check_geometry(rooms=rooms, doors=doors),
    }
    ok = validation["layout"]["ok"] and validation["geometry"]["ok"]

    resultado: dict[str, Any] = {
        "ok": ok,
        "problems": (validation["layout"]["problems"]
                     + validation["geometry"]["problems"]),
        "rooms": rooms,
        "doors": doors,
        "windows": windows,
        "areas": {r["name"]: round((r["x1"] - r["x0"]) * (r["y1"] - r["y0"]), 2)
                  for r in rooms},
        "builtDepth": round(y_fin, 2),
        "patioDepth": round(float(lot_depth) - y_fin, 2),
        "validation": validation,
        "message": ("Distribución validada por check_layout y check_geometry: "
                    "lista para dibujar con create_walls sobre las fronteras "
                    "de 'rooms'." if ok else
                    "El esquema salió con problemas — revisá 'problems' "
                    "antes de dibujar."),
    }
    if avisos:
        resultado["warnings"] = avisos
    return resultado


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
    mano con create_dimension o create_text eligiendo el offset de memoria --
    y ESO se revisa solo, sin depender de que quien dibuja se acuerde de
    avisarlo: create_text/create_mtext/create_leader se auto-registran (ver
    space.PREFIJO_TEXTO), así que un texto puesto a mano que pisa a otro
    texto (o a una cota) queda atrapado acá igual, sea cual sea el agente
    que lo dibujó y haya leído o no CLAUDE.md.

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

    extra.extend(space.text_footprints())
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


# ------------------------------------------------------ losa entre apoyos

def check_slab_span(span: float,
                    live_load: float = 400.0,
                    width: float = 1.0,
                    concrete_fc: float = 250.0,
                    steel_fy: float = 4200.0,
                    concrete_unit_weight: float = 2400.0,
                    min_thickness: float = 0.12,
                    cover: float = 0.03,
                    max_steel_ratio: float = 0.016) -> dict[str, Any]:
    """Proporción PRELIMINAR de una losa maciza simplemente apoyada entre
    dos apoyos -- una losa de entrepiso, o el tablero de un puente peatonal
    entre sus dos estribos, es la misma cuenta: un claro, una carga viva
    distribuida y un peralte que tiene que aguantar el momento sin pasarse
    de cuantía de acero.

    span: claro libre entre apoyos, m. live_load: carga viva distribuida,
    kg/m2 (400 es un valor de referencia para pasarela peatonal; una losa
    de entrepiso de vivienda va más baja, ~170-250 kg/m2 -- pasá el valor
    real del proyecto). width: ancho de análisis, m -- por default se
    analiza una franja de 1.00 m, que es como se diseña cualquier losa en
    una dirección.
    concrete_fc / steel_fy: kg/cm2 (250 y 4200 son valores típicos de obra
    en México -- Ø f'c 250, varilla grado 42). cover: recubrimiento libre
    al centroide del armado, m.
    max_steel_ratio: cuantía máxima aceptada antes de engordar el peralte
    en vez de seguir metiendo acero (0.016 es una referencia práctica, muy
    por debajo de la cuantía balanceada, para no terminar con una losa
    sobrearmada).

    Método: peralte semilla por relación claro/peralte (L/20, la
    proporción usual para no tener que verificar deflexión aparte en una
    losa ligera), luego momento simple (w·L²/8) y área de acero por
    flexión simplificada (As = M/(0.9·fy·d), sin el descuento del bloque
    de compresión -- conservador). Si la cuantía resultante supera
    max_steel_ratio, engorda el peralte y recalcula. Chequeo PRELIMINAR de
    proporción -- no reemplaza el diseño a cortante ni la verificación de
    deflexión de un cálculo estructural completo.

    Devuelve 'ok', 'thickness' y 'mainSteelArea_cm2_per_m' ya verificados
    contra la cuantía máxima, junto con el momento y la carga total con
    los que se calculó."""
    if span <= 0:
        raise ValueError("span tiene que ser mayor que 0.")

    espesor = max(min_thickness, round(span / 20.0, 2))
    momento = carga_total = as_req = cuantia = d = 0.0
    for _ in range(200):
        peso_propio = espesor * concrete_unit_weight
        carga_total = peso_propio + live_load
        momento = carga_total * width * span ** 2 / 8.0
        d = max(espesor - cover - 0.006, 0.05)
        # M en kg·cm, d en cm, fy en kg/cm2 -> As en cm2 por franja 'width'.
        as_req = (momento * 100.0) / (0.9 * steel_fy * (d * 100.0))
        as_min = 0.0018 * (width * 100.0) * (espesor * 100.0)
        as_req = max(as_req, as_min)
        cuantia = as_req / ((width * 100.0) * (d * 100.0))
        if cuantia <= max_steel_ratio:
            break
        espesor = round(espesor + 0.01, 2)

    ok = cuantia <= max_steel_ratio
    problemas: list[dict[str, str]] = []
    if not ok:
        problemas.append({
            "rule": "cuantia excesiva",
            "problem": f"Con peralte {espesor:.2f} m la cuantía de acero da "
                       f"{cuantia:.4f}, por encima del máximo aceptado "
                       f"({max_steel_ratio:g}).",
            "fix": "Subí min_thickness para arrancar de un peralte mayor, "
                   "bajá la carga viva si el uso real lo permite, o "
                   "considerá vigas de apoyo intermedias si el claro es "
                   "muy largo para una losa maciza."})

    return {
        "ok": ok,
        "problems": problemas,
        "thickness": espesor,
        "effectiveDepth_m": round(d, 3),
        "selfWeight_kg_m2": round(espesor * concrete_unit_weight, 1),
        "totalLoad_kg_m2": round(carga_total, 1),
        "moment_kgm": round(momento, 1),
        "mainSteelArea_cm2_per_m": round(as_req, 2),
        "steelRatio": round(cuantia, 5),
        "method": ("Losa maciza simplemente apoyada, peralte semilla por "
                   "L/20, momento simple w·L²/8, As=M/(0.9·fy·d) sin "
                   "descuento del bloque de compresión (conservador). "
                   "Chequeo PRELIMINAR de proporción -- no reemplaza el "
                   "diseño a cortante ni la verificación de deflexión de "
                   "un cálculo estructural completo."),
    }


# --------------------------------------------------- viga bajo carga vehicular

# Carga de carril HS20-44 (AASHTO) -- la alternativa que la propia norma
# permite a mover el camión eje por eje a mano: un uniformemente distribuido
# más una concentrada para momento. 640 lb/ft y 18000 lb, convertidos.
HS20_LANE_LOAD_KG_M = 952.5
HS20_LANE_POINT_KG = 8165.0


def check_bridge_girder(span: float,
                        girder_spacing: float,
                        girder_width: float = 0.30,
                        slab_thickness: float = 0.20,
                        concrete_fc: float = 250.0,
                        steel_fy: float = 4200.0,
                        concrete_unit_weight: float = 2400.0,
                        min_depth: float = 0.5,
                        cover: float = 0.05,
                        max_steel_ratio: float = 0.016) -> dict[str, Any]:
    """Proporción PRELIMINAR de una trabe principal de puente bajo carga
    vehicular -- un claro de 14 m con tráfico pesado no es la misma cuenta
    que una losa de entrepiso con w·L²/8 y una carga viva inventada: hace
    falta un vehículo de diseño real. Esto usa la CARGA DE CARRIL HS20-44
    de AASHTO (uniforme + concentrada para momento), que es justo la
    alternativa que la propia norma habilita para no tener que mover el
    camión eje por eje a mano -- no es un número inventado, es el método
    estándar para un cálculo preliminar de este tipo.

    span: claro libre entre apoyos, m. girder_spacing: separación entre
    ejes de trabe, m -- define cuánta losa tributa a CADA trabe y el
    factor de distribución de la carga viva.
    girder_width: ancho de la trabe, m. slab_thickness: espesor YA
    resuelto de la losa de rodadura (con check_slab_span, con la carga de
    rueda como equivalente uniforme) -- esta función no lo calcula de
    nuevo, lo toma como dato real de otro chequeo.
    concrete_fc/steel_fy: kg/cm2. min_depth: peralte mínimo a probar, m.

    Método: factor de distribución DF = girder_spacing/1.83 (AASHTO
    Standard Specifications, fórmula S/6.0 en pies convertida a metros,
    para trabes de concreto con losa colada en sitio) reparte la carga de
    carril a esta trabe; impacto AASHTO I=50/(125+L_pies), tope 0.3;
    momento de carga muerta con el peso propio de la trabe + la losa
    tributaria. Peralte semilla L/12 (una trabe cargada necesita más
    proporción que una losa: L/20 ahí no alcanza), acero por flexión
    simplificada igual que check_slab_span, engordando el peralte si la
    cuantía se pasa de max_steel_ratio.

    Chequeo PRELIMINAR de proporción -- no reemplaza el análisis de carga
    móvil completo (posición crítica de ejes, líneas de influencia), el
    diseño a cortante, ni la verificación de deflexión de un cálculo
    estructural completo. Para un claro largo con tráfico pesado real,
    esto es el punto de partida para pedir el cálculo estructural
    definitivo, no el reemplazo."""
    if span <= 0:
        raise ValueError("span tiene que ser mayor que 0.")
    if girder_spacing <= 0:
        raise ValueError("girder_spacing tiene que ser mayor que 0.")

    # Carga viva de carril + impacto, y el reparto a ESTA trabe.
    m_ll_carril = (HS20_LANE_LOAD_KG_M * span ** 2 / 8.0
                  + HS20_LANE_POINT_KG * span / 4.0)
    factor_distribucion = girder_spacing / 1.83
    l_pies = span * 3.28084
    impacto = min(0.3, 50.0 / (125.0 + l_pies))
    m_viva = m_ll_carril * factor_distribucion * (1.0 + impacto)

    peralte = max(min_depth, round(span / 12.0, 2))
    momento = as_req = cuantia = d = w_muerta = 0.0
    for _ in range(200):
        peso_propio = girder_width * peralte * concrete_unit_weight
        peso_losa_tributaria = slab_thickness * girder_spacing * concrete_unit_weight
        w_muerta = peso_propio + peso_losa_tributaria
        m_muerta = w_muerta * span ** 2 / 8.0
        momento = m_muerta + m_viva
        d = max(peralte - cover - 0.013, 0.10)
        as_req = (momento * 100.0) / (0.9 * steel_fy * (d * 100.0))
        as_min = 0.0018 * (girder_width * 100.0) * (peralte * 100.0)
        as_req = max(as_req, as_min)
        cuantia = as_req / ((girder_width * 100.0) * (d * 100.0))
        if cuantia <= max_steel_ratio:
            break
        peralte = round(peralte + 0.05, 2)

    ok = cuantia <= max_steel_ratio
    problemas: list[dict[str, str]] = []
    if not ok:
        problemas.append({
            "rule": "cuantia excesiva",
            "problem": f"Con peralte {peralte:.2f} m la cuantía de acero da "
                       f"{cuantia:.4f}, por encima del máximo aceptado "
                       f"({max_steel_ratio:g}).",
            "fix": "Subí min_depth para arrancar de un peralte mayor, "
                   "agrandá girder_width, o achicá girder_spacing (menos "
                   "losa tributaria y menor factor de distribución) "
                   "agregando más trabes."})

    return {
        "ok": ok,
        "problems": problemas,
        "depth": peralte,
        "effectiveDepth_m": round(d, 3),
        "distributionFactor": round(factor_distribucion, 3),
        "impactFactor": round(impacto, 3),
        "liveLoadMoment_kgm": round(m_viva, 1),
        "deadLoad_kg_m": round(w_muerta, 1),
        "totalMoment_kgm": round(momento, 1),
        "mainSteelArea_cm2": round(as_req, 2),
        "steelRatio": round(cuantia, 5),
        "method": ("Carga de carril HS20-44 (AASHTO): "
                   f"{HS20_LANE_LOAD_KG_M:g} kg/m + {HS20_LANE_POINT_KG:g} "
                   "kg concentrada para momento, con factor de "
                   "distribución S/1.83 e impacto AASHTO 50/(125+L_pies). "
                   "Peralte semilla L/12, acero por flexión simplificada "
                   "sin descuento del bloque de compresión (conservador). "
                   "Chequeo PRELIMINAR -- no reemplaza el análisis de "
                   "carga móvil completo, cortante, ni deflexión."),
    }


# ------------------------------------------------ armadura de techo (reacción)

def check_roof_truss(span: float,
                     truss_spacing: float,
                     rise: float,
                     roof_dead_load: float = 15.0,
                     roof_live_load: float = 40.0,
                     wind_uplift: float = 0.0,
                     dead_load_factor_uplift: float = 0.6) -> dict[str, Any]:
    """Reacción PRELIMINAR de una armadura de techo a dos aguas sobre sus dos
    apoyos -- lo que hace falta para poder dimensionar la columna y la
    zapata que la reciben con `check_column`/`check_footing`, en vez de
    inventar la carga axial a ojo. Una nave o cancha techada es
    especialmente sensible al caso que "carga muerta nomás" no contesta:
    con cubierta liviana (lámina) y mucha área de techo, la succión de
    viento puede superar al peso propio y la reacción termina siendo hacia
    ARRIBA -- el apoyo necesita anclaje a tensión, no un simple apoyo.

    span: distancia entre apoyos (columnas), m. truss_spacing: separación
    entre armaduras (a cuántas armaduras entre sí, m) -- junto con span
    define el área tributaria de ESTA armadura.
    rise: altura de cumbrera sobre el apoyo, m -- solo se usa para
    estimar la fuerza de cuerda equivalente, no cambia la reacción.
    roof_dead_load: carga muerta de techo, kg/m2 de proyección horizontal
    (lámina + largueros + peso propio de armadura estimado; 15 kg/m2 es un
    valor de referencia para lámina calibre 26 sobre estructura ligera).
    roof_live_load: carga viva de techo (mantenimiento, no acumulación de
    agua), kg/m2 -- 40 es un valor de referencia para techo inaccesible.
    wind_uplift: succión de viento, kg/m2 (positivo = hacia arriba); 0.0 no
    inventa una carga de viento que el proyecto no dio -- si el sitio la
    tiene, hay que pasarla.
    dead_load_factor_uplift: factor que reduce la carga muerta en la
    combinación de succión (0.6, un valor de referencia tipo ASD -- la
    carga muerta ayuda contra el viento, pero no toda, porque puede haber
    incertidumbre en el peso propio real).

    Método: viga simplemente apoyada sobre el área tributaria (span x
    truss_spacing); reacción de gravedad = (muerta+viva)/2 por apoyo;
    reacción de viento = (0.6·muerta - succión)/2 por apoyo -- si da
    negativa, hay levantamiento neto. Fuerza de cuerda equivalente:
    momento máximo (w·L²/8) dividido entre el peralte de la armadura
    (rise) en el centro del claro, como viga de brazo de palanca
    constante -- una forma rápida y usual de estimar el orden de magnitud
    de la fuerza en cuerdas, no un análisis por nudo.

    Chequeo PRELIMINAR -- no reemplaza el análisis de la armadura por
    nudos ni el estudio de viento del reglamento aplicable (CFE/ASCE)."""
    if span <= 0:
        raise ValueError("span tiene que ser mayor que 0.")
    if truss_spacing <= 0:
        raise ValueError("truss_spacing tiene que ser mayor que 0.")
    if rise < 0:
        raise ValueError("rise no puede ser negativo.")

    area_tributaria = span * truss_spacing
    carga_muerta_total = roof_dead_load * area_tributaria
    carga_viva_total = roof_live_load * area_tributaria
    carga_viento_total = wind_uplift * area_tributaria

    reaccion_gravedad = (carga_muerta_total + carga_viva_total) / 2.0
    reaccion_viento = (dead_load_factor_uplift * carga_muerta_total
                       - carga_viento_total) / 2.0

    momento_max = (roof_dead_load + roof_live_load) * truss_spacing * span ** 2 / 8.0
    fuerza_cuerda = momento_max / max(rise, 0.05)

    ok = reaccion_viento >= 0
    problemas: list[dict[str, str]] = []
    if not ok:
        problemas.append({
            "rule": "levantamiento por viento",
            "problem": f"La reacción con succión de viento da "
                       f"{reaccion_viento:.0f} kg -- negativa: la armadura "
                       "tira del apoyo hacia arriba en vez de apoyarse.",
            "fix": "El apoyo necesita anclaje a tensión (placa + pernos con "
                   "longitud de anclaje verificada al concreto), no alcanza "
                   "con apoyo por gravedad -- o revisá wind_uplift si el "
                   "dato no aplica a esta orientación de techo."})

    return {
        "ok": ok,
        "problems": problemas,
        "tributaryArea_m2": round(area_tributaria, 2),
        "gravityReaction_kg": round(reaccion_gravedad, 1),
        "windUpliftReaction_kg": round(reaccion_viento, 1),
        "chordForce_kg": round(fuerza_cuerda, 1),
        "method": ("Viga simplemente apoyada sobre el área tributaria "
                   "(span x truss_spacing). Reacción de gravedad "
                   "(muerta+viva)/2; reacción de viento "
                   "(0.6·muerta-succión)/2, negativa = levantamiento neto. "
                   "Fuerza de cuerda equivalente = momento máximo / peralte "
                   "de armadura, viga de brazo de palanca constante. "
                   "Chequeo PRELIMINAR -- no reemplaza el análisis por "
                   "nudos ni el estudio de viento del reglamento aplicable."),
    }


# --------------------------------------------------------------- columna

def check_column(axial_load: float,
                 height: float,
                 width: float = 0.30,
                 depth: float = 0.30,
                 concrete_fc: float = 200.0,
                 steel_fy: float = 4200.0,
                 k_factor: float = 1.0,
                 steel_ratio: float = 0.01,
                 phi: float = 0.65,
                 max_slenderness: float = 22.0,
                 max_side: Optional[float] = None) -> dict[str, Any]:
    """Proporción PRELIMINAR de una columna/castillo de concreto bajo carga
    axial. La pregunta que "30x30, típico" no contesta es si ESA columna,
    con ESA altura libre, sigue siendo una columna corta o ya es esbelta:
    una sección que sobra por capacidad pura puede fallar por pandeo antes
    de aplastarse -- el caso típico de una nave o cancha techada, con
    columnas de 4 a 6 m sin ningún apoyo intermedio.

    Dos chequeos independientes, y el que gobierna cambia con la esbeltez:
      - CAPACIDAD AXIAL: Pn de columna estribada con excentricidad mínima
        (ACI 10.3.6.2, φ=0.65), con la cuantía de acero longitudinal que le
        pasás (1% mínimo típico si la columna todavía no está armada).
      - ESBELTEZ: k·lu/r, con r=0.3·lado menor (aproximación ACI para
        sección rectangular). Si supera max_slenderness (22, el límite
        usual para tratarla como columna corta sin magnificar momentos),
        agranda la sección -- esto NO reemplaza el análisis P-Δ de una
        columna esbelta real.

    axial_load: carga de servicio, kg (sin factorizar; si viene de
    check_roof_truss, usá 'gravityReaction_kg').
    height: altura libre sin arriostrar, m (NPT de piso a donde apoya la
    trabe o armadura -- no la altura total del muro si hay antepecho).
    width/depth: sección a probar, m. k_factor: factor de longitud
    efectiva (1.0 = articulada en los dos extremos; en una nave con
    armadura apoyada simplemente arriba y base empotrada en la zapata,
    1.0-1.2 es razonable de partida -- subilo si la base no está realmente
    empotrada).
    steel_ratio: cuantía de acero longitudinal a probar (0.01 = 1%, el
    mínimo ACI para columnas). max_side: tope de lado a probar antes de
    avisar que no cierra.

    Devuelve 'ok' y, si cumple, 'width'/'depth' ya verificados por los dos
    chequeos, junto con la capacidad axial, la esbeltez y 'method'.
    Chequeo PRELIMINAR de proporción -- no reemplaza el diseño biaxial ni
    el análisis de columna esbelta con magnificación de momentos."""
    if axial_load <= 0:
        raise ValueError("axial_load tiene que ser mayor que 0.")
    if height <= 0:
        raise ValueError("height tiene que ser mayor que 0.")

    lado_w, lado_h = width, depth
    ag = pn_phi = esbeltez = r = 0.0
    ok_capacidad = ok_esbeltez = False
    for _ in range(200):
        ag = lado_w * lado_h
        ast = steel_ratio * ag
        # Pn en kg: f'c y fy en kg/cm2, areas convertidas de m2 a cm2 (x10000).
        pn = 0.85 * concrete_fc * (ag - ast) * 10000.0 + steel_fy * ast * 10000.0
        pn_phi = 0.80 * phi * pn  # 0.80: columna estribada, ACI 10.3.6.2
        ok_capacidad = axial_load <= pn_phi

        lado_menor = min(lado_w, lado_h)
        r = 0.3 * lado_menor
        esbeltez = (k_factor * height) / r
        ok_esbeltez = esbeltez <= max_slenderness

        if ok_capacidad and ok_esbeltez:
            break
        # Agranda el lado menor primero: mejora esbeltez y capacidad a la vez.
        if lado_w <= lado_h:
            lado_w = round(lado_w + 0.05, 2)
        else:
            lado_h = round(lado_h + 0.05, 2)
        if max_side is not None and max(lado_w, lado_h) >= max_side:
            lado_w = min(lado_w, max_side)
            lado_h = min(lado_h, max_side)
            break

    ok = ok_capacidad and ok_esbeltez
    problemas: list[dict[str, str]] = []
    if not ok_capacidad:
        problemas.append({
            "rule": "capacidad axial",
            "problem": f"Con sección {lado_w:.2f}x{lado_h:.2f} m, φPn da "
                       f"{pn_phi:.0f} kg, por debajo de la carga de "
                       f"{axial_load:.0f} kg (se llegó al tope max_side).",
            "fix": "Subí max_side, subí f'c, o subí steel_ratio (hasta el "
                   "máximo ACI de 8%) si agrandar la sección no es viable."})
    if not ok_esbeltez:
        problemas.append({
            "rule": "esbeltez",
            "problem": f"k·lu/r da {esbeltez:.1f}, por encima del límite de "
                       f"columna corta ({max_slenderness:g}) incluso con "
                       f"sección {lado_w:.2f}x{lado_h:.2f} m (se llegó al "
                       f"tope max_side).",
            "fix": "Subí max_side, arriostrá la columna a media altura "
                   "(reduce height), o pedí el análisis de columna esbelta "
                   "con magnificación de momentos -- esta función no lo "
                   "hace."})

    return {
        "ok": ok,
        "problems": problemas,
        "width": lado_w,
        "depth": lado_h,
        "axialCapacity_kg": round(pn_phi, 1),
        "slenderness": round(esbeltez, 1),
        "radiusOfGyration_m": round(r, 3),
        "steelArea_cm2": round(steel_ratio * ag * 10000.0, 2),
        "method": ("Capacidad axial de columna estribada con excentricidad "
                   "mínima (ACI 10.3.6.2, φ=0.65, "
                   "Pn=0.85·f'c·(Ag-Ast)+fy·Ast, factor 0.80). Esbeltez "
                   "k·lu/r con r=0.3·lado menor (aproximación ACI para "
                   "sección rectangular), límite de columna corta 22. "
                   "Chequeo PRELIMINAR de proporción -- no reemplaza el "
                   "diseño biaxial ni el análisis de columna esbelta con "
                   "magnificación de momentos."),
    }
