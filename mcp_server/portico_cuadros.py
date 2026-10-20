"""Cuadros del portico y la barda: cantidades de obra, acero y materiales (cemento, arena,
grava, agua). Todo sale de los dicts de diseño y de lo que devolvieron los dibujos.

Las cantidades son NETAS: sin merma ni desperdicio, porque la merma no es un dato del
proyecto (se suma en el precio unitario). Cada formula de abajo se puede revisar.

Dosificacion de referencia (por m³ de mezcla):
  Concreto, metodo del ACI 211.1 con agua de 205 L (revenimiento 7.5-10 cm, grava de 19 mm),
  grava de masa unitaria compactada 1600 kg/m³ y 0.62 m³ por m³ de concreto, densidad relativa
  2.65 de los agregados y 2 % de aire. La resistencia de DISEÑO de la mezcla es la de proyecto
  mas el margen del ACI 318-19 sin historial de la obra (f'c + 8.3 MPa para f'c >= 21 MPa;
  f'c + 7.0 MPa abajo de 21 MPa): f'c 250 -> 32.8 MPa -> a/c = 0.50 -> 410 kg de cemento.
  La relacion a/c sale de interpolar la tabla del ACI 211.1 (sin aire incluido).
  Mortero 1:4 (cemento:arena en volumen suelto): volumen absoluto con cemento de 3.15 de
  densidad y 1440 kg/m³ suelto, arena de 2.65 y 1500 kg/m³ suelta, a/c = 0.85.
  Los volumenes de arena y grava son SUELTOS (los que se piden al proveedor), sin abundamiento.
  Es una referencia: el diseño de mezcla del proveedor o del laboratorio manda.
"""
from __future__ import annotations

import math
from typing import Any

import annotation as ann
import zapatas as zap

KG_M = {k: v[2] for k, v in zap.VARILLAS.items()}

MEZCLAS = {
    # cemento kg, arena m³ suelta, grava m³ suelta, agua L   (por m³ de mezcla colocada)
    "concreto_250": {"nombre": "Concreto f'c = 250 kg/cm²", "cemento": 410.0, "arena": 0.48, "grava": 0.68,
                     "agua": 205.0, "nota": "a/c = 0.50 (f'cr = 32.8 MPa), agua 205 L"},
    "concreto_100": {"nombre": "Concreto pobre f'c = 100 kg/cm² (plantilla)", "cemento": 270.0, "arena": 0.56,
                     "grava": 0.68, "agua": 205.0, "nota": "a/c = 0.76 (f'cr = 16.8 MPa), agua 205 L"},
    "mortero_14": {"nombre": "Mortero cemento-arena 1:4", "cemento": 365.0, "arena": 1.02, "grava": 0.0,
                   "agua": 310.0, "nota": "volumen absoluto, a/c = 0.85"},
}
JUNTA_BLOCK_M3_M2 = 0.0075      # mortero de juntas por m² de muro de block 10x20x40 (junta de 1 cm a cama completa)
CELDA_BLOCK_M3 = 0.0036         # vacio de un block hueco 10x20x40 (45 % del volumen bruto de 0.008 m³)
APLANADO_M3_M2 = 0.02


def _est_len(b: float, h: float, cover: float, db_e: float) -> float:
    """Longitud de un estribo cerrado con ganchos a 135° (6 db, minimo 7.5 cm)."""
    return 2 * (b - 2 * cover) + 2 * (h - 2 * cover) + 2 * max(6 * db_e, 0.075) + 4 * db_e


def cantidades(d: dict[str, Any], f: dict[str, Any], r: dict[str, Any], depth_portico: float,
               depth_barda: float, bays: int = 3) -> dict[str, Any]:
    """r: resultados de los dibujos: trabe, pil1, pil2, fronton_h, dala_len."""
    g, v, fr = d["geometria"], d["viga"], d["fronton"]
    z, zc = d["zapata"], f["cimentacion"]
    P1, Pd = d["pilastra_terminada"], d["pilastra_prof"]
    P2, c1, c2 = f["pilastra_terminada"], d["nucleo"], f["nucleo"]
    Lax = g["L_ejes"] / 2.0
    xo = g["S"] / 2.0 + P1
    sp = f["spacing"]
    items: list[dict[str, Any]] = []
    acero: dict[str, float] = {}
    mezcla: dict[str, float] = {k: 0.0 for k in MEZCLAS}
    bloques = {"area": 0.0}

    def add_acero(bar, m):
        acero[bar] = acero.get(bar, 0.0) + m * KG_M[bar]

    def it(grupo, concepto, unidad, cant, mix=None):
        items.append({"group": grupo, "concept": concepto, "unit": unidad, "qty": round(cant, 2)})
        if mix:
            mezcla[mix] += cant

    # ---------------- cimentación
    B, Lz, hz = z["B"], z["L"], z["h"]
    Bc, hc = zc["B"], zc["h"]
    x_ext = xo + P2 / 2 + sp * (bays - 1) + P2 / 2 + 0.4                # fin del cimiento corrido (por lado)
    L_corrida = 2 * (x_ext - (Lax + B / 2))
    lg = d.get("liga")
    Ltl = (g["L_ejes"] - B) if lg else 0.0
    exc = 2 * (B + 0.6) * (Lz + 0.6) * depth_portico + (Bc + 0.6) * depth_barda * L_corrida
    if lg:
        exc += (lg["b"] + 0.6) * Ltl * 0.60                              # trabe de liga: fondo a 0.60 m
    G = "CIMENTACIÓN"
    it(G, "Excavación a mano en terreno arcilloso (con 30 cm de holgura de trabajo por lado)", "m³", exc)
    it(G, "Plantilla de concreto pobre f'c = 100 kg/cm², e = 5 cm", "m³", 2 * B * Lz * 0.05 + Bc * L_corrida * 0.05,
       mix="concreto_100")
    it(G, f"Concreto f'c = 250 kg/cm² en zapatas Z-1 ({B:.2f} x {Lz:.2f} x {hz:.2f}), 2 piezas", "m³",
       2 * B * Lz * hz, mix="concreto_250")
    it(G, f"Concreto f'c = 250 kg/cm² en cimiento corrido ZC-1 ({Bc:.2f} x {hc:.2f})", "m³", Bc * hc * L_corrida,
       mix="concreto_250")
    it(G, "Cimbra de madera en el contorno de zapatas y cimiento corrido", "m²",
       2 * 2 * (B + Lz) * hz + 2 * L_corrida * hc)
    if lg:
        it(G, f"Concreto f'c = 250 kg/cm² en trabe de liga TL-1 ({lg['b'] * 100:.0f} x {lg['h'] * 100:.0f}), enterrada bajo el piso del acceso",
           "m³", lg["b"] * lg["h"] * Ltl, mix="concreto_250")
        it(G, "Cimbra de las caras de la trabe de liga TL-1", "m²", 2 * lg["h"] * Ltl)
        add_acero(lg["bars"]["bar"], lg["bars"]["count"] * (g["L_ejes"] + 0.6))
        add_acero(lg["stirrup"], math.ceil(Ltl / lg["stirrup_spacing"]) *
                  _est_len(lg["b"], lg["h"], 0.04, zap.VARILLAS[lg["stirrup"]][0]))
    bx, by = z["bars_x"], z["bars_y"]
    add_acero(bx["bar"], 2 * bx["count"] * (B - 0.15))
    add_acero(by["bar"], 2 * by["count"] * (Lz - 0.15))
    bt, bl = zc["bars_x"], zc["bars_y"]
    add_acero(bt["bar"], (L_corrida / bt["spacing"]) * (Bc - 0.15))
    add_acero(bl["bar"], bl["count"] * L_corrida)
    # ---------------- estructura del pórtico
    G = "ESTRUCTURA DEL PÓRTICO"
    H1 = r["pil1"]["height_m"]
    it(G, f"Concreto f'c = 250 kg/cm² en núcleos de pilastra P-1 ({c1 * 100:.0f} x {c1 * 100:.0f}), colado dentro de la caja de block",
       "m³", 2 * c1 * c1 * H1, mix="concreto_250")
    p1 = d["pilastra"]
    add_acero(p1["bars"]["bar"], 2 * p1["bars"]["count"] * r["pil1"]["bar_len_m"])
    add_acero(p1["stirrups"]["bar"], 2 * r["pil1"]["stirrupCount"] *
              _est_len(c1, c1, 0.04, zap.VARILLAS[p1["stirrups"]["bar"]][0]))
    arco = r["trabe"]["arc_length_m"]
    it(G, f"Concreto f'c = 250 kg/cm² en trabe curva TC-1 ({v['b'] * 100:.0f} x {v['h'] * 100:.0f})", "m³",
       v["b"] * v["h"] * arco, mix="concreto_250")
    it(G, "Cimbra curva de madera de la trabe TC-1 (fondo y dos caras)", "m²", arco * (v["b"] + 2 * v["h"]))
    ab = v["zona_apoyos"]
    add_acero(ab["top"]["bar"], ab["top"]["count"] * r["trabe"]["bar_len_sup_m"])
    add_acero(ab["bottom"]["bar"], ab["bottom"]["count"] * r["trabe"]["bar_len_inf_m"])
    add_acero(ab["stirrups"]["bar"], r["trabe"]["stirrups"] *
              _est_len(v["b"], v["h"], 0.04, zap.VARILLAS[ab["stirrups"]["bar"]][0]))
    cast = fr["castillo"]
    t = fr["espesor"]
    hk, Ld = r["fronton_h"], r["dala_len"]
    it(G, f"Concreto f'c = 250 kg/cm² en castillos K-1 ({t * 100:.0f} x {t * 100:.0f}), 2 piezas", "m³",
       2 * t * t * hk, mix="concreto_250")
    it(G, f"Concreto f'c = 250 kg/cm² en dala de remate DR-1 ({t * 100:.0f} x {t * 100:.0f})", "m³", t * t * Ld,
       mix="concreto_250")
    it(G, "Cimbra de castillos K-1 y dala DR-1 (caras)", "m²", 2 * 2 * t * hk + Ld * 3 * t)
    se = zap.VARILLAS[cast["stirrup"]][0]
    add_acero(cast["bar"], 2 * cast["bars"] * (hk + 0.50))
    add_acero(cast["stirrup"], 2 * math.ceil(hk / cast["spacing"]) * _est_len(t, t, 0.02, se))
    add_acero(cast["bar"], cast["bars"] * (Ld + 0.40))
    add_acero(cast["stirrup"], math.ceil(Ld / cast["spacing"]) * _est_len(t, t, 0.02, se))
    # ---------------- albañilería del pórtico
    G = "ALBAÑILERÍA DEL PÓRTICO"
    a_fr = fr["area_m2"]
    n_blk_fr = a_fr * 2 / (0.40 * 0.20)
    it(G, "Frontón de block hueco 10x20x40 en doble hoja (e = 20 cm)", "m²", a_fr)
    it(G, "Block hueco 10x20x40 del frontón (2 hojas)", "pza", n_blk_fr)
    it(G, "Relleno de las celdas del frontón con mortero 1:4", "m³", n_blk_fr * CELDA_BLOCK_M3, mix="mortero_14")
    bloques["area"] += 2 * a_fr
    per_mid = 2 * (P1 - 0.10 + Pd - 0.10)                              # eje del muro de la caja de block
    a_caja1 = 2 * per_mid * g["top_ends_h"]
    it(G, "Caja de block hueco 10x20x40 de las 2 pilastras P-1", "pza", a_caja1 / (0.40 * 0.20))
    bloques["area"] += a_caja1
    L_aro = r["trabe"]["arc_length_m"]
    it(G, "Relieve de mortero del aro de acento (5 cm de saliente a cada cara, 0.36 m)", "m³",
       2 * 0.36 * 0.05 * L_aro, mix="mortero_14")
    per_ext = 2 * (P1 + Pd)
    it(G, "Forro de piedra aparente en pilastras P-1 (2.40 m de alto, 4 caras)", "m²", 2 * per_ext * 2.40)
    sup_ap = 2 * a_fr + 2 * per_ext * g["top_ends_h"] + L_aro * (2 * 0.36 + 0.20)
    it(G, "Aplanado de mortero e = 2 cm (frontón, pilastras y aro)", "m²", sup_ap)
    it(G, "Cornisa y remates de teja de barro (cornisa + 2 remates de pilastra)", "m", Ld + 2 * 1.60)
    it(G, "Mortero de asiento de la teja (cama de 3 cm por 30 cm de ancho)", "m³", (Ld + 2 * 1.60) * 0.30 * 0.03,
       mix="mortero_14")
    # ---------------- barda
    G = "BARDA (TRAMO DIBUJADO)"
    L_muro = 2 * (bays - 1) * (sp - P2)
    a_muro = L_muro * f["wall_h"]
    it(G, f"Muro bajo de block hueco 10x20x40, h = {f['wall_h']:.2f} m", "m²", a_muro)
    it(G, "Block hueco 10x20x40 en el muro bajo", "pza", a_muro / (0.40 * 0.20))
    bloques["area"] += a_muro
    cad = f["cadena"]
    it(G, "Concreto f'c = 250 kg/cm² en cadena de desplante y dala de cerramiento (10 x 20)", "m³",
       2 * 0.10 * 0.20 * L_muro, mix="concreto_250")
    add_acero(cad["bar"], 2 * cad["bars"] * (L_muro + 0.8))
    add_acero(cad["stirrup"], 2 * math.ceil(L_muro / cad["spacing"]) *
              _est_len(0.10, 0.20, 0.02, zap.VARILLAS[cad["stirrup"]][0]))
    n_p2 = 2 * bays
    H2 = r["pil2"]["height_m"]
    it(G, f"Concreto f'c = 250 kg/cm² en núcleos de pilastra P-2 ({c2 * 100:.0f} x {c2 * 100:.0f}), {n_p2} piezas",
       "m³", n_p2 * c2 * c2 * H2, mix="concreto_250")
    p2 = f["pilastra"]
    add_acero(p2["bars"]["bar"], n_p2 * p2["bars"]["count"] * (r["pil2"]["height_m"] + r["pil2"]["pata_m"]))
    add_acero(p2["stirrups"]["bar"], n_p2 * r["pil2"]["stirrupCount"] *
              _est_len(c2, c2, 0.02, zap.VARILLAS[p2["stirrups"]["bar"]][0]))
    a_caja2 = n_p2 * 4 * (P2 - 0.10) * f["pilaster_h"]
    it(G, f"Caja de block hueco 10x20x40 de las {n_p2} pilastras P-2", "pza", a_caja2 / (0.40 * 0.20))
    bloques["area"] += a_caja2
    h_reja = f["total_h"] - f["wall_h"]
    it(G, f"Reja metálica de tubular, h = {h_reja:.2f} m (pintada)", "m²", L_muro * h_reja)
    sup_ap2 = 2 * a_muro + n_p2 * 4 * P2 * f["pilaster_h"]
    it(G, "Aplanado de mortero e = 2 cm en muro bajo y pilastras", "m²", sup_ap2)
    G = "MORTERO DE ALBAÑILERÍA (SUMA)"
    it(G, "Mortero 1:4 en juntas de block (junta de 1 cm a cama completa)", "m³", bloques["area"] * JUNTA_BLOCK_M3_M2,
       mix="mortero_14")
    it(G, "Mortero 1:4 en aplanados (e = 2 cm)", "m³", (sup_ap + sup_ap2) * APLANADO_M3_M2, mix="mortero_14")
    it("HERRERÍA", "Portón de dos hojas con arco y ornamento, 5.00 m de claro (hoja de 400 kg)", "pza", 1)
    G = "ACERO DE REFUERZO"
    for bar, kg in sorted(acero.items(), key=lambda kv: int(kv[0].lstrip("#").split(".")[0])):
        it(G, f"Varilla corrugada {bar}, fy = 4200 kg/cm² (con estribos)", "kg", kg)
    total = sum(acero.values())
    items.append({"group": G, "concept": "TOTAL DE ACERO", "unit": "kg", "qty": round(total, 2), "total": True})
    mat = {"cemento_kg": 0.0, "arena_m3": 0.0, "grava_m3": 0.0, "agua_L": 0.0}
    filas = []
    for k, m in MEZCLAS.items():
        vol = mezcla[k]
        if vol <= 0:
            continue
        fila = {"mezcla": m["nombre"], "vol": vol, "cemento": vol * m["cemento"], "arena": vol * m["arena"],
                "grava": vol * m["grava"], "agua": vol * m["agua"], "nota": m["nota"]}
        filas.append(fila)
        mat["cemento_kg"] += fila["cemento"]
        mat["arena_m3"] += fila["arena"]
        mat["grava_m3"] += fila["grava"]
        mat["agua_L"] += fila["agua"]
    mat["bultos_50kg"] = mat["cemento_kg"] / 50.0
    return {"items": items, "acero_kg": {k: round(v_, 1) for k, v_ in acero.items()}, "acero_total_kg": round(total, 1),
            "L_corrida": round(L_corrida, 2), "L_muro": round(L_muro, 2), "mezclas": filas, "materiales": mat,
            "volumen_concreto_250": round(mezcla["concreto_250"], 2)}


def tabla_cantidades(items: list[dict[str, Any]], x: float, y: float, upm: float, ancho_mm: float = 215.0):
    """Cuadro de cantidades: No. | CONCEPTO | UNIDAD | CANTIDAD."""
    rows = [["No.", "CONCEPTO", "UNIDAD", "CANTIDAD"]]
    grupos: list[int] = []
    totales: list[int] = []
    gnum, k = 0, 0
    ultimo = None
    for i in items:
        if i["group"] != ultimo:
            gnum += 1
            k = 0
            ultimo = i["group"]
            rows.append([i["group"], "", "", ""])
            grupos.append(len(rows) - 1)
        k += 1
        rows.append([f"{gnum}.{k}", i["concept"], i["unit"],
                     f"{i['qty']:,.0f}" if i["unit"] == "pza" else f"{i['qty']:,.2f}"])
        if i.get("total"):
            totales.append(len(rows) - 1)
    w = [14, ancho_mm - 14 - 20 - 26, 20, 26]
    return ann.create_table(x=x, y=y, rows=rows, col_widths=[a * upm for a in w], text_height=0.0, header=True,
                            align=["left", "left", "center", "right"], group_rows=grupos, total_rows=totales,
                            scale=upm)


def tabla_materiales(q: dict[str, Any], x: float, y: float, upm: float):
    """Cuadro de materiales: por mezcla y suma (cemento en kg y bultos de 50 kg, arena y grava
    en m³ sueltos, agua en litros)."""
    rows = [["MEZCLA", "VOLUMEN (m³)", "CEMENTO (kg)", "ARENA (m³)", "GRAVA (m³)", "AGUA (L)"]]
    for m in q["mezclas"]:
        rows.append([m["mezcla"], f"{m['vol']:.2f}", f"{m['cemento']:.0f}", f"{m['arena']:.2f}",
                     f"{m['grava']:.2f}", f"{m['agua']:.0f}"])
    t = q["materiales"]
    rows.append(["TOTAL", "", f"{t['cemento_kg']:.0f}  ({t['bultos_50kg']:.0f} bultos de 50 kg)", f"{t['arena_m3']:.2f}",
                 f"{t['grava_m3']:.2f}", f"{t['agua_L']:.0f}"])
    w = [64, 24, 46, 26, 26, 24]
    return ann.create_table(x=x, y=y, rows=rows, col_widths=[a * upm for a in w], text_height=0.0, header=True,
                            align=["left", "center", "center", "center", "center", "center"],
                            total_rows=[len(rows) - 1], scale=upm,
                            title="MATERIALES DE LAS MEZCLAS (CANTIDADES NETAS, SIN DESPERDICIO)")
