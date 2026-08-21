"""Tests de check_retaining_wall (rules.py): proporción preliminar de un
muro de contención por empuje activo de Rankine. NO necesita AutoCAD -- es
puro cálculo.

Uso:  python test_retaining.py
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


def test_h35_da_proporciones_defendibles() -> None:
    """El caso del dictado: 3.5 m de tierra. No puede salir un muro de 15cm
    (el espesor de un tabique interior) ni una base angosta -- y los dos
    factores de seguridad tienen que quedar realmente cumplidos, no solo
    'ok' porque el loop se cansó de iterar."""
    r = rules.check_retaining_wall(height=3.5)
    check("da ok", r["ok"], str(r))
    check("el vastago no es un muro de tabique",
          r["stemThickness"] >= 0.25, r["stemThickness"])
    check("la base es mas ancha que el vastago",
          r["baseWidth"] > r["stemThickness"] * 2, r)
    check("factor de volteo cumple el minimo",
          r["fsOverturning"] >= 1.5, r["fsOverturning"])
    check("factor de deslizamiento cumple el minimo",
          r["fsSliding"] >= 1.5, r["fsSliding"])


def test_muro_mas_alto_pide_mas_base() -> None:
    """Monotonía básica: el empuje crece con el cuadrado de la altura, asi
    que un muro de 5 m no puede resolverse con la misma base que uno de 2."""
    bajo = rules.check_retaining_wall(height=2.0)
    alto = rules.check_retaining_wall(height=5.0)
    check("el muro alto pide mas base",
          alto["baseWidth"] > bajo["baseWidth"],
          f"2m -> {bajo['baseWidth']}, 5m -> {alto['baseWidth']}")
    check("el muro alto empuja mas",
          alto["activeThrust_kg_per_m"] > bajo["activeThrust_kg_per_m"],
          (alto["activeThrust_kg_per_m"], bajo["activeThrust_kg_per_m"]))


def test_sobrecarga_agranda_la_base() -> None:
    """Una cochera o banqueta cargando encima del relleno aumenta el empuje
    activo, asi que la misma altura necesita mas base que sin sobrecarga."""
    sin = rules.check_retaining_wall(height=3.0, surcharge=0.0)
    con = rules.check_retaining_wall(height=3.0, surcharge=1500.0)
    check("la sobrecarga no reduce la base",
          con["baseWidth"] >= sin["baseWidth"],
          f"sin -> {sin['baseWidth']}, con -> {con['baseWidth']}")


def test_tope_de_base_imposible_avisa_en_vez_de_inventar() -> None:
    """Si max_base_width no alcanza para los factores de seguridad, tiene
    que avisar CON el numero que le faltó -- no devolver ok=True con un
    factor de seguridad que en realidad no se cumple."""
    r = rules.check_retaining_wall(height=3.5, max_base_width=0.60)
    check("no da ok", not r["ok"], str(r))
    check("explica cual factor no cumplio",
          any(p["rule"] in ("volteo", "deslizamiento") for p in r["problems"]),
          r["problems"])
    check("se quedo en el tope pedido",
          r["baseWidth"] <= 0.60 + 1e-9, r["baseWidth"])


def test_altura_invalida() -> None:
    try:
        rules.check_retaining_wall(height=0.0)
        check("rechaza altura 0", False, "no elevo excepcion")
    except ValueError:
        check("rechaza altura 0", True)


def main() -> int:
    for fn in [test_h35_da_proporciones_defendibles,
               test_muro_mas_alto_pide_mas_base,
               test_sobrecarga_agranda_la_base,
               test_tope_de_base_imposible_avisa_en_vez_de_inventar,
               test_altura_invalida]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: check_retaining_wall proporciona muros de contencion "
          "verificados, no a ojo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
