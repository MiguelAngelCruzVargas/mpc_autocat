"""Tests de rebar.py (seccion de columna con estribo y varillas) contra el
socket mockeado. NO necesita AutoCAD.

Uso:  python test_rebar.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import rebar  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def test_solo_esquinas_da_4_varillas() -> None:
    preview.DRAWN.clear()
    r = rebar.create_column_section(x=0.0, y=0.0, width=0.30, depth=0.30)
    check("4 varillas de esquina, sin pedir nada mas",
          r["barCount"] == 4, r["barCount"])
    check("dibuja contorno + estribo + 4 circulos",
          sum(1 for d in preview.DRAWN if d["cmd"] == "create_polyline") == 2,
          preview.DRAWN)
    check("un circulo por varilla",
          sum(1 for d in preview.DRAWN if d["cmd"] == "create_circle") == 4,
          preview.DRAWN)


def test_estribo_queda_adentro_por_el_recubrimiento() -> None:
    r = rebar.create_column_section(x=0.0, y=0.0, width=0.30, depth=0.40,
                                    cover=0.03)
    handle_estribo = r["stirrupHandle"]
    dibujo = [d for d in preview.DRAWN if d["cmd"] == "create_polyline"][-1]
    xs = [p[0] for p in dibujo["points"]]
    ys = [p[1] for p in dibujo["points"]]
    check("el estribo entra adentro de la seccion en X",
          min(xs) > 0.0 and max(xs) < 0.30, (min(xs), max(xs)))
    check("el estribo entra adentro de la seccion en Y",
          min(ys) > 0.0 and max(ys) < 0.40, (min(ys), max(ys)))
    check("devuelve el handle del estribo para quantities",
          handle_estribo is not None, handle_estribo)


def test_varillas_adicionales_por_cara() -> None:
    r = rebar.create_column_section(x=0.0, y=0.0, width=0.30, depth=0.60,
                                    bars_top_bottom=1, bars_left_right=2)
    # 4 esquinas + 1 arriba + 1 abajo + 2 izq + 2 der = 10
    check("cuenta total de varillas",
          r["barCount"] == 10, r["barCount"])
    check("area total = area de una varilla * cantidad",
          abs(r["totalSteelArea_cm2"] - r["singleBarArea_cm2"] * 10) < 0.01,
          r)


def test_rechaza_recubrimiento_que_no_deja_espacio() -> None:
    try:
        rebar.create_column_section(x=0.0, y=0.0, width=0.20, depth=0.20,
                                    cover=0.15)
        check("rechaza cover imposible", False, "no elevo excepcion")
    except ValueError as exc:
        check("rechaza cover imposible", "cover" in str(exc), str(exc))


def test_rechaza_dimensiones_invalidas() -> None:
    try:
        rebar.create_column_section(x=0.0, y=0.0, width=0.0, depth=0.30)
        check("rechaza width 0", False, "no elevo excepcion")
    except ValueError:
        check("rechaza width 0", True)


def test_footing_plan_parrilla_pareja_en_los_dos_sentidos() -> None:
    """Zapata cuadrada 1.50x1.50, varilla @15cm doble armado -- el caso
    real del corte que motiva la funcion."""
    preview.DRAWN.clear()
    r = rebar.create_footing_plan(x=0.0, y=0.0, width=1.50, length=1.50,
                                  bar_spacing_x=0.15, cover=0.05)
    check("hay varillas en los dos sentidos",
          r["barCountX"] >= 2 and r["barCountY"] >= 2, r)
    check("mismo paso en X e Y cuando no se pide otro",
          abs(r["actualSpacingX_m"] - r["actualSpacingY_m"]) < 1e-6, r)
    check("el paso real nunca se pasa del pedido (@15cm es un maximo)",
          r["actualSpacingX_m"] <= 0.15 + 1e-6, r["actualSpacingX_m"])
    check("total de lineas = contorno + parrilla",
          len(preview.DRAWN) == 1 + r["barCountX"] + r["barCountY"],
          (len(preview.DRAWN), r))


def test_footing_plan_espaciamiento_distinto_por_sentido() -> None:
    """Zapata CUADRADA (mismo claro en los dos sentidos) para aislar el
    efecto del espaciamiento: con menos paso en Y, tiene que salir mas
    varillas en Y que en X."""
    r = rebar.create_footing_plan(x=0.0, y=0.0, width=1.5, length=1.5,
                                  bar_spacing_x=0.20, bar_spacing_y=0.10,
                                  cover=0.05)
    check("mas varillas en el sentido de paso mas chico",
          r["barCountY"] > r["barCountX"], r)


def test_footing_plan_con_referencia_de_apoyo_y_esquinas() -> None:
    r = rebar.create_footing_plan(x=0.0, y=0.0, width=1.50, length=1.50,
                                  bar_spacing_x=0.15,
                                  support_width=0.40, support_length=0.40,
                                  corner_bar_leg=0.50)
    check("dibuja la referencia del apoyo",
          r["supportRefHandle"] is not None, r["supportRefHandle"])
    check("4 varillas diagonales de esquina",
          len(r["cornerBarHandles"]) == 4, r["cornerBarHandles"])


def test_footing_plan_totaliza_la_longitud_real() -> None:
    r = rebar.create_footing_plan(x=0.0, y=0.0, width=1.50, length=1.50,
                                  bar_spacing_x=0.15, cover=0.05)
    esperado = (r["barCountX"] * (1.50 - 2 * 0.05)
               + r["barCountY"] * (1.50 - 2 * 0.05))
    check("totalBarLength_m suma largo real x cantidad real",
          abs(r["totalBarLength_m"] - esperado) < 0.01,
          (r["totalBarLength_m"], esperado))


def test_footing_plan_rechaza_valores_invalidos() -> None:
    try:
        rebar.create_footing_plan(x=0.0, y=0.0, width=1.0, length=1.0,
                                  bar_spacing_x=0.0)
        check("rechaza spacing 0", False, "no elevo excepcion")
    except ValueError:
        check("rechaza spacing 0", True)


def main() -> int:
    for fn in [test_solo_esquinas_da_4_varillas,
               test_estribo_queda_adentro_por_el_recubrimiento,
               test_varillas_adicionales_por_cara,
               test_rechaza_recubrimiento_que_no_deja_espacio,
               test_rechaza_dimensiones_invalidas,
               test_footing_plan_parrilla_pareja_en_los_dos_sentidos,
               test_footing_plan_espaciamiento_distinto_por_sentido,
               test_footing_plan_con_referencia_de_apoyo_y_esquinas,
               test_footing_plan_totaliza_la_longitud_real,
               test_footing_plan_rechaza_valores_invalidos]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: rebar.py dibuja la seccion de columna con estribo real "
          "(medible por quantities) y varillas, sin inventar cuantia.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
