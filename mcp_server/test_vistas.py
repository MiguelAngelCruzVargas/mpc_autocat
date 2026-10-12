"""check_view_titles sin AutoCAD: el agrupado del modelo en vistas.

Salió en un proyecto real: plantas y secciones sin nombre en el modelo, y
nadie sabía qué eran. Estas pruebas fijan que una vista sin título se
reporte, que un título separado de su dibujo cuente, y que dos vistas
lejanas no se fundan en una.

Uso:  python test_vistas.py
"""
from __future__ import annotations

import sys

import vistas

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def _planta(x0: float, y0: float, capa: str = "MUROS") -> list[dict]:
    """Una 'planta' de 10x10: cuatro muros y una cota."""
    return [{"layer": capa, "box": [x0, y0, x0 + 10, y0 + 0.2]},
            {"layer": capa, "box": [x0, y0, x0 + 0.2, y0 + 10]},
            {"layer": capa, "box": [x0 + 9.8, y0, x0 + 10, y0 + 10]},
            {"layer": capa, "box": [x0, y0 + 9.8, x0 + 10, y0 + 10]},
            {"layer": "COTAS", "box": [x0, y0 - 1.0, x0 + 10, y0 - 0.6]}]


def _titulo(x: float, y: float, texto: str) -> list[dict]:
    return [{"layer": "TITULOS", "box": [x, y, x + 6, y + 0.4], "text": texto},
            {"layer": "TITULOS", "box": [x, y - 0.1, x + 6, y - 0.05]}]


def test_vista_sin_titulo() -> None:
    ents = _planta(0, 0) + _titulo(0, 10.8, "PLANTA BAJA") + _planta(40, 0)
    r = vistas.revisar(ents, gap=1.5)
    check("dos vistas", r["views"] == 2, str(r["views"]))
    check("una sin título", len(r["untitled"]) == 1, str(r["untitled"]))
    check("la sin título es la de x=40", r["untitled"] and r["untitled"][0]["box"][0] == 40.0,
          str(r["untitled"]))
    check("problema con su caja", "caja [40.0" in r["problems"][0]["problem"],
          r["problems"][0]["problem"])


def test_titulo_separado_cuenta() -> None:
    # El título quedó 4 m arriba de la planta (más que el gap): igual la titula.
    ents = _planta(0, 0) + _titulo(0, 14.0, "CORTE A-A")
    r = vistas.revisar(ents, gap=1.5)
    check("titulada por cercanía", r["ok"], str(r))


def test_trazos_sueltos_aparte() -> None:
    ents = _planta(0, 0) + _titulo(0, 10.8, "PLANTA") + [
        {"layer": "0", "box": [100, 100, 101, 101]}]
    r = vistas.revisar(ents, gap=1.5)
    check("un trazo suelto no es 'vista sin título'", r["ok"], str(r["problems"]))
    check("pero sale en loose", len(r["loose"]) == 1, str(r["loose"]))


def test_cajon_no_cuenta() -> None:
    ents = _planta(0, 0) + _titulo(0, 10.8, "PLANTA") + [
        {"layer": "CAJON", "box": [-5, -5, 60, 40]}]
    r = vistas.revisar(ents, gap=1.5)
    check("el cajón no funde todo ni cuenta como vista", r["ok"] and r["views"] == 1, str(r))


def test_tabla_con_titulo_propio() -> None:
    tabla = [{"layer": "CUADRO-CONSTRUCCION", "box": [50, 0, 60, 0.4],
              "text": "CUADRO DE CONSTRUCCIÓN"}] + [
        {"layer": "CUADRO-CONSTRUCCION", "box": [50, -k * 0.5, 60, -k * 0.5 + 0.05]}
        for k in range(1, 8)]
    r = vistas.revisar(_planta(0, 0) + _titulo(0, 10.8, "PLANTA") + tabla, gap=1.5)
    check("una tabla con su título no es vista sin nombre", r["ok"], str(r["problems"]))


def main() -> int:
    for t in (test_vista_sin_titulo, test_titulo_separado_cuenta, test_trazos_sueltos_aparte,
              test_cajon_no_cuenta, test_tabla_con_titulo_propio):
        print(t.__name__)
        t()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" - " + f)
        return 1
    print("\nOK: títulos de vista.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
