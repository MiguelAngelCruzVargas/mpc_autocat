"""Memoria de cálculo (.md) y libro de cantidades (.xlsx) del pórtico y la barda, DESDE el diseño.

Antes esto lo armaba un script distinto cada vez que cambiaba el diseño, y el resultado dependía de quién lo
escribiera. Acá es una función pura: los mismos `d`, `f` y `q` dan SIEMPRE los mismos dos archivos. Nada se
escribe de memoria: cada número sale de los dicts que devolvieron `design_gate_portal`, `design_fence` y
`portico_cuadros.cantidades`, y lo que no cumple sale con su demanda, su capacidad y la palabra NO CUMPLE.

  d, f: los diseños (design_gate_portal y design_fence).
  q:    lo que devolvió portico_cuadros.cantidades.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import portico_cuadros as pc
import zapatas as zap

CUMPLE, NO_CUMPLE = "CUMPLE", "NO CUMPLE"
ZONA_APOYO_TRABE_M = 1.00        # largo de la zona de apoyo de la trabe curva con estribos a menor separación


def _bool(v: Any) -> bool:
    """Un 'ok' que pasó por json.dump(default=str) llega como el texto 'False': 'False' no es verdadero."""
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "", "none", "no")
    return bool(v)


def _dim(s: dict[str, Any]) -> str:
    return f"{s['B']:.1f} x {s['L']:.1f} m" if s.get("B") else "no cabe en el espacio disponible: requiere anclas a la roca"


def _estribos_trabe(d: dict[str, Any]) -> str:
    v = d["viga"]
    ap, ce = v["zona_apoyos"]["stirrups"], v["zona_centro"]["stirrups"]
    if ap["text"] == ce["text"]:
        return ap["text"]
    return f"{ap['text']} en {ZONA_APOYO_TRABE_M:.2f} m c/extremo; @ {ce['spacing'] * 100:.0f} al centro"


def filas_elementos(d: dict[str, Any], f: dict[str, Any]) -> list[list[str]]:
    """Cuadro de elementos: marca, elemento, b x h (cm), armado longitudinal, estribos, f'c."""
    z, p, v, fr = d["zapata"], d["pilastra"], d["viga"], d["fronton"]
    zc, gb = f["cimentacion"], f["cimentacion"].get("grade_beam") or {}
    fc = f"{z['fc']:.0f}"
    cm = lambda x: f"{x * 100:.0f}"
    ap = v["zona_apoyos"]
    st = p["stirrups"]
    filas = [
        ["P-1", "Pilastra del portón (núcleo)", f"{cm(d['nucleo'])} x {cm(d['nucleo'])}", p["bars"]["text"],
         f"{st['text']}; @ {st['conf_spacing'] * 100:.0f} en {st['conf_length']:.2f} m c/extremo", fc],
        ["TC-1", "Trabe curva del arco", f"{cm(v['b'])} x {cm(v['h'])}",
         f"{ap['top']['text']} sup. + {ap['bottom']['text']} inf.", _estribos_trabe(d), fc],
        ["K-1", "Castillo del frontón (2 pzas)", f"{cm(fr['castillo']['size'])} x {cm(fr['castillo']['size'])}",
         f"{fr['castillo']['bars']} {fr['castillo']['bar']}", f"E{fr['castillo']['stirrup']} @ {fr['castillo']['spacing'] * 100:.0f}", fc],
        ["DR-1", "Dala de remate del frontón", f"{cm(fr['dala_remate']['size'])} x {cm(fr['dala_remate']['size'])}",
         f"{fr['dala_remate']['bars']} {fr['dala_remate']['bar']}", f"E{fr['dala_remate']['stirrup']} @ {fr['dala_remate']['spacing'] * 100:.0f}", fc]]
    filas.append(["Z-1", "Zapata aislada del portón sobre roca (2 pzas)" if z.get("checks_suelo") else "Zapata aislada del portón (2 pzas)",
                  f"{cm(z['B'])} x {cm(z['L'])} x {cm(z['h'])}", f"{z['bars_x']['text']} en ambos sentidos", "—", fc])
    if z.get("pedestal"):
        ped = z["pedestal"]
        t = z.get("pedestal_ties") or {}
        filas.append(["D-1", f"Dado de la zapata Z-1 (2 pzas), h = {z['pedestal_height']:.2f} m", f"{cm(ped[0])} x {cm(ped[1])}",
                      f"las del núcleo de P-1 ({p['bars']['text']})", f"E{t.get('bar', '#3')} @ {t.get('spacing', 0.2) * 100:.0f}", fc])
    lg = d.get("liga")
    if lg:
        filas.append(["TL-1", "Trabe de liga: une P-1 con todas las pilastras" if lg.get("a_lo_largo") else "Trabe de liga entre las zapatas",
                      f"{cm(lg['b'])} x {cm(lg['h'])}", f"{lg['bars']['count']} {lg['bars']['bar']}",
                      f"E{lg['stirrup']} @ {lg['stirrup_spacing'] * 100:.0f}", fc])
    p2 = f["pilastra"]
    filas.append(["P-2", "Pilastra de barda (núcleo)", f"{cm(f['nucleo'])} x {cm(f['nucleo'])}", p2["bars"]["text"], p2["stirrups"]["text"], fc])
    cad = f["cadena"]
    filas.append(["CD / DC", "Cadena de desplante y dala de cerramiento", f"{cm(gb.get('width', 0.10))} x {cm(gb.get('height', 0.20))}",
                  f"{cad['bars']} {cad['bar']}", f"E{cad['stirrup']} @ {cad['spacing'] * 100:.0f}", fc])
    filas.append(["ZC-1", "Cimiento corrido de la barda", f"{cm(zc['B'])} x {cm(zc['h'])}",
                  f"transv. {zc['bars_x']['bar']} @ {zc['bars_x']['spacing'] * 100:.0f} cm; long. {zc['bars_y']['count']} {zc['bars_y']['bar']}",
                  "—", fc])
    return filas


def revision(d: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """Cada revisión de la cimentación y la pilastra: (nombre, demanda, capacidad o requisito, resultado).
    Sale de d['zapata']['checks'], de la pilastra y de la trabe de liga; nada se inventa."""
    z, p, lg = d["zapata"], d["pilastra"], d.get("liga")
    ck = z["checks"]
    r = lambda ok: CUMPLE if _bool(ok) else NO_CUMPLE
    filas: list[tuple[str, str, str, str]] = []
    if "capacidad" in ck:
        c = ck["capacidad"]
        filas.append(("Zapata: presión contra el suelo", f"q máx. {c['q_max_t_m2']:.1f} t/m²",
                      f"admisible efectiva {c['q_adm_efectiva_t_m2']:.1f} t/m²", r(c["ok"])))
    vc = ck.get("volteo_contacto")
    if vc:
        for caso in vc["casos"]:
            filas.append((f"Volteo y contacto, {caso['caso']}",
                          f"q máx. {caso['q_max_t_m2']:.1f} t/m²; contacto {caso['contacto'] * 100:.0f} %",
                          f"roca de referencia {vc['q_adm_t_m2']:.0f} t/m²; contacto mín. {vc['min_contacto'] * 100:.0f} %",
                          r(caso["q_max_t_m2"] <= vc["q_adm_t_m2"] and caso["contacto"] >= vc["min_contacto"])))
    filas.append((f"Pilastra P-1: interacción carga-momento ({p['bars']['text']})", f"{p['ratio']:.2f}", "máximo 0.95", r(p.get("ok", p["ratio"] <= 0.95))))
    for clave, nombre in (("punzonamiento", "punzonamiento"), ("cortante_x", "cortante en X"), ("cortante_y", "cortante en Y")):
        if clave in ck:
            c = ck[clave]
            filas.append((f"Zapata: {nombre}", f"Vu {c['Vu_t']:.1f} t", f"φVc {c['phiVc_t']:.1f} t", r(c["ok"])))
    for clave, nombre in (("flexion_x", "flexión en X"), ("flexion_y", "flexión en Y")):
        if clave in ck:
            c = ck[clave]
            filas.append((f"Zapata: {nombre}", f"As requerido {c['As_req_cm2']:.1f} cm²", f"As colocado {c['As_cm2']:.1f} cm²", r(c["ok"])))
    if "peralte_minimo" in ck:
        c = ck["peralte_minimo"]
        filas.append(("Zapata: peralte efectivo mínimo", f"d = {c['d_m'] * 100:.1f} cm", f"d ≥ {c['min_m'] * 100:.0f} cm (ACI 318-19 13.3.1.2)", r(c["ok"])))
    for clave, nombre in (("desarrollo_x", "desarrollo de la parrilla en X"), ("desarrollo_y", "desarrollo de la parrilla en Y")):
        if clave in ck:
            c = ck[clave]
            filas.append((f"Zapata: {nombre}", f"disponible {c['available_m'] * 100:.0f} cm", f"ld = {min(c['ld_recta_m'], c['ldh_gancho_m']) * 100:.0f} cm", r(c["ok"])))
    if "arranques" in ck:
        c = ck["arranques"]
        filas.append(("Zapata: anclaje de los arranques en la zapata", f"disponible {c['available_m'] * 100:.0f} cm",
                      f"ldc = {c['ldc_m'] * 100:.0f} cm" + (" (continúan por el dado)" if z.get("pedestal") else ""), r(c["ok"])))
    for clave, nombre in (("aplastamiento", "aplastamiento columna-zapata"), ("aplastamiento_dado", "aplastamiento columna-dado")):
        if clave in ck:
            c = ck[clave]
            filas.append((f"Zapata: {nombre}", f"Pu {c['Pu_t']:.1f} t", f"φBn {c['phiBn_t']:.0f} t", r(c["ok"])))
    if lg and lg.get("As_req_cm2") is not None:
        filas.append(("Trabe de liga TL-1: empuje del arco", f"As requerido {lg['As_req_cm2']:.2f} cm²",
                      f"As colocado {lg['As_cm2']:.2f} cm²", r(lg.get("ok", lg["As_cm2"] >= lg["As_req_cm2"]))))
    return filas


def _bases_mezcla() -> list[str]:
    M = pc.MEZCLAS
    c250, c100, mor = M["concreto_250"], M["concreto_100"], M["mortero_14"]
    return [
        f"{c250['nombre']}: {c250['nota']} → {c250['cemento']:.0f} kg de cemento, {c250['agua']:.0f} L de agua, grava {c250['grava']:.2f} m³ y arena {c250['arena']:.2f} m³ sueltos.",
        f"{c100['nombre']}: {c100['nota']} → {c100['cemento']:.0f} kg de cemento.",
        f"{mor['nombre']} (volumen suelto): {mor['cemento']:.0f} kg de cemento, {mor['arena']:.2f} m³ de arena y {mor['agua']:.0f} L de agua por m³, {mor['nota']}.",
        f"Juntas de block 10x20x40 con 1 cm a cama completa: {pc.JUNTA_BLOCK_M3_M2} m³/m²; aplanado de 2 cm: {pc.APLANADO_M3_M2} m³/m²; celdas del block: {pc.CELDA_BLOCK_M3} m³ por pieza.",
        "Arena y grava van en volumen suelto (el que se pide al proveedor). El diseño de mezcla del proveedor o del laboratorio manda sobre esta referencia.",
    ]


def memoria_md(d: dict[str, Any], f: dict[str, Any], q: dict[str, Any], proyecto: str = "pórtico con arco y barda",
               notas_proyecto: Optional[list[str]] = None,
               comparar: Optional[list[tuple[str, dict[str, Any]]]] = None) -> str:
    z, lg, rc, M = d["zapata"], d.get("liga"), d["reacciones"], q["materiales"]
    rev = revision(d)
    fallan = [a for a, _, _, res in rev if res == NO_CUMPLE]
    md = [f"# Memoria de cálculo y cantidades: {proyecto}", "",
          "Cálculo PRELIMINAR con supuestos (ver el último apartado). No sustituye la revisión de un ingeniero estructural ni el estudio de mecánica de suelos.", ""]
    if fallan:
        md += ["> **ATENCIÓN: la cimentación o la pilastra definidas NO CUMPLEN las revisiones siguientes y están SUJETAS A VERIFICACIÓN:** "
               + "; ".join(fallan) + " (ver el apartado 2.1).", ""]
    md += ["## 1. Resultado en una mirada", "",
           f"- Acero total: **{q['acero_total_kg']:.0f} kg** (neto, con estribos y ganchos, sin desperdicio).",
           f"- Concreto f'c = 250 kg/cm²: **{q['volumen_concreto_250']:.2f} m³**.",
           f"- Cemento: **{M['cemento_kg']:.0f} kg ({M['bultos_50kg']:.0f} bultos de 50 kg)**; arena **{M['arena_m3']:.1f} m³**; grava **{M['grava_m3']:.1f} m³**; agua **{M['agua_L'] / 1000:.1f} m³**."]
    for etiqueta, qc in comparar or []:
        md.append(f"- {etiqueta}: acero {qc['acero_total_kg']:.0f} kg, concreto {qc['volumen_concreto_250']:.2f} m³, cemento {qc['materiales']['cemento_kg']:.0f} kg.")
    md += [f"- Zapatas Z-1: **{z['B']:.2f} x {z['L']:.2f} x {z['h']:.2f} m**, parrilla {z['bars_x']['text']} en ambos sentidos"
           + (f", dado de {z['pedestal'][0] * 100:.0f} x {z['pedestal'][1] * 100:.0f} cm y {z['pedestal_height']:.2f} m de alto" if z.get("pedestal") else "")
           + f", desplante {z['depth']:.2f} m.",
           f"- Tramo cuantificado: portón + barda ({q['L_muro']:.1f} m de muro entre pilastras y {q['L_corrida']:.1f} m de cimiento corrido).", "",
           "## 2. Diseño", "",
           "Las secciones se dan como **b x h**: b = ancho y h = peralte (alto), en cm.", "",
           "| Marca | Elemento | Sección b x h (cm) | Armado | Estribos |", "|---|---|---|---|---|"]
    md += [f"| {a} | {b} | {c} | {e} | {g} |" for a, b, c, e, g, _ in filas_elementos(d, f)]
    md += ["", "### Esfuerzos y reacciones", "",
           f"- Trabe curva (factorizados): Mu(+) = {d['viga']['Mu_pos_tm']:.2f} t·m, Mu(−) = {d['viga']['Mu_neg_tm']:.2f} t·m, Vu = {d['viga']['Vu_t']:.2f} t, Nu = {d['viga']['Nu_t']:.2f} t.",
           f"- Frontón: {d['fronton']['area_m2']:.2f} m² de muro, {d['fronton']['peso_t']:.2f} t.",
           f"- Base de cada pilastra (servicio): V = {rc['V_serv_t']:.2f} t; fuera del plano: viento {rc['M_out_viento_tm']:.2f} t·m, sismo {rc['M_out_sismo_tm']:.2f} t·m."]
    if lg and lg.get("Tu_t") is not None:
        md.append(f"- Trabe de liga TL-1: empuje del arco {lg['Tu_t']:.2f} t; As requerido {lg['As_req_cm2']:.2f} cm² contra {lg['As_cm2']:.2f} cm² colocados.")
    md += ["", "### 2.1 Revisión de la cimentación y la pilastra", "",
           "| Revisión | Demanda | Capacidad o requisito | Resultado |", "|---|---|---|---|"]
    md += [f"| {a} | {b} | {c} | **{r}** |" for a, b, c, r in rev]
    sens = d.get("zapata_sensibilidad") or []
    if sens:
        md += ["", "| Capacidad admisible del suelo o roca (t/m²) | Zapata que cumple (B x L) |", "|---|---|"]
        md += [f"| {s['q_t_m2']:.1f} | {_dim(s)} |" for s in sens]
    md += ["", "### Decisiones", ""] + [f"- {t}" for t in d.get("decisions", [])]
    md += ["", "## 3. Cantidades de obra (netas)", "", "| Concepto | Unidad | Cantidad |", "|---|---|---:|"]
    md += [f"| {i['concept']} | {i['unit']} | {i['qty']:,.2f} |" for i in q["items"]]
    md += ["", "## 4. Materiales: cemento, arena, grava y agua", "",
           "| Mezcla | m³ | Cemento (kg) | Arena (m³) | Grava (m³) | Agua (L) |", "|---|---:|---:|---:|---:|---:|"]
    md += [f"| {m['mezcla']} | {m['vol']:.2f} | {m['cemento']:.0f} | {m['arena']:.2f} | {m['grava']:.2f} | {m['agua']:.0f} |" for m in q["mezclas"]]
    md += [f"| **TOTAL** | | **{M['cemento_kg']:.0f}** ({M['bultos_50kg']:.0f} bultos) | **{M['arena_m3']:.2f}** | **{M['grava_m3']:.2f}** | **{M['agua_L']:.0f}** |",
           "", "Base de las dosificaciones (por m³ de mezcla colocada):", ""] + [f"- {t}" for t in _bases_mezcla()]
    md += ["", "## 5. Supuestos y datos por confirmar", ""]
    md += [f"- {t}" for t in d.get("supuestos", [])] + [f"- {t}" for t in f.get("supuestos", [])]
    cs = z.get("checks_suelo")
    if cs:
        md.append(f"- Capacidad de carga de referencia del suelo o roca: {cs['q_adm_t_m2']:.0f} t/m². No hay estudio de mecánica de suelos: confirmar antes de colar.")
    md += [f"- {t}" for t in (notas_proyecto or [])]
    md.append("- No incluye: desperdicio, pintura, mano de obra, ni la herrería del portón (solo se cuenta la pieza).")
    return "\n".join(md) + "\n"


# ---------------------------------------------------------------------------------------------------- Excel

def excel(d: dict[str, Any], f: dict[str, Any], q: dict[str, Any], path: str, proyecto: str = "") -> str:
    """Libro de cantidades: Elementos, Cantidades (P.U. en celdas amarillas, importe y total formulados),
    Acero, Materiales, Diseño, Revisión, Supuestos."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    azul = PatternFill("solid", fgColor="1F3864")
    amarillo = PatternFill("solid", fgColor="FFF2CC")
    rojo = Font(bold=True, color="C00000")
    wb = openpyxl.Workbook()

    def encabezado(ws, fila, textos):
        for c, t in enumerate(textos, start=1):
            cel = ws.cell(fila, c, t)
            cel.font = Font(bold=True, color="FFFFFF")
            cel.fill = azul
            cel.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def anchos(ws, valores):
        for i, w in enumerate(valores):
            ws.column_dimensions[chr(ord("A") + i)].width = w

    # --- Elementos
    ws = wb.active
    ws.title = "Elementos"
    encabezado(ws, 1, ["MARCA", "ELEMENTO", "SECCIÓN b x h (cm)", "ARMADO LONGITUDINAL", "ESTRIBOS", "f'c (kg/cm²)"])
    for r, fila in enumerate(filas_elementos(d, f), start=2):
        for c, v in enumerate(fila, start=1):
            ws.cell(r, c, int(v) if c == 6 else v)
    ws.cell(len(filas_elementos(d, f)) + 3, 1, "b = ancho de la sección; h = peralte (alto). Las dimensiones se leen siempre ancho x alto.")
    anchos(ws, [10, 52, 20, 34, 54, 12])

    # --- Cantidades
    ws = wb.create_sheet("Cantidades")
    ws["A1"] = ("BARDA PERIMETRAL Y PÓRTICO DE ACCESO" + (f" · {proyecto.upper()}" if proyecto else "")).strip()
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "Cantidades NETAS (sin desperdicio) del tramo dibujado. Llene el P.U. (celdas amarillas): el importe, los subtotales y el total se calculan solos."
    encabezado(ws, 4, ["No.", "PARTIDA", "CONCEPTO", "UNIDAD", "CANTIDAD", "P.U. ($)", "IMPORTE ($)"])
    grupos: list[str] = []
    fila, n = 5, 0
    for it in (i for i in q["items"] if not i["concept"].startswith("TOTAL DE ACERO")):
        if it["group"] not in grupos:
            grupos.append(it["group"])
            n = 0
        n += 1
        ws.cell(fila, 1, f"{grupos.index(it['group']) + 1}.{n}")
        ws.cell(fila, 2, it["group"])
        c = ws.cell(fila, 3, it["concept"])
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(fila, 4, it["unit"])
        ws.cell(fila, 5, it["qty"]).number_format = "#,##0.00"
        ws.cell(fila, 6).fill = amarillo
        ws.cell(fila, 6).number_format = "#,##0.00"
        ws.cell(fila, 7, f"=E{fila}*F{fila}").number_format = "#,##0.00"
        fila += 1
    ult = fila - 1
    fila += 1
    ws.cell(fila, 3, "SUBTOTAL").font = Font(bold=True)
    ws.cell(fila, 7, f"=SUM(G5:G{ult})").number_format = "#,##0.00"
    ws.cell(fila + 1, 3, "IVA (%)").font = Font(bold=True)
    ws.cell(fila + 1, 5, 16).fill = amarillo
    ws.cell(fila + 1, 7, f"=G{fila}*E{fila + 1}/100").number_format = "#,##0.00"
    ws.cell(fila + 2, 3, "TOTAL").font = Font(bold=True)
    ws.cell(fila + 2, 7, f"=G{fila}+G{fila + 1}").number_format = "#,##0.00"
    ws.cell(fila + 2, 7).font = Font(bold=True)
    ws.freeze_panes = "A5"
    anchos(ws, [7, 30, 88, 9, 13, 13, 16])

    # --- Acero
    ws = wb.create_sheet("Acero")
    encabezado(ws, 1, ["VARILLA", "PESO (kg/m)", "LONGITUD (m)", "PESO (kg)", "VARILLAS DE 12 m"])
    barras = sorted(q["acero_kg"], key=lambda b: float(b.lstrip("#")))
    for r, b in enumerate(barras, start=2):
        ws.cell(r, 1, b)
        ws.cell(r, 2, zap.VARILLAS[b][2])
        ws.cell(r, 3, f"=D{r}/B{r}").number_format = "#,##0.0"
        ws.cell(r, 4, q["acero_kg"][b]).number_format = "#,##0.0"
        ws.cell(r, 5, f"=ROUNDUP(C{r}/12,0)")
    t = len(barras) + 2
    ws.cell(t, 1, "TOTAL").font = Font(bold=True)
    ws.cell(t, 4, f"=SUM(D2:D{t - 1})").number_format = "#,##0.0"
    ws.cell(t + 2, 1, "Peso NETO con estribos y ganchos; las varillas de 12 m son para compra (sin traslapes ni desperdicio de corte).")
    anchos(ws, [14, 14, 16, 14, 18])

    # --- Materiales
    ws = wb.create_sheet("Materiales")
    encabezado(ws, 1, ["MEZCLA", "VOLUMEN (m³)", "CEMENTO kg/m³", "ARENA m³/m³", "GRAVA m³/m³", "AGUA L/m³",
                       "CEMENTO (kg)", "ARENA (m³)", "GRAVA (m³)", "AGUA (L)"])
    for r, m in enumerate(q["mezclas"], start=2):
        v = m["vol"] or 1.0
        ws.cell(r, 1, m["mezcla"])
        ws.cell(r, 2, round(m["vol"], 3))
        for c, k in zip((3, 4, 5, 6), ("cemento", "arena", "grava", "agua")):
            cel = ws.cell(r, c, round(m[k] / v, 3))
            cel.fill = amarillo
        for c, col in zip((7, 8, 9, 10), "CDEF"):
            ws.cell(r, c, f"=B{r}*{col}{r}")
    t = len(q["mezclas"]) + 2
    ws.cell(t, 1, "TOTAL").font = Font(bold=True)
    ws.cell(t, 2, f"=SUM(B2:B{t - 1})")
    for c, col in zip((7, 8, 9, 10), "GHIJ"):
        ws.cell(t, c, f"=SUM({col}2:{col}{t - 1})")
    ws.cell(t + 1, 1, "Bultos de cemento de 50 kg")
    ws.cell(t + 1, 7, f"=ROUNDUP(G{t}/50,0)")
    ws.cell(t + 3, 1, "Dosificación de referencia (celdas amarillas, se pueden cambiar con la mezcla de su proveedor):")
    for k, tx in enumerate(_bases_mezcla()):
        ws.cell(t + 4 + k, 1, "· " + tx)
    anchos(ws, [44, 14, 14, 14, 14, 12, 16, 14, 14, 14])

    # --- Diseño: los esfuerzos y reacciones que salieron del cálculo
    ws = wb.create_sheet("Diseño")
    v, rc, p, z, lg = d["viga"], d["reacciones"], d["pilastra"], d["zapata"], d.get("liga")
    filas_d = [("TRABE CURVA TC-1", None, None),
               ("Momento positivo factorizado Mu(+)", v["Mu_pos_tm"], "t·m"), ("Momento negativo factorizado Mu(−)", v["Mu_neg_tm"], "t·m"),
               ("Cortante factorizado Vu", v["Vu_t"], "t"), ("Fuerza axial Nu", v["Nu_t"], "t"),
               ("FRONTÓN", None, None), ("Área de muro", d["fronton"]["area_m2"], "m²"), ("Peso", d["fronton"]["peso_t"], "t"),
               ("PILASTRA P-1 (BASE, SERVICIO)", None, None),
               ("Carga vertical por pilastra", rc["V_serv_t"], "t"),
               ("Momento fuera del plano, viento", rc["M_out_viento_tm"], "t·m"),
               ("Momento fuera del plano, sismo", rc["M_out_sismo_tm"], "t·m"),
               (f"Interacción P-M con {p['bars']['text']} (máx. 0.95)", p["ratio"], CUMPLE if _bool(p.get("ok", True)) else NO_CUMPLE),
               ("ZAPATA Z-1", None, None),
               ("Dimensiones B x L x h", f"{z['B']:.2f} x {z['L']:.2f} x {z['h']:.2f}", "m"),
               ("Desplante", z["depth"], "m"), ("Parrilla", z["bars_x"]["text"], "ambos sentidos")]
    if z.get("checks_suelo"):
        filas_d.append(("Presión máxima contra el suelo o roca", z["checks_suelo"]["q_max_t_m2"], "t/m²"))
        filas_d.append(("Capacidad de referencia", z["checks_suelo"]["q_adm_t_m2"], "t/m² (sin estudio de mecánica de suelos)"))
    if lg and lg.get("As_req_cm2") is not None:
        filas_d += [("TRABE DE LIGA TL-1", None, None), ("As requerido", lg["As_req_cm2"], "cm²"), ("As colocado", lg["As_cm2"], "cm²")]
    for r, (a, b, c) in enumerate(filas_d, start=1):
        ws.cell(r, 1, a)
        if b is None:
            ws.cell(r, 1).font = Font(bold=True)
        else:
            ws.cell(r, 2, b)
            ws.cell(r, 3, c)
    anchos(ws, [62, 22, 40])

    # --- Revisión
    ws = wb.create_sheet("Revisión")
    encabezado(ws, 1, ["REVISIÓN", "DEMANDA", "CAPACIDAD O REQUISITO", "RESULTADO"])
    for r, (a, b, c, res) in enumerate(revision(d), start=2):
        for col, v in enumerate((a, b, c, res), start=1):
            ws.cell(r, col, v)
        if res == NO_CUMPLE:
            ws.cell(r, 4).font = rojo
    anchos(ws, [60, 40, 56, 14])

    # --- Supuestos
    ws = wb.create_sheet("Supuestos")
    ws["A1"] = "DATOS QUE FALTAN CONFIRMAR (el cálculo usó estos valores)"
    ws["A1"].font = Font(bold=True)
    r = 3
    for tx in list(d.get("supuestos", [])) + list(f.get("supuestos", [])):
        ws.cell(r, 1, "· " + tx)
        r += 1
    cs = d["zapata"].get("checks_suelo")
    if cs:
        ws.cell(r, 1, f"· Capacidad de referencia del suelo o roca: {cs['q_adm_t_m2']:.0f} t/m² (sin estudio de mecánica de suelos: confirmar).")
        r += 1
    ws.cell(r, 1, "· Cálculo preliminar: no sustituye la revisión de un ingeniero estructural.")
    anchos(ws, [150])
    wb.save(path)
    return path


def exportar(design_path: str, quantities_path: str, out_dir: str, proyecto: str = "",
             notas_proyecto: Optional[list[str]] = None,
             comparar: Optional[dict[str, str]] = None) -> dict[str, Any]:
    """Lee el diseño ({"d":..., "f":...}) y las cantidades que dejaron los scripts o las tools, y escribe
    'Memoria de calculo.md' y 'Calculos y cantidades.xlsx' en out_dir. Devuelve las rutas, un resumen y
    la lista de revisiones que NO CUMPLEN."""
    with open(design_path, encoding="utf-8") as fh:
        bundle = json.load(fh)
    with open(quantities_path, encoding="utf-8") as fh:
        q = json.load(fh)
    d, f = bundle["d"], bundle["f"]
    ref: list[tuple[str, dict[str, Any]]] = []
    for etiqueta, ruta in (comparar or {}).items():
        with open(ruta, encoding="utf-8") as fh:
            ref.append((etiqueta, json.load(fh)))
    os.makedirs(out_dir, exist_ok=True)
    ruta_md = os.path.join(out_dir, "Memoria de calculo.md")
    ruta_xlsx = os.path.join(out_dir, "Calculos y cantidades.xlsx")
    with open(ruta_md, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(memoria_md(d, f, q, proyecto or "pórtico con arco y barda", notas_proyecto, ref))
    excel(d, f, q, ruta_xlsx, proyecto)
    rev = revision(d)
    return {"memoria": ruta_md, "excel": ruta_xlsx, "revisiones": len(rev),
            "no_cumplen": [a for a, _, _, res in rev if res == NO_CUMPLE],
            "acero_kg": q["acero_total_kg"], "concreto_250_m3": q["volumen_concreto_250"],
            "cemento_kg": q["materiales"]["cemento_kg"]}
