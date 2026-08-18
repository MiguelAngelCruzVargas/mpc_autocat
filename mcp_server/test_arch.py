"""Tests de arch.py contra el socket mockeado. NO necesita AutoCAD.

Verifica lo que no se ve a simple vista en el preview: que los tramos de muro
se partan donde van, que el abatimiento de las puertas barra 90 grados y no
270, y que los huecos mal puestos den un error claro en vez de dibujar algo roto.

Uso:  python test_arch.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import arch  # noqa: E402

FAILED: list[str] = []


def check(name: str, got, expected, tol: float = 1e-6) -> None:
    ok = (abs(got - expected) <= tol
          if isinstance(expected, float) else got == expected)
    if not ok:
        FAILED.append(f"{name}: esperaba {expected}, obtuve {got}")
    print(("  ok  " if ok else " FALLA ") + name)


def check_raises(name: str, fn, fragment: str) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - queremos cualquier error
        if fragment.lower() in str(exc).lower():
            print("  ok  " + name)
            return
        FAILED.append(f"{name}: error sin el texto {fragment!r}: {exc}")
    else:
        FAILED.append(f"{name}: no dio error")
    print(" FALLA " + name)


def arcs() -> list[dict]:
    return [e for e in preview.DRAWN if e["cmd"] == "create_arc"]


def sweep(arc: dict) -> float:
    return (arc["endAngleDeg"] - arc["startAngleDeg"]) % 360.0


def test_muro_recto():
    preview.DRAWN.clear()
    r = arch.create_walls([[0, 0], [10, 0]], thickness=0.15)
    check("un solo tramo", len(r["wallHandles"]), 1)
    check("largo del eje", r["axisLength"], 10.0)
    poly = [e for e in preview.DRAWN if e["cmd"] == "create_polyline"][0]
    check("contorno de 4 vertices", len(poly["points"]), 4)
    check("contorno cerrado", poly["closed"], True)


def test_muro_con_hueco():
    preview.DRAWN.clear()
    r = arch.create_walls(
        [[0, 0], [10, 0]], thickness=0.15,
        openings=[{"distance": 5.0, "width": 1.0, "type": "pass"}])
    check("se parte en dos tramos", len(r["wallHandles"]), 2)
    polys = [e for e in preview.DRAWN if e["cmd"] == "create_polyline"]
    xs_primero = [p[0] for p in polys[0]["points"]]
    check("primer tramo termina en el hueco", max(xs_primero), 4.5)
    xs_segundo = [p[0] for p in polys[1]["points"]]
    check("segundo tramo arranca tras el hueco", min(xs_segundo), 5.5)


def test_perimetro_cerrado():
    preview.DRAWN.clear()
    r = arch.create_walls([[0, 0], [10, 0], [10, 8], [0, 8]],
                          thickness=0.15, closed=True)
    check("perimetro sin huecos: dos anillos", len(r["wallHandles"]), 2)
    check("largo del perimetro", r["axisLength"], 36.0)


def test_perimetro_con_huecos_no_deja_junta():
    """Con huecos, el tramo que cruza el punto de arranque debe ser UNO solo."""
    preview.DRAWN.clear()
    r = arch.create_walls(
        [[0, 0], [10, 0], [10, 8], [0, 8]], thickness=0.15, closed=True,
        openings=[{"distance": 5.0, "width": 1.0, "type": "pass"},
                  {"distance": 20.0, "width": 1.0, "type": "pass"}])
    # 2 huecos en un anillo -> 2 tramos, no 3 (el de arranque se fusiona).
    check("dos huecos -> dos tramos", len(r["wallHandles"]), 2)


def test_abatimiento_siempre_90():
    """Las 4 combinaciones de jamba y lado tienen que barrer 90 grados."""
    for swing in ("left", "right"):
        for side in ("left", "right"):
            preview.DRAWN.clear()
            arch.create_walls(
                [[0, 0], [10, 0]], thickness=0.15,
                openings=[{"distance": 5.0, "width": 0.9, "type": "door",
                           "swing": swing, "side": side}])
            got = arcs()
            if len(got) != 1:
                FAILED.append(f"abatimiento {swing}/{side}: {len(got)} arcos")
                print(f" FALLA abatimiento {swing}/{side}: {len(got)} arcos")
                continue
            check(f"abatimiento {swing}/{side} barre 90", sweep(got[0]), 90.0,
                  tol=1e-6)


def test_puerta_abre_del_lado_pedido():
    preview.DRAWN.clear()
    arch.create_walls(
        [[0, 0], [10, 0]], thickness=0.15,
        openings=[{"distance": 5.0, "width": 0.9, "type": "door",
                   "swing": "left", "side": "left"}])
    hoja = [e for e in preview.DRAWN if e["cmd"] == "create_line"][0]
    # Muro horizontal, lado izquierdo = +Y: la hoja sube.
    check("la hoja abre hacia +Y", hoja["y2"] > hoja["y1"], True)
    check("la hoja mide el ancho del hueco", hoja["y2"] - hoja["y1"], 0.9)


def test_ventana():
    preview.DRAWN.clear()
    arch.create_walls(
        [[0, 0], [10, 0]], thickness=0.15,
        openings=[{"distance": 5.0, "width": 1.5, "type": "window"}])
    lineas = [e for e in preview.DRAWN if e["cmd"] == "create_line"]
    check("la ventana dibuja el vidrio con 2 lineas", len(lineas), 2)
    check("el vidrio cruza todo el hueco", lineas[0]["x2"] - lineas[0]["x1"], 1.5)


def test_errores_claros():
    check_raises(
        "hueco fuera del muro",
        lambda: arch.create_walls(
            [[0, 0], [5, 0]], thickness=0.15,
            openings=[{"distance": 20.0, "width": 1.0}]),
        "se sale del muro")
    check_raises(
        "huecos encimados",
        lambda: arch.create_walls(
            [[0, 0], [10, 0]], thickness=0.15,
            openings=[{"distance": 5.0, "width": 2.0},
                      {"distance": 6.0, "width": 2.0}]),
        "se pisan")
    check_raises(
        "espesor invalido",
        lambda: arch.create_walls([[0, 0], [10, 0]], thickness=0),
        "thickness")


def test_ejes():
    preview.DRAWN.clear()
    r = arch.create_axis_grid(x_positions=[0, 5, 10], y_positions=[0, 8])
    check("ejes verticales numerados", r["verticalAxes"], ["1", "2", "3"])
    check("ejes horizontales con letras", r["horizontalAxes"], ["A", "B"])
    check("un globo en cada extremo", len(r["bubbles"]), 10)


def test_letras_de_eje():
    check("eje 0 -> A", arch._letter(0), "A")
    check("eje 25 -> Z", arch._letter(25), "Z")
    check("eje 26 -> AA", arch._letter(26), "AA")


def main() -> int:
    for fn in [test_muro_recto, test_muro_con_hueco, test_perimetro_cerrado,
               test_perimetro_con_huecos_no_deja_junta,
               test_abatimiento_siempre_90, test_puerta_abre_del_lado_pedido,
               test_ventana, test_errores_claros, test_ejes,
               test_letras_de_eje]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: muros, huecos y ejes correctos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
