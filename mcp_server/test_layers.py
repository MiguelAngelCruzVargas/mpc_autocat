"""Tests de capas y color. NO necesita AutoCAD.

Dos bugs de la misma familia, que ya aparecieron dos veces:

1. Una tool se aseguraba su capa con set_layer y le pisaba el color y el
   grosor a una capa que el proyecto ya tenia configurada. Quien nombra sus
   capas VIAL_EJE / HIDRO_RED_DRENAJE lo hace justamente para controlar como
   se ve cada cosa, y la tool se lo deshacia.
2. Una tool forzaba el color POR ENTIDAD (colorIndex=1). La capa quedaba bien
   configurada y el dibujo igual salia rojo, que es peor todavia: parece un
   problema de la capa y no lo es.

La regla es una sola: la capa manda, las entidades van ByLayer.

Uso:  python test_layers.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import annotation as ann       # noqa: E402
import autocad_client          # noqa: E402
import civil                   # noqa: E402
import layers                  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def con_capas(existentes: list[str]):
    """Mock que ademas contesta list_layers y anota los set_layer."""
    hechos: list[dict] = []
    real = preview.fake_call

    def call(cmd, params=None):
        if cmd == "list_layers":
            return {"layers": [{"name": n} for n in existentes]}
        if cmd == "set_layer":
            hechos.append(params or {})
        return real(cmd, params or {})

    autocad_client.call = call
    for modulo in (civil, ann):
        modulo.acad.call = call
    layers.reset()
    preview.DRAWN.clear()
    return hechos


EJE = [[0.0, 0.0], [40.0, 0.0], [64.748737, 10.251263]]
BUL = [0.0, 0.198912367379658, 0.0]


def test_no_pisa_una_capa_existente() -> None:
    hechos = con_capas(["VIAL_EJE", "VIAL_RODADURA",
                        "VIAL_GUARNICION_BANQUETA"])
    civil.create_road(points=EJE, bulges=BUL, width=7.0, curb_width=0.15,
                      sidewalk_width=1.5, axis_layer="VIAL_EJE",
                      pavement_layer="VIAL_RODADURA",
                      curb_layer="VIAL_GUARNICION_BANQUETA",
                      sidewalk_layer="VIAL_GUARNICION_BANQUETA")
    tocadas = {h.get("name") for h in hechos}
    check("no reconfigura ninguna capa ya existente", not tocadas,
          f"reconfiguro {sorted(tocadas)}")


def test_crea_la_capa_que_falta() -> None:
    hechos = con_capas([])          # dibujo vacio: no hay ninguna
    civil.create_road(points=EJE, bulges=BUL, width=7.0, curb_width=0.15,
                      axis_layer="VIAL_EJE", pavement_layer="VIAL_RODADURA",
                      curb_layer="VIAL_GUARNICION_BANQUETA")
    tocadas = {h.get("name") for h in hechos}
    check("crea las que no existen",
          {"VIAL_EJE", "VIAL_RODADURA", "VIAL_GUARNICION_BANQUETA"} <= tocadas,
          f"creo {sorted(tocadas)}")
    check("y cada una una sola vez", len(hechos) == len(tocadas),
          f"{len(hechos)} llamadas para {len(tocadas)} capas")


def _colores(cmds: tuple[str, ...]) -> set:
    return {e.get("colorIndex") for e in preview.DRAWN if e["cmd"] in cmds}


def test_el_eje_de_la_calle_va_bylayer() -> None:
    con_capas(["VIAL_EJE"])
    civil.create_road(points=EJE, bulges=BUL, width=7.0, curb_width=0.15,
                      axis_layer="VIAL_EJE")
    ejes = [e for e in preview.DRAWN
            if e["cmd"] == "create_polyline" and e.get("layer") == "VIAL_EJE"]
    check("el eje se dibujo", len(ejes) == 1, f"{len(ejes)} polilineas")
    check("con color ByLayer, no forzado",
          all(e.get("colorIndex") is None for e in ejes),
          str([e.get("colorIndex") for e in ejes]))
    check("y con sus arcos reales",
          any(any(abs(b) > 1e-9 for b in (e.get("bulges") or [])) for e in ejes),
          "el eje salio sin bulges")


def test_el_cadenamiento_va_bylayer() -> None:
    con_capas(["ANOTACIONES_CADENAMIENTO"])
    ann.create_stationing(points=EJE, bulges=BUL, interval=20.0,
                          text_height=0.4, tick=1.0, station_format="short",
                          layer="ANOTACIONES_CADENAMIENTO")
    check("marcas y numeros en ByLayer",
          _colores(("create_line", "create_text")) == {None},
          str(_colores(("create_line", "create_text"))))


def test_los_defaults_no_usan_colores_puros() -> None:
    """Los indices 1-7 son de pantalla: en papel se lavan o no se leen."""
    import layers as L
    usados = {"ejes": L.COLOR_EJES, "cotas": L.COLOR_COTAS,
              "hidraulica": L.COLOR_HIDRAULICA,
              "vegetacion": L.COLOR_VEGETACION,
              "registros": L.COLOR_REGISTROS}
    malos = {k: v for k, v in usados.items() if v in L.EVITAR}
    check("la paleta no cae en ningun color a evitar", not malos, str(malos))
    check("el principal sigue siendo 7 (negro al imprimir)",
          L.COLOR_PRINCIPAL == 7, str(L.COLOR_PRINCIPAL))
    check("y el secundario el gris 8", L.COLOR_SECUNDARIO == 8,
          str(L.COLOR_SECUNDARIO))

    hechos = con_capas([])
    civil.create_road(points=EJE, bulges=BUL, width=7.0, curb_width=0.15,
                      sidewalk_width=1.5)
    colores = {h["name"]: h.get("colorIndex") for h in hechos}
    chillones = {n: c for n, c in colores.items() if c in L.EVITAR}
    check("create_road no crea capas con colores chillones", not chillones,
          str(chillones))


def main() -> int:
    for fn in [test_no_pisa_una_capa_existente, test_crea_la_capa_que_falta,
               test_el_eje_de_la_calle_va_bylayer,
               test_el_cadenamiento_va_bylayer,
               test_los_defaults_no_usan_colores_puros]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: la capa manda y las entidades van ByLayer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
