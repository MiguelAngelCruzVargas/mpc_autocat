"""Tests de geom.section_properties. NO necesita AutoCAD: es geometria pura.

Existe porque calculate_area devolvia SOLO el area. El centroide y los
momentos de inercia son lo que hace falta apenas se pasa de "cuanto concreto
lleva" a "resiste" -- el modulo de seccion sale de ahi.

Lo importante de estos tests: se comparan contra formulas CERRADAS conocidas
(b*h^3/12 para un rectangulo, h/3 para un triangulo, pi*r^2 para un circulo),
no contra lo que devolvio la funcion la primera vez. Un test que fija la
propia salida no verifica nada.

Uso:  python test_properties.py
"""
from __future__ import annotations

import math

import geom

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def cerca(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol


def rel(a: float, b: float, pct: float = 0.001) -> bool:
    return abs(a - b) <= abs(b) * pct


# --------------------------------------------- contra formulas cerradas

def test_rectangulo_contra_la_formula_de_libro() -> None:
    """b*h^3/12 y h*b^3/12. Si esto no da, no da nada."""
    b, h = 30.0, 5.0
    r = geom.section_properties([[0, 0], [b, 0], [b, h], [0, h]])
    check("area = b*h", cerca(r["area"], b * h), r["area"])
    check("perimetro = 2(b+h)", cerca(r["perimeter"], 2 * (b + h)),
          r["perimeter"])
    check("centroide en el centro",
          cerca(r["centroidX"], b / 2) and cerca(r["centroidY"], h / 2),
          (r["centroidX"], r["centroidY"]))
    check("Ixx = b*h^3/12", cerca(r["Ixx"], b * h ** 3 / 12.0, 1e-9),
          "%.6f vs %.6f" % (r["Ixx"], b * h ** 3 / 12.0))
    check("Iyy = h*b^3/12", cerca(r["Iyy"], h * b ** 3 / 12.0, 1e-9),
          "%.6f vs %.6f" % (r["Iyy"], h * b ** 3 / 12.0))
    check("marcado como exacto", r["exact"] is True, r)


def test_triangulo_centroide_a_un_tercio() -> None:
    """El centroide de un triangulo esta a h/3 de la base."""
    r = geom.section_properties([[0, 0], [12, 0], [0, 9]])
    check("area = b*h/2", cerca(r["area"], 54.0), r["area"])
    check("Cx a b/3", cerca(r["centroidX"], 4.0), r["centroidX"])
    check("Cy a h/3", cerca(r["centroidY"], 3.0), r["centroidY"])
    # Ixx de un triangulo respecto de su centroide: b*h^3/36
    check("Ixx = b*h^3/36", cerca(r["Ixx"], 12 * 9 ** 3 / 36.0, 1e-9),
          "%.6f vs %.6f" % (r["Ixx"], 12 * 9 ** 3 / 36.0))


def test_el_sentido_de_giro_no_cambia_nada() -> None:
    """Horario o antihorario: el area es positiva y el centroide el mismo.
    Una polilinea dibujada al reves no puede dar propiedades distintas."""
    anti = geom.section_properties([[0, 0], [10, 0], [10, 4], [0, 4]])
    hor = geom.section_properties([[0, 0], [0, 4], [10, 4], [10, 0]])
    for clave in ("area", "perimeter", "centroidX", "centroidY", "Ixx", "Iyy"):
        check("mismo %s en los dos sentidos" % clave,
              cerca(anti[clave], hor[clave], 1e-9),
              (anti[clave], hor[clave]))


def test_seccion_en_L() -> None:
    """Una L de 6x6 con un cuadrante de 3x3 sacado: el centroide se corre
    hacia la parte con mas material, y se puede calcular a mano."""
    r = geom.section_properties([[0, 0], [6, 0], [6, 3], [3, 3], [3, 6],
                                 [0, 6]])
    # Dos rectangulos: 6x3 (centro 3,1.5) y 3x3 (centro 1.5,4.5)
    a1, a2 = 18.0, 9.0
    cx = (a1 * 3.0 + a2 * 1.5) / (a1 + a2)
    cy = (a1 * 1.5 + a2 * 4.5) / (a1 + a2)
    check("area = 27", cerca(r["area"], 27.0), r["area"])
    check("centroide por composicion",
          cerca(r["centroidX"], cx) and cerca(r["centroidY"], cy),
          (r["centroidX"], cx, r["centroidY"], cy))


# ------------------------------------------------------ el muro real

def test_el_muro_de_contencion_de_la_prueba() -> None:
    """Los mismos numeros que devolvio AutoCAD para esa polilinea: area 675
    y perimetro 131.40054944640258. Si la funcion se aparta de eso, se
    aparto de la realidad."""
    r = geom.section_properties([[0, 0], [30, 0], [30, 5], [20, 40],
                                 [10, 40], [10, 5], [0, 5]])
    check("area como AutoCAD", cerca(r["area"], 675.0), r["area"])
    check("perimetro como AutoCAD",
          cerca(r["perimeter"], 131.40054944640258, 1e-9), r["perimeter"])
    check("el centroide cae DENTRO del contorno",
          0 < r["centroidX"] < 30 and 0 < r["centroidY"] < 40,
          (r["centroidX"], r["centroidY"]))


# ------------------------------------------------------------ arcos

def test_un_circulo_por_bulges_se_aproxima_y_lo_dice() -> None:
    """Dos vertices con bulge 1 cada uno son un circulo. Se muestrea, asi
    que el resultado es aproximado -- y 'exact' tiene que decirlo."""
    r = 10.0
    res = geom.section_properties([[-r, 0], [r, 0]], bulges=[1.0, 1.0])
    check("area cerca de pi*r^2", rel(res["area"], math.pi * r * r, 0.001),
          "%.4f vs %.4f" % (res["area"], math.pi * r * r))
    check("perimetro cerca de 2*pi*r",
          rel(res["perimeter"], 2 * math.pi * r, 0.001), res["perimeter"])
    check("centroide en el centro",
          cerca(res["centroidX"], 0.0, 1e-6)
          and cerca(res["centroidY"], 0.0, 1e-6),
          (res["centroidX"], res["centroidY"]))
    check("Ixx cerca de pi*r^4/4",
          rel(res["Ixx"], math.pi * r ** 4 / 4.0, 0.005), res["Ixx"])
    check("AVISA que es aproximado", res["exact"] is False, res)


def test_sin_arcos_queda_exacto() -> None:
    r = geom.section_properties([[0, 0], [4, 0], [4, 4], [0, 4]],
                                bulges=[0.0, 0.0, 0.0, 0.0])
    check("bulges en cero no lo vuelve aproximado", r["exact"] is True, r)


# ----------------------------------------------------------- errores

def test_rechaza_lo_que_no_es_una_seccion() -> None:
    casos = [([], "lista vacia"),
             ([[0, 0], [1, 1]], "dos puntos"),
             ([[0, 0], [1, 1], [2, 2]], "vertices colineales")]
    for pts, que in casos:
        try:
            geom.section_properties(pts)
            check("rechaza %s" % que, False, "no tiro ValueError")
        except ValueError:
            check("rechaza %s" % que, True)


def main() -> int:
    for fn in [test_rectangulo_contra_la_formula_de_libro,
               test_triangulo_centroide_a_un_tercio,
               test_el_sentido_de_giro_no_cambia_nada,
               test_seccion_en_L,
               test_el_muro_de_contencion_de_la_prueba,
               test_un_circulo_por_bulges_se_aproxima_y_lo_dice,
               test_sin_arcos_queda_exacto,
               test_rechaza_lo_que_no_es_una_seccion]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: area, centroide y momentos contra formulas de libro, no "
          "contra la propia salida.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
