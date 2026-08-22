"""Tests de check_roof_truss (rules.py): reaccion preliminar de una armadura
de techo a dos aguas sobre sus apoyos, incluido el caso de levantamiento por
succion de viento. NO necesita AutoCAD -- puro calculo.

Uso:  python test_roof_truss.py
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


def test_caso_tipico_da_algo_razonable() -> None:
    """El caso de la nave/cancha techada: 16 m de claro, armaduras cada 6 m,
    sin succion de viento -- la reaccion tiene que ser positiva (hacia
    abajo) y de un orden de magnitud creible para columna de vivienda-obra
    civil chica, no toneladas descabelladas."""
    r = rules.check_roof_truss(span=16.25, truss_spacing=6.0, rise=2.46)
    check("da ok", r["ok"], str(r))
    check("reaccion de gravedad positiva y razonable",
          500.0 <= r["gravityReaction_kg"] <= 15000.0,
          r["gravityReaction_kg"])
    check("sin viento, la reaccion de viento tambien da positiva",
          r["windUpliftReaction_kg"] > 0, r["windUpliftReaction_kg"])


def test_mas_area_tributaria_pide_mas_reaccion() -> None:
    chica = rules.check_roof_truss(span=10.0, truss_spacing=3.0, rise=1.5)
    grande = rules.check_roof_truss(span=16.0, truss_spacing=6.0, rise=2.5)
    check("mas area tributaria pide mas reaccion",
          grande["gravityReaction_kg"] > chica["gravityReaction_kg"],
          (chica["gravityReaction_kg"], grande["gravityReaction_kg"]))


def test_succion_fuerte_da_levantamiento_neto() -> None:
    """El caso real que motiva la funcion: techo liviano + mucha area +
    succion de viento fuerte puede superar al peso propio -- la reaccion
    neta da NEGATIVA (la armadura tira del apoyo hacia arriba) y eso tiene
    que marcar ok=False con una explicacion, no pasar en silencio."""
    r = rules.check_roof_truss(span=16.0, truss_spacing=6.0, rise=2.5,
                               roof_dead_load=15.0, wind_uplift=80.0)
    check("detecta el levantamiento neto", not r["ok"], str(r))
    check("la reaccion de viento da negativa",
          r["windUpliftReaction_kg"] < 0, r["windUpliftReaction_kg"])
    check("explica el motivo",
          any(p["rule"] == "levantamiento por viento" for p in r["problems"]),
          r["problems"])


def test_sin_succion_no_avisa() -> None:
    r = rules.check_roof_truss(span=14.0, truss_spacing=5.0, rise=2.0,
                               wind_uplift=0.0)
    check("no inventa un levantamiento", r["ok"], r["problems"])


def test_span_invalido() -> None:
    try:
        rules.check_roof_truss(span=0.0, truss_spacing=5.0, rise=2.0)
        check("rechaza span 0", False, "no elevo excepcion")
    except ValueError:
        check("rechaza span 0", True)


def main() -> int:
    for fn in [test_caso_tipico_da_algo_razonable,
               test_mas_area_tributaria_pide_mas_reaccion,
               test_succion_fuerte_da_levantamiento_neto,
               test_sin_succion_no_avisa,
               test_span_invalido]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: check_roof_truss calcula la reaccion real (y avisa el "
          "levantamiento por viento) en vez de asumir carga muerta nomas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
