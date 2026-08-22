"""Corre toda la bateria de tests de una sola vez.

Existe porque los tests son scripts sueltos (`python test_arch.py`), no una
suite de pytest: son 24 archivos y correrlos a mano uno por uno significa,
en la practica, que nadie los corre todos. El que se saltea es siempre el
mismo que se rompio.

Cada test corre en su PROPIO proceso, a proposito: varios modulos guardan
estado de proceso (`space.OCCUPIED`, `layers._EXISTING`, la escala
persistida) y un import compartido haria que el resultado de un test
dependiera de cual corrio antes.

    python run_tests.py            # TODO, incluido lo que necesita AutoCAD
    python run_tests.py --no-live  # solo lo offline (sin AutoCAD a mano)
    python run_tests.py -k rebar   # solo los que matcheen

Con AutoCAD abierto corre TAMBIEN test_live.py, y eso NO es opcional por
capricho: las suites offline mockean el socket, asi que verifican la
matematica y las reglas pero no que el dibujo salga. En una sola sesion
aparecieron CUATRO bugs que las 29 suites verdes no podian ver -- new_document
fallando con AutoCAD vacio, el perimetro de estribo 4x de mas, la lamina que
quedaba vacia, la anotacion que se quedaba huerfana. Verde sin AutoCAD no
quiere decir que funcione: quiere decir que las cuentas cierran.

Devuelve 0 si pasaron todos, 1 si fallo alguno: sirve tal cual para un hook
de pre-commit o para CI.
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
import time

# Necesita AutoCAD abierto con el plugin cargado, asi que no entra en la
# corrida por defecto: fallaria en cualquier maquina sin AutoCAD.
NEEDS_AUTOCAD = {"test_live.py"}

# La salida de los tests trae acentos, y con errors="replace" ademas puede
# traer U+FFFD. Imprimir eso en una consola cp1252 (el default en Windows)
# revienta el runner ENTERO con UnicodeEncodeError -- perdiendo el reporte
# de todo lo que ya habia corrido. Paso de verdad: 17 suites en verde y el
# resumen nunca se imprimio.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

AQUI = os.path.dirname(os.path.abspath(__file__))


def autocad_responde() -> bool:
    """Un ping corto, para decidir si los live pueden correr."""
    try:
        sys.path.insert(0, AQUI)
        import autocad_client as acad
        viejo = acad.TIMEOUT
        acad.TIMEOUT = 5.0
        try:
            acad.call("ping", {})
            return True
        finally:
            acad.TIMEOUT = viejo
    except Exception:
        return False


def descubrir(patron: str | None, live: bool) -> list[str]:
    archivos = sorted(os.path.basename(p)
                      for p in glob.glob(os.path.join(AQUI, "test_*.py")))
    if not live:
        archivos = [a for a in archivos if a not in NEEDS_AUTOCAD]
    if patron:
        archivos = [a for a in archivos if patron in a]
    return archivos


def correr(archivo: str) -> tuple[bool, float, str]:
    inicio = time.monotonic()
    proc = subprocess.run(
        [sys.executable, archivo],
        cwd=AQUI, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    return proc.returncode == 0, time.monotonic() - inicio, proc.stdout + proc.stderr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-live", dest="no_live", action="store_true",
                    help="saltear los que necesitan AutoCAD (por defecto se "
                         "corren si AutoCAD responde)")
    ap.add_argument("--live", action="store_true",
                    help="exigir los live: si AutoCAD no responde, falla")
    ap.add_argument("-k", dest="patron", default=None,
                    help="correr solo los tests cuyo nombre contenga esto")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="mostrar la salida completa de cada test")
    args = ap.parse_args()

    hay_autocad = autocad_responde()
    if args.live and not hay_autocad:
        print("Se pidio --live y AutoCAD no responde. Abrilo con el plugin "
              "cargado, o corre --no-live.")
        return 1
    live = hay_autocad and not args.no_live

    archivos = descubrir(args.patron, live)
    if not archivos:
        print("No hay tests que correr.")
        return 1

    fallados: list[tuple[str, str]] = []
    total = 0.0

    for archivo in archivos:
        ok, seg, salida = correr(archivo)
        total += seg
        print(("  ok    " if ok else " FALLA  ") + f"{archivo:<28} {seg:5.1f}s")
        if args.verbose or not ok:
            for linea in salida.rstrip().splitlines():
                print("         | " + linea)
        if not ok:
            fallados.append((archivo, salida))

    print()
    if fallados:
        print(f"{len(fallados)} de {len(archivos)} FALLARON ({total:.1f}s):")
        for archivo, _ in fallados:
            print("  -", archivo)
        return 1

    print(f"OK: {len(archivos)} suites en {total:.1f}s.")
    if live:
        print("Incluye test_live.py: verificado contra AutoCAD real.")
    else:
        motivo = ("se pidio --no-live" if args.no_live
                  else "AutoCAD no responde")
        print("ATENCION: test_live.py NO corrio (%s)." % motivo)
        print("  Esto verifica la matematica y las reglas, NO que el dibujo "
              "salga.")
        print("  Las suites offline mockean el socket: un verde aca no dice "
              "que la herramienta funcione contra AutoCAD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
