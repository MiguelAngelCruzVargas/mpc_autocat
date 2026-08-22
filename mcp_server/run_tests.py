"""Corre toda la bateria de tests de una sola vez.

Existe porque los tests son scripts sueltos (`python test_arch.py`), no una
suite de pytest: son 24 archivos y correrlos a mano uno por uno significa,
en la practica, que nadie los corre todos. El que se saltea es siempre el
mismo que se rompio.

Cada test corre en su PROPIO proceso, a proposito: varios modulos guardan
estado de proceso (`space.OCCUPIED`, `layers._EXISTING`, la escala
persistida) y un import compartido haria que el resultado de un test
dependiera de cual corrio antes.

    python run_tests.py           # los que NO necesitan AutoCAD
    python run_tests.py --live    # ademas test_live.py, contra AutoCAD abierto
    python run_tests.py -k rebar  # solo los que matcheen

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

AQUI = os.path.dirname(os.path.abspath(__file__))


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
    ap.add_argument("--live", action="store_true",
                    help="incluir los que necesitan AutoCAD abierto")
    ap.add_argument("-k", dest="patron", default=None,
                    help="correr solo los tests cuyo nombre contenga esto")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="mostrar la salida completa de cada test")
    args = ap.parse_args()

    archivos = descubrir(args.patron, args.live)
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
    if not args.live:
        print("(test_live.py no corrio: necesita AutoCAD abierto. "
              "Agregar --live para incluirlo.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
