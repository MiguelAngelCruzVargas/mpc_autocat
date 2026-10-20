"""Portico de acceso con arco (porton entre pilastras) y su barda: DISEÑO.

No dibuja nada. Calcula, con la salida de cada paso como entrada del
siguiente, lo que un albañil necesita leer en el plano:

  1. Geometria del arco rebajado (intrados por luz libre, arranque y clave;
     la trabe curva es concentrica, de peralte h).
  2. Marco plano (pilastra - trabe curva - pilastra) por rigideces, en dos
     condiciones de apoyo (empotrado en la cimentacion / articulado) y con la
     envolvente de las dos: peso propio + forros + hoja del porton (que
     cuelga de las pilastras como PAR de fuerzas horizontales en las bisagras)
     y sismo en el plano.
  3. Fuera del plano (viento sobre el porton, sobre las pilastras y la trabe, y
     sismo): cada pilastra es un voladizo desde la cimentacion.
  4. Trabe curva: flexion y cortante por design_beam (ACI 318-19), en la zona
     de apoyos y en el centro.
  5. Pilastra de concreto (nucleo): interaccion P-M por compatibilidad de
     deformaciones, flexion en los dos sentidos (carga de contorno lineal,
     conservadora), cuantia minima 20/fy (NTC-Concreto) y estribos.
  6. Zapata: design_footing con las cargas y los momentos de servicio.
  7. Barda: pilastra intermedia (separada 3 m) y su cimentacion corrida.

Lo que NO inventa: la capacidad del suelo (sin ella ValueError, igual que
design_footing), f'c, fy ni las medidas. Lo que NO viene del proyecto y hay
que suponer (peso de la hoja, velocidad del viento, coeficiente sismico, peso
del forro) va como parametro con valor por omision VISIBLE en 'supuestos' y en
las notas del plano: se confirma o se cambia, no se esconde.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np

import estructura as est
import zapatas as zap

G = 9.80665
ESTRIBO = {"#2": 0.32, "#3": 0.71, "#4": 1.27}


def _r(v: float, n: int = 2) -> float:
    return round(float(v), n)


# ----------------------------------------------------------- geometria

# Perfil de la cornisa del fronton MEDIDO en la foto de referencia del cliente
# (arco_referencia.png: claro de 5.00 m = 305 px -> 61 px/m, piso en y = 405 px).
# (|distancia al eje| m, altura sobre el piso m). Simetrico. Mas alla de 2.07 m
# la cornisa llega a la pilastra a 4.88 m.
PERFIL_FOTO: list[tuple[float, float]] = [
    (0.00, 5.92), (0.30, 5.87), (0.56, 5.79), (0.75, 5.66), (0.89, 5.54), (1.02, 5.48),
    (1.28, 5.41), (1.48, 5.33), (1.61, 5.25), (1.74, 5.11), (1.93, 4.98), (2.07, 4.90),
    (2.50, 4.88), (3.60, 4.88)]


def geometria_arco(clear_span: float, spring_h: float, crown_h: float,
                   pilaster: float, beam_h: float, top_ends_h: Optional[float] = None,
                   top_crown_h: Optional[float] = None,
                   profile: Optional[list[tuple[float, float]]] = None) -> dict[str, Any]:
    """Intrados circular por (±S/2, spring_h) y (0, crown_h). La trabe curva es
    concentrica: eje a h/2 del intrados. Los ejes de las pilastras estan a
    S + pilaster. El fronton (muro sobre la trabe) termina arriba en la
    cornisa 'profile' (puntos |x|, altura; por omision el medido en la foto).
    top_ends_h = donde termina el nucleo de la pilastra (estructura)."""
    f = crown_h - spring_h
    if f <= 0:
        raise ValueError("La clave tiene que quedar más alta que el arranque.")
    R = (clear_span ** 2 / 4.0 + f ** 2) / (2.0 * f)
    yc = crown_h - R
    Rc = R + beam_h / 2.0
    L = clear_span + pilaster
    y_eje_arranque = yc + math.sqrt(Rc ** 2 - (L / 2.0) ** 2)
    perfil = [tuple(p) for p in (profile or PERFIL_FOTO)]
    top_crown_h = top_crown_h if top_crown_h else max(h for _, h in perfil)
    top_ends_h = top_ends_h if top_ends_h else perfil[-1][1] - 0.08
    return {"S": clear_span, "f": _r(f, 3), "R": _r(R, 3), "yc": _r(yc, 3), "Rc": _r(Rc, 3),
            "L_ejes": _r(L, 3), "spring_h": spring_h, "crown_h": crown_h,
            "y_eje_arranque": _r(y_eje_arranque, 3), "beam_h": beam_h,
            "Re": _r(R + beam_h, 3), "top_ends_h": top_ends_h, "top_crown_h": top_crown_h,
            "perfil": perfil, "x_outer": _r(clear_span / 2.0 + pilaster, 3)}


def y_top(g: dict[str, Any], x: float) -> float:
    xs = [p[0] for p in g["perfil"]]
    hs = [p[1] for p in g["perfil"]]
    return float(np.interp(abs(x), xs, hs))


def y_extrados(g: dict[str, Any], x: float) -> float:
    return g["yc"] + math.sqrt(max(g["Re"] ** 2 - x * x, 0.0))


def y_intrados(g: dict[str, Any], x: float) -> float:
    return g["yc"] + math.sqrt(max(g["R"] ** 2 - x * x, 0.0))


# ----------------------------------------------------------- marco plano

def _marco(geo: dict[str, Any], hb: float, Ec: float, Ac: float, Ic: float,
           Ab: float, Ib: float, n_arco: int = 28, n_col: int = 6, n_stub: int = 3) -> dict[str, Any]:
    """Nodos y elementos: pilastra izquierda (de la base al remate, con el nudo del
    arco a la altura del arranque), arco, pilastra derecha."""
    L = geo["L_ejes"]
    xa, xb = -L / 2.0, L / 2.0
    yj, ytop = geo["y_eje_arranque"], geo["top_ends_h"]
    nodos: list[tuple[float, float]] = []
    elems: list[tuple[int, int, float, float, float, str]] = []

    def columna(x):
        ids = []
        for k in range(n_col + 1):
            nodos.append((x, -hb + (yj + hb) * k / n_col))
            ids.append(len(nodos) - 1)
        for k in range(1, n_stub + 1):
            nodos.append((x, yj + (ytop - yj) * k / n_stub))
            ids.append(len(nodos) - 1)
        return ids, ids[n_col]

    izq, jl = columna(xa)
    arco = [jl]
    for k in range(1, n_arco):
        x = xa + L * k / n_arco
        nodos.append((x, geo["yc"] + math.sqrt(geo["Rc"] ** 2 - x ** 2)))
        arco.append(len(nodos) - 1)
    der, jr = columna(xb)
    arco.append(jr)
    for ids in (izq, der):
        for a, b in zip(ids[:-1], ids[1:]):
            elems.append((a, b, Ec, Ac, Ic, "col"))
    for a, b in zip(arco[:-1], arco[1:]):
        elems.append((a, b, Ec, Ab, Ib, "arco"))
    return {"nodos": nodos, "elems": elems, "base_izq": izq[0], "base_der": der[0],
            "izq_top": jl, "der_top": jr, "izq": izq, "der": der, "arco": arco}


def _resolver(marco: dict[str, Any], cargas: dict[int, tuple[float, float, float]],
              base: str) -> dict[str, Any]:
    """Rigidez directa. cargas: nodo -> (Fx, Fy, Mz) en kg, kg·m. base:
    'empotrada' o 'articulada'. Devuelve esfuerzos en los extremos de cada
    elemento (N, V, M en i y j, locales) y las reacciones."""
    nodos, elems = marco["nodos"], marco["elems"]
    n = len(nodos)
    K = np.zeros((3 * n, 3 * n))
    info = []
    for (i, j, E, A, I, tipo) in elems:
        dx, dy = nodos[j][0] - nodos[i][0], nodos[j][1] - nodos[i][1]
        Lx = math.hypot(dx, dy)
        c, s = dx / Lx, dy / Lx
        k = np.array([
            [A * E / Lx, 0, 0, -A * E / Lx, 0, 0],
            [0, 12 * E * I / Lx ** 3, 6 * E * I / Lx ** 2, 0, -12 * E * I / Lx ** 3, 6 * E * I / Lx ** 2],
            [0, 6 * E * I / Lx ** 2, 4 * E * I / Lx, 0, -6 * E * I / Lx ** 2, 2 * E * I / Lx],
            [-A * E / Lx, 0, 0, A * E / Lx, 0, 0],
            [0, -12 * E * I / Lx ** 3, -6 * E * I / Lx ** 2, 0, 12 * E * I / Lx ** 3, -6 * E * I / Lx ** 2],
            [0, 6 * E * I / Lx ** 2, 2 * E * I / Lx, 0, -6 * E * I / Lx ** 2, 4 * E * I / Lx]])
        T = np.zeros((6, 6))
        rot = np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]])
        T[:3, :3] = rot
        T[3:, 3:] = rot
        kg = T.T @ k @ T
        idx = [3 * i, 3 * i + 1, 3 * i + 2, 3 * j, 3 * j + 1, 3 * j + 2]
        for a in range(6):
            for b in range(6):
                K[idx[a], idx[b]] += kg[a, b]
        info.append((idx, k, T, Lx, tipo))
    f = np.zeros(3 * n)
    for nodo, (fx, fy, mz) in cargas.items():
        f[3 * nodo:3 * nodo + 3] += (fx, fy, mz)
    fijos = [3 * marco["base_izq"], 3 * marco["base_izq"] + 1, 3 * marco["base_der"],
             3 * marco["base_der"] + 1]
    if base == "empotrada":
        fijos += [3 * marco["base_izq"] + 2, 3 * marco["base_der"] + 2]
    libres = [d for d in range(3 * n) if d not in fijos]
    u = np.zeros(3 * n)
    u[libres] = np.linalg.solve(K[np.ix_(libres, libres)], f[libres])
    reac = K @ u - f
    fuerzas = []
    for (idx, k, T, Lx, tipo), e in zip(info, elems):
        fl = k @ (T @ u[idx])
        fuerzas.append({"i": e[0], "j": e[1], "tipo": tipo, "L": Lx,
                        "N": (-fl[0], fl[3]), "V": (fl[1], -fl[4]), "M": (-fl[2], fl[5])})
    return {"u": u, "reac": reac, "fuerzas": fuerzas}


def _combinar(res_list, factores, marco):
    """Momento en cada nodo del arco (con signo de la fibra: positivo = tension
    abajo) y en las columnas, para la combinacion lineal pedida."""
    fuerzas0 = res_list[0]["fuerzas"]
    arco = []
    col_base = 0.0
    col_top = 0.0
    col_N = 0.0
    col_V = 0.0
    arco_V = 0.0
    arco_N = 0.0
    for e, f0 in enumerate(fuerzas0):
        M = [sum(fa * r["fuerzas"][e]["M"][k] for fa, r in zip(factores, res_list)) for k in (0, 1)]
        V = [sum(fa * r["fuerzas"][e]["V"][k] for fa, r in zip(factores, res_list)) for k in (0, 1)]
        N = [sum(fa * r["fuerzas"][e]["N"][k] for fa, r in zip(factores, res_list)) for k in (0, 1)]
        if f0["tipo"] == "arco":
            arco.append(M[0]); arco.append(M[1])
            arco_V = max(arco_V, abs(V[0]), abs(V[1]))
            arco_N = max(arco_N, abs(N[0]), abs(N[1]))
        else:
            col_V = max(col_V, abs(V[0]), abs(V[1]))
            col_N = max(col_N, abs(N[0]), abs(N[1]))
            if f0["i"] in (marco["base_izq"], marco["base_der"]):
                col_base = max(col_base, abs(M[0]))
            for m in M:
                col_top = max(col_top, abs(m))
    return {"arco_Mmax": max(arco), "arco_Mmin": min(arco), "arco_V": arco_V, "arco_N": arco_N,
            "col_M_base": col_base, "col_M": col_top, "col_V": col_V, "col_N": col_N}


# ----------------------------------------------------------- columna P-M

def _capas(b: float, h: float, cover_centro: float, n_barras: int) -> list[tuple[float, int]]:
    """Capas de barras para flexion alrededor del eje que mide 'h' (la
    distancia desde la fibra comprimida). Reparte n_barras por el perimetro de
    un rectangulo: 4 = esquinas, 8 = esquinas + puntos medios (simetrico)."""
    if n_barras == 4:
        return [(cover_centro, 2), (h - cover_centro, 2)]
    if n_barras == 8:
        return [(cover_centro, 3), (h / 2.0, 2), (h - cover_centro, 3)]
    if n_barras == 12:
        return [(cover_centro, 4), (h / 3.0 + cover_centro / 3.0, 2),
                (2 * h / 3.0 - cover_centro / 3.0, 2), (h - cover_centro, 4)]
    raise ValueError("n_barras: 4, 8 o 12 (simétrico en los dos sentidos).")


def _pm(b: float, h: float, fc: float, fy: float, capas: list[tuple[float, int]],
        area_barra: float, pu_kg: float) -> float:
    """phi·Mn (t·m) a la carga axial pu_kg (compresion positiva), alrededor del
    eje centroidal, por compatibilidad de deformaciones (ACI 318-19 22.2,
    phi segun 21.2.2). Interpola en la curva de interaccion."""
    Es, ecu = 2.0e6, 0.003
    beta1 = 0.85 if fc <= 280 else max(0.65, 0.85 - 0.05 * (fc - 280) / 70.0)
    pts = []
    for c in np.concatenate([np.linspace(0.02 * h, 2.5 * h, 220)]):
        a = min(beta1 * c, h)
        cc = 0.85 * fc * a * b * 1e4                                   # kg (b,h en m -> cm²·1e4)
        fs_tot = 0.0
        ms = 0.0
        et_max = 0.0
        for (y, nb) in capas:
            es = ecu * (c - y) / c
            fs = max(-fy, min(fy, es * Es))
            if y <= a:
                fs_net = fs - 0.85 * fc
            else:
                fs_net = fs
            f = fs_net * area_barra * nb
            fs_tot += f
            ms += f * (h / 2.0 - y)
            et_max = max(et_max, -es) if False else et_max
        et = max(-ecu * (c - capas[-1][0]) / c, 0.0)
        pn = cc + fs_tot
        mn = cc * (h / 2.0 - a / 2.0) + ms
        ey = fy / Es
        if et <= ey:
            phi = 0.65
        elif et >= ey + 0.003:
            phi = 0.90
        else:
            phi = 0.65 + 0.25 * (et - ey) / 0.003
        pts.append((phi * pn, phi * mn / 1000.0))
    # tope de compresion pura
    ast = sum(nb for (_, nb) in capas) * area_barra
    p0 = 0.80 * 0.65 * (0.85 * fc * (b * h * 1e4 - ast) + fy * ast)
    pts = [(min(p, p0), m) for p, m in pts]
    pts.sort()
    pu = min(max(pu_kg, pts[0][0]), pts[-1][0])
    ps = [p for p, _ in pts]
    ms_ = [m for _, m in pts]
    # la curva no es monotona en M: tomo el maximo M de los puntos con P>=pu cercano
    best = 0.0
    for (p1, m1), (p2, m2) in zip(pts[:-1], pts[1:]):
        if min(p1, p2) <= pu <= max(p1, p2):
            t = 0 if p1 == p2 else (pu - p1) / (p2 - p1)
            best = max(best, m1 + t * (m2 - m1))
    return best


def disenar_pilastra(b: float, h: float, fc: float, fy: float, pu_kg: float,
                     combos: list[tuple[float, float]], h_libre: float,
                     estribo: str = "#3", cover: float = 0.04) -> dict[str, Any]:
    """Nucleo de concreto b x h (m). Pu (kg), Mux (alrededor del eje que mide
    h) y Muy (t·m), ya factorizados. Elige el menor armado simetrico que
    cumple la cuantia minima 20/fy y Mux/phiMnx + Muy/phiMny <= 1."""
    db_e = zap.VARILLAS[estribo][0]
    candidatos = []
    for nb in ((4, 8, 12) if min(b, h) < 0.35 else (8, 12)):
        for barra in ("#4", "#5", "#6", "#8"):
            a_b = zap.VARILLAS[barra][1]
            candidatos.append((nb * a_b, nb, barra))
    candidatos.sort()
    ag = b * h * 1e4
    rho_min = 20.0 / fy
    for as_tot, nb, barra in candidatos:
        if as_tot < rho_min * ag - 1e-9 or as_tot > 0.06 * ag:
            continue
        db = zap.VARILLAS[barra][0]
        dprima = cover + db_e + db / 2.0
        a_b = zap.VARILLAS[barra][1]
        # la separacion libre entre barras de una cara: <= 15 cm entre barras (ejes) es lo normal
        phimx = _pm(b, h, fc, fy, _capas(b, h, dprima, nb), a_b, pu_kg)
        phimy = _pm(h, b, fc, fy, _capas(h, b, dprima, nb), a_b, pu_kg)
        if phimx <= 0 or phimy <= 0:
            continue
        ratio = max(abs(mx) / phimx + abs(my) / phimy for mx, my in combos)
        if ratio <= 0.95:
            s_est = math.floor(min(850.0 / math.sqrt(fy) * db, 48 * db_e, min(b, h) / 2.0) / 0.025) * 0.025
            s_conf = 0.10
            l_conf = max(max(b, h), h_libre / 6.0, 0.45)
            return {"b": b, "h": h, "bars": {"count": nb, "bar": barra, "As_cm2": _r(as_tot),
                                             "text": f"{nb} {barra}"},
                    "rho": _r(as_tot / ag, 4), "rho_min": _r(rho_min, 4),
                    "phiMnx_tm": _r(phimx), "phiMny_tm": _r(phimy), "ratio": _r(ratio, 3),
                    "stirrups": {"bar": estribo, "spacing": _r(s_est, 3),
                                 "conf_spacing": s_conf, "conf_length": _r(math.ceil(l_conf / 0.05) * 0.05, 2),
                                 "text": f"E{estribo} @ {s_est * 100:.0f}"},
                    "dprime": _r(dprima, 3), "ok": True,
                    "refs": "ACI 318-19 22.2 / NTC-Concreto 5.1 (ρmín = 20/fy)"}
    raise ValueError(f"La pilastra {b:.2f}x{h:.2f} no da para Pu={pu_kg:.0f} kg y "
                     f"momentos {combos} t·m: hay que ensancharla.")


# ----------------------------------------------------------- zapata (contacto real)

def contacto(B: float, L: float, N: float, Mx: float, My: float, n: int = 41) -> tuple[float, float]:
    """Presion maxima (t/m²) y fraccion del area en contacto de una zapata B x L
    con carga N (t) y momentos Mx, My (t·m) SIN tension en el suelo: se busca
    el plano de presiones q = c + a·x + b·y (recortado en cero) que equilibra
    N y los dos momentos."""
    from scipy.optimize import fsolve
    xs = (np.arange(n) + 0.5) / n * B - B / 2.0
    ys = (np.arange(n) + 0.5) / n * L - L / 2.0
    X, Y = np.meshgrid(xs, ys)
    dA = B * L / n / n

    def res(p):
        q = np.maximum(p[0] + p[1] * X + p[2] * Y, 0.0)
        return [(q * dA).sum() - N, (q * X * dA).sum() - My, (q * Y * dA).sum() - Mx]
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sol, _, ier, _ = fsolve(res, [N / (B * L), 0.0, 0.0], xtol=1e-10, full_output=True)
    q = np.maximum(sol[0] + sol[1] * X + sol[2] * Y, 0.0)
    r = res(sol)
    if ier != 1 and max(abs(v) for v in r) > 1e-3 * max(N, 1.0):
        return float("inf"), 0.0                      # no equilibra: no vale
    return float(q.max()), float((q > 1e-9).mean())


def tamano_zapata(n_serv_t: float, combos: list[tuple[float, float]], q_adm: float,
                  depth: float, gamma_s: float, core: float, h: float = 0.40,
                  min_contacto: float = 0.90, paso: float = 0.1,
                  maximo: float = 5.0, max_aspecto: float = 2.0) -> dict[str, Any]:
    """Zapata rectangular de MENOR VOLUMEN (paso 10 cm). B va en el sentido del portón
    (donde actua el momento en el plano) y L fuera del plano (donde actua el viento o
    el sismo, que es el momento grande): una zapata larga hacia afuera del plano gasta
    menos concreto que una cuadrada. combos = [(M_en_plano, M_fuera_del_plano)] de
    servicio, t·m. Presion con CONTACTO REAL (sin tension), bruta (zapata y relleno
    incluidos) contra q_adm, y >= min_contacto del area comprimida."""
    n = int(round((maximo - 1.0) / paso))
    mejor = None
    for kb in range(n + 1):
        B = round(1.0 + paso * kb, 2)
        for kl in range(n + 1):
            L = round(1.0 + paso * kl, 2)
            if mejor and B * L >= mejor["B"] * mejor["L"] - 1e-9:
                break
            if max(B, L) / min(B, L) > max_aspecto + 1e-9:
                continue
            N = n_serv_t + 2.4 * B * L * h + gamma_s * (B * L - core * core) * max(depth - h, 0.0)
            ok, peor, cont = True, 0.0, 1.0
            for m_in, m_out in combos:
                qm, c = contacto(B, L, N, m_out, m_in)       # (Mx = fuera del plano -> eje y, My = en el plano)
                peor, cont = max(peor, qm), min(cont, c)
                if qm > q_adm or c < min_contacto:
                    ok = False
                    break
            if ok:
                mom = max(combos, key=lambda m: contacto(B, L, N, m[1], m[0])[0])
                mejor = {"B": B, "L": L, "h": h, "q_max": _r(peor), "contacto": _r(cont, 2), "momentos": mom}
                break
    if mejor is None:
        raise ValueError(f"Con q = {q_adm:.1f} t/m² no basta una zapata de {maximo:.0f} m: "
                         f"hay que reducir los momentos o mejorar el suelo.")
    return mejor


# ----------------------------------------------------------- diseño completo

def design_gate_portal(clear_span: float, spring_h: float, crown_h: float,
                       fc: float, allowable_bearing: float, depth: float,
                       soil_unit_weight: float, pilaster: float = 0.95,
                       core: float = 0.40, pilaster_depth: float = 0.60, fy: float = 4200.0,
                       beam_b: float = 0.20, beam_h: float = 0.50,
                       cladding_kg_m: float = 0.0, gate_leaf_kg: float = 400.0,
                       gate_leaf_width: float = 0.0, wind_kmh: float = 120.0,
                       gate_solidity: float = 0.60, seismic_c: float = 0.30,
                       base_depth: float = 0.30, stirrup_beam: str = "#3",
                       fc_footing: Optional[float] = None,
                       top_ends_h: Optional[float] = None, top_crown_h: Optional[float] = None,
                       tymp_kg_m2: float = 400.0, cornisa_kg_m: float = 60.0,
                       tymp_t: float = 0.20, core_options: tuple[float, ...] = (),
                       extra_loads: Optional[list[tuple[float, float]]] = None) -> dict[str, Any]:
    """Diseño del portico de acceso con su fronton. Devuelve geometria, esfuerzos,
    trabe, pilastra, castillos y dala del fronton y zapata, mas 'supuestos' y
    'decisions'. Sin capacidad del suelo, fc, desplante o peso del relleno rechaza
    (no los inventa). core_options: nucleos a probar si el primero no da."""
    for nombre, v in (("fc", fc), ("allowable_bearing", allowable_bearing), ("depth", depth),
                      ("soil_unit_weight", soil_unit_weight)):
        if v is None or v <= 0:
            raise ValueError(f"{nombre} es dato del proyecto: no se supone.")
    decisions: list[str] = []
    supuestos: list[str] = []
    Ec = 15100.0 * math.sqrt(fc) * 1e4                   # kg/m²
    alturas = [beam_h] if beam_h else [0.40, 0.45, 0.50, 0.55, 0.60]
    nucleos = [core] + [c for c in core_options if c != core]
    def una(liga: bool) -> dict[str, Any]:
        """Un diseño completo (con o sin trabe de liga entre las dos zapatas)."""
        decs: list[str] = []
        sups: list[str] = []
        ultimo = None
        r = None
        for c_ in nucleos:
            for hb_ in alturas:
                try:
                    r = _disenar_con(clear_span, spring_h, crown_h, fc, fy, pilaster, c_, beam_b, hb_,
                                     cladding_kg_m, gate_leaf_kg, gate_leaf_width, wind_kmh, gate_solidity,
                                     seismic_c, base_depth, stirrup_beam, Ec, decs, sups,
                                     top_ends_h, top_crown_h, tymp_kg_m2, cornisa_kg_m, tymp_t, pilaster_depth,
                                     liga)
                    break
                except ValueError as e:
                    ultimo = e
                    decs.append(f"Núcleo {c_ * 100:.0f} / trabe {beam_b * 100:.0f}x{hb_ * 100:.0f}: {e}")
                    sups.clear()
            if r is not None:
                break
        if r is None:
            raise ValueError(f"Ningún núcleo/trabe de los probados da: {ultimo}")
        core_ = r["nucleo"]
        fcz = fc_footing or fc
        rc = r["reacciones"]
        for (p_t, e_m) in (extra_loads or []):
            rc["V_serv_t"] = _r(rc["V_serv_t"] + p_t)
            rc["M_in_D_tm"] = _r(rc["M_in_D_tm"] + p_t * e_m)
            rc["M_in_serv_tm"] = _r(rc["M_in_serv_tm"] + p_t * e_m)
            decs.append(f"La zapata Z-1 recibe además {p_t:.2f} t con {e_m:.2f} m de excentricidad "
                        f"(primera pilastra de la barda).")
        combos = [(rc["M_in_D_tm"] + rc["M_in_E_tm"], 0.3 * rc["M_out_sismo_tm"]),
                  (rc["M_in_D_tm"] + 0.3 * rc["M_in_E_tm"], max(rc["M_out_sismo_tm"], rc["M_out_viento_tm"]))]
        sens = []
        elegido: dict[str, Any] = {}
        for q in sorted({3.0, 5.0, 7.5, 10.0, 15.0, float(allowable_bearing)}):
            try:
                dim = tamano_zapata(rc["V_serv_t"], combos, q, depth, soil_unit_weight, core_)
                sens.append({"q_t_m2": q, "B": dim["B"], "L": dim["L"], "h": dim["h"],
                             "q_max_t_m2": dim["q_max"], "contacto": dim["contacto"]})
            except ValueError:
                dim = None
                sens.append({"q_t_m2": q, "B": None, "L": None, "h": None, "q_max_t_m2": None, "contacto": None})
            if abs(q - allowable_bearing) < 1e-9:
                elegido = dim
        if not elegido:
            raise ValueError("Con ese suelo no basta una zapata de 5 m: hay que reducir los momentos o "
                             "mejorar el suelo.")
        mx, my = elegido["momentos"]
        zr = zap.design_footing(
            kind="aislada", dead_load=rc["V_serv_t"], live_load=0.0, allowable_bearing=1000.0, fc=fcz,
            depth=depth, column=[core_, core_], soil_unit_weight=soil_unit_weight, fy=fy, code="NTC",
            moment_x=mx, moment_y=my, tie_beam=False, width=elegido["B"], length=elegido["L"],
            column_bar=r["pilastra"]["bars"]["bar"], column_bar_count=r["pilastra"]["bars"]["count"],
            mark="Z-1")
        zr["checks"].pop("capacidad", None)
        zr["checks_suelo"] = {"q_adm_t_m2": allowable_bearing, "q_max_t_m2": elegido["q_max"],
                              "contacto": elegido["contacto"], "ok": True,
                              "ref": "Contacto real sin tensión; sismo 100% + 30%; capacidad bruta del E.M.S."}
        zr["ok"] = all(v.get("ok") for v in zr["checks"].values())
        zr["warnings"] = [w for w in zr["warnings"] if "mínima sale negativa" not in w]
        r["zapata"] = zr
        r["zapata_sensibilidad"] = sens
        r["decisions"] = decs
        r["supuestos"] = sups
        # ---- indice de costo para comparar: concreto (m3) + acero de lo que cambia (kg) / 110
        kgm = lambda b_: zap.VARILLAS[b_][2]
        conc = 2 * zr["B"] * zr["L"] * zr["h"]
        acero = 2 * (zr["bars_x"]["count"] * (zr["B"] - 0.15) * kgm(zr["bars_x"]["bar"])
                     + zr["bars_y"]["count"] * (zr["L"] - 0.15) * kgm(zr["bars_y"]["bar"]))
        if liga:
            lg = r["liga"]
            n_l = max(4, math.ceil(lg["As_req_cm2"] / zap.VARILLAS["#4"][1]))
            L_l = r["geometria"]["L_ejes"]
            lg.update({"b": 0.25, "h": 0.30, "bars": {"count": n_l, "bar": "#4"}, "length": _r(L_l),
                       "stirrup": "#2", "stirrup_spacing": 0.20})
            conc += 0.25 * 0.30 * L_l
            acero += n_l * kgm("#4") * (L_l + 0.6) + (L_l / 0.20) * 1.10 * kgm("#2")
        vg = r["viga"]["zona_apoyos"]
        acero += (vg["top"]["count"] * kgm(vg["top"]["bar"]) + vg["bottom"]["count"] * kgm(vg["bottom"]["bar"])) * 5.2
        acero += 2 * r["pilastra"]["bars"]["count"] * kgm(r["pilastra"]["bars"]["bar"]) * 5.3
        r["indice"] = {"concreto_m3": _r(conc), "acero_kg": _r(acero, 0), "valor": _r(conc + acero / 110.0)}
        return r

    opciones = {"sin liga (zapatas empotradas)": una(False), "con trabe de liga enterrada": una(True)}
    for nombre, o in opciones.items():
        i = o["indice"]
        z_ = o["zapata"]
        opciones[nombre]["_txt"] = (f"{nombre}: Z-1 {z_['B']:.1f} x {z_['L']:.1f} x {z_['h']:.2f}, "
                                    f"TC-1 {o['viga']['zona_apoyos']['top']['text']} sup. / "
                                    f"{o['viga']['zona_apoyos']['bottom']['text']} inf., "
                                    f"{i['concreto_m3']:.2f} m³ de concreto y {i['acero_kg']:.0f} kg de acero (cimentación, trabe y pilastras)")
    simple, con_liga = "sin liga (zapatas empotradas)", "con trabe de liga enterrada"
    # la opcion con trabe de liga solo gana si ahorra mas de 5 %: es una pieza mas que ejecutar y que dejar
    # enterrada bajo el paso de vehiculos
    ganadora = con_liga if opciones[con_liga]["indice"]["valor"] < 0.95 * opciones[simple]["indice"]["valor"] else simple
    r = opciones[ganadora]
    r["decisions"] = [o["_txt"] for o in opciones.values()] +         [f"Se eligió la opción '{ganadora}' (menor concreto + acero, con 1 m³ de concreto = 110 kg de acero como equivalencia de costo; la liga solo se elige si ahorra más de 5 %)."]         + r["decisions"]
    r["opciones"] = {k: o["indice"] for k, o in opciones.items()}
    return r


def _disenar_con(S, spring_h, crown_h, fc, fy, P, core, bb, hb_, cladding_kg_m, gate_leaf_kg,
                 gate_leaf_width, wind_kmh, solidity, c_sis, base_depth, stirrup, Ec,
                 decisions, supuestos, top_ends_h, top_crown_h, tymp_kg_m2, cornisa_kg_m, tymp_t, Pd, liga=False):
    geo = geometria_arco(S, spring_h, crown_h, P, hb_, top_ends_h, top_crown_h)
    L = geo["L_ejes"]
    Lh = S / 2.0
    Ac, Ic = core * core, core ** 4 / 12.0
    Ab, Ib = bb * hb_, bb * hb_ ** 3 / 12.0
    # ---- cargas (kg, m)
    peso_trabe = bb * hb_ * 2400.0
    forro = cladding_kg_m
    if cladding_kg_m <= 0:
        # block hueco 10 cm a cada cara de la trabe (130 kg/m² de muro) + aplanado 2 cm
        # en las 4 caras (1900 kg/m³)
        # el aro de acento (0.36 m) es un relieve de mortero de 5 cm a cada cara + aplanado del intrados
        forro = 2 * 0.36 * 0.05 * 1900.0 + bb * 0.02 * 1900.0
        supuestos.append(f"Aro de acento: relieve de mortero de 5 cm a cada cara = {forro:.0f} kg/m "
                         f"de arco (más los {peso_trabe:.0f} de la trabe, que va embebida en el frontón).")
    w_d = peso_trabe + forro
    marco = _marco(geo, base_depth, Ec, Ac, Ic, Ab, Ib)
    nodos = marco["nodos"]
    trib = {i: 0.0 for i in range(len(nodos))}
    for (i, j, E, A, I, tipo) in marco["elems"]:
        if tipo == "arco":
            l = math.hypot(nodos[j][0] - nodos[i][0], nodos[j][1] - nodos[i][1])
            trib[i] += l / 2.0
            trib[j] += l / 2.0
    # fronton: muro de block sobre la trabe hasta la cornisa
    supuestos.append(f"Frontón: muro de {tymp_t * 100:.0f} cm (doble hoja de block 10x20x40, celdas rellenas) "
                     f"+ aplanado = {tymp_kg_m2:.0f} kg/m² y cornisa/teja {cornisa_kg_m:.0f} kg/m; "
                     f"sube de los remates ({geo['top_ends_h']:.2f} m) a la clave ({geo['top_crown_h']:.2f} m).")
    arco_ids = marco["arco"]
    w_tymp: dict[int, float] = {}
    area_tymp = 0.0
    for idx in range(1, len(arco_ids) - 1):
        k = arco_ids[idx]
        x = nodos[k][0]
        dx = (nodos[arco_ids[idx + 1]][0] - nodos[arco_ids[idx - 1]][0]) / 2.0
        if abs(x) <= Lh:
            ht = max(y_top(geo, x) - y_extrados(geo, x), 0.0)
            w_tymp[k] = (tymp_kg_m2 * ht + cornisa_kg_m) * dx
            area_tymp += ht * dx
    peso_tymp = sum(w_tymp.values())
    w_col = core ** 2 * 2400.0 + 2 * (P + Pd - 0.20) * 130.0 + 2 * (P + Pd) * 0.02 * 1900.0
    supuestos.append(f"Pilastra: núcleo de concreto {core * 100:.0f}x{core * 100:.0f} cm dentro de una caja de "
                     f"block hueco 10 cm con cámara hueca y aplanado = {w_col:.0f} kg/m "
                     f"({P * 100:.0f} x {Pd * 100:.0f} cm terminada, {P * 100:.0f} sobre la línea del portón).")
    hoja_ancho = gate_leaf_width or S / 2.0
    gate_h_lado = spring_h - 0.45                              # en la foto la hoja queda 45 cm abajo del arranque
    hoja_alto = gate_h_lado + 0.20                             # altura media con el remate arqueado
    y_b_inf, y_b_sup = 0.40, gate_h_lado - 0.30
    sep_bisagras = y_b_sup - y_b_inf
    supuestos.append(f"Hoja del portón: {gate_leaf_kg:.0f} kg cada una ({hoja_ancho:.2f} x {hoja_alto:.2f} m), "
                     f"bisagras a {y_b_inf:.2f} y {y_b_sup:.2f} m (dato del herrero: confirmar).")

    def nodo_cercano(y, lado):
        x0 = -L / 2.0 if lado < 0 else L / 2.0
        return min(range(len(nodos)), key=lambda k: abs(nodos[k][0] - x0) + abs(nodos[k][1] - y))
    carga_d: dict[int, list[float]] = {}
    carga_e: dict[int, list[float]] = {}
    masas: list[tuple[float, float]] = []                              # (kg, y) de la mitad izquierda -> ambas simétricas

    def sumar(dic, k, fx, fy, mz=0.0):
        a = dic.setdefault(k, [0.0, 0.0, 0.0])
        a[0] += fx; a[1] += fy; a[2] += mz
    for k, t in trib.items():
        if t > 0:
            w = w_d * t + w_tymp.get(k, 0.0)
            sumar(carga_d, k, 0.0, -w)
            sumar(carga_e, k, c_sis * w, 0.0)
            masas.append((w, nodos[k][1]))
    for ids in (marco["izq"], marco["der"]):
        for a, b in zip(ids[:-1], ids[1:]):
            l = abs(nodos[b][1] - nodos[a][1])
            for k in (a, b):
                sumar(carga_d, k, 0.0, -w_col * l / 2.0)
                sumar(carga_e, k, c_sis * w_col * l / 2.0, 0.0)
    for lado in (-1, 1):
        kinf, ksup = nodo_cercano(y_b_inf, lado), nodo_cercano(y_b_sup, lado)
        sumar(carga_d, kinf, 0.0, -gate_leaf_kg)
        F = gate_leaf_kg * (hoja_ancho / 2.0) / sep_bisagras
        sumar(carga_d, ksup, -lado * F, 0.0)
        sumar(carga_d, kinf, lado * F, 0.0)
        sumar(carga_e, kinf, c_sis * gate_leaf_kg, 0.0)
    cargas_d = {k: tuple(v) for k, v in carga_d.items()}
    cargas_e = {k: tuple(v) for k, v in carga_e.items()}
    res = {}
    bases = ("articulada",) if liga else ("empotrada", "articulada")
    for base in bases:
        res[base] = {"D": _resolver(marco, cargas_d, base), "E": _resolver(marco, cargas_e, base),
                     "Eneg": _resolver(marco, {k: (-v[0], v[1], v[2]) for k, v in cargas_e.items()}, base)}
    envs = []
    for base in res:
        d_, e_, en_ = res[base]["D"], res[base]["E"], res[base]["Eneg"]
        envs.append(_combinar([d_], [1.3], marco))
        envs.append(_combinar([d_, e_], [1.1, 1.1], marco))
        envs.append(_combinar([d_, en_], [1.1, 1.1], marco))
    arco_Mmax = max(e["arco_Mmax"] for e in envs)
    arco_Mmin = min(e["arco_Mmin"] for e in envs)
    arco_V = max(e["arco_V"] for e in envs)
    arco_N = max(e["arco_N"] for e in envs)
    m_a, m_b = abs(arco_Mmax) / 1000.0, abs(arco_Mmin) / 1000.0
    viga = est.design_beam(bb, hb_, m_a, m_b, arco_V / 1000.0, fc, fy,
                           cover=0.04, stirrup=stirrup, bars=("#4", "#5", "#6", "#8"))
    db_long = zap.VARILLAS[viga["bottom"]["bar"]][0]
    s_ap = min(viga["d"] / 4.0, 8 * db_long, 24 * zap.VARILLAS[stirrup][0], 0.30)
    s_ap = math.floor(s_ap / 0.025 + 1e-9) * 0.025
    viga["stirrups"] = {**viga["stirrups"], "spacing": _r(s_ap, 3), "text": f"E{stirrup} @ {s_ap * 100:.0f}",
                        "zone_length": _r(2 * hb_, 2),
                        "note": "zona de apoyos 2h: s ≤ min(d/4, 8db, 24dest, 30 cm) (ACI 318-19 18.4.2.4)"}
    viga_centro = est.design_beam(bb, hb_, m_a, m_b, 0.25 * arco_V / 1000.0, fc, fy,
                                  cover=0.04, stirrup=stirrup, bars=("#4", "#5", "#6", "#8"))
    # ---- fuera del plano
    q = 0.0048 * 0.85 * wind_kmh ** 2
    supuestos.append(f"Viento: V = {wind_kmh:.0f} km/h (confirmar la zona eólica del sitio), "
                     f"q = {q:.0f} kg/m², Cf muro = 1.3, solidez de la hoja = {solidity:.2f}.")
    supuestos.append(f"Sismo: coeficiente de diseño c = {c_sis:.2f} (zona sísmica alta, ductilidad "
                     f"reducida); se puede bajar si el sitio es de baja sismicidad.")
    p_muro = 1.3 * q
    p_hoja = p_muro * solidity
    F_hoja = p_hoja * hoja_ancho * hoja_alto
    H_pil = geo["top_ends_h"]
    w_pil_v = p_muro * P
    # cara del arco + fronton entre las pilastras
    n_int = 80
    xs = [-Lh + 2 * Lh * (k + 0.5) / n_int for k in range(n_int)]
    A_cara = sum(max(y_top(geo, x) - y_intrados(geo, x), 0.0) for x in xs) * (2 * Lh / n_int)
    M_cara = sum(max(y_top(geo, x) - y_intrados(geo, x), 0.0) * (y_top(geo, x) + y_intrados(geo, x)) / 2.0
                 for x in xs) * (2 * Lh / n_int)
    F_cara = p_muro * A_cara / 2.0
    y_cara = M_cara / A_cara
    M_w = (F_hoja / 2.0) * (y_b_inf + y_b_sup) + w_pil_v * H_pil ** 2 / 2.0 + F_cara * y_cara
    W_pil = w_col * H_pil
    W_arco_med = sum(w for w, _ in masas) / 2.0
    y_masas = sum(w * yy for w, yy in masas) / max(sum(w for w, _ in masas), 1e-9)
    M_s_out = c_sis * (W_pil * H_pil / 2.0 + W_arco_med * y_masas
                       + gate_leaf_kg * (y_b_inf + y_b_sup) / 2.0)
    M_out_serv = max(M_w, M_s_out)
    base_ref = "articulada" if liga else "empotrada"
    d_emp = res[base_ref]["D"]
    n_izq = d_emp["reac"][3 * marco["base_izq"] + 1]
    V_serv = n_izq / 1000.0
    if liga:
        M_in_D = M_in_E = 0.0                       # la trabe de liga toma el empuje: la base no recibe momento en el plano
    else:
        M_in_D = abs(res["empotrada"]["D"]["reac"][3 * marco["base_izq"] + 2]) / 1000.0
        M_in_E = abs(res["empotrada"]["E"]["reac"][3 * marco["base_izq"] + 2]) / 1000.0
    M_in_serv = M_in_D + M_in_E
    H_D = abs(d_emp["reac"][3 * marco["base_izq"]]) / 1000.0
    H_E = abs(res[base_ref]["E"]["reac"][3 * marco["base_izq"]]) / 1000.0
    liga_res = None
    if liga:
        Tu = max(1.3 * H_D, 1.1 * (H_D + H_E))                       # t
        as_req = Tu * 1000.0 / (0.9 * fy)                            # cm²
        liga_res = {"Tu_t": _r(Tu), "As_req_cm2": _r(as_req), "H_serv_t": _r(H_D + H_E)}
    col_M_in = max(e["col_M"] for e in envs)
    col_N = max(e["col_N"] for e in envs)
    Pu = max(col_N, 1.3 * n_izq) if col_N else 1.3 * n_izq
    M_out_s = 1.1 * M_s_out / 1000.0
    M_out_w = 1.1 * M_w / 1000.0
    pil = disenar_pilastra(core, core, fc, fy, Pu, [(col_M_in / 1000.0, 0.3 * M_out_s),
                                                    (0.3 * col_M_in / 1000.0, max(M_out_s, M_out_w))], H_pil)
    # castillos y dala de remate del fronton (NTC Mamposteria 5.1)
    cast = zap.dala(tymp_t, fc, fy)
    hmax = max(y_top(geo, x) - y_extrados(geo, x) for x in xs)
    decisions.append(f"Trabe curva {bb * 100:.0f}x{hb_ * 100:.0f} cm: M = {m_a:.2f} / {m_b:.2f} t·m, "
                     f"V = {arco_V / 1000:.2f} t, empuje en la base = "
                     f"{(abs(d_emp['reac'][3 * marco['base_izq']]) / 1000):.2f} t; el frontón pesa "
                     f"{peso_tymp / 1000:.2f} t ({area_tymp:.2f} m² de muro).")
    return {"geometria": geo, "viga": {"zona_apoyos": viga, "zona_centro": viga_centro,
                                       "Mu_pos_tm": _r(m_a), "Mu_neg_tm": _r(m_b), "Vu_t": _r(arco_V / 1000),
                                       "Nu_t": _r(arco_N / 1000), "b": bb, "h": hb_},
            "liga": liga_res, "pilastra": pil, "pilastra_terminada": P, "pilastra_prof": Pd, "nucleo": core,
            "fronton": {"espesor": tymp_t, "area_m2": _r(area_tymp), "peso_t": _r(peso_tymp / 1000),
                        "h_max": _r(hmax), "castillo": {**cast, "size": tymp_t},
                        "dala_remate": {**cast, "size": tymp_t},
                        "castillos_x": [-_r(Lh / 2), _r(Lh / 2)], "kg_m2": tymp_kg_m2,
                        "cornisa_kg_m": cornisa_kg_m},
            "cargas": {"w_trabe_kg_m": _r(w_d, 0), "w_pilastra_kg_m": _r(w_col, 0),
                       "hoja_kg": gate_leaf_kg, "q_viento_kg_m2": _r(q, 0)},
            "fuera_plano": {"M_viento_tm": _r(M_w / 1000), "M_sismo_tm": _r(M_s_out / 1000),
                            "F_hoja_kg": _r(F_hoja, 0)},
            "reacciones": {"V_serv_t": _r(V_serv), "M_in_serv_tm": _r(M_in_serv),
                           "M_in_D_tm": _r(M_in_D), "M_in_E_tm": _r(M_in_E),
                           "M_out_viento_tm": _r(M_w / 1000), "M_out_sismo_tm": _r(M_s_out / 1000),
                           "M_out_serv_tm": _r(M_out_serv / 1000),
                           "H_serv_t": _r(H_D + H_E),
                           "Pu_t": _r(Pu / 1000)}}


# ----------------------------------------------------------- barda

def design_fence(fc: float, allowable_bearing: float, depth: float, soil_unit_weight: float,
                 spacing: float = 3.0, total_h: float = 2.40, wall_h: float = 1.00,
                 pilaster_h: float = 2.50, core: float = 0.20, cladding: float = 0.10,
                 fy: float = 4200.0, wind_kmh: float = 120.0, reja_solidity: float = 0.30,
                 reja_kg_m2: float = 25.0, seismic_c: float = 0.30) -> dict[str, Any]:
    """Barda de block hueco 10x20x40 con pilastras de concreto cada `spacing`
    m (nucleo `core` + forro de block `cladding` a cada cara), muro bajo de
    `wall_h` y reja hasta `total_h`. Dimensiona pilastra (voladizo desde la
    cimentacion, viento o sismo perpendicular al plano), cadenas y la
    cimentacion corrida (contacto real, momento por metro)."""
    for nombre, v in (("fc", fc), ("allowable_bearing", allowable_bearing), ("depth", depth),
                      ("soil_unit_weight", soil_unit_weight)):
        if v is None or v <= 0:
            raise ValueError(f"{nombre} es dato del proyecto: no se supone.")
    P = core + 2 * cladding
    supuestos = [f"Viento V = {wind_kmh:.0f} km/h; reja de solidez {reja_solidity:.2f} y {reja_kg_m2:.0f} kg/m²; "
                 f"sismo c = {seismic_c:.2f} (confirmar con el sitio)."]
    q = 0.0048 * 0.85 * wind_kmh ** 2
    p_muro = 1.3 * q
    p_reja = p_muro * reja_solidity
    h_reja = total_h - wall_h
    # por tramo (una pilastra + su tramo de 'spacing')
    w_muro = 130.0 * wall_h * spacing                               # block hueco 10 cm
    w_cadenas = 2 * 0.10 * 0.20 * 2400.0 * spacing                   # desplante + cerramiento
    w_reja = reja_kg_m2 * h_reja * spacing
    w_pil_m = core ** 2 * 2400.0 + 4 * (P - 0.05) * 130.0 + 4 * P * 0.02 * 1900.0
    w_pil = w_pil_m * pilaster_h
    M_w = spacing * (p_muro * wall_h * wall_h / 2.0 + p_reja * h_reja * (wall_h + h_reja / 2.0)) \

    M_s = seismic_c * (w_muro * wall_h / 2.0 + w_cadenas * wall_h / 2.0 + w_reja * (wall_h + h_reja / 2.0)
                       + w_pil * pilaster_h / 2.0)
    M_serv = max(M_w, M_s)
    V_axial = (w_muro + w_cadenas + w_reja + w_pil) / 1000.0         # t por tramo
    pil = disenar_pilastra(core, core, fc, fy, 1.3 * (w_pil + w_cadenas / 2 + w_reja) , [(0.0, 1.1 * M_serv / 1000.0)],
                           pilaster_h, estribo="#2")
    # cimentacion corrida: contacto en franja de 1 m, momento por metro
    n_m = V_axial / spacing                                          # t/m
    m_m = M_serv / 1000.0 / spacing                                  # t·m/m
    sel = None
    for B in [round(0.40 + 0.05 * k, 2) for k in range(0, 80)]:
        hz = 0.20
        N = n_m + 2.4 * B * hz + soil_unit_weight * (B - 0.10) * max(depth - hz, 0.0)
        e = m_m / N
        qmax = N / B * (1 + 6 * e / B) if e <= B / 6 else 2 * N / (3 * (B / 2 - e)) if e < B / 2 else float("inf")
        if qmax <= allowable_bearing:
            sel = (B, qmax, e)
            break
    if sel is None:
        raise ValueError("La cimentación corrida de la barda no cabe con ese suelo: "
                         "hay que ampliar la zapata o poner contrafuertes.")
    B, qmax, e = sel
    zc = zap.design_footing(kind="corrida", dead_load=n_m, live_load=0.0, allowable_bearing=1000.0,
                            fc=fc, depth=depth, wall_thickness=0.10, wall_material="mamposteria",
                            soil_unit_weight=soil_unit_weight, fy=fy, code="NTC", width=B,
                            grade_beam_height=0.20, mark="ZC-1")
    zc["checks"].pop("capacidad", None)
    zc["checks_suelo"] = {"q_adm_t_m2": allowable_bearing, "q_max_t_m2": _r(qmax), "e_m": _r(e, 3),
                          "ok": True, "ref": "Franja de 1 m, momento de viento/sismo por metro, sin tensión"}
    zc["ok"] = all(v.get("ok") for v in zc["checks"].values())
    cadena = zap.dala(0.10, fc, fy)
    return {"pilastra": pil, "pilastra_terminada": P, "pilastra_prof": P, "nucleo": core, "spacing": spacing,
            "total_h": total_h, "wall_h": wall_h, "pilaster_h": pilaster_h,
            "cimentacion": zc, "cadena": cadena, "supuestos": supuestos,
            "cargas": {"p_muro_kg_m2": _r(p_muro, 0), "p_reja_kg_m2": _r(p_reja, 0),
                       "M_viento_tm": _r(M_w / 1000), "M_sismo_tm": _r(M_s / 1000),
                       "N_t_m": _r(n_m), "M_t_m_m": _r(m_m)}}
