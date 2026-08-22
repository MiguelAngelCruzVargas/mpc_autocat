"""Tests de compose_layout: una lamina por layout. NO necesita AutoCAD.

El flujo de layouts es lo que hace un juego profesional: el dibujo vive UNA
sola vez en el modelo y cada lamina lo recorta con sus viewports. El modelo
se ve desordenado porque tiene todas las disciplinas encimadas; cada lamina
sale limpia porque su viewport muestra solo su pedazo.

Lo que fijan estos tests:

  - La cuenta del papel. 16.60 m a 1:100 son 166 mm. Esa division es TODO
    el flujo: si esta mal, el viewport muestra algo distinto de lo que su
    rotulo dice, y no hay forma de notarlo mirando la pantalla.
  - El viewport apunta al CENTRO de la caja del modelo que se le pidio.
  - El tamano de la hoja se le PREGUNTA al dibujo, no se supone.
  - Los titulos se dibujan parado en el layout, y se vuelve al que estaba.

Uso:  python test_compose_layout.py
"""
from __future__ import annotations

import autocad_client as acad
import compose
import layers
import symbols

FAILED: list[str] = []

ANCHO_HOJA, ALTO_HOJA = 841.0, 594.0        # A1 apaisada


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def cerca(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


class Grabadora:
    """Reemplaza acad.call y guarda todo lo que se le pidio."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.actual = "Model"
        self._n = 0

    def __call__(self, cmd, params=None):
        params = params or {}
        self.calls.append((cmd, params))
        self._n += 1
        if cmd == "list_layouts":
            return {"layouts": [
                {"name": "Model", "paperWidth": 297.0, "paperHeight": 420.0,
                 "isModel": True},
                {"name": "E-01", "paperWidth": ANCHO_HOJA,
                 "paperHeight": ALTO_HOJA, "isModel": False}],
                "current": self.actual}
        if cmd == "set_current_layout":
            self.actual = params.get("name")
            return {"current": self.actual}
        if cmd == "measure_text":
            return {"width": len(params.get("text", "")) * 0.6}
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
        reales = (acad.call, compose.acad.call, symbols.acad.call,
                  layers.acad.call)
        g = Grabadora()
        try:
            acad.call = g
            compose.acad.call = g
            symbols.acad.call = g
            layers.acad.call = g
            layers.reset()
            fn(g)
        finally:
            (acad.call, compose.acad.call, symbols.acad.call,
             layers.acad.call) = reales
            layers.reset()
    envuelto.__name__ = fn.__name__
    return envuelto


def vista(nombre, ancho, alto, denom, **extra):
    v = {"name": nombre, "box": [0, 0, ancho, alto],
         "scale_denominator": denom}
    v.update(extra)
    return v


# ------------------------------------------------- la cuenta del papel

@con_mock
def test_el_papel_que_ocupa_sale_de_la_escala(g: Grabadora) -> None:
    """16.60 m a 1:100 son 166 mm. Si esta cuenta falla, el viewport muestra
    otra cosa que la que dice su rotulo y nada lo delata."""
    r = compose.compose_layout(
        "E-01", [vista("planta", 16.60, 29.10, 100)],
        model_units="m", padding_mm=0.0)
    caja = r["placements"][0]["box"]
    check("166 mm de ancho", cerca(caja[2] - caja[0], 166.0), caja)
    check("291 mm de alto", cerca(caja[3] - caja[1], 291.0), caja)


@con_mock
def test_el_padding_agranda_la_ventana_no_el_dibujo(g: Grabadora) -> None:
    r = compose.compose_layout("E-01", [vista("planta", 10.0, 10.0, 100)],
                               model_units="m", padding_mm=5.0)
    caja = r["placements"][0]["box"]
    check("100 mm mas 5 de aire por lado", cerca(caja[2] - caja[0], 110.0),
          caja)


@con_mock
def test_en_centimetros_y_milimetros(g: Grabadora) -> None:
    cm = compose.compose_layout("E-01", [vista("v", 1000.0, 100.0, 100)],
                                model_units="cm", padding_mm=0.0)
    ancho = cm["placements"][0]["box"][2] - cm["placements"][0]["box"][0]
    check("1000 cm a 1:100 son 100 mm", cerca(ancho, 100.0), ancho)

    mm = compose.compose_layout("E-01", [vista("v", 10000.0, 1000.0, 100)],
                                model_units="mm", padding_mm=0.0)
    ancho = mm["placements"][0]["box"][2] - mm["placements"][0]["box"][0]
    check("10000 mm a 1:100 son 100 mm", cerca(ancho, 100.0), ancho)


# ------------------------------------------------------- el viewport

@con_mock
def test_el_viewport_apunta_al_centro_del_modelo(g: Grabadora) -> None:
    compose.compose_layout(
        "E-01", [{"name": "planta", "box": [100.0, 200.0, 116.0, 226.0],
                  "scale_denominator": 100}],
        model_units="m", padding_mm=0.0)
    vps = g.de("create_viewport")
    check("crea un viewport", len(vps) == 1, vps)
    if not vps:
        return
    vp = vps[0]
    check("mira al centro de la caja del modelo",
          cerca(vp["viewCenterX"], 108.0) and cerca(vp["viewCenterY"], 213.0),
          (vp["viewCenterX"], vp["viewCenterY"]))
    check("con su escala", cerca(vp["scaleDenominator"], 100), vp)
    check("y 1000 mm por unidad dibujando en metros",
          cerca(vp["modelUnitsPerMm"], 1000.0), vp)
    check("la ventana mide lo que ocupa en papel",
          cerca(vp["width"], 160.0) and cerca(vp["height"], 260.0),
          (vp["width"], vp["height"]))


@con_mock
def test_reporta_cada_viewport_con_su_escala(g: Grabadora) -> None:
    r = compose.compose_layout(
        "E-01", [vista("a", 10, 10, 50), vista("b", 10, 10, 100)],
        model_units="m")
    escalas = {v["name"]: v["scale"] for v in r["viewports"]}
    check("cada uno con la suya",
          escalas == {"a": "1:50", "b": "1:100"}, escalas)


@con_mock
def test_no_mueve_nada_del_modelo(g: Grabadora) -> None:
    """A diferencia de compose_sheet, esto solo crea ventanas que miran al
    modelo: el modelo queda exactamente como estaba."""
    compose.compose_layout("E-01", [vista("v", 10, 10, 100)],
                           model_units="m")
    check("no mueve entidades",
          not g.de("move_entities") and not g.de("move_entity"), g.calls)


# --------------------------------------------------------- la hoja

@con_mock
def test_el_papel_se_le_pregunta_al_dibujo(g: Grabadora) -> None:
    """create_layout elige el papel por nombre entre los del dispositivo, y
    el que sale puede no ser el que uno tenia en la cabeza. Componer sobre un
    tamano supuesto deja las vistas fuera de la hoja sin ningun error."""
    r = compose.compose_layout("E-01", [vista("v", 5, 5, 100)],
                               model_units="m")
    check("usa el papel real del layout",
          r["paper"] == [ANCHO_HOJA, ALTO_HOJA], r["paper"])


@con_mock
def test_la_franja_derecha_se_reserva(g: Grabadora) -> None:
    """Es donde va la columna de localizacion / simbologia / rotulo que se
    repite igual en todas las laminas del juego."""
    r = compose.compose_layout("E-01", [vista("v", 10, 10, 100)],
                               model_units="m", margin_mm=15.0,
                               reserved_right_mm=160.0, padding_mm=0.0)
    limite = ANCHO_HOJA - 15.0 - 160.0
    check("ninguna vista pasa del limite",
          all(p["box"][2] <= limite + 1e-6 for p in r["placements"]),
          [p["box"] for p in r["placements"]])
    check("y el ancho util lo refleja",
          cerca(r["availableWidth"], limite - 15.0), r["availableWidth"])


@con_mock
def test_layout_inexistente_da_error_claro(g: Grabadora) -> None:
    try:
        compose.compose_layout("NO-EXISTE", [vista("v", 5, 5, 100)],
                               model_units="m", create=False)
        check("avisa que el layout no existe", False, "no tiro ValueError")
    except ValueError as exc:
        check("avisa que el layout no existe", "No existe" in str(exc),
              str(exc))


# -------------------------------------------------------- los titulos

@con_mock
def test_los_titulos_van_en_el_layout_y_vuelve_al_previo(g: Grabadora) -> None:
    """Todo se dibuja en el espacio ACTIVO: hay que pararse en el layout y
    volver, o el titulo termina en el modelo."""
    compose.compose_layout("E-01", [vista("v", 5, 5, 100, title="PLANTA")],
                           model_units="m")
    cambios = [p["name"] for p in g.de("set_current_layout")]
    check("se para en el layout", "E-01" in cambios, cambios)
    check("y vuelve al que estaba", cambios and cambios[-1] == "Model",
          cambios)
    check("dibujo el titulo", len(g.de("create_text")) >= 1,
          g.de("create_text"))


@con_mock
def test_la_escala_del_titulo_se_arma_sola(g: Grabadora) -> None:
    r = compose.compose_layout("E-01", [vista("v", 5, 5, 75, title="CORTE")],
                               model_units="m")
    check("dice ESC. 1:75",
          r["placements"][0]["scaleText"] == "ESC. 1:75",
          r["placements"][0]["scaleText"])


# ------------------------------------------------------------ errores

@con_mock
def test_dry_run_no_toca_nada(g: Grabadora) -> None:
    r = compose.compose_layout("E-01", [vista("v", 5, 5, 100, title="X")],
                               model_units="m", dry_run=True)
    check("no crea el layout", not g.de("create_layout"), g.de("create_layout"))
    check("no crea viewports", not g.de("create_viewport"),
          g.de("create_viewport"))
    check("no dibuja titulos", not g.de("create_text"), g.de("create_text"))
    check("pero devuelve el plan", len(r["placements"]) == 1, r)
    check("y avisa que no aplico", r["applied"] is False, r)


@con_mock
def test_rechaza_lo_que_no_cierra(g: Grabadora) -> None:
    casos = [
        ([{"name": "v", "box": [0, 0, 1, 1]}], "m", "vista sin escala"),
        ([vista("v", 1, 1, 0)], "m", "escala cero"),
        ([vista("v", 1, 1, 100)], "pulgadas", "unidades invalidas"),
        ([], "m", "sin vistas"),
    ]
    for vistas, unidades, que in casos:
        try:
            compose.compose_layout("E-01", vistas, model_units=unidades)
            check("rechaza %s" % que, False, "no tiro ValueError")
        except ValueError:
            check("rechaza %s" % que, True)


def main() -> int:
    for fn in [test_el_papel_que_ocupa_sale_de_la_escala,
               test_el_padding_agranda_la_ventana_no_el_dibujo,
               test_en_centimetros_y_milimetros,
               test_el_viewport_apunta_al_centro_del_modelo,
               test_reporta_cada_viewport_con_su_escala,
               test_no_mueve_nada_del_modelo,
               test_el_papel_se_le_pregunta_al_dibujo,
               test_la_franja_derecha_se_reserva,
               test_layout_inexistente_da_error_claro,
               test_los_titulos_van_en_el_layout_y_vuelve_al_previo,
               test_la_escala_del_titulo_se_arma_sola,
               test_dry_run_no_toca_nada,
               test_rechaza_lo_que_no_cierra]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: un modelo, N laminas -- cada viewport a su escala y en su "
          "lugar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
