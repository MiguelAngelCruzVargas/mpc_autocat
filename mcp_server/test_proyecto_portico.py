"""El pórtico y su barda como proyecto con tools: design_fence -> design_gate_portal -> impose_gate_foundation ->
quantify_portico -> export_portico_report, todo a través del archivo de proyecto. El dibujo (draw_portico_set) necesita
AutoCAD y se prueba en vivo; acá se prueba todo lo demás sin él."""
from __future__ import annotations

import json
import os
import sys
import tempfile

import openpyxl

import portico_proyecto as pp
import server

FALLAS: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(("  ok    " if cond else "  FALLA ") + msg)
    if not cond:
        FALLAS.append(msg)


def _textos_booleanos(x, ruta="") -> list[str]:
    """Los 'True'/'False' guardados como TEXTO (bool de numpy pasado por default=str): son verdaderos para un if."""
    malos = []
    if isinstance(x, dict):
        for k, v in x.items():
            malos += _textos_booleanos(v, f"{ruta}/{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            malos += _textos_booleanos(v, f"{ruta}[{i}]")
    elif isinstance(x, str) and x in ("True", "False"):
        malos.append(ruta)
    return malos


def test_flujo_completo():
    with tempfile.TemporaryDirectory() as tmp:
        proy = os.path.join(tmp, "mixtan.json")
        rf = server.design_fence(250, 5.0, 0.8, 1.6, spacing=3.0, total_h=2.80, wall_h=1.40, pilaster_h=3.15, project_path=proy)
        ok(rf["resumen"]["pilastra"]["armado"] and "f" in pp.cargar(proy), "design_fence guarda la barda en el proyecto")
        rg = server.design_gate_portal(5.0, 3.45, 4.20, 250, 19.0, 1.5, 1.6, core_options=[0.45], footing_max_L=1.60,
                                       project_path=proy)
        d = pp.cargar(proy)["d"]
        ok(len(rg["carga_de_la_barda_incluida"]) == 1 and abs(rg["carga_de_la_barda_incluida"][0][1] - 0.675) < 1e-6,
           "la carga de la 1.a pilastra de la barda llega sola, con su excentricidad")
        ok(d["datos"]["soil_unit_weight"] == 1.6 and d["pilastra"]["demanda"]["Pu_kg"] > 0 and "H_D_t" in d["reacciones"],
           "el diseño guarda sus datos y la demanda de la pilastra")
        ok(not _textos_booleanos(d), "ningún 'ok' queda guardado como texto")
        # el diseño que dimensiona el cálculo
        ok(d["zapata"]["ok"] and d["pilastra"]["ratio"] <= 0.95, "lo que dimensiona el cálculo cumple")

        ri = server.impose_gate_foundation(
            proy, 1.20, 1.20, 0.20, footing_bars=["#3"], pedestal=[0.5, 0.5], pedestal_height=1.30, pilaster_bar_count=8,
            pilaster_bar="#4", tie_beam={"b": 0.20, "h": 0.40, "bars": {"count": 4, "bar": "#3"}, "stirrup": "#2",
                                         "stirrup_spacing": 0.20, "a_lo_largo": True},
            bearing_reference=19.0)
        no = " | ".join(ri["no_cumplen"])
        ok("Volteo y contacto" in no and "Pilastra P-1" in no and "Zapata: cortante en X" in no and "peralte efectivo" in no,
           "la cimentación impuesta sale con lo que NO cumple (volteo, P-M, cortante, peralte)")
        d2 = pp.cargar(proy)["d"]
        z = d2["zapata"]
        ok((z["B"], z["L"], z["h"]) == (1.2, 1.2, 0.2) and z["pedestal"] == [0.5, 0.5] and d2["pilastra"]["bars"]["count"] == 8,
           "la zapata se queda como se definió: no crece sola")
        ok(d2["pilastra"]["ok"] is False and not _textos_booleanos(d2), "la pilastra de 8 #4 queda con ok=False de verdad (bool, no texto)")
        ok(d2["liga"]["ok"] and d2["liga"]["As_cm2"] > d2["liga"]["As_req_cm2"], "la liga se revisa con el empuje de la base")

        # sin el dibujo no hay cantidades: lo dice, no inventa
        try:
            server.quantify_portico(proy)
            ok(False, "quantify_portico sin dibujo rechaza")
        except ValueError as e:
            ok("draw_portico_set" in str(e), "quantify_portico sin dibujo dice qué falta correr")
        # lo que midieron los dibujos (en vivo lo da draw_portico_set)
        r = {"trabe": {"arc_length_m": 5.919, "stirrups": 39, "bar_len_inf_m": 7.161, "bar_len_sup_m": 7.505, "hook_m": 0.382},
             "pil1": {"height_m": 6.1, "bar_len_m": 6.498, "stirrupCount": 46},
             "pil2": {"height_m": 3.65, "pata_m": 0.273, "stirrupCount": 39}, "fronton_h": 0.6755, "dala_len": 6.506}
        pp.guardar(proy, r=r)
        rq = server.quantify_portico(proy, bays=3, on_rock=True)
        conceptos = " | ".join(c["concepto"] for c in rq["conceptos"])
        ok("dados de las zapatas" in conceptos and "hasta la última pilastra" in conceptos, "cuenta el dado y la liga completa")
        ok(rq["acero_total_kg"] > 0 and rq["concreto_250_m3"] > 0, "da acero y concreto")
        rep = server.export_portico_report(os.path.join(tmp, "out"), project_path=proy, project="Prueba")
        md = open(rep["memoria"], encoding="utf-8").read()
        ok("ATENCIÓN" in md and rep["no_cumplen"], "la memoria del proyecto abre con el aviso de lo que no cumple")
        ok(openpyxl.load_workbook(rep["excel"]).sheetnames[:2] == ["Elementos", "Cantidades"], "el Excel sale del proyecto")


def test_sin_archivo_devuelve_el_diseno():
    r = server.design_fence(250, 5.0, 0.8, 1.6, spacing=3.0, total_h=2.80, wall_h=1.40, pilaster_h=3.15)
    ok("design" in r and "cimentacion" in r["design"], "sin project_path devuelve el diseño completo")
    try:
        server.design_fence(250, 0.0, 0.8, 1.6)
        ok(False, "rechaza sin capacidad del suelo")
    except ValueError:
        ok(True, "rechaza sin capacidad del suelo (no la inventa)")


def test_seguro():
    import numpy as np
    x = pp.seguro({"a": np.bool_(False), "b": np.float64(1.5), "c": (np.int64(2), [np.bool_(True)])})
    ok(x["a"] is False and x["c"][1][0] is True and json.loads(json.dumps(x)) == x, "seguro() deja bool, float y entero de Python")


if __name__ == "__main__":
    test_seguro()
    test_sin_archivo_devuelve_el_diseno()
    test_flujo_completo()
    if FALLAS:
        print(f"\n{len(FALLAS)} fallas")
        sys.exit(1)
    print("\nOK")
