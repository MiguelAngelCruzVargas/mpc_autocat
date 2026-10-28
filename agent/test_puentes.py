"""Pruebas del puente a Claude Code (agent/puentes.py) sin Claude Code, sin sesión y sin AutoCAD.

Un CLI de mentira (un script de Python envuelto en un .cmd/.sh) emite el formato stream-json que SÍ se vio en la
salida real de Claude Code 2.1.310 (`system/init`, `assistant`, `result`) y, para las herramientas, el de los eventos
`user`/`tool_result` del SDK (ese no se pudo ver: ver el docstring de puentes.py).

Uso:  python -m agent.test_puentes
"""
from __future__ import annotations

import http.client
import json
import os
import stat
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

from . import puentes

FALLAS: list[str] = []


def check(nombre: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FALLAS.append(f"{nombre}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + nombre + (f" -- {detalle}" if not ok else ""))


STUB = r'''
import json, os, sys, time
prompt = sys.stdin.buffer.read().decode("utf-8")
reglas = ""
if "--append-system-prompt-file" in sys.argv:
    reglas = open(sys.argv[sys.argv.index("--append-system-prompt-file") + 1], encoding="utf-8").read()
cfg = ""
if "--mcp-config" in sys.argv:
    cfg = open(sys.argv[sys.argv.index("--mcp-config") + 1], encoding="utf-8").read()
open(os.environ["STUB_REGISTRO"], "w", encoding="utf-8").write(json.dumps(
    {"argv": sys.argv[1:], "prompt": prompt, "reglas": reglas, "mcp": cfg,
     "env": sorted(k for k in os.environ if k.startswith(("CLAUDE", "ANTHROPIC")))}))


def emit(d):
    print(json.dumps(d), flush=True)


sid = "sesion-123"
emit({"type": "system", "subtype": "hook_started", "hook_id": "x"})
print("esto no es JSON: un aviso del CLI", flush=True)
emit({"type": "system", "subtype": "init", "session_id": sid, "model": "claude-sonnet-5-5",
      "tools": ["mcp__autocad__create_line", "mcp__autocad__get_entity", "Read"],
      "mcp_servers": [{"name": "autocad", "status": "connected"}]})
if "colgar" in prompt:
    time.sleep(60)
if "org" in prompt:
    msg = "Your organization has disabled Claude subscription access for Claude Code. Use an Anthropic API key instead"
    emit({"type": "assistant", "session_id": sid, "is_api_error_message": True,
          "message": {"content": [{"type": "text", "text": msg}], "usage": {"output_tokens": 0}}})
    emit({"type": "result", "subtype": "success", "is_error": True, "result": msg, "session_id": sid,
          "num_turns": 1, "usage": {"input_tokens": 0, "output_tokens": 0}})
    sys.exit(1)
if "salir3" in prompt:
    sys.stderr.write("fallo interno del CLI")
    sys.exit(3)
if "mcpcaido" in prompt:
    emit({"type": "system", "subtype": "init", "session_id": sid, "model": "m",
          "tools": [], "mcp_servers": [{"name": "autocad", "status": "failed"}]})
emit({"type": "assistant", "session_id": sid, "message": {"content": [
    {"type": "text", "text": "Dibujo la línea."},
    {"type": "tool_use", "id": "tu_1", "name": "mcp__autocad__create_line",
     "input": {"x1": 0, "y1": 0, "x2": 5, "y2": 0}}], "usage": {"output_tokens": 20}}})
emit({"type": "user", "session_id": sid, "message": {"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "tu_1", "content": [{"type": "text", "text": "{\"handle\": \"A1\"}"}]}]}})
emit({"type": "assistant", "session_id": sid, "message": {"content": [{"type": "text", "text": "Listo: handle A1."}],
                                                          "usage": {"output_tokens": 8}}})
emit({"type": "result", "subtype": "success", "is_error": False, "result": "Listo: handle A1.", "session_id": sid,
      "num_turns": 2, "total_cost_usd": 0.01,
      "usage": {"input_tokens": 100, "cache_creation_input_tokens": 50, "cache_read_input_tokens": 400,
                "output_tokens": 28}})
'''


def preparar_stub(carpeta: str) -> tuple[str, str]:
    """Deja el CLI de mentira listo y apunta puentes.py a él. Devuelve (ruta del registro, ruta del CLI)."""
    py = os.path.join(carpeta, "stub.py")
    with open(py, "w", encoding="utf-8") as fh:
        fh.write(STUB)
    if os.name == "nt":
        cli = os.path.join(carpeta, "claude_falso.cmd")
        with open(cli, "w", encoding="utf-8") as fh:
            fh.write(f'@echo off\r\n"{sys.executable}" "{py}" %*\r\n')
    else:
        cli = os.path.join(carpeta, "claude_falso.sh")
        with open(cli, "w", encoding="utf-8") as fh:
            fh.write(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n')
        os.chmod(cli, os.stat(cli).st_mode | stat.S_IEXEC)
    registro = os.path.join(carpeta, "registro.json")
    os.environ["STUB_REGISTRO"] = registro
    os.environ[puentes.PUENTES["claude-code"]["variable"]] = cli
    return registro, cli


def correr(pedido: str, **kw):
    eventos: list[tuple[str, dict]] = []
    r = puentes.correr("claude-code", pedido, lambda t, c: eventos.append((t, c)), kw.pop("cancelado", lambda: False), **kw)
    return r, eventos


def tipos(eventos):
    return [t for t, _ in eventos]


# ---------------------------------------------------------------------------------------------- pruebas

def test_comando_y_entorno() -> None:
    cmd = puentes.armar_comando("claude", "mcp.json", "sonnet", "abc", "reglas.md")
    check("el modo es -p con stream-json", cmd[:2] == ["claude", "-p"] and "stream-json" in cmd and "--verbose" in cmd)
    check("sin herramientas propias de Claude Code (--tools \"\")", cmd[cmd.index("--tools") + 1] == "")
    check("solo lo de AutoCAD está permitido y lo demás se niega solo",
          cmd[cmd.index("--permission-mode") + 1] == "dontAsk" and cmd[cmd.index("--allowedTools") + 1] == "mcp__autocad")
    check("run_code queda negado", "mcp__autocad__run_code" in cmd[cmd.index("--disallowedTools") + 1:])
    check("solo el servidor MCP que se le da", "--strict-mcp-config" in cmd)
    check("sigue la conversación con --resume y elige modelo",
          cmd[cmd.index("--resume") + 1] == "abc" and cmd[cmd.index("--model") + 1] == "sonnet")
    check("las reglas van por archivo, no por la línea de comandos",
          cmd[cmd.index("--append-system-prompt-file") + 1] == "reglas.md" and "--append-system-prompt" not in cmd)
    check("sin sesión ni modelo no pone --resume ni --model",
          "--resume" not in puentes.armar_comando("c", "m") and "--model" not in puentes.armar_comando("c", "m"))
    env = puentes.entorno_limpio({"PATH": "x", "CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "s", "ANTHROPIC_BASE_URL": "u",
                                  "ANTHROPIC_API_KEY": "k", "OTRA": "1"})
    check("el entorno no hereda la sesión de otro Claude Code, pero conserva la clave de API si la hay",
          set(env) == {"PATH", "ANTHROPIC_API_KEY", "OTRA"})
    with tempfile.TemporaryDirectory() as d:
        cfg = json.load(open(puentes.escribir_mcp_config(d), encoding="utf-8"))
        srv = cfg["mcpServers"]["autocad"]
        check("el MCP de AutoCAD es el mismo server.py del proyecto",
              srv["args"][0].endswith(os.path.join("mcp_server", "server.py")) and os.path.exists(srv["args"][0]))


def test_traductor() -> None:
    # el caso REAL visto en esta máquina: el CLI contesta con el aviso de la organización
    msg = "Your organization has disabled Claude subscription access for Claude Code"
    t = puentes.Traductor()
    ev = t.traducir({"type": "assistant", "session_id": "s", "is_api_error_message": True,
                     "message": {"content": [{"type": "text", "text": msg}]}})
    ev += t.traducir({"type": "result", "is_error": True, "result": msg, "session_id": "s", "usage": {}})
    check("un error del CLI sale como aviso, una sola vez",
          [x for x in ev if x[0] == "aviso"] == [("aviso", {"texto": msg})] and "texto" not in tipos(ev))
    t = puentes.Traductor()
    ev = t.traducir({"type": "result", "is_error": True, "result": "otro fallo", "usage": {}})
    check("un error que solo viene en result también se avisa", ("aviso", {"texto": "otro fallo"}) in ev)
    t = puentes.Traductor()
    ev = t.traducir({"type": "system", "subtype": "init", "session_id": "S1", "model": "m",
                     "tools": ["mcp__autocad__a", "mcp__autocad__b", "Read"], "mcp_servers": [{"name": "autocad", "status": "connected"}]})
    check("init: cuenta solo las tools de AutoCAD y guarda la sesión", ev[0] == ("inicio", {"tools": 2, "modelo": "claude-code · m"}) and t.sesion == "S1")
    ev = t.traducir({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "mcp__autocad__create_line", "input": {"x": 1}}]}})
    ev += t.traducir({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok", "is_error": True}]}})
    check("tool y resultado se ligan por id y sin el prefijo mcp__autocad__",
          ev == [("tool", {"nombre": "create_line", "args": {"x": 1}}),
                 ("resultado", {"nombre": "create_line", "texto": "ok", "error": True})])
    ev = t.traducir({"type": "result", "is_error": False, "result": "x", "num_turns": 3,
                     "usage": {"input_tokens": 10, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 100, "output_tokens": 7}})
    check("el uso suma la entrada con la caché", ev[0] == ("uso", {"entrada": 115, "salida": 7, "total": 122, "vueltas": 3}))
    check("basura no rompe", t.traducir({"type": "algo_nuevo"}) == [] and t.traducir({}) == [])


def test_correr_con_cli_falso() -> None:
    with tempfile.TemporaryDirectory() as d:
        registro, _ = preparar_stub(d)
        reglas = "Reglas con & símbolos | raros > y\nsaltos de línea " + "x" * 60000
        r, ev = correr("dibuja una línea", sesion="previa-9", modelo="opus", sistema=reglas)
        check("flujo normal: inicio, texto, tool, resultado, texto, uso",
              tipos(ev) == ["inicio", "texto", "tool", "resultado", "texto", "uso"], str(tipos(ev)))
        check("devuelve la sesión para seguir y sin error", r == {"sesion": "sesion-123", "error": False}, str(r))
        check("el resultado de la tool trae el texto del bloque", ev[3] == ("resultado", {"nombre": "create_line", "texto": '{"handle": "A1"}', "error": False}))
        reg = json.load(open(registro, encoding="utf-8"))
        check("el pedido llegó por stdin, completo", reg["prompt"] == "dibuja una línea")
        check("sigue la sesión anterior y el modelo pedido", reg["argv"][reg["argv"].index("--resume") + 1] == "previa-9"
              and reg["argv"][reg["argv"].index("--model") + 1] == "opus")
        check("las reglas (60 mil caracteres, con & y saltos) llegaron enteras por archivo", reg["reglas"] == reglas)
        check("el CLI recibió el servidor MCP de AutoCAD", "mcpServers" in reg["mcp"] and "autocad" in reg["mcp"])
        check("el CLI no heredó variables CLAUDE*", not [k for k in reg["env"] if k.startswith("CLAUDE")], str(reg["env"]))
        check("la carpeta temporal se borra", not [n for n in os.listdir(tempfile.gettempdir()) if n.startswith("autocad_puente_")
                                                   and os.path.exists(os.path.join(tempfile.gettempdir(), n, "reglas.md"))])

        r, ev = correr("caso org")
        check("el aviso de la organización llega al chat tal cual y marca error",
              r["error"] is True and any(t == "aviso" and "organization has disabled" in c["texto"] for t, c in ev), str(ev))
        r, ev = correr("caso salir3")
        check("un CLI que muere sin eventos se avisa con su código y su stderr",
              r["error"] is True and any(t == "aviso" and "código 3" in c["texto"] and "fallo interno" in c["texto"] for t, c in ev), str(ev))
        r, ev = correr("caso mcpcaido")
        check("si el MCP de AutoCAD no conectó, lo avisa", any(t == "aviso" and "MCP" in c["texto"] for t, c in ev), str(ev))

        # cancelar: el CLI se cuelga y el 'Cancelar' de la interfaz lo corta
        cancelar = threading.Event()
        threading.Timer(1.5, cancelar.set).start()
        import time
        t0 = time.monotonic()
        r, ev = correr("caso colgar", cancelado=cancelar.is_set)
        check("cancelar corta el CLI en pocos segundos y no es un error",
              time.monotonic() - t0 < 20 and r["error"] is False and any(t == "aviso" and "Cancelado" in c["texto"] for t, c in ev),
              f"{time.monotonic() - t0:.1f}s {ev}")

    os.environ[puentes.PUENTES["claude-code"]["variable"]] = os.path.join(tempfile.gettempdir(), "no_existe_claude")
    r, ev = correr("hola")
    check("sin el CLI instalado lo dice y cómo arreglarlo", r["error"] is True and ev[0][0] == "aviso" and "Instala Claude Code" in ev[0][1]["texto"], str(ev))


def test_en_la_interfaz_web() -> None:
    from . import web
    from .cli import PERFILES
    os.environ["AUTOCAD_IA_PUENTES"] = "1"      # los puentes están ocultos por defecto (ver _proveedores_puente)
    with tempfile.TemporaryDirectory() as d:
        registro, cli = preparar_stub(d)
        web.Sesion.ARCHIVO = os.path.join(d, "conversacion.json")
        web.SESION.borrar()
        web._CONTEO.update({p: 1 for p in PERFILES})        # sin levantar el servidor MCP real para contar tools
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        httpd.daemon_threads = True
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        puerto = httpd.server_address[1]

        def http_(metodo, ruta, cuerpo=None):
            c = http.client.HTTPConnection("127.0.0.1", puerto, timeout=60)
            c.request(metodo, ruta, json.dumps(cuerpo) if cuerpo is not None else None, {"Content-Type": "application/json"})
            r = c.getresponse()
            return r.status, r.read().decode("utf-8")

        st, cuerpo = http_("GET", "/api/estado")
        fila = [p for p in json.loads(cuerpo)["proveedores"] if p["id"] == "claude-code"]
        check("el puente aparece entre los proveedores, sin clave y disponible",
              st == 200 and len(fila) == 1 and fila[0]["puente"] is True and fila[0]["clave"] and "listo" in fila[0]["detalle"], str(fila))
        os.environ[puentes.PUENTES["claude-code"]["variable"]] = os.path.join(d, "no_existe")
        fila = [p for p in json.loads(http_("GET", "/api/estado")[1])["proveedores"] if p["id"] == "claude-code"]
        check("sin el CLI: no hay 'clave' y el detalle dice qué hacer", fila[0]["clave"] is None and "Instala Claude Code" in fila[0]["detalle"])
        os.environ[puentes.PUENTES["claude-code"]["variable"]] = cli

        st, cuerpo = http_("POST", "/api/modelos", {"proveedor": "claude-code"})
        check("/api/modelos ofrece los alias de Claude Code", st == 200 and [m["modelo"] for m in json.loads(cuerpo)["modelos"]] == ["sonnet", "opus", "haiku"])

        def chat(texto, **extra):
            st, cuerpo = http_("POST", "/api/chat", {"mensaje": texto, "proveedor": "claude-code", "modelo": "openai/gpt-oss-20b", **extra})
            return st, [json.loads(l[6:]) for l in cuerpo.split("\n\n") if l.startswith("data: ")]

        st, ev = chat("dibuja una línea")
        t = [e["tipo"] for e in ev]
        check("el chat por HTTP emite los eventos que la interfaz ya muestra", st == 200 and t == ["inicio", "texto", "tool", "resultado", "texto", "uso", "fin"], str(t))
        reg = json.load(open(registro, encoding="utf-8"))
        check("un modelo que quedó de OTRO proveedor no se le pasa a Claude Code", "--model" not in reg["argv"], str(reg["argv"]))
        check("las reglas de dibujo del proyecto viajan en el sistema", "create_wall_network" in reg["reglas"] or len(reg["reglas"]) > 1000, str(len(reg["reglas"])))
        check("la sesión de Claude Code queda guardada para el mensaje siguiente", web.SESION.puente_sesion.get("claude-code") == "sesion-123")
        chat("sigue")
        reg = json.load(open(registro, encoding="utf-8"))
        check("el segundo mensaje continúa la misma conversación (--resume)", reg["argv"][reg["argv"].index("--resume") + 1] == "sesion-123")
        http_("POST", "/api/reset", {})
        check("'Nueva sesión' olvida la conversación del puente", web.SESION.puente_sesion == {})
        st, ev = chat("con imagen", imagenes=["data:image/png;base64,AAAA"])
        check("las imágenes se rechazan con motivo (el puente aún no las manda)", st == 400)
        st, ev = chat("caso org")
        check("el error de la organización llega a la pantalla como aviso", any(e["tipo"] == "aviso" and "organization" in e["texto"] for e in ev), str(ev))
        httpd.shutdown()
        web.SESION.borrar()


def main() -> int:
    for fn in (test_comando_y_entorno, test_traductor, test_correr_con_cli_falso, test_en_la_interfaz_web):
        print(fn.__name__)
        fn()
    if FALLAS:
        print("\n%d FALLAS:" % len(FALLAS))
        for f in FALLAS:
            print(" -", f)
        return 1
    print("\nOK: el puente traduce el CLI, lo cancela y se integra a la interfaz (con un CLI de mentira).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
