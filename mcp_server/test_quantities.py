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


def main() -> int:
    for fn in [test_concrete_volume_suma_areas_reales,
               test_concrete_volume_sin_depth_falla,
               test_brick_count_usa_modulo_y_merma,
               test_mortar_es_diferencia_real,
               test_steel_weight_longitudinal_y_estribos,
               test_steel_weight_size_invalido_falla,
               test_type_invalido_falla,
               test_create_quantities_table_no_recalcula]:
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
