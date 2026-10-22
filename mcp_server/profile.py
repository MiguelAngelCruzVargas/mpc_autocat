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
    # Por layers.ensure: si el AutoCAD esta en castellano (CENTRO2 en vez de CENTER2),
    # prueba el equivalente y, si tampoco, deja la capa continua en vez de fallar.
    if linetype:
        import layers as layers_mod
        layers_mod.ensure(name, color, lineweight, linetype, force=True)
        return
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
                   step: float = 2.0,
                   title: Optional[str] = "PERFIL LONGITUDINAL",
                   scale_text: Optional[str] = None) -> dict[str, Any]:
    """Perfil longitudinal: terreno, rasante y grilla de referencia, con
    título pegado debajo y simbología (qué línea es cada cosa). title=None
    no los dibuja. scale_text: 'ESC. H 1:100  V 1:20'.

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
    # Rasante gruesa y terreno fino gris: se distinguen por el TRAZO, también
    # en monocromo. Antes eran rojo y verde puros, sin rótulo: nadie sabía
    # qué eran (visto en una prueba real).
    _layer(LAYER_GROUND, 8, LW_GROUND)
    _layer(LAYER_GRADE, 7, LW_GRADE)
    _layer(LAYER_TEXT, 7, LW_TEXT)

    # --- Grilla ---
    ancho, alto = PX(length) - PX(0), PY(techo) - PY(base)
    # 18 y no LW_GRID+8: AutoCAD solo acepta ciertos grosores y 17 no es uno.
    _poly([(PX(0), PY(base)), (PX(0) + ancho, PY(base)),
           (PX(0) + ancho, PY(base) + alto), (PX(0), PY(base) + alto)],
          LAYER_GRID, 18, closed=True)

    est = 0.0
    while est <= length + 1e-9:
        _line((PX(est), PY(base)), (PX(est), PY(techo)), LAYER_GRID, LW_GRID)
        _text(station_text(est), PX(est) + text_height * 0.5, PY(base) - text_height * 7.5,
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
        handle_terreno = _poly(pts, LAYER_GROUND, LW_GROUND)

    # --- Rasante de proyecto ---
    pts_rasante = [(PX(e), PY(grade_elevation(pvis, e))) for e in muestras]
    handle_rasante = _poly(pts_rasante, LAYER_GRADE, LW_GRADE)

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
              text_height, LAYER_TEXT)
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

    caja = [PX(0) - text_height * 8.0, PY(base) - text_height * 8.0, PX(length), PY(techo)]
    if title:
        import symbols
        tv = symbols.create_view_title(title=title, scale_text=scale_text, figure_box=caja)
        lx, ly = PX(length) + text_height * 3.0, PY(techo)
        filas_ley = [(LAYER_GRADE, LW_GRADE, "RASANTE DE PROYECTO"),
                     (LAYER_GROUND, LW_GROUND, "TERRENO NATURAL")]
        _text("SIMBOLOGÍA", lx, ly + text_height * 1.0, text_height * 1.2, LAYER_TEXT)
        for k, (capa, lw, txt) in enumerate(filas_ley):
            yy = ly - (k + 1) * text_height * 2.4
            _line((lx, yy), (lx + text_height * 5.0, yy), capa, lw)
            _text(txt, lx + text_height * 6.0, yy - text_height * 0.4, text_height, LAYER_TEXT)
        caja = [caja[0], min(caja[1], tv["box"][1]), lx + text_height * 30.0, caja[3]]

    return {
        "x": x, "y": y, "datum": base, "top": techo,
        "width": ancho, "height": alto, "box": [round(v, 3) for v in caja],
        "groundHandle": handle_terreno, "gradeHandle": handle_rasante,
        "grades": tramos, "stations": filas,
        "vExaggeration": v_exag,
    }


# ------------------------------------------------ secciones transversales
#
# Lo que tiene que decir una sección para que se pueda construir —y para que
# quien la mira sepa qué es cada línea—: cadenamiento en formato 0+000.00,
# cota de rasante y de terreno en el eje, bombeo, talud, y las ÁREAS de corte
# y de terraplén, que son con lo que se cuantifica el movimiento de tierras.
# La versión anterior dibujaba la rasante en rojo puro y el terreno en verde
# puro, sin rótulos, con el terreno como una raya horizontal (en ladera no
# existe) y devolvía como "volumen" el del paquete estructural. Pasó en una
# prueba real: nadie supo qué eran las líneas rojas.

def station_text(station: float) -> str:
    """Cadenamiento como se rotula en obra: 0+005.00, 1+250.40."""
    return f"{int(station // 1000)}+{station % 1000:06.2f}"


def _interp_perfil(perfil: list[tuple[float, float]], o: float) -> float:
    if o <= perfil[0][0]:
        return perfil[0][1]
    if o >= perfil[-1][0]:
        return perfil[-1][1]
    for (a, za), (b, zb) in zip(perfil, perfil[1:]):
        if a <= o <= b:
            return za + (zb - za) * ((o - a) / (b - a) if b > a else 0.0)
    return perfil[-1][1]


def _seccion_proyecto(width: float, grade_elev: float, crown: float, depth: float,
                      side_slope: float, terreno: Optional[list[tuple[float, float]]]
                      ) -> dict[str, Any]:
    """Geometría de la sección en coordenadas (desplazamiento, cota): la
    rasante, la subrasante (fondo del paquete), y cada talud hasta que
    encuentra el terreno. En terraplén el talud baja desde la orilla de la
    rasante; en corte sube desde la orilla de la subrasante."""
    half = width / 2.0
    z_borde = grade_elev - half * crown
    sub = grade_elev - depth
    taludes = {}
    for signo in (-1.0, 1.0):
        o_b = signo * half
        if terreno is None:
            taludes[signo] = [(o_b, z_borde - depth), (o_b + signo * half * 0.6, z_borde - depth)]
            continue
        g_b = _interp_perfil(terreno, o_b)
        corte = g_b > z_borde
        o0, z0 = (o_b, z_borde - depth) if corte else (o_b, z_borde)
        sube = 1.0 if corte else -1.0
        fin = None
        prev = None
        for k in range(1, 3001):                       # hasta 30 m del borde
            o = o0 + signo * k * 0.01
            zt = z0 + sube * (k * 0.01) / side_slope
            d = zt - _interp_perfil(terreno, o)
            if prev is not None and (d >= 0) != (prev >= 0):
                fin = (o, zt)
                break
            prev = d
        taludes[signo] = [(o0, z0), fin or (o, zt)]
    return {"half": half, "z_borde": z_borde, "sub": sub, "taludes": taludes,
            "corte": {s: (terreno is not None and _interp_perfil(terreno, s * half) > z_borde)
                      for s in (-1.0, 1.0)}}


def _areas(sec: dict[str, Any], grade_elev: float, crown: float, depth: float,
           terreno: list[tuple[float, float]]) -> tuple[float, float]:
    """Área de corte y de terraplén entre el terreno y la línea de proyecto
    (subrasante en la calzada, taludes a los lados), integrada a cada cm."""
    half = sec["half"]
    tl, tr = sec["taludes"][-1.0], sec["taludes"][1.0]

    def proyecto(o: float) -> Optional[float]:
        if abs(o) <= half:
            return grade_elev - abs(o) * crown - depth
        t = tl if o < 0 else tr
        (o0, z0), (o1, z1) = t
        lo, hi = min(o0, o1), max(o0, o1)
        if not lo <= o <= hi or hi - lo < 1e-9:
            return None
        z = z0 + (z1 - z0) * (o - o0) / (o1 - o0)
        return z
    o_min = min(tl[0][0], tl[1][0])
    o_max = max(tr[0][0], tr[1][0])
    corte = relleno = 0.0
    paso = 0.01
    o = o_min
    while o < o_max:
        zp = proyecto(o + paso / 2.0)
        if zp is not None:
            d = _interp_perfil(terreno, o + paso / 2.0) - zp
            if d > 0:
                corte += d * paso
            else:
                relleno -= d * paso
        o += paso
    return corte, relleno


def create_cross_section(x: float, y: float, station: float,
                         width: float, grade_elev: float,
                         ground_elev: Optional[float] = None,
                         crown: float = 0.02, side_slope: float = 1.5,
                         depth: float = 0.33, scale: float = 1.0,
                         text_height: float = 0.3,
                         layer: str = LAYER_SECTION,
                         ground_profile: Optional[list[list[float]]] = None
                         ) -> dict[str, Any]:
    """Sección transversal en un cadenamiento: calzada, bombeo y taludes.

    (x, y) es donde va el eje de la sección, a la cota de RASANTE.
    width: ancho de calzada. crown: bombeo (0.02 = 2%). side_slope: talud
    H:V (1.5 = 1.5 horizontal por 1 vertical). depth: espesor del paquete
    estructural.

    ground_profile: el terreno TRANSVERSAL, [[desplazamiento, cota], ...]
    (negativo a la izquierda del eje). Es lo que hace falta en ladera: el
    terreno no es plano de lado a lado. Sin él, ground_elev lo toma plano.

    Devuelve áreas de corte y terraplén (m², con su escala real) y el área
    del paquete estructural, por separado."""
    if width <= 0:
        raise ValueError("width tiene que ser > 0.")
    import layers as layers_mod
    c_ras, c_ter, c_eje, c_txt = (layer, f"{layer}-TERRENO", f"{layer}-EJE",
                                  f"{layer}-TEXTO")
    _layer(c_ras, 7, LW_GRADE)
    _layer(c_ter, 8, LW_GROUND)
    _layer(c_eje, 32, 13, layers_mod.LT_EJE)
    _layer(c_txt, 7, LW_TEXT)

    terreno = None
    if ground_profile:
        terreno = sorted(((float(o), float(z)) for o, z in ground_profile), key=lambda p: p[0])
    elif ground_elev is not None:
        terreno = [(-50.0, float(ground_elev)), (50.0, float(ground_elev))]
    sec = _seccion_proyecto(width, grade_elev, crown, depth, side_slope, terreno)

    def P(o: float, z: float) -> tuple[float, float]:
        return (x + o * scale, y + (z - grade_elev) * scale)

    half, zb = sec["half"], sec["z_borde"]
    # Rasante con su bombeo y el paquete estructural debajo.
    _poly([P(-half, zb), P(0.0, grade_elev), P(half, zb)], c_ras, LW_GRADE)
    _poly([P(-half, zb), P(0.0, grade_elev), P(half, zb), P(half, zb - depth),
           P(0.0, grade_elev - depth), P(-half, zb - depth)], c_ras, LW_GROUND, closed=True)
    for s in (-1.0, 1.0):
        (o0, z0), (o1, z1) = sec["taludes"][s]
        _line(P(o0, z0), P(o1, z1), c_ras, LW_GROUND)
    # Terreno natural, en el ancho que ocupa la sección más un metro.
    o_ext = max(abs(sec["taludes"][-1.0][1][0]), abs(sec["taludes"][1.0][1][0])) + 1.0
    if terreno is not None:
        pts = [P(o, _interp_perfil(terreno, o))
               for o in [-o_ext + k * 0.25 for k in range(int(2 * o_ext / 0.25) + 1)]]
        _poly(pts, c_ter, LW_GROUND)
    arriba = max([grade_elev] + ([_interp_perfil(terreno, 0.0)] if terreno else []))
    abajo = min([grade_elev - depth] + ([_interp_perfil(terreno, 0.0)] if terreno else []))
    th = text_height
    # Eje de la sección: de bajo el paquete hasta justo debajo de "CALZADA";
    # más largo cruzaba ese texto y el cadenamiento (visto en AutoCAD).
    _line((x, P(0.0, grade_elev - depth)[1] - th * 0.6), (x, y + th * 1.9), c_eje, 13)
    # Bombeo sobre cada mitad y ancho de calzada.
    for s in (-1.0, 1.0):
        bx, by = P(s * half / 2.0, grade_elev - half / 2.0 * crown)
        _text(f"{crown * 100:.0f}%", bx - th, by + th * 0.6, th * 0.8, c_txt)
    tx, ty = P(0.0, grade_elev)
    _text(f"CALZADA {width:.2f}", tx - th * 4.0, ty + th * 2.2, th * 0.8, c_txt)
    # Talud rotulado del lado más largo.
    s_l = max((-1.0, 1.0), key=lambda s: abs(sec["taludes"][s][1][0] - sec["taludes"][s][0][0]))
    (o0, z0), (o1, z1) = sec["taludes"][s_l]
    mx, my = P((o0 + o1) / 2.0, (z0 + z1) / 2.0)
    _text(f"TALUD {side_slope:g}:1", mx + (0.2 if s_l > 0 else -th * 7.0), my + th * 0.4,
          th * 0.75, c_txt)

    # Rótulo de la sección: cadenamiento, cotas y áreas, debajo de todo.
    ys = [P(0.0, grade_elev - depth)[1]] + [P(o, z)[1] for s in (-1.0, 1.0)
                                            for o, z in sec["taludes"][s]]
    if terreno is not None:
        ys += [P(0.0, _interp_perfil(terreno, o))[1] for o in (-o_ext, 0.0, o_ext)]
    y_pie = min(ys) - th * 2.0
    _text(station_text(station), x - th * 3.0, y_pie, th * 1.25, c_txt)
    linea = f"RAS. {grade_elev:.2f}"
    corte = relleno = None
    if terreno is not None:
        g0 = _interp_perfil(terreno, 0.0)
        linea += f"   T.N. {g0:.2f}"
        corte, relleno = _areas(sec, grade_elev, crown, depth, terreno)
        _text(f"A. CORTE {corte:.2f} m²   A. TERRAPLÉN {relleno:.2f} m²",
              x - th * 9.0, y_pie - th * 3.6, th * 0.85, c_txt)
    _text(linea, x - th * 6.0, y_pie - th * 1.9, th * 0.85, c_txt)

    area_paquete = width * depth
    tipo = None
    if terreno is not None:
        g0 = _interp_perfil(terreno, 0.0)
        tipo = "corte" if g0 > grade_elev else "terraplen"
    return {"station": station, "label": station_text(station), "x": x, "y": y,
            "width": width, "area": area_paquete, "pavementArea": area_paquete,
            "cutArea": None if corte is None else round(corte, 3),
            "fillArea": None if relleno is None else round(relleno, 3),
            "crown": crown,
            "cutFill": (_interp_perfil(terreno, 0.0) - grade_elev) if terreno else None,
            "type": tipo,
            "extent": [x - o_ext * scale, y_pie - th * 4.5,
                       x + o_ext * scale, P(0.0, arriba + 0.6)[1] + th * 3.0]}


def sample_surface(grid: dict[str, Any], px: float, py: float) -> float:
    """Cota de una malla regular {"x0","y0","dx","dy","z"} (z[i][j] en
    x0 + j*dx, y0 + i*dy) por interpolación bilineal. Fuera de la malla
    toma el borde."""
    x0, y0, dx, dy, z = grid["x0"], grid["y0"], grid["dx"], grid["dy"], grid["z"]
    ny, nx = len(z), len(z[0])
    fj = min(max((px - x0) / dx, 0.0), nx - 1.000001)
    fi = min(max((py - y0) / dy, 0.0), ny - 1.000001)
    j, i = int(fj), int(fi)
    tj, ti = fj - j, fi - i
    return ((z[i][j] * (1 - tj) + z[i][j + 1] * tj) * (1 - ti)
            + (z[i + 1][j] * (1 - tj) + z[i + 1][j + 1] * tj) * ti)


def create_cross_section_series(x: float, y: float, stations: list[float],
                                width: float, pvis: list[dict[str, Any]],
                                ground: Optional[list[list[float]]] = None,
                                columns: int = 3, spacing_x: float = 0.0,
                                spacing_y: float = 0.0, crown: float = 0.02,
                                side_slope: float = 1.5, depth: float = 0.33,
                                scale: float = 1.0, text_height: float = 0.3,
                                layer: str = LAYER_SECTION,
                                surface: Optional[dict[str, Any]] = None,
                                alignment: Optional[dict[str, Any]] = None,
                                half_width: float = 0.0,
                                title: Optional[str] = "SECCIONES TRANSVERSALES",
                                scale_text: Optional[str] = None) -> dict[str, Any]:
    """Una tanda de secciones transversales, acomodadas en cuadrícula, con
    título y simbología (qué es cada línea).

    Terreno, de lo más pobre a lo mejor:
      - ground: [[cadenamiento, cota]] a lo largo del eje; lo toma PLANO de
        lado a lado (sirve en terreno llano).
      - surface + alignment: la superficie del terreno como malla
        {"x0","y0","dx","dy","z"} y el eje {"points","bulges"}. Muestrea el
        terreno TRANSVERSAL en cada cadenamiento, perpendicular al eje, hasta
        half_width (default 3 veces el ancho). Es lo que hace falta en ladera.

    Devuelve el volumen de CORTE y de TERRAPLÉN por áreas medias, y aparte el
    del paquete estructural (pavementVolume; 'volume' queda por
    compatibilidad y es ese mismo)."""
    if not stations:
        raise ValueError("Hay que pasar al menos un cadenamiento.")
    if (surface is None) != (alignment is None):
        raise ValueError("surface y alignment van juntos: la superficie sin el eje no "
                         "dice dónde cortar.")
    if alignment is not None:
        import civil
        largo = civil.point_on_road(alignment["points"], 0.0,
                                    bulges=alignment.get("bulges"))["totalLength"]
        fuera = [e for e in stations if e < -1e-6 or e > largo + 0.01]
        if fuera:
            # Pasó: se pidió la 0+010 en un acceso de 8.49 m y salió una
            # sección dibujada más allá del final del camino.
            raise ValueError(f"Cadenamientos fuera del eje (mide {largo:.2f} m): "
                             f"{', '.join(station_text(e) for e in fuera)}.")

    def terreno_eje(est: float) -> Optional[float]:
        if not ground:
            return None
        pts = sorted(((float(a), float(b)) for a, b in ground), key=lambda p: p[0])
        return _interp_perfil(pts, est)

    def terreno_transversal(est: float) -> Optional[list[list[float]]]:
        if surface is None:
            return None
        import civil
        hw = half_width or width * 3.0
        perfil = []
        for k in range(int(2 * hw / 0.25) + 1):
            o = -hw + k * 0.25
            # point_on_road: desplazamiento positivo a la IZQUIERDA del avance.
            p = civil.point_on_road(alignment["points"], est, offset=-o,
                                    bulges=alignment.get("bulges"))
            perfil.append([o, sample_surface(surface, p["x"], p["y"])])
        return perfil

    dx = spacing_x or width * scale * 2.6
    dy = spacing_y or width * scale * 1.8
    hechas = []
    for i, est in enumerate(sorted(stations)):
        col, fila = i % columns, i // columns
        sec = create_cross_section(
            x=x + col * dx, y=y - fila * dy, station=est, width=width,
            grade_elev=grade_elevation(pvis, est), ground_elev=terreno_eje(est),
            crown=crown, side_slope=side_slope, depth=depth, scale=scale,
            text_height=text_height, layer=layer,
            ground_profile=terreno_transversal(est))
        hechas.append(sec)

    def medias(clave: str) -> Optional[float]:
        if any(s[clave] is None for s in hechas):
            return None
        return round(sum((a[clave] + b[clave]) / 2.0 * (b["station"] - a["station"])
                         for a, b in zip(hechas, hechas[1:])), 2)

    caja = [min(s["extent"][0] for s in hechas), min(s["extent"][1] for s in hechas),
            max(s["extent"][2] for s in hechas), max(s["extent"][3] for s in hechas)]
    leyenda = None
    if title:
        import symbols
        tv = symbols.create_view_title(title=title, scale_text=scale_text, figure_box=caja)
        # Simbología: qué es cada línea. Sin esto el plano solo lo lee
        # quien lo dibujó.
        lx, ly = caja[2] + text_height * 4.0, caja[3]
        filas = [(layer, LW_GRADE, "RASANTE (SUPERFICIE DE RODAMIENTO, CON BOMBEO)"),
                 (layer, LW_GROUND, f"PAQUETE ESTRUCTURAL e = {depth:.2f} m Y TALUDES"),
                 (f"{layer}-TERRENO", LW_GROUND, "TERRENO NATURAL"),
                 (f"{layer}-EJE", 13, "EJE DEL CAMINO")]
        for k, (capa, lw, txt) in enumerate(filas):
            yy = ly - k * text_height * 2.4
            _line((lx, yy), (lx + text_height * 5.0, yy), capa, lw)
            _text(txt, lx + text_height * 6.0, yy - text_height * 0.4, text_height,
                  f"{layer}-TEXTO")
        _text("SIMBOLOGÍA", lx, ly + text_height * 2.0, text_height * 1.2, f"{layer}-TEXTO")
        leyenda = [lx, ly - len(filas) * text_height * 2.4, lx + text_height * 40.0,
                   ly + text_height * 3.5]
        caja = [caja[0], min(caja[1], tv["box"][1]), max(caja[2], leyenda[2]), caja[3]]

    paquete = medias("area")
    return {"sections": hechas, "count": len(hechas),
            "volume": paquete, "pavementVolume": paquete,
            "cutVolume": medias("cutArea"), "fillVolume": medias("fillArea"),
            "box": [round(v, 3) for v in caja]}
