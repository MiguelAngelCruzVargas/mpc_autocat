"""Qué herramientas piden permiso antes de correr y cuáles no tocan el dibujo (para la marca de deshacer).

El agente nativo (C#) usa estas dos listas; viven aquí para que haya UNA sola fuente y para probarlas sin AutoCAD
(`agent/test_host.py`). Se mandan en /api/h/preparar.

DESTRUCTIVAS: lo que borra, purga, cierra, deshace o ejecuta comandos libres. La persona debe aprobarlo cada vez (o
decir «permitir esta herramienta siempre en esta conversación»). Dibujar, acotar, rotular y calcular NO piden permiso:
un chat que pregunta antes de cada línea no sirve, y todo eso se revierte con «Deshacer este pedido».

SOLO_LECTURA: lo que no cambia el dibujo. Antes de la primera herramienta que NO sea de estas, el agente pone una marca de
UNDO; «Deshacer este pedido» vuelve a esa marca y revierte todo lo que hizo el pedido, sin contar pasos.
"""
from __future__ import annotations

import re

DESTRUCTIVAS = re.compile(
    r"^(delete_|purge_|remove_|clear_|detach_|unload_|close_document$|undo$|merge_layers$|overkill_entities$|"
    r"run_command$|set_system_variable$|explode_entities$)")

SOLO_LECTURA = re.compile(
    r"^(get_|list_|check_|query_|describe_|aggregate_|calculate_|measure_|capture_|zoom_|find_|select_entities$|"
    r"export_|buscar_|describir_|native_status$|ping$|api_guide$|diagnose_|panel_leer_|point_on_road$|sheet_origin$|"
    r"save_drawing$|read_pdf$|consultar_norma$)")


def pide_permiso(nombre: str) -> bool:
    return bool(DESTRUCTIVAS.match(nombre))


def toca_el_dibujo(nombre: str) -> bool:
    return not SOLO_LECTURA.match(nombre)
