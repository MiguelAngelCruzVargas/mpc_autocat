"""Chequea que los dos lados del puente hablen el mismo idioma. NO necesita AutoCAD.

El error clásico de este proyecto es agregar una tool en server.py y olvidarse
del `case` en Handlers.cs (o al revés): el plugin responde "Comando no
soportado" recién en runtime, con AutoCAD abierto. Esto lo agarra antes.

Uso:  python test_contract.py
"""
from __future__ import annotations

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "server.py")
HANDLERS = os.path.join(HERE, "..", "plugin", "AutoCadMcpPlugin", "Handlers.cs")


def main() -> int:
    server_src = io.open(SERVER, encoding="utf-8").read()
    handlers_src = io.open(HANDLERS, encoding="utf-8").read()
    # sheet.py compone tools basicas, asi que tambien invoca comandos.
    composed = "".join(
        io.open(os.path.join(HERE, name), encoding="utf-8").read()
        for name in ("sheet.py", "arch.py", "furniture.py", "annotation.py", "civil.py", "profile.py", "rules.py", "electrical.py", "sections.py", "quantities.py")
    )

    called = set(re.findall(r'acad\.call\(\s*"([a-z_]+)"', server_src + composed))
    handled = set(re.findall(r'case\s+"([a-z_]+)"\s*:', handlers_src))
    exposed = set(re.findall(r"@mcp\.tool\(\)\s*\ndef\s+([a-z_]+)", server_src))

    problems = []

    missing = sorted(called - handled)
    if missing:
        problems.append(
            "Comandos que server.py invoca pero Handlers.cs no atiende "
            "(falta el case): " + ", ".join(missing)
        )

    orphan = sorted(handled - called)
    if orphan:
        problems.append(
            "Comandos implementados en el plugin que ninguna tool expone: "
            + ", ".join(orphan)
        )

    # Toda tool MCP deberia terminar en al menos un acad.call. La ventana
    # es amplia a proposito: un docstring largo es deseable y no tiene
    # por que hacer fallar el chequeo.
    silent = sorted(t for t in exposed if not re.search(
        r"def\s+" + t + r"\b[\s\S]{0,6000}?(acad\.call|sheet_mod\.|arch_mod\.|fur_mod\.|ann_mod\.|civil_mod\.|elec_mod\.|profile_mod\.|rules_mod\.|sect_mod\.|qty_mod\.)",
        server_src))
    if silent:
        problems.append("Tools que no llaman al plugin: " + ", ".join(silent))

    for p in problems:
        print("FALLA:", p)

    if problems:
        return 1

    print(f"OK: {len(exposed)} tools MCP -> {len(called)} comandos, "
          f"todos atendidos por el plugin.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
