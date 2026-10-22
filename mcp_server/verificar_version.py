"""Batería de verificación en vivo de las tools nuevas (consulta, variables de sistema,
edición nativa + undo, propiedades, métodos, 3D) contra el AutoCAD abierto.

Trabaja en un dibujo NUEVO descartable y lo cierra al final. NO usarlo con un plano en
curso. Imprime una línea por verificación y un resumen; sale con código 1 si algo falla.

Uso:  python verificar_version.py
"""
from __future__ import annotations

import re
import sys

import server as s

R: list[tuple[str, bool]] = []


def chk(n, ok, det=""):
    R.append((n, bool(ok)))
    print(("  ok   " if ok else " FALLA ") + n + (f"  [{det}]" if det and not ok else ""))


def intento(n, f):
    try:
        return f()
    except Exception as e:  # noqa: BLE001
        chk(n, False, str(e)[:200])
        return None


def main() -> int:
    s.new_document()
    print("== version:", s.ping())
    # --- variables de sistema / estado
    v = intento("get_system_variables", lambda: s.get_system_variables(["LTSCALE", "INSUNITS", "CTAB", "NOEXISTEXX"]))
    chk("get_system_variables: valores y error de la inexistente", v and "LTSCALE" in v["values"] and "NOEXISTEXX" in v["errors"], v)
    r = intento("set_system_variable", lambda: s.set_system_variable("LTSCALE", 25))
    chk("set_system_variable cambia", r and r["value"] == 25, r)
    if r:
        s.set_system_variable("LTSCALE", r["previous"])
    try:
        s.set_system_variable("SECURELOAD", 0)
        chk("SECURELOAD se rechaza", False)
    except Exception:  # noqa: BLE001
        chk("SECURELOAD se rechaza", True)
    e = intento("get_editor_state", lambda: s.get_editor_state())
    chk("get_editor_state libre", e and e["busy"] is False, e)

    # --- dibujo base
    L = s.create_line(0, 0, 10, 0)["handle"]
    V = s.create_line(5, -5, 5, 5)["handle"]
    C = s.create_circle(30, 0, 5)["handle"]
    P = s.create_polyline([[0, 10], [10, 10], [10, 20]], closed=False)["handle"]
    s.create_text("hola", 0, 30, 1.5)

    # --- consulta y agregados
    a = intento("aggregate por capa", lambda: s.aggregate_entities([{"type": "count", "group_by": "layer"}]))
    chk("aggregate: total 5", a and a["matches"] == 5, a)
    q = intento("query_entities", lambda: s.query_entities(entity_type="Line", filter="length > 9", fields=["length"]))
    chk("query: 2 lineas de largo>9 (L y V miden 10)", q and q["matches"] == 2, q)
    sm = intento("sum length", lambda: s.aggregate_entities([{"type": "sum", "field": "length"}], entity_type="Line"))
    chk("sum de largos = 20", sm and abs(sm["results"][0]["value"] - 20) < 1e-9, sm)

    # --- propiedades 2D
    lp = intento("list_object_properties", lambda: s.list_object_properties(handle=L))
    chk("Line: >30 propiedades y >10 escribibles", lp and lp["count"] > 30 and lp["writableCount"] > 10,
        lp and (lp["count"], lp["writableCount"]))
    s.set_layer("MUROS", color_index=7)
    intento("set props Line", lambda: s.set_object_properties(
        [L], {"EndPoint": [20, 5, 0], "Layer": "MUROS", "Color": [255, 0, 0], "LineWeight": "LineWeight050"}))
    g = s.get_object_properties([L], ["EndPoint", "Layer", "Color", "LineWeight"])["objects"][L]["properties"]
    chk("set/get props Line (punto, capa, RGB, enum)",
        g["EndPoint"] == [20, 5, 0] and g["Layer"] == "MUROS" and g["Color"] == [255, 0, 0]
        and g["LineWeight"] == "LineWeight050", g)
    intento("set Circle.Radius", lambda: s.set_object_properties([C], {"Radius": 3.5}))
    chk("Circle.Radius recalcula el area",
        s.get_object_properties([C], ["Area"])["objects"][C]["properties"]["Area"] > 38, "")
    ant = s.get_object_properties([C], ["Radius"])["objects"][C]["properties"]["Radius"]
    try:
        s.set_object_properties([C], {"Radius": 9, "Layer": "NO_EXISTE"})
        chk("atomicidad: rechaza", False)
    except Exception:  # noqa: BLE001
        chk("atomicidad: no cambio nada",
            s.get_object_properties([C], ["Radius"])["objects"][C]["properties"]["Radius"] == ant)

    # --- metodos 2D
    m = intento("GetClosestPointTo", lambda: s.call_object_method(P, "GetClosestPointTo", [[3, 12, 0], False]))
    chk("GetClosestPointTo", m and m["result"] == [3, 10, 0], m)
    m = intento("IntersectWith", lambda: s.call_object_method(L, "IntersectWith", [V, "OnBothOperands"]))
    chk("IntersectWith linea x vertical", m and m["out"]["points"], m)
    m = intento("GetSplitCurves", lambda: s.call_object_method(P, "GetSplitCurves", [[0.5, 1.5]], add_results_to_space=True))
    chk("GetSplitCurves crea 3", m and len(m.get("created", [])) == 3, m)
    try:
        s.call_object_method(L, "Dispose")
        chk("Dispose se rechaza", False)
    except Exception:  # noqa: BLE001
        chk("Dispose se rechaza", True)

    # --- operaciones nativas
    a1 = s.create_line(100, 0, 105, 0)["handle"]
    b1 = s.create_line(105, 0, 110, 0)["handle"]
    j = intento("join_entities", lambda: s.join_entities([a1, b1]))
    chk("join_entities ok y borra una", j and j["ok"] and len(j["deleted"]) == 1, j)
    t0 = s.create_line(200, 0, 210, 0)["handle"]
    e0 = s.create_line(205, -5, 205, 5)["handle"]
    tr = intento("trim_entity", lambda: s.trim_entity([e0], t0, [208, 0]))
    chk("trim_entity recorta", tr and tr["ok"] and tr["modified"], tr)
    x1 = s.create_line(300, 0, 303, 0)["handle"]
    x2 = s.create_line(306, -5, 306, 5)["handle"]
    ex = intento("extend_entity", lambda: s.extend_entity([x2], x1, [303, 0]))
    chk("extend_entity alarga", ex and ex["ok"] and ex["modified"], ex)
    f1 = s.create_line(400, 0, 408, 0)["handle"]
    f2 = s.create_line(410, 2, 410, 10)["handle"]
    fl = intento("fillet_entities", lambda: s.fillet_entities(f1, f2, 1, [406, 0], [410, 6]))
    chk("fillet crea un arco", fl and fl["ok"] and any(c["type"] == "Arc" for c in fl["created"]), fl)
    o1 = s.create_line(500, 0, 505, 0)["handle"]
    o2 = s.create_line(500, 0, 505, 0)["handle"]
    ok_ = intento("overkill_entities", lambda: s.overkill_entities([o1, o2]))
    chk("overkill borra el duplicado", ok_ and ok_["ok"] and ok_["deletedCount"] == 1, ok_)
    u = intento("undo del overkill", lambda: s.undo(1))
    chk("undo verifica y revierte (overkill)", u and u["ok"], u)
    u = intento("undo del fillet", lambda: s.undo(1))
    chk("undo verifica y revierte (fillet)", u and u["ok"], u)

    # --- 3D
    def vol(h):
        return s.get_object_properties([h], ["MassProperties"])["objects"][h]["properties"]["MassProperties"]["Volume"]

    def caja(x0, x1_, y0=0, y1=10, alto=10):
        return s.extrude_profile([[x0, y0], [x1_, y0], [x1_, y1], [x0, y1]], alto)["handle"]

    S1, S2 = caja(0, 10), caja(5, 15)
    chk("Solid3d.MassProperties.Volume = 1000", abs(vol(S1) - 1000) < 1e-6, vol(S1))
    m = intento("CheckInterference", lambda: s.call_object_method(S1, "CheckInterference", [S2]))
    chk("CheckInterference true", m and m["result"] is True, m)
    intento("TransformBy matriz", lambda: s.call_object_method(
        S1, "TransformBy", [[[1, 0, 0, 10], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]]))
    cen = s.get_object_properties([S1], ["MassProperties"])["objects"][S1]["properties"]["MassProperties"]["Centroid"]
    chk("TransformBy movio el centroide a 15,5,5", cen == [15, 5, 5], cen)
    intento("OffsetBody", lambda: s.call_object_method(S2, "OffsetBody", [1.0]))
    chk("OffsetBody: 12*12*12=1728", abs(vol(S2) - 1728) < 1e-6, vol(S2))
    S3, S4 = caja(40, 50), caja(45, 55)
    intento("BoolSubtract", lambda: s.call_object_method(S3, "BooleanOperation", ["BoolSubtract", S4]))
    chk("Subtract: 500", abs(vol(S3) - 500) < 1e-6, vol(S3))
    S5 = caja(60, 70)
    m = intento("Slice", lambda: s.call_object_method(
        S5, "Slice", [{"point": [0, 0, 5], "normal": [0, 0, 1]}, True], add_results_to_space=True))
    chk("Slice: crea la mitad y el original queda en 500", m and m.get("created") and abs(vol(S5) - 500) < 1e-6, m)
    P1 = s.create_polyline([[100, 50], [110, 50], [110, 60], [100, 60]], closed=True)["handle"]
    P2 = s.create_polyline([[105, 55], [115, 55], [115, 65], [105, 65]], closed=True)["handle"]
    rg = intento("union_regions", lambda: s.union_regions([P1, P2], delete_sources=True))
    chk("Region area 175", rg and rg["area"] == 175, rg)
    if rg:
        pr = s.get_object_properties([rg["handle"]], ["Area", "Perimeter"])["objects"][rg["handle"]]["properties"]
        chk("Region props Area/Perimeter", pr["Area"] == 175 and pr["Perimeter"] == 60, pr)
    mm = intento("run_code SubDMesh", lambda: s.run_code(
        code=("var mesh = new Autodesk.AutoCAD.DatabaseServices.SubDMesh(); mesh.SetSphere(3.0, 8, 8, 0); "
              "space.AppendEntity(mesh); tr.AddNewlyCreatedDBObject(mesh, true); "
              'Print("HANDLE=" + mesh.Handle.ToString());'),
        description="malla de prueba", force=True))
    h = re.search(r"HANDLE=(\w+)", (mm or {}).get("output", "") or "")
    if h:
        m = intento("ComputeVolume", lambda: s.call_object_method(h.group(1), "ComputeVolume"))
        chk("SubDMesh.ComputeVolume ~98", m and 90 < m["result"] < 110, m)
    else:
        chk("SubDMesh creada con run_code", False, mm)

    n = sum(1 for _, ok in R if ok)
    print(f"\nRESULTADO: {n}/{len(R)} verificaciones OK  (AutoCAD {s.ping().get('pluginVersion')})")
    fallan = [x for x, ok in R if not ok]
    if fallan:
        print("FALLAN:", fallan)
    try:
        s.close_document(discard_unsaved=True)
    except Exception:  # noqa: BLE001
        pass
    return 0 if not fallan else 1


if __name__ == "__main__":
    sys.exit(main())
