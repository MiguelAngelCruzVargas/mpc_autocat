"""Tests de create_stairs (arch.py) contra el socket mockeado. NO necesita AutoCAD.

Verifica que la cantidad de escalones salga de la fórmula de Blondel y no de
un número fijo, que la contrahuella se recalcule para repartir exacto, que
una escalera incómoda o insegura tire error en vez de dibujarse, y que la
planta y el corte midan lo mismo (misma cantidad de escalones, mismo
recorrido total).

Uso:  python test_stairs.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import arch  # noqa: E402

FAILED: list[str] = []


def check(name: str, got, expected, tol: float = 1e-6) -> None:
    ok = (abs(got - expected) <= tol
          if isinstance(expected, float) else got == expected)
    if not ok:
        FAILED.append(f"{name}: esperaba {expected}, obtuve {got}")
    print(("  ok  " if ok else " FALLA ") + name)


def check_raises(name: str, fn, fragment: str) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        if fragment.lower() in str(exc).lower():
            print("  ok  " + name)
            return
        FAILED.append(f"{name}: error sin el texto {fragment!r}: {exc}")
    else:
        FAILED.append(f"{name}: no dio error")
    print(" FALLA " + name)


def lineas() -> list[dict]:
    return [e for e in preview.DRAWN if e["cmd"] == "create_line"]


def test_blondel_recalcula_contrahuella_exacta() -> None:
    preview.DRAWN.clear()
    r = arch.create_stairs(start_x=0, start_y=0, total_rise=2.80,
                           width=1.0, tread=0.28, riser=0.17,
                           view="planta")
    # 2.80 / 0.17 = 16.47 -> redondea a 16, contrahuella real = 2.80/16.
    check("cantidad de escalones (redondeo)", r["steps"], 16)
    check("contrahuella real recalculada", r["riser"], 2.80 / 16, tol=1e-4)
    check("huellas = escalones - 1", r["treads"], 15)
    check("recorrido total = huellas x huella", r["totalRun"], 15 * 0.28, tol=1e-4)
    blondel_esperado = 2 * (2.80 / 16) + 0.28
    check("blondel = 2xcontrahuella + huella", r["blondel"], blondel_esperado, tol=1e-4)
    check("la formula queda armada", "CH" in r["formula"] and "H x" in r["formula"], True)


def test_blondel_fuera_de_rango_falla() -> None:
    # contrahuella muy chica + huella normal generan blondel fuera de 60-64cm.
    check_raises(
        "blondel fuera de rango avisa la huella sugerida",
        lambda: arch.create_stairs(start_x=0, start_y=0, total_rise=2.0,
                                   width=1.0, tread=0.28, riser=0.13,
                                   view="planta"),
        "blondel")


def test_contrahuella_fuera_de_uso_falla() -> None:
    # Con un total_rise muy chico y riser objetivo alto, el redondeo puede
    # dar una contrahuella real por encima del maximo usable.
    check_raises(
        "contrahuella fuera del rango usable",
        lambda: arch.create_stairs(start_x=0, start_y=0, total_rise=0.42,
                                   width=1.0, tread=0.28, riser=0.20,
                                   view="planta"),
        "rango usable")


def test_huella_bajo_minimo_falla() -> None:
    check_raises(
        "huella menor al minimo usable",
        lambda: arch.create_stairs(start_x=0, start_y=0, total_rise=2.8,
                                   width=1.0, tread=0.15, riser=0.17,
                                   view="planta"),
        "mínimo usable")


def test_view_invalido_falla() -> None:
    check_raises(
        "view invalido",
        lambda: arch.create_stairs(start_x=0, start_y=0, total_rise=2.8,
                                   view="alzado"),
        "planta")


def test_planta_dibuja_zancas_y_huellas() -> None:
    preview.DRAWN.clear()
    r = arch.create_stairs(start_x=0, start_y=0, total_rise=2.80,
                           width=1.0, tread=0.28, riser=0.17,
                           direction_deg=0.0, handrail=True, view="planta")
    ls = lineas()
    # 2 zancas + (treads+1) huellas + 1 baranda + 1 eje de flecha = fijo.
    esperadas = 2 + (r["treads"] + 1) + 1 + 1
    check("cantidad de lineas en planta", len(ls), esperadas)
    check("las zancas miden el recorrido total",
          max(abs(e["x2"] - e["x1"]) for e in ls), r["totalRun"], tol=1e-4)
    check("la flecha de sentido devuelve punta y cola",
          "upArrowTip" in r and "upArrowTail" in r, True)


def test_planta_sin_baranda() -> None:
    preview.DRAWN.clear()
    r = arch.create_stairs(start_x=0, start_y=0, total_rise=2.80,
                           width=1.0, tread=0.28, riser=0.17,
                           direction_deg=0.0, handrail=False, view="planta")
    ls = lineas()
    esperadas = 2 + (r["treads"] + 1) + 1  # sin la linea de baranda
    check("sin baranda hay una linea menos", len(ls), esperadas)


def test_corte_perfil_en_zigzag() -> None:
    preview.DRAWN.clear()
    r = arch.create_stairs(start_x=0, start_y=0, total_rise=2.80,
                           width=1.0, tread=0.28, riser=0.17,
                           direction_deg=0.0, view="corte")
    perfil = r["profile"]
    # Arranca en (0,0) y termina en (totalRun, totalRise): el perfil sube
    # y avanza exactamente lo que dicen steps/treads, no una aproximacion.
    check("el perfil arranca en el origen del tramo", perfil[0], (0.0, 0.0))
    x_final, y_final = perfil[-1]
    check("el perfil termina a la altura total", y_final, r["totalRise"], tol=1e-4)
    check("el perfil termina al recorrido total", x_final, r["totalRun"], tol=1e-4)
    check("nivel inferior en y=0", r["bottomLevel"]["y"], 0.0)
    check("nivel superior en y=totalRise", r["topLevel"]["y"], r["totalRise"], tol=1e-4)


def test_planta_y_corte_miden_lo_mismo() -> None:
    kwargs = dict(start_x=0, start_y=0, total_rise=2.80, width=1.0,
                 tread=0.28, riser=0.17, direction_deg=0.0)
    planta = arch.create_stairs(view="planta", **kwargs)
    corte = arch.create_stairs(view="corte", **kwargs)
    check("misma cantidad de escalones en planta y corte",
          planta["steps"], corte["steps"])
    check("mismo recorrido total en planta y corte",
          planta["totalRun"], corte["totalRun"], tol=1e-6)


def main() -> int:
    for fn in [test_blondel_recalcula_contrahuella_exacta,
               test_blondel_fuera_de_rango_falla,
               test_contrahuella_fuera_de_uso_falla,
               test_huella_bajo_minimo_falla,
               test_view_invalido_falla,
               test_planta_dibuja_zancas_y_huellas,
               test_planta_sin_baranda,
               test_corte_perfil_en_zigzag,
               test_planta_y_corte_miden_lo_mismo]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: la escalera se calcula por Blondel, no a ojo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
