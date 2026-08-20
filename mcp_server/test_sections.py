"""Tests de sections.py contra el socket mockeado. NO necesita AutoCAD.

Verifica lo que no se ve a simple vista: que las cotas de nivel se acumulen
bien piso a piso, que un vano o un muro cortado fuera de rango no se dibuje
en silencio, que 'fachada' nunca dibuje losas, y que un patrón de achurado
que falla no tumbe el corte entero.

Uso:  python test_sections.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import autocad_client as acad  # noqa: E402
import sections  # noqa: E402
import space  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def check_raises(name: str, fn, fragment: str) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - queremos cualquier error
        if fragment.lower() in str(exc).lower():
            print("  ok  " + name)
            return
        FAILED.append(f"{name}: error sin el texto {fragment!r}: {exc}")
        print(" FALLA " + name)
        return
    FAILED.append(f"{name}: no dio error")
    print(" FALLA " + name)


def limpiar() -> None:
    preview.DRAWN.clear()
    space.clear()
    space.set_scale(0.05)  # 1:50 en metros


UNA_CASA = [
    {"name": "PB", "height": 2.90, "slab_thickness": 0.12, "elements": [
        {"type": "cut_wall", "x": 0.15, "thickness": 0.15},
        {"type": "cut_wall", "x": 6.30, "thickness": 0.15},
        {"type": "door", "x_start": 3.80, "x_end": 4.70, "head": 2.10},
    ]},
    {"name": "PA", "height": 2.70, "slab_thickness": 0.12, "elements": [
        {"type": "cut_wall", "x": 0.15, "thickness": 0.15},
        {"type": "cut_wall", "x": 6.30, "thickness": 0.15},
        {"type": "window", "x_start": 1.20, "x_end": 2.60, "sill": 0.90, "head": 2.10},
    ]},
]


def test_niveles_acumulados() -> None:
    limpiar()
    r = sections.create_building_section(0.0, 0.0, 6.45, UNA_CASA)
    cotas = [n["elevation"] for n in r["levels"]]
    check("arranca en 0.00", cotas[0] == 0.0, str(cotas))
    check("PA arranca a 2.90", abs(cotas[1] - 2.90) < 1e-9, str(cotas))
    check("remate a 5.60", abs(cotas[2] - 5.60) < 1e-9, str(cotas))
    check("totalHeight coincide", abs(r["totalHeight"] - 5.60) < 1e-9,
          str(r["totalHeight"]))
    check("3 niveles devueltos", len(r["levels"]) == 3, str(r["levels"]))


def test_cut_wall_pisados() -> None:
    limpiar()
    story = [{"name": "PB", "height": 2.90, "slab_thickness": 0.0, "elements": [
        {"type": "cut_wall", "x": 1.00, "thickness": 0.30},
        {"type": "cut_wall", "x": 1.10, "thickness": 0.30},
    ]}]
    check_raises("dos cut_wall que se pisan",
                 lambda: sections.create_building_section(0, 0, 5.0, story),
                 "se pisan")


def test_elemento_fuera_de_rango() -> None:
    limpiar()
    story = [{"name": "PB", "height": 2.90, "slab_thickness": 0.0, "elements": [
        {"type": "window", "x_start": 4.5, "x_end": 5.5, "sill": 0.9, "head": 2.1},
    ]}]
    check_raises("ventana que se sale del corte",
                 lambda: sections.create_building_section(0, 0, 5.0, story),
                 "se sale del corte")


def test_sill_mayor_que_head() -> None:
    limpiar()
    story = [{"name": "PB", "height": 2.90, "slab_thickness": 0.0, "elements": [
        {"type": "window", "x_start": 1.0, "x_end": 2.0, "sill": 2.0, "head": 1.0},
    ]}]
    check_raises("sill >= head",
                 lambda: sections.create_building_section(0, 0, 5.0, story),
                 "sill")


def test_fachada_no_dibuja_losas() -> None:
    limpiar()
    r = sections.create_building_section(0.0, 0.0, 6.45, UNA_CASA, view="fachada")
    check("ningun slabHandle en fachada",
          all(s["slabHandle"] is None for s in r["storyHandles"]),
          str(r["storyHandles"]))
    hatches = [e for e in preview.DRAWN if e["cmd"] == "create_hatch"]
    check("fachada no achura nada", len(hatches) == 0, str(len(hatches)))


def test_cotas_de_nivel() -> None:
    limpiar()
    r = sections.create_building_section(0.0, 0.0, 6.45, UNA_CASA,
                                         dimension_stories=True)
    dims = r["storyDimensions"]
    check("hay cadena de cotas", dims is not None)
    check("una cota por nivel", len(dims["handles"]) == len(UNA_CASA),
          str(dims))
    esperado = [round(n["elevation"], 3) for n in r["levels"]]
    ys_cadena = [round(e["y1"], 3) for e in preview.DRAWN
                if e["cmd"] == "create_line"]
    # Las tres cotas de la cadena arrancan/terminan en cada nivel: basta con
    # que cada cota aparezca al menos una vez entre los puntos dibujados.
    check("las cotas tocan cada nivel",
          all(any(abs(y - e) < 1e-6 for y in ys_cadena) for e in esperado),
          f"esperado {esperado}, dibujado {ys_cadena}")


def test_hatch_que_falla_no_tumba_el_corte() -> None:
    limpiar()
    real = acad.call

    def falla_hatch(cmd, params=None):
        if cmd == "create_hatch":
            raise acad.AutoCadError("patron inexistente")
        return real(cmd, params)

    sections.acad.call = falla_hatch
    try:
        r = sections.create_building_section(0.0, 0.0, 6.45, UNA_CASA)
        check("el corte se dibuja igual", len(r["storyHandles"]) == 2,
              str(r["storyHandles"]))
    finally:
        sections.acad.call = real


def main() -> int:
    for fn in [test_niveles_acumulados, test_cut_wall_pisados,
               test_elemento_fuera_de_rango, test_sill_mayor_que_head,
               test_fachada_no_dibuja_losas, test_cotas_de_nivel,
               test_hatch_que_falla_no_tumba_el_corte]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: cortes y fachadas correctos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
