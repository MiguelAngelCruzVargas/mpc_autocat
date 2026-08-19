"""Tests de simbologia electrica. NO necesita AutoCAD.

Lo que verifica es que el simbolo sea el simbolo: una salida de techo tiene
cruz, un contacto apoya la cuerda contra el muro y abre hacia el ambiente, y
un tablero lleva medio relleno. Si eso se dibuja a mano en cada plano sale
distinto cada vez, que es exactamente el problema que la biblioteca resuelve.

Uso:  python test_electrical.py
"""
from __future__ import annotations

import math
import sys

import preview

preview.install()

import electrical as elec  # noqa: E402
import space               # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def limpiar() -> None:
    preview.DRAWN.clear()
    space.clear()


def _de(cmd: str) -> list[dict]:
    return [e for e in preview.DRAWN if e["cmd"] == cmd]


def test_lampara() -> None:
    limpiar()
    r = elec.place_devices([{"type": "lamp", "x": 3.0, "y": 2.0}])
    circulos = _de("create_circle")
    check("un circulo", len(circulos) == 1, str(len(circulos)))
    check("de 0.30 de diametro", abs(circulos[0]["radius"] - 0.15) < 1e-9,
          str(circulos[0]["radius"]))
    check("con la cruz adentro", len(_de("create_line")) == 2,
          str(len(_de("create_line"))))
    check("la caja abarca el simbolo",
          r["devices"][0]["box"] == [2.85, 1.85, 3.15, 2.15],
          str(r["devices"][0]["box"]))


def test_apagador_apunta_al_ambiente() -> None:
    limpiar()
    elec.place_devices([{"type": "switch", "x": 1.85, "y": 0.175,
                         "angle": 90.0}])
    linea = _de("create_line")[0]
    check("la linea radial sale hacia el ambiente",
          linea["y2"] > linea["y1"] > 0.175,
          f'de {linea["y1"]:.3f} a {linea["y2"]:.3f}')
    check("y arranca en el borde del circulo",
          abs(linea["y1"] - (0.175 + 0.10)) < 1e-9, str(linea["y1"]))


def test_contacto_apoya_en_el_muro() -> None:
    limpiar()
    # Contacto sobre el muro izquierdo, abriendo hacia +X.
    elec.place_devices([{"type": "outlet", "x": 0.175, "y": 1.5,
                         "angle": 0.0, "double": True}])
    arco = _de("create_arc")[0]
    check("el semicirculo barre 180 grados",
          abs(((arco["endAngleDeg"] - arco["startAngleDeg"]) % 360) - 180) < 1e-6,
          f'{arco["startAngleDeg"]} a {arco["endAngleDeg"]}')
    check("de radio 0.15", abs(arco["radius"] - 0.15) < 1e-9, str(arco["radius"]))
    cuerda = _de("create_line")[0]
    check("la cuerda es vertical, apoyada en el muro",
          abs(cuerda["x1"] - cuerda["x2"]) < 1e-9,
          f'{cuerda["x1"]:.3f} vs {cuerda["x2"]:.3f}')
    check("el doble agrega su barra", len(_de("create_line")) == 2,
          str(len(_de("create_line"))))


def test_gfci_se_distingue_del_contacto_comun() -> None:
    limpiar()
    elec.place_devices([{"type": "outlet", "x": 0.0, "y": 0.0, "angle": 0.0}])
    comun = len(_de("create_line"))
    limpiar()
    elec.place_devices([{"type": "gfci", "x": 0.0, "y": 0.0, "angle": 0.0}])
    check("el gfci lleva una marca mas", len(_de("create_line")) == comun + 1,
          f"{len(_de('create_line'))} contra {comun}")


def test_tablero_medio_relleno() -> None:
    limpiar()
    r = elec.place_devices([{"type": "panel", "x": 5.85, "y": 2.5,
                             "angle": 90.0, "tag": "TG-1"}])
    check("dos contornos: el tablero y su mitad",
          len(_de("create_polyline")) == 2, str(len(_de("create_polyline"))))
    check("con un relleno solido", len(_de("create_hatch")) == 1,
          str(len(_de("create_hatch"))))
    caja = r["devices"][0]["box"]
    lado_largo = round(caja[3] - caja[1], 4)
    lado_corto = round(caja[2] - caja[0], 4)
    check("montado a lo largo del muro (0.40 x 0.15)",
          (lado_largo, lado_corto) == (0.40, 0.15),
          f"{lado_largo} x {lado_corto}")


def test_registra_huellas_para_los_rotulos() -> None:
    limpiar()
    elec.place_devices([{"type": "lamp", "x": 3.0, "y": 2.0, "tag": "L1"},
                        {"type": "switch", "x": 1.0, "y": 0.2, "tag": "Sa"}])
    check("cada dispositivo dejo su huella", len(space.FOOTPRINTS) == 2,
          str(len(space.FOOTPRINTS)))
    check("identificadas", {h["what"] for h in space.FOOTPRINTS}
          == {"lamp L1", "switch Sa"}, str([h["what"] for h in space.FOOTPRINTS]))


def test_canalizacion_en_arco_con_conductores() -> None:
    limpiar()
    r = elec.create_conduit([[0.0, 0.0], [4.0, 0.0]], sag=0.12,
                            conductors="//|T")
    poli = _de("create_polyline")[0]
    check("sale en arco, no recta",
          any(abs(b) > 1e-9 for b in (poli["bulges"] or [])),
          str(poli["bulges"]))
    check("no cerrada", not poli.get("closed"))
    check("el largo es el del recorrido", abs(r["length"] - 4.0) < 1e-9,
          str(r["length"]))
    check("una marca por conductor", len(r["marks"]) == 4, str(r["marks"]))
    check("dos fases, un neutro y tierra",
          [m["kind"] for m in r["marks"]] == ["/", "/", "|", "T"],
          str([m["kind"] for m in r["marks"]]))
    check("la tierra ademas lleva su letra",
          any(e["text"] == "T" for e in _de("create_text")),
          str([e["text"] for e in _de("create_text")]))
    check("las marcas caen sobre el tramo",
          all(-1e-9 <= m["x"] <= 4.0 + 1e-9 for m in r["marks"]),
          str([m["x"] for m in r["marks"]]))


def test_errores_claros() -> None:
    limpiar()
    casos = (
        ("tipo desconocido",
         lambda: elec.place_devices([{"type": "foco", "x": 0, "y": 0}]),
         "desconocido"),
        ("sin coordenadas",
         lambda: elec.place_devices([{"type": "lamp"}]), "necesita 'x'"),
        ("lista vacia", lambda: elec.place_devices([]), "no hay dispositivos"),
        ("canalizacion de un punto",
         lambda: elec.create_conduit([[0.0, 0.0]]), "al menos 2"),
        ("conductor invalido",
         lambda: elec.create_conduit([[0.0, 0.0], [1.0, 0.0]],
                                     conductors="X"), "desconocido"),
    )
    for nombre, fn, frag in casos:
        try:
            fn()
        except ValueError as exc:
            check(nombre, frag.lower() in str(exc).lower(), str(exc))
        else:
            check(nombre, False, "no dio error")


def main() -> int:
    for fn in [test_lampara, test_apagador_apunta_al_ambiente,
               test_contacto_apoya_en_el_muro,
               test_gfci_se_distingue_del_contacto_comun,
               test_tablero_medio_relleno,
               test_registra_huellas_para_los_rotulos,
               test_canalizacion_en_arco_con_conductores,
               test_errores_claros]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: la simbologia electrica sale normalizada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
