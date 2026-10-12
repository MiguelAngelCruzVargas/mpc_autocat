"""Tests de la red hidráulica en casas de dos niveles (sin AutoCAD).

Lo que salió en la planta alta de la casa en ladera: sin patio, el
calentador caía junto a la BAF, adentro de una recámara. Ahora la planta de
arriba recibe la caliente por una columna (hot_riser) y la de abajo la
manda con una salida extra (extra_outlets).

Uso:  python test_instalaciones_hid.py
"""
from __future__ import annotations

import sys

import instalaciones as inst

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


ROOMS = [{"name": "RECÁMARA 2", "x0": 0.0, "y0": 0.0, "x1": 4.0, "y1": 4.0},
         {"name": "BAÑO 2", "x0": 4.0, "y0": 0.0, "x1": 6.0, "y1": 3.0}]
MUEBLES = [{"type": "lavatory", "x": 5.0, "y": 2.7, "rotation_deg": 0.0, "room": "BAÑO 2"},
           {"type": "wc", "x": 4.4, "y": 1.0, "rotation_deg": 0.0, "room": "BAÑO 2"},
           {"type": "shower", "x": 5.5, "y": 0.5, "rotation_deg": 0.0, "room": "BAÑO 2"}]


def test_calentador_en_recamara_avisa() -> None:
    r = inst.suggest_hydraulic(ROOMS, fixtures=MUEBLES, supply=[0.45, 2.0], draw=False)
    check("sin patio ni heater: el calentador cae en la recámara y lo AVISA",
          any("RECÁMARA 2" in w for w in r["warnings"]), str(r["warnings"]))


def test_columna_de_agua_caliente() -> None:
    sube = [4.2, 2.8]
    r = inst.suggest_hydraulic(ROOMS, fixtures=MUEBLES, supply=[0.45, 2.0], hot_riser=sube,
                               draw=False)
    check("con hot_riser no hay aviso de calentador",
          not any("calentador quedó" in w for w in r["warnings"]), str(r["warnings"]))
    check("la caliente arranca de la columna", r["heater"] == sube, str(r["heater"]))
    arranques = {tuple(t["from"]) for t in r["hotPipes"]}
    check("la red caliente sale de la columna", tuple(sube) in arranques, str(arranques))
    # La fría no lleva ramal a un calentador que no existe: sus extremos son
    # los muebles y nada más.
    finales = {tuple(t["to"]) for t in r["coldPipes"]}
    check("la fría no alimenta la columna caliente", tuple(sube) not in finales, str(finales))
    check("UM totales = solo los muebles", r["totalUM"] == 3, str(r["totalUM"]))


def test_salida_extra_suma_su_carga() -> None:
    sube = {"point": [1.0, 3.8], "um": 6, "hot": True, "label": "SUBE AC"}
    sin = inst.suggest_hydraulic(ROOMS, fixtures=MUEBLES, supply=[0.45, 2.0],
                                 heater=[0.45, 3.5], draw=False)
    con = inst.suggest_hydraulic(ROOMS, fixtures=MUEBLES, supply=[0.45, 2.0],
                                 heater=[0.45, 3.5], extra_outlets=[sube], draw=False)
    check("la salida extra suma sus UM", con["totalUM"] == sin["totalUM"] + 6,
          f"{sin['totalUM']} -> {con['totalUM']}")
    tope_sin = max(t["load"] for t in sin["hotPipes"])
    tope_con = max(t["load"] for t in con["hotPipes"])
    check("la troncal caliente carga la columna que sube", tope_con == tope_sin + 6,
          f"{tope_sin} -> {tope_con}")
    check("sale en fixtures con su etiqueta",
          any(f["room"] == "SUBE AC" and f["hot"] for f in con["fixtures"]),
          str(con["fixtures"]))


def main() -> int:
    for t in (test_calentador_en_recamara_avisa, test_columna_de_agua_caliente,
              test_salida_extra_suma_su_carga):
        print(t.__name__)
        t()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" - " + f)
        return 1
    print("\nOK: hidráulica en dos niveles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
