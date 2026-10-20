"""Portico y barda en 3D (solidos reales), calcado de las mismas medidas que el alzado:
pilastras con forro de piedra, molduras y remate de teja; frontón con su cornisa mixtilinea;
aro de acento en relieve; medallon; hojas de herreria con barrotes, rosetas y arco; y los
tramos de barda con muro bajo, cadena, pilastras y reja.

Ejes: X a lo largo del porton, Y hacia fuera del plano (la fachada mira a -Y), Z arriba.
Cada pieza es un solido: extrude_profile (plane='xy' para plantas, 'xz' para alzados).
"""
from __future__ import annotations

import math
from typing import Any

import autocad_client as acad
import layers
import portico_arco as pa
import portico_dibujo as pd

# colores ACI (indices del 10 al 249: se leen igual en pantalla y en papel)
C_REVOQUE = 41      # aplanado crema
C_PIEDRA = 33       # piedra
C_TEJA = 22         # barro cocido
C_BLOCK = 8         # block gris
C_HERRERIA = 250    # negro
C_PISO = 253
C_FAROL = 30


def _caja(x0, x1, y0, y1, z0, z1, layer, color, taper=0.0):
    return acad.call("extrude_profile", {
        "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "bulges": None, "z0": z0, "height": z1 - z0,
        "taper": taper, "layer": layer, "colorIndex": color, "plane": "xy", "y0": 0.0})["handle"]


def _perfil_xz(pts, y0, espesor, layer, color):
    return acad.call("extrude_profile", {
        "points": [[p[0], p[1]] for p in pts], "bulges": None, "z0": 0.0, "height": espesor,
        "taper": 0.0, "layer": layer, "colorIndex": color, "plane": "xz", "y0": y0})["handle"]


def _disco_xz(cx, cz, r, y0, espesor, layer, color):
    return acad.call("extrude_profile", {
        "points": [[cx - r, cz], [cx + r, cz]], "bulges": [1.0, 1.0], "z0": 0.0, "height": espesor,
        "taper": 0.0, "layer": layer, "colorIndex": color, "plane": "xz", "y0": y0})["handle"]


def _lyr(nombre, color):
    layers.ensure(nombre, color, 25)
    return nombre


def modelar(d: dict[str, Any], f: dict[str, Any], x0: float = 0.0, y0: float = 0.0, bays: int = 3) -> dict[str, Any]:
    """Levanta todo el modelo con el eje del porton en (x0, y0) y el piso en z = 0."""
    g = d["geometria"]
    S, P, Pd = g["S"], d["pilastra_terminada"], d["pilastra_prof"]
    Lh, xo = S / 2.0, S / 2.0 + P
    R, yc, aro = g["R"], g["yc"], pd.FOTO["aro"]
    L_rev = _lyr("3D-REVOQUE", C_REVOQUE)
    L_pie = _lyr("3D-PIEDRA", C_PIEDRA)
    L_tej = _lyr("3D-TEJA", C_TEJA)
    L_blk = _lyr("3D-BLOCK", C_BLOCK)
    L_her = _lyr("3D-HERRERIA", C_HERRERIA)
    L_pis = _lyr("3D-PISO", C_PISO)
    L_far = _lyr("3D-FAROL", C_FAROL)
    n = 0
    with acad.lote():
        # ---- piso y banqueta
        _caja(x0 - 14, x0 + 14, y0 - 7, y0 + 7, -0.06, 0.0, L_pis, C_PISO)
        # ---- pilastras P-1
        for lado in (-1, 1):
            xa, xb = sorted((x0 + lado * Lh, x0 + lado * xo))
            ya, yb = y0 - Pd / 2, y0 + Pd / 2
            _caja(xa - 0.03, xb + 0.03, ya - 0.03, yb + 0.03, 0.0, 2.40, L_pie, C_PIEDRA)          # forro de piedra
            _caja(xa - 0.05, xb + 0.05, ya - 0.05, yb + 0.05, 2.40, 2.54, L_rev, C_REVOQUE)       # repisa
            _caja(xa, xb, ya, yb, 2.54, 4.39, L_rev, C_REVOQUE)                                  # fuste
            _caja(xa + 0.03, xb - 0.03, ya - 0.015, ya, 2.70, 4.20, L_rev, C_REVOQUE)            # tablero en relieve
            _caja(xa - 0.05, xb + 0.05, ya - 0.05, yb + 0.05, 4.39, 4.56, L_rev, C_REVOQUE)      # moldura
            _caja(xa, xb, ya, yb, 4.56, 4.80, L_rev, C_REVOQUE)                                  # bloque del capitel
            ex = (pd.FOTO["teja_ancho"] - P) / 2.0
            _caja(xa - ex, xb + ex, ya - 0.20, yb + 0.20, 4.80, 5.07, L_tej, C_TEJA, taper=8.0)  # remate de teja
            xm = (xa + xb) / 2.0
            _caja(xm - 0.12, xm + 0.12, ya - 0.20, ya - 0.04, 3.05, 3.60, L_far, C_FAROL)         # farol
            n += 9
        # ---- fronton (muro de 20 cm): de la linea del arco a la cornisa
        pts = []
        npt = 70
        for k in range(npt + 1):                                      # cornisa, de izquierda a derecha
            xx = -xo + 2 * xo * k / npt
            pts.append((x0 + xx, pa.y_top(g, xx)))
        for k in range(npt + 1):                                      # intrados, de derecha a izquierda
            xx = Lh - 2 * Lh * k / npt
            pts.append((x0 + xx, yc + math.sqrt(R * R - xx * xx)))
        # cierre por dentro de las pilastras (a 4.60 m, dentro del bloque del capitel)
        pts.insert(npt + 1, (x0 + xo, 4.60))
        pts.insert(npt + 2, (x0 + Lh, 4.60))
        pts.append((x0 - Lh, 4.60))
        pts.append((x0 - xo, 4.60))
        _perfil_xz(pts, y0 - 0.10, 0.20, L_rev, C_REVOQUE)
        # ---- aro de acento: relieve de 5 cm a cada cara (0.30 de espesor)
        aro_pts = []
        for k in range(61):
            xx = -Lh + 2 * Lh * k / 60
            aro_pts.append((x0 + xx, yc + math.sqrt((R + aro) ** 2 - xx * xx)))
        for k in range(61):
            xx = Lh - 2 * Lh * k / 60
            aro_pts.append((x0 + xx, yc + math.sqrt(R * R - xx * xx)))
        _perfil_xz(aro_pts, y0 - 0.15, 0.30, L_tej, C_TEJA)
        # ---- borde de teja de la cornisa (franja de 7 cm sobre el perfil)
        borde = [(x0 + (-xo + 2 * xo * k / npt), pa.y_top(g, -xo + 2 * xo * k / npt) + 0.07) for k in range(npt + 1)]
        borde += [(x0 + (xo - 2 * xo * k / npt), pa.y_top(g, xo - 2 * xo * k / npt)) for k in range(npt + 1)]
        _perfil_xz(borde, y0 - 0.14, 0.28, L_tej, C_TEJA)
        # ---- medallon
        ym = pd.FOTO["medallon"][0]
        rm = pd.FOTO["medallon"][1]
        _disco_xz(x0, ym, rm, y0 - 0.16, 0.06, L_tej, C_TEJA)
        _disco_xz(x0, ym, rm * 0.72, y0 - 0.20, 0.04, L_rev, C_REVOQUE)
        n += 6
        # ---- herreria: dos hojas
        gh = g["spring_h"] - 0.45
        gc = pd.FOTO["hoja_clave"]
        Lg = S / 2.0 - 0.05
        fl = gc - gh
        Rg = (Lg ** 2 + fl ** 2) / (2 * fl)
        ycg = gc - Rg
        top = lambda xx: ycg + math.sqrt(max(Rg * Rg - xx * xx, 0.0))
        t = 0.04                                                    # grueso de la herreria
        yh = y0 - 0.02
        for lado in (-1, 1):
            xa, xb = (0.012, Lg) if lado > 0 else (-Lg, -0.012)
            xa, xb = min(xa, xb), max(xa, xb)
            # poste de 15 cm en el extremo y chapa lisa abajo
            xp = xb if lado > 0 else xa
            _caja(x0 + min(xp, xp - lado * 0.15), x0 + max(xp, xp - lado * 0.15), yh - 0.05, yh + 0.05, 0.03, top(xp), L_her, C_HERRERIA)
            _caja(x0 + xa, x0 + xb, yh - 0.015, yh + 0.015, 0.03, 0.66, L_her, C_HERRERIA)
            for zz in (0.66, 0.80, 1.07):
                _caja(x0 + xa, x0 + xb, yh - 0.02, yh + 0.02, zz - 0.02, zz + 0.02, L_her, C_HERRERIA)
            nb = int((xb - xa) / 0.18)
            for k in range(1, nb):
                xx = xa + (xb - xa) * k / nb
                _caja(x0 + xx - 0.012, x0 + xx + 0.012, yh - 0.012, yh + 0.012, 1.07, top(xx) - 0.02, L_her, C_HERRERIA)
                if k % 2 == 0:
                    _caja(x0 + xx - 0.02, x0 + xx + 0.02, yh - 0.012, yh + 0.012, top(xx) - 0.03, top(xx) + 0.20, L_her, C_HERRERIA, taper=3.0)
            nr = int((xb - xa) / 0.19)
            for k in range(nr):
                xx = xa + (xb - xa) * (k + 0.5) / nr
                _disco_xz(x0 + xx, 0.935, 0.085, yh - 0.015, 0.03, L_her, C_HERRERIA)
            # aro superior de la hoja (franja de 4 cm sobre la curva)
            band = [(x0 + xa + (xb - xa) * k / 30, top(xa + (xb - xa) * k / 30)) for k in range(31)]
            band += [(x0 + xb - (xb - xa) * k / 30, top(xb - (xb - xa) * k / 30) + 0.04) for k in range(31)]
            _perfil_xz(band, yh - 0.02, 0.04, L_her, C_HERRERIA)
            n += nb * 2 + nr + 6
        # remate central
        yt = top(0.0)
        _caja(x0 - 0.012, x0 + 0.012, yh - 0.012, yh + 0.012, yt, yt + 0.40, L_her, C_HERRERIA)
        _disco_xz(x0, yt + 0.40, 0.06, yh - 0.02, 0.04, L_her, C_HERRERIA)
        # ---- barda
        sp, P2, c2 = f["spacing"], f["pilastra_terminada"], f["nucleo"]
        hw, ht, hp = f["wall_h"], f["total_h"], f["pilaster_h"]
        ejes_der = [xo + P2 / 2 + sp * k for k in range(bays)]
        for lado in (-1, 1):
            ejes = [lado * e for e in ejes_der]
            for e in ejes:
                _caja(x0 + e - P2 / 2, x0 + e + P2 / 2, y0 - P2 / 2, y0 + P2 / 2, 0.0, hp - 0.10, L_rev, C_REVOQUE)
                _caja(x0 + e - P2 / 2 - 0.08, x0 + e + P2 / 2 + 0.08, y0 - P2 / 2 - 0.08, y0 + P2 / 2 + 0.08,
                      hp - 0.10, hp + 0.0, L_tej, C_TEJA, taper=10.0)
            for e1, e2 in zip(ejes[:-1], ejes[1:]):
                ia, ib = sorted((e1, e2))
                ia, ib = ia + P2 / 2, ib - P2 / 2
                _caja(x0 + ia, x0 + ib, y0 - 0.06, y0 + 0.06, 0.0, hw, L_blk, C_REVOQUE)          # muro bajo
                _caja(x0 + ia, x0 + ib, y0 - 0.09, y0 + 0.09, hw - 0.05, hw + 0.03, L_tej, C_TEJA)  # remate de barro
                _caja(x0 + ia, x0 + ib, y0 - 0.015, y0 + 0.015, hw + 0.08, hw + 0.11, L_her, C_HERRERIA)
                _caja(x0 + ia, x0 + ib, y0 - 0.015, y0 + 0.015, ht - 0.11, ht - 0.08, L_her, C_HERRERIA)
                nbar = int((ib - ia) / 0.12)
                for k in range(1, nbar):
                    xx = ia + (ib - ia) * k / nbar
                    _caja(x0 + xx - 0.01, x0 + xx + 0.01, y0 - 0.01, y0 + 0.01, hw + 0.11, ht - 0.11, L_her, C_HERRERIA)
                n += nbar + 4
    return {"entidades": n}
