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

import arch
import autocad_client
import sheet

DRAWN: list[dict[str, Any]] = []
_next_handle = [0x100]

# Color por capa, solo para que el preview se lea; AutoCAD usa los ACI reales.
LAYER_COLORS = {
    "CAJON": "#1a1a1a",
    "ROTULO": "#1a1a1a",
    "MUROS": "#111111",
    "PUERTAS-VENTANAS": "#356fb5",
    "EJES": "#12879b",
}
DEFAULT_COLOR = "#444444"


def fake_call(cmd: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    _next_handle[0] += 1
    handle = format(_next_handle[0], "X")
    if cmd in ("create_polyline", "create_line", "create_text",
               "create_circle", "create_arc"):
        DRAWN.append({"cmd": cmd, **params})
    return {"handle": handle, "status": "ok", "area": 0.0}


def install() -> None:
    """Desvía todas las llamadas al plugin hacia el mock."""
    DRAWN.clear()
    autocad_client.call = fake_call
    sheet.acad.call = fake_call
    arch.acad.call = fake_call


def _color(entity: dict[str, Any]) -> str:
    return LAYER_COLORS.get(entity.get("layer") or "", DEFAULT_COLOR)


def bounds(entities: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for e in entities:
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
