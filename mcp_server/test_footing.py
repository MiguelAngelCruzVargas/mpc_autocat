"""Tests de check_footing (rules.py): proporción preliminar de una zapata
aislada por capacidad de carga y punzonamiento. NO necesita AutoCAD -- es
puro cálculo.

Uso:  python test_footing.py
"""
from __future__ import annotations

import sys

import rules

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def test_carga_liviana_da_algo_razonable() -> None:
    """Una columna con carga moderada (15 t) no puede pedir una zapata
    gigante ni una minúscula -- y los dos chequeos (carga y punzonamiento)
    tienen que quedar realmente satisfechos."""
    r = rules.check_footing(axial_load=15000.0)
    check("da ok", r["ok"], str(r))
    check("el lado es mayor que la columna",
          r["side"] > 0.30, r["side"])
    check("el lado es un tamaño de vivienda, no una losa",
          0.6 <= r["side"] <= 3.0, r["side"])
    check("no punzona",
          r["punchingShearDemand_kg"] <= r["punchingShearCapacity_kg"],
          (r["punchingShearDemand_kg"], r["punchingShearCapacity_kg"]))


def test_mas_carga_pide_mas_zapata() -> None:
    """Monotonía básica: el doble de carga no puede caber en la misma
    zapata."""
    liviana = rules.check_footing(axial_load=10000.0)
    pesada = rules.check_footing(axial_load=40000.0)
    check("mas carga pide mas lado",
          pesada["side"] > liviana["side"],
          f"10t -> {liviana['side']}, 40t -> {pesada['side']}")
    check("mas carga pide igual o mas peralte",
          pesada["thickness"] >= liviana["thickness"],
          f"10t -> {liviana['thickness']}, 40t -> {pesada['thickness']}")


def test_columna_mas_grande_punzona_menos() -> None:
    """Con la MISMA carga, una columna de sección mayor reparte el
    punzonamiento en un perímetro más largo -- necesita menos (o igual)
    peralte que una columna angosta cargando lo mismo."""
    angosta = rules.check_footing(axial_load=30000.0, column_width=0.25,
                                  column_length=0.25)
    ancha = rules.check_footing(axial_load=30000.0, column_width=0.50,
                                column_length=0.50)
    check("la columna ancha no necesita mas peralte",
          ancha["thickness"] <= angosta["thickness"],
          f"25cm -> {angosta['thickness']}, 50cm -> {ancha['thickness']}")


def test_suelo_flojo_pide_mas_lado() -> None:
    """Bajar la capacidad admisible del suelo (peor terreno) obliga a un
    lado mayor para la misma carga."""
    firme = rules.check_footing(axial_load=20000.0, allow_bearing=20000.0)
    flojo = rules.check_footing(axial_load=20000.0, allow_bearing=8000.0)
    check("el suelo flojo pide mas lado",
          flojo["side"] > firme["side"],
          f"firme -> {firme['side']}, flojo -> {flojo['side']}")


def test_tope_de_lado_imposible_avisa() -> None:
    """Si max_side no alcanza para bajar la presión sobre el suelo, tiene
    que avisar -- no devolver ok=True con la presión real por encima del
    admisible."""
    r = rules.check_footing(axial_load=80000.0, max_side=1.0)
    check("no da ok", not r["ok"], str(r))
    check("explica el motivo",
          any(p["rule"] in ("capacidad de carga", "punzonamiento")
              for p in r["problems"]),
          r["problems"])


def test_carga_invalida() -> None:
    try:
        rules.check_footing(axial_load=0.0)
        check("rechaza carga 0", False, "no elevo excepcion")
    except ValueError:
        check("rechaza carga 0", True)


def main() -> int:
    for fn in [test_carga_liviana_da_algo_razonable,
               test_mas_carga_pide_mas_zapata,
               test_columna_mas_grande_punzona_menos,
               test_suelo_flojo_pide_mas_lado,
               test_tope_de_lado_imposible_avisa,
               test_carga_invalida]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: check_footing dimensiona zapatas verificadas, no a ojo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
