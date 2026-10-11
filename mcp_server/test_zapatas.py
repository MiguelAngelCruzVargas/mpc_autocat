"""Tests del capítulo de zapatas (zapatas.py, zapatas_dibujo.py,
zapatas_combinada.py, zapatas_cuadros.py, detalle.py). NO necesita AutoCAD:
el diseño es cálculo puro y el dibujo se corre contra el mock de preview.

Uso:  python test_zapatas.py
"""
from __future__ import annotations

import math
import sys

import preview

preview.install()

import autocad_client as acad   # noqa: E402
import detalle as dt            # noqa: E402
import space                    # noqa: E402
import zapatas                  # noqa: E402
import zapatas_combinada        # noqa: E402
import zapatas_cuadros          # noqa: E402
import zapatas_dibujo           # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: object = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name + (f" -- {detalle}" if not ok else ""))


BASE = dict(allowable_bearing=15, fc=250, depth=1.50, soil_unit_weight=1.7)
TIPOS = {
    "aislada": dict(kind="aislada", dead_load=60, live_load=20, column=[0.40, 0.40], **BASE),
    "dado": dict(kind="aislada", dead_load=60, live_load=20, column=[0.40, 0.40],
                 pedestal=[0.60, 0.60], pedestal_height=0.60, **BASE),
    "lindero": dict(kind="lindero", dead_load=40, live_load=12, column=[0.35, 0.35], **BASE),
    "esquina": dict(kind="esquina", dead_load=25, live_load=8, column=[0.35, 0.35], **BASE),
    "corrida": dict(kind="corrida", dead_load=6, live_load=2, wall_thickness=0.15,
                    wall_material="mamposteria", grade_beam_height=0.20, allowable_bearing=10,
                    fc=250, depth=1.00, soil_unit_weight=1.7),
    "combinada": dict(kind="combinada", dead_load=0, live_load=0, allowable_bearing=15, fc=250,
                      depth=1.50, soil_unit_weight=1.7, spacing=4.0, boundary_left=True,
                      columns=[{"dead": 40, "live": 15, "size": [0.35, 0.35]},
                               {"dead": 60, "live": 20, "size": [0.40, 0.40]}]),
}


def test_formulas_aci() -> None:
    """Los números de las fórmulas contra cuentas a mano (ACI 318-19)."""
    fc, fy = 250 * zapatas.KGCM2_A_MPA, 4200 * zapatas.KGCM2_A_MPA
    # ldc #6: 0.24·412/√24.5·19.1 = 381 mm; 0.043·412·19.1 = 338 -> 381.
    check("ldc #6 = 0.381 m", abs(zapatas.ldc_compresion(0.0191, fc, fy) - 0.381) < 0.002,
          zapatas.ldc_compresion(0.0191, fc, fy))
    # Traslape en compresión #6: 0.071·412·19.1 = 559 mm.
    check("traslape #6 = 0.559 m",
          abs(zapatas.traslape_compresion(0.0191, fy) - 0.559) < 0.003,
          zapatas.traslape_compresion(0.0191, fy))
    check("lambda_s de d=300 mm", abs(zapatas.lambda_s(0.30) - 0.958) < 0.002,
          zapatas.lambda_s(0.30))
    check("lambda_s no pasa de 1", zapatas.lambda_s(0.10) == 1.0)
    check("As mínimo 0.0018·b·h", abs(zapatas.as_minimo(1.0, 0.50, fy) - 9.0) < 1e-6)
    vc, ec = zapatas.vc_punzonamiento(fc, 0.4, 0.4, 3.4, 0.45, 40)
    check("punzonamiento de columna cuadrada lo gobierna (a)", ec.startswith("(a)"), ec)


def test_rechaza_lo_que_no_se_supone() -> None:
    for falta, kw in (("capacidad", dict(allowable_bearing=None)), ("f'c", dict(fc=None)),
                      ("desplante", dict(depth=None)), ("peso del relleno",
                                                        dict(soil_unit_weight=None))):
        datos = {**TIPOS["aislada"], **kw}
        try:
            zapatas.design_footing(**datos)
            check(f"sin {falta} rechaza", False, "no levantó ValueError")
        except ValueError:
            check(f"sin {falta} rechaza", True)
    datos = {**TIPOS["aislada"], "soil_unit_weight": None, "bearing_is_net": True}
    check("con capacidad neta no pide el peso del relleno",
          zapatas.design_footing(**datos)["ok"])


def test_cada_tipo_cumple_y_es_coherente() -> None:
    for nombre, datos in TIPOS.items():
        z = zapatas.design_footing(mark=nombre.upper(), **datos)
        check(f"{nombre}: cumple todas las revisiones", z["ok"],
              {k: v for k, v in z["checks"].items() if not v.get("ok", True)})
        if nombre not in ("corrida", "combinada"):
            izq, der, aba, arr = z["column_offsets"]
            a1, a2 = z.get("pedestal") or z["column"]
            check(f"{nombre}: los volados cierran con B",
                  abs(izq + der + a1 - z["B"]) < 1e-6, (izq, der, a1, z["B"]))
            check(f"{nombre}: los volados cierran con L",
                  abs(aba + arr + a2 - z["L"]) < 1e-6, (aba, arr, a2, z["L"]))
            for v in (izq, der, aba, arr):
                check(f"{nombre}: volado {v} en cm redondos",
                      abs(v * 100 - round(v * 100)) < 1e-6, v)
        for clave in ("bars_x", "bars_y"):
            arm = z[clave]
            if arm and arm.get("spacing"):
                check(f"{nombre}: {clave} a s <= min(3h, 45 cm)",
                      arm["spacing"] <= min(3 * z["h"], 0.45) + 1e-9, arm)


def test_lindero_y_esquina_punzonan_con_menos_lados() -> None:
    li = zapatas.design_footing(**TIPOS["lindero"])["checks"]["punzonamiento"]
    es = zapatas.design_footing(**TIPOS["esquina"])["checks"]["punzonamiento"]
    ai = zapatas.design_footing(**TIPOS["aislada"])["checks"]["punzonamiento"]
    check("aislada: 4 lados, alfa 40", (ai["sides"], ai["alpha_s"]) == (4, 40.0), ai)
    check("lindero: 3 lados, alfa 30", (li["sides"], li["alpha_s"]) == (3, 30.0), li)
    check("esquina: 2 lados, alfa 20", (es["sides"], es["alpha_s"]) == (2, 20.0), es)
    z = zapatas.design_footing(**TIPOS["lindero"])
    check("lindero con contratrabe avisa el momento que hay que diseñar",
          "contratrabe_liga" in z["checks"] and z["checks"]["contratrabe_liga"]["moments"]["x"]
          ["Mu_tm"] > 0, z["checks"].get("contratrabe_liga"))


def test_arranques_gobiernan_el_peralte() -> None:
    """Con #8 en la columna el desarrollo en compresión pide más peralte que
    con #4: el arranque se desarrolla en la zapata (ACI 25.4.9.2)."""
    z4 = zapatas.design_footing(**{**TIPOS["aislada"], "column_bar": "#4"})
    z8 = zapatas.design_footing(**{**TIPOS["aislada"], "column_bar": "#8"})
    check("#8 pide más peralte que #4", z8["h"] > z4["h"], (z4["h"], z8["h"]))
    k = z8["checks"]["arranques"]
    check("y le alcanza", k["available_m"] >= k["ldc_m"], k)


def test_dala_ntc_mamposteria() -> None:
    d = zapatas.dala(0.15, 250, 4200)
    check("dala 15: As >= 0.2 f'c t²/fy", d["As_cm2"] >= 0.2 * 250 * 15 ** 2 / 4200, d)
    check("dala 15: s <= 1.5t y 20 cm", d["spacing"] <= min(0.225, 0.20) + 1e-9, d)


def test_cuantificacion() -> None:
    z = zapatas.design_footing(mark="Z-1", **TIPOS["aislada"])
    q = zapatas.cantidades(z)
    t = q["totals"]
    check("concreto de zapata = B·L·h", abs(t["concreto_m3"] - z["B"] * z["L"] * z["h"]) < 0.01, t)
    check("relleno < excavación", t["relleno_m3"] < t["excavacion_m3"], t)
    check("hay acero", t["acero_kg"] > 0, t)
    check("la plantilla no se suma al estructural", "concreto_pobre_m3" in t, t)
    zc = zapatas.design_footing(mark="ZC-1", **TIPOS["corrida"])
    qc = zapatas.cantidades(zc)
    check("corrida: por metro", all("(por metro)" in i["label"] for i in qc["items"]),
          [i["label"] for i in qc["items"]])


def test_texto_cota_exacto() -> None:
    check("cm redondos -> sin texto propio", dt.texto_cota(0.35) is None)
    check("0.175 -> '0.175'", dt.texto_cota(0.175) == "0.175", dt.texto_cota(0.175))


def _segmentos_llamada():
    return [e for e in preview.DRAWN if e["cmd"] == "create_polyline"
            and e.get("layer") == dt.LAYER_LLAMADAS and len(e["points"]) == 3]


def test_dibujo_de_cada_tipo() -> None:
    for nombre, datos in TIPOS.items():
        preview.DRAWN.clear()
        space.clear()
        acad.LOTE_ERRORES.clear()
        space.set_scale(0.02)
        z = zapatas.design_footing(mark=nombre.upper(), **datos)
        if nombre == "combinada":
            c = zapatas_combinada.draw_combined_section(z, 0.0, 0.0, 0.02)
            p = zapatas_combinada.draw_combined_plan(z, 12.0, -1.6, 0.02)
        else:
            c = zapatas_dibujo.draw_footing_section(z, 0.0, 0.0, 0.02)
            p = (zapatas_dibujo.draw_strip_plan(z, 9.0, -0.5, 0.02) if nombre == "corrida"
                 else zapatas_dibujo.draw_footing_plan(z, 9.0, -0.5, 0.02))
        check(f"{nombre}: dibujó corte y planta", len(preview.DRAWN) > 120, len(preview.DRAWN))
        check(f"{nombre}: sin errores de lote", not c["batchErrors"] and not p["batchErrors"])
        segs = _segmentos_llamada()
        cruces = 0
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                a, b = segs[i]["points"], segs[j]["points"]
                if dt._se_cruzan(a[0], a[1], b[0], b[1]):
                    cruces += 1
        check(f"{nombre}: ninguna llamada cruza otra", cruces == 0, cruces)
        anchos = [e for e in preview.DRAWN if e["cmd"] == "create_polyline" and e.get("width")]
        check(f"{nombre}: las varillas tienen su grueso real", len(anchos) >= 4, len(anchos))
        b = c["box"]
        check(f"{nombre}: caja del corte con sentido", b[2] > b[0] and b[3] > b[1], b)


def test_cuadros() -> None:
    preview.DRAWN.clear()
    space.clear()
    z = zapatas.design_footing(mark="Z-1", **TIPOS["aislada"])
    filas = zapatas_cuadros.check_rows(z)
    check("revisión: una fila por chequeo y todas CUMPLE",
          all(f[3] in ("CUMPLE", "") for f in filas[1:]) and len(filas) >= 10, filas)
    t = zapatas_cuadros.draw_footing_tables(z, 0, 0, 0.02, qa=15.0)
    check("cuadros apilados hacia abajo", t["box"][1] < t["box"][3], t["box"])
    notas = zapatas_cuadros.general_notes(z, 15.0)
    check("las notas citan el recubrimiento de ACI", any("20.5.1.3.1" in n for n in notas))


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_") and callable(f):
            print(f"\n{nombre}")
            f()
    print(f"\n{'FALLARON ' + str(len(FAILED)) if FAILED else 'TODO OK'}")
    for f in FAILED:
        print("  -", f)
    sys.exit(1 if FAILED else 0)
