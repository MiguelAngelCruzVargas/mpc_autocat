"""Perfil longitudinal y secciones transversales de una obra lineal.

La planta dice por dónde va la calle; el perfil dice a qué altura, y las
secciones cómo es el corte en cada punto. Sin esos dos, un proyecto vial no se
puede construir: no hay cotas de rasante ni volúmenes de corte y terraplén.

Convención de escalas: un perfil se dibuja con la vertical exagerada respecto
de la horizontal (típico 10:1), porque si no las pendientes no se ven. Por eso
casi todo acá lleva `v_exag`.

Se compone con las tools básicas, así que se cambia sin recompilar.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad

LAYER_GRID = "PERFIL-GRILLA"
LAYER_GROUND = "PERFIL-TERRENO"
LAYER_GRADE = "PERFIL-RASANTE"
LAYER_TEXT = "PERFIL-TEXTO"
LAYER_SECTION = "SECCIONES"

LW_GRID = 9
LW_GROUND = 25
LW_GRADE = 50
LW_TEXT = 18


def _layer(name: str, color: int, lineweight: int,
           linetype: Optional[str] = None) -> None:
    acad.call("set_layer", {"name": name, "colorIndex": color,
                            "linetype": linetype,
                            "lineweightHundredthsMm": lineweight})


def _poly(points: list[tuple[float, float]], layer: str, lineweight: int,
          closed: bool = False, color: Optional[int] = None) -> str:
    return acad.call("create_polyline", {
        "points": [[p[0], p[1]] for p in points], "bulges": None,
        "closed": closed, "layer": layer,
        "lineweight": lineweight, "colorIndex": color,
    })["handle"]


def _line(p0: tuple[float, float], p1: tuple[float, float], layer: str,
          lineweight: int, color: Optional[int] = None) -> str:
    return acad.call("create_line", {
        "x1": p0[0], "y1": p0[1], "z1": 0.0,
        "x2": p1[0], "y2": p1[1], "z2": 0.0,
        "layer": layer, "lineweight": lineweight, "colorIndex": color,
    })["handle"]


def _text(content: str, x: float, y: float, height: float, layer: str,
          rotation: float = 0.0, color: Optional[int] = None) -> None:
    if not content:
        return
    acad.call("create_text", {
        "text": content, "x": x, "y": y, "z": 0.0, "height": height,
        "layer": layer, "rotationDeg": rotation, "style": None,
        "lineweight": LW_TEXT, "colorIndex": color,
    })


# ------------------------------------------------------- rasante (PVIs)

def grade_elevation(pvis: list[dict[str, Any]], station: float) -> float:
    """Cota de la rasante en un cadenamiento, con las curvas verticales.

    pvis son los puntos de inflexión vertical: [{"station":.., "elevation":..,
    "curve_length":..}]. Entre dos PVIs la rasante es una recta; dentro de una
    curva vertical es una parábola, que es la forma estándar de suavizar el
    cambio de pendiente.
    """
    if len(pvis) < 2:
        raise ValueError("La rasante necesita al menos dos PVI.")

    est = station
    if est <= pvis[0]["station"]:
        return float(pvis[0]["elevation"])
    if est >= pvis[-1]["station"]:
        return float(pvis[-1]["elevation"])

    for k in range(len(pvis) - 1):
        a, b = pvis[k], pvis[k + 1]
        s0, e0 = float(a["station"]), float(a["elevation"])
        s1, e1 = float(b["station"]), float(b["elevation"])
        if not (s0 <= est <= s1):
            continue

        pend = (e1 - e0) / (s1 - s0) if s1 > s0 else 0.0
        cota = e0 + pend * (est - s0)

        # Curva vertical del PVI de llegada.
        lcv = float(b.get("curve_length", 0.0) or 0.0)
        if lcv > 0 and k + 2 < len(pvis):
            c = pvis[k + 2]
            s2, e2 = float(c["station"]), float(c["elevation"])
            pend2 = (e2 - e1) / (s2 - s1) if s2 > s1 else 0.0
            inicio = s1 - lcv / 2.0
            if est >= inicio:
                # Parábola: y = y_pcv + g1*d + (g2-g1)*d^2/(2*L)
                d = est - inicio
                y_pcv = e1 - pend * (lcv / 2.0)
                cota = y_pcv + pend * d + (pend2 - pend) * d * d / (2.0 * lcv)

        # Curva vertical del PVI de salida.
        lcv0 = float(a.get("curve_length", 0.0) or 0.0)
        if lcv0 > 0 and k > 0:
            fin = s0 + lcv0 / 2.0
            if est <= fin:
                z = pvis[k - 1]
                sm1, em1 = float(z["station"]), float(z["elevation"])
                pend_ant = (e0 - em1) / (s0 - sm1) if s0 > sm1 else 0.0
                inicio = s0 - lcv0 / 2.0
                d = est - inicio
                y_pcv = e0 - pend_ant * (lcv0 / 2.0)
                cota = (y_pcv + pend_ant * d
                        + (pend - pend_ant) * d * d / (2.0 * lcv0))
        return cota

    return float(pvis[-1]["elevation"])


def create_profile(x: float, y: float, length: float,
                   pvis: list[dict[str, Any]],
                   ground: Optional[list[list[float]]] = None,
                   h_scale: float = 1.0, v_exag: float = 10.0,
                   datum: Optional[float] = None,
                   grid_station: float = 20.0, grid_elevation: float = 1.0,
                   text_height: float = 0.5,
                   step: float = 2.0) -> dict[str, Any]:
    """Perfil longitudinal: terreno, rasante y grilla de referencia.

    (x, y) es la esquina inferior izquierda del cuadro del perfil.
    length: largo del eje, en metros de obra.
    pvis: la rasante de proyecto.
    ground: terreno natural [[estacion, cota], ...]; opcional.
    v_exag: cuánto se exagera la vertical (10 = 10:1, lo habitual).
    datum: cota de referencia del piso del cuadro; por defecto, la mínima
    redondeada hacia abajo.

    Devuelve las cotas de rasante y terreno en cada estación de la grilla y el
    desnivel entre ambas, que es de donde salen los volúmenes de corte y
    terraplén.
    """
    if len(pvis) < 2:
        raise ValueError("La rasante necesita al menos dos PVI.")
    if length <= 0:
        raise ValueError("length tiene que ser > 0.")

    pvis = sorted(({"station": float(p["station"]),
                    "elevation": float(p["elevation"]),
                    "curve_length": float(p.get("curve_length", 0.0) or 0.0)}
                   for p in pvis), key=lambda p: p["station"])

    def terreno(est: float) -> Optional[float]:
        if not ground:
            return None
        pts = sorted(([float(a), float(b)] for a, b in ground),
                     key=lambda p: p[0])
        if est <= pts[0][0]:
            return pts[0][1]
        if est >= pts[-1][0]:
            return pts[-1][1]
        for (s0, e0), (s1, e1) in zip(pts, pts[1:]):
            if s0 <= est <= s1:
                t = (est - s0) / (s1 - s0) if s1 > s0 else 0.0
                return e0 + (e1 - e0) * t
        return pts[-1][1]

    # Rango de cotas para dimensionar el cuadro.
    muestras = [i * step for i in range(int(length / step) + 1)] + [length]
    cotas = [grade_elevation(pvis, e) for e in muestras]
    if ground:
        cotas += [terreno(e) for e in muestras if terreno(e) is not None]
    base = datum if datum is not None else math.floor(min(cotas)) - 1.0
    techo = math.ceil(max(cotas)) + 1.0

    def PX(est: float) -> float:
        return x + est * h_scale

    def PY(cota: float) -> float:
        return y + (cota - base) * h_scale * v_exag

    _layer(LAYER_GRID, 8, LW_GRID)
    _layer(LAYER_GROUND, 3, LW_GROUND)
    _layer(LAYER_GRADE, 1, LW_GRADE)
    _layer(LAYER_TEXT, 7, LW_TEXT)

    # --- Grilla ---
    ancho, alto = PX(length) - PX(0), PY(techo) - PY(base)
    _poly([(PX(0), PY(base)), (PX(0) + ancho, PY(base)),
           (PX(0) + ancho, PY(base) + alto), (PX(0), PY(base) + alto)],
          LAYER_GRID, LW_GRID + 8, closed=True)

    est = 0.0
    while est <= length + 1e-9:
        _line((PX(est), PY(base)), (PX(est), PY(techo)), LAYER_GRID, LW_GRID)
        _text(f"{est:.0f}", PX(est) - text_height, PY(base) - text_height * 3.5,
              text_height, LAYER_TEXT, rotation=90.0)
        est += grid_station

    cota = base
    while cota <= techo + 1e-9:
        _line((PX(0), PY(cota)), (PX(length), PY(cota)), LAYER_GRID, LW_GRID)
        _text(f"{cota:.2f}", PX(0) - text_height * 7.0,
              PY(cota) - text_height / 2.0, text_height, LAYER_TEXT)
        cota += grid_elevation

    # --- Terreno natural ---
    handle_terreno = None
    if ground:
        pts = [(PX(e), PY(terreno(e))) for e in muestras]
        handle_terreno = _poly(pts, LAYER_GROUND, LW_GROUND, color=3)

    # --- Rasante de proyecto ---
    pts_rasante = [(PX(e), PY(grade_elevation(pvis, e))) for e in muestras]
    handle_rasante = _poly(pts_rasante, LAYER_GRADE, LW_GRADE, color=1)

    # --- Pendientes rotuladas entre PVIs ---
    tramos = []
    for a, b in zip(pvis, pvis[1:]):
        dl = b["station"] - a["station"]
        if dl <= 0:
            continue
        pend = (b["elevation"] - a["elevation"]) / dl * 100.0
        medio = (a["station"] + b["station"]) / 2.0
        _text(f"{pend:+.2f}%", PX(medio) - text_height * 2.0,
              PY(grade_elevation(pvis, medio)) + text_height * 1.5,
              text_height, LAYER_TEXT, color=1)
        tramos.append({"from": a["station"], "to": b["station"],
                       "gradePercent": pend, "length": dl})

    # --- Datos por estación de grilla ---
    filas = []
    est = 0.0
    while est <= length + 1e-9:
        r = grade_elevation(pvis, est)
        t = terreno(est)
        filas.append({"station": est, "grade": round(r, 3),
                      "ground": round(t, 3) if t is not None else None,
                      "cut_fill": round(t - r, 3) if t is not None else None})
        est += grid_station

    return {
        "x": x, "y": y, "datum": base, "top": techo,
        "width": ancho, "height": alto,
        "groundHandle": handle_terreno, "gradeHandle": handle_rasante,
        "grades": tramos, "stations": filas,
        "vExaggeration": v_exag,
    }


# ------------------------------------------------ secciones transversales

def create_cross_section(x: float, y: float, station: float,
                         width: float, grade_elev: float,
                         ground_elev: Optional[float] = None,
                         crown: float = 0.02, side_slope: float = 1.5,
                         depth: float = 0.33, scale: float = 1.0,
                         text_height: float = 0.3,
                         layer: str = LAYER_SECTION) -> dict[str, Any]:
    """Sección transversal en un cadenamiento: calzada, bombeo y taludes.

    (x, y) es donde va el eje de la sección (el centro de la calzada).
    width: ancho de calzada. crown: bombeo, la pendiente transversal que saca
    el agua al borde (2% es lo normal). side_slope: talud de los costados,
    expresado como H:V (1.5 significa 1.5 horizontal por 1 vertical).
    depth: espesor del paquete estructural.

    Devuelve el área de la sección, que multiplicada por la distancia entre
    secciones da el volumen de obra.
    """
    if width <= 0:
        raise ValueError("width tiene que ser > 0.")

    _layer(layer, 7, LW_GROUND)
    half = width / 2.0 * scale
    caida = width / 2.0 * crown * scale

    # Rasante: del eje hacia los bordes, cayendo por el bombeo.
    eje = (x, y)
    borde_izq = (x - half, y - caida)
    borde_der = (x + half, y - caida)
    _poly([borde_izq, eje, borde_der], layer, LW_GRADE, color=1)

    # Paquete estructural debajo.
    e = depth * scale
    _poly([borde_izq, borde_der, (borde_der[0], borde_der[1] - e),
           (borde_izq[0], borde_izq[1] - e)], layer, LW_GROUND, closed=True)

    # Taludes hacia afuera, hasta encontrar el terreno.
    desnivel = 0.0
    if ground_elev is not None:
        desnivel = (ground_elev - grade_elev) * scale
    corrida = abs(desnivel) * side_slope if desnivel else half * 0.6
    for signo, borde in ((-1.0, borde_izq), (1.0, borde_der)):
        fin = (borde[0] + signo * corrida, borde[1] + desnivel)
        _line((borde[0], borde[1] - e), fin, layer, LW_GROUND)

    # Terreno natural, si se conoce.
    if ground_elev is not None:
        yt = y + desnivel
        _line((x - half - corrida, yt), (x + half + corrida, yt),
              layer, LW_GROUND, color=3)

    etiqueta = f"EST {station:.2f}"
    _text(etiqueta, x - text_height * 3.0, y - e - text_height * 4.0,
          text_height, layer)
    if ground_elev is not None:
        tipo = "CORTE" if ground_elev > grade_elev else "TERRAPLEN"
        _text(f"{tipo} {abs(ground_elev - grade_elev):.2f} m",
              x - text_height * 4.0, y - e - text_height * 6.0,
              text_height * 0.85, layer)

    area = width * depth
    return {"station": station, "x": x, "y": y, "width": width,
            "area": area, "crown": crown,
            "cutFill": (ground_elev - grade_elev) if ground_elev is not None else None,
            "type": (None if ground_elev is None
                     else ("corte" if ground_elev > grade_elev else "terraplen"))}


def create_cross_section_series(x: float, y: float, stations: list[float],
                                width: float, pvis: list[dict[str, Any]],
                                ground: Optional[list[list[float]]] = None,
                                columns: int = 3, spacing_x: float = 0.0,
                                spacing_y: float = 0.0, crown: float = 0.02,
                                side_slope: float = 1.5, depth: float = 0.33,
                                scale: float = 1.0, text_height: float = 0.3,
                                layer: str = LAYER_SECTION) -> dict[str, Any]:
    """Una tanda de secciones transversales, acomodadas en cuadrícula.

    Toma las cotas de rasante de los PVIs y las de terreno de `ground`, así que
    cada sección sale con su corte o terraplén ya resuelto. Devuelve el volumen
    estimado por el método de las áreas medias, que es el que se usa para
    cuantificar movimiento de tierras.
    """
    if not stations:
        raise ValueError("Hay que pasar al menos un cadenamiento.")

    def terreno(est: float) -> Optional[float]:
        if not ground:
            return None
        pts = sorted(([float(a), float(b)] for a, b in ground),
                     key=lambda p: p[0])
        if est <= pts[0][0]:
            return pts[0][1]
        if est >= pts[-1][0]:
            return pts[-1][1]
        for (s0, e0), (s1, e1) in zip(pts, pts[1:]):
            if s0 <= est <= s1:
                t = (est - s0) / (s1 - s0) if s1 > s0 else 0.0
                return e0 + (e1 - e0) * t
        return pts[-1][1]

    dx = spacing_x or width * scale * 2.2
    dy = spacing_y or width * scale * 1.4
    hechas = []

    for i, est in enumerate(sorted(stations)):
        col, fila = i % columns, i // columns
        sec = create_cross_section(
            x=x + col * dx, y=y - fila * dy, station=est, width=width,
            grade_elev=grade_elevation(pvis, est), ground_elev=terreno(est),
            crown=crown, side_slope=side_slope, depth=depth, scale=scale,
            text_height=text_height, layer=layer)
        hechas.append(sec)

    # Volumen por areas medias entre secciones consecutivas.
    volumen = 0.0
    for a, b in zip(hechas, hechas[1:]):
        dist = b["station"] - a["station"]
        volumen += (a["area"] + b["area"]) / 2.0 * dist

    return {"sections": hechas, "count": len(hechas),
            "volume": round(volumen, 2)}
