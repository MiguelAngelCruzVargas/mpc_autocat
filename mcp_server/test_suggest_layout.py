"""Tests del generador de partido: la distribución sale YA válida.

La promesa de suggest_layout es fuerte: lo que devuelve pasa check_layout y
check_geometry SIEMPRE, para cualquier combinación admitida de frente, fondo,
recámaras y baños. Acá se recorre la grilla completa de combinaciones — si
una sola falla, el generador está mintiendo.

NO necesita AutoCAD.

Uso:  python test_suggest_layout.py
"""
from __future__ import annotations

import sys

import rules

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def test_toda_la_grilla_sale_valida() -> None:
    """Cada combinación admitida tiene que pasar sus propios checks."""
    fallas = 0
    for w in (6.4, 8.0, 10.0, 12.0):
        for beds in (1, 2, 3, 4, 5, 6):
            for baths in (1, 2):
                r = rules.suggest_layout(w, 40.0, bedrooms=beds,
                                         bathrooms=baths)
                if not r["ok"]:
                    fallas += 1
                    FAILED.append(
                        f"grilla w={w} beds={beds} baths={baths}: "
                        + "; ".join(p["problem"] for p in r["problems"]))
    check("toda la grilla de combinaciones pasa sus checks", fallas == 0,
          f"{fallas} combinaciones fallaron")


def test_partido_tipico() -> None:
    r = rules.suggest_layout(8.0, 15.0, bedrooms=2, bathrooms=1)
    check("2 recamaras / 1 bano en 8x15 sale ok", r["ok"],
          str(r["problems"]))
    nombres = {room["name"] for room in r["rooms"]}
    for esperado in ("SALA", "COMEDOR", "COCINA", "BAÑO", "PASILLO",
                     "RECÁMARA PRINCIPAL", "RECÁMARA 2",
                     "PATIO DE SERVICIO"):
        check(f"tiene {esperado}", esperado in nombres, str(nombres))
    check("el patio queda al fondo",
          any(room["name"] == "PATIO DE SERVICIO"
              and abs(room["y1"] - 15.0) < 1e-9 for room in r["rooms"]),
          str(r["rooms"]))
    check("el acceso entra por la sala",
          any(d["from"] == "EXTERIOR" and d["to"] == "SALA"
              for d in r["doors"]), str(r["doors"]))


def test_bano_principal_en_suite() -> None:
    r = rules.suggest_layout(8.0, 20.0, bedrooms=3, bathrooms=2)
    check("con 2 banos sale valido", r["ok"], str(r["problems"]))
    puerta = [d for d in r["doors"] if d["to"] == "BAÑO PRINCIPAL"]
    check("el bano principal abre desde la recamara principal",
          len(puerta) == 1 and puerta[0]["from"] == "RECÁMARA PRINCIPAL",
          str(puerta))


def test_frente_chico_no_fuerza_minimos() -> None:
    r = rules.suggest_layout(5.0, 20.0)
    check("frente de 5 m se niega", not r["ok"], str(r))
    check("y dice el minimo que hace falta",
          any("6.40" in p["problem"] for p in r["problems"]),
          str(r["problems"]))
    check("sin inventar recintos", r["rooms"] == [], str(r["rooms"]))


def test_fondo_corto_dice_cuanto_falta() -> None:
    r = rules.suggest_layout(8.0, 10.0, bedrooms=4)
    check("fondo de 10 m para 4 recamaras se niega", not r["ok"], str(r))
    check("dice el fondo necesario", r.get("neededDepth", 0) > 10.0, str(r))


def test_una_recamara_no_deja_hueco_muerto() -> None:
    """Con una sola recamara, la columna derecha se llena con un estudio en
    vez de quedar un vacio que no es de nadie."""
    r = rules.suggest_layout(8.0, 15.0, bedrooms=1)
    check("1 recamara sale ok", r["ok"], str(r["problems"]))
    check("aparece el estudio del lado vacio",
          any(room["name"] == "ESTUDIO" for room in r["rooms"]),
          str([room["name"] for room in r["rooms"]]))


def test_avisa_recamaras_interiores() -> None:
    """Con muchas recamaras, las que no tocan el patio quedan interiores y
    hay que decirlo: la luz natural no es opcional en una vivienda real."""
    r = rules.suggest_layout(8.0, 40.0, bedrooms=6)
    check("6 recamaras sale ok", r["ok"], str(r["problems"]))
    check("avisa las recamaras sin luz",
          any("patio de luz" in a for a in r.get("warnings", [])),
          str(r.get("warnings")))


def main() -> int:
    for fn in [test_toda_la_grilla_sale_valida, test_partido_tipico,
               test_bano_principal_en_suite,
               test_frente_chico_no_fuerza_minimos,
               test_fondo_corto_dice_cuanto_falta,
               test_una_recamara_no_deja_hueco_muerto,
               test_avisa_recamaras_interiores]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: el generador de partido produce distribuciones validas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
