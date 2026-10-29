"""Copia las especialidades (perfiles) de agent/cli.py a plugin/AutoCadMcpPlugin/Chat/perfiles.json, que el plugin lleva
incrustado: el panel nativo (C#) decide qué herramientas ve cada especialidad con esos mismos patrones.

La fuente sigue siendo agent/cli.py (PERFILES, con sus comentarios); este archivo es una copia generada. Si se cambia un
perfil, hay que volver a correr esto:

    python tools/generar_perfiles.py              reescribe perfiles.json
    python tools/generar_perfiles.py --verificar  sale con 1 si perfiles.json no coincide (lo corre agent/test_host.py)
"""
from __future__ import annotations

import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO = os.path.join(RAIZ, "plugin", "AutoCadMcpPlugin", "Chat", "perfiles.json")


def generar() -> str:
    sys.path.insert(0, RAIZ)
    from agent.cli import PERFILES
    datos = [{"id": nombre, "patrones": list(patrones or [])} for nombre, patrones in PERFILES.items()]
    return json.dumps(datos, indent=1, ensure_ascii=False) + "\n"


def coincide() -> bool:
    try:
        with open(DESTINO, encoding="utf-8") as fh:
            return json.loads(fh.read()) == json.loads(generar())
    except (OSError, ValueError):
        return False


if __name__ == "__main__":
    if "--verificar" in sys.argv:
        ok = coincide()
        print("perfiles.json coincide con agent/cli.py" if ok else "perfiles.json NO coincide: corre python tools/generar_perfiles.py")
        sys.exit(0 if ok else 1)
    with open(DESTINO, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(generar())
    print("escrito", DESTINO)
