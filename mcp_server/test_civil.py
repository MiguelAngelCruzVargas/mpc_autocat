"""Tests de trazado vial contra el socket mockeado. NO necesita AutoCAD.

Cubre lo que se ve mal recien al mirar el plano impreso: que el tramo no se
remate como si la calle terminara ahi, que el numero de cadenamiento no caiga
encima de lo que corre sobre el eje, y que el sentido del flujo se lea sin
buscar un rotulo.

Uso:  python test_civil.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import annotation as ann  # noqa: E402
import civil              # noqa: E402

FAILED: list[str] = []

EJE = [[0.0, 0.0], [40.0, 0.0], [64.748737, 10.251263]]
BUL = [0.0, 0.198912367379658, 0.0]


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def limpiar() -> None:
    preview.DRAWN.clear()


def _polilineas(layer: str) -> list[dict]:
    return [e for e in preview.DRAWN
            if e["cmd"] == "create_polyline" and e.get("layer") == layer]


def test_extremos_cerrados_por_defecto() -> None:
    limpiar()
    civil.create_road(points=EJE, bulges=BUL, width=7.0, curb_width=0.15,
                      sidewalk_width=1.5, draw_axis=False,
                      pavement_layer="CALZ", curb_layer="GUAR",
                      sidewalk_layer="BANQ")
    check("la calzada es un contorno cerrado",
          all(e.get("closed") for e in _polilineas("CALZ")),
          "salio abierta")
    check("una sola polilinea por franja",
          len(_polilineas("CALZ")) == 1 and len(_polilineas("BANQ")) == 2,
          f'calzada {len(_polilineas("CALZ"))}, banquetas {len(_polilineas("BANQ"))}')


def test_extremos_abiertos() -> None:
    """cap_ends=False: la calle sigue mas alla del dibujo, no se remata."""
    limpiar()
    r = civil.create_road(points=EJE, bulges=BUL, width=7.0, curb_width=0.15,
                          sidewalk_width=1.5, draw_axis=False, cap_ends=False,
                          pavement_layer="CALZ", curb_layer="GUAR",
                          sidewalk_layer="BANQ")
    calz = _polilineas("CALZ")
    check("la calzada son sus dos bordes sueltos", len(calz) == 2, str(len(calz)))
    check("ninguno cerrado", not any(e.get("closed") for e in calz))
    check("las banquetas tambien: 2 franjas x 2 bordes",
          len(_polilineas("BANQ")) == 4, str(len(_polilineas("BANQ"))))
    check("las guarniciones igual",
          len(_polilineas("GUAR")) == 4, str(len(_polilineas("GUAR"))))
    check("y las cantidades de obra no cambian",
          abs(r["pavementArea"] - r["length"] * 7.0) < 1e-6,
          str(r["pavementArea"]))


def test_achurado_y_extremos_abiertos_no_conviven() -> None:
    limpiar()
    try:
        civil.create_road(points=EJE, bulges=BUL, width=7.0, cap_ends=False,
                          pavement_pattern="AR-CONC", draw_axis=False)
    except ValueError as exc:
        check("avisa que no se puede achurar sin contorno cerrado",
              "achurar" in str(exc).lower(), str(exc))
    else:
        check("avisa que no se puede achurar sin contorno cerrado", False,
              "no dio error")


def test_label_offset_separa_el_cadenamiento() -> None:
    limpiar()
    ann.create_stationing(points=EJE, bulges=BUL, interval=20.0,
                          text_height=0.4, tick=1.0, station_format="short",
                          label_offset=1.50, layer="CAD")
    # En la tangente inicial el eje va sobre y=0, asi que el numero tiene que
    # quedar a 1.50 exactos por encima.
    en_tangente = [e for e in preview.DRAWN
                   if e["cmd"] == "create_text" and e["x"] < 40.0]
    check("los numeros salen a 1.50 del eje",
          all(abs(e["y"] - 1.50) < 1e-6 for e in en_tangente),
          str([round(e["y"], 3) for e in en_tangente]))
    check("y no quedan sobre el eje",
          all(abs(e["y"]) > 0.5 for e in en_tangente))


def test_flecha_de_flujo() -> None:
    limpiar()
    r = ann.create_flow_arrow(points=EJE, bulges=BUL, positions=[20.0, 55.0],
                              size=1.2, layer="RED")
    puntas = _polilineas("RED")
    check("una punta por posicion", len(puntas) == 2, str(len(puntas)))
    check("son triangulos cerrados",
          all(e.get("closed") and len(e["points"]) == 3 for e in puntas))
    rellenos = [e for e in preview.DRAWN if e["cmd"] == "create_hatch"]
    check("rellenas, no huecas: una por punta", len(rellenos) == 2,
          f"{len(rellenos)} achurados")
    check("con relleno solido",
          all(e.get("pattern") == "SOLID" for e in rellenos),
          str([e.get("pattern") for e in rellenos]))
    p = r["arrows"][0]
    check("la punta cae sobre el eje en el cadenamiento pedido",
          abs(p["y"]) < 1e-6 and abs(p["x"] - 20.0) < 1e-6,
          f'({p["x"]}, {p["y"]})')
    # La punta mira hacia adelante: el vertice va delante de la base.
    v = puntas[0]["points"]
    base = ((v[1][0] + v[2][0]) / 2.0, (v[1][1] + v[2][1]) / 2.0)
    check("apunta en el sentido de avance", v[0][0] > base[0],
          f"punta {v[0]}, base {base}")

    limpiar()
    ann.create_flow_arrow(points=EJE, bulges=BUL, positions=[20.0], size=1.2,
                          reverse=True, layer="RED")
    v = _polilineas("RED")[0]["points"]
    base = ((v[1][0] + v[2][0]) / 2.0, (v[1][1] + v[2][1]) / 2.0)
    check("reverse la da vuelta", v[0][0] < base[0], f"punta {v[0]}, base {base}")


def test_flecha_fuera_del_eje_da_error() -> None:
    limpiar()
    try:
        ann.create_flow_arrow(points=EJE, bulges=BUL, positions=[500.0])
    except ValueError as exc:
        check("avisa si la flecha se sale del eje",
              "se sale" in str(exc).lower(), str(exc))
    else:
        check("avisa si la flecha se sale del eje", False, "no dio error")


def main() -> int:
    for fn in [test_extremos_cerrados_por_defecto, test_extremos_abiertos,
               test_achurado_y_extremos_abiertos_no_conviven,
               test_label_offset_separa_el_cadenamiento,
               test_flecha_de_flujo, test_flecha_fuera_del_eje_da_error]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: remates, cadenamiento y sentido de flujo correctos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
