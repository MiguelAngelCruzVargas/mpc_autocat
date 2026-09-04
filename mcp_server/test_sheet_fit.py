"""Tests de check_sheet / sheet.fit_report: que el dibujo entre en su lamina.

NO necesita AutoCAD: fit_report es geometria pura.

Lo que fija, y por que importa:

  - El caso que se vio en un plano de verdad: la planta trazada en el origen
    mientras el cajon vivia en otra parte, y la casa cruzando el marco. Todos
    los demas check_* daban limpio porque cada tool habia hecho bien SU parte.
  - La diferencia entre "esta corrido" y "no entra ni centrado". Se arreglan
    distinto -- mover, contra cambiar de formato o de escala -- y el consejo
    tiene que decir cual.
  - Sin lamina creada no se inventa un veredicto: se saltea y se dice.

Uso:  python test_sheet_fit.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import sheet as sheet_mod   # noqa: E402
import space                # noqa: E402

FAILED: list[str] = []

# Area util tipica de una A2 a 1:50 dibujando en metros.
AREA = {"x1": 0.0, "y1": 0.0, "x2": 20.0, "y2": 14.0}


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def ext(x0: float, y0: float, x1: float, y1: float) -> dict:
    return {"isEmpty": False, "minX": x0, "minY": y0, "maxX": x1, "maxY": y1}


def test_lo_que_entra_sale_limpio() -> None:
    r = sheet_mod.fit_report(ext(2.0, 2.0, 10.0, 12.0), AREA)
    check("entra: ok", r["ok"], r)
    check("no inventa problemas", r["count"] == 0, r["problems"])
    check("no reporta lados afuera", r["outsideBy"] == {}, r["outsideBy"])


def test_pegado_al_borde_todavia_entra() -> None:
    """Tocar el borde no es salirse: un dibujo que llena el area util exacta
    es correcto, y marcarlo como error obligaria a dejar un margen que la
    lamina ya tiene."""
    r = sheet_mod.fit_report(ext(0.0, 0.0, 20.0, 14.0), AREA)
    check("el borde exacto entra", r["ok"], r)


def test_corrido_dice_que_se_mueva() -> None:
    """La casa de 8x14 trazada en el origen con el cajon en otra parte."""
    r = sheet_mod.fit_report(ext(-3.0, -1.0, 5.0, 13.0), AREA)
    check("lo detecta", not r["ok"], r)
    check("dice por que lados se sale",
          r["outsideBy"] == {"left": 3.0, "bottom": 1.0}, r["outsideBy"])
    check("sabe que entra si se centra", r["fitsIfCentered"], r)
    check("aconseja mover, no cambiar de hoja",
          "corrido" in r["problems"][0]["fix"], r["problems"][0]["fix"])


def test_lo_que_no_entra_manda_a_cambiar_escala() -> None:
    r = sheet_mod.fit_report(ext(0.0, 0.0, 40.0, 30.0), AREA)
    check("lo detecta", not r["ok"], r)
    check("sabe que NO entra ni centrado", not r["fitsIfCentered"], r)
    check("manda a subir formato o escala",
          "escala" in r["problems"][0]["fix"], r["problems"][0]["fix"])
    check("y no sugiere achicar fuera de escala",
          "NUNCA achiques" in r["problems"][0]["fix"],
          r["problems"][0]["fix"])


def test_sin_lamina_no_inventa_veredicto() -> None:
    r = sheet_mod.fit_report(ext(0.0, 0.0, 5.0, 5.0), None)
    check("se saltea", r["ok"] and "skipped" in r, r)


def test_dibujo_vacio_no_es_un_problema() -> None:
    r = sheet_mod.fit_report({"isEmpty": True}, AREA)
    check("no protesta con el dibujo vacio", r["ok"] and "skipped" in r, r)


def test_create_sheet_registra_el_area() -> None:
    """Sin esto check_sheet no tiene contra que comparar."""
    space.clear()
    check("arranca sin lamina", space.sheet() is None, space.sheet())

    r = sheet_mod.create_sheet(sheet_format="A2", scale_denominator=50,
                               model_units="m", project="PRUEBA")
    area = space.sheet()
    check("create_sheet la registra", area is not None, area)
    if area:
        d = r["drawArea"]
        check("y es la misma que devolvio",
              abs(area["x1"] - d["x1"]) < 1e-9
              and abs(area["y2"] - d["y2"]) < 1e-9, (area, d))

    # Sobrevive al PROCESO: cada ConexionMcp levanta un server.py nuevo, y
    # el check corre en uno distinto del que dibujo. Sin esto check_sheet
    # contestaba "ok" por amnesia sobre un plano que se salia del cajon.
    guardada = space._leer_lamina_persistida()
    check("queda persistida en disco",
          guardada is not None
          and abs(guardada["x1"] - area["x1"]) < 1e-9, guardada)

    # Cambiar de dibujo la tiene que olvidar: describe UNA lamina.
    space.clear()
    check("cambiar de dibujo la olvida", space.sheet() is None, space.sheet())
    check("y tampoco queda en disco",
          space._leer_lamina_persistida() is None,
          space._leer_lamina_persistida())


def main() -> int:
    for fn in [test_lo_que_entra_sale_limpio,
               test_pegado_al_borde_todavia_entra,
               test_corrido_dice_que_se_mueva,
               test_lo_que_no_entra_manda_a_cambiar_escala,
               test_sin_lamina_no_inventa_veredicto,
               test_dibujo_vacio_no_es_un_problema,
               test_create_sheet_registra_el_area]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: el dibujo que se sale de su lamina ya no pasa desapercibido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
