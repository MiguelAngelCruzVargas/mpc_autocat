"""EXAMEN de un edificio de vivienda: ¿el proyecto cumple y el juego de
planos está completo?

Dos partes, porque fallan por motivos distintos:

- revisar_proyecto(datos): los NÚMEROS de norma sobre lo que se diseñó —
  dimensiones de locales, puertas, iluminación, patios, escalera,
  circulaciones, elevador, estructura. Es pura cuenta: corre sin AutoCAD.
- revisar_juego(): el JUEGO DE PLANOS en el DWG — que estén las láminas que
  pide el trámite y que cada una tenga lo suyo (cortes, cuadro de cargas,
  notas de materiales, rótulo con DRO...). Lee el dibujo.

Cada regla dice de dónde sale. Referencia: Ciudad de México, Manifestación
de Construcción tipo B.

  [RCDF]  Reglamento de Construcciones CDMX, reforma 04/10/2024:
          https://paot.org.mx/centro/reglamentos/df/pdf/2024/RGTO_CONSTRUCCIONES_04_10_2024.pdf
  [NTCPA] NTC para el Proyecto Arquitectónico, Gaceta 12/12/2024:
          https://amraci.org/wp-content/uploads/2024/12/2024-12-12_NTCPA.pdf
  [NTCC]  NTC para Diseño y Construcción de Estructuras de Concreto, 06/11/2023.

Lo que no se pudo verificar en un texto oficial NO está como regla (la
dotación de agua vigente, el formato del rótulo): se pide como dato.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Optional

# --------------------------------------------------------------- números

# Tabla 2.2.1.1 [NTCPA]: área mínima, lado mínimo, altura mínima.
LOCALES = {
    "recamara_principal": (7.00, 2.40, 2.30),
    "recamara": (6.00, 2.20, 2.30),
    "sala_comedor": (9.75, 2.50, 2.30),
    "sala": (6.75, 2.50, 2.30),
    "comedor": (4.80, 2.40, 2.30),
    "cocina": (3.75, 1.55, 2.30),
    "lavado": (2.20, 1.55, 2.10),
    "bano": (2.90, 1.20, 2.10),
}
ALTURA_MINIMA = 2.30                    # [NTCPA] 2.2.1.1: local fuera de la tabla
VENTANA_HABITABLE = 0.175               # [NTCPA] 3.3.3.2.1
VENTANA_COMPLEMENTARIO = 0.15
PATIO_HABITABLE = 1 / 3                 # [NTCPA] 3.3.3.4: de la altura de paramentos
PATIO_COMPLEMENTARIO = 1 / 4
PATIO_MINIMO = 2.50
ESCALERA = {"peralte_max": 0.18, "peralte_min": 0.10, "huella_min": 0.25,
            "altura_entre_descansos": 2.70, "descanso_min": 1.20,
            "ancho_min": 0.90}           # [NTCPA] 2.2.2.5, Tabla 4.3.5.2 (1-50 usuarios)
CIRCULACION_COMUN_MIN = 1.10            # [NTCPA] Tabla 4.3.5.1b
PUERTA_COCINA_BANO = 0.80               # [NTCPA] Tabla 4.3.5.4
PUERTA_OTRAS = 0.90
ELEVADOR_NIVELES = 5                    # [NTCPA] 2.2.2.8.1-b: más de 5 además de PB
ELEVADOR_ALTURA = 15.0                  #   o más de 15 m
CAJONES_MAX_POR_VIVIENDA = 3            # [NTCPA] Tabla 1.3.1.2.3 (sin mínimo, 1.3.1.1.1)
CAJON = (5.00, 2.50)                    # [NTCPA] 1.3.1.3.1, grande
FC_MINIMO = 250.0                       # [NTCC] 4.4.1.1, kg/cm²
SOLAR_DESDE_VIVIENDAS = 3               # [RCDF] art. 82-VI: más de 3


def clase(nombre: str) -> Optional[str]:
    n = nombre.upper()
    if "BAÑO" in n or "BANO" in n:
        return "bano"
    if "RECÁMARA PRINCIPAL" in n or "RECAMARA PRINCIPAL" in n:
        return "recamara_principal"
    if "RECÁMARA" in n or "RECAMARA" in n:
        return "recamara"
    if "SALA" in n and "COMEDOR" in n:
        return "sala_comedor"
    if "SALA" in n:
        return "sala"
    if "COMEDOR" in n:
        return "comedor"
    if "COCINA" in n:
        return "cocina"
    if "LAVADO" in n:
        return "lavado"
    return None


HABITABLES = {"recamara_principal", "recamara", "sala_comedor", "sala", "comedor"}
COMPLEMENTARIOS = {"cocina", "lavado", "bano"}


def _falla(regla: str, que: str, fuente: str, donde: str = "") -> dict[str, Any]:
    return {"rule": regla, "problem": que, "source": fuente, "where": donde}


# ------------------------------------------------------- revisar_proyecto

def revisar_proyecto(datos: dict[str, Any]) -> dict[str, Any]:
    """Números de norma sobre lo diseñado.

    datos:
      levels: [{"name", "floor_to_floor", "slab", "rooms", "doors",
                "windows"}]  — rooms/doors/windows como draw_layout; cada
                ventana con 'width' y 'height' (alto del vano).
      lot: [ancho, fondo]
      dwellings: número de viviendas
      parking: número de cajones; parking_size: [largo, ancho]
      stair: {"riser", "tread", "width", "landing", "rise_per_flight"}
      patios: [{"name", "wall_height", "serves": "habitable"|"complementario"}]
      structure: {"fc", "fy", "seismic_zone", "soil_study": bool,
                  "seismic_coefficient"}
      equipment: ["calentador solar", "elevador", ...]
    """
    fallas: list[dict[str, Any]] = []
    revisadas = 0

    for nivel in datos.get("levels", []):
        n_nombre = nivel.get("name", "?")
        rooms = nivel.get("rooms", [])
        por_nombre = {r["name"]: r for r in rooms}
        libre = float(nivel.get("floor_to_floor", 0)) - float(nivel.get("slab", 0))

        # 1. Locales: área, lado, altura.
        for r in rooms:
            c = clase(r["name"])
            w, h = r["x1"] - r["x0"], r["y1"] - r["y0"]
            if c:
                area_min, lado_min, alto_min = LOCALES[c]
                revisadas += 3
                if w * h < area_min - 1e-6:
                    fallas.append(_falla("local_area", f"{r['name']}: {w * h:.2f} m² < {area_min} m²",
                                         "NTCPA Tabla 2.2.1.1", n_nombre))
                if min(w, h) < lado_min - 1e-6:
                    fallas.append(_falla("local_lado", f"{r['name']}: lado {min(w, h):.2f} m < {lado_min} m",
                                         "NTCPA Tabla 2.2.1.1", n_nombre))
                if libre and libre < alto_min - 1e-6:
                    fallas.append(_falla("local_altura", f"{r['name']}: altura libre {libre:.2f} m < {alto_min} m",
                                         "NTCPA Tabla 2.2.1.1", n_nombre))
            if "CIRCULACIÓN COMÚN" in r["name"].upper() or "CIRCULACION COMUN" in r["name"].upper():
                revisadas += 1
                if min(w, h) < CIRCULACION_COMUN_MIN - 1e-6:
                    fallas.append(_falla("circulacion_comun", f"{r['name']}: {min(w, h):.2f} m < "
                                         f"{CIRCULACION_COMUN_MIN} m", "NTCPA Tabla 4.3.5.1b", n_nombre))

        # 2. Puertas (los vanos abiertos y los registros de ducto no cuentan).
        for d in nivel.get("doors", []):
            if d.get("open") or "DUCTO" in (str(d.get("to")) + str(d.get("from"))).upper():
                continue
            destino = [str(d.get("to", "")), str(d.get("from", ""))]
            minimo = (PUERTA_COCINA_BANO if any(clase(x) in ("cocina", "bano") for x in destino)
                      else PUERTA_OTRAS)
            revisadas += 1
            if float(d.get("width", 0)) < minimo - 1e-6:
                fallas.append(_falla("puerta_ancho", f"{d.get('from')} → {d.get('to')}: "
                                     f"{float(d['width']):.2f} m < {minimo:.2f} m",
                                     "NTCPA Tabla 4.3.5.4", n_nombre))

        # 3. Iluminación: el vano contra el área del local, medida A EJES
        # (del lado seguro: el área interior es menor). Un local sin
        # ventana que abre por un vano libre a otro (cocina abierta a la
        # sala) se ilumina con el de ese: se revisan JUNTOS.
        ventanas: dict[str, float] = {}
        for v in nivel.get("windows", []):
            ventanas[v["room"]] = ventanas.get(v["room"], 0.0) + (
                float(v.get("width", 1.2)) * float(v.get("height", 1.2)))
        abiertos: dict[str, set] = {}
        for d in nivel.get("doors", []):
            if d.get("open"):
                a, b = str(d.get("from")), str(d.get("to"))
                abiertos.setdefault(a, set()).add(b)
                abiertos.setdefault(b, set()).add(a)
        ya: set = set()
        for r in rooms:
            c = clase(r["name"])
            if not c or r["name"] in ya:
                continue
            grupo = {r["name"]}
            if r["name"] not in ventanas:
                grupo |= {x for x in abiertos.get(r["name"], set()) if x in ventanas}
            area = sum((por_nombre[g]["x1"] - por_nombre[g]["x0"]) *
                       (por_nombre[g]["y1"] - por_nombre[g]["y0"]) for g in grupo if g in por_nombre)
            # Al juntar con el que tiene la ventana, se suman también los
            # otros que ese ilumina (la sala + la cocina abierta).
            vano = sum(ventanas.get(g, 0.0) for g in grupo)
            pide = VENTANA_HABITABLE if any(clase(g) in HABITABLES for g in grupo) else VENTANA_COMPLEMENTARIO
            revisadas += 1
            ya |= grupo
            if vano < pide * area - 1e-6:
                fallas.append(_falla("iluminacion", f"{' + '.join(sorted(grupo))}: vano {vano:.2f} m² "
                                     f"< {pide * 100:.1f} % de {area:.2f} m² = {pide * area:.2f} m²",
                                     "NTCPA 3.3.3.2.1", n_nombre))

        # 4. Nada se ilumina por la colindancia.
        lote = datos.get("lot")
        for v in nivel.get("windows", []):
            if lote and "x" in v and (abs(v["x"]) < 1e-6 or abs(v["x"] - lote[0]) < 1e-6):
                fallas.append(_falla("colindancia", f"ventana de {v['room']} sobre la colindancia",
                                     "NTCPA 3.3.3.2.5", n_nombre))

    # 5. Patios de iluminación.
    for p in datos.get("patios", []):
        lado = float(p["min_side"])
        fac = PATIO_HABITABLE if p.get("serves") == "habitable" else PATIO_COMPLEMENTARIO
        pide = max(PATIO_MINIMO, fac * float(p["wall_height"]))
        revisadas += 1
        if lado < pide - 1e-6:
            fallas.append(_falla("patio_iluminacion", f"{p['name']}: lado {lado:.2f} m < {pide:.2f} m "
                                 f"({'1/3' if fac == PATIO_HABITABLE else '1/4'} de {p['wall_height']:.2f} m, "
                                 f"mínimo {PATIO_MINIMO} m)", "NTCPA 3.3.3.4"))

    # 6. Escalera.
    e = datos.get("stair")
    if e:
        for clave, ok, txt in (
                ("peralte", ESCALERA["peralte_min"] - 1e-6 <= e["riser"] <= ESCALERA["peralte_max"] + 1e-6,
                 f"peralte {e['riser'] * 100:.1f} cm fuera de 10-18 cm"),
                ("huella", e["tread"] >= ESCALERA["huella_min"] - 1e-6,
                 f"huella {e['tread'] * 100:.0f} cm < 25 cm"),
                ("ancho", e["width"] >= ESCALERA["ancho_min"] - 1e-6,
                 f"ancho {e['width']:.2f} m < 0.90 m"),
                ("descanso", e["landing"] >= max(ESCALERA["descanso_min"], e["width"]) - 1e-6,
                 f"descanso {e['landing']:.2f} m < {max(ESCALERA['descanso_min'], e['width']):.2f} m"),
                ("tramo", e["rise_per_flight"] <= ESCALERA["altura_entre_descansos"] + 1e-6,
                 f"{e['rise_per_flight']:.2f} m entre descansos > 2.70 m")):
            revisadas += 1
            if not ok:
                fallas.append(_falla("escalera_" + clave, txt, "NTCPA 2.2.2.5 / Tabla 4.3.5.2"))

    # 7. Elevador, estacionamiento, calentador solar.
    niveles = len(datos.get("levels_total", datos.get("levels", [])))
    altura = float(datos.get("height", 0))
    equipo = [x.lower() for x in datos.get("equipment", [])]
    revisadas += 1
    if (niveles - 1 > ELEVADOR_NIVELES or altura > ELEVADOR_ALTURA) and not any("elevador" in x for x in equipo):
        fallas.append(_falla("elevador", f"{niveles} niveles / {altura:.1f} m piden elevador",
                             "NTCPA 2.2.2.8.1-b"))
    viv = int(datos.get("dwellings", 0))
    if "parking" in datos:
        revisadas += 1
        if datos["parking"] > CAJONES_MAX_POR_VIVIENDA * viv:
            fallas.append(_falla("cajones", f"{datos['parking']} cajones > 3 por vivienda",
                                 "NTCPA Tabla 1.3.1.2.3"))
        largo, ancho = datos.get("parking_size", CAJON)
        if largo < CAJON[0] - 1e-6 or ancho < CAJON[1] - 1e-6:
            # El cajón chico (4.20 x 2.40) también vale; se avisa igual.
            if largo < 4.20 or ancho < 2.40:
                fallas.append(_falla("cajon_medida", f"cajón {largo:.2f} x {ancho:.2f} m",
                                     "NTCPA 1.3.1.3.1"))
    revisadas += 1
    if viv > SOLAR_DESDE_VIVIENDAS and not any("solar" in x for x in equipo):
        fallas.append(_falla("calentador_solar", f"{viv} viviendas: calentador solar obligatorio",
                             "RCDF art. 82-VI"))

    # 8. Estructura: materiales y lo que tiene que declarar el proyecto.
    s = datos.get("structure", {})
    revisadas += 3
    if float(s.get("fc", 0)) < FC_MINIMO:
        fallas.append(_falla("fc", f"f'c = {s.get('fc')} < {FC_MINIMO:.0f} kg/cm²", "NTCC 4.4.1.1"))
    if not s.get("seismic_zone") or not s.get("seismic_coefficient"):
        fallas.append(_falla("sismo", "el proyecto no declara zona sísmica y coeficiente sísmico",
                             "RCDF art. 53-I-e y 170"))
    if not s.get("soil_study"):
        fallas.append(_falla("mecanica_de_suelos", "sin estudio de mecánica de suelos: la capacidad "
                             "de carga es un supuesto, no un dato", "RCDF art. 53-I-f"))

    return {"ok": not fallas, "checked": revisadas, "failures": fallas}


# --------------------------------------------------------- revisar_juego

# Lo que el juego de planos tiene que MOSTRAR. Cada requisito busca textos
# en el dibujo (los títulos de vista, los cuadros, las notas). Es una
# revisión de presencia: que el corte esté, no que esté bien dibujado.
# Cada texto llega en dos formas: sin espacios (los títulos van con las
# letras separadas, "P L A N T A") y tal cual, para buscar PALABRAS enteras:
# "GAS" adentro de "CARGAS" no es una instalación de gas (pasó).
def _hay(*palabras: str) -> Callable[[list[tuple[str, str]]], bool]:
    def f(textos: list[tuple[str, str]]) -> bool:
        return any(all(p in t for p in palabras) for t, _ in textos)
    return f


def _palabra(patron: str) -> Callable[[list[tuple[str, str]]], bool]:
    import re
    rx = re.compile(r"(?<![A-ZÁÉÍÓÚÑ])" + patron + r"(?![A-ZÁÉÍÓÚÑ])")
    return lambda textos: any(rx.search(o) for _, o in textos)


def _cuantos(minimo: int, *palabras: str) -> Callable[[list[tuple[str, str]]], bool]:
    def f(textos: list[tuple[str, str]]) -> bool:
        return sum(1 for t, _ in textos if all(p in t for p in palabras)) >= minimo
    return f


def _sin_espacios(t: str) -> str:
    # create_view_title separa las letras ("P L A N T A"): se compara sin
    # espacios y en mayúsculas.
    return "".join(str(t).upper().split())


JUEGO = [
    # Arquitectónico — RCDF art. 53-I-c
    ("arq_localizacion", "Arquitectónico", "Croquis de localización", "RCDF 53-I-c", _hay("LOCALIZACIÓN")),
    ("arq_conjunto", "Arquitectónico", "Planta de conjunto con límites del predio", "RCDF 53-I-c", _hay("CONJUNTO")),
    ("arq_planta_baja", "Arquitectónico", "Planta baja", "RCDF 53-I-c", _hay("PLANTABAJA")),
    ("arq_plantas_altas", "Arquitectónico", "Plantas de los niveles superiores (o planta tipo)",
     "RCDF 53-I-c", lambda t: _hay("PLANTATIPO")(t) or _hay("NIVEL")(t)),
    ("arq_azotea", "Arquitectónico", "Planta de azotea", "RCDF 53-I-c (captación pluvial)", _hay("AZOTEA")),
    ("arq_cortes", "Arquitectónico", "Al menos dos cortes (longitudinal y transversal)",
     "RCDF 53-I-c", _cuantos(2, "CORTE")),
    ("arq_corte_escalera", "Arquitectónico", "Un corte por la escalera", "práctica", _hay("CORTE", "ESCALERA")),
    ("arq_fachadas", "Arquitectónico", "Fachadas (al menos la que da a la calle)", "RCDF 53-I-c", _hay("FACHADA")),
    ("arq_cuadro_areas", "Arquitectónico", "Cuadro de áreas por nivel", "RCDF 53 (memoria descriptiva)",
     _hay("CUADRODEÁREAS")),
    ("arq_norte", "Arquitectónico", "Norte", "práctica", lambda t: any(o == "N" for _, o in t)),
    # Estructural — RCDF art. 53-I-e
    ("est_cimentacion", "Estructural", "Planta de cimentación", "RCDF 53-I-e", _hay("CIMENTACIÓN")),
    ("est_planta", "Estructural", "Planta estructural de entrepiso / azotea", "RCDF 53-I-e",
     _hay("ESTRUCTURAL")),
    ("est_detalles", "Estructural", "Detalles (zapata, columna, trabe)", "RCDF 53-I-e",
     lambda t: _hay("ZAPATA")(t) and _hay("COLUMNA")(t) and _hay("TRABE")(t)),
    ("est_materiales", "Estructural", "Calidad de materiales (f'c, fy)", "RCDF 53-I-e",
     lambda t: _hay("F'C")(t) and _hay("FY")(t)),
    ("est_cargas", "Estructural", "Cargas vivas", "RCDF 53-I-e", _hay("CARGAVIVA")),
    ("est_sismo", "Estructural", "Coeficiente sísmico / zona", "RCDF 53-I-e", _hay("SÍSMIC")),
    # Instalaciones — RCDF art. 53-I-d
    ("ih_hidraulica", "Instalaciones", "Instalación hidráulica", "RCDF 53-I-d", _hay("HIDRÁULICA")),
    ("ih_isometrico", "Instalaciones", "Isométrico hidráulico", "RCDF 53-I-d", _hay("ISOMÉTRICO")),
    ("ih_cisterna", "Instalaciones", "Cisterna y bombeo", "práctica", _hay("CISTERNA")),
    ("ih_tinacos", "Instalaciones", "Tinacos", "práctica", _hay("TINACO")),
    ("ih_solar", "Instalaciones", "Calentador solar", "RCDF 82-VI", _hay("SOLAR")),
    ("is_sanitaria", "Instalaciones", "Instalación sanitaria", "RCDF 53-I-d", _hay("SANITARIA")),
    ("is_registros", "Instalaciones", "Registros y albañal", "práctica", _hay("ALBAÑAL")),
    ("is_pluvial", "Instalaciones", "Bajadas pluviales", "RCDF 53-I-d", _palabra("BAP")),
    ("ie_electrica", "Instalaciones", "Instalación eléctrica", "RCDF 53-I-d", _hay("ELÉCTRICA")),
    ("ie_cargas", "Instalaciones", "Cuadro de cargas", "NOM-001-SEDE-2012", _hay("CUADRODECARGAS")),
    ("ie_unifilar", "Instalaciones", "Diagrama unifilar", "NOM-001-SEDE-2012 (proyecto)", _hay("UNIFILAR")),
    ("gas", "Instalaciones", "Instalación de gas", "RCDF 53-I-d; NOM-004-SEDG-2004", _palabra("GAS")),
    # Cuantificación — estándar de esta biblioteca
    ("cuantificacion", "Cuantificación", "Cuadro de volúmenes de obra", "CLAUDE.md 8.bis",
     lambda t: _hay("VOLÚMENES")(t) or _hay("CUANTIFICACIÓN")(t)),
    # Rótulo — RCDF 53-I-c,d,e (firmas)
    ("rotulo_dro", "Rótulo", "Nombre y registro del DRO", "RCDF 53-I", _palabra(r"D\.?R\.?O\.?")),
    ("rotulo_cedula", "Rótulo", "Cédula del proyectista", "RCDF 53-I-c", _hay("CÉDULA")),
]


def revisar_juego(textos: list[str], layouts: list[str]) -> dict[str, Any]:
    """Qué láminas y contenidos del juego están en el dibujo. textos: el
    contenido de TODOS los textos (modelo y láminas); layouts: nombres."""
    planos = [(_sin_espacios(t), " ".join(str(t).upper().split())) for t in textos if t]
    faltan, estan = [], []
    for clave, disc, que, fuente, prueba in JUEGO:
        (estan if prueba(planos) else faltan).append(
            {"id": clave, "discipline": disc, "what": que, "source": fuente})
    laminas = [l for l in layouts if l.upper() not in ("MODEL", "MODELO")]
    if not laminas:
        faltan.append({"id": "laminas", "discipline": "General",
                       "what": "Ninguna lámina (layout) armada", "source": "CLAUDE.md 8.quater"})
    return {"ok": not faltan, "present": estan, "missing": faltan,
            "score": f"{len(estan)}/{len(estan) + len(faltan)}"}


def textos_del_dibujo(acad) -> list[str]:
    """Todos los textos del dibujo, modelo y láminas, en UNA llamada si el
    plugin lo sabe (1.8.5+); si no, uno por uno."""
    r = acad.call("list_entities", {"limit": 500000, "allSpaces": True, "includeText": True})
    salida = []
    for e in r.get("entities", []):
        if e.get("type") not in ("DBText", "MText"):
            continue
        if "text" in e:
            salida.append(str(e["text"]))
        else:
            salida.append(str(acad.call("get_entity", {"handle": e["handle"]}).get("text", "")))
    return salida
