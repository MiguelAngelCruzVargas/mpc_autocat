"""Portico de acceso con arco y barda: DIBUJO de oficio.

Todo sale del dict de portico_arco.design_gate_portal / design_fence: ningun
numero se escribe a mano. Cada funcion dibuja UNA vista, a partir de un punto
(x, y) en el modelo (metros), y devuelve su 'box' para compose_layout.

  alzado_portico     el porton: pilastras, arco, remate, hojas y cotas
  tramo_barda        un tramo de barda (muro bajo de block + reja + pilastras)
  alzado_general     porton + barda a ambos lados, con lineas de corte
  planta_general     la planta: hojas y su giro, pilastras, muros
  corte_trabe        seccion de la trabe curva con su forro y su armado
  armado_trabe       la trabe curva DESARROLLADA: lechos, estribos y anclajes
  armado_pilastra    la pilastra (elevacion con arranques + seccion)
  detalle_barda      pilastra de barda + corte de la barda con su cimentacion
  planta_cimentacion zapatas, cimiento corrido y ejes

upm = unidades por mm de papel de la vista (0.025 = 1:25).
"""
from __future__ import annotations

import math
from typing import Any, Optional

import annotation as ann
import autocad_client as acad
import detalle as dt
import layers
import materials
import prim
import rebar
import zapatas as zap

L_CON = "PORT-CONCRETO"
L_BLK = "PORT-BLOCK"
L_REJA = "PORT-REJA"
L_OCU = "PORT-OCULTO"
L_TXT = "PORT-TEXTOS"
L_EJE = "EJES"
L_HOJA = "PORT-HOJA"


def _capas() -> None:
    prim.capa(L_CON, 7, 50)
    prim.capa(L_BLK, 8, 13)
    prim.capa(L_REJA, 8, 18)
    prim.capa(L_OCU, 8, 13, layers.LT_OCULTO)
    prim.capa(L_TXT, 7, 0)
    prim.capa(L_HOJA, 8, 25)
    prim.capa(L_EJE, 32, 13, layers.LT_EJE)


def _db(nombre: str) -> float:
    return zap.VARILLAS[nombre][0]


def _caja(pts) -> list[float]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def _rect(x0, y0, x1, y1, layer=L_CON, lw=35):
    return prim.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer, True, lw)


def _arco_puntos(cx, cy, r, x0, x1, n=48):
    """Puntos del arco de circulo (cx, cy, r) entre las abscisas x0 y x1 (arco superior)."""
    pts = []
    for k in range(n + 1):
        x = x0 + (x1 - x0) * k / n
        pts.append((x, cy + math.sqrt(max(r * r - (x - cx) ** 2, 0.0))))
    return pts


def _arco_cad(cx, cy, r, x_der, x_izq, layer, lw=35):
    """Arco superior de AutoCAD entre dos abscisas (derecha -> izquierda, antihorario)."""
    a0 = math.degrees(math.acos(max(-1.0, min(1.0, (x_der - cx) / r))))
    a1 = math.degrees(math.acos(max(-1.0, min(1.0, (x_izq - cx) / r))))
    return prim.arc((cx, cy), r, a0, a1, layer, lw)


# ----------------------------------------------------------- tramos de barda

def tramo_barda(f: dict[str, Any], x_axes: list[float], y: float, upm: float,
                draw_first: bool = True, p_first: float = 0.0) -> list[float]:
    """Pilastras P-2 en los ejes x_axes (ya con la separacion), muro bajo de block
    (hiladas de 20 cm, juntas cada 40 a trasbapar), cadena de desplante, dala de
    cerramiento y reja. Devuelve la caja."""
    _capas()
    P = f["pilastra_terminada"]
    hp, hw, ht = f["pilaster_h"], f["wall_h"], f["total_h"]
    with acad.lote():
        for i, xc in enumerate(x_axes):
            if i == 0 and not draw_first:
                continue
            _rect(xc - P / 2, y, xc + P / 2, y + hp, L_CON, 35)
            prim.poly([(xc - P / 2 - 0.03, y + hp - 0.10), (xc + P / 2 + 0.03, y + hp - 0.10),
                       (xc + P / 2 + 0.03, y + hp), (xc - P / 2 - 0.03, y + hp)], L_CON, True, 25)
        for i_, (xa, xb) in enumerate(zip(x_axes[:-1], x_axes[1:])):
            a, b = xa + (p_first if (i_ == 0 and p_first) else P) / 2, xb - P / 2
            if b - a < 0.05:
                continue
            # muro bajo: hiladas de 20 cm, juntas verticales a 40 trabadas
            n_h = int(round(hw / 0.20))
            for k in range(1, n_h):
                prim.line((a, y + 0.20 * k), (b, y + 0.20 * k), L_BLK, 13)
            for k in range(n_h):
                off = 0.0 if k % 2 == 0 else 0.20
                x = a + off + 0.40
                while x < b - 1e-6:
                    prim.line((x, y + 0.20 * k), (x, y + 0.20 * (k + 1)), L_BLK, 13)
                    x += 0.40
            # cadena de desplante y dala de cerramiento (10 x 20)
            prim.poly([(a, y), (b, y), (b, y + hw), (a, y + hw)], L_CON, True, 35)
            prim.line((a, y + 0.20), (b, y + 0.20), L_CON, 25)
            prim.line((a, y + hw - 0.20), (b, y + hw - 0.20), L_CON, 25)
            # reja: dos largueros y barrotes cada 12 cm
            r0, r1 = y + hw + 0.05, y + ht - 0.05
            prim.line((a, r0), (b, r0), L_REJA, 35)
            prim.line((a, r1), (b, r1), L_REJA, 35)
            prim.line((a, (r0 + r1) / 2), (b, (r0 + r1) / 2), L_REJA, 25)
            n = int((b - a) / 0.12)
            for k in range(1, n):
                x = a + (b - a) * k / n
                prim.line((x, r0), (x, r1), L_REJA, 18)
    return [x_axes[0] - P / 2, y, x_axes[-1] + P / 2, y + hp]


def _arco_sobre(cx, cy, r, x0, x1, n=80):
    return [(x0 + (x1 - x0) * k / n, cy + math.sqrt(max(r * r - (x0 + (x1 - x0) * k / n - cx) ** 2, 0.0)))
            for k in range(n + 1)]


# ----------------------------------------------------------- alzado del porton (calcado de la foto)

# MEDIDAS CONGELADAS, tomadas de arco_referencia.png (61 px/m, piso en y = 405 px, eje en x = 262 px).
# Todas en metros sobre el piso; ancho = a lo largo del porton.
FOTO = {
    "pil_ancho": 0.95,            # cuerpo de la pilastra
    "piedra_h": 2.40,             # forro de piedra (hasta la repisa)
    "repisa": (2.41, 2.54),       # repisa/moldura sobre la piedra (sobresale 0.05)
    "moldura_sup": (4.39, 4.56),  # moldura bajo el capitel (sobresale 0.05)
    "bloque_cap": (4.56, 4.80),   # bloque del capitel
    "teja": (4.80, 5.07),         # remate de teja (ancho 1.45)
    "teja_ancho": 1.60,
    "farol": (3.00, 3.93),        # farol de muro
    "hoja_lado": None,            # se calcula: arranque - 0.45
    "hoja_clave": 3.40,
    "hoja_panel": 0.66,           # chapa lisa abajo
    "rosetas": (0.80, 1.07),      # faja de rosetas
    "aro": 0.36,                  # espesor radial del aro de acento
    "medallon": (5.25, 0.30),     # centro y radio
    "remate_h": 0.0,
}


def _poly_perfil(g, x, y, dy=0.0, desde=-2.5, hasta=2.5, paso=0.1):
    pts = []
    n = int(round((hasta - desde) / paso))
    import portico_arco as pa
    for k in range(n + 1):
        xx = desde + (hasta - desde) * k / n
        pts.append((x + xx, y + pa.y_top(g, xx) + dy))
    return pts


def _farol(x, y, escala=1.0):
    """Farol de muro con brazo: cuerpo con cristal, tapa, gancho."""
    w, h = 0.30 * escala, 0.55 * escala
    prim.poly([(x - w / 2, y), (x + w / 2, y), (x + w / 2 - 0.03, y + h), (x - w / 2 + 0.03, y + h)], L_HOJA, True, 25)
    prim.poly([(x - w / 2 + 0.05, y + 0.07), (x + w / 2 - 0.05, y + 0.07), (x + w / 2 - 0.07, y + h - 0.06),
               (x - w / 2 + 0.07, y + h - 0.06)], L_HOJA, True, 13)
    prim.poly([(x - w / 2 - 0.02, y + h), (x + w / 2 + 0.02, y + h), (x, y + h + 0.13 * escala)], L_HOJA, True, 25)
    prim.arc((x, y + h + 0.13 * escala + 0.07), 0.07, 0, 180, L_HOJA, 25)
    prim.line((x, y - 0.10 * escala), (x, y), L_HOJA, 25)


def _piedra(xa, xb, y0, y1):
    """Forro de piedra: bandas de piedra irregular en los dos bordes (0.13 m) y aplanado al centro."""
    import random
    rnd = random.Random(7)
    ancho = 0.13
    for x0_, x1_ in ((xa + 0.03, xa + 0.03 + ancho), (xb - 0.03 - ancho, xb - 0.03)):
        y = y0
        prim.line((x0_, y0), (x0_, y1), L_BLK, 13)
        prim.line((x1_, y0), (x1_, y1), L_BLK, 13)
        while y < y1 - 0.05:
            hh = min(rnd.choice((0.10, 0.13, 0.16, 0.12, 0.18)), y1 - y)
            y += hh
            if y < y1 - 0.02:
                prim.line((x0_, y), (x1_, y), L_BLK, 13)


def _teja(xa, xb, ya, yb, ancho_extra):
    """Remate de teja de barro: trapecio, cumbrera y tejas (arcos) en dos hiladas."""
    prim.poly([(xa - ancho_extra, ya), (xb + ancho_extra, ya), (xb + ancho_extra - 0.06, yb - 0.04),
               (xa - ancho_extra + 0.06, yb - 0.04)], L_CON, True, 35)
    prim.line((xa - ancho_extra + 0.06, yb - 0.04), (xb + ancho_extra - 0.06, yb - 0.04), L_CON, 25)
    n = int((xb - xa + 2 * ancho_extra) / 0.13)
    for hil, (y0_, y1_) in enumerate(((ya, ya + (yb - ya) * 0.5), (ya + (yb - ya) * 0.5, yb - 0.04))):
        for k in range(n):
            x0_ = xa - ancho_extra + (xb - xa + 2 * ancho_extra) * k / n
            x1_ = xa - ancho_extra + (xb - xa + 2 * ancho_extra) * (k + 1) / n
            prim.arc(((x0_ + x1_) / 2, y1_), (x1_ - x0_) / 2, 180, 360, L_CON, 13)


def alzado_portico(d: dict[str, Any], x: float, y: float, upm: float,
                   con_hojas: bool = True, cotas: bool = True, ornamentos: bool = True) -> dict[str, Any]:
    """Alzado del porton calcado de la foto de referencia: pilastras con forro de piedra,
    repisa, farol, molduras y remate de teja; aro de acento; frontón con cornisa mixtilinea y
    medallon; hoja de herreria 45 cm abajo del arranque con rosetas y remates. (x, y) = centro
    del claro a nivel de piso terminado."""
    import portico_arco as pa
    _capas()
    prim.capa("PORT-PROYECCION", 8, 13, layers.LT_PROYECCION)
    g = d["geometria"]
    S, P = g["S"], d["pilastra_terminada"]
    Lh, xo = S / 2.0, S / 2.0 + P
    R, yc = g["R"], y + g["yc"]
    aro = FOTO["aro"]
    th = 2.0 * upm
    with acad.lote():
        # ---- pilastras
        for lado in (-1, 1):
            xi, xe = x + lado * Lh, x + lado * xo
            xa, xb = sorted((xi, xe))
            y_cap0, y_cap1 = y + FOTO["bloque_cap"][0], y + FOTO["bloque_cap"][1]
            _rect(xa, y, xb, y_cap1, L_CON, 35)                              # fuste
            _piedra(xa, xb, y + 0.05, y + FOTO["piedra_h"])
            for (ya, yb_) in (FOTO["repisa"], FOTO["moldura_sup"]):
                prim.poly([(xa - 0.05, y + ya), (xb + 0.05, y + ya), (xb + 0.05, y + yb_), (xa - 0.05, y + yb_)],
                          L_CON, True, 25)
                prim.line((xa - 0.05, y + (ya + yb_) / 2), (xb + 0.05, y + (ya + yb_) / 2), L_CON, 13)
            # tablero rehundido del fuste alto
            _rect(xa + 0.08, y + FOTO["repisa"][1] + 0.12, xb - 0.08, y + FOTO["moldura_sup"][0] - 0.10, L_CON, 13)
            # remate de teja (1.45 de ancho)
            ex = (FOTO["teja_ancho"] - P) / 2.0
            _teja(xa, xb, y + FOTO["teja"][0], y + FOTO["teja"][1], ex)
            # nucleo de concreto (oculto)
            c = d["nucleo"]
            xm = x + lado * (Lh + P / 2)
            _rect(xm - c / 2, y - 0.05, xm + c / 2, y + g["top_ends_h"], L_OCU, 13)
            # farol
            _farol(xm, y + FOTO["farol"][0])
        # ---- frontón: perfil de la cornisa (medido), con su borde de teja
        top = _poly_perfil(g, x, y, 0.0, -(xo - 0.05), (xo - 0.05), 0.08)
        prim.poly(top, L_CON, False, 50)
        prim.poly([(px, py + 0.07) for px, py in top], L_CON, False, 25)
        # ---- aro de acento (intrados, banda clara, extrados)
        _arco_cad(x, yc, R, x + Lh, x - Lh, L_CON, 50)
        _arco_cad(x, yc, R + 0.14, x + Lh, x - Lh, L_CON, 18)
        _arco_cad(x, yc, R + aro, x + Lh, x - Lh, L_CON, 50)
        for lado in (-1, 1):
            xx = x + lado * Lh
            prim.line((xx, y + pa.y_intrados(g, Lh)), (xx, y + pa.y_intrados(g, Lh) + aro * 1.05), L_CON, 25)
        # ---- medallon
        ym = y + FOTO["medallon"][0]
        rm = FOTO["medallon"][1]
        if ornamentos:
            for k in range(14):
                a = math.radians(360 / 14 * k)
                prim.circle((x + rm * 0.88 * math.cos(a), ym + rm * 0.88 * math.sin(a)), rm * 0.17, L_CON, 13)
            prim.circle((x, ym), rm * 0.72, L_CON, 25)
            prim.poly([(x - 0.13, ym + 0.17), (x + 0.13, ym + 0.17), (x + 0.13, ym - 0.05), (x, ym - 0.19),
                       (x - 0.13, ym - 0.05)], L_CON, True, 25)
        # ---- estructura oculta: trabe curva, castillos K-1, dala DR-1
        _arco_cad(x, yc, R + 0.02, x + Lh, x - Lh, L_OCU, 13)
        _arco_cad(x, yc, R + g["beam_h"] + 0.02, x + Lh, x - Lh, L_OCU, 13)
        for xx in d["fronton"]["castillos_x"]:
            y0_ = yc + math.sqrt((R + g["beam_h"]) ** 2 - xx ** 2)
            y1_ = y + pa.y_top(g, xx) - d["fronton"]["espesor"]
            _rect(x + xx - 0.10, y0_, x + xx + 0.10, y1_, L_OCU, 13)
        dala_h = _poly_perfil(g, x, y, -d["fronton"]["espesor"], -(Lh + P / 2), Lh + P / 2, 0.1)
        prim.poly(dala_h, L_OCU, False, 13)
        # ---- ejes
        for lado in (-1, 1):
            xe = x + lado * (Lh + P / 2)
            prim.line((xe, y - 0.4), (xe, y + FOTO["teja"][1] + 0.5), L_EJE, 13)
        prim.line((x, y - 0.4), (x, y + g["top_crown_h"] + 0.5), L_EJE, 13)
        if con_hojas:
            _hojas(x, y, g, S, upm, [])
        prim.line((x - xo - 1.2, y), (x + xo + 1.2, y), L_CON, 50)
    ex = xo + 1.2
    box = [x - ex, y - 0.4, x + ex, y + g["top_crown_h"] + 0.4]
    if cotas:
        ann.create_dimension_chain(positions=[x - xo, x - Lh, x + Lh, x + xo], side="bottom",
                                   reference=y, total=True, scale=upm)
        ann.create_dimension_chain(positions=[y, y + g["spring_h"], y + g["crown_h"], y + FOTO["teja"][1],
                                              y + g["top_crown_h"]], side="right", reference=x + xo + 0.35, scale=upm)
        box[1] -= 12 * upm * 3
        box[2] += 22 * upm
    return {"box": box, "yc": yc, "R": R}


def _hojas(x, y, g, S, upm, hs):
    """Dos hojas de herreria como en la foto: 3.00 m al costado y 3.40 en la clave (arco
    muy tendido), poste de 15 cm, chapa lisa abajo, faja de rosetas, barrotes con punta de
    lanza y volutas en el centro con el remate."""
    Lh = S / 2.0 - 0.05
    gh = g["spring_h"] - 0.45
    gc = FOTO["hoja_clave"]
    f = gc - gh
    Rg = (Lh ** 2 + f ** 2) / (2 * f)
    ycg = y + gc - Rg
    top = lambda xx: ycg + math.sqrt(max(Rg * Rg - (xx - x) ** 2, 0.0))
    y0 = y + 0.03
    for lado in (-1, 1):
        xa, xb = (x + 0.012, x + Lh) if lado > 0 else (x - Lh, x - 0.012)
        pts = [(xa, y0), (xb, y0)] + [(xb - (xb - xa) * k / 30.0, top(xb - (xb - xa) * k / 30.0))
                                       for k in range(31)]
        prim.poly(pts, L_HOJA, True, 35)
        xp = xb if lado > 0 else xa
        _rect(min(xp, xp - lado * 0.15), y0, max(xp, xp - lado * 0.15), top(xp) + 0.0, L_HOJA, 35)
        panel, (r0, r1) = FOTO["hoja_panel"], FOTO["rosetas"]
        prim.line((xa, y + panel), (xb, y + panel), L_HOJA, 35)
        prim.line((xa, y + r0), (xb, y + r0), L_HOJA, 25)
        prim.line((xa, y + r1), (xb, y + r1), L_HOJA, 25)
        n = int((xb - xa) / 0.18)
        for k in range(1, n):
            xx = xa + (xb - xa) * k / n
            prim.line((xx, y + r1), (xx, top(xx) - 0.03), L_REJA, 13)
            if k % 2 == 0:
                prim.poly([(xx - 0.02, top(xx) - 0.03), (xx + 0.02, top(xx) - 0.03), (xx, top(xx) + 0.20)],
                          L_REJA, True, 13)
        nr = int((xb - xa) / 0.19)
        for k in range(nr):
            xx = xa + (xb - xa) * (k + 0.5) / nr
            prim.circle((xx, y + (r0 + r1) / 2), 0.085, L_HOJA, 18)
            prim.circle((xx, y + (r0 + r1) / 2), 0.04, L_HOJA, 13)
        # rail superior doble con volutas
        nv = int((xb - xa) / 0.30)
        for k in range(nv):
            xx = xa + (xb - xa) * (k + 0.5) / nv
            prim.circle((xx, top(xx) - 0.20), 0.07, L_HOJA, 13)
    # remate central: volutas y lanza alta
    yt = top(x)
    prim.line((x, yt), (x, yt + 0.35), L_HOJA, 25)
    prim.circle((x - 0.10, yt + 0.28), 0.08, L_HOJA, 18)
    prim.circle((x + 0.10, yt + 0.28), 0.08, L_HOJA, 18)
    prim.poly([(x - 0.04, yt + 0.35), (x + 0.04, yt + 0.35), (x, yt + 0.55)], L_HOJA, True, 25)


# ----------------------------------------------------------- alzado general

def alzado_general(d: dict[str, Any], f: dict[str, Any], x: float, y: float, upm: float,
                   bays: int = 2) -> dict[str, Any]:
    """Porton al centro y `bays` tramos de barda a cada lado (separacion f['spacing'])."""
    _capas()
    g = d["geometria"]
    Lax = g["L_ejes"] / 2.0
    sp = f["spacing"]
    P1 = d["pilastra_terminada"]
    P2 = f["pilastra_terminada"]
    r = alzado_portico(d, x, y, upm, con_hojas=True, cotas=False)
    xo_ = g["S"] / 2.0 + P1
    der = [x + Lax] + [x + xo_ + P2 / 2 + sp * (k - 1) for k in range(1, bays + 1)]
    izq = [x - Lax] + [x - xo_ - P2 / 2 - sp * (k - 1) for k in range(1, bays + 1)]
    bx = tramo_barda(f, der, y, upm, draw_first=False, p_first=P1)
    bi = tramo_barda(f, list(reversed(izq)), y, upm, draw_first=False, p_first=P1)
    # quiebres al final de la barda
    xr_end = der[-1] + P2 / 2 + 0.40
    xl_end = izq[-1] - P2 / 2 - 0.40
    with acad.lote():
        for xe, lado in ((xr_end, 1), (xl_end, -1)):
            prim.line((xe - 0.10 * lado, y - 0.2), (xe + 0.10 * lado, y + f["total_h"] + 0.2), L_TXT, 25)
        prim.line((xl_end, y), (xr_end, y), L_CON, 50)
    top = y + g["top_crown_h"] + 0.5
    # cotas: ejes
    pos = sorted(set(izq[1:] + der[1:] + [x - xo_, x - g["S"] / 2.0, x + g["S"] / 2.0, x + xo_]))
    ann.create_dimension_chain(positions=pos, side="bottom", reference=y, total=True, scale=upm)
    ann.create_dimension_chain(positions=[y, y + f["wall_h"], y + f["total_h"]],
                               side="left", reference=xl_end - 0.2, scale=upm)
    ann.create_dimension_chain(positions=[y, y + g["spring_h"], y + g["crown_h"], y + g["top_ends_h"],
                                          y + g["top_crown_h"]], side="right", reference=xr_end + 0.2, scale=upm)
    box = [xl_end - 1.6, y - 1.6, xr_end + 1.9, top]
    return {"box": box, "ejes_barda": der + izq}


# ----------------------------------------------------------- planta general

def planta_general(d: dict[str, Any], f: dict[str, Any], x: float, y: float, upm: float,
                   bays: int = 2) -> dict[str, Any]:
    """Planta: pilastras del porton (60x60), hojas con su giro a 90 grados, pilastras
    de barda (40x40) y muros de 10 cm. (x, y) = centro del claro sobre el eje de la
    barda."""
    _capas()
    g = d["geometria"]
    S = g["S"]
    P1, P2 = d["pilastra_terminada"], f["pilastra_terminada"]
    c1, c2 = d["nucleo"], f["nucleo"]
    Lax = g["L_ejes"] / 2.0
    sp = f["spacing"]
    th = 2.0 * upm
    xo_ = S / 2.0 + P1
    der = [x + Lax] + [x + xo_ + P2 / 2 + sp * (k - 1) for k in range(1, bays + 1)]
    izq = [x - Lax] + [x - xo_ - P2 / 2 - sp * (k - 1) for k in range(1, bays + 1)]
    with acad.lote():
        Pd = d["pilastra_prof"]
        for xc in (x - Lax, x + Lax):
            _rect(xc - P1 / 2, y - Pd / 2, xc + P1 / 2, y + Pd / 2, L_CON, 50)
            _rect(xc - 0.10 - c1 / 2 + 0.10, y - c1 / 2, xc + c1 / 2, y + c1 / 2, L_OCU, 13)
            _rect(xc - P1 / 2 + 0.10, y - Pd / 2 + 0.10, xc + P1 / 2 - 0.10, y + Pd / 2 - 0.10, L_OCU, 13)
        for xs in (der[1:], izq[1:]):
            for xc in xs:
                _rect(xc - P2 / 2, y - P2 / 2, xc + P2 / 2, y + P2 / 2, L_CON, 50)
                _rect(xc - c2 / 2, y - c2 / 2, xc + c2 / 2, y + c2 / 2, L_OCU, 13)
        for xa, xb in zip(der[:-1], der[1:]):
            a = xa + (P1 if xa == der[0] else P2) / 2
            b = xb - P2 / 2
            _rect(a, y - 0.05, b, y + 0.05, L_CON, 35)
        for xa, xb in zip(izq[:-1], izq[1:]):
            a = xb + P2 / 2
            b = xa - (P1 if xa == izq[0] else P2) / 2
            _rect(a, y - 0.05, b, y + 0.05, L_CON, 35)
        # hojas abiertas 90 grados hacia adentro (+y) en linea fina y cerradas gruesas
        for lado in (-1, 1):
            xh = x + lado * S / 2.0
            xe = x + lado * 0.01
            prim.poly([(xh, y - 0.025), (xe, y - 0.025), (xe, y + 0.025), (xh, y + 0.025)], L_HOJA, True, 35)
            a0, a1 = (0, 90) if lado < 0 else (90, 180)
            prim.arc((xh, y), S / 2.0 - 0.01, a0, a1, L_OCU, 13)
            prim.line((xh, y), (xh, y + S / 2.0 - 0.01), L_HOJA, 25)
        prim.line((x, y - 1.0), (x, y + S / 2.0 + 0.4), L_EJE, 13)
        # fronton (20 cm) y aro de la trabe (40 cm) arriba, en proyeccion
        for ancho in (d["fronton"]["espesor"], 0.40):
            _rect(x - S / 2.0, y - ancho / 2, x + S / 2.0, y + ancho / 2, "PORT-PROYECCION", 13)
    dt.text("HOJA ABATIDA 90°", x - S / 4, y + S / 2.0 - 0.45, th, L_TXT, justify="center")
    box = [izq[-1] - P2 / 2 - 0.6, y - 1.3, der[-1] + P2 / 2 + 0.6, y + S / 2.0 + 0.6]
    pos = sorted(set(izq + der))
    ann.create_dimension_chain(positions=pos, side="bottom", reference=y - d["pilastra_prof"] / 2 - 0.05,
                               total=True, scale=upm)
    box[1] -= 8 * upm * 3
    return {"box": box, "ejes": izq + der}
