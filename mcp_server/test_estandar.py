"""Tests del estándar de oficina, sin AutoCAD (acad.call simulado).

Uso:  python test_estandar.py
"""
from __future__ import annotations

import os
import sys
import tempfile

import estandar

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def _dibujo(capas, entidades, estilos):
    def fake(cmd, params=None):
        if cmd == "list_layers":
            return {"layers": capas}
        if cmd == "list_entities":
            return {"entities": entidades}
        if cmd == "list_styles":
            return {"textStyles": estilos}
        raise AssertionError(cmd)
    estandar.acad.call = fake


CAPAS = [{"name": "0", "colorIndex": 7, "linetype": "Continuous"},
         {"name": "MUROS", "colorIndex": 1, "linetype": "Continuous"},
         {"name": "EJES", "colorIndex": 4, "linetype": "Continuous"},
         {"name": "COTAS", "colorIndex": 12, "linetype": "Continuous"}]
ENTIDADES = ([{"layer": "0"}] * 3 + [{"layer": "MUROS"}] * 5
             + [{"layer": "EJES"}] * 2)
ESTILOS = [{"name": "Standard", "font": "txt"},
           {"name": "MCP-ARIAL", "font": "arial.ttf"}]


def test_minimo_sin_archivo() -> None:
    real = estandar.acad.call
    try:
        _dibujo(CAPAS, ENTIDADES, ESTILOS)
        with tempfile.TemporaryDirectory() as d:
            est = estandar.cargar(os.path.join(d, "no_existe.json"))
        r = estandar.revisar(est)
        reglas = sorted(p["rule"] for p in r["problems"])
        check("el mínimo marca capa 0, txt.shx y colores puros en uso",
              reglas == ["capa 0", "color puro", "color puro", "fuente"],
              str(reglas))
        check("una capa pura SIN entidades no molesta",
              not any("COTAS" in p["problem"] for p in r["problems"]))
    finally:
        estandar.acad.call = real


def test_estandar_de_la_oficina() -> None:
    real = estandar.acad.call
    try:
        _dibujo(CAPAS, ENTIDADES, ESTILOS)
        est = {"nombre": "Oficina X",
               "capas": {"MUROS": {"color": 7}, "EJES": {"color": 32,
                                                         "linetype": "CENTER2"}},
               "capas_obligatorias": ["MUROS", "TEXTOS"],
               "prohibir_capa_0": False, "fuentes_prohibidas": []}
        r = estandar.revisar(est)
        textos = " | ".join(p["problem"] for p in r["problems"])
        check("falta la capa obligatoria TEXTOS", "TEXTOS" in textos, textos)
        check("MUROS en color 1 cuando el estándar pide 7",
              "'MUROS' tiene color 1" in textos, textos)
        check("EJES con tipo de línea equivocado", "CENTER2" in textos, textos)
        check("una capa del estándar no se marca además como 'color puro'",
              not any(p["rule"] == "color puro" and "'MUROS'" in p["problem"]
                      for p in r["problems"]), textos)
        check("respeta prohibir_capa_0=False",
              not any(p["rule"] == "capa 0" for p in r["problems"]))
    finally:
        estandar.acad.call = real


def test_guardar_y_errores_claros() -> None:
    with tempfile.TemporaryDirectory() as d:
        ruta = os.path.join(d, "est.json")
        estandar.guardar({"nombre": "Y", "capas": {"MUROS": {"color": 7}}}, ruta)
        check("se guarda y se vuelve a leer",
              estandar.cargar(ruta)["capas"]["MUROS"]["color"] == 7)
    for malo, frag in (({"capas": []}, "capas"),
                       ({"capas": {"M": {"color": 300}}}, "1-255"),
                       ({"capas_obligatorias": "MUROS"}, "lista"),
                       ([], "objeto")):
        try:
            estandar.validar(malo)
            check(f"error claro ({frag})", False, "no falló")
        except ValueError as exc:
            check(f"error claro ({frag})", frag in str(exc), str(exc))


def main() -> int:
    for t in (test_minimo_sin_archivo, test_estandar_de_la_oficina,
              test_guardar_y_errores_claros):
        print(t.__name__)
        t()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" - " + f)
        return 1
    print("\nOK: el dibujo se revisa contra el estándar de la oficina.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
