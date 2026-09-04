"""Interfaz de consola para dibujar en AutoCAD con el modelo que quieras.

    python -m agent.cli --proveedor openrouter --modelo anthropic/claude-3.5-sonnet
    python -m agent.cli --proveedor local --modelo qwen2.5-coder-32b
    python -m agent.cli --proveedor deepseek -p "dibujá una casa de 3 recámaras en 8x16"

Sin --prompt entra en modo conversación: se le va pidiendo cosas y el
agente dibuja, igual que en Claude Code pero con el modelo que elijas.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys

from .loop import conversar
from .mcp_link import ConexionMcp, SERVIDOR_DEFECTO
from . import credenciales, providers

# Perfiles de tools. Con las 128 tools del servidor, las definiciones solas
# son miles de tokens EN CADA VUELTA: en un modelo de ventana corta no
# entran, y en uno caro se paga en cada llamada. Estos grupos son los que
# de verdad se usan juntos.
PERFILES: dict[str, list[str]] = {
    "arquitectura": [
        "suggest_layout", "draw_layout", "dimension_layout",
        "suggest_furniture", "place_furniture", "label_rooms",
        "create_walls", "create_axis_grid", "create_sheet", "create_stairs",
        "create_building_section", "create_gable_roof",
        "check_", "create_text", "create_mtext", "create_dimension",
        "place_labels", "create_north", "create_view_title",
        "create_level_mark", "create_section_mark", "set_layer",
        "save_drawing", "zoom_", "capture_viewport", "get_extents",
        "new_document", "open_document", "list_documents",
        # Sin esto el perfil deja DIAGNOSTICAR pero no CORREGIR: check_all
        # avisa "16 grupos de entidades duplicadas" y el agente no tiene con
        # qué borrarlas. Pasó de verdad, y encima Groq rechazó el request
        # entero por pedir una tool que no estaba en la lista.
        "delete_entity", "delete_entities", "undo",
        "list_entities", "get_entity", "select_entities", "ping",
        "list_layers",
        # Instalación eléctrica: vive en su propio módulo (electrical.py)
        # pero no tiene perfil propio, y "Arquitectura" es donde tiene
        # sentido dibujarla (necesita los muros ya puestos). Sin esto el
        # preset "Instalación Eléctrica" de la interfaz pedía una tool que
        # ningún perfil ofrecía, en ninguno de los cuatro.
        "place_devices", "create_conduit",
    ],
    "civil": [
        "create_alignment", "create_road", "create_stationing",
        "create_profile", "create_cross_sections", "create_intersection",
        "point_on_road", "grade_elevation", "create_coordinate_grid",
        "create_construction_table", "create_layer_section",
        "create_flow_arrow", "create_sheet", "check_", "set_layer",
        "save_drawing", "zoom_", "capture_viewport", "get_extents",
        "new_document", "open_document", "ping", "list_layers",
    ],
    "estructura": [
        "check_footing", "check_column", "check_slab_span",
        "check_retaining_wall", "check_roof_truss", "check_bridge_girder",
        "create_column_section", "create_rebar_elevation",
        "create_footing_plan", "create_truss", "calculate_quantities",
        "create_quantities_table", "export_quantities_csv",
        "create_sheet", "set_layer", "save_drawing", "zoom_",
        "capture_viewport", "get_extents", "new_document", "open_document",
        "ping", "list_layers",
    ],
    "basico": [
        "create_line", "create_polyline", "create_circle", "create_arc",
        "create_text", "create_dimension", "create_hatch", "set_layer",
        "get_drawing_info", "list_entities", "delete_entity", "zoom_",
        "capture_viewport", "save_drawing", "new_document", "ping",
        "list_layers",
    ],
    "todo": [],
}

SYSTEM_BASE = """Eres un asistente que dibuja planos en AutoCAD a través de \
herramientas MCP. Trabajas sobre el dibujo abierto de una persona real: \
cada llamada modifica su archivo.

Hablas en español mexicano. Regla dura, no de estilo: en TODA respuesta \
usa al menos un modismo mexicano (órale, va, sale, ándale, no hay bronca, \
échale ganas, qué onda, nel, chido) — no es opcional, revísalo antes de \
mandar la respuesta. Pero sin exagerarle ni sonar payaso: sigues siendo un \
asistente técnico serio, nomás que mexicano.

Tu chamba es AutoCAD y el dibujo técnico, y nada más: distribuciones, \
cotas, cimentaciones, instalaciones, capas, entidades del dibujo actual, y \
también un saludo o una pregunta de qué puedes hacer — eso SÍ es tu tema, \
contéstalo normal. Lo que rechazas es lo que de plano no tiene nada que \
ver con dibujar (chisme, tarea de otra materia, opiniones de política, \
recetas, lo que sea): ahí no le entres, contesta en una línea que ese tema \
no es lo tuyo y regresa la plática al plano que está abierto. No eres un \
asistente de propósito general, pero tampoco seas cortante con quien \
recién te está saludando o preguntando qué sabes hacer.

Reglas de trabajo:
- Antes de dibujar algo grande, di en una línea qué vas a hacer.
- Las herramientas devuelven 'warning' y 'problems': LÉELOS. Están \
escritos para que corrijas, no para ignorarlos.
- Si una herramienta falla, el mensaje dice qué pasó y cómo arreglarlo. \
Corrige y sigue; no repitas la misma llamada igual.
- Guarda seguido con save_drawing: AutoCAD se puede caer y llevarse lo no \
guardado.
- Al terminar, mira lo que dibujaste con capture_viewport antes de decir \
que está listo."""


def _system_prompt(con_reglas: bool, limite: int) -> str:
    """El prompt de sistema, con las reglas de dibujo del repo si se piden.

    CLAUDE.md es la memoria de oficio de este proyecto: por qué un muro no
    es una línea, dónde va el cajón, qué colores no imprimen. Un modelo que
    no lo lee dibuja como dibujaba este MCP antes de que existiera. Pero son
    ~44 KB, así que se puede recortar o apagar para un modelo chico.
    """
    if not con_reglas:
        return SYSTEM_BASE
    ruta = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "CLAUDE.md")
    try:
        with open(ruta, encoding="utf-8") as fh:
            reglas = fh.read()
    except OSError:
        return SYSTEM_BASE
    if limite > 0:
        reglas = reglas[:limite]
    return (SYSTEM_BASE + "\n\n--- Reglas de dibujo de este proyecto ---\n"
            + reglas)


def _mostrar(tipo: str, datos: dict) -> None:
    if tipo == "texto":
        print(f"\n{datos['texto']}\n")
    elif tipo == "tool":
        args = json.dumps(datos["args"], ensure_ascii=False)
        if len(args) > 160:
            args = args[:157] + "..."
        print(f"  → {datos['nombre']}({args})")
    elif tipo == "resultado":
        texto = datos["texto"].replace("\n", " ")
        if len(texto) > 200:
            texto = texto[:197] + "..."
        marca = "  ✗" if datos["error"] else "  ✓"
        print(f"{marca} {texto}")
    elif tipo == "aviso":
        print(f"\n[!] {datos['texto']}\n")


async def _correr(args: argparse.Namespace) -> int:
    try:
        proveedor = providers.construir(
            args.proveedor, modelo=args.modelo, url=args.url,
            api_key=args.api_key, temperatura=args.temperatura)
    except providers.ErrorProveedor as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    incluir = PERFILES.get(args.perfil)
    if incluir is None:
        print(f"ERROR: perfil '{args.perfil}' desconocido. "
              f"Hay: {', '.join(PERFILES)}", file=sys.stderr)
        return 2

    async with ConexionMcp(servidor=args.servidor, python=args.python) as mcp:
        tools = mcp.catalogo(incluir=incluir or None,
                             limite_descripcion=args.limite_descripcion)
        print(f"Servidor MCP: {len(mcp.tools)} tools disponibles, "
              f"{len(tools)} en el perfil '{args.perfil}'.")
        print(f"Modelo: {proveedor.modelo} ({args.proveedor})\n")

        mensajes: list[dict] = [{
            "role": "system",
            "content": _system_prompt(not args.sin_reglas, args.limite_reglas),
        }]

        if args.prompt:
            mensajes.append({"role": "user", "content": args.prompt})
            await conversar(mcp, proveedor, mensajes, tools, _mostrar,
                            vueltas_max=args.vueltas)
            return 0

        print("Escribí lo que querés dibujar. 'salir' para terminar.\n")
        while True:
            try:
                pedido = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if pedido.lower() in ("salir", "exit", "quit"):
                return 0
            if not pedido:
                continue
            mensajes.append({"role": "user", "content": pedido})
            await conversar(mcp, proveedor, mensajes, tools, _mostrar,
                            vueltas_max=args.vueltas)


def _config(argv: list[str]) -> int:
    """Subcomando `config`: guardar, listar y borrar claves."""
    uso = ("uso: python -m agent.cli config set <proveedor> [clave]\n"
           "     python -m agent.cli config list\n"
           "     python -m agent.cli config del <proveedor>\n\n"
           "Proveedores: " + ", ".join(sorted(providers.PRESETS)))
    if not argv:
        print(uso)
        return 2
    accion = argv[0]

    if accion == "list":
        filas = credenciales.listar()
        if not filas:
            print("No hay ninguna clave guardada.")
            print(f"Archivo: {credenciales.ARCHIVO}")
            return 0
        print(f"{'PROVEEDOR':<14} {'CLAVE':<18} PROTECCION")
        for f in filas:
            proteccion = ("cifrada con DPAPI (solo esta cuenta de Windows)"
                          if f["proteccion"] == "dpapi"
                          else "texto plano, permisos restringidos")
            print(f"{f['proveedor']:<14} {f['clave']:<18} {proteccion}")
        print(f"\nArchivo: {credenciales.ARCHIVO}")
        return 0

    if accion in ("set", "del") and len(argv) < 2:
        print(uso)
        return 2

    if accion == "del":
        proveedor = argv[1]
        if credenciales.borrar(proveedor):
            print(f"Clave de '{proveedor}' borrada.")
            return 0
        print(f"No había ninguna clave guardada para '{proveedor}'.")
        return 1

    if accion == "set":
        proveedor = argv[1]
        if proveedor not in providers.PRESETS:
            print(f"AVISO: '{proveedor}' no es un proveedor conocido "
                  f"({', '.join(sorted(providers.PRESETS))}). Se guarda igual.")
        # Sin la clave en la línea de comandos queda fuera del historial
        # del shell, que es donde más se filtran.
        clave = argv[2] if len(argv) > 2 else getpass.getpass(
            f"Clave de {proveedor} (no se muestra): ")
        try:
            modo = credenciales.guardar(proveedor, clave)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 2
        detalle = ("cifrada con DPAPI: solo esta cuenta de Windows puede "
                   "leerla" if modo == "dpapi" else
                   "texto plano con permisos 0600 (DPAPI no disponible acá)")
        print(f"Guardada la clave de '{proveedor}' — {detalle}.")
        print(f"Archivo: {credenciales.ARCHIVO}")
        if len(argv) > 2:
            print("OJO: la pasaste en la línea de comandos, así que quedó en "
                  "el historial del shell. Considerá limpiarlo o rotarla.")
        return 0

    print(uso)
    return 2


def _modelos(argv: list[str]) -> int:
    """Subcomando `modelos`: qué ofrece el proveedor y qué funciona."""
    p = argparse.ArgumentParser(prog="agent.cli modelos")
    p.add_argument("--proveedor", default="openrouter")
    p.add_argument("--api-key", default=None)
    p.add_argument("--url", default=None)
    p.add_argument("--probar", action="store_true",
                   help="Ademas de listar, le manda un 'hola' de 5 tokens a "
                        "cada uno para ver cual responde y cual acepta tools. "
                        "Cuesta centavos y evita descubrir un bloqueo a mitad "
                        "de un plano.")
    a = p.parse_args(argv)

    try:
        filas = providers.modelos_disponibles(
            a.proveedor, api_key=a.api_key, url=a.url, probar=a.probar)
    except providers.ErrorProveedor as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not filas:
        print("El proveedor no devolvió ningún modelo.")
        return 1
    ancho = max(len(f["modelo"]) for f in filas) + 2
    print(f"{'MODELO':<{ancho}} ESTADO")
    for f in sorted(filas, key=lambda x: x["modelo"]):
        print(f"{f['modelo']:<{ancho}} {f['estado']}")
    if not a.probar:
        print("\nEstar en la lista no quiere decir que se pueda usar: "
              "agregá --probar para verificarlo de verdad.")
    else:
        usables = [f for f in filas if f["estado"].startswith("OK")]
        print(f"\n{len(usables)} modelo(s) usables para dibujar.")
        if not usables:
            print("Ninguno acepta tools con esta clave. Si dice 'bloqueado "
                  "por la organizacion', habilitalos en la consola del "
                  "proveedor (en Groq: console.groq.com/settings/limits).")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "config":
        return _config(argv[1:])
    if argv and argv[0] == "modelos":
        return _modelos(argv[1:])

    p = argparse.ArgumentParser(
        prog="agent.cli",
        description="Dibujá en AutoCAD con el modelo de IA que elijas.",
        epilog="Claves: 'config set <proveedor>' las guarda cifradas; "
               "'config list' muestra qué hay (enmascarado); "
               "'config del <proveedor>' borra.")
    p.add_argument("--proveedor", default="openrouter",
                   help="openrouter, openai, groq, deepseek, together, "
                        "anthropic, local (default: openrouter)")
    p.add_argument("--modelo", default=None,
                   help="Nombre del modelo. Sin esto, el default del proveedor.")
    p.add_argument("--url", default=None,
                   help="Endpoint compatible con OpenAI, para uno no listado.")
    p.add_argument("--api-key", default=None,
                   help="Clave suelta. Mejor guardarla con 'config set': en "
                        "la línea de comandos queda en el historial del shell.")
    p.add_argument("--perfil", default="arquitectura",
                   help="Qué tools ofrecer: " + ", ".join(PERFILES)
                        + " (default: arquitectura)")
    p.add_argument("-p", "--prompt", default=None,
                   help="Una sola instrucción y salir (sin esto, conversación).")
    p.add_argument("--vueltas", type=int, default=40,
                   help="Tope de vueltas del bucle (default: 40).")
    p.add_argument("--temperatura", type=float, default=None)
    p.add_argument("--sin-reglas", action="store_true",
                   help="No mandar CLAUDE.md como system prompt (ahorra "
                        "tokens, pero el modelo dibuja peor).")
    p.add_argument("--limite-reglas", type=int, default=0,
                   help="Recortar CLAUDE.md a N caracteres (0 = completo).")
    p.add_argument("--limite-descripcion", type=int, default=0,
                   help="Recortar la descripción de cada tool a N caracteres "
                        "(0 = completa). Útil en modelos de ventana corta.")
    p.add_argument("--servidor", default=SERVIDOR_DEFECTO,
                   help="Ruta a server.py del MCP.")
    p.add_argument("--python", default=None,
                   help="Intérprete con el que lanzar el servidor.")
    args = p.parse_args(argv)

    try:
        return asyncio.run(_correr(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
