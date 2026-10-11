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
        for name in ("sheet.py", "arch.py", "furniture.py", "annotation.py", "civil.py", "profile.py", "rules.py", "electrical.py", "sections.py", "quantities.py", "roof.py", "rebar.py", "isometric.py", "materials.py", "symbols.py", "engine.py", "instalaciones.py", "examen_edificio.py", "autocad_client.py", "detalle.py", "zapatas_dibujo.py", "zapatas_combinada.py", "zapatas_cuadros.py")
    )

    # _do_call: el lote ('batch') lo manda el cliente mismo, no una tool.
    called = set(re.findall(r'(?:acad\.call|_do_call)\(\s*"([a-z_]+)"', server_src + composed))
    handled = set(re.findall(r'case\s+"([a-z_]+)"\s*:', handlers_src))
    # Con dígitos: create_3d_model se leía como "create_" y fallaba sin motivo.
    exposed = set(re.findall(r"@mcp\.tool\(\)\s*\ndef\s+([a-z_0-9]+)", server_src))

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
    #
    # El allowlist tiene que incluir TODO modulo al que una tool delegue.
    # sym_mod./compose_mod. faltaban y sus tools pasaban de casualidad,
    # porque la ventana de 6000 chars alcanzaba el acad.call de la tool
    # SIGUIENTE: al insertar create_north entre create_level_mark y ese
    # acad.call, create_level_mark empezo a fallar sin haber cambiado.
    delegados = ("sheet_mod.", "arch_mod.", "fur_mod.", "ann_mod.",
                 "civil_mod.", "elec_mod.", "profile_mod.", "rules_mod.",
                 "sect_mod.", "qty_mod.", "roof_mod.", "rebar_mod.",
                 "iso_mod.", "sym_mod.", "compose_mod.", "geom_mod.",
                 "layers_mod.", "space_mod.", "session_mod.", "mat_mod.",
                 # engine: run_code y las plantillas que corren sobre el
                 # (describe_api, api_guide), que no tienen comando propio.
                 "engine_mod.",
                 # model3d: create_3d_model genera C# y lo corre con run_code.
                 "model3d_mod.",
                 # instalaciones: eléctrica, hidráulica, sanitaria y su simbología.
                 "inst_mod.",
                 # capítulo de zapatas: diseño y dibujo de oficio.
                 "zap_mod.", "zd_mod.", "zc_mod.", "zq_mod.", "dt_mod.",
                 # examen de edificio: revisar_proyecto (sin AutoCAD) y
                 # revisar_juego (lee el dibujo).
                 "exam_mod.",
                 # entregables: carpeta del proyecto y juego en un PDF (sin AutoCAD).
                 "ent_mod.")
    patron = "|".join(re.escape(d) for d in delegados)
    silent = sorted(t for t in exposed if not re.search(
        r"def\s+" + t + r"\b[\s\S]{0,6000}?(acad\.call|" + patron + ")",
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
