"""Tests de check_bridge_girder (rules.py): trabe de puente bajo carga de
carril HS20-44 (AASHTO). NO necesita AutoCAD -- puro calculo.

Uso:  python test_bridge_girder.py
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


def test_claro_14m_da_algo_razonable() -> None:
    """El caso del dictado: 14 m de claro, tráfico pesado real (HS20-44,
    no una carga viva inventada)."""
    r = rules.check_bridge_girder(span=14.0, girder_spacing=2.0)
    check("da ok", r["ok"], str(r))
    check("peralte de trabe cargada, no de losa liviana",
          0.8 <= r["depth"] <= 2.0, r["depth"])
    check("cuantia dentro del maximo", r["steelRatio"] <= 0.016, r["steelRatio"])
    check("el factor de impacto esta acotado a 0.3",
          r["impactFactor"] <= 0.3, r["impactFactor"])


def test_claro_mayor_pide_mas_peralte() -> None:
    corto = rules.check_bridge_girder(span=8.0, girder_spacing=2.0)
    largo = rules.check_bridge_girder(span=18.0, girder_spacing=2.0)
    check("mas claro pide mas peralte",
          largo["depth"] > corto["depth"],
          f"8m -> {corto['depth']}, 18m -> {largo['depth']}")
    check("mas claro pide mas acero",
          largo["mainSteelArea_cm2"] > corto["mainSteelArea_cm2"],
          (corto["mainSteelArea_cm2"], largo["mainSteelArea_cm2"]))


def test_menos_separacion_entre_trabes_reduce_la_carga_por_trabe() -> None:
    """Mas trabes (separacion menor) reparten la misma carga de carril
    entre mas elementos -- cada uno lleva menos momento."""
    separadas = rules.check_bridge_girder(span=14.0, girder_spacing=3.0)
    juntas = rules.check_bridge_girder(span=14.0, girder_spacing=1.5)
    check("menos separacion, menos momento vivo por trabe",
          juntas["liveLoadMoment_kgm"] < separadas["liveLoadMoment_kgm"],
          (juntas["liveLoadMoment_kgm"], separadas["liveLoadMoment_kgm"]))


def test_claro_invalido() -> None:
    try:
        rules.check_bridge_girder(span=0.0, girder_spacing=2.0)
        check("rechaza span 0", False, "no elevo excepcion")
    except ValueError:
        check("rechaza span 0", True)


def main() -> int:
    for fn in [test_claro_14m_da_algo_razonable,
               test_claro_mayor_pide_mas_peralte,
               test_menos_separacion_entre_trabes_reduce_la_carga_por_trabe,
               test_claro_invalido]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: check_bridge_girder dimensiona trabes con carga vehicular "
          "real, no una carga viva inventada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
