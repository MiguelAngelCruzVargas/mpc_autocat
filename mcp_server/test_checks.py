"""Tests de check_all (server.py): el reporte que junta TODOS los check_* de
cierre en una sola llamada. NO necesita AutoCAD.

Verifica que junte problemas de checks con formatos distintos (los que
reciben rooms/doors/walls devuelven dicts con rule/problem/fix;
check_drawing_hygiene devuelve strings sueltos) en una sola lista con el
mismo formato, que salte los checks a los que les falta el dato que
necesitan, y que no invente problemas cuando todo está limpio.

Uso:  python test_checks.py
"""
from __future__ import annotations

import sys

import server

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def _mock_dibujo_limpio() -> None:
    """El dibujo activo no tiene nada raro: check_drawing_hygiene sale ok."""
    def fake(cmd, params=None):
        if cmd == "list_layers":
            return {"layers": [{"name": "0"}]}
        if cmd == "list_entities":
            return {"entities": []}
        if cmd == "list_styles":
            return {"textStyles": []}
        if cmd == "list_xrefs":
            return {"xrefs": []}
        raise AssertionError(f"comando no mockeado: {cmd}")
    server.acad.call = fake


def _mock_capa_fantasma() -> None:
    """Una capa creada y nunca usada, para forzar un problema de hygiene."""
    def fake(cmd, params=None):
        if cmd == "list_layers":
            return {"layers": [{"name": "0"}, {"name": "CAPA_FANTASMA"}]}
        if cmd == "list_entities":
            return {"entities": []}
        if cmd == "list_styles":
            return {"textStyles": []}
        if cmd == "list_xrefs":
            return {"xrefs": []}
        raise AssertionError(f"comando no mockeado: {cmd}")
    server.acad.call = fake


def test_junta_problemas_de_layout_y_geometry() -> None:
    """Puerta de calle abriendo a una recamara: tiene que aparecer con
    check='layout', y annotations/hygiene tienen que correr igual aunque no
    tengan nada que ver con rooms/doors."""
    real = server.acad.call
    try:
        _mock_dibujo_limpio()
        rooms = [{"name": "RECAMARA 1", "x0": 0.0, "y0": 0.0, "x1": 3.0, "y1": 3.0}]
        doors = [{"from": "EXTERIOR", "to": "RECAMARA 1", "width": 0.9}]
        r = server.check_all(rooms=rooms, doors=doors)
        check("no ok", not r["ok"], str(r["problems"]))
        origenes = {p["check"] for p in r["problems"]}
        check("aparece el problema de layout", "layout" in origenes, origenes)
        check("annotations corrio igual", "annotations" in r["checks"], r["checks"].keys())
        check("hygiene corrio igual", "hygiene" in r["checks"], r["checks"].keys())
        check("avisa que se salteo walls",
              any("walls" in s for s in r["skipped"]), r["skipped"])
    finally:
        server.acad.call = real


def test_todo_limpio_no_inventa_nada() -> None:
    real = server.acad.call
    try:
        _mock_dibujo_limpio()
        rooms = [
            {"name": "SALA", "x0": 0.0, "y0": 0.0, "x1": 4.0, "y1": 4.0},
            {"name": "COMEDOR", "x0": 4.0, "y0": 0.0, "x1": 7.0, "y1": 4.0},
            {"name": "COCINA", "x0": 4.0, "y0": 4.0, "x1": 7.5, "y1": 7.0},
        ]
        doors = [
            {"from": "EXTERIOR", "to": "SALA", "width": 0.9},
            {"from": "SALA", "to": "COMEDOR", "width": 0.9},
            {"from": "COMEDOR", "to": "COCINA", "width": 0.8},
        ]
        walls = [{"points": [[0.0, 0.0], [7.5, 0.0], [7.5, 7.0], [0.0, 7.0], [0.0, 0.0]],
                  "name": "perimetro"}]
        r = server.check_all(rooms=rooms, doors=doors, walls=walls)
        check("todo limpio da ok", r["ok"], str(r["problems"]))
        check("no se salteo nada", r["skipped"] == [], r["skipped"])
    finally:
        server.acad.call = real


def test_hygiene_se_normaliza_al_mismo_formato() -> None:
    """check_drawing_hygiene devuelve strings sueltos en 'problems'; check_all
    los tiene que envolver en {'check':.., 'problem':..} igual que los demas,
    para poder recorrer TODO con el mismo código."""
    real = server.acad.call
    try:
        _mock_capa_fantasma()
        r = server.check_all()
        de_hygiene = [p for p in r["problems"] if p["check"] == "hygiene"]
        check("encuentra la capa vacia", len(de_hygiene) > 0, r["checks"]["hygiene"])
        check("normaliza a dict con 'problem'",
              all(isinstance(p, dict) and isinstance(p.get("problem"), str)
                  for p in de_hygiene),
              de_hygiene)
        check("layout/geometry se saltearon sin rooms/doors",
              any("layout" in s for s in r["skipped"]), r["skipped"])
    finally:
        server.acad.call = real


def test_xref_roto_es_problema() -> None:
    """Un xref FileNotFound en la máquina de destino deja la lámina sin la
    base de otra disciplina, y hasta ahora nadie lo miraba al cierre."""
    real = server.acad.call
    try:
        def fake(cmd, params=None):
            if cmd == "list_layers":
                return {"layers": [{"name": "0"}]}
            if cmd == "list_entities":
                return {"entities": []}
            if cmd == "list_styles":
                return {"textStyles": []}
            if cmd == "list_xrefs":
                return {"xrefs": [
                    {"name": "ARQ-BASE", "path": "C:/x/arq.dwg",
                     "status": "Resolved", "unloaded": False},
                    {"name": "ESTRUCTURA", "path": "../est.dwg",
                     "status": "FileNotFound", "unloaded": False},
                ]}
            raise AssertionError(f"comando no mockeado: {cmd}")
        server.acad.call = fake
        r = server.check_all()
        de_xrefs = [p for p in r["problems"] if p["check"] == "xrefs"]
        check("el xref roto aparece como problema", len(de_xrefs) == 1,
              r["problems"])
        check("el resuelto no molesta",
              all("ESTRUCTURA" in p["problem"] for p in de_xrefs), de_xrefs)
    finally:
        server.acad.call = real


def main() -> int:
    for fn in [test_junta_problemas_de_layout_y_geometry,
               test_todo_limpio_no_inventa_nada,
               test_hygiene_se_normaliza_al_mismo_formato,
               test_xref_roto_es_problema]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: check_all junta todos los check_* en un solo reporte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
