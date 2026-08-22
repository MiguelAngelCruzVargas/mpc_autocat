"""Tests del armado en elevacion. NO necesita AutoCAD.

Lo que fijan, en orden de importancia:

  - La separacion de estribos es un MAXIMO de obra. "est. #3 @ 20 cms" no
    admite que el paso real se pase de 20: cerrar parejo tiene que redondear
    siempre hacia MAS estribos. Uno de menos es un error estructural; uno de
    mas es un centimetro de acero.
  - stirrup_spacing NO tiene default. Es un dato del proyecto, y una tool
    que lo inventa dibuja un armado que nadie calculo.
  - Los numeros que devuelve son los del dibujo que quedo, no los que se
    pidieron: es lo que permite que calculate_quantities mida en vez de
    recordar.

Uso:  python test_rebar_elevation.py
"""
from __future__ import annotations

import autocad_client as acad
import layers
import rebar
import space

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def cerca(a: float, b: float, tol: float = 1e-4) -> bool:
    return abs(a - b) <= tol


class Grabadora:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._n = 0

    def __call__(self, cmd, params=None):
        params = params or {}
        self.calls.append((cmd, params))
        self._n += 1
        if cmd == "list_layers":
            return {"layers": []}
        if cmd == "list_styles":
            return {"textStyles": [{"name": "ARIAL", "font": "arial.ttf",
                                    "isCurrent": True}]}
        return {"handle": "H%d" % self._n}

    def de(self, cmd: str) -> list[dict]:
        return [p for c, p in self.calls if c == cmd]


def con_mock(fn):
    def envuelto():
        reales = (acad.call, rebar.acad.call, layers.acad.call)
        g = Grabadora()
        space.clear()
        try:
            acad.call = g
            rebar.acad.call = g
            layers.acad.call = g
            layers.reset()
            fn(g)
        finally:
            acad.call, rebar.acad.call, layers.acad.call = reales
            layers.reset()
            space.clear()
    envuelto.__name__ = fn.__name__
    return envuelto


# ------------------------------------- la separacion es un MAXIMO de obra

def test_la_separacion_nunca_se_pasa_de_la_pedida() -> None:
    """Un estribo de MENOS es un error estructural; uno de mas es un
    centimetro de acero. El redondeo va siempre hacia mas."""
    for largo, pedido in [(2.40, 0.20), (2.50, 0.20), (3.10, 0.25),
                          (1.07, 0.15), (0.95, 0.30), (5.0, 0.20)]:
        pos, paso, _ = rebar._posiciones_estribos(0.0, largo, pedido)
        check("%.2f m @ %.2f: el paso real no se pasa" % (largo, pedido),
              paso <= pedido + 1e-9, "paso real %.4f" % paso)
        check("%.2f m @ %.2f: los estribos cubren el largo" % (largo, pedido),
              cerca(pos[-1] - pos[0], largo), (pos[0], pos[-1]))


def test_cuando_cierra_justo_no_avisa_nada() -> None:
    pos, paso, av = rebar._posiciones_estribos(0.0, 2.40, 0.20)
    check("2.40 @ 0.20 da 13 estribos", len(pos) == 13, len(pos))
    check("con el paso exacto", cerca(paso, 0.20), paso)
    check("y sin aviso", not av, av)


def test_cuando_no_cierra_justo_lo_dice() -> None:
    pos, paso, av = rebar._posiciones_estribos(0.0, 2.50, 0.20)
    check("2.50 @ 0.20 da 14 estribos", len(pos) == 14, len(pos))
    check("cerrando a 0.1923", cerca(paso, 0.1923), paso)
    check("y lo avisa", any("real" in a for a in av), av)


def test_confinamiento_junta_los_extremos() -> None:
    """Asi se arma una columna de verdad: el confinamiento manda en los
    extremos, no en el centro."""
    pos, _, _ = rebar._posiciones_estribos(0.0, 3.00, 0.20, 0.60, 0.10)
    sep_extremo = pos[1] - pos[0]
    medio = len(pos) // 2
    sep_centro = pos[medio + 1] - pos[medio]
    check("los extremos van mas juntos que el centro",
          sep_extremo < sep_centro - 1e-6,
          "extremo %.3f vs centro %.3f" % (sep_extremo, sep_centro))
    check("el extremo cierra al paso de confinamiento",
          cerca(sep_extremo, 0.10), sep_extremo)


def test_confinamiento_que_cubre_todo_avisa() -> None:
    pos, _, av = rebar._posiciones_estribos(0.0, 1.00, 0.20, 0.80, 0.10)
    check("avisa que el confinamiento cubre la pieza entera",
          any("toda" in a for a in av), av)


def test_sin_separacion_no_dibuja() -> None:
    """Es un dato del proyecto. Una tool que lo inventa dibuja un armado que
    nadie calculo."""
    for paso in (0.0, -0.20):
        try:
            rebar._posiciones_estribos(0.0, 2.0, paso)
            check("rechaza separacion %s" % paso, False, "no tiro ValueError")
        except ValueError as exc:
            check("rechaza separacion %s" % paso, "no se inventa" in str(exc),
                  str(exc)[:60])


# ----------------------------------------------------------- el dibujo

@con_mock
def test_dibuja_estribos_y_varillas(g: Grabadora) -> None:
    r = rebar.create_rebar_elevation(
        x=0.0, y=0.0, width=0.40, height=2.40,
        stirrup_spacing=0.20, bars_interior=2, cover=0.03)

    check("13 estribos", r["stirrupCount"] == 13, r["stirrupCount"])
    check("4 varillas (2 de borde + 2 interiores)", r["barCount"] == 4,
          r["barCount"])
    lineas = g.de("create_line")
    check("dibuja una linea por estribo y por varilla",
          len(lineas) == 13 + 4, len(lineas))
    check("dibuja el contorno", len(g.de("create_polyline")) == 1,
          g.de("create_polyline"))

    horizontales = [p for p in lineas if cerca(p["y1"], p["y2"])]
    check("los estribos son transversales", len(horizontales) == 13,
          len(horizontales))
    if horizontales:
        e = horizontales[0]
        check("y van de recubrimiento a recubrimiento",
              cerca(e["x1"], 0.03) and cerca(e["x2"], 0.37),
              (e["x1"], e["x2"]))


@con_mock
def test_las_varillas_corren_a_lo_largo(g: Grabadora) -> None:
    rebar.create_rebar_elevation(x=0.0, y=0.0, width=0.40, height=2.40,
                                 stirrup_spacing=0.20, cover=0.03)
    verticales = [p for p in g.de("create_line") if cerca(p["x1"], p["x2"])]
    check("2 varillas de borde", len(verticales) == 2, len(verticales))
    xs = sorted(p["x1"] for p in verticales)
    check("en las esquinas del estribo",
          cerca(xs[0], 0.03) and cerca(xs[1], 0.37), xs)


@con_mock
def test_horizontal_intercambia_los_ejes(g: Grabadora) -> None:
    """Una trabe de liga vista en elevacion: las varillas corren en X."""
    r = rebar.create_rebar_elevation(
        x=0.0, y=0.0, width=3.00, height=0.40,
        stirrup_spacing=0.15, orientation="horizontal", cover=0.03)
    lineas = g.de("create_line")
    verticales = [p for p in lineas if cerca(p["x1"], p["x2"])]
    horizontales = [p for p in lineas if cerca(p["y1"], p["y2"])]
    check("los estribos son verticales",
          len(verticales) == r["stirrupCount"], len(verticales))
    check("las varillas corren horizontales", len(horizontales) == 2,
          len(horizontales))


@con_mock
def test_la_prolongacion_alarga_la_varilla(g: Grabadora) -> None:
    """El anclaje en la zapata y el traslape hacia arriba son varilla que se
    compra: tienen que contar en el largo."""
    sin = rebar.create_rebar_elevation(x=0, y=0, width=0.4, height=2.0,
                                       stirrup_spacing=0.2, cover=0.03)
    con = rebar.create_rebar_elevation(x=0, y=0, width=0.4, height=2.0,
                                       stirrup_spacing=0.2, cover=0.03,
                                       extend_start=0.30, extend_end=0.50)
    check("la varilla mide 0.80 m mas",
          cerca(con["barLength_m"] - sin["barLength_m"], 0.80),
          (sin["barLength_m"], con["barLength_m"]))
    check("y el total lo refleja",
          cerca(con["totalBarLength_m"],
                con["barLength_m"] * con["barCount"]), con)


# ------------------------------------------- lo que devuelve, para medir

@con_mock
def test_devuelve_lo_que_QUEDO_dibujado(g: Grabadora) -> None:
    """El mismo criterio de calculate_quantities: el numero sale de lo
    dibujado, no de lo que se pidio."""
    r = rebar.create_rebar_elevation(x=0, y=0, width=0.40, height=2.50,
                                     stirrup_spacing=0.20, cover=0.03,
                                     depth=0.40)
    check("informa la separacion PEDIDA",
          cerca(r["requestedStirrupSpacing_m"], 0.20), r)
    # 2.50 - 2x0.03 = 2.44 utiles; 2.44/0.20 = 12.2 -> 13 tramos de 0.18769.
    check("y la REAL, que es otra",
          cerca(r["actualStirrupSpacing_m"], 0.1877, 1e-3),
          r["actualStirrupSpacing_m"])
    check("el perimetro del estribo sale de la SECCION, no de la elevacion",
          cerca(r["stirrupPerimeter_m"], 2 * (0.34 + 0.34)),
          r["stirrupPerimeter_m"])
    check("y el acero de estribo es perimetro x cantidad",
          cerca(r["totalStirrupLength_m"],
                r["stirrupPerimeter_m"] * r["stirrupCount"], 1e-2), r)


@con_mock
def test_sin_depth_no_inventa_el_perimetro(g: Grabadora) -> None:
    """Una elevacion no ve la dimension de afuera del plano. Un perimetro
    inventado ahi se vuelve kilos de acero inventados en la cuantificacion."""
    r = rebar.create_rebar_elevation(x=0, y=0, width=0.40, height=2.0,
                                     stirrup_spacing=0.20)
    check("no devuelve perimetro", r["stirrupPerimeter_m"] is None, r)
    check("ni acero de estribo", r["totalStirrupLength_m"] is None, r)
    check("y explica por que",
          any("depth" in a for a in r["warnings"]), r["warnings"])


@con_mock
def test_registra_su_huella(g: Grabadora) -> None:
    rebar.create_rebar_elevation(x=1.0, y=2.0, width=0.4, height=2.0,
                                 stirrup_spacing=0.2)
    check("queda registrado en space", len(space.FOOTPRINTS) == 1,
          space.FOOTPRINTS)


@con_mock
def test_rechaza_lo_que_no_cierra(g: Grabadora) -> None:
    casos = [
        ({"orientation": "diagonal"}, "orientation invalida"),
        ({"width": 0}, "ancho cero"),
        ({"cover": 0.30}, "recubrimiento mas grande que la pieza"),
        ({"confinement_length": 0.5}, "confinamiento sin su separacion"),
        ({"confinement_spacing": 0.1}, "separacion de confinamiento sin zona"),
        ({"depth": 0.05, "cover": 0.03}, "depth menor que dos recubrimientos"),
    ]
    for kw, que in casos:
        base = dict(x=0, y=0, width=0.40, height=2.0, stirrup_spacing=0.20)
        base.update(kw)
        try:
            rebar.create_rebar_elevation(**base)
            check("rechaza %s" % que, False, "no tiro ValueError")
        except ValueError:
            check("rechaza %s" % que, True)


def main() -> int:
    for fn in [test_la_separacion_nunca_se_pasa_de_la_pedida,
               test_cuando_cierra_justo_no_avisa_nada,
               test_cuando_no_cierra_justo_lo_dice,
               test_confinamiento_junta_los_extremos,
               test_confinamiento_que_cubre_todo_avisa,
               test_sin_separacion_no_dibuja,
               test_dibuja_estribos_y_varillas,
               test_las_varillas_corren_a_lo_largo,
               test_horizontal_intercambia_los_ejes,
               test_la_prolongacion_alarga_la_varilla,
               test_devuelve_lo_que_QUEDO_dibujado,
               test_sin_depth_no_inventa_el_perimetro,
               test_registra_su_huella,
               test_rechaza_lo_que_no_cierra]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: el armado en elevacion sale calculado, con la separacion "
          "como maximo de obra y los numeros del dibujo que quedo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
