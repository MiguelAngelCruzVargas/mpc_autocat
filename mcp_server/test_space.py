"""Tests de space.py: la escala de la lámina sobrevive a un reinicio del
proceso. NO necesita AutoCAD.

El bug real: `create_dimension_chain(scale=0)` toma la escala de un global de
Python (`space._UNITS_PER_PAPER_MM`) que `create_sheet` deja seteado. Si el
servidor MCP se reinicia a mitad de sesión (reconectar para levantar una tool
nueva, por ejemplo), ese global se pierde en silencio y la próxima cadena de
cotas sale con el default (1:100) aunque la lámina activa sea otra escala —
sin ningún error que lo avise. Este test simula el reinicio (reimportando el
módulo, que es lo que le pasa de verdad al proceso) y verifica que la escala
persistida en disco se recupera.

Uso:  python test_space.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile

FAILED: list[str] = []


def check(name: str, got, expected, tol: float = 1e-9) -> None:
    ok = (abs(got - expected) <= tol
          if isinstance(expected, float) else got == expected)
    if not ok:
        FAILED.append(f"{name}: esperaba {expected}, obtuve {got}")
    print(("  ok  " if ok else " FALLA ") + name)


def test_scale_persiste_entre_reinicios() -> None:
    real_localappdata = os.environ.get("LOCALAPPDATA")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["LOCALAPPDATA"] = tmp
        try:
            import space
            importlib.reload(space)  # sin archivo previo -> default de fabrica
            check("sin escala persistida, arranca en el default",
                  space.units_per_paper_mm(), 0.1)

            space.set_scale(0.025)  # lo que create_sheet deja a 1:25 en metros
            check("el global del proceso actual queda actualizado",
                  space.units_per_paper_mm(), 0.025)

            # Simula el reinicio del servidor MCP: un modulo nuevo, sin
            # memoria del proceso anterior -pero con el mismo LOCALAPPDATA.
            importlib.reload(space)
            check("un proceso 'nuevo' recupera la escala persistida en disco",
                  space.units_per_paper_mm(), 0.025)

            check("paper() usa la escala recuperada, no el default",
                  space.paper(4.0), 4.0 * 0.025)
        finally:
            if real_localappdata is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = real_localappdata
            import space
            importlib.reload(space)  # deja el modulo como lo encontro


def test_escala_invalida_en_disco_cae_al_default() -> None:
    real_localappdata = os.environ.get("LOCALAPPDATA")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["LOCALAPPDATA"] = tmp
        try:
            import space
            scale_file = os.path.join(tmp, "AutoCadMcp", "scale")
            os.makedirs(os.path.dirname(scale_file), exist_ok=True)
            with open(scale_file, "w", encoding="utf-8") as fh:
                fh.write("no-es-un-numero")
            importlib.reload(space)
            check("contenido invalido no rompe el arranque, cae al default",
                  space.units_per_paper_mm(), 0.1)

            with open(scale_file, "w", encoding="utf-8") as fh:
                fh.write("-1.0")
            importlib.reload(space)
            check("una escala negativa persistida tambien cae al default",
                  space.units_per_paper_mm(), 0.1)
        finally:
            if real_localappdata is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = real_localappdata
            import space
            importlib.reload(space)


def main() -> int:
    for fn in [test_scale_persiste_entre_reinicios,
               test_escala_invalida_en_disco_cae_al_default]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: la escala de la lamina sobrevive a un reinicio del proceso.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
