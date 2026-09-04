"""Arranca la interfaz de AutoCAD IA.

    python iniciar.py

Levanta el servidor local y abre el navegador. Desde ahí se configura el
proveedor, se guarda la API key (cifrada) y se le pide al agente que dibuje.

Usa el intérprete del entorno virtual del proyecto si existe, así no hay
que activarlo a mano ni acordarse de dónde está.
"""
from __future__ import annotations

import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
_VENV_BIN = os.path.join(RAIZ, "mcp_server", ".venv",
                         "Scripts" if os.name == "nt" else "bin")
VENV = os.path.join(_VENV_BIN, "python.exe" if os.name == "nt" else "python")
if not os.path.exists(VENV):
    VENV = os.path.join(RAIZ, "mcp_server", ".venv", "bin", "python")
    _VENV_BIN = os.path.dirname(VENV)


def _ya_en_venv() -> bool:
    """True si el intérprete que está corriendo YA vive en la carpeta del
    venv del proyecto — no importa si es python.exe o pythonw.exe (los dos
    son válidos, la única diferencia es si abren consola). Comparar contra
    solo python.exe rompía al lanzar con pythonw.exe (la interfaz sin
    consola, ver AutoCAD-IA.vbs): se detectaba como "intérprete distinto" y
    se relanzaba con el Python del sistema — y ESE, al no tener el mismo
    chequeo, volvía a relanzarse otra vez, dejando hasta 4 procesos vivos
    para un solo arranque.
    """
    try:
        return os.path.commonpath(
            [os.path.abspath(sys.executable), _VENV_BIN]) == _VENV_BIN
    except ValueError:      # unidades de disco distintas en Windows
        return False


def _dependencias_ok(interprete: str) -> bool:
    try:
        r = subprocess.run([interprete, "-c", "import mcp, httpx"],
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main() -> int:
    puerto = 8770
    for i, a in enumerate(sys.argv):
        if a in ("--puerto", "-p") and i + 1 < len(sys.argv):
            puerto = int(sys.argv[i + 1])

    # El venv del proyecto ya tiene mcp y httpx; el Python del sistema
    # casi nunca. Elegirlo solo evita el "ModuleNotFoundError: mcp" que
    # es el primer tropiezo de cualquiera que clona esto.
    interprete = VENV if os.path.exists(VENV) else sys.executable
    if not _dependencias_ok(interprete):
        otro = sys.executable if os.path.abspath(interprete) == os.path.abspath(VENV) else VENV
        if os.path.exists(otro) and _dependencias_ok(otro):
            interprete = otro
        else:
            print("Faltan dependencias (mcp, httpx). Instalalas con:\n"
                  f"    {interprete} -m pip install mcp httpx\n")
            return 2

    if not _ya_en_venv():
        # Relanzarse con el intérprete correcto en vez de fallar.
        return subprocess.call([interprete, os.path.abspath(__file__),
                                "--puerto", str(puerto)])

    sys.path.insert(0, RAIZ)
    from agent.web import iniciar
    iniciar(puerto=puerto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
