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


def test_rumbos_cuadrantales() -> None:
    import math
    check("noreste", civil.rumbo((0, 0), (10, 10)) == 'N 45°00\'00" E',
          civil.rumbo((0, 0), (10, 10)))
    check("sureste", civil.rumbo((0, 0), (10, -10)) == 'S 45°00\'00" E',
          civil.rumbo((0, 0), (10, -10)))
    check("suroeste", civil.rumbo((0, 0), (-10, -10)) == 'S 45°00\'00" W',
          civil.rumbo((0, 0), (-10, -10)))
    check("noroeste", civil.rumbo((0, 0), (-10, 10)) == 'N 45°00\'00" W',
          civil.rumbo((0, 0), (-10, 10)))
    check("norte franco", civil.rumbo((0, 0), (0, 10)) == 'N 00°00\'00" E',
          civil.rumbo((0, 0), (0, 10)))
    check("este franco", civil.rumbo((0, 0), (10, 0)) == 'N 90°00\'00" E',
          civil.rumbo((0, 0), (10, 0)))
    dx = math.tan(math.radians(30.0 + 30.0 / 60.0 + 30.0 / 3600.0)) * 100.0
    check("grados, minutos y segundos",
          civil.rumbo((0, 0), (dx, 100.0)) == 'N 30°30\'30" E',
          civil.rumbo((0, 0), (dx, 100.0)))


def test_cuadro_de_construccion() -> None:
    import space
    limpiar()
    space.clear()
    # Terreno de 10 x 20 en coordenadas UTM realistas.
    pts = [[196400.0, 2005200.0], [196410.0, 2005200.0],
           [196410.0, 2005220.0], [196400.0, 2005220.0]]
    r = civil.create_construction_table(pts, x=196420.0, y=2005220.0,
                                        scale=0.1)
    check("cuatro lados", len(r["sides"]) == 4, str(len(r["sides"])))
    check("superficie por shoelace", r["area"] == 200.0, str(r["area"]))
    check("perimetro", r["perimeter"] == 60.0, str(r["perimeter"]))
    check("el lado V2-V3 va al norte",
          r["sides"][1]["bearing"] == 'N 00°00\'00" E',
          r["sides"][1]["bearing"])
    check("el vertice de llegada del primer lado es V2",
          r["sides"][0]["vertex"] == "V2", r["sides"][0]["vertex"])
    circulos = [e for e in preview.DRAWN if e["cmd"] == "create_circle"]
    check("un circulo por vertice", len(circulos) == 4, str(len(circulos)))
    # Solo las etiquetas SOBRE el poligono (la tabla, a la derecha de
    # x=196420, tambien tiene celdas "V1", "V2"...).
    textos = [e for e in preview.DRAWN if e["cmd"] == "create_text"
              and str(e.get("text", "")).startswith("V")
              and e["x"] < 196415.0]
    check("una etiqueta por vertice", len(textos) == 4, str(len(textos)))


def test_cuadro_acepta_poligono_cerrado() -> None:
    import space
    limpiar()
    space.clear()
    pts = [[0.0, 0.0], [10.0, 0.0], [10.0, 20.0], [0.0, 20.0], [0.0, 0.0]]
    r = civil.create_construction_table(pts, x=15.0, y=20.0, scale=0.1,
                                        mark_vertices=False)
    check("el cierre repetido no duplica lados", len(r["sides"]) == 4,
          str(len(r["sides"])))
    check("y la superficie da igual", r["area"] == 200.0, str(r["area"]))


def test_cuadro_errores() -> None:
    try:
        civil.create_construction_table([[0, 0], [1, 1]], x=0, y=0)
    except ValueError as exc:
        check("menos de 3 vertices se niega", "3 v" in str(exc), str(exc))
    else:
        check("menos de 3 vertices se niega", False, "no dio error")


def test_reticula_cae_en_multiplos() -> None:
    """Las cruces van en los multiplos exactos del espaciamiento, no en el
    borde de la zona: una reticula con numeros no redondos no se lee."""
    import space
    limpiar()
    space.clear()
    # Zona que arranca y termina en numeros feos, a proposito.
    r = civil.create_coordinate_grid(196403.7, 2005207.2, 196438.1,
                                     2005231.9, spacing=10.0, scale=0.1)
    check("las X son multiplos de 10", r["xValues"] == [196410.0, 196420.0,
                                                        196430.0],
          str(r["xValues"]))
    check("las Y tambien", r["yValues"] == [2005210.0, 2005220.0, 2005230.0],
          str(r["yValues"]))
    check("3x3 = 9 cruces", r["crosses"] == 9, str(r["crosses"]))
    lineas = [e for e in preview.DRAWN if e["cmd"] == "create_line"]
    check("dos lineas por cruz", len(lineas) == 18, str(len(lineas)))
    check("rotula los dos bordes", r["labels"] == 6, str(r["labels"]))


def test_reticula_no_bloquea_el_dibujo() -> None:
    """Las cruces son malla de fondo: si registraran huella, place_labels se
    quedaria sin lugar en todo el plano."""
    import space
    limpiar()
    space.clear()
    civil.create_coordinate_grid(0.0, 0.0, 30.0, 30.0, spacing=10.0,
                                 scale=0.1, label_x=False, label_y=False)
    check("las cruces no dejan huella", len(space.FOOTPRINTS) == 0,
          str(space.FOOTPRINTS))
    limpiar()
    space.clear()
    civil.create_coordinate_grid(0.0, 0.0, 30.0, 30.0, spacing=10.0,
                                 scale=0.1)
    # 0, 10, 20 y 30 son cuatro multiplos por eje -> 8 rotulos.
    check("pero los rotulos si", len(space.FOOTPRINTS) == 8,
          str(len(space.FOOTPRINTS)))


def test_reticula_errores() -> None:
    import space
    limpiar()
    space.clear()
    try:
        civil.create_coordinate_grid(0.0, 0.0, 10.0, 10.0, spacing=0.0)
    except ValueError as exc:
        check("spacing 0 se niega", "spacing" in str(exc), str(exc))
    else:
        check("spacing 0 se niega", False, "no dio error")
    try:
        # Zona de 3 m con espaciamiento de 100: no cae ninguna cruz.
        civil.create_coordinate_grid(1.0, 1.0, 4.0, 4.0, spacing=100.0)
    except ValueError as exc:
        check("avisa si no cae ninguna cruz", "ninguna cruz" in str(exc),
              str(exc))
    else:
        check("avisa si no cae ninguna cruz", False, "no dio error")


def main() -> int:
    for fn in [test_extremos_cerrados_por_defecto, test_extremos_abiertos,
               test_achurado_y_extremos_abiertos_no_conviven,
               test_label_offset_separa_el_cadenamiento,
               test_flecha_de_flujo, test_flecha_fuera_del_eje_da_error,
               test_rumbos_cuadrantales, test_cuadro_de_construccion,
               test_cuadro_acepta_poligono_cerrado, test_cuadro_errores,
               test_reticula_cae_en_multiplos,
               test_reticula_no_bloquea_el_dibujo, test_reticula_errores]:
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
