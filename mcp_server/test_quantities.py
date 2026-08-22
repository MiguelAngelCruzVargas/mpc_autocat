"""Tests de quantities.py contra el socket mockeado. NO necesita AutoCAD.

Verifica que la cuantificación mida de verdad (no invente): que el volumen
salga de sumar las áreas reales por handle, que la merma de ladrillo se
aplique sobre el módulo correcto, que el mortero sea la diferencia real
entre el volumen del muro y el de las piezas, y que el acero tome el
perímetro del estribo YA dibujado en vez de recalcularlo a mano.

Uso:  python test_quantities.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import autocad_client as acad  # noqa: E402
import quantities  # noqa: E402

FAILED: list[str] = []


def check(name: str, got, expected, tol: float = 1e-6) -> None:
    ok = (abs(got - expected) <= tol
          if isinstance(expected, float) else got == expected)
    if not ok:
        FAILED.append(f"{name}: esperaba {expected}, obtuve {got}")
    print(("  ok  " if ok else " FALLA ") + name)


def check_raises(name: str, fn, fragment: str) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        if fragment.lower() in str(exc).lower():
            print("  ok  " + name)
            return
        FAILED.append(f"{name}: error sin el texto {fragment!r}: {exc}")
    else:
        FAILED.append(f"{name}: no dio error")
    print(" FALLA " + name)


def _mock_areas(areas: dict) -> None:
    """Reemplaza acad.call para que calculate_area/get_entity devuelvan
    valores fijos por handle; todo lo demás cae al mock genérico de preview
    (list_layers, create_text, etc.) para que create_quantities_table siga
    funcionando dentro del mismo test."""
    def fake(cmd, params=None):
        params = params or {}
        if cmd == "calculate_area":
            return {"area": areas[params["handle"]]}
        if cmd == "get_entity":
            return {"length": areas.get(("perim", params["handle"]), 0.0)}
        return preview.fake_call(cmd, params)
    quantities.acad.call = fake


def test_concrete_volume_suma_areas_reales() -> None:
    real = quantities.acad.call
    try:
        _mock_areas({"K1": 0.375, "K2": 0.375, "K3": 0.375})
        r = quantities.calculate_quantities([
            {"type": "concrete_volume", "label": "Castillos K-1",
             "handles": ["K1", "K2", "K3"], "depth": 0.15},
        ])
        check("area sumada de los 3 handles", r["items"][0]["area"], 1.125)
        check("volumen = area x depth", r["items"][0]["volume"], 0.16875, tol=1e-4)
        check("total concreto_m3", r["totals"]["concreto_m3"], 0.169, tol=1e-3)
    finally:
        quantities.acad.call = real


def test_concrete_mix_desde_volumen_ya_calculado() -> None:
    """El caso normal: el volumen ya salió de un item de concrete_volume y
    concrete_mix solo reparte ese numero en bolsas/arena/grava -- no lo
    vuelve a medir."""
    r = quantities.calculate_quantities([
        {"type": "concrete_mix", "label": "Losa de escalera", "volume": 2.0},
    ])
    item = r["items"][0]
    check("bolsas por default (7.5/m3)", item["cementBags"], 15)
    check("arena por default (0.50/m3)", item["sandM3"], 1.0)
    check("grava por default (0.80/m3)", item["gravelM3"], 1.6)
    check("total cemento_bolsas", r["totals"]["cemento_bolsas"], 15)
    check("total arena_m3", r["totals"]["arena_m3"], 1.0)
    check("total grava_m3", r["totals"]["grava_m3"], 1.6)


def test_concrete_mix_redondea_bolsas_hacia_arriba() -> None:
    """No se compra media bolsa: 1.01 m3 x 7.5 = 7.575 bolsas -> 8, no 7."""
    r = quantities.calculate_quantities([
        {"type": "concrete_mix", "label": "Dado", "volume": 1.01},
    ])
    check("redondea hacia arriba", r["items"][0]["cementBags"], 8)


def test_concrete_mix_coeficientes_propios() -> None:
    """Si el proyecto ya tiene su propio diseño de mezcla, esos coeficientes
    pisan el default -- no una proporción 1:2:3 inventada."""
    r = quantities.calculate_quantities([
        {"type": "concrete_mix", "label": "Losa premezclada", "volume": 1.0,
         "cement_bags_per_m3": 9.0, "sand_m3_per_m3": 0.45,
         "gravel_m3_per_m3": 0.75},
    ])
    item = r["items"][0]
    check("usa el coeficiente propio de cemento", item["cementBags"], 9)
    check("usa el coeficiente propio de arena", item["sandM3"], 0.45)
    check("usa el coeficiente propio de grava", item["gravelM3"], 0.75)


def test_concrete_mix_midiendo_handles_igual_que_concrete_volume() -> None:
    """Si no hay un volumen ya calculado, mide igual que concrete_volume:
    area real x depth, no una suposicion aparte."""
    real = quantities.acad.call
    try:
        _mock_areas({"E1": 1.6})
        r = quantities.calculate_quantities([
            {"type": "concrete_mix", "label": "Losa de escalera",
             "handles": ["E1"], "depth": 1.0},
        ])
        item = r["items"][0]
        check("volumen medido = area x depth", item["volume"], 1.6)
        check("bolsas sobre el volumen medido", item["cementBags"], 12)
    finally:
        quantities.acad.call = real


def test_concrete_mix_sin_volumen_ni_handles_falla() -> None:
    check_raises(
        "concrete_mix sin volume ni handles",
        lambda: quantities.calculate_quantities([
            {"type": "concrete_mix", "label": "Losa"}]),
        "necesita")


def test_concrete_volume_aplica_merma() -> None:
    real = quantities.acad.call
    try:
        _mock_areas({"Z1": 1.0})
        r = quantities.calculate_quantities([
            {"type": "concrete_volume", "label": "Zapata", "handles": ["Z1"],
             "depth": 0.5, "waste_pct": 8.0},
        ])
        check("volumen con 8% de merma", r["items"][0]["volume"], 0.54, tol=1e-6)
        check("total incluye la merma", r["totals"]["concreto_m3"], 0.54, tol=1e-3)
    finally:
        quantities.acad.call = real


def test_concrete_volume_sin_depth_falla() -> None:
    check_raises(
        "sin depth tira error",
        lambda: quantities.calculate_quantities(
            [{"type": "concrete_volume", "label": "X", "handles": ["a"]}]),
        "depth")


def test_brick_count_usa_modulo_y_merma() -> None:
    real = quantities.acad.call
    try:
        # Área tal que sin merma darian exactamente 100 piezas.
        modulo = (0.28 + 0.015) * (0.07 + 0.015)
        _mock_areas({"muro": modulo * 100})
        r = quantities.calculate_quantities([
            {"type": "brick_count", "label": "Muro", "handles": ["muro"],
             "waste_pct": 5.0},
        ])
        check("100 piezas + 5% merma = 105", r["items"][0]["pieces"], 105)
        check("total ladrillo_piezas", r["totals"]["ladrillo_piezas"], 105)
    finally:
        quantities.acad.call = real


def test_mortar_es_diferencia_real() -> None:
    real = quantities.acad.call
    try:
        modulo = (0.28 + 0.015) * (0.07 + 0.015)
        area = modulo * 10  # exactamente 10 piezas de módulo
        _mock_areas({"muro": area})
        r = quantities.calculate_quantities([
            {"type": "mortar_volume", "label": "Mortero", "handles": ["muro"],
             "thickness": 0.14},
        ])
        wall_vol = area * 0.14
        brick_vol = 10 * (0.28 * 0.07 * 0.14)
        esperado = wall_vol - brick_vol
        check("mortero = volumen muro - volumen piezas",
              r["items"][0]["mortarVolume"], round(esperado, 4))
        check("nunca negativo", r["items"][0]["mortarVolume"] >= 0, True)
    finally:
        quantities.acad.call = real


def test_mortar_aplica_merma() -> None:
    real = quantities.acad.call
    try:
        modulo = (0.28 + 0.015) * (0.07 + 0.015)
        area = modulo * 10
        _mock_areas({"muro": area})
        r = quantities.calculate_quantities([
            {"type": "mortar_volume", "label": "Mortero", "handles": ["muro"],
             "thickness": 0.14, "waste_pct": 10.0},
        ])
        wall_vol = area * 0.14
        brick_vol = 10 * (0.28 * 0.07 * 0.14)
        sin_merma = wall_vol - brick_vol
        check("mortero con 10% de merma",
              r["items"][0]["mortarVolume"], round(sin_merma * 1.10, 4))
    finally:
        quantities.acad.call = real


def test_steel_weight_longitudinal_y_estribos() -> None:
    real = quantities.acad.call
    try:
        _mock_areas({("perim", "estribo1"): 0.5})
        r = quantities.calculate_quantities([
            {"type": "steel_weight", "label": "Castillos K-1", "count": 3,
             "length": 2.5, "long_bars": 4, "long_bar_size": "#3",
             "stirrup_size": "#2", "stirrup_spacing": 0.15,
             "stirrup_handle": "estribo1"},
        ])
        item = r["items"][0]
        kg_long = 3 * 4 * 2.5 * 0.56
        check("longitudinal: count x bars x length x kg/m",
              item["detail"]["longitudinal"]["kg"], round(kg_long, 2))
        num_estribos = 2.5 / 0.15
        import math
        num_estribos = math.ceil(num_estribos) + 1
        kg_estribos = 3 * num_estribos * 0.5 * 0.25
        check("estribos usan el perimetro MEDIDO del handle",
              item["detail"]["estribos"]["perimeter"], 0.5)
        check("kg de estribos", item["detail"]["estribos"]["kg"],
              round(kg_estribos, 2))
        check("peso total = longitudinal + estribos", item["weight"],
              round(kg_long + kg_estribos, 2))
    finally:
        quantities.acad.call = real


def test_steel_weight_aplica_merma() -> None:
    real = quantities.acad.call
    try:
        _mock_areas({("perim", "estribo1"): 0.5})
        r = quantities.calculate_quantities([
            {"type": "steel_weight", "label": "Castillos K-1", "count": 3,
             "length": 2.5, "long_bars": 4, "long_bar_size": "#3",
             "waste_pct": 5.0},
        ])
        kg_sin_merma = 3 * 4 * 2.5 * 0.56
        check("peso con 5% de merma de corte",
              r["items"][0]["weight"], round(kg_sin_merma * 1.05, 2))
    finally:
        quantities.acad.call = real


def test_steel_weight_traslape_por_largo_comercial() -> None:
    real = quantities.acad.call
    try:
        r = quantities.calculate_quantities([
            {"type": "steel_weight", "label": "Trabe larga", "count": 1,
             "length": 20.0, "long_bars": 2, "long_bar_size": "#4",
             "commercial_length": 9.0, "lap_diam_factor": 40},
        ])
        d = r["items"][0]["detail"]["longitudinal"]
        # 20m / 9m comercial => 3 tramos => 2 traslapes por varilla
        check("2 traslapes por varilla (20m / 9m comercial)",
              d["splicesPerBar"], 2)
        lap_len = 0.01270 * 40  # diametro #4 en m x 40 diametros
        check("longitud de cada traslape", d["lapLengthEach"], round(lap_len, 3))
        largo_efectivo = 20.0 + 2 * lap_len
        check("largo efectivo incluye los traslapes",
              d["effectiveLength"], round(largo_efectivo, 3))
        kg_esperado = 1 * 2 * largo_efectivo * 0.994
        check("kg usa el largo efectivo, no el nominal",
              d["kg"], round(kg_esperado, 2))
    finally:
        quantities.acad.call = real


def test_steel_weight_malla_electrosoldada() -> None:
    real = quantities.acad.call
    try:
        _mock_areas({"losa1": 30.0})
        r = quantities.calculate_quantities([
            {"type": "steel_weight", "label": "Malla losa", "handles": ["losa1"],
             "mesh_kg_m2": 2.86, "waste_pct": 3.0},
        ])
        esperado = 30.0 * 2.86 * 1.03
        check("kg de malla = area x kg/m2 (+merma)",
              r["items"][0]["weight"], round(esperado, 2))
        check("total acero_kg incluye la malla",
              r["totals"]["acero_kg"], round(esperado, 3), tol=1e-2)
    finally:
        quantities.acad.call = real


def test_steel_weight_sin_ningun_modo_falla() -> None:
    check_raises(
        "steel_weight sin longitudinal/estribos/malla",
        lambda: quantities.calculate_quantities(
            [{"type": "steel_weight", "label": "X", "count": 1, "length": 1.0}]),
        "al menos uno de los tres")


def test_earthwork_excavacion_con_esponjamiento() -> None:
    real = quantities.acad.call
    try:
        _mock_areas({"z1": 4.0})
        r = quantities.calculate_quantities([
            {"type": "earthwork", "mode": "excavation", "label": "Excavación Z-1",
             "handles": ["z1"], "depth": 0.6, "swell_pct": 25.0},
        ])
        item = r["items"][0]
        check("volumen de banco", item["volume"], 2.4, tol=1e-6)
        check("volumen esponjado para acarreo", item["volumeSwollen"], 3.0, tol=1e-6)
        check("total excavacion_m3 es el de banco",
              r["totals"]["excavacion_m3"], 2.4, tol=1e-3)
    finally:
        quantities.acad.call = real


def test_earthwork_relleno_descuenta_estructura() -> None:
    real = quantities.acad.call
    try:
        _mock_areas({"z1": 4.0})
        r = quantities.calculate_quantities([
            {"type": "earthwork", "mode": "backfill", "label": "Relleno Z-1",
             "handles": ["z1"], "depth": 0.6, "structure_volume": 0.9},
        ])
        check("relleno = excavacion - estructura",
              r["items"][0]["volume"], 2.4 - 0.9, tol=1e-6)
    finally:
        quantities.acad.call = real


def test_earthwork_relleno_nunca_negativo() -> None:
    real = quantities.acad.call
    try:
        _mock_areas({"z1": 1.0})
        r = quantities.calculate_quantities([
            {"type": "earthwork", "mode": "backfill", "label": "Relleno Z-1",
             "handles": ["z1"], "depth": 0.3, "structure_volume": 10.0},
        ])
        check("relleno no baja de 0", r["items"][0]["volume"] >= 0, True)
    finally:
        quantities.acad.call = real


def test_earthwork_mode_invalido_falla() -> None:
    check_raises(
        "earthwork con mode invalido",
        lambda: quantities.calculate_quantities(
            [{"type": "earthwork", "label": "X", "handles": ["a"], "depth": 1.0}]),
        "excavation")


def test_formwork_por_cara_dibujada() -> None:
    real = quantities.acad.call
    try:
        _mock_areas({"losa1": 12.0})
        r = quantities.calculate_quantities([
            {"type": "formwork", "label": "Cimbra losa", "handles": ["losa1"],
             "faces": 1, "waste_pct": 5.0},
        ])
        check("area con merma", r["items"][0]["areaTotal"], 12.0 * 1.05, tol=1e-6)
        check("total cimbra_m2", r["totals"]["cimbra_m2"], round(12.0 * 1.05, 3),
              tol=1e-3)
    finally:
        quantities.acad.call = real


def test_formwork_por_seccion_mide_perimetro_real() -> None:
    real = quantities.acad.call
    try:
        _mock_areas({("perim", "secc1"): 0.9})
        r = quantities.calculate_quantities([
            {"type": "formwork", "label": "Cimbra castillos K-1", "count": 3,
             "length": 2.5, "section_handle": "secc1"},
        ])
        esperado = 3 * 0.9 * 2.5
        check("area = count x perimetro medido x length",
              r["items"][0]["areaTotal"], esperado, tol=1e-6)
    finally:
        quantities.acad.call = real


def test_area_finish_con_manos_y_espesor() -> None:
    real = quantities.acad.call
    try:
        _mock_areas({"muro1": 20.0})
        r = quantities.calculate_quantities([
            {"type": "area_finish", "label": "Aplanado fino", "material": "aplanado",
             "handles": ["muro1"], "coats": 1, "thickness": 0.015,
             "waste_pct": 5.0},
        ])
        item = r["items"][0]
        check("area facturable con merma", item["billableArea"], 20.0 * 1.05,
              tol=1e-6)
        check("volumen = area x espesor (+merma)", item["volume"],
              round(20.0 * 0.015 * 1.05, 4))
        check("total agrupado por material", r["totals"]["aplanado_m2"],
              round(20.0 * 1.05, 3), tol=1e-3)
        check("total en m3 tambien por material", r["totals"]["aplanado_m3"],
              round(20.0 * 0.015 * 1.05, 3), tol=1e-3)
    finally:
        quantities.acad.call = real


def test_area_finish_pintura_con_dos_manos() -> None:
    real = quantities.acad.call
    try:
        _mock_areas({"muro1": 10.0})
        r = quantities.calculate_quantities([
            {"type": "area_finish", "label": "Pintura vinílica",
             "material": "pintura", "handles": ["muro1"], "coats": 2},
        ])
        check("2 manos duplican el area a cubrir",
              r["items"][0]["billableArea"], 20.0, tol=1e-6)
        check("sin thickness no hay volumen", "volume" in r["items"][0], False)
    finally:
        quantities.acad.call = real


def test_area_finish_sin_material_falla() -> None:
    check_raises(
        "area_finish sin material",
        lambda: quantities.calculate_quantities(
            [{"type": "area_finish", "label": "X", "handles": ["a"]}]),
        "material")


def test_steel_weight_size_invalido_falla() -> None:
    check_raises(
        "tamano de varilla no tabulado",
        lambda: quantities.calculate_quantities([
            {"type": "steel_weight", "label": "X", "count": 1, "length": 1.0,
             "long_bars": 4, "long_bar_size": "#99"}]),
        "no está en la tabla")


def test_type_invalido_falla() -> None:
    check_raises(
        "type desconocido",
        lambda: quantities.calculate_quantities(
            [{"type": "no_existe", "label": "X"}]),
        "type tiene que ser")


def test_muchos_handles_iguales_colapsa_la_formula() -> None:
    """35 castillos idénticos (0.0225 m² cada uno) escritos uno por uno
    necesitan una columna de 50 m -- inservible en cualquier tabla real. Con
    más de 4 handles del mismo valor tiene que colapsar a 'Nxvalor', y si los
    valores difieren (aunque sean muchos) seguir mostrando cada uno."""
    handles = [f"C{i}" for i in range(35)]
    real = quantities.acad.call
    try:
        _mock_areas({h: 0.0225 for h in handles})
        r = quantities.calculate_quantities([
            {"type": "concrete_volume", "label": "Castillos C-1",
             "handles": handles, "depth": 2.6, "waste_pct": 5.0},
        ])
        formula = quantities._fmt_item(r["items"][0])
        check("formula corta, no 35 sumandos", len(formula) < 60, True)
        check("dice cuantos son", "35x0.022" in formula, True)
    finally:
        quantities.acad.call = real

    real = quantities.acad.call
    try:
        _mock_areas({"A": 0.30, "B": 0.45, "C": 0.60, "D": 0.75, "E": 0.90})
        r = quantities.calculate_quantities([
            {"type": "concrete_volume", "label": "Zapatas distintas",
             "handles": ["A", "B", "C", "D", "E"], "depth": 0.2},
        ])
        formula = quantities._fmt_item(r["items"][0])
        check("con valores distintos no colapsa", formula.count("+"), 4)
    finally:
        quantities.acad.call = real


def test_create_quantities_table_no_recalcula() -> None:
    real = quantities.acad.call
    try:
        _mock_areas({"K1": 0.375})
        r = quantities.calculate_quantities([
            {"type": "concrete_volume", "label": "Castillo", "handles": ["K1"],
             "depth": 0.15},
        ])
        preview.DRAWN.clear()
        quantities.create_quantities_table(0.0, 0.0, r, text_height=0.12)
        textos = [e["text"] for e in preview.DRAWN if e["cmd"] == "create_text"]
        check("la fila del item aparece en la tabla",
              any("Castillo" == t for t in textos), True)
        check("el total tambien aparece", any("TOTAL CONCRETO" in t for t in textos), True)
    finally:
        quantities.acad.call = real


def test_export_quantities_csv_no_recalcula() -> None:
    import csv
    import os
    import tempfile

    real = quantities.acad.call
    try:
        _mock_areas({"K1": 0.375})
        r = quantities.calculate_quantities([
            {"type": "concrete_volume", "label": "Castillo", "handles": ["K1"],
             "depth": 0.15},
        ])
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            out = quantities.export_quantities_csv(r, path)
            check("devuelve la ruta", out["path"], path)
            check("cuenta las filas de items", out["rows"], 1)
            with open(path, encoding="utf-8-sig") as fh:
                filas = list(csv.reader(fh))
            check("encabezado correcto", filas[0][0], "CONCEPTO")
            check("la fila del item aparece", filas[1][0], "Castillo")
            check("la cantidad es la misma que calculate_quantities",
                  float(filas[1][4]), r["items"][0]["volume"])
            check("hay una fila de totales",
                  any(f and f[0] == "TOTAL CONCRETO" for f in filas), True)
        finally:
            os.remove(path)
    finally:
        quantities.acad.call = real


def main() -> int:
    for fn in [test_concrete_volume_suma_areas_reales,
               test_concrete_mix_desde_volumen_ya_calculado,
               test_concrete_mix_redondea_bolsas_hacia_arriba,
               test_concrete_mix_coeficientes_propios,
               test_concrete_mix_midiendo_handles_igual_que_concrete_volume,
               test_concrete_mix_sin_volumen_ni_handles_falla,
               test_concrete_volume_aplica_merma,
               test_concrete_volume_sin_depth_falla,
               test_brick_count_usa_modulo_y_merma,
               test_mortar_es_diferencia_real,
               test_mortar_aplica_merma,
               test_steel_weight_longitudinal_y_estribos,
               test_steel_weight_aplica_merma,
               test_steel_weight_traslape_por_largo_comercial,
               test_steel_weight_malla_electrosoldada,
               test_steel_weight_sin_ningun_modo_falla,
               test_steel_weight_size_invalido_falla,
               test_earthwork_excavacion_con_esponjamiento,
               test_earthwork_relleno_descuenta_estructura,
               test_earthwork_relleno_nunca_negativo,
               test_earthwork_mode_invalido_falla,
               test_formwork_por_cara_dibujada,
               test_formwork_por_seccion_mide_perimetro_real,
               test_area_finish_con_manos_y_espesor,
               test_area_finish_pintura_con_dos_manos,
               test_area_finish_sin_material_falla,
               test_type_invalido_falla,
               test_muchos_handles_iguales_colapsa_la_formula,
               test_create_quantities_table_no_recalcula,
               test_export_quantities_csv_no_recalcula]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: cuantificacion mide, no supone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
