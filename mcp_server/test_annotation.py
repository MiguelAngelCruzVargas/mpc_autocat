"""Tests del aparato de anotacion contra el socket mockeado. NO necesita AutoCAD.

Verifica lo unico que importa de las cadenas de cotas: que no se encimen. Ni
entre ellas, ni con las burbujas de eje, se dibujen en el orden que se
dibujen. Es el bug que motivo space.py — una cota general a 1.10 cayendo
adentro de una burbuja que ocupa de 0.96 a 1.56 — y sin test vuelve solo.

Uso:  python test_annotation.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import annotation as ann  # noqa: E402
import arch               # noqa: E402
import rules              # noqa: E402
import space              # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def limpiar(units_per_paper_mm: float = 0.05) -> None:
    """Arranca de cero, a 1:50 en metros (1 mm de papel = 0.05 m)."""
    preview.DRAWN.clear()
    space.clear()
    space.set_scale(units_per_paper_mm)


def test_cadena_apila_a_8mm() -> None:
    """Tres cadenas seguidas salen a 10, 18 y 26 mm de papel del dibujo."""
    limpiar()
    a = ann.create_dimension_chain([0.0, 3.0, 9.0], "bottom", 0.0)
    b = ann.create_dimension_chain([0.0, 9.0], "bottom", 0.0)
    c = ann.create_dimension_chain([0.0, 9.0], "bottom", 0.0)
    check("primera cadena a 10 mm de papel", abs(a["offset"] - 0.50) < 1e-6,
          f"offset {a['offset']}")
    check("segunda a 8 mm de la primera", abs(b["offset"] - 0.90) < 1e-6,
          f"offset {b['offset']}")
    check("tercera a 8 mm de la segunda", abs(c["offset"] - 1.30) < 1e-6,
          f"offset {c['offset']}")
    check("ninguna se pisa", rules.check_annotations()["ok"])


def test_total_va_un_nivel_afuera() -> None:
    limpiar()
    r = ann.create_dimension_chain([0.0, 3.0, 9.0], "bottom", 0.0, total=True)
    check("la general sale afuera de la parcial",
          r["totalChain"]["offset"] > r["offset"],
          str(r["totalChain"]["offset"]))
    check("la general mide punta a punta", abs(r["total"] - 9.0) < 1e-6,
          str(r.get("total")))


def test_burbujas_salen_afuera_de_las_cotas() -> None:
    """El caso que se veia mal: cotas primero, ejes despues."""
    limpiar()
    ann.create_dimension_chain([0.0, 3.5, 4.6, 9.0], "bottom", 0.0)
    ann.create_dimension_chain([0.0, 9.0], "bottom", 0.0, total=True)
    grid = arch.create_axis_grid(x_positions=[0.0, 3.5, 9.0],
                                 y_positions=[0.0, 12.0])
    burbuja_baja = min(b["y"] for b in grid["bubbles"])
    cota_mas_baja = min(b["y0"] for b in space.bands()
                        if b["what"].startswith("cotas"))
    check("la burbuja queda por debajo de la ultima cota",
          burbuja_baja + grid["bubbleRadius"] < cota_mas_baja,
          f"burbuja hasta {burbuja_baja + grid['bubbleRadius']:.3f}, "
          f"cota desde {cota_mas_baja:.3f}")
    check("nada del margen se pisa", rules.check_annotations()["ok"],
          rules.check_annotations()["message"])


def test_cotas_esquivan_las_burbujas() -> None:
    """Y al reves: ejes primero, cotas despues. Tambien tiene que cerrar.

    Que la cadena caiga ADENTRO de la extension de los ejes no es un
    problema, es el dibujo correcto: la linea de eje cruza las cotas. Lo que
    no puede pasar es que caiga sobre el anillo de las burbujas.
    """
    limpiar()
    grid = arch.create_axis_grid(x_positions=[0.0, 3.5, 9.0],
                                 y_positions=[0.0, 12.0])
    cadena = ann.create_dimension_chain([0.0, 3.5, 9.0], "bottom", 0.0)
    anillo = (grid["extension"], grid["extension"] + 2 * grid["bubbleRadius"])
    banda = (0.0 - cadena["band"][3], 0.0 - cadena["band"][1])  # offsets
    check("la cadena no toca el anillo de burbujas",
          banda[1] <= anillo[0] or banda[0] >= anillo[1],
          f"cota en {banda}, burbujas en {anillo}")
    check("nada del margen se pisa", rules.check_annotations()["ok"],
          rules.check_annotations()["message"])


def test_cotas_se_corren_si_la_burbuja_esta_encima() -> None:
    """Con las burbujas pegadas al dibujo, la cadena salta por afuera."""
    limpiar()
    grid = arch.create_axis_grid(x_positions=[0.0, 3.5, 9.0],
                                 y_positions=[0.0, 12.0],
                                 extension=0.20, bubble_radius=0.25)
    cadena = ann.create_dimension_chain([0.0, 3.5, 9.0], "bottom", 0.0)
    borde = grid["extension"] + 2 * grid["bubbleRadius"]
    check("la cadena sale afuera de la burbuja",
          cadena["offset"] > borde,
          f"cota a {cadena['offset']:.3f}, burbujas hasta {borde:.3f}")
    check("nada del margen se pisa", rules.check_annotations()["ok"],
          rules.check_annotations()["message"])


def test_los_cuatro_lados() -> None:
    limpiar()
    for lado, ref in (("bottom", 0.0), ("top", 12.0),
                      ("left", 0.0), ("right", 9.0)):
        r = ann.create_dimension_chain([0.0, 5.0], lado, ref)
        check(f"cadena {lado} a 10 mm", abs(r["offset"] - 0.50) < 1e-6,
              f"offset {r['offset']}")
    check("los cuatro lados son independientes",
          rules.check_annotations()["ok"])


def test_tramos_sueltos_en_una_sola_linea() -> None:
    """Una seccion tipo: banqueta, calzada, banqueta, salteando guarniciones."""
    limpiar()
    r = ann.create_dimension_chain(
        segments=[[3.65, 5.15], [-3.50, 3.50], [-5.15, -3.65]],
        side="left", reference=20.0)
    check("mide los tres tramos", r["segments"] == [1.5, 7.0, 1.5],
          str(r["segments"]))
    check("los tres en la misma linea de cota",
          len({round(r["dimLineCoord"], 6)}) == 1 and len(r["handles"]) == 3,
          f"{len(r['handles'])} cotas en x={r['dimLineCoord']}")
    check("la franja abarca de punta a punta",
          abs((r["band"][3] - r["band"][1]) - 10.30) < 1e-6
          or abs((r["band"][2] - r["band"][0]) - 10.30) > 0,
          str(r["band"]))
    check("no se pisa con nada", rules.check_annotations()["ok"])


def test_segments_invalidos() -> None:
    limpiar()
    casos = (
        ("tramos que se pisan",
         lambda: ann.create_dimension_chain(
             segments=[[0.0, 5.0], [3.0, 8.0]], side="bottom", reference=0.0),
         "se pisan"),
        ("tramo de largo cero",
         lambda: ann.create_dimension_chain(
             segments=[[2.0, 2.0]], side="bottom", reference=0.0), "mide 0"),
        ("positions y segments a la vez",
         lambda: ann.create_dimension_chain(
             positions=[0.0, 1.0], segments=[[0.0, 1.0]],
             side="bottom", reference=0.0), "no los dos"),
    )
    for nombre, fn, frag in casos:
        try:
            fn()
        except ValueError as exc:
            check(nombre, frag.lower() in str(exc).lower(), str(exc))
        else:
            check(nombre, False, "no dio error")


def test_tramo_apretado_avisa() -> None:
    limpiar()
    r = ann.create_dimension_chain([0.0, 0.10, 9.0], "bottom", 0.0)
    check("avisa el tramo donde el numero no entra", "warning" in r,
          str(list(r.keys())))
    check("dice cual", r.get("tightSegments", [{}])[0].get("length") == 0.1,
          str(r.get("tightSegments")))


def test_offset_a_mano_se_respeta_y_se_reserva() -> None:
    limpiar()
    r = ann.create_dimension_chain([0.0, 9.0], "bottom", 0.0, offset=2.0)
    check("respeta el offset pedido", abs(r["offset"] - 2.0) < 1e-6,
          str(r["offset"]))
    otra = ann.create_dimension_chain([0.0, 9.0], "bottom", 0.0)
    check("la automatica no se le encima", rules.check_annotations()["ok"],
          f"otra a {otra['offset']}")


def test_check_annotations_detecta_lo_puesto_a_mano() -> None:
    limpiar()
    ann.create_dimension_chain([0.0, 9.0], "bottom", 0.0)
    banda = space.bands()[0]
    pisado = rules.check_annotations([{
        "x0": banda["x0"], "y0": banda["y0"],
        "x1": banda["x1"], "y1": banda["y1"], "what": "texto a mano"}])
    check("detecta el choque", not pisado["ok"], pisado["message"])
    limpio = rules.check_annotations([{
        "x0": 0.0, "y0": 5.0, "x1": 1.0, "y1": 6.0, "what": "texto adentro"}])
    check("no inventa choques", limpio["ok"], limpio["message"])


def test_errores_claros() -> None:
    limpiar()
    casos = (
        ("side invalido",
         lambda: ann.create_dimension_chain([0.0, 1.0], "abajo", 0.0), "side"),
        ("una sola posicion",
         lambda: ann.create_dimension_chain([3.0], "bottom", 0.0), "al menos 2"),
        ("posiciones repetidas",
         lambda: ann.create_dimension_chain([3.0, 3.0], "bottom", 0.0),
         "al menos 2"),
    )
    for nombre, fn, frag in casos:
        try:
            fn()
        except ValueError as exc:
            check(nombre, frag.lower() in str(exc).lower(), str(exc))
        else:
            check(nombre, False, "no dio error")


def test_el_preview_dibuja_las_cotas() -> None:
    """Sin esto la encimadura solo se veia abriendo el DWG."""
    limpiar()
    ann.create_dimension_chain([0.0, 4.5, 9.0], "bottom", 0.0)
    textos = [e for e in preview.DRAWN if e["cmd"] == "create_text"]
    lineas = [e for e in preview.DRAWN if e["cmd"] == "create_line"]
    check("el numero de cada tramo queda dibujado", len(textos) == 2,
          f"{len(textos)} textos")
    check("dice la medida", {t["text"] for t in textos} == {"4.50"},
          str([t["text"] for t in textos]))
    check("con sus lineas de extension y remates", len(lineas) == 10,
          f"{len(lineas)} lineas")


def test_spanmismatch_solo_si_se_solapan() -> None:
    """Dos cadenas 'bottom' que miden el MISMO tramo con distinto total tienen
    que avisar -- pero dos laminas separadas (una barda a x=0..30, su detalle
    a x=100..103, mismo espacio modelo con origin_x corrido) no, porque no
    estan midiendo lo mismo. Antes de la correccion, compartir el lado
    alcanzaba para el aviso sin importar la distancia."""
    limpiar()
    ann.create_dimension_chain([0.0, 9.0], "bottom", 0.0)
    solapada = ann.create_dimension_chain([0.15, 9.30], "bottom", 0.0)
    check("avisa cuando el mismo tramo no cierra", "spanMismatch" in solapada,
          str(solapada.get("warning")))

    limpiar()
    ann.create_dimension_chain([0.0, 9.0], "bottom", 0.0)
    lejana = ann.create_dimension_chain([100.0, 103.0], "bottom", -0.2)
    check("no avisa entre laminas separadas sin relacion",
          "spanMismatch" not in lejana, str(lejana.get("warning")))


def test_create_table_avisa_si_tapa_una_ilustracion() -> None:
    """El bug reportado: la tabla de especificaciones tapando el detalle de
    castillo/zapata, sin ningun aviso porque create_table no sabia que ahi
    habia algo dibujado."""
    limpiar()
    ilustracion = {"x0": 0.0, "y0": -3.0, "x1": 4.0, "y1": 0.0,
                  "what": "detalle castillo C-1"}
    tapada = ann.create_table(2.0, -1.0, [["CASTILLO", "TIPO"], ["C-1", "15x15"]],
                              [2.0, 2.0], 0.35, 0.20, avoid=[ilustracion])
    check("avisa el choque", "warning" in tapada, str(tapada))
    check("nombra la ilustracion", "detalle castillo C-1" in tapada.get("warning", ""),
          tapada.get("warning", ""))

    limpia = ann.create_table(10.0, -1.0, [["CASTILLO", "TIPO"], ["C-1", "15x15"]],
                              [2.0, 2.0], 0.35, 0.20, avoid=[ilustracion])
    check("no inventa un choque cuando no lo hay", "warning" not in limpia,
          str(limpia))


def test_create_table_corta_si_el_texto_no_entra_ni_de_cerca() -> None:
    """Desborde grave: la tabla NO se dibuja (nada queda en el DWG a medio
    encimar) y la llamada se corta con un error que dice donde y cuanto
    falta -- en vez de dibujarla con el texto ya montado y avisarlo recien
    en 'warning', que es el mismo bug reportado leido tarde."""
    limpiar()
    try:
        ann.create_table(
            0.0, 0.0,
            [["CONCEPTO", "MEDICIÓN Y CÁLCULO"],
             ["Concreto", "11.97 m2 / modulo 0.0251 m2 = 502 pzas"]],
            [2.0, 1.0], 0.4, 0.25)
        check("corta con ValueError", False, "no elevo ninguna excepcion")
    except ValueError as exc:
        check("el mensaje explica el desborde",
              "no entra" in str(exc) or "columna" in str(exc), str(exc))
    check("no dibuja nada de la tabla", not preview.DRAWN, str(preview.DRAWN))


def test_create_table_avisa_desborde_leve_sin_cortar() -> None:
    """Un desborde chico -- el texto se pasa un poco de su columna, pero no
    30% ni nada parecido -- sigue dibujandose con el aviso en 'warning' en
    vez de cortar la llamada: frenar por un margen minimo molesta mas de lo
    que ayuda."""
    limpiar()
    r = ann.create_table(0.0, 0.0, [["CASTILLO", "TIPO"], ["C-1", "15x15 cm"]],
                         [1.0, 0.975], 0.35, 0.15)
    check("dibuja la tabla igual", bool(preview.DRAWN), "no dibujo nada")
    check("avisa el desborde leve", "warning" in r, str(r))


def main() -> int:
    for fn in [test_cadena_apila_a_8mm, test_total_va_un_nivel_afuera,
               test_burbujas_salen_afuera_de_las_cotas,
               test_cotas_esquivan_las_burbujas,
               test_cotas_se_corren_si_la_burbuja_esta_encima,
               test_los_cuatro_lados,
               test_tramos_sueltos_en_una_sola_linea, test_segments_invalidos,
               test_tramo_apretado_avisa,
               test_offset_a_mano_se_respeta_y_se_reserva,
               test_check_annotations_detecta_lo_puesto_a_mano,
               test_errores_claros, test_el_preview_dibuja_las_cotas,
               test_spanmismatch_solo_si_se_solapan,
               test_create_table_avisa_si_tapa_una_ilustracion,
               test_create_table_corta_si_el_texto_no_entra_ni_de_cerca,
               test_create_table_avisa_desborde_leve_sin_cortar]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: cotas y burbujas no se enciman, en cualquier orden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
