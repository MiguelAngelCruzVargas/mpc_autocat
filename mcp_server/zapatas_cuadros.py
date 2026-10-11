"""Cuadros de una zapata: el cuadro de zapatas, la revisión estructural con
su referencia de norma, las especificaciones y la cuantificación.

Todo sale del dict de zapatas.design_footing: los números del cuadro son los
mismos que dimensionaron el armado, no se vuelven a escribir.
"""
from __future__ import annotations

from typing import Any, Optional

import annotation as ann_mod
import autocad_client as acad
import quantities as q_mod
import zapatas


def _ok(c: dict[str, Any]) -> str:
    return "CUMPLE" if c.get("ok") else "NO CUMPLE"


def check_rows(z: dict[str, Any]) -> list[list[str]]:
    """Las revisiones del diseño como filas de cuadro: lo que el revisor de
    la licencia quiere ver junto al armado."""
    c = z["checks"]
    filas = [["REVISIÓN", "ACTUANTE", "RESISTENTE / LÍMITE", "", "REFERENCIA"]]

    def fila(nombre, act, res, chk, ref):
        filas.append([nombre, act, res, _ok(chk), ref])

    if "capacidad" in c:
        k = c["capacidad"]
        q = k.get("q_max_t_m2", k.get("q_t_m2"))
        fila("Presión en el suelo (servicio)", f"{q:.2f} t/m²",
             f"{k['q_adm_efectiva_t_m2']:.2f} t/m²", k, "E.M.S.; ACI 13.3.1.1")
    for clave, nombre in (("punzonamiento", "Punzonamiento"),
                          ("punzonamiento_col1", "Punzonamiento col. 1"),
                          ("punzonamiento_col2", "Punzonamiento col. 2")):
        if clave in c:
            k = c[clave]
            fila(f"{nombre} ({k['sides']} lados, αs={k['alpha_s']:.0f})", f"Vu = {k['Vu_t']:.1f} t",
                 f"φVc = {k['phiVc_t']:.1f} t", k, "ACI 22.6.4.1, 22.6.5.2")
    for clave, nombre in (("cortante_x", "Cortante en X (a d de la cara)"),
                          ("cortante_y", "Cortante en Y (a d de la cara)"),
                          ("cortante", "Cortante (a d de la cara)")):
        if clave in c:
            k = c[clave]
            fila(nombre, f"Vu = {k['Vu_t']:.1f} t", f"φVc = {k['phiVc_t']:.1f} t", k,
                 "ACI 13.2.7.2, 22.5.5.1(c)")
    for clave, nombre in (("flexion_x", "Flexión en X (cara de columna)"),
                          ("flexion_y", "Flexión en Y (cara de columna)")):
        if clave in c:
            k = c[clave]
            fila(nombre, f"Mu = {k['Mu_tm']:.1f} t·m; As = {k['As_req_cm2']:.1f} cm²",
                 f"As = {k['As_cm2']:.1f} cm²", k, "ACI 13.2.7.1, 22.2, 7.6.1.1")
    for clave, nombre in (("flexion", "Flexión (por metro)"),
                          ("flexion_superior", "Flexión lecho superior"),
                          ("flexion_inferior", "Flexión lecho inferior")):
        if clave in c:
            k = c[clave]
            fila(nombre, f"Mu = {k['Mu_tm']:.1f} t·m", "As según cuadro", k, "ACI 22.2")
    for clave, nombre in (("desarrollo_x", "Anclaje de la parrilla X"),
                          ("desarrollo_y", "Anclaje de la parrilla Y")):
        if clave in c:
            k = c[clave]
            fila(nombre, f"disponible {k['available_m']:.2f} m",
                 f"ld {k['ld_recta_m']:.2f} / ldh {k['ldh_gancho_m']:.2f} m", k,
                 "ACI 25.4.2.3, 25.4.3.1")
    if "aplastamiento" in c:
        k = c["aplastamiento"]
        fila("Aplastamiento columna-zapata", f"Pu = {k['Pu_t']:.1f} t", f"φBn = {k['phiBn_t']:.1f} t",
             k, "ACI 22.8.3.2")
    if "arranques" in c:
        k = c["arranques"]
        fila(f"Arranques {k['count']} {k['bar']} en compresión", f"ldc = {k['ldc_m']:.2f} m",
             f"disponible {k['available_m']:.2f} m", k, "ACI 16.3.4.1, 25.4.9.2")
    if "peralte_minimo" in c:
        k = c["peralte_minimo"]
        fila("Peralte efectivo mínimo", f"d = {k['d_m'] * 100:.0f} cm", "15 cm", k, "ACI 13.3.1.2")
    if "contratrabe_liga" in c:
        for eje, m in c["contratrabe_liga"]["moments"].items():
            filas.append([f"Contratrabe de liga ({eje.upper()})", f"Mu = {m['Mu_tm']:.1f} t·m",
                          "SE DISEÑA APARTE", "PENDIENTE", "excentricidad P·e"])
    return filas


def general_notes(z: dict[str, Any], qa: float) -> list[str]:
    dw = z.get("dowels")
    notas = [
        f"CAPACIDAD DE CARGA ADMISIBLE qa = {qa:.1f} t/m² SEGÚN ESTUDIO DE MECÁNICA DE SUELOS. "
        "VERIFICAR EN OBRA EL TERRENO AL NIVEL DE DESPLANTE ANTES DE COLAR.",
        f"CONCRETO EN ZAPATAS f'c = {z['fc']:.0f} kg/cm². PLANTILLA DE CONCRETO POBRE "
        f"f'c = 100 kg/cm² DE {z['lean_concrete'] * 100:.0f} cm.",
        f"ACERO DE REFUERZO fy = {z['fy']:.0f} kg/cm² (GRADO {z['fy'] / 100:.0f}).",
        (f"RECUBRIMIENTO LIBRE INFERIOR {z['cover'] * 100:.1f} cm (CONCRETO COLADO CONTRA EL "
         "SUELO, ACI 318-19 TABLA 20.5.1.3.1).").replace(".0 cm", " cm"),
        "GANCHOS ESTÁNDAR A 90° CON EXTENSIÓN DE 12 DIÁMETROS (ACI 318-19 25.3.1).",
    ]
    if dw:
        notas.append(f"ARRANQUES: TRASLAPE EN COMPRESIÓN lb = {dw['lap_m']:.2f} m (ACI 318-19 "
                     f"25.5.5.1). DESARROLLO DENTRO DE LA ZAPATA ldc = {dw['ldc_m']:.2f} m "
                     "(25.4.9.2); LA PATA NO CUENTA EN COMPRESIÓN (25.4.1.2).")
    notas += [
        "LA PARRILLA SE APOYA EN CALZOS DE CONCRETO DEL ESPESOR DEL RECUBRIMIENTO, A NO MÁS "
        "DE 1.00 m ENTRE SÍ.",
        "LA JUNTA DE COLADO ZAPATA-COLUMNA SE DEJA RUGOSA, LIMPIA Y HUMEDECIDA ANTES DEL "
        "SEGUNDO COLADO.",
        "EL RELLENO SE COMPACTA EN CAPAS CON EL GRADO QUE FIJE EL E.M.S.",
        f"DISEÑO: ACI 318-19 CAP. 13. COMBINACIÓN {z['code'].split(':')[-1].strip()}.",
        "COTAS EN METROS. NIVELES REFERIDOS AL N.T.N.",
    ]
    return notas


def footing_schedule_rows(designs: list[dict[str, Any]]) -> list[list[str]]:
    filas = [["ZAPATA", "TIPO", "B x L x h (m)", "Df (m)", "PARRILLA X", "PARRILLA Y",
              "ARRANQUES", "f'c"]]
    for z in designs:
        dw = z.get("dowels") or {}
        filas.append([z["mark"], z["kind"].upper(), f"{z['B']:.2f} x {z['L']:.2f} x {z['h']:.2f}",
                      f"{z['depth']:.2f}", z["bars_x"]["text"], z["bars_y"]["text"],
                      f"{dw.get('count', '')} {dw.get('bar', '')}".strip() or "-",
                      f"{z['fc']:.0f}"])
    return filas


def _fondo(tabla: dict[str, Any], y_top: float) -> float:
    if "bottom" in tabla:
        return float(tabla["bottom"])
    return y_top - float(tabla.get("height", 0.0))


def draw_footing_tables(z: dict[str, Any], x: float, y: float, upm: float, qa: float,
                        designs: Optional[list[dict[str, Any]]] = None,
                        count: int = 1, width_mm: float = 192.0) -> dict[str, Any]:
    """Columna de cuadros, de arriba hacia abajo desde (x, y) = esquina
    superior izquierda: cuadro de zapatas, revisión estructural,
    especificaciones y cuantificación. Devuelve la caja que ocupan."""
    def w(mm):
        return mm * upm

    k = width_mm / 192.0
    tablas = []
    yy = y
    t1 = ann_mod.create_table(x, yy, footing_schedule_rows(designs or [z]),
                              [w(v * k) for v in (14, 22, 38, 14, 32, 32, 24, 16)],
                              title="CUADRO DE ZAPATAS", align=["center"] * 8, scale=upm)
    tablas.append(t1)
    yy = _fondo(t1, yy) - w(10)
    t2 = ann_mod.create_table(x, yy, check_rows(z), [w(v * k) for v in (56, 44, 42, 18, 32)],
                              title=f"REVISIÓN ESTRUCTURAL {z['mark']} (ACI 318-19)",
                              align=["left", "center", "center", "center", "left"], scale=upm)
    tablas.append(t2)
    yy = _fondo(t2, yy) - w(10)
    notas = general_notes(z, qa)
    t3 = ann_mod.create_table(x, yy, [["", "ESPECIFICACIONES"]] +
                              [[f"{i + 1}.", n] for i, n in enumerate(notas)],
                              [w(8 * k), w(184 * k)], align=["center", "left"], scale=upm)
    tablas.append(t3)
    yy = _fondo(t3, yy) - w(10)
    t4 = q_mod.create_quantities_table(x, yy, zapatas.cantidades(z, count=count),
                                       title=f"CUANTIFICACIÓN {z['mark']}"
                                             + (f" ({count} PZAS.)" if count > 1 else ""),
                                       scale=upm,
                                       col_widths=[w(v * k) for v in (12, 132, 18, 30)])
    tablas.append(t4)
    yy = _fondo(t4, yy)
    return {"box": [x, yy, x + w(width_mm), y], "tables": tablas}
