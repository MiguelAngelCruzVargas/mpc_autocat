"""Tests del motor de composicion. NO necesita AutoCAD: es geometria pura.

Lo que fijan, en orden de importancia:

  - Las vistas de una fila apoyan sobre una LINEA DE BASE comun. Es lo que
    hace que una lamina se vea alineada y no con los dibujos flotando a
    distintas alturas.
  - Una vista con 'below' se apila con la de arriba y las dos comparten el
    centro en X. Esa es la alineacion proyectiva -- la planta debajo de su
    corte, compartiendo los ejes verticales -- y es la unica forma de que
    se puedan leer una con otra.
  - Si no entra, lo DICE. No achica: una vista fuera de escala no es una
    lamina, es un error.

Los tamanos se piden en mm de papel, asi que todos los tests pasan 'scale'
explicito para no depender de la escala que quedo persistida.

Uso:  python test_compose.py
"""
from __future__ import annotations

import compose

FAILED: list[str] = []

# 1:100 dibujando en metros: 1 mm de papel = 0.1 unidades.
ESCALA = 0.1


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def cerca(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def plan(views, area, **kw):
    kw.setdefault("scale", ESCALA)
    return compose.plan_composition(views, area, **kw)


def por_nombre(r) -> dict:
    return {p["name"]: p for p in r["placements"]}


def vista(nombre, x0, y0, x1, y1, **extra):
    v = {"name": nombre, "box": [x0, y0, x1, y1]}
    v.update(extra)
    return v


# ------------------------------------------------------- fila y linea base

def test_una_fila_apoya_en_una_linea_de_base_comun() -> None:
    """Dos vistas de distinto alto: los BORDES INFERIORES tienen que
    coincidir. Es lo que separa una lamina alineada de uno con los dibujos
    flotando cada uno a su altura."""
    r = plan([vista("alta", 0, 0, 10, 8),
              vista("baja", 100, 100, 106, 3 + 100)],
             area=[0, 0, 40, 20])
    p = por_nombre(r)
    check("las dos entran en una fila", len(r["rows"]) == 1, r["rows"])
    check("comparten la linea de base",
          cerca(p["alta"]["box"][1], p["baja"]["box"][1]),
          f'{p["alta"]["box"][1]} vs {p["baja"]["box"][1]}')
    check("conservan su alto",
          cerca(p["alta"]["box"][3] - p["alta"]["box"][1], 8)
          and cerca(p["baja"]["box"][3] - p["baja"]["box"][1], 3),
          [p["alta"]["box"], p["baja"]["box"]])
    check("y su ancho", cerca(p["alta"]["box"][2] - p["alta"]["box"][0], 10),
          p["alta"]["box"])


def test_align_center_centra_en_vez_de_apoyar() -> None:
    r = plan([vista("alta", 0, 0, 10, 8), vista("baja", 0, 0, 6, 4)],
             area=[0, 0, 40, 20], align="center")
    p = por_nombre(r)
    centro_a = (p["alta"]["box"][1] + p["alta"]["box"][3]) / 2
    centro_b = (p["baja"]["box"][1] + p["baja"]["box"][3]) / 2
    check("comparten el eje horizontal", cerca(centro_a, centro_b),
          f"{centro_a} vs {centro_b}")


def test_el_dx_dy_lleva_la_caja_al_destino() -> None:
    """El desplazamiento es lo unico que se le aplica a las entidades: si no
    lleva la caja original al destino, todo lo demas da igual."""
    v = vista("sola", 33.0, -12.0, 43.0, -4.0)
    r = plan([v], area=[0, 0, 40, 20])
    p = por_nombre(r)["sola"]
    check("dx lleva x0 al destino",
          cerca(33.0 + p["dx"], p["box"][0]), (p["dx"], p["box"]))
    check("dy lleva y1 al destino",
          cerca(-4.0 + p["dy"], p["box"][3]), (p["dy"], p["box"]))


# -------------------------------------------------------------- envolver

def test_lo_que_no_entra_a_lo_ancho_pasa_a_otra_fila() -> None:
    vistas = [vista("v%d" % i, 0, 0, 12, 5) for i in range(3)]
    r = plan(vistas, area=[0, 0, 30, 40])
    check("dos filas", len(r["rows"]) == 2, r["rows"])
    check("dos arriba y una abajo",
          [len(f) for f in r["rows"]] == [2, 1], r["rows"])
    p = por_nombre(r)
    check("la tercera queda MAS ABAJO que las dos primeras",
          p["v2"]["box"][3] < p["v0"]["box"][1], [p["v0"]["box"], p["v2"]["box"]])


def test_la_primera_vista_queda_arriba_a_la_izquierda() -> None:
    """Una lamina se empieza a leer por arriba a la izquierda."""
    r = plan([vista("primera", 0, 0, 10, 5), vista("segunda", 0, 0, 10, 5)],
             area=[0, 0, 40, 20], distribute="left")
    p = por_nombre(r)
    check("la primera pegada al margen izquierdo",
          cerca(p["primera"]["box"][0], 0.0), p["primera"]["box"])
    check("y contra el borde de arriba",
          cerca(p["primera"]["box"][3], 20.0), p["primera"]["box"])
    check("la segunda a su derecha",
          p["segunda"]["box"][0] > p["primera"]["box"][2],
          [p["primera"]["box"], p["segunda"]["box"]])


def test_distribute_reparte_distinto() -> None:
    vs = [vista("a", 0, 0, 10, 5), vista("b", 0, 0, 10, 5)]
    izq = por_nombre(plan(vs, area=[0, 0, 40, 20], distribute="left"))
    cen = por_nombre(plan(vs, area=[0, 0, 40, 20], distribute="center"))
    jus = por_nombre(plan(vs, area=[0, 0, 40, 20], distribute="justify"))
    check("'left' arranca en el margen", cerca(izq["a"]["box"][0], 0.0),
          izq["a"]["box"])
    check("'center' deja aire a los dos lados", cen["a"]["box"][0] > 0,
          cen["a"]["box"])
    check("'justify' estira hasta el borde derecho",
          cerca(jus["b"]["box"][2], 40.0), jus["b"]["box"])


# ------------------------------------------ alineacion proyectiva (below)

def test_below_alinea_los_centros_en_x() -> None:
    """La planta debajo de su corte, compartiendo los ejes verticales. Es
    para lo que existe 'below' y lo que permite leer una vista con la otra."""
    r = plan([vista("corte", 0, 0, 16, 6),
              vista("planta", 200, 200, 200 + 10, 200 + 8, below="corte")],
             area=[0, 0, 40, 40])
    p = por_nombre(r)
    cx_corte = (p["corte"]["box"][0] + p["corte"]["box"][2]) / 2
    cx_planta = (p["planta"]["box"][0] + p["planta"]["box"][2]) / 2
    check("los centros en X coinciden", cerca(cx_corte, cx_planta),
          f"{cx_corte} vs {cx_planta}")
    check("la planta queda DEBAJO del corte",
          p["planta"]["box"][3] < p["corte"]["box"][1],
          [p["corte"]["box"], p["planta"]["box"]])
    check("y las dos son UNA unidad en la fila",
          r["rows"] == [["corte + planta"]], r["rows"])


def test_la_pila_acomoda_como_una_sola_cosa() -> None:
    """La unidad ocupa el ancho de su vista mas ancha, no la suma."""
    r = plan([vista("ancha", 0, 0, 20, 4),
              vista("angosta", 0, 0, 6, 4, below="ancha"),
              vista("vecina", 0, 0, 15, 4)],
             area=[0, 0, 40, 40])
    check("la pila y la vecina entran juntas en una fila",
          len(r["rows"]) == 1, r["rows"])
    p = por_nombre(r)
    check("la vecina no se mete en la columna de la pila",
          p["vecina"]["box"][0] >= p["ancha"]["box"][2],
          [p["ancha"]["box"], p["vecina"]["box"]])


def test_below_rechaza_lo_que_no_cierra() -> None:
    casos = [
        ([vista("a", 0, 0, 1, 1, below="fantasma")], "referencia inexistente"),
        ([vista("a", 0, 0, 1, 1, below="a")], "debajo de si misma"),
        ([vista("a", 0, 0, 1, 1, below="b"),
          vista("b", 0, 0, 1, 1, below="a")], "ciclo"),
        ([vista("a", 0, 0, 1, 1),
          vista("b", 0, 0, 1, 1, below="a"),
          vista("c", 0, 0, 1, 1, below="a")], "dos debajo de la misma"),
        ([vista("a", 0, 0, 1, 1), vista("a", 0, 0, 1, 1)], "nombre repetido"),
        ([{"box": [0, 0, 1, 1]}], "vista sin nombre"),
        ([{"name": "a"}], "vista sin caja"),
        ([vista("a", 5, 5, 1, 1)], "caja invertida"),
    ]
    for vistas, que in casos:
        try:
            plan(vistas, area=[0, 0, 40, 40])
            check("rechaza %s" % que, False, "no tiro ValueError")
        except ValueError:
            check("rechaza %s" % que, True)


# ------------------------------------------------------------- titulos

def test_el_titulo_reserva_su_lugar_debajo() -> None:
    con = plan([vista("v", 0, 0, 10, 5, title="PLANTA"),
                vista("w", 0, 0, 10, 5, title="PLANTA", below="v")],
               area=[0, 0, 40, 40])
    sin = plan([vista("v", 0, 0, 10, 5),
                vista("w", 0, 0, 10, 5, below="v")],
               area=[0, 0, 40, 40])
    hueco_con = (por_nombre(con)["v"]["box"][1]
                 - por_nombre(con)["w"]["box"][3])
    hueco_sin = (por_nombre(sin)["v"]["box"][1]
                 - por_nombre(sin)["w"]["box"][3])
    check("con titulo queda mas separacion entre las dos",
          hueco_con > hueco_sin, f"{hueco_con} vs {hueco_sin}")

    p = por_nombre(con)["v"]
    check("devuelve donde va el titulo", p["titlePoint"] is not None, p)
    check("centrado bajo la vista",
          cerca(p["titlePoint"][0], (p["box"][0] + p["box"][2]) / 2),
          p["titlePoint"])
    check("y por debajo del dibujo", p["titlePoint"][1] < p["box"][1], p)


def test_sin_titulo_no_hay_punto_de_titulo() -> None:
    p = por_nombre(plan([vista("v", 0, 0, 10, 5)], area=[0, 0, 40, 40]))["v"]
    check("titlePoint es None", p["titlePoint"] is None, p)


# --------------------------------------------------------- lo que no entra

def test_si_no_entra_lo_dice_y_no_achica() -> None:
    """Achicar para que entre seria dibujar fuera de escala. La tool avisa
    y deja la decision -- otro formato, otra escala, dos laminas."""
    r = plan([vista("v%d" % i, 0, 0, 30, 15) for i in range(4)],
             area=[0, 0, 35, 20])
    check("avisa que no entra", r["fits"] is False, r["fits"])
    check("lo explica", any("alto" in w for w in r["warnings"]), r["warnings"])
    p = por_nombre(r)
    check("NO achico las vistas",
          cerca(p["v0"]["box"][2] - p["v0"]["box"][0], 30),
          p["v0"]["box"])
    check("igual devuelve donde iria cada una",
          len(r["placements"]) == 4, len(r["placements"]))


def test_una_vista_mas_ancha_que_la_hoja_se_avisa() -> None:
    r = plan([vista("gigante", 0, 0, 80, 5)], area=[0, 0, 35, 20])
    check("avisa que no entra ni sola",
          any("ni sola" in w for w in r["warnings"]), r["warnings"])


def test_reporta_cuanto_uso() -> None:
    r = plan([vista("v", 0, 0, 10, 5)], area=[0, 0, 40, 20])
    check("informa alto usado y disponible",
          cerca(r["usedHeight"], 5) and cerca(r["availableHeight"], 20), r)
    check("informa ancho usado y disponible",
          cerca(r["usedWidth"], 10) and cerca(r["availableWidth"], 40), r)


def test_rechaza_parametros_invalidos() -> None:
    casos = [({"align": "arriba"}, "align"),
             ({"distribute": "esparcido"}, "distribute")]
    for kw, que in casos:
        try:
            plan([vista("v", 0, 0, 1, 1)], area=[0, 0, 10, 10], **kw)
            check("rechaza %s invalido" % que, False, "no tiro ValueError")
        except ValueError:
            check("rechaza %s invalido" % que, True)
    for vistas, area, que in [([], [0, 0, 10, 10], "sin vistas"),
                              ([vista("v", 0, 0, 1, 1)], [0, 0, 0, 10],
                               "area de ancho cero")]:
        try:
            plan(vistas, area=area)
            check("rechaza %s" % que, False, "no tiro ValueError")
        except ValueError:
            check("rechaza %s" % que, True)


def main() -> int:
    for fn in [test_una_fila_apoya_en_una_linea_de_base_comun,
               test_align_center_centra_en_vez_de_apoyar,
               test_el_dx_dy_lleva_la_caja_al_destino,
               test_lo_que_no_entra_a_lo_ancho_pasa_a_otra_fila,
               test_la_primera_vista_queda_arriba_a_la_izquierda,
               test_distribute_reparte_distinto,
               test_below_alinea_los_centros_en_x,
               test_la_pila_acomoda_como_una_sola_cosa,
               test_below_rechaza_lo_que_no_cierra,
               test_el_titulo_reserva_su_lugar_debajo,
               test_sin_titulo_no_hay_punto_de_titulo,
               test_si_no_entra_lo_dice_y_no_achica,
               test_una_vista_mas_ancha_que_la_hoja_se_avisa,
               test_reporta_cuanto_uso,
               test_rechaza_parametros_invalidos]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: las vistas se alinean, se apilan y avisan cuando no entran.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
