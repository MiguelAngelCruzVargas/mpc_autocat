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
import layers
import quantities
import sections
import sheet
import space

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
        DRAWN.append({"cmd": cmd, **params})
    elif cmd == "create_mtext":
        DRAWN.append({"cmd": "create_text", **params})
    elif cmd == "create_hatch":
        # No se dibuja (habria que resolver el contorno), pero queda anotado:
        # sin esto un test no puede verificar que un simbolo salio relleno.
        DRAWN.append({"cmd": cmd, **params})
    elif cmd in ("create_dimension", "create_dimension_rotated"):
        # Las cotas se descomponen en las lineas y el numero que se ven en el
        # papel. Sin esto el preview las tiraba en silencio, que es justo por
        # lo que una cota encimada solo aparecia al abrir el DWG.
        DRAWN.extend(_expand_dimension(params, rotated=cmd.endswith("rotated")))
    return {"handle": handle, "status": "ok", "area": 0.0}


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
    for modulo in (sheet, arch, furniture, annotation, sections):
        modulo.acad.call = fake_call
    # El preview arranca de cero: sin esto, dos corridas seguidas en el mismo
    # proceso apilan las cotas sobre franjas del plano anterior.
    space.clear()
    layers.reset()
    # El mock no tiene estilos: se da por chequeado.
    layers._TEXT_CHECKED[0] = True
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

    def stroke(e: dict[str, Any]) -> float:
        # centesimas de mm -> algo proporcional, solo para ver la jerarquia.
        lw = e.get("lineweight") or 25
        return max(lw / 100.0 * (span / 841.0), span / 5000.0)

    for e in entities:
        col = _color(e)
        sw = stroke(e)
        if e["cmd"] == "create_polyline":
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
            out.append(
                f'<g transform="translate({e["x"]},{e["y"]}) scale(1,-1)">'
                f'<text x="0" y="0" font-family="Arial, Helvetica, sans-serif" '
                f'font-size="{e["height"]}" fill="{col}">{txt}</text></g>')

    out.append("</g></svg>")
    return "\n".join(out)


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
