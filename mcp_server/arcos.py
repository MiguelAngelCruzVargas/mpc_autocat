"""Arcos de mampostería: geometría de trazo y revisión de la línea de presiones.

Un arco en un plano no es "un arco de AutoCAD": es una luz, una flecha y un
tipo de trazo (medio punto, rebajado, apuntado, carpanel), con su espesor,
sus dovelas y su clave. Y en el cálculo lo que importa es el EMPUJE
horizontal que manda a los apoyos y que exista una línea de presiones que
quepa dentro de la sección (análisis límite de Heyman).

  arch_geometry       centros, radios y ángulos del trazo elegido, puntos del
                      intradós y extradós con bulges (listos para polilínea),
                      dovelas y clave.
  create_arch         lo dibuja (alzado o corte), con dovelas, cotas de luz y
                      flecha, y —si se le da la carga— el empuje y el veredicto.
  check_masonry_arch  funicular NUMÉRICA del peso propio (que sigue el arco) más
                      la sobrecarga uniforme: para cada empuje H se traza la
                      línea de presiones M(x)/H y se busca la que menos se aparta
                      del eje del arco. Regla del tercio central (e <= t/6),
                      estabilidad (e <= t/2), esfuerzo contra f'm/3 y el
                      espesor mínimo con el que la línea cabe en el tercio.

Unidades: m, kg/m, kg/cm². Sin f'm (resistencia de la mampostería) no se
revisa el esfuerzo: es dato del proyecto, no un supuesto. Referencias:
Heyman, "The Stone Skeleton" (1966) y "The safety of masonry arches"
(1969); Méry (1840). Revisión PRELIMINAR para arcos de vivienda; la primera
versión comparaba con la parábola de carga uniforme y condenaba cualquier
medio punto: un arco circular no sigue esa parábola porque su peso propio
no es uniforme en planta.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import annotation as ann
import autocad_client as acad
import prim
import space

TIPOS = ("medio_punto", "rebajado", "apuntado", "carpanel")
LAYER_ARCO = "ARCOS"
LAYER_DOVELA = "ARCOS-DOVELAS"
LAYER_TXT = "ARCOS-TEXTOS"

Arc = tuple[tuple[float, float], float, float, float]      # centro, R, a0, a1 (grados)


def _r(v: float, n: int = 3) -> float:
    return round(float(v), n)


def _bulge(theta_rad: float) -> float:
    return math.tan(theta_rad / 4.0)


def _trazo(L: float, rise: Optional[float], kind: str) -> tuple[list[Arc], float, list[str]]:
    """Los arcos del trazo (de izquierda a derecha), la flecha real y avisos."""
    avisos: list[str] = []
    if kind == "medio_punto":
        f = L / 2
        if rise is not None and abs(rise - f) > 1e-6:
            avisos.append(f"Un medio punto tiene flecha = luz/2 = {f:.3f}; se ignora rise={rise}.")
        return [((L / 2, 0.0), L / 2, 0.0, 180.0)], f, avisos
    if kind == "rebajado":
        if rise is None or not 0 < rise < L / 2:
            raise ValueError("rebajado: 0 < rise < span/2 (si rise = span/2 es medio punto).")
        f = float(rise)
        R = (L * L / 4 + f * f) / (2 * f)
        a = math.degrees(math.asin((L / 2) / R))
        return [((L / 2, f - R), R, 90.0 - a, 90.0 + a)], f, avisos
    if kind == "apuntado":
        if rise is None or rise <= 0:
            raise ValueError("apuntado: hace falta rise > 0 (típico rise >= span/2).")
        f = float(rise)
        # Dos arcos de radio R con centros (L/2 ± d, 0) sobre la línea de
        # arranques; cada uno pasa por su arranque y por la clave (L/2, f):
        # R = L/2 + d  y  R² = d² + f²  ->  d = (f² − L²/4)/L
        d = (f * f - L * L / 4) / L
        if d < 0:
            raise ValueError("apuntado: con rise < span/2 los centros caen fuera; usá 'rebajado'.")
        R = L / 2 + d
        a = math.degrees(math.atan2(f, d))
        return [((L / 2 + d, 0.0), R, 180.0 - a, 180.0), ((L / 2 - d, 0.0), R, 0.0, a)], f, avisos
    if kind == "carpanel":
        if rise is None or not 0 < rise < L / 2:
            raise ValueError("carpanel: 0 < rise < span/2.")
        f = float(rise)
        r = L * f / (L + 2 * f)
        # Tres centros: laterales (r, 0) y (L − r, 0) de radio r; central (L/2, c)
        # de radio R = f − c, tangente interior a los laterales:
        #   (L/2 − r)² + c² = (R − r)²  ->  c = ((f − r)² − (L/2 − r)²) / (2(f − r))
        c = ((f - r) ** 2 - (L / 2 - r) ** 2) / (2 * (f - r))
        R = f - c
        if R <= r or r <= 0:
            raise ValueError("carpanel: la flecha es demasiado chica para tres centros; usá 'rebajado'.")
        ux, uy = (r - L / 2), (0.0 - c)
        n = math.hypot(ux, uy)
        ux, uy = ux / n, uy / n
        tx_i, ty_i = r + ux * r, uy * r
        tx_d, ty_d = (L - r) - ux * r, uy * r
        a_i = math.degrees(math.atan2(ty_i, tx_i - r))
        a_d = math.degrees(math.atan2(ty_d, tx_d - (L - r)))
        c_i = math.degrees(math.atan2(ty_i - c, tx_i - L / 2))
        c_d = math.degrees(math.atan2(ty_d - c, tx_d - L / 2))
        return [((r, 0.0), r, a_i, 180.0), ((L / 2, c), R, c_i, c_d), ((L - r, 0.0), r, 0.0, a_d)], f, avisos
    raise ValueError(f"kind: {', '.join(TIPOS)}.")


def _puntos(arcs: list[Arc], offset: float) -> tuple[list[list[float]], list[float], float]:
    """Polilínea de izquierda a derecha sobre los arcos con radio + offset."""
    pts: list[list[float]] = []
    bul: list[float] = []
    largo = 0.0
    for (cx, cy), R, a0, a1 in arcs:
        Ro = R + offset
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


def _y_en(arcs: list[Arc], x: float, offset: float = 0.0) -> Optional[float]:
    """y del trazo (con offset radial) en la abscisa x, respetando el tramo
    angular de cada arco: en un apuntado los dos círculos se cruzan, y tomar
    'el más alto' daba una excentricidad de 1.41 m en un arco de 1.60 de
    flecha."""
    mejor, respaldo = None, None
    for (cx, cy), R, a0, a1 in arcs:
        Ro = R + offset
        dx = x - cx
        if abs(dx) > Ro + 1e-9:
            continue
        y = cy + math.sqrt(max(Ro * Ro - dx * dx, 0.0))
        ang = math.degrees(math.atan2(y - cy, dx)) % 360.0
        lo, hi = min(a0, a1) % 360.0, max(a0, a1) % 360.0
        if lo - 1e-6 <= ang <= hi + 1e-6 and (mejor is None or y > mejor):
            mejor = y
        if respaldo is None or y > respaldo:
            respaldo = y
    # Con offset, los arcos de un apuntado no se tocan en la clave (queda una
    # cuña): ahí ningún tramo angular acepta el punto y se toma el más alto.
    return mejor if mejor is not None else respaldo


def arch_geometry(span: float, rise: Optional[float] = None, kind: str = "medio_punto",
                  thickness: float = 0.0, voussoirs: int = 0) -> dict[str, Any]:
    """Trazo de un arco de luz `span` (entre arranques, intradós) y flecha
    `rise` (del arranque a la clave, intradós). (0, 0) es el arranque
    izquierdo; el eje X va hacia el derecho.

    medio_punto: rise = span/2. rebajado (escarzano): un centro bajo la línea
    de arranques, rise < span/2. apuntado (ojival): dos centros sobre la
    línea de arranques, rise >= span/2. carpanel: tres centros, rise < span/2.

    Devuelve `intrados` (puntos + bulges, de izq. a der.), `extrados` si hay
    thickness, los `arcs` (centro, radio, ángulos), el largo del intradós y,
    con voussoirs (impar), las juntas de las dovelas y la clave."""
    L = float(span)
    if L <= 0:
        raise ValueError("span tiene que ser > 0.")
    if kind not in TIPOS:
        raise ValueError(f"kind: {', '.join(TIPOS)}.")
    t = float(thickness or 0.0)
    if t < 0:
        raise ValueError("thickness no puede ser negativo.")
    arcs, f, avisos = _trazo(L, rise, kind)
    ip, ib, largo_i = _puntos(arcs, 0.0)
    out: dict[str, Any] = {
        "kind": kind, "span": L, "rise": _r(f), "thickness": t,
        "centers": [[_r(c[0]), _r(c[1])] for c, *_ in arcs],
        "radii": [_r(R) for _, R, *_ in arcs],
        "arcs": [{"center": [_r(c[0]), _r(c[1])], "radius": _r(R), "start_deg": _r(a0, 2),
                  "end_deg": _r(a1, 2)} for c, R, a0, a1 in arcs],
        "intrados": {"points": [[_r(x), _r(y)] for x, y in ip], "bulges": [_r(b, 6) for b in ib],
                     "length": _r(largo_i)},
        "crown": [_r(L / 2), _r(f)],
        "warnings": avisos,
    }
    if t > 0:
        ep, eb, largo_e = _puntos(arcs, t)
        out["extrados"] = {"points": [[_r(x), _r(y)] for x, y in ep], "bulges": [_r(b, 6) for b in eb],
                           "length": _r(largo_e)}
    if voussoirs:
        n = int(voussoirs)
        if n < 3 or n % 2 == 0:
            raise ValueError("voussoirs: impar y >= 3, para que haya una clave centrada.")
        juntas = [_punto_y_normal(arcs, largo_i * k / n) for k in range(1, n)]
        out["voussoirs"] = {"count": n, "joints": [{"intrados": [_r(p[0]), _r(p[1])],
                                                    "normal": [_r(v[0], 4), _r(v[1], 4)]}
                                                   for p, v in juntas],
                            "keystone_index": n // 2}
    return out


def _punto_y_normal(arcs: list[Arc], s: float, offset: float = 0.0
                    ) -> tuple[tuple[float, float], tuple[float, float]]:
    """Punto sobre el trazo (intradós + offset radial) a longitud s desde el
    arranque izquierdo y la normal exterior (hacia el extradós)."""
    for (cx, cy), R, a0, a1 in arcs:
        Ro = R + offset
        hi, lo = max(a0, a1), min(a0, a1)
        largo = Ro * math.radians(hi - lo)
        if s <= largo + 1e-9:
            ang = math.radians(hi) - s / Ro
            return (cx + Ro * math.cos(ang), cy + Ro * math.sin(ang)), (math.cos(ang), math.sin(ang))
        s -= largo
    (cx, cy), R, a0, a1 = arcs[-1]
    Ro = R + offset
    ang = math.radians(min(a0, a1))
    return (cx + Ro * math.cos(ang), cy + Ro * math.sin(ang)), (math.cos(ang), math.sin(ang))


# ------------------------------------------------------------ revisión

def check_masonry_arch(span: float, rise: float, thickness: float, width: float,
                       load_kg_m: float, fm_kgcm2: Optional[float] = None,
                       self_weight: bool = True, unit_weight: float = 1800.0,
                       kind: str = "medio_punto", n: int = 80) -> dict[str, Any]:
    """Arco de mampostería de luz `span`, flecha `rise` (intradós), espesor
    radial `thickness` y ancho `width` (profundidad del muro), con sobrecarga
    vertical uniforme `load_kg_m` (muro encima, losa) MÁS su peso propio, que
    SIGUE EL ARCO (más pesado por metro de planta donde el arco es más
    vertical).

    Método (Heyman, análisis límite): el arco es un sistema biarticulado en
    los arranques del eje; para cada empuje H la línea de presiones es
    y(x) = M(x)/H con M el momento de viga simplemente apoyada bajo las cargas
    reales. Se busca el H cuya línea menos se aparta del eje del arco
    (excentricidad máxima e_max, medida normal a la sección). Si cabe en el
    tercio central (e_max <= t/6) la junta trabaja toda a compresión; si cabe
    en la sección (e_max <= t/2) el arco es estable aunque agriete. Esfuerzo
    máximo σ = N/A + 6·N·e/(b·t²) contra f'm/3 si se da f'm. PRELIMINAR."""
    L, f, t, b = float(span), float(rise), float(thickness), float(width)
    if min(L, f, t, b) <= 0:
        raise ValueError("span, rise, thickness y width tienen que ser > 0.")
    if load_kg_m < 0:
        raise ValueError("load_kg_m no puede ser negativa.")
    arcs, f_real, avisos = _trazo(L, None if kind == "medio_punto" else f, kind)
    if kind != "medio_punto" and abs(f_real - f) > 1e-6:
        avisos.append(f"rise ajustado a {f_real:.3f}.")
    # Eje del arco: el trazo a t/2 del intradós. Su dominio en x (los
    # arranques del eje) sale de los extremos del primer y último arco.
    cp, _, _ = _puntos(arcs, t / 2)
    xa, xb = cp[0][0], cp[-1][0]
    ya, yb = cp[0][1], cp[-1][1]
    xs = [xa + (xb - xa) * k / n for k in range(n + 1)]
    yc = []
    for x in xs:
        y = _y_en(arcs, x, t / 2)
        yc.append(y if y is not None else 0.0)
    # Carga por metro de planta: sobrecarga + peso propio por longitud de eje.
    q = []
    for i, x in enumerate(xs):
        i0, i1 = max(i - 1, 0), min(i + 1, n)
        dy = (yc[i1] - yc[i0]) / (xs[i1] - xs[i0]) if xs[i1] != xs[i0] else 0.0
        ds_dx = min(math.sqrt(1.0 + dy * dy), 6.0)          # tope en los arranques verticales
        q.append(float(load_kg_m) + (unit_weight * t * b * ds_dx if self_weight else 0.0))
    dx = (xb - xa) / n
    Lp = xb - xa
    # Integrales acumuladas de la carga: W(x) = ∫q, S(x) = ∫q·x. Con ellas el
    # momento de viga simplemente apoyada entre DOS PUNTOS CUALESQUIERA
    # (las rótulas, que no tienen por qué estar en el eje) sale cerrado.
    Wc, Sc = [0.0], [0.0]
    for i in range(n):
        qm = (q[i] + q[i + 1]) / 2
        xm = (xs[i] + xs[i + 1]) / 2
        Wc.append(Wc[-1] + qm * dx)
        Sc.append(Sc[-1] + qm * dx * xm)
    W = Wc[-1]

    def _interp(arr, x):
        u = min(max((x - xa) / dx, 0.0), n - 1e-9)
        i = int(u)
        return arr[i] + (arr[i + 1] - arr[i]) * (u - i)

    # Secciones de control: puntos del eje repartidos por LONGITUD DE ARCO
    # (así los riñones de un medio punto, donde la línea se escapa, quedan
    # bien muestreados) con la dirección RADIAL de cada junta.
    ns = 60
    largo_eje = sum((R + t / 2) * math.radians(abs(a1 - a0)) for _, R, a0, a1 in arcs)
    secciones = [_punto_y_normal(arcs, largo_eje * k / ns, t / 2) for k in range(ns + 1)]
    (Ca, nA), (Cb, nB) = secciones[0], secciones[-1]

    def linea(H: float, ea: float):
        """Línea de presiones para empuje H con las rótulas corridas `ea`
        SOBRE LA JUNTA de arranque (dirección radial; simétrico): devuelve
        la función y(x) y el tramo [x1, x2] donde existe."""
        x1, y1 = Ca[0] + ea * nA[0], Ca[1] + ea * nA[1]
        x2, y2 = Cb[0] + ea * nB[0], Cb[1] + ea * nB[1]
        if x2 - x1 < 0.3 * Lp:
            return None, x1, x2
        W1, S1 = _interp(Wc, x1), _interp(Sc, x1)
        W2, S2 = _interp(Wc, x2), _interp(Sc, x2)
        Wt = W2 - W1
        Vb = ((S2 - S1) - x1 * Wt) / (x2 - x1)
        Va = Wt - Vb

        def y(x):
            if x < x1 - 1e-9 or x > x2 + 1e-9:
                return None
            Wx, Sx = _interp(Wc, x), _interp(Sc, x)
            m = Va * (x - x1) - (x * (Wx - W1) - (Sx - S1))
            return y1 + (y2 - y1) * (x - x1) / (x2 - x1) + m / H
        return y, x1, x2

    def exc_normal(yl, C, nrm) -> float:
        """Dónde cruza la línea la junta radial que pasa por C (bisección
        sobre s ∈ [−t, t]); si no la cruza, la línea salió de la sección."""
        def g(s):
            v = yl(C[0] + s * nrm[0])
            return None if v is None else v - (C[1] + s * nrm[1])
        lo, hi = -t, t
        glo, ghi = g(lo), g(hi)
        if glo is None or ghi is None or glo * ghi > 0:
            # Sin cambio de signo en ±t: la línea pasa por fuera. Se devuelve
            # t MÁS cuánto le falta, para que el optimizador tenga pendiente
            # (un valor plano lo dejaba ciego y daba "inestable" a cualquier
            # medio punto).
            mejor_s, mejor_g = None, float("inf")
            for k in range(13):
                s = -t + 2 * t * k / 12
                v = g(s)
                if v is not None and abs(v) < mejor_g:
                    mejor_g, mejor_s = abs(v), s
            if mejor_s is None:
                return 2 * t
            return abs(mejor_s) if mejor_g <= 0.2 * t else t + mejor_g
        for _ in range(14):
            mid = (lo + hi) / 2
            gm = g(mid)
            if gm is None:
                break
            if glo * gm <= 0:
                hi, ghi = mid, gm
            else:
                lo, glo = mid, gm
        return abs((lo + hi) / 2)

    def e_max_para(H: float, ea: float) -> tuple[float, int]:
        yl, _, _ = linea(H, ea)
        if yl is None:
            return 2 * t, 0
        peor, idx = 0.0, 0
        for i, (C, nrm) in enumerate(secciones):
            e = exc_normal(yl, C, nrm)
            if e > peor:
                peor, idx = e, i
        return peor, idx

    H0 = W * Lp / (8 * f_real)
    GR = (math.sqrt(5) - 1) / 2

    def golden(fn, lo, hi, iters=14):
        """Mínimo de fn en [lo, hi] por sección áurea (fn unimodal)."""
        a, b = lo, hi
        c, d = b - GR * (b - a), a + GR * (b - a)
        fc, fd = fn(c), fn(d)
        for _ in range(iters):
            if fc[0] <= fd[0]:
                b, d, fd = d, c, fc
                c = b - GR * (b - a)
                fc = fn(c)
            else:
                a, c, fc = c, d, fd
                d = a + GR * (b - a)
                fd = fn(d)
        return fc if fc[0] <= fd[0] else fd

    def mejor_ea(H):
        """Para un empuje dado, la posición de rótula que minimiza e_max."""
        e, i, ea = golden(lambda ea: (*e_max_para(H, ea), ea), -0.49 * t, 0.49 * t, 12)
        return e, H, ea, i

    # La sensibilidad al empuje es grande: barrido grueso de H y después
    # sección áurea alrededor del mejor. Con un barrido fijo de 7 x 54 el
    # medio punto de Heyman (t/R = 0.1075) salía inestable hasta t/R = 0.17.
    candidatos = [mejor_ea(H0 * (0.20 + 4.0 * k / 23)) for k in range(24)]
    mejor = min(candidatos, key=lambda c: c[0])
    k0 = candidatos.index(mejor)
    Hlo = H0 * (0.20 + 4.0 * max(k0 - 1, 0) / 23)
    Hhi = H0 * (0.20 + 4.0 * min(k0 + 1, 23) / 23)
    fino = golden(lambda H: mejor_ea(H), Hlo, Hhi, 16)
    if fino[0] < mejor[0]:
        mejor = fino
    mejor_e, H, ea, mejor_i = mejor
    mejor_e = min(mejor_e, t)              # fuera de la sección se reporta como t
    yl, x1, x2 = linea(H, ea)
    W1 = _interp(Wc, x1)
    Va = (W - 0) - (((_interp(Sc, x2) - _interp(Sc, x1)) - x1 * (_interp(Wc, x2) - W1)) / (x2 - x1))
    Vb = W - Va
    # Esfuerzo en la junta más cargada: N = resultante de H y el cortante.
    sigma_max, x_s = 0.0, xa
    for C, nrm in secciones:
        e = exc_normal(yl, C, nrm) if yl else t
        Vx = Va - (_interp(Wc, C[0]) - W1)
        N = math.hypot(H, Vx)
        sig = N / (b * t) + 6 * N * e / (b * t * t)
        if sig > sigma_max:
            sigma_max, x_s = sig, C[0]
    xs = [C[0] for C, _ in secciones]       # para reportar dónde está e_max
    sigma_kgcm2 = sigma_max / 1e4
    tercio = mejor_e <= t / 6 + 1e-9
    estable = mejor_e <= t / 2 + 1e-9
    out: dict[str, Any] = {
        "kind": kind, "span": L, "rise": _r(f_real), "thickness": t, "width": b,
        "W_total_kg": _r(W, 1), "load_kg_m": load_kg_m,
        "thrust_H_kg": _r(H, 1), "reactions_V_kg": [_r(Va, 1), _r(Vb, 1)],
        "e_max_m": _r(mejor_e, 4), "e_max_at_x": _r(xs[mejor_i], 3),
        "middle_third": {"ok": tercio, "limit_m": _r(t / 6, 4),
                         "ref": "Tercio central (Heyman 1966): toda la junta a compresión"},
        "stability": {"ok": estable, "limit_m": _r(t / 2, 4),
                      "ref": "Heyman 1969: línea de presiones dentro de la sección"},
        "t_required_m": _r(6 * mejor_e, 3),
        "sigma_max_kgcm2": _r(sigma_kgcm2, 2), "sigma_at_x": _r(x_s, 3),
        "method": "Funicular numérica (peso propio sobre el eje + sobrecarga), H óptimo; Heyman. PRELIMINAR.",
        "warnings": avisos,
    }
    if fm_kgcm2 is None:
        out["stress"] = {"ok": None, "note": "Sin f'm no se revisa el esfuerzo: pasá fm_kgcm2 (dato del proyecto)."}
    else:
        if fm_kgcm2 <= 0:
            raise ValueError("fm_kgcm2 tiene que ser > 0.")
        adm = fm_kgcm2 / 3.0
        out["stress"] = {"ok": sigma_kgcm2 <= adm + 1e-9, "allowable_kgcm2": _r(adm, 2),
                         "fm_kgcm2": fm_kgcm2,
                         "ref": "Esfuerzo admisible f'm/3 (criterio clásico de mampostería; confirmar con la norma local)"}
    out["ok"] = tercio and estable and (out["stress"]["ok"] is not False)
    return out


# ------------------------------------------------------------ dibujo

def create_arch(x: float, y: float, span: float, rise: Optional[float] = None,
                kind: str = "medio_punto", thickness: float = 0.0, voussoirs: int = 0,
                closed: bool = True, layer: str = LAYER_ARCO, lineweight: int = 35,
                annotate: bool = False, label: Optional[str] = None,
                load_kg_m: Optional[float] = None, width: float = 0.15,
                fm_kgcm2: Optional[float] = None, upm: float = 0.0) -> dict[str, Any]:
    """Dibuja el arco con su arranque izquierdo en (x, y). Con thickness traza
    intradós y extradós (y cierra los arranques si closed); con voussoirs
    dibuja las juntas radiales. annotate=True acota luz y flecha y rotula el
    tipo, L/f/e; con load_kg_m además corre check_masonry_arch y escribe el
    empuje H y el veredicto del tercio central. upm = unidades por mm de
    papel (0 = la escala registrada de la lámina)."""
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
    f = g["rise"]
    ext = thickness if thickness > 0 else 0.0
    xs_ext = [p[0] for p in g.get("extrados", g["intrados"])["points"]]
    x_min, x_max = x + min(xs_ext), x + max(xs_ext)
    g["box"] = [x_min, y, x_max, y + f + ext]
    if annotate:
        esc = upm or space.units_per_paper_mm() or 0.0
        kw = {"scale": esc} if esc else {}
        ann.create_dimension_chain(positions=[x, x + span], side="bottom", reference=y, **kw)
        ann.create_dimension_chain(positions=[y, y + f], side="right", reference=x_max + 0.1, **kw)
        h = (esc or 0.05) * 2.0
        nombre = label or kind.replace("_", " ").upper()
        textos = [{"text": nombre, "x": x + span / 2 - 0.46 * h * len(nombre), "y": y - 7.5 * h},
                  {"text": f"L = {span:.2f}  f = {f:.2f}" + (f"  e = {thickness:.2f}" if thickness else ""),
                   "x": x + span / 2 - 0.46 * h * 22, "y": y - 10 * h}]
        if load_kg_m is not None:
            if thickness <= 0:
                raise ValueError("Para revisar el arco hace falta thickness (espesor radial).")
            chk = check_masonry_arch(span, f, thickness, width, load_kg_m, fm_kgcm2, kind=kind)
            g["check"] = chk
            ver = ("OK" if chk["middle_third"]["ok"] else
                   ("ESTABLE, JUNTA ABIERTA" if chk["stability"]["ok"] else "NO ESTABLE"))
            s = f"H = {chk['thrust_H_kg']:.0f} kg  e.max = {chk['e_max_m'] * 100:.1f} cm  {ver}"
            textos.append({"text": s, "x": x + span / 2 - 0.46 * h * len(s), "y": y - 12.5 * h})
        prim.capa(LAYER_TXT, 7, 0)
        ann.place_labels(textos, height=h, layer=LAYER_TXT)
        # La caja incluye el rótulo más largo (centrado en la luz): si no, la
        # vista del layout lo cortaba por la izquierda.
        semi = max(0.5 * h * len(tx["text"]) for tx in textos) + h
        g["box"] = [min(x_min - 2.0 * h, x + span / 2 - semi), y - 14 * h,
                    max(x_max + 14 * h, x + span / 2 + semi), y + f + ext + 2 * h]
    return g
