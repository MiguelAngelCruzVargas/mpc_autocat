"""El canal con el panel de AutoCAD (canal_panel.py): actividad en vivo y bandeja. NO necesita AutoCAD.

Uso:  python test_canal_panel.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from typing import Any

FALLAS: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(("  ok    " if cond else "  FALLA ") + msg)
    if not cond:
        FALLAS.append(msg)


ESTADO = tempfile.mkdtemp(prefix="canal_panel_")
os.environ["AUTOCAD_IA_ESTADO"] = ESTADO
os.environ.pop("AUTOCAD_IA_SIN_CANAL", None)

import canal_panel as cp  # noqa: E402


def test_actividad() -> None:
    ev, pos = cp.leer_actividad(0)
    ok(ev == [] and pos == 0, "sin archivo no hay nada y no falla")
    cp.registrar({"t": "inicio", "id": "a", "tool": "create_line"})
    cp.registrar({"t": "fin", "id": "a", "tool": "create_line", "ok": True, "ms": 12})
    ev, pos = cp.leer_actividad(0)
    ok([e["t"] for e in ev] == ["inicio", "fin"] and all("ts" in e and "pid" in e for e in ev), "lee lo registrado, con hora y proceso")
    cp.registrar({"t": "inicio", "id": "b", "tool": "x"})
    ev2, pos2 = cp.leer_actividad(pos)
    ok(len(ev2) == 1 and ev2[0]["id"] == "b" and pos2 > pos, "desde la posición anterior llega solo lo nuevo")
    ev3, pos3 = cp.leer_actividad(pos2)
    ok(ev3 == [] and pos3 == pos2, "sin novedades no devuelve nada")
    # una línea a medio escribir no se lee hasta que se completa
    with open(os.path.join(ESTADO, "actividad.jsonl"), "ab") as fh:
        fh.write(b'{"t": "inicio", "id": "c"')
    ev4, pos4 = cp.leer_actividad(pos2)
    ok(ev4 == [] and pos4 == pos2, "una línea sin terminar espera")
    with open(os.path.join(ESTADO, "actividad.jsonl"), "ab") as fh:
        fh.write(b', "tool": "y"}\n')
    ev5, _ = cp.leer_actividad(pos2)
    ok(len(ev5) == 1 and ev5[0]["id"] == "c", "y se lee entera cuando termina")
    ev6, pos6 = cp.leer_actividad(10_000_000)
    ok(len(ev6) >= 4 and pos6 > 0, "si el archivo quedó más corto que la posición, vuelve a leerlo desde el inicio")
    # el recorte de un archivo enorme
    cp.MAX_ARCHIVO, viejo = 2000, cp.MAX_ARCHIVO
    for i in range(80):
        cp.registrar({"t": "inicio", "id": f"r{i}", "tool": "t" * 20})
    cp.MAX_ARCHIVO = viejo
    ev7, _ = cp.leer_actividad(0)
    ok(0 < len(ev7) < 300 and ev7[-1]["id"] == "r79", "el archivo se recorta conservando lo último")
    # una línea gigante no rompe la lectura
    cp.registrar({"t": "fin", "id": "g", "texto": "x" * 20000})
    ev8, _ = cp.leer_actividad(0)
    ok(ev8[-1]["id"] == "g" and len(json.dumps(ev8[-1])) < 4000, "una línea enorme se acorta y las demás siguen legibles")


def test_resumen_de_argumentos() -> None:
    r = cp._resumir_args("run_code", {"code": "Console.WriteLine(1); " * 50, "password": "secreta"})
    ok("secreta" not in json.dumps(r) and "Console" not in json.dumps(r) and "caracteres" in json.dumps(r, ensure_ascii=False),
       "de run_code se guarda el tamaño del código, no el código ni lo demás")
    r = cp._resumir_args("create_line", {"x1": 0, "layer": "M" * 500, "pts": [[0, 0]] * 100})
    ok(len(json.dumps(r)) <= 700 and r.get("x1") == 0, "los argumentos largos se acortan")
    ok(cp._resumir_args("t", {}) == {} and cp._resumir_args("t", None) == {}, "sin argumentos no falla")


def test_bandeja() -> None:
    ok(cp.hay_pendientes() == 0 and cp.mensajes_pendientes() == [], "bandeja vacía")
    try:
        cp.enviar("usuario", "   ")
        ok(False, "un mensaje vacío se rechaza")
    except ValueError:
        ok(True, "un mensaje vacío se rechaza")
    try:
        cp.enviar("otro", "hola")
        ok(False, "solo 'usuario' o 'claude'")
    except ValueError:
        ok(True, "solo 'usuario' o 'claude'")
    cp.enviar("usuario", "revisa la cota del eje B")
    cp.enviar("claude", "Voy a revisarla.", "info")
    cp.enviar("usuario", "y el muro norte")
    ok(cp.hay_pendientes() == 2, "cuenta solo lo que escribió la persona")
    ok(cp.hay_pendientes() == 2, "mirar no los marca como leídos")
    p = cp.mensajes_pendientes(marcar=False)
    ok([m["texto"] for m in p] == ["revisa la cota del eje B", "y el muro norte"] and cp.hay_pendientes() == 2, "leer sin marcar los deja pendientes")
    p = cp.mensajes_pendientes()
    ok(len(p) == 2 and cp.hay_pendientes() == 0 and cp.mensajes_pendientes() == [], "al leerlos se marcan y no se entregan dos veces")
    cp.enviar("usuario", "uno más")
    ok([m["texto"] for m in cp.mensajes_pendientes()] == ["uno más"], "lo que llega después sí se entrega")
    todo, _ = cp.leer_bandeja(0)
    ok([m["de"] for m in todo] == ["usuario", "claude", "usuario", "usuario"], "el panel ve los mensajes en los dos sentidos, en orden")
    # el archivo se recortó y el cursor quedó más allá: no reentrega lo viejo ni se queda sordo
    with open(os.path.join(ESTADO, "bandeja.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": "z", "ts": 1, "de": "usuario", "tipo": "info", "texto": "viejo"}) + "\n")
    ok(cp.hay_pendientes() == 0, "tras un recorte no reentrega mensajes viejos")
    cp.enviar("usuario", "nuevo tras el recorte")
    ok([m["texto"] for m in cp.mensajes_pendientes()] == ["nuevo tras el recorte"], "y lo nuevo se entrega")


def _servidor_de_prueba():
    from mcp.server.fastmcp import FastMCP
    s = FastMCP("prueba")

    @s.tool()
    def suma(a: int, b: int) -> dict[str, Any]:
        """suma"""
        return {"total": a + b}

    @s.tool()
    def explota() -> dict[str, Any]:
        """falla"""
        raise RuntimeError("boom de prueba")

    @s.tool()
    def panel_decir(texto: str) -> dict[str, Any]:
        """simula la tool del canal"""
        return {"ok": True}

    @s.tool()
    def run_code(code: str) -> dict[str, Any]:
        """simula run_code"""
        return {"ok": True}
    return s


def test_envoltorio() -> None:
    # limpio el estado para mirar solo esta prueba
    for f in ("actividad.jsonl", "bandeja.jsonl", "bandeja_leida.txt"):
        try:
            os.remove(os.path.join(ESTADO, f))
        except OSError:
            pass
    s = _servidor_de_prueba()
    antes = asyncio.run(s.call_tool("suma", {"a": 1, "b": 2}))
    ok(not os.path.exists(os.path.join(ESTADO, "actividad.jsonl")), "sin instalar el envoltorio no se registra nada")
    cp.instalar(s)
    cp.instalar(s)                                   # dos veces: no se envuelve dos veces
    r = asyncio.run(s.call_tool("suma", {"a": 1, "b": 2}))
    ok(r[1] == antes[1] == {"total": 3} and [b.text for b in r[0]] == [b.text for b in antes[0]], "el resultado de la tool queda idéntico")
    ev, _ = cp.leer_actividad(0)
    ok([e["t"] for e in ev] == ["inicio", "fin"] and ev[0]["tool"] == "suma" and ev[0]["args"] == {"a": 1, "b": 2}
       and ev[1]["ok"] is True and ev[0]["id"] == ev[1]["id"] and ev[1]["ms"] >= 0 and "3" in ev[1]["texto"],
       "una llamada deja su inicio y su fin ligados, con argumentos, duración y un resumen")
    try:
        asyncio.run(s.call_tool("explota", {}))
        ok(False, "el error de la tool sigue llegando")
    except Exception as e:                           # noqa: BLE001
        ok("boom de prueba" in str(e), "el error de la tool sigue llegando igual")
    ev, _ = cp.leer_actividad(0)
    ok(ev[-1]["t"] == "fin" and ev[-1]["ok"] is False and "boom" in ev[-1]["texto"], "y queda registrado como fallido")
    asyncio.run(s.call_tool("run_code", {"code": "SECRETO_DEL_CODIGO()"}))
    crudo = open(os.path.join(ESTADO, "actividad.jsonl"), encoding="utf-8").read()
    ok("SECRETO_DEL_CODIGO" not in crudo, "el código de run_code no se guarda")

    # con un mensaje pendiente, las tools lo avisan y las del canal no
    cp.enviar("usuario", "cuando puedas revisa el eje B")
    r = asyncio.run(s.call_tool("suma", {"a": 2, "b": 2}))
    textos = [b.text for b in r[0]]
    ok(r[1] == {"total": 4} and len(textos) == 2 and "panel_leer_mensajes" in textos[1] and "1 mensaje" in textos[1],
       "con un mensaje sin leer, el resultado trae un aviso extra y el resultado estructurado no cambia")
    r = asyncio.run(s.call_tool("panel_decir", {"texto": "x"}))
    ok(len(r[0]) == 1, "las tools del canal no llevan el aviso (ya son el canal)")
    cp.mensajes_pendientes()
    r = asyncio.run(s.call_tool("suma", {"a": 2, "b": 2}))
    ok(len(r[0]) == 1, "leídos los mensajes el aviso desaparece")

    # que registrar falle (carpeta imposible) no puede tumbar la tool
    os.environ["AUTOCAD_IA_ESTADO"] = os.path.join(ESTADO, "actividad.jsonl", "no_es_carpeta")
    r = asyncio.run(s.call_tool("suma", {"a": 5, "b": 5}))
    ok(r[1] == {"total": 10}, "si no se puede escribir el registro, la tool funciona igual")
    os.environ["AUTOCAD_IA_ESTADO"] = ESTADO

    # el interruptor
    os.environ["AUTOCAD_IA_SIN_CANAL"] = "1"
    s2 = _servidor_de_prueba()
    cp.instalar(s2)
    n0 = len(cp.leer_actividad(0)[0])
    asyncio.run(s2.call_tool("suma", {"a": 1, "b": 1}))
    ok(len(cp.leer_actividad(0)[0]) == n0, "AUTOCAD_IA_SIN_CANAL=1 apaga el registro")
    os.environ.pop("AUTOCAD_IA_SIN_CANAL")


def test_el_servidor_real() -> None:
    import server
    nombres = [t.name for t in asyncio.run(server.mcp.list_tools())]
    ok("panel_decir" in nombres and "panel_leer_mensajes" in nombres, "el servidor MCP del proyecto expone las dos tools del canal")
    for f in ("actividad.jsonl", "bandeja.jsonl", "bandeja_leida.txt"):
        try:
            os.remove(os.path.join(ESTADO, f))
        except OSError:
            pass
    r = asyncio.run(server.mcp.call_tool("panel_decir", {"texto": "Listo, revisé la planta.", "tipo": "listo"}))
    ok(r[1]["ok"] is True, "panel_decir escribe en la bandeja")
    msgs, _ = cp.leer_bandeja(0)
    ok(msgs and msgs[0]["de"] == "claude" and msgs[0]["tipo"] == "listo" and msgs[0]["texto"].startswith("Listo"), "queda como mensaje de claude, con su tipo")
    try:
        asyncio.run(server.mcp.call_tool("panel_decir", {"texto": "x", "tipo": "grito"}))
        ok(False, "un tipo inválido se rechaza")
    except Exception:                                # noqa: BLE001
        ok(True, "un tipo inválido se rechaza")
    r = asyncio.run(server.mcp.call_tool("panel_leer_mensajes", {}))
    ok(r[1]["count"] == 0 and "No hay" in r[1]["nota"], "sin mensajes de la persona dice que no hay")
    cp.enviar("usuario", "pon la escala en 1:50")
    r = asyncio.run(server.mcp.call_tool("get_normative", {}))
    ok(any("panel_leer_mensajes" in b.text for b in r[0]), "una tool real del proyecto trae el aviso del mensaje pendiente")
    r = asyncio.run(server.mcp.call_tool("panel_leer_mensajes", {}))
    ok(r[1]["count"] == 1 and r[1]["mensajes"][0]["texto"] == "pon la escala en 1:50", "panel_leer_mensajes entrega el mensaje de la persona")
    ev, _ = cp.leer_actividad(0)
    ok({"panel_decir", "panel_leer_mensajes", "get_normative"} <= {e["tool"] for e in ev if e["t"] == "inicio"}, "toda llamada del servidor real queda en la actividad")


if __name__ == "__main__":
    test_actividad()
    test_resumen_de_argumentos()
    test_bandeja()
    test_envoltorio()
    test_el_servidor_real()
    if FALLAS:
        print(f"\n{len(FALLAS)} fallas")
        sys.exit(1)
    print("\nOK")
