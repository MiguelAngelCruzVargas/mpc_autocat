"""Tests de check_text_placement. NO necesita AutoCAD: se mockea el socket.

El caso que motiva todo esto es real: un corte de barda dibujado con
create_polyline crudo, con el titulo "CORTE A-A / BARDA PERIMETRAL TIPO"
cayendo sobre la dala de cerramiento. check_annotations lo daba por bueno
porque compara contra un registro interno que las primitivas no llenan --
para el, ese dibujo estaba vacio.

Lo que fijan estos tests:

  - Se le pregunta AL DIBUJO, no a un registro. Un texto sobre geometria
    dibujada con primitivas tiene que salir igual.
  - Un texto sobre OTRA anotacion es un problema de otra clase, y se
    reporta aparte: se arregla distinto.
  - El propio texto no cuenta como estorbo de si mismo.

Uso:  python test_placement.py
"""
from __future__ import annotations

import autocad_client as acad
import placement

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


class Dibujo:
    """Un dibujo falso: entidades con caja, y consultas por ventana."""

    def __init__(self, entidades: list[dict]) -> None:
        self.ents = entidades
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, cmd, params=None):
        params = params or {}
        self.calls.append((cmd, params))

        if cmd == "get_entity":
            for e in self.ents:
                if e["handle"] == params["handle"]:
                    return {"handle": e["handle"], "type": e["type"],
                            "layer": e["layer"], "bbox": e.get("bbox")}
            raise acad.AutoCadError("eUnknownHandle")

        if cmd == "select_entities":
            tipos = params.get("types")
            x1, y1 = params.get("x1"), params.get("y1")
            x2, y2 = params.get("x2"), params.get("y2")
            out = []
            for e in self.ents:
                if tipos and e["type"] not in tipos:
                    continue
                if params.get("layers") and e["layer"] not in params["layers"]:
                    continue
                if x1 is not None:
                    b = e.get("bbox")
                    if not b:
                        continue
                    # crossing: se tocan las cajas
                    if b[2] < x1 or b[0] > x2 or b[3] < y1 or b[1] > y2:
                        continue
                out.append({"handle": e["handle"], "type": e["type"],
                            "layer": e["layer"]})
            return {"entities": out, "count": len(out)}

        return {}


def con(entidades):
    def deco(fn):
        def envuelto():
            real = acad.call
            g = Dibujo(entidades)
            try:
                acad.call = g
                placement.acad.call = g
                fn(g)
            finally:
                acad.call = real
                placement.acad.call = real
        envuelto.__name__ = fn.__name__
        return envuelto
    return deco


def ent(h, tipo, capa, x0, y0, x1, y1):
    return {"handle": h, "type": tipo, "layer": capa,
            "bbox": [x0, y0, x1, y1]}


# ------------------------------------------------- el caso de la barda

BARDA = [
    # La dala de cerramiento, dibujada con create_polyline crudo: NADA la
    # registra en space, asi que check_annotations no la ve.
    ent("DALA", "Polyline", "ARQ-CONCRETO", 0.325, 3.6, 0.475, 3.8),
    ent("HATCH", "Hatch", "ARQ-HATCH", 0.325, 3.6, 0.475, 3.8),
    # El titulo, cayendole encima.
    ent("TIT", "MText", "ARQ-ANOTACIONES", -0.93, 3.84, 1.75, 4.20),
]


@con(BARDA)
def test_detecta_el_titulo_sobre_la_dala(g: Dibujo) -> None:
    """Con margen 0 las cajas se tocan por 0.0 -- no alcanza. Con un
    margen chico, que es lo que se le exige a un plano, salta."""
    r = placement.check_text_placement(margin=0.05)
    check("lo detecta", not r["ok"], r)
    check("revisa el texto", r["checked"] == 1, r["checked"])
    if r["problems"]:
        p = r["problems"][0]
        check("dice que es sobre el dibujo", p["kind"] == "sobre el dibujo", p)
        check("nombra la dala",
              any(o["handle"] == "DALA" for o in p["over"]), p["over"])
        check("y da la capa del estorbo",
              any(o["layer"] == "ARQ-CONCRETO" for o in p["over"]), p["over"])


@con(BARDA)
def test_corriendo_el_titulo_queda_limpio(g: Dibujo) -> None:
    """Es la correccion real que se aplico: subirlo 0.35."""
    subido = [dict(e) for e in BARDA]
    for e in subido:
        if e["handle"] == "TIT":
            e["bbox"] = [-0.93, 4.19, 1.75, 4.55]
    g.ents = subido
    r = placement.check_text_placement(margin=0.05)
    check("ya no hay problema", r["ok"], r["problems"])


# ------------------------------------------------------ otras reglas

@con([ent("T1", "DBText", "TEXTOS", 0, 0, 2, 0.3),
      ent("T2", "DBText", "TEXTOS", 1, 0.1, 3, 0.4)])
def test_texto_sobre_texto_se_reporta_aparte(g: Dibujo) -> None:
    """Se arregla distinto que un texto sobre el dibujo, asi que no se
    mezclan en la misma bolsa."""
    r = placement.check_text_placement()
    check("lo detecta", not r["ok"], r)
    check("los dos se reportan", len(r["problems"]) == 2, r["problems"])
    check("como 'sobre otra anotacion'",
          all(p["kind"] == "sobre otra anotacion" for p in r["problems"]),
          [p["kind"] for p in r["problems"]])


@con([ent("SOLO", "DBText", "TEXTOS", 0, 0, 2, 0.3)])
def test_un_texto_solo_no_se_estorba_a_si_mismo(g: Dibujo) -> None:
    r = placement.check_text_placement()
    check("sale limpio", r["ok"], r["problems"])
    check("y dice que reviso uno", r["checked"] == 1, r)


@con([ent("T", "DBText", "TEXTOS", 0, 0, 2, 0.3),
      ent("FONDO", "Polyline", "REFERENCIA", 0, 0, 5, 5)])
def test_ignore_layers_deja_pasar_lo_que_va_debajo(g: Dibujo) -> None:
    """Una capa de fondo o de referencia va debajo a proposito."""
    sin = placement.check_text_placement()
    check("sin ignorar, lo marca", not sin["ok"], sin)
    con_ = placement.check_text_placement(ignore_layers=["REFERENCIA"])
    check("ignorandola, sale limpio", con_["ok"], con_["problems"])


@con([ent("T", "DBText", "TEXTOS", 0, 0, 2, 0.3),
      ent("LEJOS", "Polyline", "MUROS", 10, 10, 12, 12)])
def test_lo_que_esta_lejos_no_molesta(g: Dibujo) -> None:
    r = placement.check_text_placement()
    check("no inventa un problema", r["ok"], r["problems"])


@con([{"handle": "VACIO", "type": "DBText", "layer": "TEXTOS", "bbox": None},
      ent("T", "DBText", "TEXTOS", 0, 0, 2, 0.3)])
def test_un_texto_sin_caja_se_avisa_no_se_ignora(g: Dibujo) -> None:
    """Un plugin viejo no devuelve bbox. Callarlo haria creer que el dibujo
    esta revisado cuando no lo esta."""
    r = placement.check_text_placement()
    check("revisa solo el que tiene caja", r["checked"] == 1, r["checked"])
    check("y avisa del otro", r["warning"] and "no reportaron caja" in r["warning"],
          r["warning"])


@con([])
def test_margin_negativo_es_error(g: Dibujo) -> None:
    try:
        placement.check_text_placement(margin=-1)
        check("rechaza margin negativo", False, "no tiro ValueError")
    except ValueError:
        check("rechaza margin negativo", True)


def main() -> int:
    for fn in [test_detecta_el_titulo_sobre_la_dala,
               test_corriendo_el_titulo_queda_limpio,
               test_texto_sobre_texto_se_reporta_aparte,
               test_un_texto_solo_no_se_estorba_a_si_mismo,
               test_ignore_layers_deja_pasar_lo_que_va_debajo,
               test_lo_que_esta_lejos_no_molesta,
               test_un_texto_sin_caja_se_avisa_no_se_ignora,
               test_margin_negativo_es_error]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: el chequeo le pregunta al dibujo, no a un registro que las "
          "primitivas nunca llenan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
