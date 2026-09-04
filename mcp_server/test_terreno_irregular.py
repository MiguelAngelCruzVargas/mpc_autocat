"""Tests del terreno IRREGULAR: el lote deja de tener que ser un rectangulo.

NO necesita AutoCAD.

METODO: los valores esperados se calculan A MANO o por una formula
INDEPENDIENTE de la funcion que se prueba -- nunca copiando lo que devolvio
el codigo. Un test cuyo numero esperado salio de correr la propia funcion no
prueba que este bien: congela lo que hace hoy, este bien o mal. Por eso aca:

  - el cuadrado y el triangulo se verifican de cabeza (lado^2, base*altura/2);
  - el trapecio se verifica con (a+b)/2*h, que no es shoelace;
  - y lo demas son PROPIEDADES que tienen que valer para cualquier poligono
    (trasladarlo no cambia su area, invertir los vertices tampoco, escalarlo
    por k la multiplica por k^2).

Las medidas no son de ningun plano en particular a proposito: lo que se
prueba es la matematica, no un proyecto.
"""
from __future__ import annotations

import math

import preview

preview.install()

import geom                # noqa: E402
import rules               # noqa: E402
import sheet as sheet_mod  # noqa: E402

FAILED: list[str] = []

# Trapecio con los dos lados paralelos VERTICALES: uno de 26 m (el frente) y
# otro de 20 m (el fondo), separados 30 m. Es la forma de un lote entre
# medianeras que se angosta hacia el fondo -- el caso irregular mas comun.
# Su area por la formula del trapecio: (26 + 20) / 2 * 30 = 690 m2 exactos.
TRAPECIO = [[0.0, 0.0], [30.0, 0.0], [30.0, 20.0], [0.0, 26.0]]
TRAPECIO_AREA = (26.0 + 20.0) / 2.0 * 30.0          # 690.0, a mano
TRAPECIO_ENVOLVENTE = 30.0 * 26.0                    # 780.0, el rectangulo


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


# ------------------------------------------------ superficie, a mano

def test_areas_que_se_verifican_de_cabeza() -> None:
    cuadrado = [[0, 0], [10, 0], [10, 10], [0, 10]]
    check("cuadrado de 10: 100 m2",
          abs(geom.polygon_area(cuadrado) - 100.0) < 1e-9,
          geom.polygon_area(cuadrado))

    triangulo = [[0, 0], [6, 0], [0, 4]]        # base 6, altura 4 -> 12
    check("triangulo 6x4/2: 12 m2",
          abs(geom.polygon_area(triangulo) - 12.0) < 1e-9,
          geom.polygon_area(triangulo))

    # (a+b)/2*h, que no es la formula que usa polygon_area.
    check("trapecio (26+20)/2*30: 690 m2",
          abs(geom.polygon_area(TRAPECIO) - TRAPECIO_AREA) < 1e-9,
          geom.polygon_area(TRAPECIO))

    check("perimetro del cuadrado: 40 m",
          abs(geom.polygon_perimeter(cuadrado) - 40.0) < 1e-9,
          geom.polygon_perimeter(cuadrado))


def test_propiedades_que_valen_para_cualquier_poligono() -> None:
    base = geom.polygon_area(TRAPECIO)

    invertido = geom.polygon_area(list(reversed(TRAPECIO)))
    check("el sentido de los vertices no cambia el area",
          abs(invertido - base) < 1e-9, invertido)

    movido = [[x + 137.5, y - 42.0] for x, y in TRAPECIO]
    check("trasladarlo no cambia el area",
          abs(geom.polygon_area(movido) - base) < 1e-9,
          geom.polygon_area(movido))

    k = 3.0
    escalado = [[x * k, y * k] for x, y in TRAPECIO]
    check("escalar por k multiplica el area por k^2",
          abs(geom.polygon_area(escalado) - base * k * k) < 1e-6,
          geom.polygon_area(escalado))

    cerrado = TRAPECIO + [TRAPECIO[0]]
    check("cerrado o abierto da lo mismo",
          abs(geom.polygon_area(cerrado) - base) < 1e-9,
          geom.polygon_area(cerrado))


def test_menos_de_tres_vertices_se_niega() -> None:
    try:
        geom.polygon_area([[0, 0], [1, 1]])
    except ValueError:
        check("un 'poligono' de dos puntos se rechaza", True)
    else:
        check("un 'poligono' de dos puntos se rechaza", False, "no fallo")


# ------------------------------------------------------ pertenencia

def test_el_borde_cuenta_como_adentro() -> None:
    """Un recinto que apoya en la colindancia esta dentro del terreno.
    Rechazarlo obligaria a un retiro que el proyecto puede no tener."""
    check("un vertice", geom.point_in_polygon(0.0, 0.0, TRAPECIO))
    check("sobre un lado recto", geom.point_in_polygon(15.0, 0.0, TRAPECIO))
    # Punto medio del lado inclinado, calculado a mano: entre (30,20) y (0,26).
    check("sobre el lado inclinado",
          geom.point_in_polygon(15.0, 23.0, TRAPECIO))
    check("bien adentro", geom.point_in_polygon(10.0, 10.0, TRAPECIO))
    check("afuera por el costado",
          not geom.point_in_polygon(40.0, 10.0, TRAPECIO))
    # Justo encima del lado inclinado: a x=15 el borde esta en y=23.
    check("afuera por arriba del lado inclinado",
          not geom.point_in_polygon(15.0, 23.5, TRAPECIO))


def test_recinto_dentro_del_envolvente_pero_fuera_del_terreno() -> None:
    """El error que el rectangulo no podia ver.

    A x=25 el lado inclinado del trapecio esta en y = 26 - 25*(6/30) = 21.
    Un recinto hasta y=24 entra holgado en el rectangulo envolvente (26 m de
    alto) y se sale del terreno de verdad. Los dos numeros salen de la recta
    del lado, no de correr el codigo.
    """
    y_borde = 26.0 - 25.0 * (6.0 / 30.0)
    check("el borde a x=25 esta en y=21 (a mano)",
          abs(y_borde - 21.0) < 1e-9, y_borde)

    fuera = {"name": "RECAMARA 3", "x0": 22.0, "y0": 22.0,
             "x1": 28.0, "y1": 24.0}
    check("el rectangulo envolvente lo daria por bueno",
          fuera["x1"] <= 30.0 and fuera["y1"] <= 26.0)
    check("contra el poligono real, no entra",
          not geom.rect_in_polygon(fuera["x0"], fuera["y0"],
                                   fuera["x1"], fuera["y1"], TRAPECIO))

    r = rules.check_layout(
        rooms=[{"name": "SALA", "x0": 2.0, "y0": 2.0, "x1": 8.0, "y1": 8.0},
               fuera],
        doors=[{"from": "EXTERIOR", "to": "SALA", "width": 0.9},
               {"from": "SALA", "to": "RECAMARA 3", "width": 0.8}],
        lot_points=TRAPECIO)
    afuera = [p for p in r["problems"] if p["rule"] == "dentro del terreno"]
    check("check_layout lo reporta", len(afuera) == 1, r["problems"])
    check("y nombra al recinto culpable",
          bool(afuera) and "RECAMARA 3" in afuera[0]["problem"], afuera)


def test_sin_lot_points_no_cambia_nada() -> None:
    """La firma vieja tiene que seguir andando igual."""
    r = rules.check_layout(
        rooms=[{"name": "SALA", "x0": 0, "y0": 0, "x1": 4, "y1": 4}],
        doors=[{"from": "EXTERIOR", "to": "SALA", "width": 0.9}])
    check("sin poligono no inventa el problema del terreno",
          not any(p["rule"] == "dentro del terreno" for p in r["problems"]),
          r["problems"])


def test_terreno_concavo_no_se_conforma_con_las_esquinas() -> None:
    """Terreno en L: las cuatro esquinas adentro y el rectangulo cruzando.

    Es el caso que un chequeo por esquinas no puede ver, y por eso
    rect_in_polygon ademas comprueba que ningun lado se cruce.
    """
    ele = [[0, 0], [10, 0], [10, 4], [4, 4], [4, 10], [0, 10]]
    check("lo que entra en un brazo, entra",
          geom.rect_in_polygon(1, 1, 9, 3, ele))
    check("el que cruza el hueco NO entra",
          not geom.rect_in_polygon(1, 1, 9, 9, ele))
    check("y el hueco esta afuera",
          not geom.point_in_polygon(7.0, 7.0, ele))


# --------------------------------------------------- check_program

def test_check_program_mide_el_poligono_no_el_envolvente() -> None:
    """Lo que importa no es un numero magico: es que el terreno real deje
    MENOS superficie util que el rectangulo que lo envuelve, y exactamente
    en la proporcion de sus areas."""
    espacios = [{"name": "Ambiente", "area": 100.0}]
    poli = sheet_mod.check_program(spaces=espacios, lot_points=TRAPECIO)
    rect = sheet_mod.check_program(spaces=espacios, lot_width=30.0,
                                   lot_depth=26.0)

    check("lotArea con el poligono = 690 (a mano)",
          abs(poli["lotArea"] - TRAPECIO_AREA) < 1e-9, poli["lotArea"])
    check("lotArea con el rectangulo = 780 (a mano)",
          abs(rect["lotArea"] - TRAPECIO_ENVOLVENTE) < 1e-9, rect["lotArea"])
    check("el terreno real deja menos superficie util",
          poli["usableArea"] < rect["usableArea"],
          f"{poli['usableArea']} vs {rect['usableArea']}")

    # El programa que cae JUSTO entre las dos superficies se calcula de los
    # numeros que devolvio la tool, no de un valor pegado a mano: asi el
    # test sigue valiendo si cambia el factor de muros o de circulacion.
    entre = (poli["usableArea"] + rect["usableArea"]) / 2.0
    medio = [{"name": "Programa", "area": entre / 1.12}]
    check("ese programa NO entra en el terreno real",
          not sheet_mod.check_program(spaces=medio,
                                      lot_points=TRAPECIO)["fits"])
    check("y SI entraria en el rectangulo inventado",
          sheet_mod.check_program(spaces=medio, lot_width=30.0,
                                  lot_depth=26.0)["fits"])


def test_check_program_sin_terreno_se_niega() -> None:
    try:
        sheet_mod.check_program(spaces=[{"name": "X", "area": 10.0}])
    except ValueError as exc:
        check("pide el terreno en vez de suponerlo",
              "lot_points" in str(exc), str(exc))
    else:
        check("pide el terreno en vez de suponerlo", False, "no fallo")


def main() -> int:
    for fn in [test_areas_que_se_verifican_de_cabeza,
               test_propiedades_que_valen_para_cualquier_poligono,
               test_menos_de_tres_vertices_se_niega,
               test_el_borde_cuenta_como_adentro,
               test_recinto_dentro_del_envolvente_pero_fuera_del_terreno,
               test_sin_lot_points_no_cambia_nada,
               test_terreno_concavo_no_se_conforma_con_las_esquinas,
               test_check_program_mide_el_poligono_no_el_envolvente,
               test_check_program_sin_terreno_se_niega]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: el terreno ya no tiene que ser un rectangulo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
