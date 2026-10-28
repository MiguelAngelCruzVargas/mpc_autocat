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
    config._claves["anthropic"] = "sk-ant-prueba"
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
    ok("SECRETO" not in crudo and "claves_dpapi" in crudo, "la clave no queda en texto claro en el disco")
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
    res = [m for m in s.mensajes if m["role"] == "herramienta"]
    ok(len(res[-1]["contenido"]) < 9000 and "recortado" in res[-1]["contenido"],
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
    ultimo = [m for m in s.mensajes if m["role"] == "herramienta"][-1]
    ok(ultimo["error"] and "NO autorizó" in ultimo["contenido"],
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
    res = [m for m in s.mensajes if m["role"] == "herramienta"]
    ok(all(b["error"] for b in res) and len(res) == 3, "run_code, una herramienta inexistente y una que falla vuelven como error al modelo")
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
    config._claves["anthropic"] = "sk-ant-prueba"
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


# ---------------------------------------------------------------------------------------------- Groq (transporte de mentira)

def _sse(*trozos):
    """Un flujo SSE como el de Groq (compatible con OpenAI): cada trozo es un dict."""
    return ("".join("data: " + json.dumps(t) + "\n\n" for t in trozos) + "data: [DONE]\n\n").encode("utf-8")


def _delta(**d):
    return {"choices": [{"index": 0, "delta": d}]}


def _fin(razon, uso=None):
    t = {"choices": [{"index": 0, "delta": {}, "finish_reason": razon}]}
    if uso:
        t["x_groq"] = {"usage": uso}
    return t


class GroqFalso:
    """httpx.MockTransport que contesta con un guion de respuestas y guarda lo que se le mandó."""

    def __init__(self, *respuestas):
        import httpx
        self.pendientes = list(respuestas)
        self.peticiones: list[Any] = []
        self.transporte = httpx.MockTransport(self._atender)

    def _atender(self, req):
        import httpx
        self.peticiones.append(req)
        if req.method == "GET":
            return httpx.Response(200, json={"data": [
                {"id": "openai/gpt-oss-20b", "active": True}, {"id": "whisper-large-v3", "active": True},
                {"id": "openai/gpt-oss-120b", "active": True}, {"id": "llama-guard-4", "active": True},
                {"id": "viejo/modelo", "active": False}, {"id": "otro/chat", "active": True}]})
        r = self.pendientes.pop(0) if self.pendientes else _sse(_delta(content="(sin guion)"), _fin("stop"))
        if isinstance(r, tuple):
            return httpx.Response(r[0], json=r[1])
        return httpx.Response(200, content=r, headers={"Content-Type": "text/event-stream"})

    def cuerpos(self):
        return [json.loads(p.content) for p in self.peticiones if p.method == "POST"]


def _sesion_groq(falso, **cfg):
    config = cs.Config(ruta=os.path.join(tempfile.mkdtemp(), "chat.json"))
    config.proveedor = "groq"
    config._claves["groq"] = "gsk_prueba"
    for k, v in cfg.items():
        setattr(config, k, v)
    mcp = FalsoMcp()
    return cs.Sesion(config, cs.Herramientas(mcp), None, falso.transporte), mcp


def test_config_por_proveedor():
    ruta = os.path.join(tempfile.mkdtemp(), "chat.json")
    c = cs.Config(ruta=ruta)
    try:
        c.poner_clave("sk-ant-que-no-es-de-groq", "groq")
        ok(False, "una clave de Anthropic no se acepta como clave de Groq")
    except ValueError as e:
        ok("gsk_" in str(e), "una clave de Anthropic no se acepta como clave de Groq")
    c.poner_clave("sk-ant-api03-SECRETOANT", "anthropic")
    c.poner_clave("gsk_SECRETOGROQ", "groq")
    c.proveedor = "groq"
    c.modelo = "openai/gpt-oss-20b"
    c.guardar()
    crudo = open(ruta, encoding="utf-8").read()
    ok("SECRETOGROQ" not in crudo and "SECRETOANT" not in crudo, "ninguna de las dos claves queda en texto claro")
    c2 = cs.Config(ruta=ruta)
    ok(c2.proveedor == "groq" and c2.clave == "gsk_SECRETOGROQ" and c2.clave_de("anthropic") == "sk-ant-api03-SECRETOANT",
       "se recuperan el proveedor y la clave de cada uno")
    ok(c2.modelo == "openai/gpt-oss-20b" and c2.modelos["anthropic"] == cs.MODELOS[0][0], "cada proveedor recuerda su modelo")
    # formato anterior: una sola clave y un solo modelo, de Anthropic
    ruta_vieja = os.path.join(tempfile.mkdtemp(), "chat.json")
    json.dump({"modelo": "claude-haiku-5-5", "auto": True,
               "clave_dpapi": __import__("base64").b64encode(cs.proteger(b"sk-ant-vieja")).decode()}, open(ruta_vieja, "w"))
    c3 = cs.Config(ruta=ruta_vieja)
    ok(c3.proveedor == "anthropic" and c3.clave == "sk-ant-vieja" and c3.modelo == "claude-haiku-5-5" and c3.auto,
       "el archivo de la versión anterior se sigue leyendo")


def test_groq_conversion():
    hist = [{"role": "user", "texto": "hola"},
            {"role": "assistant", "texto": "Busco.", "llamadas": [{"id": "c1", "nombre": "buscar_herramientas", "entrada": {"flujo": "casa"}}]},
            {"role": "herramienta", "id": "c1", "contenido": "pasos", "error": False}]
    m = cs.prov.ProvGroq.convertir("SIS", hist)
    ok(m[0] == {"role": "system", "content": "SIS"} and m[1] == {"role": "user", "content": "hola"}, "el sistema va como primer mensaje")
    ok(m[2]["tool_calls"][0]["function"] == {"name": "buscar_herramientas", "arguments": '{"flujo": "casa"}'}
       and m[3] == {"role": "tool", "tool_call_id": "c1", "content": "pasos"},
       "la llamada y su resultado quedan en el formato de OpenAI")
    a = cs.prov.ProvAnthropic.convertir(hist + [{"role": "herramienta", "id": "c2", "contenido": "x", "error": True}])
    ok(a[1]["content"][1]["type"] == "tool_use" and a[2]["content"][0]["type"] == "tool_result", "y en el de Anthropic")
    ok(len(cs.prov.ProvGroq.herramientas(cs.HERRAMIENTAS)) == 4
       and cs.prov.ProvGroq.herramientas(cs.HERRAMIENTAS)[2]["function"]["parameters"]["required"] == ["nombre"],
       "las 4 herramientas se traducen a funciones con su esquema")


def test_groq_bucle_completo():
    falso = GroqFalso(
        _sse(_delta(content="Busco "), _delta(content="la herramienta. "),
             _delta(tool_calls=[{"index": 0, "id": "call_1", "type": "function", "function": {"name": "ejecutar_herramienta", "arguments": ""}}]),
             _delta(tool_calls=[{"index": 0, "function": {"arguments": '{"nombre": "get_entity", '}}]),
             _delta(tool_calls=[{"index": 0, "function": {"arguments": '"argumentos": {"handle": "A1"}}'}}]),
             _fin("tool_calls")),
        _sse(_delta(content="Listo."), _fin("stop", {"prompt_tokens": 800, "completion_tokens": 40})))
    s, mcp = _sesion_groq(falso)
    ev = _correr(s, "¿qué hay?")
    ok("".join(e["d"] for e in ev if e["t"] == "texto") == "Busco la herramienta. Listo.", "el texto llega por pedazos y completo")
    ok(("get_entity", {"handle": "A1"}) in mcp.llamadas, "los argumentos que llegaron en pedazos se juntan y la herramienta corre")
    ok([e["t"] for e in ev if e["t"] != "texto"] == ["herramienta", "resultado", "fin"], "emite los mismos eventos que con Claude")
    c1, c2 = falso.cuerpos()
    ok(c1["model"] == "openai/gpt-oss-120b" and c1["stream"] is True and len(c1["tools"]) == 4 and c1["tools"][0]["type"] == "function",
       "pide streaming con las 4 herramientas y el modelo elegido")
    ok(c1["messages"][0]["role"] == "system" and "Procedimiento obligatorio" in c1["messages"][0]["content"],
       "a un modelo abierto se le agrega el procedimiento de herramientas")
    ok(falso.peticiones[0].headers["authorization"] == "Bearer gsk_prueba", "manda la clave de Groq como Bearer")
    ok([m["role"] for m in c2["messages"]][-2:] == ["assistant", "tool"] and c2["messages"][-1]["tool_call_id"] == "call_1",
       "la segunda vuelta lleva la llamada y su resultado")
    ok(s.tokens["entrada"] == 800 and s.tokens["salida"] == 40, "cuenta los tokens que informa Groq")


def test_groq_argumentos_malos_y_permisos():
    falso = GroqFalso(
        _sse(_delta(tool_calls=[{"index": 0, "id": "c1", "type": "function",
                                  "function": {"name": "ejecutar_herramienta", "arguments": '{"nombre": "create_line", "argumentos": {'}}]),
             _fin("tool_calls")),
        _sse(_delta(tool_calls=[{"index": 0, "id": "c2", "type": "function",
                                  "function": {"name": "ejecutar_herramienta", "arguments": '{"nombre": "create_line", "argumentos": {"x": 1}}'}}]),
             _fin("tool_calls")),
        _sse(_delta(content="fin"), _fin("stop")))
    s, mcp = _sesion_groq(falso)
    ev = _correr(s, "dibuja", responder=lambda e: (False, False))
    res = [m for m in s.mensajes if m["role"] == "herramienta"]
    ok(res[0]["error"] and "JSON válido" in res[0]["contenido"], "un JSON cortado vuelve al modelo como error")
    ok(sum(1 for e in ev if e["t"] == "aprobar") == 1 and mcp.llamadas == [],
       "el JSON roto no se ejecuta ni se pregunta; el bueno pide permiso igual que con Claude y, rechazado, no corre")


def test_groq_errores():
    for estado, cuerpo, frase in ((401, {"error": {"message": "Invalid API Key", "code": "invalid_api_key"}}, "clave de Groq no es válida"),
                                  (429, {"error": {"message": "rate", "code": "rate_limit_exceeded"}}, "límite"),
                                  (404, {"error": {"message": "model not found", "code": "model_not_found"}}, "no existe"),
                                  (400, {"error": {"message": "bad", "code": "tool_use_failed"}}, "mal una llamada"),
                                  (503, {"error": {"message": "over"}}, "saturado")):
        s, _ = _sesion_groq(GroqFalso((estado, cuerpo)))
        ev = _correr(s, "hola")
        ok(ev[0]["t"] == "error" and frase in ev[0]["d"], f"Groq {estado} sale en español y sin traza")
    config = cs.Config(ruta=os.path.join(tempfile.mkdtemp(), "c.json"))
    config.proveedor = "groq"
    os.environ.pop("GROQ_API_KEY", None)
    s2 = cs.Sesion(config, cs.Herramientas(FalsoMcp()))
    ev = _correr(s2, "hola")
    ok(ev[0]["t"] == "error" and "Groq" in ev[0]["d"], "sin clave de Groq lo dice y no llama a nadie")


def test_groq_modelos_y_api():
    falso = GroqFalso()
    p = cs.prov.ProvGroq("gsk_x", transporte=falso.transporte)
    ids = [i for i, _ in p.modelos()]
    ok(ids == ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "otro/chat"],
       "la lista sale de la API de Groq, sin voz ni guardias ni inactivos, con los gpt-oss primero")
    ok(cs.prov.ProvGroq("", transporte=falso.transporte).modelos() == cs.prov.MODELOS_GROQ, "sin clave usa la lista de respaldo")
    # la API local: cambiar de proveedor, guardar su clave y elegir modelo
    config = cs.Config(ruta=os.path.join(tempfile.mkdtemp(), "chat.json"))
    config._claves["anthropic"] = "sk-ant-prueba"
    app = cs.Aplicacion(config, cs.Herramientas(FalsoMcp()), None, falso.transporte)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), cs._manejador(app))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    puerto = httpd.server_address[1]
    st, cuerpo = _http(puerto, "GET", "/api/estado", token=app.token)
    e = json.loads(cuerpo)
    ok(e["proveedor"] == "anthropic" and [p["id"] for p in e["proveedores"]] == ["anthropic", "groq"]
       and e["proveedores"][0]["clave"] and not e["proveedores"][1]["clave"], "el estado dice el proveedor y cuál tiene clave")
    st, _ = _http(puerto, "POST", "/api/config", {"proveedor": "groq", "clave": "sk-ant-mala"}, token=app.token)
    ok(st == 400 and config.proveedor == "anthropic", "una clave del proveedor equivocado se rechaza y no cambia nada")
    st, cuerpo = _http(puerto, "POST", "/api/config", {"proveedor": "groq", "clave": "gsk_buena", "modelo": "openai/gpt-oss-20b"}, token=app.token)
    e = json.loads(cuerpo)
    ok(st == 200 and e["proveedor"] == "groq" and e["clave"] and e["modelo"] == "openai/gpt-oss-20b"
       and "openai/gpt-oss-120b" in [m["id"] for m in e["modelos"]], "cambiar a Groq devuelve su clave, su modelo y su lista")
    st, cuerpo = _http(puerto, "POST", "/api/config", {"modelo": "claude-opus-5-5"}, token=app.token)
    ok(config.modelos["anthropic"] == cs.MODELOS[0][0] and config.modelo == "openai/gpt-oss-20b",
       "un modelo de Claude no se acepta como modelo de Groq")
    st, _ = _http(puerto, "POST", "/api/config", {"proveedor": "anthropic", "modelo": "claude-haiku-5-5"}, token=app.token)
    ok(config.proveedor == "anthropic" and config.modelo == "claude-haiku-5-5" and config.modelos["groq"] == "openai/gpt-oss-20b",
       "volver a Claude conserva el modelo de cada uno")
    ok(_http(puerto, "POST", "/api/config", {"proveedor": "nadie"}, token=app.token)[0] == 400, "un proveedor que no existe se rechaza")
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
    test_config_por_proveedor()
    test_groq_conversion()
    test_groq_bucle_completo()
    test_groq_argumentos_malos_y_permisos()
    test_groq_errores()
    test_groq_modelos_y_api()
    if FALLAS:
        print(f"\n{len(FALLAS)} fallas")
        sys.exit(1)
    print("\nOK")
