"""Tests de traverse() y sheet_origin(). NO necesita AutoCAD.

Las dos tools nacieron de borrar dos scripts: la trigonometria para pasar de
un cuadro de construccion a coordenadas, y la cuenta para ubicar el dibujo
dentro del area util de la lamina. Mientras eso vivia en un script no servia
para el proximo plano.

METODO: los valores esperados se calculan A MANO o con una formula
independiente de la funcion que se prueba -- nunca copiando lo que devolvio
el codigo.

Uso:  python test_trazo.py
"""
from __future__ import annotations

import math

import preview

preview.install()

import civil              # noqa: E402
import sheet as sheet_mod # noqa: E402
import space              # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


# ------------------------------------------------------ leer un rumbo

def test_rumbo_a_azimut() -> None:
    """Los cuatro cuadrantes, verificables de cabeza."""
    casos = [
        ("N 00°00'00\" E",   0.0),
        ("N 90°00'00\" E",  90.0),
        ("S 90°00'00\" E",  90.0),    # sur-este a 90 es el este
        ("S 00°00'00\" E", 180.0),
        ("S 90°00'00\" W", 270.0),
        ("N 90°00'00\" W", 270.0),
        ("N 45°00'00\" E",  45.0),
        ("S 45°00'00\" E", 135.0),
        ("S 45°00'00\" W", 225.0),
        ("N 45°00'00\" W", 315.0),
    ]
    for texto, esperado in casos:
        got = civil.parse_rumbo(texto)
        check("%-18s -> %6.1f" % (texto, esperado),
              abs(got - esperado) < 1e-9, got)

    # 30'  = 0.5 grados; 36" = 0.01 grados. A mano.
    check("los minutos valen 1/60",
          abs(civil.parse_rumbo("N 10°30'00\" E") - 10.5) < 1e-9)
    check("los segundos valen 1/3600",
          abs(civil.parse_rumbo("N 10°00'36\" E") - 10.01) < 1e-9)


def test_rumbo_como_viene_en_un_plano_real() -> None:
    """Formatos que aparecen impresos, incluido el oeste en castellano."""
    base = civil.parse_rumbo("N 45°00'00\" W")
    check("con 'O' de oeste en vez de 'W'",
          abs(civil.parse_rumbo("N 45°00'00\" O") - base) < 1e-9)
    check("sin simbolos, solo espacios",
          abs(civil.parse_rumbo("N 45 00 00 W") - base) < 1e-9)
    check("en grados decimales",
          abs(civil.parse_rumbo("N 45.0 W") - base) < 1e-9)
    check("en minusculas",
          abs(civil.parse_rumbo("n 45°00'00\" w") - base) < 1e-9)


def test_rumbo_invalido_se_niega() -> None:
    for malo, porque in [("", "vacio"),
                         ("N 120°00'00\" E", "mas de 90 grados"),
                         ("X 45 Z", "letras que no son cuadrante"),
                         ("45 grados", "sin cuadrante")]:
        try:
            civil.parse_rumbo(malo)
        except ValueError:
            check("rechaza %s" % porque, True)
        else:
            check("rechaza %s" % porque, False, "lo acepto")


def test_ida_y_vuelta_con_create_construction_table() -> None:
    """rumbo() y parse_rumbo() son inversos, hasta donde el formato permite.

    Un cuadro de construccion se escribe en grados-minutos-SEGUNDOS enteros,
    asi que la vuelta no puede ser exacta: el redondeo del formato vale hasta
    medio segundo (1/7200 de grado). No es un error del codigo, es la
    precision que tiene la notacion -- y sobre un lado de 60 m, medio segundo
    son 0.15 mm en el terreno.
    """
    MEDIO_SEGUNDO = 1.0 / 7200.0
    puntos = [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 26.0)]
    for i in range(4):
        p0, p1 = puntos[i], puntos[(i + 1) % 4]
        texto = civil.rumbo(p0, p1)
        azimut = civil.parse_rumbo(texto)
        # El azimut reconstruido tiene que apuntar al mismo lado.
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        esperado = math.degrees(math.atan2(dx, dy)) % 360.0
        desvio = abs((azimut - esperado + 180) % 360 - 180)
        check("ida y vuelta del lado %d (%s)" % (i + 1, texto),
              desvio <= MEDIO_SEGUNDO,
              f"{desvio*3600:.3f}\" de desvio")

    # Y el error de cierre que deja ese redondeo tiene que ser despreciable:
    # se recorre el mismo poligono leyendo su propio cuadro.
    lados = []
    for i in range(4):
        p0, p1 = puntos[i], puntos[(i + 1) % 4]
        lados.append({"bearing": civil.rumbo(p0, p1),
                      "distance": math.dist(p0, p1)})
    r = civil.traverse(lados)
    check("releer el propio cuadro cierra dentro de tolerancia",
          r["closes"], f"error {r['closureError']} m")
    check("y el area sale igual (690 a mano)",
          abs(r["area"] - 690.0) < 0.01, r["area"])


# --------------------------------------------------------- el recorrido

def test_traverse_de_un_rectangulo_a_mano() -> None:
    """30 x 20: los vertices y el area se saben de cabeza."""
    r = civil.traverse([
        {"bearing": "N 90°00'00\" E", "distance": 30.0},
        {"bearing": "N 00°00'00\" E", "distance": 20.0},
        {"bearing": "S 90°00'00\" W", "distance": 30.0},
        {"bearing": "S 00°00'00\" W", "distance": 20.0}])

    esperados = [[0.0, 0.0], [30.0, 0.0], [30.0, 20.0], [0.0, 20.0]]
    check("los cuatro vertices",
          all(abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6
              for a, b in zip(r["points"], esperados)), r["points"])
    check("area 30x20 = 600", abs(r["area"] - 600.0) < 1e-6, r["area"])
    check("perimetro 2*(30+20) = 100",
          abs(r["perimeter"] - 100.0) < 1e-9, r["perimeter"])
    check("cierra exacto", r["closes"] and r["closureError"] < 1e-9,
          r["closureError"])
    check("sin warning cuando cierra", "warning" not in r, r.get("warning"))


def test_traverse_arranca_donde_se_le_diga() -> None:
    r = civil.traverse([{"azimuth": 90.0, "distance": 10.0},
                        {"azimuth": 0.0, "distance": 10.0},
                        {"azimuth": 270.0, "distance": 10.0},
                        {"azimuth": 180.0, "distance": 10.0}],
                       start_x=100.0, start_y=-50.0)
    check("el primer vertice es el punto dado",
          r["points"][0] == [100.0, -50.0], r["points"][0])
    check("y el area no cambia por trasladarlo",
          abs(r["area"] - 100.0) < 1e-6, r["area"])


def test_traverse_avisa_cuando_no_cierra() -> None:
    """Un lado mal copiado deja el poligono abierto, y hay que saberlo."""
    r = civil.traverse([
        {"bearing": "N 90°00'00\" E", "distance": 30.0},
        {"bearing": "N 00°00'00\" E", "distance": 20.0},
        {"bearing": "S 90°00'00\" W", "distance": 30.0},
        {"bearing": "S 00°00'00\" W", "distance": 17.0}])   # 3 m de menos
    check("dice que no cierra", not r["closes"], r)
    check("y de cuanto es el error",
          abs(r["closureError"] - 3.0) < 1e-6, r["closureError"])
    check("con el desglose en x/y",
          abs(r["closureBy"]["dy"] - 3.0) < 1e-6, r["closureBy"])
    check("y lo explica", "warning" in r and "no cierra" in r["warning"].lower(),
          r.get("warning"))


def test_traverse_datos_incompletos_se_niegan() -> None:
    for lados, porque in [
            ([], "sin lados"),
            ([{"distance": 10.0}], "sin rumbo ni azimut"),
            ([{"bearing": "N 0 E"}], "sin distancia"),
            ([{"bearing": "N 0 E", "distance": -5.0}], "distancia negativa")]:
        try:
            civil.traverse(lados)
        except ValueError:
            check("rechaza %s" % porque, True)
        else:
            check("rechaza %s" % porque, False, "lo acepto")


# ------------------------------------------- donde arranca el dibujo

def _lamina(x1: float, y1: float, x2: float, y2: float,
            escala: float = 0.2) -> None:
    space.clear()
    space.set_scale(escala)
    space.set_sheet({"x1": x1, "y1": y1, "x2": x2, "y2": y2})


def test_sheet_origin_centra_de_verdad() -> None:
    # Area util de 100 x 50 desde (10, 20). Escala 0.2 u/mm -> margen de
    # 10 mm son 2 unidades. Queda 96 x 46 disponible desde (12, 22).
    _lamina(10.0, 20.0, 110.0, 70.0)
    r = sheet_mod.sheet_origin(width=40.0, height=20.0, margin_mm=10.0)

    check("entra", r["fits"], r)
    check("disponible 96 x 46 (a mano)",
          abs(r["available"]["width"] - 96.0) < 1e-9
          and abs(r["available"]["height"] - 46.0) < 1e-9, r["available"])
    # Centrado: 12 + (96-40)/2 = 40 ; 22 + (46-20)/2 = 35
    check("x centrado = 40", abs(r["x"] - 40.0) < 1e-6, r["x"])
    check("y centrado = 35", abs(r["y"] - 35.0) < 1e-6, r["y"])


def test_sheet_origin_apoyado_abajo_a_la_izquierda() -> None:
    _lamina(10.0, 20.0, 110.0, 70.0)
    r = sheet_mod.sheet_origin(width=40.0, height=20.0, margin_mm=10.0,
                               align="bottom-left")
    check("x = borde + margen = 12", abs(r["x"] - 12.0) < 1e-6, r["x"])
    check("y = borde + margen = 22", abs(r["y"] - 22.0) < 1e-6, r["y"])


def test_sheet_origin_el_margen_esta_en_mm_de_papel() -> None:
    """Es la confusion clasica: el margen es de PAPEL, no del modelo."""
    _lamina(0.0, 0.0, 100.0, 100.0, escala=0.05)   # 1:50 en metros
    r = sheet_mod.sheet_origin(width=10.0, height=10.0, margin_mm=20.0,
                               align="bottom-left")
    # 20 mm de papel a 0.05 u/mm son 1.0 unidad del modelo.
    check("20 mm de papel a 1:50 son 1.00 m",
          abs(r["marginModel"] - 1.0) < 1e-9, r["marginModel"])
    check("y el origen se corre eso", abs(r["x"] - 1.0) < 1e-6, r["x"])


def test_sheet_origin_dice_cuando_no_entra() -> None:
    _lamina(0.0, 0.0, 100.0, 50.0)      # util 100 x 50, margen 2 -> 96 x 46
    r = sheet_mod.sheet_origin(width=200.0, height=20.0, margin_mm=10.0)

    check("no entra", not r["fits"], r)
    check("dice cuanto falta de ancho",
          abs(r["shortBy"]["width"] - 104.0) < 1e-6, r["shortBy"])
    check("no falta de alto", abs(r["shortBy"]["height"]) < 1e-9, r["shortBy"])
    check("sugiere un denominador de uso corriente",
          r.get("suggestedScaleDenominator") in
          (25, 50, 75, 100, 125, 150, 200, 250, 500, 1000),
          r.get("suggestedScaleDenominator"))
    check("y a esa escala ya entraria",
          200.0 <= (r["suggestedScaleDenominator"] / 1000.0) * (96.0 / 0.2)
          + 1e-6, r.get("suggestedScaleDenominator"))
    check("lo explica sin proponer achicar el dibujo",
          "warning" in r and "escala" in r["warning"].lower()
          and "achicar" in r["warning"].lower(), r.get("warning"))


def test_sheet_origin_sin_lamina_se_niega() -> None:
    space.clear()
    try:
        sheet_mod.sheet_origin(width=10.0, height=10.0)
    except ValueError as exc:
        check("pide create_sheet en vez de suponer",
              "create_sheet" in str(exc), str(exc))
    else:
        check("pide create_sheet en vez de suponer", False, "no fallo")


def test_sheet_origin_argumentos_invalidos() -> None:
    _lamina(0.0, 0.0, 100.0, 50.0)
    for kwargs, porque in [({"width": 0.0, "height": 10.0}, "ancho cero"),
                           ({"width": 10.0, "height": -1.0}, "alto negativo"),
                           ({"width": 10.0, "height": 10.0,
                             "margin_mm": -1.0}, "margen negativo"),
                           ({"width": 10.0, "height": 10.0,
                             "align": "arriba"}, "align desconocido")]:
        try:
            sheet_mod.sheet_origin(**kwargs)
        except ValueError:
            check("rechaza %s" % porque, True)
        else:
            check("rechaza %s" % porque, False, "lo acepto")


def main() -> int:
    for fn in [test_rumbo_a_azimut,
               test_rumbo_como_viene_en_un_plano_real,
               test_rumbo_invalido_se_niega,
               test_ida_y_vuelta_con_create_construction_table,
               test_traverse_de_un_rectangulo_a_mano,
               test_traverse_arranca_donde_se_le_diga,
               test_traverse_avisa_cuando_no_cierra,
               test_traverse_datos_incompletos_se_niegan,
               test_sheet_origin_centra_de_verdad,
               test_sheet_origin_apoyado_abajo_a_la_izquierda,
               test_sheet_origin_el_margen_esta_en_mm_de_papel,
               test_sheet_origin_dice_cuando_no_entra,
               test_sheet_origin_sin_lamina_se_niega,
               test_sheet_origin_argumentos_invalidos]:
        print(fn.__name__)
        fn()

    space.clear()
    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: el cuadro de construccion se lee, y el dibujo sabe donde va.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
