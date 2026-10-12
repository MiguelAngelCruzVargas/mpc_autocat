"""Secciones transversales contra el socket mockeado. NO necesita AutoCAD.

Salió en una prueba real: cuatro secciones de un camino con la rasante en
rojo puro, el terreno como una raya horizontal, sin título ni simbología —
nadie sabía qué eran las líneas rojas— y un "volumen" que era el del paquete
estructural, no el movimiento de tierras.

Uso:  python test_secciones.py
"""
from __future__ import annotations

import math
import sys

import preview

preview.install()

import profile as prof  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def _textos() -> list[str]:
    return [e.get("text", "") for e in preview.DRAWN if e["cmd"] == "create_text"]


def test_cadenamiento() -> None:
    check("0+005.00", prof.station_text(5.0) == "0+005.00", prof.station_text(5.0))
    check("1+250.40", prof.station_text(1250.4) == "1+250.40", prof.station_text(1250.4))


def test_areas_terraplen_y_corte() -> None:
    # Terraplén de 1 m bajo una calzada de 7 sin bombeo, paquete 0.30, talud
    # 1.5:1 desde la orilla de la rasante: 7 x 0.70 + 2 x (1.5 x 1 / 2) = 6.40
    preview.DRAWN.clear()
    r = prof.create_cross_section(0, 0, 0.0, 7.0, 100.0, ground_elev=99.0, crown=0.0,
                                  depth=0.30)
    check("terraplén: 6.40 m²", math.isclose(r["fillArea"], 6.40, abs_tol=0.03),
          str(r["fillArea"]))
    check("terraplén: sin corte", r["cutArea"] < 0.01, str(r["cutArea"]))
    # Corte de 1 m: desde la subrasante (99.70) sube 1.30 a 1.5:1.
    # 7 x 1.30 + 2 x (1.95 x 1.30 / 2) = 11.635
    r = prof.create_cross_section(0, 0, 0.0, 7.0, 100.0, ground_elev=101.0, crown=0.0,
                                  depth=0.30)
    check("corte: 11.64 m²", math.isclose(r["cutArea"], 11.635, abs_tol=0.03),
          str(r["cutArea"]))
    check("paquete aparte: 2.10 m²", math.isclose(r["pavementArea"], 2.10), str(r["pavementArea"]))


def test_terreno_en_ladera() -> None:
    # Terreno inclinado de lado a lado: corte de un lado y terraplén del otro.
    preview.DRAWN.clear()
    r = prof.create_cross_section(0, 0, 10.0, 4.0, 100.0, crown=0.02, depth=0.30,
                                  ground_profile=[[-10, 96.0], [10, 104.0]])
    check("ladera: hay corte Y terraplén", r["cutArea"] > 0.5 and r["fillArea"] > 0.5,
          f"{r['cutArea']} / {r['fillArea']}")
    ter = [e for e in preview.DRAWN if e["cmd"] == "create_polyline"
           and e.get("layer") == "SECCIONES-TERRENO"]
    check("terreno dibujado inclinado", ter and abs(ter[0]["points"][0][1]
                                                    - ter[0]["points"][-1][1]) > 1.0,
          str(ter[:1]))


def test_nada_en_colores_puros_y_rotulado() -> None:
    preview.DRAWN.clear()
    r = prof.create_cross_section_series(
        0, 0, [0.0, 5.0], 3.5, [{"station": 0, "elevation": 100.0},
                                {"station": 10, "elevation": 100.5}],
        ground=[[0, 99.6], [10, 100.9]], text_height=0.2)
    colores = {e.get("colorIndex") for e in preview.DRAWN} | {
        e.get("colorIndex") for e in preview.DRAWN if e["cmd"] == "set_layer"}
    check("sin rojo puro ni verde puro", not ({1, 3} & colores), str(colores))
    t = " | ".join(_textos())
    for esperado in ("0+000.00", "0+005.00", "RASANTE", "TERRENO NATURAL", "A. CORTE",
                     "RAS. ", "T.N. ", "SECCIONES TRANSVERSALES"):
        check(f"rotula '{esperado}'", esperado in t, t[:300])
    check("volúmenes de corte y terraplén", r["cutVolume"] is not None
          and r["fillVolume"] is not None, str(r))
    check("paquete por separado", math.isclose(r["pavementVolume"], 3.5 * 0.33 * 5.0,
                                               abs_tol=0.01), str(r["pavementVolume"]))


def test_superficie_y_eje() -> None:
    # Malla plana inclinada en X (z = 100 + 0.1 x) y eje hacia +Y: a la
    # izquierda del avance (x menor) el terreno es más bajo.
    malla = {"x0": -20.0, "y0": -5.0, "dx": 1.0, "dy": 1.0,
             "z": [[100 + 0.1 * (-20 + j) for j in range(41)] for _ in range(31)]}
    check("bilineal", math.isclose(prof.sample_surface(malla, 3.5, 2.0), 100.35),
          str(prof.sample_surface(malla, 3.5, 2.0)))
    preview.DRAWN.clear()
    r = prof.create_cross_section_series(
        0, 0, [5.0], 4.0, [{"station": 0, "elevation": 100.0},
                           {"station": 20, "elevation": 100.0}],
        surface=malla, alignment={"points": [[0, 0], [0, 20]]}, title=None)
    s = r["sections"][0]
    check("de la superficie: corte a la derecha y terraplén a la izquierda",
          s["cutArea"] > 0 and s["fillArea"] > 0, str(s))
    try:
        prof.create_cross_section_series(0, 0, [0.0], 4.0, [{"station": 0, "elevation": 1},
                                                            {"station": 1, "elevation": 1}],
                                         surface=malla)
        check("surface sin alignment falla", False)
    except ValueError:
        check("surface sin alignment falla", True)
    try:
        prof.create_cross_section_series(0, 0, [25.0], 4.0, [{"station": 0, "elevation": 1},
                                                             {"station": 1, "elevation": 1}],
                                         surface=malla, alignment={"points": [[0, 0], [0, 20]]})
        check("cadenamiento más allá del eje falla", False)
    except ValueError as e:
        check("cadenamiento más allá del eje falla", "0+025.00" in str(e), str(e))


def test_perfil_rotulado_y_sin_colores_puros() -> None:
    preview.DRAWN.clear()
    r = prof.create_profile(0, 0, 40.0, [{"station": 0, "elevation": 100.0},
                                         {"station": 40, "elevation": 102.0}],
                            ground=[[0, 99.5], [40, 103.0]], grid_station=10.0,
                            text_height=0.3, scale_text="ESC. H 1:200  V 1:40")
    colores = {e.get("colorIndex") for e in preview.DRAWN}
    check("perfil: sin rojo ni verde puros", not ({1, 3} & colores), str(colores))
    t = " | ".join(_textos())
    for esperado in ("PERFIL LONGITUDINAL", "RASANTE DE PROYECTO", "TERRENO NATURAL",
                     "0+010.00", "ESC. H 1:200"):
        check(f"perfil rotula '{esperado}'", esperado in t, t[:300])
    check("perfil devuelve su caja", len(r["box"]) == 4, str(r.get("box")))


def main() -> int:
    for t in (test_cadenamiento, test_areas_terraplen_y_corte, test_terreno_en_ladera,
              test_nada_en_colores_puros_y_rotulado, test_superficie_y_eje,
              test_perfil_rotulado_y_sin_colores_puros):
        print(t.__name__)
        t()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" - " + f)
        return 1
    print("\nOK: secciones transversales.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
