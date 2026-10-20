"""El juego estructural de una planta de marcos, de punta a punta y dentro
del servidor: losa → bajada de cargas → trabes continuas → diseño de trabe →
zapatas → planta estructural y de cimentación → lámina (layout) y PDF.

Existe para que el detalle no dependa de quién llama: un modelo chico que
pida "la estructura de una casa de 15 x 8 con columnas cada 5 y 4" recibe
las mismas láminas que uno grande encadenando las tools una por una. Nada se
supone: f'c, cargas, capacidad del suelo y desplante los pasa quien proyecta
(y sin ellos rechaza); lo que la tool decide (sección de trabe, espesor de
losa) lo decide iterando hasta que cumpla y lo deja escrito en el resultado.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import compose
import estructura as es
import planta_estructural as pe
import zapatas as zap


def _r(v: float, n: int = 3) -> float:
    return round(float(v), n)


def design_frame_structure(x_axes: list[float], y_axes: list[float], w_dead: float, w_live: float,
                           fc: float, allowable_bearing: float, depth: float,
                           soil_unit_weight: Optional[float] = None,
                           slab_h: float = 0.0, beam_b: float = 0.25, beam_h: float = 0.0,
                           column_size: float = 0.30, fy: float = 4200.0, code: str = "NTC",
                           openings: Optional[list[list[float]]] = None,
                           beam_mark_prefix: str = "T", tie_beam_b: float = 0.25) -> dict[str, Any]:
    """Diseña toda la planta sin dibujar. x_axes/y_axes: coordenadas de los
    ejes (m, en el sistema de la planta). Cargas de SERVICIO en kg/m²
    (w_dead SIN el peso propio de la losa: se suma solo). slab_h/beam_h = 0
    -> se eligen iterando (losa desde el mínimo de ACI 8.3.1.2, trabe desde
    L/12 redondeado a 5 cm) hasta cumplir."""
    xs, ys = sorted(set(map(float, x_axes))), sorted(set(map(float, y_axes)))
    if len(xs) < 2 or len(ys) < 2:
        raise ValueError("Hacen falta al menos dos ejes en cada sentido.")
    if min(w_dead, w_live, fc, allowable_bearing, depth) <= 0:
        raise ValueError("w_dead, w_live, fc, allowable_bearing y depth tienen que ser > 0: son datos del proyecto.")
    decisiones: list[str] = []
    # --- 1. Losa: el tablero más grande manda; iterar h de 2 en 2 cm.
    paneles = [(xs[i], ys[j], xs[i + 1], ys[j + 1]) for i in range(len(xs) - 1) for j in range(len(ys) - 1)]
    mayor = max(paneles, key=lambda p: (p[2] - p[0]) * (p[3] - p[1]))
    lx, ly = mayor[2] - mayor[0], mayor[3] - mayor[1]
    h = slab_h
    if h <= 0:
        h = 0.10
        while h <= 0.40:
            d = es.design_two_way_slab(lx, ly, w_dead + 2400 * h, w_live, fc, h, fy, continuous_edges=1, code=code)
            if d["ok"]:
                break
            h = round(h + 0.02, 3)
        decisiones.append(f"Losa: h = {h * 100:.0f} cm, el primer espesor (de 2 en 2 cm) que cumple ACI 8.3.1.2 "
                          f"en el tablero mayor de {lx:.2f} x {ly:.2f}.")
    losa = es.design_two_way_slab(lx, ly, w_dead + 2400 * h, w_live, fc, h, fy, continuous_edges=1, code=code)
    if not losa["ok"]:
        raise ValueError(f"La losa de {h * 100:.0f} cm no cumple en el tablero de {lx:.2f} x {ly:.2f}: {losa['min_thickness']}.")
    # --- 2. Bajada a trabes: cada trabe recibe los tableros que apoyan en ella.
    wu = losa["wu_kg_m2"]
    fd = zap.COMBOS[code][0]

    def carga_trabe(a: float, z: float, lado: float, tableros: list) -> float:
        """kg/m factorizados sobre un tramo: triángulos/trapecios de los
        tableros a cada lado + peso propio de la trabe."""
        w = 0.0
        for (px0, py0, px1, py1) in tableros:
            r = es.panel_edge_loads(px1 - px0, py1 - py0, wu)
            corto = min(px1 - px0, py1 - py0)
            w += r["short"]["equiv_kg_m"] if abs(lado - corto) < 1e-6 else r["long"]["equiv_kg_m"]
        return w

    hb = beam_h
    if hb <= 0:
        Lmax = max(max(b - a for a, b in zip(xs, xs[1:])), max(b - a for a, b in zip(ys, ys[1:])))
        hb = math.ceil(Lmax / 12 / 0.05) * 0.05
        decisiones.append(f"Trabe: peralte inicial L/12 = {hb:.2f} m (claro mayor {Lmax:.2f}); crece de 5 en 5 cm si no da.")
    pp = fd * 2400 * beam_b * hb
    trabes: list[dict[str, Any]] = []
    n = 1
    lineas = [("y", yv, xs) for yv in ys] + [("x", xv, ys) for xv in xs]
    peor = {"mpos": 0.0, "mneg": 0.0, "v": 0.0}
    for sentido, c, pos in lineas:
        cargas = []
        for a, z in zip(pos, pos[1:]):
            if sentido == "y":
                tabs = [p for p in paneles if abs(p[1] - c) < 1e-6 or abs(p[3] - c) < 1e-6
                        if p[0] <= a + 1e-6 and p[2] >= z - 1e-6]
                w = carga_trabe(a, z, z - a, tabs)
            else:
                tabs = [p for p in paneles if abs(p[0] - c) < 1e-6 or abs(p[2] - c) < 1e-6
                        if p[1] <= a + 1e-6 and p[3] >= z - 1e-6]
                w = carga_trabe(a, z, z - a, tabs)
            cargas.append(w + pp)
        claros = [z - a for a, z in zip(pos, pos[1:])]
        vc = es.continuous_beam(claros, cargas)
        mpos = max(s["M_pos_tm"] for s in vc["spans"])
        mneg = max(abs(m) for m in vc["support_moments_tm"])
        v = max(max(abs(s["V_left_t"]), abs(s["V_right_t"])) for s in vc["spans"])
        peor = {"mpos": max(peor["mpos"], mpos), "mneg": max(peor["mneg"], mneg), "v": max(peor["v"], v)}
        mark = f"{beam_mark_prefix}-{n}"
        n += 1
        if sentido == "y":
            trabes.append({"x0": pos[0], "y0": c, "x1": pos[-1], "y1": c, "b": beam_b, "mark": mark,
                           "loads_kg_m": [_r(w, 1) for w in cargas], "analysis": vc})
        else:
            trabes.append({"x0": c, "y0": pos[0], "x1": c, "y1": pos[-1], "b": beam_b, "mark": mark,
                           "loads_kg_m": [_r(w, 1) for w in cargas], "analysis": vc})
    # --- 3. Sección de trabe: una sola para toda la planta (la peor manda), creciendo si no da.
    Lcond = max(claros)
    while True:
        try:
            diseno = es.design_beam(beam_b, hb, peor["mpos"], peor["mneg"], peor["v"], fc, fy,
                                    span=Lcond, condition="both")
            if diseno["ok"]:
                break
        except ValueError:
            pass
        hb = round(hb + 0.05, 3)
        if hb > 1.50:
            raise ValueError("Ninguna trabe hasta 1.50 m de peralte cumple: revisá cargas o separación de ejes.")
    if beam_h <= 0:
        decisiones.append(f"Trabe final: {beam_b * 100:.0f} x {hb * 100:.0f} cm, {diseno['bottom']['text']} inf., "
                          f"{diseno['top']['text']} sup., {diseno['stirrups']['text']}.")
    for t in trabes:
        t["h"] = hb
    # --- 4. Zapatas: reacción máxima de las dos trabes que llegan a cada columna (servicio).
    reac = {}
    for t in trabes:
        pos = xs if abs(t["y0"] - t["y1"]) < 1e-6 else ys
        for p, R in zip(pos, t["analysis"]["reactions_t"]):
            key = (p, t["y0"]) if abs(t["y0"] - t["y1"]) < 1e-6 else (t["x0"], p)
            reac[key] = reac.get(key, 0.0) + R
    Rmax = max(reac.values())
    frac_d = (fd * w_dead) / wu if wu else 0.7
    servicio = Rmax / fd
    zapata = zap.design_footing("aislada", servicio * frac_d, servicio * (1 - frac_d), allowable_bearing, fc, depth,
                                column=(column_size, column_size), soil_unit_weight=soil_unit_weight, fy=fy,
                                code=code, mark="Z-1")
    decisiones.append(f"Zapata Z-1 para la reacción máxima ({Rmax:.1f} t factorizada) en todas las columnas: "
                      f"{zapata['B']:.2f} x {zapata['L']:.2f} x {zapata['h'] * 100:.0f} cm.")
    columnas = [{"x": xv, "y": yv, "type": "Z-1", "reaction_t": _r(reac.get((xv, yv), 0.0), 2)} for xv in xs for yv in ys]
    paneles_out = []
    k = 1
    for (px0, py0, px1, py1) in sorted(paneles, key=lambda p: (p[1], p[0])):
        paneles_out.append({"x0": px0, "y0": py0, "x1": px1, "y1": py1, "mark": str(k),
                            "short": losa["short"], "long": losa["long"]})
        k += 1
    ligas = [{"x0": xv, "y0": ys[0], "x1": xv, "y1": ys[-1], "b": tie_beam_b, "mark": f"CT-{i + 1}"} for i, xv in enumerate(xs)]
    ligas += [{"x0": xs[0], "y0": yv, "x1": xs[-1], "y1": yv, "b": tie_beam_b, "mark": f"CT-{len(xs) + j + 1}"}
              for j, yv in enumerate(ys)]
    return {"slab": losa, "slab_h": h, "beams": trabes, "beam_design": diseno, "beam_h": hb,
            "footing": zapata, "columns": columnas, "panels": paneles_out, "tie_beams": ligas,
            "openings": openings or [], "decisions": decisiones, "column_size": column_size,
            "inputs": {"w_dead": w_dead, "w_live": w_live, "fc": fc, "fy": fy, "code": code,
                       "allowable_bearing": allowable_bearing, "depth": depth}}


def draw_structural_set(design: dict[str, Any], upm: float, origin: tuple[float, float] = (0.0, 0.0),
                        gap: float = 2.0, notes: Optional[list[str]] = None,
                        layout: Optional[str] = "E-01", paper_size: str = "A1",
                        sheet: Optional[dict[str, Any]] = None,
                        title_framing: str = "PLANTA ESTRUCTURAL",
                        title_foundation: str = "PLANTA DE CIMENTACIÓN") -> dict[str, Any]:
    """Dibuja las dos plantas (una al lado de la otra, sin pisarse) desde el
    resultado de design_frame_structure y, si layout no es None, compone la
    lámina con compose_layout (cajón, rótulo y títulos en el papel). Las
    notas de proyecto salen de 'inputs' y de las decisiones de diseño."""
    ox, oy = origin
    inp = design["inputs"]
    base_notes = [
        f"Concreto f'c = {inp['fc']:.0f} kg/cm2; acero fy = {inp['fy']:.0f} kg/cm2.",
        f"Cargas de servicio: muerta {inp['w_dead']:.0f} kg/m2 (sin peso propio de losa) + viva "
        f"{inp['w_live']:.0f} kg/m2; combinación {zap.COMBOS[inp['code']][2]}.",
        "Recubrimiento libre: trabes 4 cm, losa 2 cm, zapatas 7.5 cm.",
        "Dimensiones en metros; armados en número de varilla y separación en cm.",
    ] + (notes or [])
    desplazar = lambda d, dx: {**d, "x0": d["x0"] + dx, "x1": d["x1"] + dx, "y0": d["y0"] + oy, "y1": d["y1"] + oy}
    cols = [{**c, "x": c["x"] + ox, "y": c["y"] + oy} for c in design["columns"]]
    beams = [desplazar(b, ox) for b in design["beams"]]
    panels = [desplazar(p, ox) for p in design["panels"]]
    huecos = [[h[0] + ox, h[1] + oy, h[2] + ox, h[3] + oy] for h in design["openings"]]
    # El título va en el MODELO (lo lee quien abra el DWG, y check_view_titles
    # lo exige); el layout no repite el suyo (draw_titles=False).
    r1 = pe.draw_framing_plan(cols, beams, panels, upm, huecos, design["column_size"],
                              title=title_framing,
                              beam_designs={b["mark"]: design["beam_design"] for b in design["beams"]},
                              slab_thickness=design["slab_h"], notes=base_notes)
    b1 = r1["box"]
    # La cimentación arranca donde termina la planta (cuadro incluido) más lo
    # que sus propios ejes, cotas y la zapata izquierda se extienden a la izquierda.
    B = design["footing"]["B"]
    ext_izq = B / 2 + 1.2 + 30 * upm + 8 * upm
    ox2 = b1[2] + gap + ext_izq
    cols2 = [{**c, "x": c["x"] - ox + ox2} for c in cols]
    ligas = [desplazar(t, ox2) for t in design["tie_beams"]]
    W = max(c["x"] for c in design["columns"]) - min(c["x"] for c in design["columns"])
    D = max(c["y"] for c in design["columns"]) - min(c["y"] for c in design["columns"])
    r2 = pe.draw_foundation_plan(cols2, {"Z-1": design["footing"]}, ligas, (W, D), upm,
                                 design["column_size"], title=title_foundation,
                                 origin=(ox2, oy),
                                 notes=[f"Capacidad de carga admisible del suelo: {inp['allowable_bearing']:.1f} t/m2 "
                                        f"(E.M.S.); desplante a {inp['depth']:.2f} m.",
                                        "Plantilla de concreto pobre de 5 cm bajo zapatas y contratrabes."])
    out: dict[str, Any] = {"framing": r1, "foundation": r2, "decisions": design["decisions"]}
    if layout:
        esc = round(1000 * upm)
        views = [{"name": "planta", "box": b1, "scale_denominator": esc},
                 {"name": "cimentacion", "box": r2["box"], "scale_denominator": esc}]
        out["layout"] = compose.compose_layout(layout, views, model_units="m", paper_size=paper_size,
                                               sheet=sheet, draw_titles=False)
    return out
