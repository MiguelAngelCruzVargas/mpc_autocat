"""Instalaciones de una vivienda: eléctrica, hidráulica y sanitaria.

Las tres parten del mismo vocabulario que el resto del proyecto (rooms y
doors de suggest_layout, muebles de suggest_furniture) y siguen NORMA
MEXICANA. Cada criterio lleva su fuente en NORMA; lo que no es norma sino
práctica de proyecto está marcado como tal, para que nadie confunda una
costumbre con una obligación.

- suggest_electrical: salidas de alumbrado, apagadores, contactos (con
  falla a tierra donde la NOM la exige), tablero, circuitos y cuadro de
  cargas.
- suggest_hydraulic: agua fría desde la toma y el tinaco, agua caliente
  desde el calentador, diámetros por unidades mueble acumuladas.
- suggest_sanitary: desagüe de cada mueble, diámetros, pendiente, registros
  y albañal hasta la red municipal.

Las redes son árboles ortogonales (instalaciones_geom.red_en_arbol): cada
tramo sabe qué muebles alimenta o drena, que es lo que define su diámetro.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad
import electrical
import furniture
import instalaciones_geom as geo
import layers
import space

# ------------------------------------------------------------------ NORMA
# Cada valor con su fuente. 'práctica' = criterio usual de proyecto en
# México, no obligación normativa; 'no verificado' = no se encontró el
# texto oficial que lo respalde.
#
# Fuentes:
#  [NOM] NOM-001-SEDE-2012 (DOF): https://sidof.segob.gob.mx/notas/docFuente/5280607
#  [NTC] NTC Proyecto Arquitectónico CDMX (GODF 08-02-2011) §6.1:
#        https://paot.mx/centro/leyes/df/pdf/GODF/GODF_08_02_2011_02.pdf
#        (las de dic-2024 remiten los números a la NTC-Instalaciones
#        Hidráulicas, cuyo texto no se pudo leer)
#  [INIFED] Normas y Especificaciones Vol. 5 Tomo II, Instalaciones
#        Hidrosanitarias (rev. 2022). Norma federal pensada para escuelas;
#        se usa como la tabla oficial disponible de unidades mueble.
# Fuera de la CDMX manda el reglamento de cada estado o municipio.
NORMA: dict[str, Any] = {
    # NOM-001-SEDE-2012 (Instalaciones eléctricas, utilización)
    "contacto_max_m": 1.8,          # 210-52(a)(1): ningún punto del muro a más de 1.8 m de un contacto
    "muro_min_contacto_m": 0.6,     # 210-52(a)(2): cuenta todo muro de 600 mm o más
    "cubierta_max_m": 0.6,          # 210-52(c)(1): sobre cubierta de cocina, ningún punto a más de 600 mm
    "lavabo_contacto_m": 0.9,       # 210-52(d): contacto a no más de 900 mm del lavabo
    "pasillo_min_m": 3.0,           # 210-52(h): pasillo de 3 m o más lleva al menos un contacto
    "va_m2_alumbrado": 33.0,        # Tabla 220-12: unidades de vivienda, 33 VA/m²
    "va_contacto": 180.0,           # 220-14(l): 180 VA por contacto (pequeños aparatos, baño, exterior de servicio)
    # 220-14(j): en VIVIENDA los contactos de uso general ya están incluidos
    # en los 33 VA/m² de alumbrado (Tabla 220-12): no suman carga propia.
    # Sumarles 180 VA cada uno le daba 10 circuitos a un depto de 75 m².
    "va_contacto_general_vivienda": 0.0,
    "va_circuito_20a": 1500.0,      # 220-52(a)/(b): pequeños aparatos y lavado, 1500 VA por circuito
    "tension_v": 120.0,             # [NOM] tensión nominal del texto (CFE suministra 127 V: no verificado)
    "demanda_100_va": 3000.0,       # 220-42: primeros 3000 VA de alumbrado al 100 %
    "demanda_resto": 0.35,          # 220-42: de 3001 a 120 000 VA al 35 %
    "exterior_max_altura_m": 2.0,   # 210-52(e): contacto exterior al frente y atrás, a no más de 2 m
    "factor_continua": 0.8,         # 210-19(a)/210-20(a): carga continua al 80 % de la capacidad
    "calibre_awg": {15: 14, 20: 12},  # 240-4(d) (=NEC 240.4(D)); en el texto NOM: no verificado
    # Reglamento de Construcciones CDMX / NTC para el Diseño y Ejecución de
    # Obras e Instalaciones Hidráulicas
    "pendiente_drenaje": 0.02,      # [NTC] 6.1.3.1: pendiente mínima 2 %
    "desague_min_mm": 32,           # [NTC] 6.1.3.1: ninguna tubería de desagüe menor de 32 mm
    "albanal_min_mm": 150,          # [NTC] 6.1.3.2-I: albañal fuera del predio, mínimo 15 cm
    "registro_max_m": 10.0,         # [NTC] 6.1.3.2-V: registros a ≤10 m y en cada cambio de dirección
    "registro_40x60_hasta_m": 1.0,  # [NTC] 6.1.3.2-VI: 40x60 cm hasta 1 m de profundidad
    "ventilador_min_mm": 50,        # [NTC] 6.1.3.2-III: tubo ventilador ≥5 cm en el origen del albañal
    "tinaco_sobre_regadera_m": 2.0, # [NTC] 6.1.2: salida del tinaco ≥2 m sobre la regadera
    "retorno_ac_m": 25.0,           # [INIFED] §2.8: retorno de agua caliente a más de 25 m
}

# Diámetro mínimo de descarga por mueble, en mm: [INIFED] Tabla 3.1. El
# fregadero no figura en la tabla: 50 mm es práctica (no verificado).
DESCARGA_MM = {"wc": 100, "lavatory": 32, "shower": 50, "kitchen_sink": 50,
               "laundry_sink": 38}

# Unidades de descarga por mueble: [INIFED] Tabla 3.1 (fregadero: práctica).
UNIDADES_DESCARGA = {"wc": 6, "lavatory": 1, "shower": 3, "kitchen_sink": 2,
                     "laundry_sink": 2}

# Ramal horizontal: diámetro mínimo según UD acumuladas, [INIFED] Tabla 3.3.
DIAMETRO_RAMAL = [(1, 32), (3, 38), (6, 50), (32, 75), (160, 100), (640, 150)]

# Unidades mueble de agua: [INIFED] Tabla 2.2 (1 UM ≈ 6 L/min). OJO: no se
# mezcla con la escala de Hunter (1 UM ≈ 25 L/min, WC=3): cada escala va
# con su propia tabla de diámetros.
UNIDADES_MUEBLE = {"wc": 1, "lavatory": 1, "shower": 1, "kitchen_sink": 1,
                   "laundry_sink": 1}

# Qué muebles reciben agua caliente (práctica: el WC y el lavadero no).
CON_AGUA_CALIENTE = {"lavatory", "shower", "kitchen_sink"}

# Diámetro de tubería de agua por UM acumuladas, sin fluxómetro:
# [INIFED] Tabla 2.3. Hasta N UM -> diámetro en mm.
DIAMETRO_AGUA = [(1, 13), (4, 19), (8, 25), (14, 32), (28, 38), (55, 50),
                 (95, 64), (250, 75)]

NOMBRES_MUEBLE = {"wc": "WC", "lavatory": "LAVABO", "shower": "REGADERA",
                  "kitchen_sink": "FREGADERO", "laundry_sink": "LAVADERO"}

# Capas (nomenclatura de instalaciones; colores de la paleta del proyecto,
# nunca los puros 1-6, CLAUDE.md 6.ter).
CAPA_AF = "IH-AGUA-FRIA"
CAPA_AC = "IH-AGUA-CALIENTE"
CAPA_HID_SIMB = "IH-SIMBOLOS"
CAPA_DRENAJE = "IS-DRENAJE"
CAPA_REGISTRO = "IS-REGISTROS"
CAPA_TEXTO_INST = "I-TEXTOS"
COLOR_AF = 152       # azul acero
COLOR_AC = 12        # rojo oscuro
COLOR_DRENAJE = 32   # ámbar oscuro (café en papel)
COLOR_REGISTRO = 172

MUEBLES_SANITARIOS = set(DESCARGA_MM)


# ----------------------------------------------------------- utilidades

def _ensure(capa: str, color: int, grosor: int, tipo: Optional[str] = None) -> None:
    layers.ensure(capa, color, grosor, tipo)
    layers.ensure_text_style()


def _linea(p: tuple, q: tuple, capa: str, grosor: int = 30) -> str:
    return acad.call("create_line", {
        "x1": p[0], "y1": p[1], "z1": 0.0, "x2": q[0], "y2": q[1], "z2": 0.0,
        "layer": capa, "lineweight": grosor, "colorIndex": None})["handle"]


def _circulo(c: tuple, r: float, capa: str, grosor: int = 25) -> str:
    return acad.call("create_circle", {
        "x": c[0], "y": c[1], "z": 0.0, "radius": r, "layer": capa,
        "lineweight": grosor, "colorIndex": None})["handle"]


def _rect(x0: float, y0: float, x1: float, y1: float, capa: str,
          grosor: int = 25) -> str:
    return acad.call("create_polyline", {
        "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "closed": True,
        "layer": capa, "lineweight": grosor, "colorIndex": None})["handle"]


def _texto(t: str, x: float, y: float, h: float, capa: str,
           rot: float = 0.0) -> str:
    return acad.call("create_text", {
        "text": t, "x": x, "y": y, "z": 0.0, "height": h, "layer": capa,
        "rotationDeg": rot, "lineweight": 18, "colorIndex": None})["handle"]


def _cajas_utiles(rooms: list[dict[str, Any]], ext: float, inter: float
                  ) -> dict[str, tuple[float, float, float, float]]:
    """Caja útil (cara interior de muros) de cada recinto."""
    bx0 = min(r["x0"] for r in rooms)
    bx1 = max(r["x1"] for r in rooms)
    by0 = min(r["y0"] for r in rooms)
    by1 = max(r["y1"] for r in rooms)

    def medio(c: float, lo: float, hi: float) -> float:
        return (ext if abs(c - lo) < 1e-6 or abs(c - hi) < 1e-6 else inter) / 2.0
    return {r["name"]: (r["x0"] + medio(r["x0"], bx0, bx1),
                        r["y0"] + medio(r["y0"], by0, by1),
                        r["x1"] - medio(r["x1"], bx0, bx1),
                        r["y1"] - medio(r["y1"], by0, by1)) for r in rooms}


def _muebles(rooms: list[dict[str, Any]], doors: Optional[list[dict[str, Any]]],
             fixtures: Optional[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Muebles sanitarios con su punto de conexión y su recinto. Sin
    'fixtures' se toman los que pone suggest_furniture (determinístico: los
    mismos que dibujó)."""
    if fixtures is None:
        fixtures = furniture.suggest_furniture(rooms, doors, draw=False)["items"]
    salida = []
    for f in fixtures:
        if f.get("type") not in MUEBLES_SANITARIOS:
            continue
        p = geo.conexion(f)
        salida.append({**f, "conexion": p,
                       "room": f.get("room") or geo.recinto_de(p, rooms)})
    return salida


def _diametro_agua(um: float) -> int:
    for limite, d in DIAMETRO_AGUA:
        if um <= limite:
            return d
    return DIAMETRO_AGUA[-1][1]


def _paper(mm: float) -> float:
    return space.paper(mm)


# ============================================================ ELÉCTRICA

def _puerta_principal(nombre: str, doors: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """La puerta por la que se entra al recinto (la de la circulación)."""
    propias = [d for d in doors or []
               if nombre.upper() in (str(d.get("to", "")).upper(),
                                     str(d.get("from", "")).upper())
               and not d.get("open")]
    if not propias:
        return None
    for pref in ("PASILLO", "EXTERIOR", "SALA", "COMEDOR"):
        for d in propias:
            otro = d["from"] if str(d["to"]).upper() == nombre.upper() else d["to"]
            if pref in str(otro).upper():
                return d
    return propias[0]


def _junto_a_puerta(nombre: str, caja: tuple, doors: list[dict[str, Any]],
                    huecos: list) -> tuple[dict[str, Any], float]:
    """El tramo libre de muro más cercano a la puerta del recinto y el punto
    (a lo largo del tramo) a 0.25 m del canto de la puerta. Sin puerta, el
    centro del tramo más largo."""
    tramos = geo.tramos_de_muro(caja, huecos)
    puerta = _puerta_principal(nombre, doors)
    if not puerta:
        t = max(tramos, key=lambda t: t["a1"] - t["a0"])
        return t, (t["a0"] + t["a1"]) / 2.0
    p = (puerta["x"], puerta["y"])
    t = min(tramos, key=lambda t: min(math.dist(t["punto"](t["a0"]), p),
                                      math.dist(t["punto"](t["a1"]), p)))
    if math.dist(t["punto"](t["a0"]), p) <= math.dist(t["punto"](t["a1"]), p):
        a = min(t["a0"] + 0.25, (t["a0"] + t["a1"]) / 2.0)
    else:
        a = max(t["a1"] - 0.25, (t["a0"] + t["a1"]) / 2.0)
    return t, a


def _lado_de_puerta(d: dict[str, Any], caja: tuple) -> str:
    x0, y0, x1, y1 = caja
    dist = {"bottom": abs(d["y"] - y0), "top": abs(d["y"] - y1),
            "left": abs(d["x"] - x0), "right": abs(d["x"] - x1)}
    return min(dist, key=dist.get)


def _huecos(nombre: str, caja: tuple, doors: list[dict[str, Any]]) -> list[tuple[str, float, float]]:
    salida = []
    for d in doors or []:
        if nombre.upper() not in (str(d.get("to", "")).upper(),
                                  str(d.get("from", "")).upper()):
            continue
        lado = _lado_de_puerta(d, caja)
        a = d["x"] if lado in ("bottom", "top") else d["y"]
        w = float(d.get("width", 0.8)) / 2.0
        salida.append((lado, a - w - 0.05, a + w + 0.05))
    return salida


def _contactos_en_muros(caja: tuple, huecos: list, separacion: float,
                        minimo: float) -> list[tuple[float, float, float]]:
    """Contactos a lo largo de los muros libres: el primero a la mitad de
    la separación del arranque de cada tramo y después cada 'separacion',
    así ningún punto del muro queda a más de separacion/2 de uno."""
    salida = []
    for t in geo.tramos_de_muro(caja, huecos):
        largo = t["a1"] - t["a0"]
        if largo < minimo:
            continue
        n = max(1, math.ceil(largo / separacion))
        paso = largo / n
        for k in range(n):
            a = t["a0"] + paso * (k + 0.5)
            x, y = t["punto"](a)
            salida.append((x, y, t["hacia"]))
    return salida


def suggest_electrical(rooms: list[dict[str, Any]],
                       doors: Optional[list[dict[str, Any]]] = None,
                       fixtures: Optional[list[dict[str, Any]]] = None,
                       panel_room: Optional[str] = None,
                       draw: bool = True,
                       exterior_thickness: float = 0.15,
                       interior_thickness: float = 0.10,
                       table_x: Optional[float] = None,
                       table_y: Optional[float] = None,
                       legend: bool = True,
                       legend_x: Optional[float] = None,
                       legend_y: Optional[float] = None,
                       notes: Optional[list[str]] = None) -> dict[str, Any]:
    """Instalación eléctrica de la vivienda según la NOM-001-SEDE-2012."""
    doors = doors or []
    cajas = _cajas_utiles(rooms, exterior_thickness, interior_thickness)
    muebles = _muebles(rooms, doors, fixtures)
    sep = 2.0 * NORMA["contacto_max_m"]
    devices: list[dict[str, Any]] = []
    cargas: list[dict[str, Any]] = []      # una por salida, para los circuitos
    avisos: list[str] = []

    def agregar(tipo: str, x: float, y: float, ang: float, room: str,
                grupo: str, va: float) -> None:
        devices.append({"type": tipo, "x": round(x, 4), "y": round(y, 4),
                        "angle": ang, "tag": f"{room}"})
        cargas.append({"tipo": tipo, "x": x, "y": y, "room": room,
                       "grupo": grupo, "va": va})

    for r in rooms:
        nombre = r["name"]
        u = nombre.upper()
        caja = cajas[nombre]
        x0, y0, x1, y1 = caja
        area = (r["x1"] - r["x0"]) * (r["y1"] - r["y0"])
        exterior = "PATIO" in u or "COCHERA" in u or "JARDIN" in u
        # --- alumbrado: 33 VA/m² repartidos en sus salidas (Tabla 220-12).
        # Una salida de centro por recinto, dos si es grande o alargado
        # (práctica de proyecto).
        largo, ancho = max(x1 - x0, y1 - y0), min(x1 - x0, y1 - y0)
        n_luz = 1 if (area <= 16 and largo <= 2.2 * ancho) else 2
        if "PASILLO" in u:
            n_luz = max(1, round(largo / 3.5))
        # Tabla 220-12 es para el área de la VIVIENDA; una salida exterior
        # (patio, cochera) se toma a 180 VA (220-14(l)).
        va_luz = (NORMA["va_contacto"] if exterior
                  else NORMA["va_m2_alumbrado"] * area / n_luz)
        huecos = _huecos(nombre, caja, doors)
        if exterior:
            # En el patio todo va sobre la FACHADA de la casa, junto a la
            # puerta que da a él: un arbotante y el contacto de 210-52(e)
            # ("atrás" es atrás de la VIVIENDA, no la barda del fondo). En
            # la barda quedaban a 11 m y la canalización cruzaba el patio
            # entero en una V.
            t, a = _junto_a_puerta(nombre, caja, doors, huecos)
            lx, ly = t["punto"](a)
            ang = math.radians(t["hacia"])
            agregar("lamp", lx + 0.35 * math.cos(ang), ly + 0.35 * math.sin(ang),
                    0.0, nombre, "alumbrado", va_luz)
            b_ = a + 0.9 if a + 0.9 <= t["a1"] - 0.15 else max(t["a0"] + 0.15, a - 0.9)
            x, y = t["punto"](b_)
            agregar("gfci", x, y, t["hacia"], nombre, "general", NORMA["va_contacto_general_vivienda"])
            n_luz = 0
        for k in range(n_luz):
            f = (k + 0.5) / n_luz
            if (x1 - x0) >= (y1 - y0):
                cx, cy = x0 + (x1 - x0) * f, (y0 + y1) / 2.0
            else:
                cx, cy = (x0 + x1) / 2.0, y0 + (y1 - y0) * f
            agregar("lamp", cx, cy, 0.0, nombre, "alumbrado", va_luz)

        # --- apagador junto a la puerta, del lado con más muro, adentro.
        puerta = _puerta_principal(nombre, doors)
        if puerta:
            lado = _lado_de_puerta(puerta, caja)
            w = float(puerta.get("width", 0.8)) / 2.0
            if lado in ("bottom", "top"):
                izq = puerta["x"] - x0
                der = x1 - puerta["x"]
                ax = puerta["x"] + (w + 0.20) * (1 if der >= izq else -1)
                ay = y0 + 0.10 if lado == "bottom" else y1 - 0.10
                ang = 90.0 if lado == "bottom" else 270.0
            else:
                abajo = puerta["y"] - y0
                arriba = y1 - puerta["y"]
                ay = puerta["y"] + (w + 0.20) * (1 if arriba >= abajo else -1)
                ax = x0 + 0.10 if lado == "left" else x1 - 0.10
                ang = 0.0 if lado == "left" else 180.0
            devices.append({"type": "switch", "x": round(ax, 4),
                            "y": round(ay, 4), "angle": ang, "tag": nombre})

        # --- contactos
        if "BAÑO" in u or "BANO" in u:
            # 210-52(d): al menos uno a no más de 900 mm del lavabo, con
            # falla a tierra (210-8(a)(1)).
            lav = [m for m in muebles if m["type"] == "lavatory" and m["room"] == nombre]
            if lav:
                cx, cy = lav[0]["conexion"]
                lado = min(("bottom", "top", "left", "right"),
                           key=lambda s: {"bottom": abs(cy - y0), "top": abs(cy - y1),
                                          "left": abs(cx - x0), "right": abs(cx - x1)}[s])
                d = 0.45
                if lado in ("bottom", "top"):
                    px = cx + d if cx + d < x1 - 0.1 else cx - d
                    py, ang = (y0, 90.0) if lado == "bottom" else (y1, 270.0)
                else:
                    py = cy + d if cy + d < y1 - 0.1 else cy - d
                    px, ang = (x0, 0.0) if lado == "left" else (x1, 180.0)
                agregar("gfci", px, py, ang, nombre, "baño", NORMA["va_contacto"])
            continue
        if "PASILLO" in u:
            if largo >= NORMA["pasillo_min_m"]:
                t = max(geo.tramos_de_muro(caja, huecos), key=lambda t: t["a1"] - t["a0"])
                x, y = t["punto"]((t["a0"] + t["a1"]) / 2.0)
                agregar("outlet", x, y, t["hacia"], nombre, "general", NORMA["va_contacto_general_vivienda"])
            continue
        if "LAVADO" in u or "LAVANDER" in u:
            # 210-52(f) y 210-11(c)(2): contacto de lavado en su circuito de
            # 20 A; con falla a tierra por estar junto al lavadero (210-8).
            lv = [m for m in muebles if m["type"] == "laundry_sink" and m["room"] == nombre]
            ref = lv[0]["conexion"] if lv else ((x0 + x1) / 2.0, y0)
            t = min(geo.tramos_de_muro(caja, huecos),
                    key=lambda t: math.dist(t["punto"]((t["a0"] + t["a1"]) / 2), ref))
            a = min(max((ref[0] if t["lado"] in ("bottom", "top") else ref[1]) + 0.9,
                        t["a0"] + 0.15), t["a1"] - 0.15)
            x, y = t["punto"](a)
            agregar("gfci", x, y, t["hacia"], nombre, "lavado", NORMA["va_circuito_20a"])
            continue
        if exterior:
            continue        # su contacto ya quedó junto a la puerta
        cocina = "COCINA" in u
        for x, y, ang in _contactos_en_muros(
                caja, huecos, NORMA["cubierta_max_m"] * 2 if cocina else sep,
                NORMA["muro_min_contacto_m"]):
            if cocina:
                # 210-52(c) y 210-8(a)(6): sobre la cubierta, con falla a
                # tierra; van a los circuitos de pequeños aparatos (20 A).
                agregar("gfci", x, y, ang, nombre, "cocina", NORMA["va_contacto"])
            elif "COMEDOR" in u:
                agregar("outlet", x, y, ang, nombre, "cocina", NORMA["va_contacto"])
            else:
                agregar("outlet", x, y, ang, nombre, "general", NORMA["va_contacto_general_vivienda"])

    # --- 210-52(e): contacto exterior también AL FRENTE (el de atrás es el
    # del patio), con falla a tierra, junto al acceso por fuera.
    frente = next((d for d in doors if str(d.get("from", "")).upper() == "EXTERIOR"), None)
    if frente:
        y_fachada = min(r["y0"] for r in rooms) - exterior_thickness / 2.0
        agregar("gfci", frente["x"] + float(frente.get("width", 0.9)) / 2.0 + 0.5,
                y_fachada, 270.0, "EXTERIOR (FRENTE)", "general", NORMA["va_contacto_general_vivienda"])

    # --- tablero: junto al acceso, adentro.
    acceso = next((d for d in doors if str(d.get("from", "")).upper() == "EXTERIOR"), None)
    destino = panel_room or (acceso["to"] if acceso else rooms[0]["name"])
    caja_t = cajas[destino]
    if acceso and str(acceso.get("to")) == destino:
        lado = _lado_de_puerta(acceso, caja_t)
        w = float(acceso.get("width", 0.9)) / 2.0
        if lado in ("bottom", "top"):
            tx = acceso["x"] - w - 0.45 if acceso["x"] - w - 0.45 > caja_t[0] + 0.3 else acceso["x"] + w + 0.45
            ty = caja_t[1] + 0.08 if lado == "bottom" else caja_t[3] - 0.08
            tang = 0.0
        else:
            ty = acceso["y"] - w - 0.45
            tx = caja_t[0] + 0.08 if lado == "left" else caja_t[2] - 0.08
            tang = 90.0
    else:
        tx, ty, tang = caja_t[0] + 0.5, caja_t[1] + 0.08, 0.0
    tablero = {"type": "panel", "x": round(tx, 4), "y": round(ty, 4),
               "angle": tang, "tag": "TABLERO"}
    devices.append(tablero)

    circuitos = _armar_circuitos(cargas, (tx, ty))
    cuadro = _cuadro_de_cargas(circuitos)
    cuadro["service"] = _carga_servicio(rooms, circuitos)
    resultado: dict[str, Any] = {
        "devices": devices, "circuits": circuitos, "loadTable": cuadro,
        "panel": {"x": tx, "y": ty, "room": destino},
        "criteria": {k: NORMA[k] for k in ("contacto_max_m", "cubierta_max_m",
                                           "va_m2_alumbrado", "va_contacto")},
    }
    if draw:
        resultado.update(_dibujar_electrica(devices, circuitos, (tx, ty), cuadro,
                                            rooms, table_x, table_y))
        if legend:
            resultado["legend"] = _leyenda_auto("electrica", rooms, legend_x, legend_y, notes)
    if avisos:
        resultado["warnings"] = avisos
    return resultado


def _armar_circuitos(cargas: list[dict[str, Any]], tablero: tuple) -> list[dict[str, Any]]:
    """Circuitos derivados:
    - pequeños aparatos de cocina/comedor: DOS de 20 A (210-11(c)(1))
    - lavado: uno de 20 A (210-11(c)(2))
    - contactos de baño: uno de 20 A (210-11(c)(3))
    - alumbrado y contactos generales: de 15 A, sin pasar el 80 % de su
      capacidad (210-19/210-20), agrupando por cercanía.
    """
    v, f = NORMA["tension_v"], NORMA["factor_continua"]
    circuitos: list[dict[str, Any]] = []

    def nuevo(nombre: str, amp: int, salidas: list[dict[str, Any]]) -> None:
        if not salidas:
            return
        va = sum(s["va"] for s in salidas)
        circuitos.append({"name": nombre, "amps": amp,
                          "awg": NORMA["calibre_awg"][amp],
                          "outlets": salidas, "va": round(va, 1),
                          "current": round(va / v, 2)})

    cocina = [c for c in cargas if c["grupo"] == "cocina"]
    nuevo("PA-1", 20, cocina[0::2])
    nuevo("PA-2", 20, cocina[1::2])
    nuevo("LAV", 20, [c for c in cargas if c["grupo"] == "lavado"])
    nuevo("BAÑO", 20, [c for c in cargas if c["grupo"] == "baño"])

    resto = [c for c in cargas if c["grupo"] in ("alumbrado", "general")]
    limite = 15 * v * f
    # Por RECINTOS COMPLETOS, recorriendo la casa desde el tablero: un
    # circuito que salta de un cuarto al de enfrente se canaliza cruzando
    # media casa (visto en AutoCAD: arcos de 15 m de punta a punta). Si un
    # recinto solo no entra en un circuito, se parte.
    por_recinto: dict[str, list[dict[str, Any]]] = {}
    for c in resto:
        por_recinto.setdefault(c["room"], []).append(c)

    def centro(salidas: list[dict[str, Any]]) -> tuple[float, float]:
        return (sum(s["x"] for s in salidas) / len(salidas),
                sum(s["y"] for s in salidas) / len(salidas))

    pendientes = dict(por_recinto)
    n = 1
    actual: list[dict[str, Any]] = []
    ref = tablero
    while pendientes:
        nombre = min(pendientes, key=lambda k: math.dist(centro(pendientes[k]), ref))
        salidas = pendientes.pop(nombre)
        va = sum(s["va"] for s in salidas)
        if actual and sum(s["va"] for s in actual) + va > limite:
            nuevo(f"C-{n}", 15, actual)
            n += 1
            actual = []
        for s_ in salidas:
            if actual and sum(x["va"] for x in actual) + s_["va"] > limite:
                nuevo(f"C-{n}", 15, actual)
                n += 1
                actual = []
            actual.append(s_)
        ref = centro(salidas)
    nuevo(f"C-{n}", 15, actual)
    return circuitos


def _carga_servicio(rooms: list[dict[str, Any]],
                    circuitos: list[dict[str, Any]]) -> dict[str, Any]:
    """Carga del servicio de la vivienda: alumbrado general 33 VA/m² sobre
    el área techada (Tabla 220-12, que en vivienda ya incluye los contactos
    de uso general, 220-14(j)) + 1500 VA por circuito de pequeños aparatos y
    de lavado (220-52), con la demanda de 220-42."""
    techada = sum((r["x1"] - r["x0"]) * (r["y1"] - r["y0"]) for r in rooms
                  if "PATIO" not in r["name"].upper())
    alumbrado = NORMA["va_m2_alumbrado"] * techada
    especiales = NORMA["va_circuito_20a"] * sum(
        1 for c in circuitos if c["name"].startswith(("PA-", "LAV")))
    instalada = alumbrado + especiales
    tope = NORMA["demanda_100_va"]
    demandada = min(instalada, tope) + max(0.0, instalada - tope) * NORMA["demanda_resto"]
    return {"area_m2": round(techada, 2), "lighting_va": round(alumbrado, 1),
            "appliance_va": round(especiales, 1), "installed_va": round(instalada, 1),
            "demand_va": round(demandada, 1),
            "demand_a": round(demandada / NORMA["tension_v"], 2)}


def _cuadro_de_cargas(circuitos: list[dict[str, Any]]) -> dict[str, Any]:
    filas = []
    for c in circuitos:
        luces = [s for s in c["outlets"] if s["tipo"] == "lamp"]
        conts = [s for s in c["outlets"] if s["tipo"] != "lamp"]
        filas.append([c["name"], str(len(luces)),
                      f"{sum(s['va'] for s in luces):.0f}", str(len(conts)),
                      f"{sum(s['va'] for s in conts):.0f}", f"{c['va']:.0f}",
                      f"{c['current']:.2f}", f"1P-{c['amps']} A",
                      f"{c['awg']} AWG"])
    total = sum(c["va"] for c in circuitos)
    return {"header": ["CIRCUITO", "SAL. ALUMB.", "VA ALUMB.", "CONTACTOS",
                       "VA CONT.", "VA TOTAL", "I (A)", "PROTECCIÓN", "CALIBRE"],
            "rows": filas, "totalVA": round(total, 1),
            "totalA": round(total / NORMA["tension_v"], 2)}


def _dibujar_electrica(devices, circuitos, tablero, cuadro, rooms,
                       table_x, table_y) -> dict[str, Any]:
    r = electrical.place_devices(devices)
    import annotation
    # Canalización como la traza un proyectista: dentro de cada circuito
    # las salidas se unen por el árbol MÁS CORTO (Prim), en arco suave
    # (recta se confunde con la muraria), y la llegada al tablero NO se
    # dibuja de punta a punta: sale una flecha de retorno con el número de
    # circuito desde la salida más cercana. Antes se encadenaba todo desde
    # el tablero y quedaban arcos de 15 m cruzando la casa.
    canal = []
    etiquetas: list[dict[str, Any]] = []
    h = _paper(2.0)
    _ensure(CAPA_TEXTO_INST, 7, 18)
    for c in circuitos:
        pts = [(s["x"], s["y"]) for s in c["outlets"]]
        dentro, fuera = [0], list(range(1, len(pts)))
        aristas = []
        while fuera:
            i, j = min(((i, j) for i in dentro for j in fuera),
                       key=lambda ij: math.dist(pts[ij[0]], pts[ij[1]]))
            aristas.append((pts[i], pts[j]))
            dentro.append(j)
            fuera.remove(j)
        for a, b in aristas:
            largo = math.dist(a, b)
            if largo < 0.25:
                continue
            canal.append(electrical.create_conduit(
                [[a[0], a[1]], [b[0], b[1]]], sag=min(0.10, 0.30 / largo),
                conductors="/|T"))
        # Retorno al tablero.
        cerca = min(pts, key=lambda p: math.dist(p, tablero))
        d = math.dist(cerca, tablero)
        if d <= 3.0:
            canal.append(electrical.create_conduit(
                [[cerca[0], cerca[1]], [tablero[0], tablero[1]]],
                sag=min(0.10, 0.30 / max(d, 0.3)), conductors="/|T"))
            punta = cerca
        else:
            ux, uy = (tablero[0] - cerca[0]) / d, (tablero[1] - cerca[1]) / d
            punta = (cerca[0] + ux * 0.8, cerca[1] + uy * 0.8)
            _linea(cerca, punta, electrical.LAYER_OUTLET, 25)
            try:
                annotation.create_flow_arrow(points=[list(cerca), list(punta)],
                                             positions=[0.8], size=_paper(2.5),
                                             layer=electrical.LAYER_OUTLET)
            except Exception:                           # noqa: BLE001
                pass
        etiquetas.append({"text": c["name"],
                          "box": [punta[0] - 0.05, punta[1] - 0.05, punta[0] + 0.05, punta[1] + 0.05]})
    if etiquetas:
        annotation.place_labels(etiquetas, height=h, layer=CAPA_TEXTO_INST)
    # Cuadro de cargas a la derecha de la planta.
    bx1 = max(r_["x1"] for r_ in rooms)
    by1 = max(r_["y1"] for r_ in rooms)
    serv = cuadro.get("service", {})
    filas = [cuadro["header"]] + cuadro["rows"] + [
        ["TOTAL", "", "", "", "", f"{cuadro['totalVA']:.0f}",
         f"{cuadro['totalA']:.2f}", "", ""],
        ["SERVICIO", f"{serv.get('area_m2', 0):.1f} m2", "x33 VA/m2",
         "+1500 c/PA y LAV", "", f"{serv.get('installed_va', 0):.0f}",
         "", "DEMANDA 220-42", f"{serv.get('demand_va', 0):.0f} VA"]]
    tabla = annotation.create_table(
        table_x if table_x is not None else bx1 + 2.0,
        table_y if table_y is not None else by1, filas,
        # Ancho de cada columna según su texto más largo (2 mm de letra,
        # arial ~0.87 de ancho por alto, más aire).
        col_widths=[_paper(max(len(str(f[i])) for f in filas) * 2.0 * 0.95 + 4.0)
                    for i in range(len(filas[0]))],
        text_height=0,
        title="CUADRO DE CARGAS (NOM-001-SEDE-2012)", layer=CAPA_TEXTO_INST)
    return {"drawn": r["count"], "conduits": len(canal), "table": tabla}


# ============================================================ HIDRÁULICA

def suggest_hydraulic(rooms: list[dict[str, Any]],
                      doors: Optional[list[dict[str, Any]]] = None,
                      fixtures: Optional[list[dict[str, Any]]] = None,
                      supply: Optional[list[float]] = None,
                      heater: Optional[list[float]] = None,
                      draw: bool = True,
                      legend: bool = True,
                      legend_x: Optional[float] = None,
                      legend_y: Optional[float] = None,
                      notes: Optional[list[str]] = None) -> dict[str, Any]:
    """Agua fría y caliente a cada mueble, con diámetros por unidades mueble.

    Sistema por gravedad, el usual en vivienda mexicana: la toma municipal y
    el medidor al frente suben al tinaco (SAF); el tinaco BAJA (BAF) y
    alimenta la casa. El calentador sale de la red fría y alimenta el agua
    caliente.

    supply: punto de la bajada del tinaco (BAF). Por defecto, sobre el muro
    del patio más cercano a los muebles. heater: punto del calentador; por
    defecto, en el patio de servicio junto a la BAF."""
    muebles = _muebles(rooms, doors, fixtures)
    if not muebles:
        raise ValueError("No hay muebles sanitarios: amuebla los baños, la "
                         "cocina y el lavado antes (suggest_furniture).")
    patio = next((r for r in rooms if "PATIO" in r["name"].upper()), None)
    cx = sum(m["conexion"][0] for m in muebles) / len(muebles)
    if supply is None:
        if patio:
            supply = [min(max(cx, patio["x0"] + 0.4), patio["x1"] - 0.4), patio["y0"] + 0.25]
        else:
            supply = [cx, max(r["y1"] for r in rooms) - 0.25]
    if heater is None:
        heater = [supply[0] + 1.0, supply[1] + 0.35]
    baf = (float(supply[0]), float(supply[1]))
    cal = (float(heater[0]), float(heater[1]))

    for i, m in enumerate(muebles):
        m["_id"] = i
    fria = geo.red_en_arbol(baf, [(m["conexion"], 0.0, m) for m in muebles]
                            + [(cal, 0.0, "calentador")])
    caliente = geo.red_en_arbol(cal, [(m["conexion"], 0.0, m) for m in muebles
                                      if m["type"] in CON_AGUA_CALIENTE])
    con_ac = [m for m in muebles if m["type"] in CON_AGUA_CALIENTE]

    def describir(red: geo.Red, es_fria: bool) -> list[dict[str, Any]]:
        """La UM de un tramo cuenta cada mueble UNA vez: un lavabo que
        recibe fría y caliente pesa lo mismo aguas arriba que uno que solo
        recibe fría. El tramo que va al calentador sirve a todos los
        muebles con agua caliente."""
        salida = []
        for t in red.tramos():
            abajo = red.aguas_abajo(t["nodo"])
            servidos = {m["_id"]: m for m in abajo if isinstance(m, dict)}
            if es_fria and "calentador" in abajo:
                servidos.update({m["_id"]: m for m in con_ac})
            um = sum(UNIDADES_MUEBLE[m["type"]] for m in servidos.values())
            salida.append({**t, "carga": um, "diametro_mm": _diametro_agua(um)})
        return salida

    tramos_f, tramos_c = describir(fria, True), describir(caliente, False)
    avisos = [f"El tinaco va con su salida al menos {NORMA['tinaco_sobre_regadera_m']:g} m "
              "por encima de la regadera más alta (NTC 6.1.2): con menos, no hay "
              "presión en la regadera."]
    lejos = max((abs(m["conexion"][0] - cal[0]) + abs(m["conexion"][1] - cal[1]), m["room"])
                for m in muebles if m["type"] in CON_AGUA_CALIENTE) \
        if any(m["type"] in CON_AGUA_CALIENTE for m in muebles) else (0.0, "")
    if lejos[0] > NORMA["retorno_ac_m"]:
        avisos.append(f"El mueble con agua caliente más lejano ({lejos[1]}) está a "
                      f"{lejos[0]:.1f} m del calentador: más de "
                      f"{NORMA['retorno_ac_m']:g} m pide línea de retorno (INIFED §2.8).")
    resultado: dict[str, Any] = {
        "supply": list(baf), "heater": list(cal),
        "fixtures": [{"type": m["type"], "room": m["room"],
                      "point": [round(v, 3) for v in m["conexion"]],
                      "um": UNIDADES_MUEBLE[m["type"]],
                      "hot": m["type"] in CON_AGUA_CALIENTE} for m in muebles],
        "coldPipes": [_tramo_publico(t) for t in tramos_f],
        "hotPipes": [_tramo_publico(t) for t in tramos_c],
        "totalUM": sum(UNIDADES_MUEBLE[m["type"]] for m in muebles),
        "warnings": avisos,
        "criteria": {"unidades_mueble": UNIDADES_MUEBLE,
                     "diametro_por_um": DIAMETRO_AGUA},
    }
    if draw:
        resultado.update(_dibujar_hidraulica(tramos_f, tramos_c, baf, cal, muebles))
        if legend:
            resultado["legend"] = _leyenda_auto("hidraulica", rooms, legend_x, legend_y, notes)
    return resultado


def _tramo_publico(t: dict[str, Any]) -> dict[str, Any]:
    salida = {"from": [round(v, 3) for v in t["desde"]],
              "to": [round(v, 3) for v in t["hasta"]],
              "length": round(t["largo"], 3), "load": round(t["carga"], 2)}
    if "diametro_mm" in t:
        salida["diameter_mm"] = t["diametro_mm"]
    return salida


def _rotulos_diametro(tramos, prefijo: str, capa: str, desplaz: float) -> list[dict[str, Any]]:
    """Un rótulo de diámetro por tramo largo, a un costado de la línea."""
    labels = []
    for t in tramos:
        if t["largo"] < 0.9:
            continue
        a, b = t["desde"], t["hasta"]
        mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        vertical = abs(a[0] - b[0]) < 1e-9
        labels.append({"text": f"{prefijo} Ø{t['diametro_mm']}",
                       "x": mx + (desplaz if vertical else 0.0),
                       "y": my + (0.0 if vertical else desplaz),
                       "rotation": 90.0 if vertical else 0.0})
    return labels


def _dibujar_hidraulica(tramos_f, tramos_c, baf, cal, muebles) -> dict[str, Any]:
    # Más gruesas que la muraria (50): corren junto a los muros y con el
    # mismo grosor se perdían sobre sus líneas (visto en AutoCAD).
    _ensure(CAPA_AF, COLOR_AF, 50)
    _ensure(CAPA_AC, COLOR_AC, 50, layers.LT_OCULTO)
    _ensure(CAPA_HID_SIMB, 8, 25)
    _ensure(CAPA_TEXTO_INST, 7, 18)
    # El agua caliente corre 12 cm corrida de la fría: encimadas no se leen.
    off = 0.12
    for t in tramos_f:
        _linea(t["desde"], t["hasta"], CAPA_AF, 50)
    for t in tramos_c:
        a, b = t["desde"], t["hasta"]
        if abs(a[0] - b[0]) < 1e-9:
            a, b = (a[0] + off, a[1]), (b[0] + off, b[1])
        else:
            a, b = (a[0], a[1] + off), (b[0], b[1] + off)
        _linea(a, b, CAPA_AC, 50)
    h = _paper(1.8)
    # Símbolos: BAF (círculo con texto), calentador (rectángulo CAL),
    # salida en cada mueble (círculo chico).
    _circulo(baf, 0.15, CAPA_HID_SIMB)
    _rect(cal[0] - 0.25, cal[1] - 0.25, cal[0] + 0.25, cal[1] + 0.25, CAPA_HID_SIMB)
    simbolos = [{"text": "BAF", "box": [baf[0] - 0.15, baf[1] - 0.15, baf[0] + 0.15, baf[1] + 0.15]},
                {"text": "CAL", "box": [cal[0] - 0.25, cal[1] - 0.25, cal[0] + 0.25, cal[1] + 0.25]}]
    for m in muebles:
        _circulo(m["conexion"], 0.06, CAPA_HID_SIMB)
    import annotation
    rot = simbolos + (_rotulos_diametro(tramos_f, "AF", CAPA_AF, 0.15)
           + _rotulos_diametro(tramos_c, "AC", CAPA_AC, -0.15))
    lab = annotation.place_labels(rot, height=h, layer=CAPA_TEXTO_INST) if rot else {}
    return {"coldSegments": len(tramos_f), "hotSegments": len(tramos_c),
            "labels": len(rot), "cramped": len(lab.get("cramped", []))}


# ============================================================ SANITARIA

def suggest_sanitary(rooms: list[dict[str, Any]],
                     doors: Optional[list[dict[str, Any]]] = None,
                     fixtures: Optional[list[dict[str, Any]]] = None,
                     outlet: Optional[list[float]] = None,
                     draw: bool = True,
                     legend: bool = True,
                     legend_x: Optional[float] = None,
                     legend_y: Optional[float] = None,
                     notes: Optional[list[str]] = None) -> dict[str, Any]:
    """Desagüe de cada mueble hasta la red municipal.

    Diámetro de cada tramo = el mayor de lo que drena (un WC aguas arriba
    lo lleva a 100 mm); albañal hasta la calle de 150 mm como mínimo;
    pendiente mínima 2 %; registros en cada cambio de dirección o unión de
    ramales del albañal y a no más de 10 m entre sí.

    outlet: punto de conexión a la red municipal (sobre el frente). Por
    defecto, en el paramento del frente alineado con los muebles."""
    muebles = _muebles(rooms, doors, fixtures)
    if not muebles:
        raise ValueError("No hay muebles sanitarios: amuebla los baños, la "
                         "cocina y el lavado antes (suggest_furniture).")
    y_frente = min(r["y0"] for r in rooms)
    if outlet is None:
        cx = sum(m["conexion"][0] for m in muebles) / len(muebles)
        outlet = [cx, y_frente]
    salida = (float(outlet[0]), float(outlet[1]))
    # El registro de conexión va adentro del predio, a 0.60 del paramento.
    reg_final = (salida[0], salida[1] + 0.6)
    red = geo.red_en_arbol(reg_final, [(m["conexion"], 0.0, m) for m in muebles])

    tramos = []
    for t in red.tramos():
        abajo = red.aguas_abajo(t["nodo"])
        # El mayor entre la boca del mueble más grande que drena y lo que
        # pide la suma de unidades de descarga (INIFED Tabla 3.3).
        ud = sum(UNIDADES_DESCARGA[m["type"]] for m in abajo)
        por_ud = next((d for lim, d in DIAMETRO_RAMAL if ud <= lim), 150)
        diam = max(max(DESCARGA_MM[m["type"]] for m in abajo), por_ud,
                   NORMA["desague_min_mm"])
        tramos.append({**t, "diametro_mm": diam, "ud": ud,
                       "drena": sorted({NOMBRES_MUEBLE[m["type"]] for m in abajo})})
    # Albañal: lo que lleva WC es la línea principal.
    principal = [t for t in tramos if t["diametro_mm"] >= 100]

    registros = _registros(red, principal, reg_final)
    for r in registros:
        local = geo.recinto_de(tuple(r["point"]), rooms)
        # [NTC] 6.1.3.2-VII: registro bajo un local habitable, doble tapa.
        if local and "PATIO" not in local.upper() and "COCHERA" not in local.upper():
            r["double_lid"] = True
            r["room"] = local
    # [NTC] 6.1.3.2-III: tubo ventilador en el ORIGEN del albañal: el WC
    # más alejado de la descarga.
    wcs = [m for m in muebles if m["type"] == "wc"]
    ventilador = None
    if wcs:
        lejos = max(wcs, key=lambda m: abs(m["conexion"][0] - reg_final[0])
                    + abs(m["conexion"][1] - reg_final[1]))
        ventilador = {"point": [round(v, 3) for v in lejos["conexion"]],
                      "diameter_mm": NORMA["ventilador_min_mm"],
                      "room": lejos["room"]}
    albanal = {"from": list(reg_final), "to": list(salida),
               "diameter_mm": NORMA["albanal_min_mm"],
               "slope": NORMA["pendiente_drenaje"]}
    resultado: dict[str, Any] = {
        "outlet": list(salida),
        "pipes": [{**_tramo_publico(t), "drains": t["drena"],
                   "slope": NORMA["pendiente_drenaje"]} for t in tramos],
        "registers": registros,
        "sewer": albanal,
        "vent": ventilador,
        "criteria": {k: NORMA[k] for k in ("pendiente_drenaje", "albanal_min_mm",
                                           "registro_max_m")},
    }
    if draw:
        resultado.update(_dibujar_sanitaria(tramos, registros, albanal, ventilador))
        if legend:
            resultado["legend"] = _leyenda_auto("sanitaria", rooms, legend_x, legend_y, notes)
    return resultado


def _registros(red: geo.Red, principal: list[dict[str, Any]],
               final: tuple) -> list[dict[str, Any]]:
    """Registros sobre la línea principal: en el de conexión, en cada unión
    de ramales y cambio de dirección, y a no más de 10 m entre sí."""
    puntos: list[tuple[float, float]] = [final]
    hijos: dict[int, list[int]] = {}
    for i, p in enumerate(red.padre):
        if p is not None:
            hijos.setdefault(p, []).append(i)
    nodos_principales = {t["nodo"] for t in principal}
    for n in nodos_principales:
        p = red.padre[n]
        if p is None:
            continue
        ramas = hijos.get(n, [])
        es_union = len(ramas) >= 2
        # Cambio de dirección: el tramo que llega y el que sale no son
        # colineales.
        cambio = False
        for h in ramas:
            a, b, c = red.nodos[h], red.nodos[n], red.nodos[p]
            if not (abs(a[0] - b[0]) < 1e-9 and abs(b[0] - c[0]) < 1e-9) and \
               not (abs(a[1] - b[1]) < 1e-9 and abs(b[1] - c[1]) < 1e-9):
                cambio = True
        if (es_union or cambio) and red.etiqueta[n] is None:
            puntos.append(red.nodos[n])
    # A no más de 10 m sobre cada tramo principal largo.
    for t in principal:
        n = math.floor(t["largo"] / NORMA["registro_max_m"])
        for k in range(1, n + 1):
            f = k * NORMA["registro_max_m"] / t["largo"]
            a, b = t["desde"], t["hasta"]
            puntos.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    unicos: list[tuple[float, float]] = []
    for p in puntos:
        if all(math.dist(p, q) > 0.5 for q in unicos):
            unicos.append(p)
    return [{"name": f"R-{i + 1}", "point": [round(p[0], 3), round(p[1], 3)],
             "size_cm": "40x60"} for i, p in enumerate(unicos)]


def _dibujar_sanitaria(tramos, registros, albanal, ventilador=None) -> dict[str, Any]:
    _ensure(CAPA_DRENAJE, COLOR_DRENAJE, 40)
    _ensure(CAPA_REGISTRO, COLOR_REGISTRO, 30)
    _ensure(CAPA_TEXTO_INST, 7, 18)
    for t in tramos:
        _linea(t["desde"], t["hasta"], CAPA_DRENAJE, 40 if t["diametro_mm"] >= 100 else 30)
    _linea(tuple(albanal["from"]), tuple(albanal["to"]), CAPA_DRENAJE, 50)
    h = _paper(1.8)
    # Los rótulos de registro y del ventilador van por place_labels junto
    # con los de diámetro: escritos a mano a +0.25 caían encima del
    # "Ø100 P=2%" del tramo que llega al mismo registro (visto en AutoCAD).
    rot = []
    for r in registros:
        x, y = r["point"]
        _rect(x - 0.2, y - 0.3, x + 0.2, y + 0.3, CAPA_REGISTRO)
        if r.get("double_lid"):
            _rect(x - 0.15, y - 0.25, x + 0.15, y + 0.25, CAPA_REGISTRO, 18)
        rot.append({"text": f"{r['name']} {r['size_cm']}" + (" D.T." if r.get("double_lid") else ""),
                    "box": [x - 0.2, y - 0.3, x + 0.2, y + 0.3]})
    if ventilador:
        vx, vy = ventilador["point"]
        _circulo((vx, vy), 0.10, CAPA_DRENAJE)
        rot.append({"text": f"TV Ø{ventilador['diameter_mm']}",
                    "box": [vx - 0.1, vy - 0.1, vx + 0.1, vy + 0.1]})
    # Sentido del flujo y pendiente en los tramos largos.
    import annotation
    flechas = 0
    for t in tramos:
        if t["largo"] < 1.5:
            continue
        # El flujo va del mueble (hasta) hacia la descarga (desde).
        pts = [list(t["hasta"]), list(t["desde"])]
        try:
            annotation.create_flow_arrow(points=pts, positions=[t["largo"] / 2.0],
                                         layer=CAPA_DRENAJE)
            flechas += 1
        except Exception:                               # noqa: BLE001
            pass
    for t in tramos:
        if t["largo"] < 1.2:
            continue
        a, b = t["desde"], t["hasta"]
        vertical = abs(a[0] - b[0]) < 1e-9
        rot.append({"text": f"Ø{t['diametro_mm']} P={NORMA['pendiente_drenaje'] * 100:.0f}%",
                    "x": (a[0] + b[0]) / 2.0 + (0.18 if vertical else 0.0),
                    "y": (a[1] + b[1]) / 2.0 + (0.0 if vertical else 0.18),
                    "rotation": 90.0 if vertical else 0.0})
    rot.append({"text": f"ALBAÑAL Ø{albanal['diameter_mm']} A RED MUNICIPAL",
                "x": albanal["to"][0] + 0.25, "y": albanal["to"][1] - 0.4})
    lab = annotation.place_labels(rot, height=h, layer=CAPA_TEXTO_INST)
    return {"drainSegments": len(tramos), "registersDrawn": len(registros),
            "flowArrows": flechas, "cramped": len(lab.get("cramped", []))}


# ========================================================== SIMBOLOGÍA

# Lo que dice cada nota sale de NORMA, no de memoria: si cambia un valor
# allá, cambia el texto acá. Solo notas que respalda una norma; el material
# (CPVC, cobre tipo M, poliducto...) y las alturas de montaje son decisión
# del proyecto y entran por 'notes', nunca inventadas.
def _notas_norma(kind: str) -> list[str]:
    n = NORMA
    if kind == "electrica":
        return [
            f"INSTALACIÓN SEGÚN NOM-001-SEDE-2012. TENSIÓN NOMINAL {n['tension_v']:.0f} V.",
            "SÍMBOLOS SEGÚN NMX-J-136-SCFI; LOS QUE NO FIGURAN AHÍ SE DESCRIBEN EN ESTE CUADRO.",
            "CONTACTOS DE BAÑO, COCINA, LAVADO Y EXTERIORES CON PROTECCIÓN "
            "POR FALLA A TIERRA (GFCI), ART. 210-8.",
            "DOS CIRCUITOS DE 20 A PARA PEQUEÑOS APARATOS (COCINA Y COMEDOR), "
            "UNO DE LAVADO Y UNO DE BAÑO, ART. 210-11(c).",
            f"NINGÚN PUNTO DE MURO A MÁS DE {n['contacto_max_m']:.2f} m DE UN "
            "CONTACTO, ART. 210-52(a).",
            f"CONDUCTOR CAL. {n['calibre_awg'][20]} AWG EN CIRCUITOS DE 20 A Y "
            f"CAL. {n['calibre_awg'][15]} AWG EN LOS DE 15 A, ART. 240-4(d).",
            "CONTACTOS DE USO GENERAL INCLUIDOS EN LOS 33 VA/m2 DE ALUMBRADO, ART. 220-14(j).",
            "CARGAS, PROTECCIONES Y CALIBRES POR CIRCUITO: VER CUADRO DE CARGAS.",
        ]
    if kind == "hidraulica":
        return [
            "DIÁMETROS EN mm POR UNIDADES MUEBLE ACUMULADAS, INIFED TABLA 2.3.",
            "ALIMENTACIÓN POR GRAVEDAD: LA BAF BAJA DEL TINACO Y ALIMENTA LA RED "
            "DE AGUA FRÍA Y EL CALENTADOR.",
            f"SALIDA DEL TINACO A {n['tinaco_sobre_regadera_m']:.1f} m O MÁS SOBRE "
            "LA REGADERA MÁS ALTA (NTC CDMX 6.1.2).",
            f"RETORNO DE AGUA CALIENTE SI EL RECORRIDO SUPERA {n['retorno_ac_m']:.0f} m "
            "(INIFED 2.8).",
        ]
    return [
        f"PENDIENTE MÍNIMA {n['pendiente_drenaje'] * 100:.0f} % EN TODO DESAGÜE; "
        f"NINGUNO MENOR DE {n['desague_min_mm']} mm (NTC CDMX 6.1.3.1).",
        "DESCARGA DE WC Ø100 mm; DIÁMETROS POR UNIDADES DE DESCARGA, "
        "INIFED TABLAS 3.1 Y 3.3.",
        f"REGISTROS DE 40x60 cm A NO MÁS DE {n['registro_max_m']:.0f} m Y EN CADA "
        "CAMBIO DE DIRECCIÓN; DOBLE TAPA BAJO LOCALES HABITABLES (NTC 6.1.3.2).",
        f"TUBO VENTILADOR DE Ø{n['ventilador_min_mm']} mm EN EL ORIGEN DEL ALBAÑAL.",
        f"ALBAÑAL DE Ø{n['albanal_min_mm']} mm MÍNIMO HASTA LA RED MUNICIPAL.",
    ]


def _filas_simbologia(kind: str) -> list[tuple[str, Any]]:
    """(descripción, cómo dibujar el símbolo centrado en (cx, cy) en un
    ancho w). Los símbolos salen de las MISMAS funciones que dibujan la
    planta: una simbología que dibuja otra cosa no sirve."""
    import annotation

    def dispositivo(tipo: str, ang: float = 90.0):
        def f(cx, cy, w):
            dy = -0.08 if tipo in ("outlet", "gfci") else 0.0
            electrical.place_devices([{"type": tipo, "x": cx, "y": cy + dy, "angle": ang}])
        return f

    def tuberia(cx, cy, w):
        electrical.create_conduit([[cx - w / 2, cy], [cx + w / 2, cy]],
                                  sag=0.06, conductors="/|T")

    def retorno(cx, cy, w):
        _linea((cx - w / 2, cy), (cx + w / 2, cy), electrical.LAYER_OUTLET, 25)
        annotation.create_flow_arrow(points=[[cx - w / 2, cy], [cx + w / 2, cy]],
                                     positions=[w], size=_paper(2.5),
                                     layer=electrical.LAYER_OUTLET)

    def linea(capa, grosor):
        return lambda cx, cy, w: _linea((cx - w / 2, cy), (cx + w / 2, cy), capa, grosor)

    def texto(t):
        h = _paper(1.8)
        return lambda cx, cy, w: _texto(t, cx - len(t) * h * 0.38, cy - h / 2, h,
                                        CAPA_TEXTO_INST)

    def drenaje(cx, cy, w):
        _linea((cx - w / 2, cy), (cx + w / 2, cy), CAPA_DRENAJE, 40)
        annotation.create_flow_arrow(points=[[cx - w / 2, cy], [cx + w / 2, cy]],
                                     positions=[w / 2], layer=CAPA_DRENAJE)

    def registro(doble):
        def f(cx, cy, w):
            _rect(cx - 0.2, cy - 0.3, cx + 0.2, cy + 0.3, CAPA_REGISTRO)
            if doble:
                _rect(cx - 0.15, cy - 0.25, cx + 0.15, cy + 0.25, CAPA_REGISTRO, 18)
        return f

    if kind == "electrica":
        return [
            ("SALIDA DE ALUMBRADO DE CENTRO (TECHO)", dispositivo("lamp")),
            ("APAGADOR SENCILLO", dispositivo("switch", 0.0)),
            ("CONTACTO POLARIZADO CON TIERRA (180 VA)", dispositivo("outlet")),
            ("CONTACTO CON PROTECCIÓN DE FALLA A TIERRA (GFCI)", dispositivo("gfci")),
            ("CENTRO DE CARGA", dispositivo("panel", 0.0)),
            ("TUBERÍA POR LOSA O MURO:  / FASE   | NEUTRO   T TIERRA", tuberia),
            ("LLEGADA AL CENTRO DE CARGA (C-n: NÚMERO DE CIRCUITO)", retorno),
        ]
    if kind == "hidraulica":
        return [
            ("TUBERÍA DE AGUA FRÍA (AF)", linea(CAPA_AF, 50)),
            ("TUBERÍA DE AGUA CALIENTE (AC)", linea(CAPA_AC, 50)),
            ("BAF: BAJADA DE AGUA FRÍA DEL TINACO",
             lambda cx, cy, w: _circulo((cx, cy), 0.15, CAPA_HID_SIMB)),
            ("CAL: CALENTADOR DE AGUA",
             lambda cx, cy, w: _rect(cx - 0.25, cy - 0.25, cx + 0.25, cy + 0.25, CAPA_HID_SIMB)),
            ("SALIDA A MUEBLE", lambda cx, cy, w: _circulo((cx, cy), 0.06, CAPA_HID_SIMB)),
            ("DIÁMETRO NOMINAL DEL TRAMO, EN mm", texto("AF Ø19")),
        ]
    return [
        ("DESAGÜE CON SENTIDO DEL FLUJO", drenaje),
        ("REGISTRO DE 40x60 cm (R-n)", registro(False)),
        ("REGISTRO CON DOBLE TAPA (D.T.)", registro(True)),
        ("TV: TUBO VENTILADOR",
         lambda cx, cy, w: _circulo((cx, cy), 0.10, CAPA_DRENAJE)),
        ("ALBAÑAL A LA RED MUNICIPAL", linea(CAPA_DRENAJE, 50)),
        ("DIÁMETRO Y PENDIENTE DEL TRAMO", texto("Ø100 P=2%")),
    ]


TITULOS_SIMBOLOGIA = {"electrica": "INSTALACIÓN ELÉCTRICA",
                      "hidraulica": "INSTALACIÓN HIDRÁULICA",
                      "sanitaria": "INSTALACIÓN SANITARIA"}


def create_installation_legend(kind: str, x: float, y: float,
                               notes: Optional[list[str]] = None,
                               norm_notes: bool = True) -> dict[str, Any]:
    """Cuadro de SIMBOLOGÍA y NOTAS de una instalación, con la esquina
    superior izquierda en (x, y).

    Sin esto el plano solo lo lee quien lo dibujó: el cliente, el
    electricista o el plomero necesitan saber qué es cada círculo, cada
    línea discontinua y cada abreviatura (BAF, D.T., TV, GFCI). Cada
    símbolo se dibuja con la MISMA función que lo dibuja en la planta.

    kind: 'electrica', 'hidraulica' o 'sanitaria'.
    notes: notas del proyecto que se agregan a las de norma — materiales,
    marcas, alturas de montaje. No se inventan: lo que el proyecto no
    definió, no se escribe. norm_notes=False deja solo las propias.
    """
    import textwrap
    kind = kind.lower().replace("á", "a").replace("é", "e")
    if kind not in TITULOS_SIMBOLOGIA:
        raise ValueError("kind debe ser 'electrica', 'hidraulica' o 'sanitaria'.")
    _ensure(CAPA_TEXTO_INST, 7, 18)
    if kind == "hidraulica":
        _ensure(CAPA_AF, COLOR_AF, 50)
        _ensure(CAPA_AC, COLOR_AC, 50, layers.LT_OCULTO)
        _ensure(CAPA_HID_SIMB, COLOR_AF, 25)
    if kind == "sanitaria":
        _ensure(CAPA_DRENAJE, COLOR_DRENAJE, 40)
        _ensure(CAPA_REGISTRO, COLOR_REGISTRO, 30)

    h = _paper(2.0)
    filas = _filas_simbologia(kind)
    alto = max(_paper(8.0), 0.75)
    w_simb = max(_paper(22.0), 1.4)
    pad = h * 0.8
    w_desc = max(len(d) for d, _ in filas) * h * 0.78 + 2 * pad
    ancho = w_simb + w_desc
    capa = CAPA_TEXTO_INST

    _texto(f"SIMBOLOGÍA — {TITULOS_SIMBOLOGIA[kind]}", x, y - h * 1.4, h * 1.3, capa)
    top = y - h * 2.4
    enc = h * 2.2
    _texto("SÍMBOLO", x + pad, top - enc / 2 - h / 2, h, capa)
    _texto("DESCRIPCIÓN", x + w_simb + pad, top - enc / 2 - h / 2, h, capa)
    y_fila = top - enc
    _linea((x, y_fila), (x + ancho, y_fila), capa, 25)
    for desc, dibujar in filas:
        cy = y_fila - alto / 2
        dibujar(x + w_simb / 2, cy, w_simb * 0.6)
        _texto(desc, x + w_simb + pad, cy - h / 2, h, capa)
        y_fila -= alto
        _linea((x, y_fila), (x + ancho, y_fila), capa, 13)
    bottom = y_fila
    _rect(x, bottom, x + ancho, top, capa, 35)
    _linea((x + w_simb, bottom), (x + w_simb, top), capa, 13)

    # Notas numeradas, partidas al ancho del cuadro.
    lista = (_notas_norma(kind) if norm_notes else []) + list(notes or [])
    y_n = bottom
    if lista:
        y_n -= h * 2.2
        _texto("NOTAS:", x, y_n, h * 1.1, capa)
        cols = max(30, int(ancho / (h * 0.78)) - 4)
        for i, nota in enumerate(lista, start=1):
            for j, renglon in enumerate(textwrap.wrap(nota, width=cols)):
                y_n -= h * 1.6
                if j == 0:
                    _texto(f"{i}.", x, y_n, h, capa)
                _texto(renglon, x + h * 2.0, y_n, h, capa)
    caja = [x, y_n - h * 0.5, x + ancho, y]
    space.reserve(*caja, what=f"simbologia {kind}")
    return {"kind": kind, "box": [round(v, 3) for v in caja],
            "symbols": len(filas), "notes": len(lista)}


def _leyenda_auto(kind: str, rooms: list[dict[str, Any]], x: Optional[float],
                  y: Optional[float], notes: Optional[list[str]]) -> dict[str, Any]:
    """Simbología a la derecha de la planta, alineada con su borde superior."""
    if x is None:
        x = max(r["x1"] for r in rooms) + max(_paper(15.0), 1.0)
    if y is None:
        y = max(r["y1"] for r in rooms)
    return create_installation_legend(kind, x, y, notes=notes)
