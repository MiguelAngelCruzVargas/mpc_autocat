"""La interfaz de AutoCAD IA DENTRO de AutoCAD: es la misma de `iniciar.py`, en el panel del comando MCPCHAT.

    python iniciar_en_autocad.py --registrar    una vez (lo hace tools/install_bundle.ps1): anota qué arrancar
    python iniciar_en_autocad.py                lo arranca el comando MCPCHAT si no está corriendo

Mismos modelos (Claude, Groq, OpenRouter, OpenAI, DeepSeek, local...), mismas claves guardadas, mismos perfiles de
tools, presets, costo y entregables que en el navegador. Lo único que cambia: no hay visor del plano ni chequeo de la
conexión con AutoCAD, porque el dibujo se ve en AutoCAD y el plugin es quien abre el panel.
"""
from __future__ import annotations

import json
import os
import sys

import iniciar

ESTADO = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AutoCadMcp")
LANZADOR = os.path.join(ESTADO, "chat_launcher.json")


def registrar() -> None:
    """Deja anotado qué intérprete y qué script arranca el comando MCPCHAT (lee %LOCALAPPDATA%\\AutoCadMcp)."""
    interprete = iniciar.VENV if os.path.exists(iniciar.VENV) else sys.executable
    os.makedirs(ESTADO, exist_ok=True)
    with open(LANZADOR, "w", encoding="utf-8") as fh:
        json.dump({"python": interprete, "script": os.path.abspath(__file__), "cwd": iniciar.RAIZ}, fh)
    print("Registrado en " + LANZADOR)


if __name__ == "__main__":
    if "--registrar" in sys.argv:
        registrar()
        sys.exit(0)
    if "--en-autocad" not in sys.argv:
        sys.argv.append("--en-autocad")
    sys.exit(iniciar.main())
