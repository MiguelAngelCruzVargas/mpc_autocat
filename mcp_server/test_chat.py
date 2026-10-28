"""El chat dentro de AutoCAD (chat_server): clave cifrada, reglas de permiso, bucle del agente y la API local.
Con un 'Claude' de mentira (chat_prueba) y un servidor MCP de mentira: no necesita AutoCAD, clave ni red."""
from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any

import chat_prueba as cp
import chat_server as cs

FALLAS: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(("  ok    " if cond else "  FALLA ") + msg)
    if not cond:
        FALLAS.append(msg)


class FalsoMcp:
    """Lo mínimo del FastMCP: lista de herramientas y call_tool."""

    def __init__(self):
        self.llamadas: list[tuple[str, dict]] = []
        self.mcp = self

    async def list_tools(self):
        def t(n, d):
            return SimpleNamespace(name=n, description=d, inputSchema={"title": "X", "properties": {"x": {"title": "X", "type": "number"}}})
        return [t("get_entity", "lee"), t("create_line", "dibuja"), t("delete_entities", "borra"), t("list_tool_categories", "mapa"),
                t("get_drawing_info", "info"), t("get_editor_state", "estado"), t("run_code", "c#"), t("explota", "falla")]

    async def call_tool(self, nombre, args):
        self.llamadas.append((nombre, args))
        if nombre == "explota":
            raise RuntimeError("boom")
        if nombre == "get_entity":
            return ([SimpleNamespace(text="x" * 20000)], {})
        return ([SimpleNamespace(text=json.dumps({"tool": nombre, "args": args}))], {})


def _sesion(cliente, **cfg):
    config = cs.Config(ruta=os.path.join(tempfile.mkdtemp(), "chat.json"))
    config._clave = "sk-ant-prueba"
    for k, v in cfg.items():
        setattr(config, k, v)
    falso = FalsoMcp()
    s = cs.Sesion(config, cs.Herramientas(falso), lambda _k: cliente)
    return s, falso


def _correr(s, texto, responder=None):
    """Corre un mensaje y devuelve los eventos; `responder(evento)` contesta los permisos (lo que haría la interfaz)."""
    eventos: list[dict] = []

    def emitir(e):
        eventos.append(e)
        if e["t"] == "aprobar" and responder:
            threading.Timer(0.05, lambda: s.resolver(e["id"], *responder(e))).start()
    s.correr(texto, emitir)
    return eventos


def test_clave_cifrada():
    ruta = os.path.join(tempfile.mkdtemp(), "chat.json")
    c = cs.Config(ruta=ruta)
    try:
        c.poner_clave("hola")
        ok(False, "rechaza una clave que no es de Anthropic")
    except ValueError:
        ok(True, "rechaza una clave que no es de Anthropic")
    c.poner_clave("sk-ant-api03-SECRETO-1234")
    crudo = open(ruta, encoding="utf-8").read()
    ok("SECRETO" not in crudo and "clave_dpapi" in crudo, "la clave no queda en texto claro en el disco")
    c2 = cs.Config(ruta=ruta)
    ok(c2.clave == "sk-ant-api03-SECRETO-1234", "se recupera al volver a abrir")


def test_reglas_de_permiso():
    ok(cs.es_lectura("get_entity") and cs.es_lectura("check_all") and cs.es_lectura("query_entities"), "consultar no pide permiso")
    ok(not cs.es_lectura("create_line") and not cs.es_lectura("export_pdf") and not cs.es_lectura("save_drawing"),
       "dibujar, exportar y guardar sí piden")
    ok(cs.es_destructiva("delete_entities") and cs.es_destructiva("purge_database_objects") and cs.es_destructiva("undo"),
       "borrar, purgar y deshacer son destructivas")
    ok(not cs.es_destructiva("create_line"), "dibujar no es destructiva")


def test_bucle_con_lectura_sin_permiso():
    cli = cp.con_guion(
        cp.respuesta(cp.texto("Busco. "), cp.usa("buscar_herramientas", flujo="portico")),
        cp.respuesta(cp.texto("Veo la entidad. "), cp.usa("ejecutar_herramienta", nombre="get_entity", argumentos={"handle": "A1"})),
        cp.respuesta(cp.texto("Listo.")))
    s, falso = _sesion(cli)
    ev = _correr(s, "¿qué hay?")
    ok([e["t"] for e in ev if e["t"] != "texto"] == ["herramienta", "resultado", "herramienta", "resultado", "fin"],
       "buscar y consultar corren sin pedir permiso y terminan con 'fin'")
    ok(("list_tool_categories", {"workflow": "portico"}) in falso.llamadas, "buscar_herramientas llama a list_tool_categories")
    res = [m for m in s.mensajes if m["role"] == "user" and isinstance(m["content"], list)]
    ok(len(res[-1]["content"][0]["content"]) < 9000 and "recortado" in res[-1]["content"][0]["content"],
       "un resultado enorme le llega recortado al modelo")
    ok(s.tokens["entrada"] == 3600 and s.tokens["cache"] == 2700, "suma los tokens de cada vuelta")
    ok(cli.llamadas[0]["system"][0]["cache_control"] == {"type": "ephemeral"} and len(cli.llamadas[0]["tools"]) == 4,
       "manda 4 herramientas (no 300) y el sistema con caché")


def test_permiso_aceptado_y_rechazado():
    guion = lambda: cp.con_guion(
        cp.respuesta(cp.texto("Dibujo. "), cp.usa("ejecutar_herramienta", nombre="create_line", argumentos={"x": 1})),
        cp.respuesta(cp.texto("Listo.")))
    s, falso = _sesion(guion())
    ev = _correr(s, "dibuja", responder=lambda e: (True, False))
    ok(any(e["t"] == "aprobar" and e["nombre"] == "create_line" for e in ev) and ("create_line", {"x": 1}) in falso.llamadas,
       "dibujar pide permiso y, aceptado, se ejecuta")
    s, falso = _sesion(guion())
    ev = _correr(s, "dibuja", responder=lambda e: (False, False))
    ok(falso.llamadas == [] and any(e["t"] == "resultado" and not e["ok"] for e in ev), "rechazado: NO se ejecuta")
    ultimo = [m for m in s.mensajes if isinstance(m["content"], list) and m["content"][0].get("type") == "tool_result"][-1]
    ok(ultimo["content"][0]["is_error"] and "NO autorizó" in ultimo["content"][0]["content"],
       "el modelo recibe que el usuario no autorizó, como error")
    # permitir todo en la conversación
    s, falso = _sesion(cp.con_guion(
        cp.respuesta(cp.usa("ejecutar_herramienta", nombre="create_line", argumentos={"x": 1})),
        cp.respuesta(cp.usa("ejecutar_herramienta", nombre="create_line", argumentos={"x": 2})), cp.respuesta(cp.texto("ok"))))
    ev = _correr(s, "dos líneas", responder=lambda e: (True, True))
    ok(sum(1 for e in ev if e["t"] == "aprobar") == 1 and len(falso.llamadas) == 2, "'permitir todo' pregunta una sola vez")


def test_modo_auto_no_salta_lo_destructivo():
    s, falso = _sesion(cp.con_guion(
        cp.respuesta(cp.usa("ejecutar_herramienta", nombre="create_line", argumentos={"x": 1})),
        cp.respuesta(cp.usa("ejecutar_herramienta", nombre="delete_entities", argumentos={"handles": ["A"]})),
        cp.respuesta(cp.texto("fin"))), auto=True)
    ev = _correr(s, "haz", responder=lambda e: (False, False))
    pidio = [e["nombre"] for e in ev if e["t"] == "aprobar"]
    ok(pidio == ["delete_entities"] and ("create_line", {"x": 1}) in falso.llamadas and not any(n == "delete_entities" for n, _ in falso.llamadas),
       "en modo auto dibujar pasa, pero borrar se pide igual (y rechazado no se ejecuta)")


def test_casos_malos():
    s, falso = _sesion(cp.con_guion(
        cp.respuesta(cp.usa("ejecutar_herramienta", nombre="run_code", argumentos={"code": "x"})),
        cp.respuesta(cp.usa("ejecutar_herramienta", nombre="no_existe", argumentos={})),
        cp.respuesta(cp.usa("ejecutar_herramienta", nombre="explota", argumentos={})),
        cp.respuesta(cp.texto("fin"))), auto=True)
    _correr(s, "mal", responder=lambda e: (True, False))
    res = [b for m in s.mensajes if m["role"] == "user" and isinstance(m["content"], list) for b in m["content"]]
    ok(all(b["is_error"] for b in res) and len(res) == 3, "run_code, una herramienta inexistente y una que falla vuelven como error al modelo")
    ok(falso.llamadas == [("explota", {})], "run_code ni se intenta ni se pregunta")
    # sin clave
    config = cs.Config(ruta=os.path.join(tempfile.mkdtemp(), "c.json"))
    os.environ.pop("ANTHROPIC_API_KEY", None)
    s2 = cs.Sesion(config, cs.Herramientas(FalsoMcp()), lambda _k: cp.con_guion())
    ev = _correr(s2, "hola")
    ok(ev[0]["t"] == "error" and "clave" in ev[0]["d"].lower(), "sin clave lo dice y no llama a nadie")

    class Malo:
        def __init__(self, estado):
            self.messages = SimpleNamespace(stream=self._s)
            self.e = estado

        def _s(self, **_k):
            err = RuntimeError("x")
            err.status_code = self.e
            raise err
    for estado, frase in ((401, "no es válida"), (429, "límite"), (529, "saturado")):
        s3, _ = _sesion(Malo(estado))
        ev = _correr(s3, "hola")
        ok(ev[0]["t"] == "error" and frase in ev[0]["d"], f"error {estado} del API sale en español y sin traza")


def test_detener_y_limite():
    s, _ = _sesion(cp.Cliente(lambda m: cp.respuesta(cp.usa("buscar_herramientas"))))
    ev = _correr(s, "sin fin")
    ok(any(e["t"] == "texto" and "me detuve" in e["d"] for e in ev), f"corta a los {cs.MAX_PASOS} pasos")
    # detener: el usuario aprieta "Detener" apenas empieza la primera herramienta
    s, falso = _sesion(cp.Cliente(lambda m: cp.respuesta(cp.usa("buscar_herramientas"))))
    eventos: list[dict] = []

    def emitir(e):
        eventos.append(e)
        if e["t"] == "herramienta":
            s.parar.set()
    s.correr("sin fin", emitir)
    vueltas = sum(1 for e in eventos if e["t"] == "herramienta")
    ok(vueltas == 1 and any(e["t"] == "texto" and "detenido" in e["d"] for e in eventos),
       "'Detener' corta el bucle antes de la vuelta siguiente y lo avisa")


# ---------------------------------------------------------------------------------------------- API local

def _servidor(cliente):
    config = cs.Config(ruta=os.path.join(tempfile.mkdtemp(), "chat.json"))
    config._clave = "sk-ant-prueba"
    app = cs.Aplicacion(config, cs.Herramientas(FalsoMcp()), lambda _k: cliente)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), cs._manejador(app))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return app, httpd, httpd.server_address[1]


def _http(puerto, metodo, ruta, cuerpo=None, token=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", puerto, timeout=10)
    h = {"Content-Type": "application/json"}
    if token is not None:
        h["X-Chat-Token"] = token
    if host:
        h["Host"] = host
    c.request(metodo, ruta, json.dumps(cuerpo) if cuerpo is not None else None, h)
    r = c.getresponse()
    return r.status, r.read().decode("utf-8")


def test_api_local():
    app, httpd, puerto = _servidor(cp.con_guion(
        cp.respuesta(cp.texto("Dibujo. "), cp.usa("ejecutar_herramienta", nombre="create_line", argumentos={"x": 1})),
        cp.respuesta(cp.texto("Listo."))))
    st, cuerpo = _http(puerto, "GET", "/")
    ok(st == 200 and app.token in cuerpo and "__TOKEN__" not in cuerpo, "la página sale con su token")
    ok(_http(puerto, "GET", "/api/estado")[0] == 401, "sin token no hay API")
    ok(_http(puerto, "GET", "/api/estado", token="malo")[0] == 401, "con token malo tampoco")
    ok(_http(puerto, "GET", "/api/estado", token=app.token, host="evil.example.com")[0] == 403, "otro Host se rechaza (DNS rebinding)")
    ok(_http(puerto, "GET", "/api/estado", token=app.token)[0] == 200, "con token y Host bueno, sí")
    st, _ = _http(puerto, "POST", "/api/config", {"clave": "mala"}, token=app.token)
    ok(st == 400, "una clave que no es de Anthropic se rechaza con 400")
    # chat completo por HTTP, con el permiso contestado por otra conexión
    resultado: dict[str, Any] = {}

    def chatea():
        resultado["r"] = _http(puerto, "POST", "/api/chat", {"texto": "dibuja"}, token=app.token)
    t = threading.Thread(target=chatea)
    t.start()
    for _ in range(100):
        if any(s.aprobaciones for s in app.sesiones.values()):
            break
        threading.Event().wait(0.05)
    s = list(app.sesiones.values())[0]
    pid = list(s.aprobaciones)[0]
    st, cuerpo = _http(puerto, "POST", "/api/aprobar", {"sesion": s.id, "id": pid, "ok": True}, token=app.token)
    t.join(15)
    st, cuerpo = resultado["r"]
    eventos = [json.loads(l[6:]) for l in cuerpo.split("\n\n") if l.startswith("data: ")]
    ok(st == 200 and [e["t"] for e in eventos if e["t"] not in ("texto",)] == ["herramienta", "aprobar", "resultado", "fin"],
       "el chat por HTTP emite herramienta, aprobar, resultado y fin")
    ok("".join(e["d"] for e in eventos if e["t"] == "texto") == "Dibujo. Listo.", "el texto llega por pedazos y completo")
    httpd.shutdown()


if __name__ == "__main__":
    test_clave_cifrada()
    test_reglas_de_permiso()
    test_bucle_con_lectura_sin_permiso()
    test_permiso_aceptado_y_rechazado()
    test_modo_auto_no_salta_lo_destructivo()
    test_casos_malos()
    test_detener_y_limite()
    test_api_local()
    if FALLAS:
        print(f"\n{len(FALLAS)} fallas")
        sys.exit(1)
    print("\nOK")
