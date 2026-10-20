"""Arcos de mampostería: geometría de trazo y revisión de empuje.

Un arco en un plano no es "un arco de AutoCAD": es una luz, una flecha y un
tipo de trazo (medio punto, rebajado, apuntado, carpanel), con su espesor,
sus dovelas y su clave. Y en el cálculo, lo que importa es el EMPUJE
horizontal que manda a los apoyos y que la línea de presiones quede dentro
del tercio central de la sección.

  arch_geometry       centros, radios y ángulos del trazo elegido, puntos del
                      intradós y extradós con bulges (listos para polilínea),
                      dovelas y clave.
  create_arch         lo dibuja (alzado o corte), con dovelas opcionales.
  check_masonry_arch  arco bajo carga uniforme: funicular parabólica
                      H = w·L²/(8·f), reacciones, excentricidad máxima de la
                      línea de presiones respecto al eje del arco, regla del
                      tercio central (e <= t/6, sin tensión) y esfuerzo de
                      compresión contra f'm. Espesor mínimo requerido.

Unidades: m, kg/m, kg/cm². Sin f'm (resistencia de la mampostería) no se
revisa el esfuerzo: es dato del proyecto, no un supuesto. Referencias:
Heyman, "The Stone Skeleton" (1966; análisis límite, tercio central);
Méry, método gráfico de la línea de presiones (1840). Es una revisión
PRELIMINAR para arcos de vivienda, no un análisis de bóvedas.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad
import prim

TIPOS = ("medio_punto", "rebajado", "apuntado", "carpanel")
LAYER_ARCO = "ARCOS"
LAYER_DOVELA = "ARCOS-DOVELAS"


def _r(v: float, n: int = 3) -> float:
    return round(float(v), n)


def _bulge(theta_rad: float) -> float:
    return math.tan(theta_rad / 4.0)


def arch_geometry(span: float, rise: Optional[float] = None, kind: str = "medio_punto",
                  thickness: float = 0.0, voussoirs: int = 0) -> dict[str, Any]:
    """Trazo de un arco de luz `span` (entre arranques, intradós) y flecha
    `rise` (del arranque a la clave, intradós). (0, 0) es el arranque
    izquierdo; el eje X va hacia el derecho.

    medio_punto: rise = span/2 (si se da otro, se avisa y se usa span/2).
    rebajado (escarzano): un centro bajo la línea de arranques, rise < span/2.
    apuntado (ojival): dos centros sobre la línea de arranques, rise > span/2
    típico; centros a d = (L²/4 − f²)/L... resueltos de rise.
    carpanel: tres centros, rise < span/2.

    Devuelve `intrados` (puntos + bulges, de izq. a der.), `extrados` si hay
    thickness, los `centers` y `radii`, el largo del intradós y, con
    voussoirs, los radios de junta de cada dovela y la clave."""
    L = float(span)
    if L <= 0:
        raise ValueError("span tiene que ser > 0.")
    if kind not in TIPOS:
        raise ValueError(f"kind: {', '.join(TIPOS)}.")
    t = float(thickness or 0.0)
    if t < 0:
        raise ValueError("thickness no puede ser negativo.")
    avisos: list[str] = []
    arcs: list[tuple[tuple[float, float], float, float, float]] = []   # centro, R, a0, a1 (deg, antihorario)

    if kind == "medio_punto":
        f = L / 2
        if rise is not None and abs(rise - f) > 1e-6:
            avisos.append(f"Un medio punto tiene flecha = luz/2 = {f:.3f}; se ignora rise={rise}.")
        arcs = [((L / 2, 0.0), L / 2, 0.0, 180.0)]
    elif kind == "rebajado":
        if rise is None or not 0 < rise < L / 2:
            raise ValueError("rebajado: 0 < rise < span/2 (si rise = span/2 es medio punto).")
        f = float(rise)
        R = (L * L / 4 + f * f) / (2 * f)
        cy = f - R
        a = math.degrees(math.asin((L / 2) / R))
        arcs = [((L / 2, cy), R, 90.0 - a, 90.0 + a)]
    elif kind == "apuntado":
        if rise is None or rise <= 0:
            raise ValueError("apuntado: hace falta rise > 0 (típico rise >= span/2).")
        f = float(rise)
        # Dos arcos de radio R con centros (L/2 ± d, 0) sobre la línea de
        # arranques: cada uno pasa por su arranque y por la clave (L/2, f).
        # R = L/2 + d  y  R² = d² + f²  ->  d = (f² − L²/4)/L
        d = (f * f - L * L / 4) / L
        if d < 0:
            raise ValueError("apuntado: con rise < span/2 los centros caen fuera; usá 'rebajado'.")
        R = L / 2 + d
        a = math.degrees(math.atan2(f, d))         # ángulo de la clave visto desde el centro derecho
        arcs = [((L / 2 + d, 0.0), R, 180.0 - a, 180.0),      # mitad izquierda
                ((L / 2 - d, 0.0), R, 0.0, a)]                # mitad derecha
    else:  # carpanel (3 centros)
        if rise is None or not 0 < rise < L / 2:
            raise ValueError("carpanel: 0 < rise < span/2.")
        f = float(rise)
        # Construcción clásica: radio de los arcos laterales r = (L/2 − f)… se
        # usa la de Huygens/clásica: r = f·L/(L + 2f) ... Aquí la de tres
        # centros con r = L/2 − f? No: tomamos r = L·f/(L + 2·f) (lateral) y el
        # central tangente, resolviendo R y el centro por tangencia.
        r = L * f / (L + 2 * f)
        # Tres centros: laterales (r, 0) y (L − r, 0) de radio r; central (L/2, c)
        # de radio R = f − c, tangente interior a los laterales:
        #   (L/2 − r)² + c² = (R − r)²  ->  c = ((f − r)² − (L/2 − r)²) / (2(f − r))
        c = ((f - r) ** 2 - (L / 2 - r) ** 2) / (2 * (f - r))
        R = f - c
        if R <= r or r <= 0:
            raise ValueError("carpanel: la flecha es demasiado chica para tres centros; usá 'rebajado'.")
        # El punto de tangencia está sobre la recta centro central -> centro lateral,
        # a r del lateral y del lado exterior.
        ux, uy = (r - L / 2), (0.0 - c)
        n = math.hypot(ux, uy)
        ux, uy = ux / n, uy / n
        tx_i, ty_i = r + ux * r, uy * r                        # tangencia izquierda
        tx_d, ty_d = (L - r) - ux * r, uy * r                  # tangencia derecha
        a_i = math.degrees(math.atan2(ty_i, tx_i - r))
        a_d = math.degrees(math.atan2(ty_d, tx_d - (L - r)))
        c_i = math.degrees(math.atan2(ty_i - c, tx_i - L / 2))
        c_d = math.degrees(math.atan2(ty_d - c, tx_d - L / 2))
        arcs = [((r, 0.0), r, a_i, 180.0), ((L / 2, c), R, c_i, c_d), ((L - r, 0.0), r, 0.0, a_d)]

    def puntos(offset: float) -> tuple[list[list[float]], list[float], float]:
        """Polilínea de izquierda a derecha sobre los arcos con radio + offset."""
        pts: list[list[float]] = []
        bul: list[float] = []
        largo = 0.0
        # recorrer de izquierda (ángulo mayor) a derecha (ángulo menor): horario
        for (cx, cy), Rr, a0, a1 in arcs:
            Ro = Rr + offset
            hi, lo = max(a0, a1), min(a0, a1)
            sweep = hi - lo
            p_ini = [cx + Ro * math.cos(math.radians(hi)), cy + Ro * math.sin(math.radians(hi))]
            if not pts or math.dist(pts[-1], p_ini) > 1e-6:
                pts.append(p_ini)
                bul.append(0.0)
            bul[-1] = -_bulge(math.radians(sweep))           # horario
            pts.append([cx + Ro * math.cos(math.radians(lo)), cy + Ro * math.sin(math.radians(lo))])
            bul.append(0.0)
            largo += Ro * math.radians(sweep)
        return pts, bul, largo

    ip, ib, largo_i = puntos(0.0)
    out: dict[str, Any] = {
        "kind": kind, "span": L, "rise": _r(f), "thickness": t,
        "centers": [[_r(c[0]), _r(c[1])] for c, *_ in arcs],
        "radii": [_r(R) for _, R, *_ in arcs],
        "intrados": {"points": [[_r(x), _r(y)] for x, y in ip], "bulges": [_r(b, 6) for b in ib],
                     "length": _r(largo_i)},
        "crown": [_r(L / 2), _r(f)],
        "warnings": avisos,
    }
    if t > 0:
        ep, eb, largo_e = puntos(t)
        out["extrados"] = {"points": [[_r(x), _r(y)] for x, y in ep], "bulges": [_r(b, 6) for b in eb],
                           "length": _r(largo_e)}
    if voussoirs:
        n = int(voussoirs)
        if n < 3 or n % 2 == 0:
            raise ValueError("voussoirs: impar y >= 3, para que haya una clave centrada.")
        juntas = []
        # repartir por longitud de intradós: n dovelas -> n−1 juntas interiores
        for k in range(1, n):
            s = largo_i * k / n
            juntas.append(_punto_y_normal(arcs, s))
        out["voussoirs"] = {"count": n, "joints": [{"intrados": [_r(p[0]), _r(p[1])],
                                                    "normal": [_r(v[0], 4), _r(v[1], 4)]}
                                                   for p, v in juntas],
                            "keystone_index": n // 2}
    return out


def _punto_y_normal(arcs, s: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Punto sobre el intradós a longitud s desde el arranque izquierdo y la
    normal exterior (hacia el extradós)."""
    for (cx, cy), R, a0, a1 in arcs:
        hi, lo = max(a0, a1), min(a0, a1)
        largo = R * math.radians(hi - lo)
        if s <= largo + 1e-9:
            ang = math.radians(hi) - s / R
            return (cx + R * math.cos(ang), cy + R * math.sin(ang)), (math.cos(ang), math.sin(ang))
        s -= largo
    (cx, cy), R, a0, a1 = arcs[-1]
    ang = math.radians(min(a0, a1))
    return (cx + R * math.cos(ang), cy + R * math.sin(ang)), (math.cos(ang), math.sin(ang))


def create_arch(x: float, y: float, span: float, rise: Optional[float] = None,
                kind: str = "medio_punto", thickness: float = 0.0, voussoirs: int = 0,
                closed: bool = True, layer: str = LAYER_ARCO, lineweight: int = 35
                ) -> dict[str, Any]:
    """Dibuja el arco con su arranque izquierdo en (x, y). Con thickness traza
    intradós y extradós (y cierra los arranques si closed); con voussoirs
    dibuja las juntas radiales."""
    g = arch_geometry(span, rise, kind, thickness, voussoirs)
    prim.capa(layer, 7, lineweight)
    hs: list[str] = []

    def mv(pts):
        return [(x + p[0], y + p[1]) for p in pts]
    with acad.lote():
        hs.append(prim.poly(mv(g["intrados"]["points"]), layer, False, lineweight, None,
                            g["intrados"]["bulges"]))
        if thickness > 0:
            hs.append(prim.poly(mv(g["extrados"]["points"]), layer, False, lineweight, None,
                                g["extrados"]["bulges"]))
            if closed:
                ip, ep = g["intrados"]["points"], g["extrados"]["points"]
                hs.append(prim.line((x + ip[0][0], y + ip[0][1]), (x + ep[0][0], y + ep[0][1]), layer, lineweight))
                hs.append(prim.line((x + ip[-1][0], y + ip[-1][1]), (x + ep[-1][0], y + ep[-1][1]), layer, lineweight))
            if voussoirs:
                prim.capa(LAYER_DOVELA, 8, 13)
                for j in g["voussoirs"]["joints"]:
                    px, py = j["intrados"]
                    nx, ny = j["normal"]
                    hs.append(prim.line((x + px, y + py), (x + px + nx * thickness, y + py + ny * thickness),
                                        LAYER_DOVELA, 13))
    g["handles"] = hs
    return g


def check_masonry_arch(span: float, rise: float, thickness: float, width: float,
                       load_kg_m: float, fm_kgcm2: Optional[float] = None,
                       self_weight: bool = True, unit_weight: float = 1800.0,
                       kind: str = "medio_punto", n: int = 60) -> dict[str, Any]:
    """Arco de mampostería de luz `span`, flecha `rise` (al eje del arco), espesor
    radial `thickness` y ancho `width` (profundidad del muro), con carga vertical
    uniforme `load_kg_m` (muro encima, losa, lo que apoye) MÁS su peso propio.

    Modelo: arco biarticulado con funicular parabólica de la carga uniforme:
      H = w·L²/(8·f)   (empuje horizontal, igual en toda la línea)
      V = w·L/2        (reacción vertical en cada arranque)
    Línea de presiones y = 4f·x·(L−x)/L²; se compara con el eje del arco del
    trazo elegido y se toma la excentricidad máxima e_max. Regla del tercio
    central: e_max <= t/6 (sin tensión en la junta); e_max <= t/2 es el
    límite de estabilidad. Esfuerzo máximo de compresión en la junta más
    cargada σ = N/A + 6·N·e/(b·t²), contra f'm si se da.
    Devuelve también el espesor mínimo t_req = 6·e_max para que la línea
    quede en el tercio central. PRELIMINAR (Heyman 1966, Méry 1840)."""
    L, f, t, b = float(span), float(rise), float(thickness), float(width)
    if min(L, f, t, b) <= 0:
        raise ValueError("span, rise, thickness y width tienen que ser > 0.")
    if load_kg_m < 0:
        raise ValueError("load_kg_m no puede ser negativa.")
    w = float(load_kg_m)
    if self_weight:
        w += unit_weight * t * b          # kg/m de desarrollo horizontal (aprox.)
    H = w * L * L / (8 * f)
    V = w * L / 2
    g = arch_geometry(L, None if kind == "medio_punto" else f, kind, 0.0)
    # eje del arco: muestrear por x el punto del trazo (intradós) y subir t/2
    arcs = _arcs_de(g)
    e_max, x_e = 0.0, 0.0
    sigma_max, x_s = 0.0, 0.0
    for k in range(1, n):
        x = L * k / n
        y_par = 4 * f * x * (L - x) / (L * L)
        y_eje = _y_en(arcs, x) + 0.0
        e = abs(y_par - y_eje)
        # fuerza normal en la sección (aprox.: resultante de H y cortante V(x))
        vx = w * (L / 2 - x)
        N = math.hypot(H, vx)
        sig = N / (b * t) + 6 * N * e / (b * t * t)     # kg/m²
        if e > e_max:
            e_max, x_e = e, x
        if sig > sigma_max:
            sigma_max, x_s = sig, x
    sigma_kgcm2 = sigma_max / 1e4
    tercio = e_max <= t / 6 + 1e-9
    estable = e_max <= t / 2 + 1e-9
    out: dict[str, Any] = {
        "kind": kind, "span": L, "rise": f, "thickness": t, "width": b,
        "w_total_kg_m": _r(w, 1), "thrust_H_kg": _r(H, 1), "reaction_V_kg": _r(V, 1),
        "e_max_m": _r(e_max, 4), "e_max_at_x": _r(x_e, 3),
        "middle_third": {"ok": tercio, "limit_m": _r(t / 6, 4),
                         "ref": "Regla del tercio central (Heyman, 1966): sin tensión en la junta"},
        "stability": {"ok": estable, "limit_m": _r(t / 2, 4)},
        "t_required_m": _r(6 * e_max, 3),
        "sigma_max_kgcm2": _r(sigma_kgcm2, 2), "sigma_at_x": _r(x_s, 3),
        "method": "Funicular parabólica de carga uniforme vs eje del arco; Méry/Heyman. PRELIMINAR.",
        "warnings": list(g.get("warnings", [])),
    }
    if fm_kgcm2 is None:
        out["stress"] = {"ok": None, "note": "Sin f'm no se revisa el esfuerzo: pasá fm_kgcm2 (dato del proyecto)."}
    else:
        if fm_kgcm2 <= 0:
            raise ValueError("fm_kgcm2 tiene que ser > 0.")
        # factor de seguridad habitual en mampostería: σ <= f'm/3 (criterio clásico de esfuerzos admisibles)
        adm = fm_kgcm2 / 3.0
        out["stress"] = {"ok": sigma_kgcm2 <= adm + 1e-9, "allowable_kgcm2": _r(adm, 2),
                         "fm_kgcm2": fm_kgcm2,
                         "ref": "Esfuerzo admisible f'm/3 (criterio clásico de mampostería; confirmar con la norma local)"}
    out["ok"] = tercio and estable and (out["stress"]["ok"] is not False)
    if kind != "medio_punto" and kind != "rebajado":
        out["warnings"].append("La comparación con la parábola es aproximada en arcos apuntados y carpaneles.")
    return out


def _arcs_de(g: dict[str, Any]):
    arcs = []
    pts = g["intrados"]["points"]
    for (c, R) in zip(g["centers"], g["radii"]):
        arcs.append((tuple(c), R))
    return arcs, pts


def _y_en(arcs_pts, x: float) -> float:
    """y del intradós en x: el mayor y entre los arcos que lo cubren."""
    arcs, _ = arcs_pts
    mejor = None
    for (cx, cy), R in arcs:
        dx = x - cx
        if abs(dx) <= R + 1e-9:
            y = cy + math.sqrt(max(R * R - dx * dx, 0.0))
            if y >= -1e-9 and (mejor is None or y > mejor):
                mejor = y
    return mejor if mejor is not None else 0.0
