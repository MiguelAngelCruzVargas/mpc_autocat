"""Tests de rotulado que esquiva. NO necesita AutoCAD.

El rotulo encimado fue el error que aparecio en los tres planos seguidos: el
cadenamiento sobre la linea de eje, el dato de la tuberia sobre el
cadenamiento, la etiqueta de la zapata cruzada con la trabe. Las tres veces se
corrigio moviendo el texto a mano, que es la forma de que vuelva al plano
siguiente. Esto verifica que la tool lo resuelva sola.

Uso:  python test_labels.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import annotation as ann  # noqa: E402
import arch               # noqa: E402
import space              # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def limpiar() -> None:
    preview.DRAWN.clear()
    space.clear()
    space.set_scale(0.05)


def _cajas_de_texto() -> list[tuple]:
    return [(h["x0"], h["y0"], h["x1"], h["y1"]) for h in space.FOOTPRINTS
            if h["what"].startswith("rotulo")]


def _pisan(a, b, tol: float = 1e-9) -> bool:
    return (a[0] < b[2] - tol and a[2] > b[0] + tol
            and a[1] < b[3] - tol and a[3] > b[1] + tol)


def test_no_escribe_encima_del_elemento() -> None:
    limpiar()
    zapata = [3.70, 4.20, 5.30, 5.80]
    r = ann.place_labels([{"text": "Z-1 / D-1", "box": zapata}], height=0.125)
    check("el rotulo salio", r["count"] == 1, str(r))
    check("y no pisa la zapata", not _pisan(_cajas_de_texto()[0], zapata),
          f'{_cajas_de_texto()[0]} contra {zapata}')
    check("sin avisos", "warning" not in r, str(r.get("warning")))


def test_dos_rotulos_no_se_pisan_entre_si() -> None:
    limpiar()
    ann.place_labels([{"text": "Z-2 / D-1", "box": [0.0, 0.0, 1.2, 1.2]},
                      {"text": "Z-3 / D-1", "box": [1.3, 0.0, 2.5, 1.2]},
                      {"text": "Z-1 / D-1", "box": [2.6, 0.0, 3.8, 1.2]}],
                     height=0.125)
    cajas = _cajas_de_texto()
    choques = [(a, b) for i, a in enumerate(cajas) for b in cajas[i + 1:]
               if _pisan(a, b)]
    check("los tres rotulos quedaron separados", not choques, str(choques))


def test_esquiva_lo_que_dibujaron_las_tools() -> None:
    """Una trabe de liga registra su huella sola; el rotulo la esquiva."""
    limpiar()
    arch.create_walls(points=[[0.0, 0.0], [0.0, 9.7]], thickness=0.20,
                      layer="ESTR_TRABES_LIGA", draw_symbols=False)
    muros = [(h["x0"], h["y0"], h["x1"], h["y1"]) for h in space.FOOTPRINTS
             if h["what"].startswith("muro")]
    check("la trabe quedo registrada", len(muros) == 1, str(len(muros)))
    ann.place_labels([{"text": "TL-1 (20x35)", "x": 0.0, "y": 5.0}],
                     height=0.10)
    check("el rotulo no cae sobre la trabe",
          not _pisan(_cajas_de_texto()[0], muros[0]),
          f'{_cajas_de_texto()[0]} contra {muros[0]}')


def test_obstaculos_extra() -> None:
    limpiar()
    eje = [-0.05, 0.0, 9.05, 0.0]      # la linea de eje, como caja fina
    r = ann.place_labels([{"text": "0+020", "x": 2.0, "y": 0.0}],
                         height=0.10, obstacles=[eje])
    caja = _cajas_de_texto()[0]
    check("el cadenamiento no queda sobre la linea de eje",
          not _pisan(caja, (-0.05, -0.001, 9.05, 0.001)), str(caja))
    check("sin avisos", "warning" not in r, str(r.get("warning")))


def test_rotado_90() -> None:
    limpiar()
    r = ann.place_labels([{"text": "TL-1 (20x35)", "box": [0.0, 0.0, 0.2, 9.7],
                           "rotation": 90.0}], height=0.10)
    caja = _cajas_de_texto()[0]
    alto = caja[3] - caja[1]
    ancho = caja[2] - caja[0]
    check("el texto girado ocupa a lo largo, no a lo ancho", alto > ancho,
          f"ancho {ancho:.3f} alto {alto:.3f}")
    check("y no pisa la trabe", not _pisan(caja, (0.0, 0.0, 0.2, 9.7)),
          str(caja))
    check("se dibujo girado",
          preview.DRAWN[-1].get("rotationDeg") == 90.0, str(preview.DRAWN[-1]))


def test_avisa_cuando_no_hay_lugar() -> None:
    limpiar()
    # Todo el entorno ocupado: no hay donde ponerlo.
    for caja in ([-5, -5, -0.1, 5], [1.3, -5, 6, 5], [-5, 1.3, 6, 5],
                 [-5, -5, 6, -0.1]):
        space.track(*caja, what="lleno")
    r = ann.place_labels([{"text": "Z-3 / D-1", "box": [0.0, 0.0, 1.2, 1.2]}],
                         height=0.125)
    check("avisa que no encontro lugar", "warning" in r, str(r.keys()))
    check("y lo dibuja igual, no lo pierde", r["count"] == 1, str(r["count"]))
    check("lo lista como apretado", len(r.get("cramped", [])) == 1,
          str(r.get("cramped")))


def test_prefer() -> None:
    limpiar()
    r = ann.place_labels([{"text": "PV-1", "box": [0.0, 0.0, 1.0, 1.0],
                           "prefer": "bottom"}], height=0.125)
    caja = _cajas_de_texto()[0]
    check("respeta el lado preferido", caja[3] <= 0.0 + 1e-6,
          f"quedo en y {caja[1]:.3f}..{caja[3]:.3f}")


def test_el_rotulo_no_cambia_de_ambiente() -> None:
    """El caso real: el contacto del bano rotulado adentro de la recamara.

    No basta con que el texto no PISE el muro. En el plano electrico el
    rotulo termino 5 mm antes del divisorio, sin tocarlo, y por eso paso el
    chequeo de colision: quedo entero del lado equivocado, que se lee peor
    que si lo cruzara. Lo que hay que mirar es si el segmento del elemento a
    su rotulo atraviesa un muro.
    """
    limpiar()
    space.track(2.95, -96.0, 3.05, -92.0, "muro ELEC_ARQ_BASE")
    space.track(3.85, -93.15, 4.15, -92.85, "lamp L-BANO")   # tapa la derecha
    r = ann.place_labels([{"text": "C-3 GFCI",
                           "box": [3.025, -92.95, 3.325, -92.65]}],
                         height=0.125, gap=0.08)
    x = r["labels"][0]["x"]
    check("el rotulo se queda del lado del aparato", x > 3.05,
          f"quedo en x={x:.3f}, del otro lado del muro")
    check("y encontro lugar igual", r["labels"][0]["fits"], str(r["labels"][0]))


def test_sin_muro_de_por_medio_usa_el_mejor_lado() -> None:
    """La barrera no debe estorbar cuando no hay muro."""
    limpiar()
    space.track(3.85, -93.15, 4.15, -92.85, "lamp L-BANO")
    r = ann.place_labels([{"text": "C-3 GFCI",
                           "box": [3.025, -92.95, 3.325, -92.65]}],
                         height=0.125, gap=0.08)
    check("coloca sin problema", r["labels"][0]["fits"], str(r["labels"][0]))


def test_si_no_hay_nada_libre_prefiere_cruzar_a_no_rotular() -> None:
    """Un elemento sin rotular es peor que un rotulo en el ambiente vecino."""
    limpiar()
    space.track(2.95, -96.0, 3.05, -92.0, "muro")
    # Todo el lado del aparato ocupado: solo queda cruzar.
    for caja in ([3.05, -94.0, 6.0, -92.6], [3.05, -92.6, 6.0, -91.0],
                 [3.05, -96.0, 6.0, -94.0]):
        space.track(*caja, what="lleno")
    r = ann.place_labels([{"text": "C-3", "box": [3.06, -92.95, 3.30, -92.65]}],
                         height=0.125, gap=0.05)
    check("lo dibuja igual", r["count"] == 1, str(r))
    check("y avisa que quedo apretado", "warning" in r or not r["labels"][0]["fits"],
          str(r["labels"][0]))


def test_barreras_extra() -> None:
    limpiar()
    space.track(3.85, -93.15, 4.15, -92.85, "lamp")
    # Un limite que no es un muro registrado: se pasa a mano.
    r = ann.place_labels([{"text": "C-3 GFCI",
                           "box": [3.025, -92.95, 3.325, -92.65]}],
                         height=0.125, gap=0.08,
                         barriers=[[3.30, -96.0, 3.40, -92.0]])
    check("respeta la barrera pasada a mano",
          r["labels"][0]["x"] < 3.30 or not r["labels"][0]["fits"],
          str(r["labels"][0]))


def test_errores_claros() -> None:
    limpiar()
    for nombre, fn, frag in (
        ("lista vacia", lambda: ann.place_labels([], height=0.1), "nada que rotular"),
        ("altura invalida",
         lambda: ann.place_labels([{"text": "X", "x": 0, "y": 0}], height=0),
         "height"),
    ):
        try:
            fn()
        except ValueError as exc:
            check(nombre, frag.lower() in str(exc).lower(), str(exc))
        else:
            check(nombre, False, "no dio error")


def main() -> int:
    for fn in [test_no_escribe_encima_del_elemento,
               test_dos_rotulos_no_se_pisan_entre_si,
               test_esquiva_lo_que_dibujaron_las_tools,
               test_obstaculos_extra, test_rotado_90,
               test_avisa_cuando_no_hay_lugar, test_prefer,
               test_el_rotulo_no_cambia_de_ambiente,
               test_sin_muro_de_por_medio_usa_el_mejor_lado,
               test_si_no_hay_nada_libre_prefiere_cruzar_a_no_rotular,
               test_barreras_extra,
               test_errores_claros]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: los rotulos se ubican solos sin encimarse.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
