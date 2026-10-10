"""Motor de preview: mockea el socket y renderiza a SVG. SIN AutoCAD.

Reemplaza autocad_client.call por un mock que captura lo que se habría
dibujado, y lo vuelca a un SVG. Sirve para iterar el diseño de la rotulación,
los muros o los ejes sin abrir AutoCAD ni recargar el plugin.

Lo usan preview_sheet.py (solo el cajón) y preview_plan.py (un plano completo).
"""
from __future__ import annotations

import io
import math
from typing import Any

import annotation
import arch
import autocad_client
import furniture
import isometric
import layers
import materials
import quantities
import rebar
import roof
import sections
import sheet
import space
import symbols

DRAWN: list[dict[str, Any]] = []
_next_handle = [0x100]

# Color por capa, solo para que el preview se lea; AutoCAD usa los ACI reales.
LAYER_COLORS = {
    "CAJON": "#1a1a1a",
    "ROTULO": "#1a1a1a",
    "MUROS": "#111111",
    "PUERTAS-VENTANAS": "#356fb5",
    "EJES": "#12879b",
    "COTAS": "#8a5a1b",
    "TEXTOS": "#333333",
    "MOBILIARIO": "#5b6b7a",
    "CORTES-ARQ": "#111111",
    "CORTES-ARQ-VISTO": "#5b6b7a",
    "FACHADAS": "#356fb5",
    "CUBIERTA": "#111111",
    "ESTRUCTURA-TECHO": "#5b6b7a",
    "DETALLES": "#111111",
    "TERRENO-CORTE": "#6b5b45",
    "ARMADO": "#8a1b1b",
    "CIMENTACION-MURO": "#111111",
    "TITULOS": "#2b5c8a",
}
DEFAULT_COLOR = "#444444"


# Relacion ancho/altura por caracter medida contra AutoCAD real con arial.
# El preview la usa para que los textos ocupen aca lo mismo que alla.
CHAR_W_RATIO = 0.87


def fake_call(cmd: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    _next_handle[0] += 1
    handle = format(_next_handle[0], "X")

    if cmd == "measure_text":
        text = str(params.get("text", ""))
        h = float(params.get("height", 1.0))
        return {"text": text, "width": len(text) * h * CHAR_W_RATIO,
                "height": h, "charWidthRatio": CHAR_W_RATIO}
    if cmd in ("create_polyline", "create_line", "create_text",
               "create_circle", "create_arc"):
        DRAWN.append({"cmd": cmd, "handle": handle, **params})
    elif cmd == "create_mtext":
        DRAWN.append({"cmd": "create_text", "handle": handle, **params})
    elif cmd == "create_hatch":
        # Se guarda con su handle de contorno: to_svg lo rellena resolviendo
        # el contorno (y las islas) entre lo ya dibujado, asi el achurado se
        # ve en el preview igual que en el DWG -- antes se descartaba y un
        # detalle "sin textura" solo se descubria abriendo AutoCAD.
        # El contorno se resuelve AHORA y se guarda adentro: en AutoCAD un
        # hatch no asociativo sobrevive a que se borre su contorno (es lo
        # que hace soil_section a proposito), y el preview tiene que
        # sobrevivir igual.
        por_handle = {e.get("handle"): e for e in DRAWN if e.get("handle")}
        entry = {"cmd": cmd, "handle": handle, **params}
        entry["_boundary"] = por_handle.get(params.get("boundaryHandle"))
        entry["_islands"] = [por_handle[h] for h in (params.get("islandHandles") or [])
                             if h in por_handle]
        DRAWN.append(entry)
    elif cmd == "delete_entity":
        _borrar([params.get("handle")])
    elif cmd == "delete_entities":
        _borrar(list(params.get("handles") or []))
    elif cmd in ("create_dimension", "create_dimension_rotated"):
        # Las cotas se descomponen en las lineas y el numero que se ven en el
        # papel. Sin esto el preview las tiraba en silencio, que es justo por
        # lo que una cota encimada solo aparecia al abrir el DWG.
        DRAWN.extend(_expand_dimension(params, rotated=cmd.endswith("rotated")))
    return {"handle": handle, "status": "ok", "area": 0.0}


def _borrar(handles: list) -> None:
    quitar = {h for h in handles if h}
    DRAWN[:] = [e for e in DRAWN if e.get("handle") not in quitar]


# Altura del numero de cota: DIMTXT por DIMSCALE. El estilo base son 2.5 mm
# de papel, y 'scale' son las unidades del modelo que mide 1 mm de papel.
DIM_TXT_MM = 2.5


def _expand_dimension(params: dict[str, Any],
                      rotated: bool) -> list[dict[str, Any]]:
    p1 = (float(params["x1"]), float(params["y1"]))
    p2 = (float(params["x2"]), float(params["y2"]))
    dl = (float(params["dimLineX"]), float(params["dimLineY"]))
    escala = float(params.get("scale") or 0.1)
    h = DIM_TXT_MM * escala
    layer = params.get("layer") or "COTAS"
    lw = params.get("lineweight") or 13

    if rotated:
        a = math.radians(float(params.get("angleDeg") or 0.0))
        u = (math.cos(a), math.sin(a))
    else:
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        largo = math.hypot(dx, dy) or 1.0
        u = (dx / largo, dy / largo)
    n = (-u[1], u[0])

    def pie(p):
        """El punto proyectado sobre la linea de cota."""
        t = (dl[0] - p[0]) * n[0] + (dl[1] - p[1]) * n[1]
        return (p[0] + n[0] * t, p[1] + n[1] * t)

    f1, f2 = pie(p1), pie(p2)
    valor = math.hypot(f2[0] - f1[0], f2[1] - f1[1])

    def linea(a, b, grosor):
        return {"cmd": "create_line", "x1": a[0], "y1": a[1], "z1": 0.0,
                "x2": b[0], "y2": b[1], "z2": 0.0,
                "layer": layer, "lineweight": grosor, "colorIndex": None}

    salida = [linea(p1, f1, lw), linea(p2, f2, lw), linea(f1, f2, lw)]

    # Marca oblicua en cada extremo, que es como se rematan las cotas de
    # arquitectura (la flecha se usa en mecanica).
    t = h * 0.45
    for f in (f1, f2):
        d = (u[0] + n[0], u[1] + n[1])
        salida.append(linea((f[0] - d[0] * t, f[1] - d[1] * t),
                            (f[0] + d[0] * t, f[1] + d[1] * t), lw))

    medio = ((f1[0] + f2[0]) / 2.0, (f1[1] + f2[1]) / 2.0)
    texto = params.get("text") or f"{valor:.2f}"
    ancho = len(texto) * h * CHAR_W_RATIO
    ang = math.degrees(math.atan2(u[1], u[0]))
    if ang > 90 or ang < -90:
        ang += 180
    ar = math.radians(ang)
    # Centrado sobre la linea y corrido hacia afuera: el numero va ARRIBA de
    # la linea de cota, no encima.
    base = (medio[0] - math.cos(ar) * ancho / 2.0 - n[0] * h * 0.35,
            medio[1] - math.sin(ar) * ancho / 2.0 - n[1] * h * 0.35)
    salida.append({"cmd": "create_text", "text": texto,
                   "x": base[0], "y": base[1], "z": 0.0, "height": h,
                   "layer": layer, "rotationDeg": ang,
                   "lineweight": lw, "colorIndex": None})
    return salida


def install() -> None:
    """Desvía todas las llamadas al plugin hacia el mock."""
    DRAWN.clear()
    autocad_client.call = fake_call
    for modulo in (sheet, arch, furniture, annotation, sections, roof, rebar,
                   isometric, materials, symbols):
        modulo.acad.call = fake_call
    # El preview arranca de cero: sin esto, dos corridas seguidas en el mismo
    # proceso apilan las cotas sobre franjas del plano anterior.
    space.clear()
    layers.reset()
    # El mock no tiene estilos: se da por chequeado.
    layers._TEXT_CHECKED[0] = True
    # Y no tiene get_drawing_info: los patrones se toman en pulgadas
    # (acad.pat), que es la base de NATIVE_MODULE.
    materials.set_pattern_units("inch")
    furniture.reset_footprints()


def _color(entity: dict[str, Any]) -> str:
    return LAYER_COLORS.get(entity.get("layer") or "", DEFAULT_COLOR)


def bounds(entities: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for e in entities:
        if "x" not in e and e["cmd"] not in ("create_polyline", "create_line"):
            continue      # entidades sin geometria propia, como el achurado
        if e["cmd"] == "create_polyline":
            xs += [p[0] for p in e["points"]]
            ys += [p[1] for p in e["points"]]
        elif e["cmd"] == "create_line":
            xs += [e["x1"], e["x2"]]
            ys += [e["y1"], e["y2"]]
        elif e["cmd"] in ("create_circle", "create_arc"):
            xs += [e["x"] - e["radius"], e["x"] + e["radius"]]
            ys += [e["y"] - e["radius"], e["y"] + e["radius"]]
        else:
            xs.append(e["x"])
            ys.append(e["y"])
    return min(xs), min(ys), max(xs), max(ys)


def to_svg(entities: list[dict[str, Any]], width_px: int = 1200,
           reference_span: float | None = None) -> str:
    """Modelo -> SVG. Y se invierte: en AutoCAD crece hacia arriba."""
    x0, y0, x1, y1 = bounds(entities)
    w, h = x1 - x0, y1 - y0
    pad = max(w, h) * 0.03
    span = reference_span or max(w, h)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{x0 - pad} {y0 - pad} {w + 2 * pad} {h + 2 * pad}" '
        f'width="{width_px}">',
        f'<rect x="{x0 - pad}" y="{y0 - pad}" width="{w + 2 * pad}" '
        f'height="{h + 2 * pad}" fill="#faf9f7"/>',
        f'<g transform="translate(0,{2 * y0 + h}) scale(1,-1)">',
    ]
    por_handle = {e.get("handle"): e for e in entities if e.get("handle")}
    defs: list[str] = []
    # Los achurados van primero, debajo de las lineas.
    for e in entities:
        if e["cmd"] == "create_hatch":
            out.append(_hatch_svg(e, por_handle, defs, span))
    if defs:
        out.insert(3, "<defs>" + "".join(defs) + "</defs>")

    def stroke(e: dict[str, Any]) -> float:
        # centesimas de mm -> algo proporcional, solo para ver la jerarquia.
        lw = e.get("lineweight") or 25
        return max(lw / 100.0 * (span / 841.0), span / 5000.0)

    for e in entities:
        col = _color(e)
        sw = stroke(e)
        if e["cmd"] == "create_polyline":
            if any(abs(b) > 1e-9 for b in (e.get("bulges") or [])):
                out.append(f'<path d="{_contorno_path(e)}" fill="none" '
                           f'stroke="{col}" stroke-width="{sw}" '
                           f'stroke-linejoin="round"/>')
                continue
            pts = " ".join(f"{p[0]},{p[1]}" for p in e["points"])
            tag = "polygon" if e.get("closed") else "polyline"
            out.append(f'<{tag} points="{pts}" fill="none" stroke="{col}" '
                       f'stroke-width="{sw}" stroke-linejoin="miter"/>')
        elif e["cmd"] == "create_line":
            out.append(f'<line x1="{e["x1"]}" y1="{e["y1"]}" x2="{e["x2"]}" '
                       f'y2="{e["y2"]}" stroke="{col}" stroke-width="{sw}"/>')
        elif e["cmd"] == "create_circle":
            out.append(f'<circle cx="{e["x"]}" cy="{e["y"]}" r="{e["radius"]}" '
                       f'fill="none" stroke="{col}" stroke-width="{sw}"/>')
        elif e["cmd"] == "create_arc":
            out.append(_arc_path(e, col, sw))
        elif e["cmd"] == "create_text":
            txt = (e["text"].replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;"))
            just = str(e.get("justify") or "left")
            ancla = ("middle" if just.endswith("center") else
                     "end" if just.endswith("right") else "start")
            base = (' dominant-baseline="central"' if just.startswith("middle") else "")
            out.append(
                f'<g transform="translate({e["x"]},{e["y"]}) scale(1,-1)">'
                f'<text x="0" y="0" font-family="Arial, Helvetica, sans-serif" '
                f'font-size="{e["height"]}" fill="{col}" text-anchor="{ancla}"{base}>'
                f'{txt}</text></g>')

    out.append("</g></svg>")
    return "\n".join(out)


def _contorno_path(e: dict[str, Any]) -> str:
    """Un contorno cerrado (polilinea o circulo) como subpath SVG. Los
    bulges se aproximan con un arco SVG por tramo."""
    if e["cmd"] == "create_circle":
        cx, cy, r = e["x"], e["y"], e["radius"]
        return (f"M {cx - r},{cy} A {r},{r} 0 1,0 {cx + r},{cy} "
                f"A {r},{r} 0 1,0 {cx - r},{cy} Z")
    if e["cmd"] != "create_polyline":
        return ""
    pts = e["points"]
    bulges = e.get("bulges") or [0.0] * len(pts)
    d = [f"M {pts[0][0]},{pts[0][1]}"]
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        if j == 0 and not e.get("closed"):
            break
        b = bulges[i] if i < len(bulges) else 0.0
        p, q = pts[i], pts[j]
        if abs(b) < 1e-9:
            d.append(f"L {q[0]},{q[1]}")
        else:
            c = math.dist(p, q)
            theta = 4.0 * math.atan(abs(b))
            r = c / (2.0 * math.sin(theta / 2.0)) if theta > 1e-9 else c
            large = 1 if theta > math.pi else 0
            sweep = 1 if b > 0 else 0
            d.append(f"A {r},{r} 0 {large},{sweep} {q[0]},{q[1]}")
    if e.get("closed"):
        d.append("Z")
    return " ".join(d)


def _hatch_svg(e: dict[str, Any], por_handle: dict[str, Any],
               defs: list[str], span: float) -> str:
    """El achurado como relleno del contorno con un patron SVG del mismo
    modulo que tendria en AutoCAD (scale x modulo nativo del patron)."""
    borde = e.get("_boundary") or por_handle.get(e.get("boundaryHandle"))
    if not borde:
        return ""
    path = _contorno_path(borde)
    islas = e.get("_islands") or [por_handle[h] for h in (e.get("islandHandles") or [])
                                  if h in por_handle]
    for isla in islas:
        path += " " + _contorno_path(isla)
    patron = str(e.get("pattern") or "SOLID").upper()
    col = _color(borde)
    if patron == "SOLID":
        ci = e.get("colorIndex")
        if isinstance(ci, int) and 250 <= ci <= 255:
            col = "#%02x%02x%02x" % ((51 + (ci - 250) * 40,) * 3)
        elif ci == 8:
            col = "#888888"
        return f'<path d="{path}" fill="{col}" fill-rule="evenodd" stroke="none"/>'
    esc = float(e.get("scale") or 1.0)
    modulo = esc * materials.NATIVE_MODULE.get(patron, 1.0)
    ang = float(e.get("angleDeg") or 0.0)
    pid = f"p{len(defs)}"
    sw = max(span / 2500.0, modulo / 40.0)
    m = modulo
    if patron.startswith("ANSI3") or patron == "LINE":
        base = 0.0 if patron == "ANSI37" else 45.0
        cuerpo = (f'<line x1="0" y1="0" x2="0" y2="{m}" stroke="{col}" '
                  f'stroke-width="{sw}"/>')
        if patron == "ANSI37":
            cuerpo += (f'<line x1="0" y1="0" x2="{m}" y2="0" stroke="{col}" '
                       f'stroke-width="{sw}"/>')
        rot = base + ang
    elif patron == "EARTH":
        # Rayas cortas en dos direcciones alternadas: el simbolo de tierra.
        cuerpo = (f'<line x1="0" y1="{m * 0.5}" x2="{m * 0.7}" y2="{m * 0.5}" '
                  f'stroke="{col}" stroke-width="{sw}"/>'
                  f'<line x1="{m * 0.5}" y1="{m}" x2="{m * 0.5}" y2="{m * 1.7}" '
                  f'stroke="{col}" stroke-width="{sw}"/>')
        m = m * 2.0
        rot = ang
    elif patron in ("AR-CONC", "AR-SAND", "DOTS", "GRAVEL"):
        rnd = [(0.15, 0.2, 0.09), (0.55, 0.7, 0.06), (0.8, 0.25, 0.05),
               (0.35, 0.85, 0.07), (0.62, 0.42, 0.04)]
        k = 1.0 if patron == "AR-CONC" else 0.6
        cuerpo = "".join(
            f'<circle cx="{m * a}" cy="{m * b}" r="{m * c * k}" fill="{col}"/>'
            for a, b, c in rnd)
        rot = ang
    elif patron.startswith("AR-B"):
        alto = m / 2.0
        cuerpo = (f'<rect x="0" y="0" width="{m}" height="{alto}" fill="none" '
                  f'stroke="{col}" stroke-width="{sw}"/>'
                  f'<rect x="{-m / 2}" y="{alto}" width="{m}" height="{alto}" '
                  f'fill="none" stroke="{col}" stroke-width="{sw}"/>'
                  f'<rect x="{m / 2}" y="{alto}" width="{m}" height="{alto}" '
                  f'fill="none" stroke="{col}" stroke-width="{sw}"/>')
        rot = ang
    else:
        cuerpo = (f'<line x1="0" y1="0" x2="0" y2="{m}" stroke="{col}" '
                  f'stroke-width="{sw}"/>')
        rot = 45.0 + ang
    defs.append(
        f'<pattern id="{pid}" patternUnits="userSpaceOnUse" width="{m}" '
        f'height="{m}" patternTransform="rotate({rot})">{cuerpo}</pattern>')
    return (f'<path d="{path}" fill="url(#{pid})" fill-rule="evenodd" '
            f'stroke="none" opacity="0.85"/>')


def _arc_path(e: dict[str, Any], color: str, stroke_width: float) -> str:
    """Arco antihorario de AutoCAD -> path SVG."""
    cx, cy, r = e["x"], e["y"], e["radius"]
    a0 = math.radians(e["startAngleDeg"])
    a1 = math.radians(e["endAngleDeg"])
    sweep = (a1 - a0) % (2 * math.pi)
    x_start, y_start = cx + r * math.cos(a0), cy + r * math.sin(a0)
    x_end, y_end = cx + r * math.cos(a1), cy + r * math.sin(a1)
    large = 1 if sweep > math.pi else 0
    # sweep-flag 1 = antihorario en el sistema ya invertido por el <g>.
    return (f'<path d="M {x_start},{y_start} A {r},{r} 0 {large},1 '
            f'{x_end},{y_end}" fill="none" stroke="{color}" '
            f'stroke-width="{stroke_width}"/>')


def save(path: str, entities: list[dict[str, Any]], **kwargs: Any) -> None:
    io.open(path, "w", encoding="utf-8").write(to_svg(entities, **kwargs))


def check_inside(entities: list[dict[str, Any]], w: float, h: float,
                 ox: float = 0.0, oy: float = 0.0,
                 tol: float = 0.01) -> list[tuple[str, float, float]]:
    """Entidades que se salen de la hoja."""
    out: list[tuple[str, float, float]] = []
    for e in entities:
        if "x" not in e and e["cmd"] not in ("create_polyline", "create_line"):
            continue
        if e["cmd"] == "create_polyline":
            coords = [(p[0], p[1]) for p in e["points"]]
        elif e["cmd"] == "create_line":
            coords = [(e["x1"], e["y1"]), (e["x2"], e["y2"])]
        elif e["cmd"] in ("create_circle", "create_arc"):
            coords = [(e["x"] - e["radius"], e["y"] - e["radius"]),
                      (e["x"] + e["radius"], e["y"] + e["radius"])]
        else:
            coords = [(e["x"], e["y"])]
        for x, y in coords:
            if not (ox - tol <= x <= ox + w + tol
                    and oy - tol <= y <= oy + h + tol):
                out.append((e["cmd"], x, y))
    return out
