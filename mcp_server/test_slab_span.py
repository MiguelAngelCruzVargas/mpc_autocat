"""Tests de check_slab_span (rules.py): losa maciza simplemente apoyada,
peralte + acero por flexion. NO necesita AutoCAD -- puro calculo.

Uso:  python test_slab_span.py
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


def test_claro_moderado_da_algo_razonable() -> None:
    r = rules.check_slab_span(span=8.0)
    check("da ok", r["ok"], str(r))
    check("peralte razonable (no una losa de 3 metros)",
          0.3 <= r["thickness"] <= 1.0, r["thickness"])
    check("cuantia dentro del maximo", r["steelRatio"] <= 0.016, r["steelRatio"])


def test_claro_mayor_pide_mas_peralte_y_mas_acero() -> None:
    corto = rules.check_slab_span(span=4.0)
    largo = rules.check_slab_span(span=10.0)
    check("mas claro pide mas peralte",
          largo["thickness"] > corto["thickness"],
          f"4m -> {corto['thickness']}, 10m -> {largo['thickness']}")
    check("mas claro pide mas acero",
          largo["mainSteelArea_cm2_per_m"] > corto["mainSteelArea_cm2_per_m"],
          (corto["mainSteelArea_cm2_per_m"], largo["mainSteelArea_cm2_per_m"]))


def test_mas_carga_viva_pide_mas_acero() -> None:
    liviana = rules.check_slab_span(span=6.0, live_load=200.0)
    pesada = rules.check_slab_span(span=6.0, live_load=800.0)
    check("mas carga pide mas acero",
          pesada["mainSteelArea_cm2_per_m"] > liviana["mainSteelArea_cm2_per_m"],
          (liviana["mainSteelArea_cm2_per_m"], pesada["mainSteelArea_cm2_per_m"]))


def test_claro_invalido() -> None:
    try:
        rules.check_slab_span(span=0.0)
        check("rechaza span 0", False, "no elevo excepcion")
    except ValueError:
        check("rechaza span 0", True)


def main() -> int:
    for fn in [test_claro_moderado_da_algo_razonable,
               test_claro_mayor_pide_mas_peralte_y_mas_acero,
               test_mas_carga_viva_pide_mas_acero,
               test_claro_invalido]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: check_slab_span dimensiona losas entre apoyos verificadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
