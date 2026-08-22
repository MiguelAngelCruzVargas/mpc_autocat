"""Tests de check_drawing_hygiene (server.py) contra el socket mockeado.
NO necesita AutoCAD.

Verifica que detecte capas sin usar, estilos de texto todavía en .shx, y
entidades duplicadas exactas — y que NO invente ningún problema cuando el
dibujo está limpio.

Uso:  python test_hygiene.py
"""
from __future__ import annotations

import sys

import server

FAILED: list[str] = []


def check(name: str, got, expected) -> None:
    ok = got == expected
    if not ok:
        FAILED.append(f"{name}: esperaba {expected!r}, obtuve {got!r}")
    print(("  ok  " if ok else " FALLA ") + name)


def _mock(layers, entities, styles, geometry) -> None:
    """geometry: handle -> dict con lo que devolvería get_entity."""
    def fake(cmd, params=None):
        params = params or {}
        if cmd == "list_layers":
            return {"layers": layers}
        if cmd == "list_entities":
            return {"entities": entities}
        if cmd == "list_styles":
            return {"textStyles": styles}
        if cmd == "get_entity":
            return geometry[params["handle"]]
        raise AssertionError(f"comando no mockeado: {cmd}")
    server.acad.call = fake


def test_dibujo_limpio_no_inventa_problemas() -> None:
    real = server.acad.call
    try:
        _mock(
            layers=[{"name": "0"}, {"name": "MUROS"}, {"name": "COTAS"}],
            entities=[{"handle": "A1", "type": "Line", "layer": "MUROS"},
                     {"handle": "A2", "type": "Line", "layer": "COTAS"}],
            styles=[{"name": "ROTULOS", "font": "arial.ttf"}],
            geometry={
                "A1": {"startPoint": [0, 0, 0], "endPoint": [1, 0, 0]},
                "A2": {"startPoint": [0, 1, 0], "endPoint": [1, 1, 0]},
            },
        )
        r = server.check_drawing_hygiene()
        check("ok=True sin nada que avisar", r["ok"], True)
        check("sin capas vacias", r["emptyLayers"], [])
        check("sin estilos shx", r["shxTextStyles"], [])
        check("sin duplicados", r["duplicates"], [])
    finally:
        server.acad.call = real


def test_detecta_capa_sin_usar() -> None:
    real = server.acad.call
    try:
        _mock(
            layers=[{"name": "0"}, {"name": "MUROS"}, {"name": "FANTASMA"}],
            entities=[{"handle": "A1", "type": "Line", "layer": "MUROS"}],
            styles=[],
            geometry={"A1": {"startPoint": [0, 0, 0], "endPoint": [1, 0, 0]}},
        )
        r = server.check_drawing_hygiene()
        check("detecta la capa sin entidades", r["emptyLayers"], ["FANTASMA"])
        check("la capa '0' no cuenta como huerfana", "0" in r["emptyLayers"], False)
        check("ok=False con algo que avisar", r["ok"], False)
    finally:
        server.acad.call = real


def test_detecta_estilo_shx() -> None:
    real = server.acad.call
    try:
        _mock(
            layers=[{"name": "0"}],
            entities=[],
            styles=[{"name": "Standard", "font": "txt.shx"},
                   {"name": "ROTULOS", "font": "arial.ttf"}],
            geometry={},
        )
        r = server.check_drawing_hygiene()
        check("detecta el estilo en txt.shx", r["shxTextStyles"], ["Standard"])
    finally:
        server.acad.call = real


def test_detecta_duplicados_exactos() -> None:
    real = server.acad.call
    try:
        _mock(
            layers=[{"name": "0"}, {"name": "MUROS"}],
            entities=[{"handle": "A1", "type": "Line", "layer": "MUROS"},
                     {"handle": "A2", "type": "Line", "layer": "MUROS"},
                     {"handle": "A3", "type": "Circle", "layer": "MUROS"}],
            styles=[],
            geometry={
                "A1": {"startPoint": [0, 0, 0], "endPoint": [5, 0, 0]},
                "A2": {"startPoint": [0, 0, 0], "endPoint": [5, 0, 0]},  # igual a A1
                "A3": {"center": [2, 2, 0], "radius": 1.0},
            },
        )
        r = server.check_drawing_hygiene()
        check("un grupo de duplicados", len(r["duplicates"]), 1)
        check("los dos handles que se pisan", sorted(r["duplicates"][0]["handles"]), ["A1", "A2"])
    finally:
        server.acad.call = real


def test_no_detecta_lineas_distintas_como_duplicadas() -> None:
    real = server.acad.call
    try:
        _mock(
            layers=[{"name": "0"}, {"name": "MUROS"}],
            entities=[{"handle": "A1", "type": "Line", "layer": "MUROS"},
                     {"handle": "A2", "type": "Line", "layer": "MUROS"}],
            styles=[],
            geometry={
                "A1": {"startPoint": [0, 0, 0], "endPoint": [5, 0, 0]},
                "A2": {"startPoint": [0, 1, 0], "endPoint": [5, 1, 0]},
            },
        )
        r = server.check_drawing_hygiene()
        check("lineas distintas no son duplicados", r["duplicates"], [])
    finally:
        server.acad.call = real


def test_muchos_candidatos_saltea_duplicados() -> None:
    real = server.acad.call
    try:
        entidades = [{"handle": f"H{i}", "type": "Line", "layer": "MUROS"}
                    for i in range(5)]
        _mock(
            layers=[{"name": "0"}, {"name": "MUROS"}],
            entities=entidades,
            styles=[],
            geometry={},  # no deberia llamarse get_entity en absoluto
        )
        r = server.check_drawing_hygiene(max_duplicate_check=3)
        check("no hay duplicados calculados (se salteo)", r["duplicates"], [])
        check("avisa por que se salteo",
              any("salteó" in p for p in r["problems"]), True)
    finally:
        server.acad.call = real


def main() -> int:
    for fn in [test_dibujo_limpio_no_inventa_problemas,
               test_detecta_capa_sin_usar,
               test_detecta_estilo_shx,
               test_detecta_duplicados_exactos,
               test_no_detecta_lineas_distintas_como_duplicadas,
               test_muchos_candidatos_saltea_duplicados]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: check_drawing_hygiene detecta basura real, no inventa nada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
