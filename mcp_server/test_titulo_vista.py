"""create_view_title(figure_box=...) contra el socket mockeado.

Salió mirando el modelo: títulos "donde sea" y diminutos al lado de una
planta de 16 m. Con figure_box el título va pegado a su figura, centrado, y
con un alto proporcional a ella.

Uso:  python test_titulo_vista.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import space    # noqa: E402
import symbols  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def test_pegado_y_proporcional() -> None:
    space.set_scale(0.05)                      # 1:50 en metros
    planta = [0.0, 0.0, 16.0, 12.0]
    r = symbols.create_view_title(title="PLANTA ESTRUCTURAL DE ENTREPISO",
                                  scale_text="ESC. 1:50", figure_box=planta)
    x0, y0, x1, y1 = r["box"]
    check("alto proporcional: 2.5 % de 16 m = 0.40", abs(r["height"] - 0.40) < 1e-9,
          str(r["height"]))
    check("centrado bajo la figura", abs((x0 + x1) / 2.0 - 8.0) < 0.05, str(r["box"]))
    check("debajo y pegado (menos de 3 altos de aire)", y1 < 0.0 and -y1 < 3 * r["height"],
          str(r["box"]))
    chica = symbols.create_view_title(title="DETALLE", figure_box=[0, 0, 2.0, 2.0])
    check("figura chica: no baja de 4 mm de papel", abs(chica["height"] - 0.20) < 1e-9,
          str(chica["height"]))
    grande = symbols.create_view_title(title="CONJUNTO", figure_box=[0, 0, 80.0, 40.0])
    check("figura enorme: no pasa de 10 mm de papel", abs(grande["height"] - 0.50) < 1e-9,
          str(grande["height"]))
    arriba = symbols.create_view_title(title="CORTE", figure_box=planta, position="above")
    check("above: arriba de la figura", arriba["box"][1] > 12.0, str(arriba["box"]))


def test_sin_caja_ni_punto_falla() -> None:
    try:
        symbols.create_view_title(title="X")
        check("sin figure_box ni x/y falla", False)
    except ValueError:
        check("sin figure_box ni x/y falla", True)


def main() -> int:
    for t in (test_pegado_y_proporcional, test_sin_caja_ni_punto_falla):
        print(t.__name__)
        t()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" - " + f)
        return 1
    print("\nOK: título pegado a su figura.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
