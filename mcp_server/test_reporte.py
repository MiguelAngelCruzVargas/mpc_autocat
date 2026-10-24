"""Memoria y libro de cantidades del portico generados desde el diseno (portico_reporte), y el reencuadre de
viewports (viewport_ajuste). No necesita AutoCAD."""
from __future__ import annotations

import json
import os
import sys
import tempfile

import openpyxl

import portico_arco as pa
import portico_cuadros as pc
import portico_reporte as pr
import viewport_ajuste as va
import zapatas as zap

FALLAS: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(("  ok    " if cond else "  FALLA ") + msg)
    if not cond:
        FALLAS.append(msg)


def _proyecto(zapata_impuesta: bool):
    f = pa.design_fence(250, 5.0, 0.8, 1.6, total_h=2.80, wall_h=1.40, pilaster_h=3.15)
    ex = [(f["cargas"]["N_t_m"] * f["spacing"], 0.68)]
    d = pa.design_gate_portal(5.0, 3.45, 4.20, 250, 19.0, 1.5, 1.6, core_options=(0.45,), extra_loads=ex, footing_max_L=1.60)
    if zapata_impuesta:
        d["zapata"] = zap.design_footing(
            kind="aislada", dead_load=8.81, live_load=0.0, allowable_bearing=1000.0, fc=250, depth=1.5, column=[0.4, 0.4],
            soil_unit_weight=1.6, code="NTC", moment_x=1.37, moment_y=5.7, tie_beam=False, width=1.2, length=1.2,
            min_thickness=0.20, pedestal=[0.5, 0.5], pedestal_height=1.3, column_bar="#4", column_bar_count=8,
            bars=("#3",), mark="Z-1", fixed_thickness=True)
        d["zapata"]["checks"].pop("capacidad", None)
        # lo que pasa por json.dump(default=str) con un bool de numpy: llega como el TEXTO 'False'
        d["pilastra"]["ok"] = "False"
        d["pilastra"]["ratio"] = 1.17
    rr = {"trabe": {"arc_length_m": 5.2, "stirrups": 36, "bar_len_inf_m": 6.4, "bar_len_sup_m": 6.7},
          "pil1": {"height_m": 6.1, "bar_len_m": 6.5, "stirrupCount": 46},
          "pil2": {"height_m": 3.7, "pata_m": 0.3, "stirrupCount": 35}, "fronton_h": 0.8, "dala_len": 7.2}
    q = pc.cantidades(d, f, rr, 1.5, 0.8, bays=3, roca=True)
    return d, f, q


def _guardar(d, f, q, carpeta):
    a, b = os.path.join(carpeta, "d.json"), os.path.join(carpeta, "q.json")
    with open(a, "w", encoding="utf-8") as fh:
        json.dump({"d": d, "f": f}, fh, ensure_ascii=False, default=str)
    with open(b, "w", encoding="utf-8") as fh:
        json.dump(q, fh, ensure_ascii=False, default=str)
    return a, b


def test_reporte_con_diseno_que_no_cumple():
    d, f, q = _proyecto(True)
    with tempfile.TemporaryDirectory() as tmp:
        a, b = _guardar(d, f, q, tmp)
        r = pr.exportar(a, b, os.path.join(tmp, "out"), "Prueba")
        with open(r["memoria"], encoding="utf-8") as fh:
            md = fh.read()
        ok("ATENCIÓN" in md and "SUJETAS A VERIFICACIÓN" in md, "la memoria abre con el aviso cuando algo no cumple")
        nombres = " | ".join(r["no_cumplen"])
        ok("Zapata: cortante en X" in nombres and "Zapata: peralte efectivo mínimo" in nombres, "lista lo que no cumple de la zapata")
        ok("Pilastra P-1" in nombres, "un 'ok' que llega como texto 'False' cuenta como NO CUMPLE (no como verdadero)")
        ok("| Z-1 |" in md and "120 x 120 x 20" in md and "| D-1 |" in md, "el cuadro de elementos trae la zapata y su dado")
        ok(f"{q['acero_total_kg']:.0f} kg" in md, "el acero de la memoria es el de las cantidades")
        wb = openpyxl.load_workbook(r["excel"])
        ok(wb.sheetnames == ["Elementos", "Cantidades", "Acero", "Materiales", "Diseño", "Revisión", "Supuestos"], "el libro trae sus siete hojas")
        ws = wb["Cantidades"]
        formulas = [c.value for row in ws.iter_rows(min_row=5) for c in row if isinstance(c.value, str) and c.value.startswith("=")]
        ok(any(x.startswith("=SUM(G5:G") for x in formulas) and any(x.startswith("=E") for x in formulas),
           "el importe, el subtotal y el total van formulados")
        ok(ws["F5"].fill.fgColor.rgb.endswith("FFF2CC"), "el P.U. queda en celda amarilla para llenar")


def test_reporte_es_determinista_y_sin_aviso_si_cumple():
    d, f, q = _proyecto(False)
    with tempfile.TemporaryDirectory() as tmp:
        a, b = _guardar(d, f, q, tmp)
        r1 = pr.exportar(a, b, os.path.join(tmp, "o1"), "Prueba")
        r2 = pr.exportar(a, b, os.path.join(tmp, "o2"), "Prueba")
        with open(r1["memoria"], encoding="utf-8") as fh:
            m1 = fh.read()
        with open(r2["memoria"], encoding="utf-8") as fh:
            m2 = fh.read()
        ok(m1 == m2, "la misma entrada da exactamente la misma memoria")
        ok("ATENCIÓN" not in m1 and not r1["no_cumplen"], "sin aviso cuando el diseño cumple todo")
        a1 = openpyxl.load_workbook(r1["excel"])["Cantidades"]
        a2 = openpyxl.load_workbook(r2["excel"])["Cantidades"]
        ok([c.value for row in a1.iter_rows() for c in row] == [c.value for row in a2.iter_rows() for c in row],
           "el Excel también sale igual")


# --------------------------------------------------------------------------- viewport
class _Falso:
    """AutoCAD de mentira: el viewport general y dos viewports de detalle."""

    def __init__(self):
        self.vp = {"A": {"Width": 100.0, "Height": 60.0, "ViewCenter": [10.0, 10.0], "CustomScale": 40.0,
                         "CenterPoint": [0, 0, 0], "Locked": True},
                   "B": {"Width": 100.0, "Height": 60.0, "ViewCenter": [50.0, 10.0], "CustomScale": 40.0,
                         "CenterPoint": [0, 0, 0], "Locked": True}}
        self.layout = "Model"

    def call(self, nombre, pars=None):
        if nombre == "get_editor_state":
            return {"layout": self.layout}
        if nombre == "set_current_layout":
            self.layout = pars["name"]
            return {}
        if nombre == "select_entities":
            return {"entities": [{"handle": "G"}, {"handle": "A"}, {"handle": "B"}]}
        raise AssertionError(nombre)

    def get(self, handles, names=None):
        h = handles[0]
        return {"objects": {h: {"properties": dict(self.vp[h])}}}

    def set(self, handles, properties, dry_run=False):
        self.vp[handles[0]].update(properties)
        return {}


def test_reencuadre():
    fake = _Falso()
    va.acad.call, va.prop.get_properties, va.prop.set_properties = fake.call, fake.get, fake.set
    r = va.refit_viewport("BP-01", [48.0, 8.0, 52.0, 12.0])
    ok(r["handle"] == "B", "elige el viewport que ya cubría esa zona")
    ok(fake.vp["B"]["ViewCenter"] == [50.0, 10.0] and fake.vp["B"]["Locked"] is True, "centra la vista y lo deja bloqueado")
    ok(fake.layout == "Model", "el layout activo vuelve al de antes")
    r = va.refit_viewport("BP-01", [40.0, 0.0, 60.0, 20.0], handle="B")
    ok(fake.vp["B"]["Width"] >= (20 + 0.5) * 40.0 - 1e-6 and r["caja_entra"], "'grow' agranda el viewport cuando la caja no entra")
    fake.vp["B"].update({"Width": 100.0, "Height": 60.0})      # entra 2.5 x 1.5 m: una caja de 2.4 x 1.4 entra sin margen
    va.refit_viewport("BP-01", [48.8, 9.3, 51.2, 10.7], handle="B")
    ok(fake.vp["B"]["Width"] == 100.0 and fake.vp["B"]["Height"] == 60.0, "'grow' no toca el tamaño si la caja ya entra")
    fake.vp["B"].update({"Width": 800.0, "Height": 400.0})      # viewport grande y una caja chica
    va.refit_viewport("BP-01", [49.5, 9.5, 50.5, 10.5], handle="B")
    ok(fake.vp["B"]["Height"] == 400.0 and fake.vp["B"]["Width"] == 800.0, "'grow' nunca lo achica")
    va.refit_viewport("BP-01", [49.0, 9.0, 51.0, 11.0], handle="B", resize="fit")
    ok(abs(fake.vp["B"]["Width"] - (2 + 0.5) * 40.0) < 1e-6, "'fit' lo deja justo a la caja más el margen")
    for mal in (dict(box=[1, 1, 0, 2]), dict(box=[0, 0, 1, 1], scale_denominator=25.0), dict(box=[0, 0, 1, 1], resize="x")):
        try:
            va.refit_viewport("BP-01", handle="B", **mal)
            ok(False, f"rechaza {mal}")
        except va.ViewportError:
            ok(True, f"rechaza {mal}")
    fake.vp["B"] = dict(fake.vp["A"])            # dos viewports idénticos sobre la misma zona
    try:
        va.refit_viewport("BP-01", [8.0, 8.0, 12.0, 12.0])
        ok(False, "dos viewports sobre la caja: pide el handle")
    except va.ViewportError:
        ok(True, "dos viewports sobre la caja: pide el handle")


if __name__ == "__main__":
    test_reporte_con_diseno_que_no_cumple()
    test_reporte_es_determinista_y_sin_aviso_si_cumple()
    test_reencuadre()
    if FALLAS:
        print(f"\n{len(FALLAS)} fallas")
        sys.exit(1)
    print("\nOK")
