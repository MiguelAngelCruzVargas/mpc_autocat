"""Teléfono en 3D a partir de DIMENSIONES: ningún modelo de teléfono está
cableado acá. Alto, ancho, espesor, radio de esquina, pantalla, plateau de
cámara, lentes y botones son parámetros; los datos de un modelo concreto
(163.4 x 78.0 x 8.75 mm, etc.) los trae quien llama.

Se compone sobre comandos del plugin que NO dependen de run_code:
`extrude_profile` (contorno de líneas y arcos -> sólido), `solid_boolean` y
`fillet_solid_edges`. Unidades: las que use el dibujo (mm en el ejemplo).

Convención: vista frontal, X crece a la derecha, Y hacia arriba. La base de
la caja está en Z=0 (el dorso) y la pantalla mira a +Z: el cuerpo ocupa
Z de 0 a `thickness`; plateau y lentes salen del dorso hacia -Z.
Las medidas "from_top" / "from_left" se toman desde el borde superior /
izquierdo del frente.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad

K90 = math.tan(math.radians(90) / 4)   # bulge de un arco de 90 grados

# Piezas, en el orden en que se crean. Cada una va en su capa y su color.
PIEZAS = ("body", "screen", "island", "plateau", "lens_ring", "lens_glass",
          "button")
CAPA = {
    "body": "TEL-CUERPO", "screen": "TEL-PANTALLA", "island": "TEL-PANTALLA",
    "plateau": "TEL-PLATEAU", "lens_ring": "TEL-LENTES",
    "lens_glass": "TEL-LENTES", "button": "TEL-BOTONES",
}

# Acabados: color ACI por pieza. Del 10 al 255 para que se lean en pantalla
# y en papel (ver CLAUDE.md, "Color"). Son una paleta de partida, no la
# medición de ningún modelo: cualquier pieza se pisa con `colors`.
ACABADOS: dict[str, dict[str, int]] = {
    "grafito": {"body": 252, "plateau": 251, "button": 252, "screen": 250,
                "island": 251, "lens_ring": 8, "lens_glass": 250},
    "plata":   {"body": 254, "plateau": 253, "button": 254, "screen": 250,
                "island": 251, "lens_ring": 8, "lens_glass": 250},
    "dorado":  {"body": 42, "plateau": 41, "button": 42, "screen": 250,
                "island": 251, "lens_ring": 8, "lens_glass": 250},
    "azul":    {"body": 150, "plateau": 154, "button": 150, "screen": 250,
                "island": 251, "lens_ring": 8, "lens_glass": 250},
}

EMBED = 0.3      # cuánto entra un botón en el cuerpo, para que no flote
CUT_MARGIN = 0.2  # cuánto sobresale la herramienta de resta del frente


# ------------------------------------------------------------- contornos

def rounded_rect(x0: float, y0: float, x1: float, y1: float,
                 r: float) -> tuple[list[list[float]], list[float]]:
    """Rectángulo de esquinas redondeadas como puntos + bulges (líneas y
    arcos de 90° en un solo contorno cerrado, antihorario). Si r llega a
    media arista el tramo recto mide 0: se descarta y quedan solo arcos
    (una píldora)."""
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        raise ValueError(f"Rectángulo sin área: {w} x {h}.")
    if r < 0 or r > min(w, h) / 2 + 1e-9:
        raise ValueError(
            f"Radio de esquina {r} no cabe en {w:.2f} x {h:.2f} "
            f"(máximo {min(w, h) / 2:.2f}).")
    if r < 1e-9:
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], [0.0] * 4
    pts = [(x0 + r, y0), (x1 - r, y0), (x1, y0 + r), (x1, y1 - r),
           (x1 - r, y1), (x0 + r, y1), (x0, y1 - r), (x0, y0 + r)]
    bul = [0.0, K90, 0.0, K90, 0.0, K90, 0.0, K90]
    out_p: list[list[float]] = []
    out_b: list[float] = []
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        if math.dist(pts[i], pts[j]) < 1e-9:
            continue        # tramo recto de longitud 0: el arco siguiente sigue
        out_p.append([pts[i][0], pts[i][1]])
        out_b.append(bul[i])
    return out_p, out_b


def circle(cx: float, cy: float, d: float
           ) -> tuple[list[list[float]], list[float]]:
    """Círculo como dos semicírculos (bulge 1) en un contorno cerrado."""
    if d <= 0:
        raise ValueError(f"Diámetro inválido: {d}.")
    r = d / 2
    return [[cx - r, cy], [cx + r, cy]], [1.0, 1.0]


# ------------------------------------------------------------ validación

def _bezel(screen: dict[str, Any]) -> tuple[float, float, float, float]:
    b = screen.get("bezel")
    if b is None:
        raise ValueError("screen.bezel es obligatorio (marco: un número o "
                         "[izq, der, arriba, abajo]).")
    if isinstance(b, (int, float)):
        return float(b), float(b), float(b), float(b)
    if len(b) != 4:
        raise ValueError("screen.bezel: un número o [izq, der, arriba, abajo].")
    return tuple(float(v) for v in b)  # type: ignore[return-value]


def _colors(finish: Optional[str],
            colors: Optional[dict[str, int]]) -> dict[str, int]:
    base = dict(ACABADOS["grafito"])
    if finish is not None:
        if finish not in ACABADOS:
            raise ValueError(f"Acabado '{finish}' no existe: "
                             f"{', '.join(ACABADOS)}.")
        base = dict(ACABADOS[finish])
    for k, v in (colors or {}).items():
        if k not in PIEZAS:
            raise ValueError(f"Pieza '{k}' no existe: {', '.join(PIEZAS)}.")
        base[k] = int(v)
    for k, v in base.items():
        if not 0 <= v <= 255:
            raise ValueError(f"Color ACI {v} fuera de 0-255 ({k}).")
    return base


def validate(width: float, height: float, thickness: float,
             corner_radius: float, edge_radius: Optional[float],
             screen: Optional[dict[str, Any]],
             plateau: Optional[dict[str, Any]],
             lenses: list[dict[str, Any]],
             buttons: list[dict[str, Any]]) -> list[str]:
    """Chequea que las piezas existan de verdad. Tira ValueError si algo es
    imposible; devuelve avisos para lo dudoso."""
    warnings: list[str] = []
    for nombre, v in (("width", width), ("height", height),
                      ("thickness", thickness)):
        if v <= 0:
            raise ValueError(f"{nombre} tiene que ser > 0 (vino {v}).")
    if corner_radius < 0 or corner_radius > min(width, height) / 2:
        raise ValueError(f"corner_radius {corner_radius} no cabe en "
                         f"{width} x {height}.")
    if edge_radius is not None:
        if edge_radius <= 0:
            raise ValueError("edge_radius tiene que ser > 0 (o None).")
        if edge_radius > thickness / 2:
            raise ValueError(
                f"edge_radius {edge_radius} > mitad del espesor "
                f"({thickness / 2:.2f}): los dos cantos se tocarían.")
        if edge_radius > corner_radius:
            warnings.append(
                f"edge_radius {edge_radius} mayor que corner_radius "
                f"{corner_radius}: AutoCAD puede rechazar el fillet.")

    if screen is not None:
        bl, br, bt, bb = _bezel(screen)
        sw, sh = width - bl - br, height - bt - bb
        if sw <= 0 or sh <= 0:
            raise ValueError("El marco (bezel) se come toda la pantalla.")
        depth = screen.get("depth")
        if depth is None or not 0 < depth < thickness:
            raise ValueError(
                "screen.depth (espesor del vidrio) es obligatorio y tiene "
                f"que estar entre 0 y el espesor {thickness}.")
        if edge_radius is not None and min(bl, br, bt, bb) < edge_radius:
            warnings.append("El marco es más fino que edge_radius: el "
                            "rebaje de la pantalla toca el canto redondeado.")
        isl = screen.get("island")
        if isl:
            if (isl["width"] > sw or isl["height"] > sh
                    or isl["from_top"] < 0
                    or isl["from_top"] + isl["height"] > sh):
                raise ValueError("screen.island no cabe en la pantalla.")

    if plateau is not None:
        for k in ("width", "height", "protrusion", "from_left", "from_top"):
            if k not in plateau:
                raise ValueError(f"plateau.{k} es obligatorio.")
        if plateau["protrusion"] <= 0:
            raise ValueError("plateau.protrusion tiene que ser > 0.")
        pr = plateau.get("corner_radius", 0.0)
        if pr > min(plateau["width"], plateau["height"]) / 2:
            raise ValueError("plateau.corner_radius no cabe en el plateau.")
        if (plateau["from_left"] < 0 or plateau["from_top"] < 0
                or plateau["from_left"] + plateau["width"] > width
                or plateau["from_top"] + plateau["height"] > height):
            raise ValueError("El plateau se sale del cuerpo.")
    elif lenses:
        raise ValueError("Hay lentes pero no plateau donde apoyarlos.")

    for i, ln in enumerate(lenses):
        for k in ("dx", "dy", "diameter", "protrusion"):
            if k not in ln:
                raise ValueError(f"lenses[{i}].{k} es obligatorio.")
        rd = ln.get("ring_diameter") or ln["diameter"]
        if rd < ln["diameter"]:
            raise ValueError(f"lenses[{i}]: ring_diameter < diameter.")
        r = rd / 2
        if (ln["dx"] - r < 0 or ln["dy"] - r < 0
                or ln["dx"] + r > plateau["width"]
                or ln["dy"] + r > plateau["height"]):
            raise ValueError(f"lenses[{i}] se sale del plateau.")
        if ln["protrusion"] <= 0:
            raise ValueError(f"lenses[{i}].protrusion tiene que ser > 0.")

    for i, b in enumerate(buttons):
        if b.get("side") not in ("left", "right", "top", "bottom"):
            raise ValueError(f"buttons[{i}].side: left, right, top o bottom.")
        for k in ("from_start", "length", "protrusion"):
            if k not in b:
                raise ValueError(f"buttons[{i}].{k} es obligatorio.")
        along = height if b["side"] in ("left", "right") else width
        if b["from_start"] < 0 or b["from_start"] + b["length"] > along:
            raise ValueError(f"buttons[{i}] se sale del lado {b['side']}.")
        bz = b.get("height", thickness / 2)
        zc = b.get("z_center", thickness / 2)
        if bz <= 0 or zc - bz / 2 < 0 or zc + bz / 2 > thickness:
            raise ValueError(
                f"buttons[{i}]: el alto {bz} centrado en z={zc} se sale del "
                f"espesor {thickness}.")
    return warnings


# ------------------------------------------------------------- dibujo

def _extrude(created: list[str], pts: list[list[float]], bul: list[float],
             z0: float, h: float, piece: str, colors: dict[str, int],
             layer: Optional[str] = None) -> str:
    r = acad.call("extrude_profile", {
        "points": pts, "bulges": bul, "z0": z0, "height": h,
        "layer": layer or CAPA[piece], "colorIndex": colors[piece],
    })
    created.append(r["handle"])
    return r["handle"]


def create_phone(width: float, height: float, thickness: float,
                 corner_radius: float,
                 edge_radius: Optional[float] = None,
                 screen: Optional[dict[str, Any]] = None,
                 plateau: Optional[dict[str, Any]] = None,
                 lenses: Optional[list[dict[str, Any]]] = None,
                 buttons: Optional[list[dict[str, Any]]] = None,
                 finish: Optional[str] = None,
                 colors: Optional[dict[str, int]] = None,
                 origin: tuple[float, float] = (0.0, 0.0),
                 layer_prefix: Optional[str] = None) -> dict[str, Any]:
    """Arma el teléfono completo. Ver la tool `create_phone_3d` en server.py
    para el significado de cada dict."""
    lenses = lenses or []
    buttons = buttons or []
    warnings = validate(width, height, thickness, corner_radius, edge_radius,
                        screen, plateau, lenses, buttons)
    col = _colors(finish, colors)
    ox, oy = origin
    created: list[str] = []
    piezas: dict[str, Any] = {"buttons": [], "lensRings": [], "lensGlasses": []}

    def capa(p: str) -> Optional[str]:
        return (layer_prefix + CAPA[p].split("-", 1)[1]) if layer_prefix else None

    try:
        # 1. Cuerpo: contorno de líneas y arcos extruido, y su canto redondeado
        pts, bul = rounded_rect(ox, oy, ox + width, oy + height, corner_radius)
        body = _extrude(created, pts, bul, 0.0, thickness, "body", col,
                        capa("body"))
        piezas["body"] = body
        if edge_radius:
            f = acad.call("fillet_solid_edges", {
                "handle": body, "radius": edge_radius,
                "zPlanes": [0.0, thickness], "outerOnly": True})
            piezas["edgesFilleted"] = f.get("edgesFilleted")

        # 2. Pantalla: rebaje en el cuerpo + vidrio que lo llena
        if screen is not None:
            bl, br, bt, bb = _bezel(screen)
            depth = float(screen["depth"])
            sx0, sx1 = ox + bl, ox + width - br
            sy0, sy1 = oy + bb, oy + height - bt
            sr = screen.get("corner_radius")
            if sr is None:
                sr = max(corner_radius - min(bl, br, bt, bb), 0.0)
            sr = min(sr, min(sx1 - sx0, sy1 - sy0) / 2)
            spts, sbul = rounded_rect(sx0, sy0, sx1, sy1, sr)
            cut = _extrude(created, spts, sbul, thickness - depth,
                           depth + CUT_MARGIN, "screen", col, capa("screen"))
            acad.call("solid_boolean", {
                "target": body, "tools": [cut], "op": "subtract",
                "deleteTools": True})
            created.remove(cut)
            piezas["screen"] = _extrude(created, spts, sbul, thickness - depth,
                                        depth, "screen", col, capa("screen"))
            isl = screen.get("island")
            if isl:
                iw, ih = isl["width"], isl["height"]
                icx = (sx0 + sx1) / 2 + isl.get("offset_x", 0.0)
                iy1 = sy1 - isl["from_top"]
                ipts, ibul = rounded_rect(icx - iw / 2, iy1 - ih,
                                          icx + iw / 2, iy1, ih / 2)
                piezas["island"] = _extrude(
                    created, ipts, ibul, thickness,
                    isl.get("height_above", 0.05), "island", col,
                    capa("island"))

        # 3. Plateau de cámara y lentes, en el dorso (hacia -Z)
        if plateau is not None:
            px0 = ox + plateau["from_left"]
            py1 = oy + height - plateau["from_top"]
            py0 = py1 - plateau["height"]
            ppts, pbul = rounded_rect(px0, py0, px0 + plateau["width"], py1,
                                      plateau.get("corner_radius", 0.0))
            pr = float(plateau["protrusion"])
            piezas["plateau"] = _extrude(created, ppts, pbul, 0.0, -pr,
                                         "plateau", col, capa("plateau"))
            for ln in lenses:
                cx, cy = px0 + ln["dx"], py1 - ln["dy"]
                lp = float(ln["protrusion"])
                rd = ln.get("ring_diameter")
                if rd:
                    rp, rb = circle(cx, cy, rd)
                    piezas["lensRings"].append(_extrude(
                        created, rp, rb, -pr, -lp, "lens_ring", col,
                        capa("lens_ring")))
                gp, gb = circle(cx, cy, ln["diameter"])
                gh = lp + float(ln.get("glass_extra", 0.0)) \
                    - float(ln.get("glass_recess", 0.0))
                piezas["lensGlasses"].append(_extrude(
                    created, gp, gb, -pr, -gh, "lens_glass", col,
                    capa("lens_glass")))

        # 4. Botones: placas que salen del costado y entran un poco al cuerpo
        for b in buttons:
            side, a0 = b["side"], float(b["from_start"])
            ln_, prot = float(b["length"]), float(b["protrusion"])
            bz = float(b.get("height", thickness / 2))
            zc = float(b.get("z_center", thickness / 2))
            if side in ("left", "right"):
                ya1 = oy + height - a0
                y0, y1 = ya1 - ln_, ya1
                x0, x1 = ((ox - prot, ox + EMBED) if side == "left"
                          else (ox + width - EMBED, ox + width + prot))
            else:
                xa0 = ox + a0
                x0, x1 = xa0, xa0 + ln_
                y0, y1 = ((oy - prot, oy + EMBED) if side == "bottom"
                          else (oy + height - EMBED, oy + height + prot))
            r = min(float(b.get("corner_radius", 0.0)),
                    min(x1 - x0, y1 - y0) / 2)
            bpts, bbul = rounded_rect(x0, y0, x1, y1, r)
            piezas["buttons"].append(_extrude(
                created, bpts, bbul, zc - bz / 2, bz, "button", col,
                capa("button")))
    except Exception:
        # Un teléfono a medias es peor que ninguno: se borra lo creado.
        try:
            acad.call("delete_entities",
                      {"handles": created, "ignoreMissing": True})
        except Exception:
            pass
        raise

    return {
        "pieces": piezas,
        "handles": created,
        "size": {"width": width, "height": height, "thickness": thickness},
        "origin": [ox, oy],
        "finish": finish or "grafito",
        "colors": col,
        "warnings": warnings,
    }
