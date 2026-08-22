"""Tests de check_column (rules.py): proporcion preliminar de una columna de
concreto por capacidad axial y esbeltez. NO necesita AutoCAD -- puro calculo.

Uso:  python test_column.py
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


def test_carga_moderada_columna_corta_da_algo_razonable() -> None:
    """Columna de 2.5 m con carga moderada: corta de sobra, tiene que
    cerrar con la seccion de partida o algo cercano."""
    r = rules.check_column(axial_load=15000.0, height=2.5)
    check("da ok", r["ok"], str(r))
    check("seccion de vivienda, no una columna gigante",
          0.20 <= r["width"] <= 0.60, r["width"])
    check("esbeltez de columna corta",
          r["slenderness"] <= 22.0, r["slenderness"])


def test_columna_alta_de_nave_puede_necesitar_mas_seccion() -> None:
    """El caso real que motiva la funcion: una columna de 5 m sin apoyo
    intermedio (nave/cancha techada) con la misma carga que una de 2.5 m
    -- si 30x30 le alcanza en carga a la corta, a la alta la esbeltez la
    puede obligar a crecer aunque la carga axial sea identica."""
    baja = rules.check_column(axial_load=8000.0, height=2.5,
                              width=0.30, depth=0.30, max_side=1.0)
    alta = rules.check_column(axial_load=8000.0, height=5.0,
                              width=0.30, depth=0.30, max_side=1.0)
    check("la columna alta no queda con seccion menor que la baja",
          min(alta["width"], alta["depth"]) >= min(baja["width"], baja["depth"]),
          (baja["width"], alta["width"]))
    check("la columna alta tiene mas esbeltez que la baja para la misma seccion base",
          alta["slenderness"] >= baja["slenderness"] or alta["width"] > baja["width"],
          (baja["slenderness"], alta["slenderness"]))


def test_mas_carga_pide_mas_seccion() -> None:
    liviana = rules.check_column(axial_load=10000.0, height=3.0)
    pesada = rules.check_column(axial_load=60000.0, height=3.0)
    check("mas carga pide seccion mayor o igual",
          pesada["width"] * pesada["depth"] >= liviana["width"] * liviana["depth"],
          (liviana["width"], pesada["width"]))


def test_tope_de_lado_imposible_avisa() -> None:
    """Si max_side no alcanza ni para la capacidad ni para la esbeltez,
    tiene que avisar -- no devolver ok=True a medias."""
    r = rules.check_column(axial_load=200000.0, height=6.0, max_side=0.30)
    check("no da ok", not r["ok"], str(r))
    check("explica el motivo",
          any(p["rule"] in ("capacidad axial", "esbeltez") for p in r["problems"]),
          r["problems"])


def test_carga_invalida() -> None:
    try:
        rules.check_column(axial_load=0.0, height=3.0)
        check("rechaza carga 0", False, "no elevo excepcion")
    except ValueError:
        check("rechaza carga 0", True)


def test_altura_invalida() -> None:
    try:
        rules.check_column(axial_load=10000.0, height=0.0)
        check("rechaza altura 0", False, "no elevo excepcion")
    except ValueError:
        check("rechaza altura 0", True)


def main() -> int:
    for fn in [test_carga_moderada_columna_corta_da_algo_razonable,
               test_columna_alta_de_nave_puede_necesitar_mas_seccion,
               test_mas_carga_pide_mas_seccion,
               test_tope_de_lado_imposible_avisa,
               test_carga_invalida,
               test_altura_invalida]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: check_column distingue columna corta de esbelta, no solo "
          "capacidad axial pura.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
