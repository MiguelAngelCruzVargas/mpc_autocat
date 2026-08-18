"""Renderiza el cajón + rótulo a un SVG, SIN AutoCAD.

Reemplaza el socket por un mock que captura lo que se habría dibujado, y lo
dibuja en un SVG. Sirve para iterar el diseño de la rotulación (proporciones,
qué campo va dónde, alturas de texto) sin tener que abrir AutoCAD ni recargar
el plugin.

Uso:
  python preview_sheet.py [salida.svg]
"""
from __future__ import annotations

import io
import sys
from typing import Any

import autocad_client
import sheet as sheet_mod

# ------------------------------------------------------------------ el mock

_drawn: list[dict[str, Any]] = []
_next_handle = [0x100]


def _fake_call(cmd: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    _next_handle[0] += 1
    handle = format(_next_handle[0], "X")
    if cmd in ("create_polyline", "create_line", "create_text"):
        _drawn.append({"cmd": cmd, **params})
    return {"handle": handle, "status": "ok", "area": 0.0}


# ------------------------------------------------------------------- el SVG

def _svg(entities: list[dict[str, Any]], w: float, h: float,
         ox: float, oy: float) -> str:
    """Modelo -> SVG. Y se invierte: en AutoCAD crece hacia arriba."""
    pad = w * 0.03
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{ox - pad} {oy - pad} {w + 2 * pad} {h + 2 * pad}" '
        f'width="1100">',
        f'<rect x="{ox - pad}" y="{oy - pad}" width="{w + 2 * pad}" '
        f'height="{h + 2 * pad}" fill="#faf9f7"/>',
        f'<g transform="translate(0,{2 * oy + h}) scale(1,-1)">',
    ]

    def stroke_w(lw: Any) -> float:
        # centesimas de mm de papel -> unidades de modelo, solo para que el
        # preview muestre la jerarquia de grosores.
        return max((lw or 25) / 100.0 * (w / 841.0), w / 4000.0)

    for e in entities:
        lw = stroke_w(e.get("lineweight"))
        if e["cmd"] == "create_polyline":
            pts = " ".join(f"{p[0]},{p[1]}" for p in e["points"])
            close = "Z" if e.get("closed") else ""
            out.append(
                f'<polygon points="{pts}" fill="none" stroke="#1a1a1a" '
                f'stroke-width="{lw}"/>' if close else
                f'<polyline points="{pts}" fill="none" stroke="#1a1a1a" '
                f'stroke-width="{lw}"/>')
        elif e["cmd"] == "create_line":
            out.append(
                f'<line x1="{e["x1"]}" y1="{e["y1"]}" x2="{e["x2"]}" '
                f'y2="{e["y2"]}" stroke="#1a1a1a" stroke-width="{lw}"/>')
        elif e["cmd"] == "create_text":
            txt = (e["text"].replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;"))
            fs = e["height"]
            out.append(
                f'<g transform="translate({e["x"]},{e["y"]}) scale(1,-1)">'
                f'<text x="0" y="0" font-family="Arial, Helvetica, sans-serif" '
                f'font-size="{fs}" fill="#1a1a1a">{txt}</text></g>')

    out.append("</g></svg>")
    return "\n".join(out)


def main() -> int:
    autocad_client.call = _fake_call
    sheet_mod.acad.call = _fake_call

    info = sheet_mod.create_sheet(
        sheet_format="A1",
        scale_denominator=100.0,
        model_units="m",
        project="CASA HABITACIÓN FAMILIA CRUZ VARGAS",
        location="AV. REFORMA 123, COL. CENTRO, OAXACA DE JUÁREZ, OAX.",
        client="MIGUEL ÁNGEL CRUZ VARGAS",
        content="PLANTA ARQUITECTÓNICA BAJA",
        drawn_by="M. A. CRUZ",
        reviewed_by="ARQ. RESPONSABLE",
        date="18/08/2026",
        sheet_number="A-01",
    )

    w, h = info["sheetSizeModel"]
    svg = _svg(_drawn, w, h, 0.0, 0.0)

    out_path = sys.argv[1] if len(sys.argv) > 1 else "preview_sheet.svg"
    io.open(out_path, "w", encoding="utf-8").write(svg)

    print(f"formato {info['format']} escala {info['scale']} "
          f"({info['modelUnits']}) -> {w:g} x {h:g} unidades de modelo")
    d = info["drawArea"]
    print(f"area util (arriba del rotulo): "
          f"{d['x2'] - d['x1']:.2f} x {d['y2'] - d['y1']:.2f}")
    print(f"area util (completa, al lado del rotulo): "
          f"{d['full_x2'] - d['full_x1']:.2f} x {d['full_y2'] - d['full_y1']:.2f}")
    print(f"{len(_drawn)} entidades -> {out_path}")

    # Chequeo: nada puede quedar fuera de la hoja.
    fuera = []
    for e in _drawn:
        if e["cmd"] == "create_polyline":
            coords = [(p[0], p[1]) for p in e["points"]]
        elif e["cmd"] == "create_line":
            coords = [(e["x1"], e["y1"]), (e["x2"], e["y2"])]
        else:
            coords = [(e["x"], e["y"])]
        for x, y in coords:
            if not (-0.01 <= x <= w + 0.01 and -0.01 <= y <= h + 0.01):
                fuera.append((e["cmd"], x, y))
    if fuera:
        print("AVISO: entidades fuera de la hoja:", fuera[:5])
        return 1
    print("OK: todo cae dentro de la hoja.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
