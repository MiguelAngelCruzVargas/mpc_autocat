"""Chat DENTRO de AutoCAD: servidor local que habla con Claude y le presta las herramientas de este proyecto.

El panel de AutoCAD (comando MCPCHAT, ver plugin/.../ChatPaletteCommand.cs) solo muestra la página que sirve este
programa. Acá vive todo lo demás:

  - la página del chat (chat_ui/index.html) y su API local, solo en 127.0.0.1 y con un token por arranque;
  - el AGENTE: un bucle que le manda la conversación a Claude, ejecuta las herramientas que pide y vuelve a
    preguntar hasta que termina. Las herramientas son las mismas del servidor MCP (server.py), llamadas en este
    mismo proceso;
  - las reglas de seguridad: lo que modifica el dibujo se le PIDE al usuario antes de ejecutarse, y lo destructivo
    se pide siempre, incluso en modo automático.

Claude no recibe las ~300 herramientas de una vez (serían 100 mil tokens por mensaje): recibe tres de oficio
—buscar, describir, ejecutar— y descubre las que necesita, igual que se usa list_tool_categories.

La clave de API es del USUARIO (consola de Anthropic) y se guarda cifrada con DPAPI de Windows en
%LOCALAPPDATA%\\AutoCadMcp\\chat.json. Una suscripción de Claude no sirve para esto: la API es aparte.

Uso:  python chat_server.py            (lo arranca el comando MCPCHAT si hace falta)
      python chat_server.py --demo     (modelo de mentira: para ver la interfaz sin clave ni gasto)
"""
from __future__ import annotations

import asyncio
import base64
import ctypes
import json
import os
import secrets
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional

AQUI = os.path.dirname(os.path.abspath(__file__))
ESTADO = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AutoCadMcp")
CONFIG = os.path.join(ESTADO, "chat.json")
ARCHIVO_URL = os.path.join(ESTADO, "chat_url.txt")
ARCHIVO_LANZADOR = os.path.join(ESTADO, "chat_launcher.json")

MODELOS = [("claude-sonnet-5-5", "Sonnet 5.5 (recomendado)"), ("claude-haiku-5-5", "Haiku 5.5 (rápido y barato)"),
           ("claude-opus-5-5", "Opus 5.5 (el más capaz)")]
MAX_PASOS = 30                 # vueltas del agente por mensaje del usuario
MAX_RESULTADO = 8000           # caracteres de un resultado de herramienta que le llegan al modelo
ESPERA_APROBACION_S = 300

SISTEMA = """Eres el asistente de AutoCAD que vive dentro del programa. Trabajas sobre el dibujo ABIERTO del usuario con \
las herramientas de este proyecto (más de 280), que descubres tú mismo: `buscar_herramientas` (por texto, categoría o \
flujo de trabajo), `describir_herramienta` (parámetros exactos) y `ejecutar_herramienta`. No las escribas de memoria: \
descríbelas antes de usarlas. Para un trabajo completo pide primero el flujo con `buscar_herramientas(flujo=...)` \
(casa, estructura, instalaciones, vial, 3d, laminas, portico).

Reglas de oficio (no se negocian):
- Los datos del PROYECTO no se inventan ni se suponen: país y norma, capacidad del suelo, f'c, desplantes, medidas, \
nombre de la obra. Si faltan, pregúntalos juntos, en una sola tanda. Lo que supongas por falta de dato, dilo.
- Antes de dibujar algo serio, el dibujo debe estar guardado con nombre (`save_drawing`); nunca trabajes sobre Drawing1.
- Usa las herramientas de oficio, no scripts: `create_wall_network` para muros, cadenas de cotas, `place_labels` para \
rótulos, `compose_layout` para láminas. `run_code` está apagado: no lo pidas.
- Después de dibujar, VERIFICA con los `check_*` y mira de cerca si hace falta (`capture_viewport`). Un resultado que \
dice NO CUMPLE se dice tal cual, con su número; nunca lo escondas ni lo corrijas en silencio.
- Lo que modifica el dibujo se le pide permiso al usuario antes de ejecutarse: explica en una frase qué vas a hacer y \
por qué, y luego llama la herramienta. Si el usuario rechaza una acción, no la repitas: pregunta qué prefiere.
- Responde en español, corto y concreto: qué hiciste, con qué números y qué falta. Sin relleno ni adornos.
"""


# ---------------------------------------------------------------------------------------------- DPAPI y config

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def proteger(datos: bytes) -> bytes:
    """Cifra con DPAPI (solo este usuario de Windows puede descifrarlo)."""
    if os.name != "nt":
        return datos
    entrada = _Blob(len(datos), ctypes.cast(ctypes.create_string_buffer(datos), ctypes.POINTER(ctypes.c_char)))
    salida = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(salida)):
        raise OSError("DPAPI no pudo cifrar la clave")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def desproteger(datos: bytes) -> bytes:
    if os.name != "nt":
        return datos
    entrada = _Blob(len(datos), ctypes.cast(ctypes.create_string_buffer(datos), ctypes.POINTER(ctypes.c_char)))
    salida = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(salida)):
        raise OSError("DPAPI no pudo descifrar la clave (¿otro usuario de Windows?)")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


class Config:
    """clave (cifrada en disco), modelo y modo automático. `ruta` se puede cambiar para las pruebas."""

    def __init__(self, ruta: str = CONFIG):
        self.ruta = ruta
        self.modelo = MODELOS[0][0]
        self.auto = False
        self._clave: str = ""
        self.cargar()

    def cargar(self) -> None:
        try:
            with open(self.ruta, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return
        self.modelo = d.get("modelo") or self.modelo
        self.auto = bool(d.get("auto", False))
        if d.get("clave_dpapi"):
            try:
                self._clave = desproteger(base64.b64decode(d["clave_dpapi"])).decode("utf-8")
            except (OSError, ValueError):
                self._clave = ""

    def guardar(self) -> None:
        os.makedirs(os.path.dirname(self.ruta), exist_ok=True)
        d = {"modelo": self.modelo, "auto": self.auto}
        if self._clave:
            d["clave_dpapi"] = base64.b64encode(proteger(self._clave.encode("utf-8"))).decode("ascii")
        with open(self.ruta, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=1)

    @property
    def clave(self) -> str:
        return self._clave or os.environ.get("ANTHROPIC_API_KEY", "")

    def poner_clave(self, clave: str) -> None:
        clave = (clave or "").strip()
        if clave and not clave.startswith("sk-ant-"):
            raise ValueError("Esa no parece una clave de la API de Anthropic (empieza con sk-ant-).")
        self._clave = clave
        self.guardar()


# ---------------------------------------------------------------------------------------------- herramientas

PREFIJOS_LECTURA = ("get_", "list_", "check_", "query_", "aggregate_", "describe_", "calculate_", "capture_", "diagnose_",
                    "zoom_", "measure_", "api_guide", "ping", "suggest_layout", "suggest_furniture", "point_on_road",
                    "design_footing", "design_two_way_slab", "design_beam", "design_gate_portal", "design_fence",
                    "design_lintel", "design_pool", "panel_edge_loads", "continuous_beam", "traverse", "buscar_", "estado_")
PREFIJOS_DESTRUCTIVAS = ("delete_", "purge_", "close_document", "undo", "run_code", "set_system_variable", "merge_layers",
                         "overkill_entities", "detach_xref", "remove_", "clear_xdata", "union_regions")


def es_lectura(nombre: str) -> bool:
    return nombre.startswith(PREFIJOS_LECTURA)


def es_destructiva(nombre: str) -> bool:
    return nombre.startswith(PREFIJOS_DESTRUCTIVAS)


HERRAMIENTAS = [
    {"name": "buscar_herramientas",
     "description": "Busca herramientas de AutoCAD. Sin argumentos lista las categorías. `flujo` da los pasos EN ORDEN de un tipo "
                    "de proyecto (casa, estructura, instalaciones, vial, 3d, laminas, portico); `categoria` lista las de una "
                    "categoría; `texto` busca por palabras.",
     "input_schema": {"type": "object", "properties": {"texto": {"type": "string"}, "categoria": {"type": "string"},
                                                       "flujo": {"type": "string"}}}},
    {"name": "describir_herramienta",
     "description": "Devuelve la descripción completa y los parámetros exactos de UNA herramienta. Hazlo antes de ejecutarla.",
     "input_schema": {"type": "object", "properties": {"nombre": {"type": "string"}}, "required": ["nombre"]}},
    {"name": "ejecutar_herramienta",
     "description": "Ejecuta una herramienta de AutoCAD con sus argumentos. Lo que modifica el dibujo le pide permiso al usuario.",
     "input_schema": {"type": "object", "properties": {"nombre": {"type": "string"}, "argumentos": {"type": "object"}},
                      "required": ["nombre"]}},
    {"name": "estado_del_dibujo",
     "description": "Dibujo activo: archivo, unidades, capa actual, cantidad de entidades y si AutoCAD está ocupado.",
     "input_schema": {"type": "object", "properties": {}}},
]


def _recortar(texto: str, limite: int = MAX_RESULTADO) -> str:
    if len(texto) <= limite:
        return texto
    return texto[:limite] + f"\n[... recortado: {len(texto) - limite} caracteres más. Pide algo más acotado (filtros, límites).]"


def _compactar_esquema(x: Any) -> Any:
    """Quita los 'title' que FastMCP agrega a cada parámetro: gastan tokens y no dicen nada."""
    if isinstance(x, dict):
        return {k: _compactar_esquema(v) for k, v in x.items() if k != "title"}
    if isinstance(x, list):
        return [_compactar_esquema(v) for v in x]
    return x


class Herramientas:
    """Las herramientas del servidor MCP, llamadas en este mismo proceso."""

    def __init__(self, servidor: Any = None):
        self._servidor = servidor
        self._tools: dict[str, Any] = {}

    @property
    def mcp(self) -> Any:
        if self._servidor is None:
            import server
            self._servidor = server
        return self._servidor.mcp

    def _cargar(self) -> None:
        if not self._tools:
            tools = asyncio.run(self.mcp.list_tools())
            self._tools = {t.name: t for t in tools}

    def existe(self, nombre: str) -> bool:
        self._cargar()
        return nombre in self._tools

    def buscar(self, texto: str = "", categoria: str = "", flujo: str = "") -> str:
        r = asyncio.run(self.mcp.call_tool("list_tool_categories", {k: v for k, v in
                                                                      (("query", texto), ("category", categoria), ("workflow", flujo)) if v}))
        return _texto_de(r)

    def describir(self, nombre: str) -> str:
        self._cargar()
        t = self._tools.get(nombre)
        if not t:
            return f"No existe la herramienta '{nombre}'. Usa buscar_herramientas."
        return json.dumps({"nombre": t.name, "descripcion": t.description, "parametros": _compactar_esquema(t.inputSchema)},
                          ensure_ascii=False)

    def ejecutar(self, nombre: str, argumentos: dict[str, Any]) -> str:
        r = asyncio.run(self.mcp.call_tool(nombre, argumentos or {}))
        return _texto_de(r)


def _texto_de(resultado: Any) -> str:
    contenido = resultado[0] if isinstance(resultado, tuple) else resultado
    partes = [getattr(c, "text", None) or str(c) for c in (contenido or [])]
    return "\n".join(partes)


# ---------------------------------------------------------------------------------------------- el agente

def _bloques(contenido: Any) -> list[dict[str, Any]]:
    """Los bloques de la respuesta del modelo como dicts que se pueden volver a enviar."""
    out = []
    for b in contenido:
        tipo = getattr(b, "type", None)
        if tipo == "text":
            out.append({"type": "text", "text": b.text})
        elif tipo == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
    return out


def _error_amable(e: Exception) -> str:
    estado = getattr(e, "status_code", None)
    if estado == 401:
        return "La clave de API no es válida. Revísala en Ajustes."
    if estado == 403:
        return "La clave de API no tiene permiso para este modelo."
    if estado == 429:
        return "Se alcanzó el límite de uso de la API. Espera un momento e inténtalo de nuevo."
    if estado in (500, 502, 503, 529):
        return "El servicio de Claude está saturado. Inténtalo de nuevo en un momento."
    if estado == 400 and "credit" in str(e).lower():
        return "La cuenta de la API se quedó sin saldo."
    return f"Error al hablar con Claude: {e}"


class Sesion:
    """Una conversación: su historial y su bucle de agente."""

    def __init__(self, config: Config, herramientas: Herramientas, crear_cliente: Optional[Callable[[str], Any]] = None):
        self.id = uuid.uuid4().hex[:8]
        self.config = config
        self.herr = herramientas
        self.mensajes: list[dict[str, Any]] = []
        self.crear_cliente = crear_cliente or self._cliente_real
        self.parar = threading.Event()
        self.aprobaciones: dict[str, dict[str, Any]] = {}
        self.permitir_todo = False
        self.tokens = {"entrada": 0, "salida": 0, "cache": 0}
        self.ocupada = threading.Lock()

    @staticmethod
    def _cliente_real(clave: str) -> Any:
        import anthropic
        return anthropic.Anthropic(api_key=clave, max_retries=2)

    # --- aprobación
    def resolver(self, id_: str, ok: bool, siempre: bool = False) -> bool:
        a = self.aprobaciones.get(id_)
        if not a:
            return False
        a["ok"] = ok
        if ok and siempre:
            self.permitir_todo = True
        a["evento"].set()
        return True

    def _pedir_permiso(self, nombre: str, args: dict[str, Any], emitir: Callable[[dict], None]) -> bool:
        if es_lectura(nombre):
            return True
        if (self.config.auto or self.permitir_todo) and not es_destructiva(nombre):
            return True
        id_ = uuid.uuid4().hex[:8]
        a = {"evento": threading.Event(), "ok": False}
        self.aprobaciones[id_] = a
        emitir({"t": "aprobar", "id": id_, "nombre": nombre, "args": args, "destructiva": es_destructiva(nombre)})
        a["evento"].wait(ESPERA_APROBACION_S)
        self.aprobaciones.pop(id_, None)
        return bool(a["ok"])

    # --- una herramienta del modelo
    def _atender(self, bloque: Any, emitir: Callable[[dict], None]) -> tuple[str, bool]:
        nombre, entrada = bloque.name, bloque.input or {}
        if nombre in ("buscar_herramientas", "describir_herramienta", "estado_del_dibujo"):
            emitir({"t": "herramienta", "id": bloque.id, "nombre": nombre, "args": entrada})
            if nombre == "buscar_herramientas":
                texto = self.herr.buscar(entrada.get("texto", ""), entrada.get("categoria", ""), entrada.get("flujo", ""))
            elif nombre == "describir_herramienta":
                texto = self.herr.describir(entrada.get("nombre", ""))
            else:
                partes = []
                for t in ("get_drawing_info", "get_editor_state"):
                    try:
                        partes.append(self.herr.ejecutar(t, {}))
                    except Exception as e:                   # noqa: BLE001
                        partes.append(f"{t}: {e}")
                texto = "\n".join(partes)
            emitir({"t": "resultado", "id": bloque.id, "ok": True, "texto": _recortar(texto, 700)})
            return texto, False
        if nombre != "ejecutar_herramienta":
            return f"Herramienta desconocida: {nombre}", True
        real, args = entrada.get("nombre", ""), entrada.get("argumentos") or {}
        if not isinstance(args, dict):
            return "'argumentos' tiene que ser un objeto.", True
        if real == "run_code":
            return "run_code está apagado en el chat: usa las herramientas de oficio.", True
        if not self.herr.existe(real):
            return f"No existe la herramienta '{real}'. Usa buscar_herramientas.", True
        emitir({"t": "herramienta", "id": bloque.id, "nombre": real, "args": args})
        if not self._pedir_permiso(real, args, emitir):
            emitir({"t": "resultado", "id": bloque.id, "ok": False, "texto": "Rechazada por el usuario."})
            return "El usuario NO autorizó esta acción. No la repitas: pregúntale qué prefiere.", True
        try:
            texto = self.herr.ejecutar(real, args)
            ok = True
        except Exception as e:                               # noqa: BLE001
            texto, ok = f"Error de la herramienta: {e}", False
        emitir({"t": "resultado", "id": bloque.id, "ok": ok, "texto": _recortar(texto, 700)})
        return texto, not ok

    def _podar(self) -> None:
        """Si el historial crece demasiado, los resultados viejos de herramientas se reducen a una línea."""
        total = 0
        for m in reversed(self.mensajes):
            if isinstance(m["content"], list):
                for b in m["content"]:
                    if b.get("type") == "tool_result":
                        total += len(str(b["content"]))
                        if total > 120_000:
                            b["content"] = "[resultado anterior recortado para ahorrar contexto]"

    # --- el bucle
    def correr(self, texto: str, emitir: Callable[[dict], None]) -> None:
        if not self.ocupada.acquire(blocking=False):
            emitir({"t": "error", "d": "Todavía estoy trabajando en el mensaje anterior."})
            return
        try:
            self.parar.clear()
            clave = self.config.clave
            if not clave:
                emitir({"t": "error", "d": "Falta la clave de API. Ponla en Ajustes."})
                return
            cliente = self.crear_cliente(clave)
            self.mensajes.append({"role": "user", "content": texto})
            for _ in range(MAX_PASOS):
                if self.parar.is_set():
                    emitir({"t": "texto", "d": "\n(detenido)"})
                    break
                self._podar()
                try:
                    with cliente.messages.stream(
                            model=self.config.modelo, max_tokens=8192,
                            system=[{"type": "text", "text": SISTEMA, "cache_control": {"type": "ephemeral"}}],
                            tools=HERRAMIENTAS, messages=self.mensajes) as flujo:
                        for trozo in flujo.text_stream:
                            emitir({"t": "texto", "d": trozo})
                            if self.parar.is_set():
                                break
                        final = flujo.get_final_message()
                except Exception as e:                       # noqa: BLE001
                    emitir({"t": "error", "d": _error_amable(e)})
                    break
                uso = getattr(final, "usage", None)
                if uso:
                    self.tokens["entrada"] += getattr(uso, "input_tokens", 0) or 0
                    self.tokens["salida"] += getattr(uso, "output_tokens", 0) or 0
                    self.tokens["cache"] += getattr(uso, "cache_read_input_tokens", 0) or 0
                self.mensajes.append({"role": "assistant", "content": _bloques(final.content)})
                pedidos = [b for b in final.content if getattr(b, "type", None) == "tool_use"]
                if not pedidos:
                    if getattr(final, "stop_reason", "") == "max_tokens":
                        emitir({"t": "texto", "d": "\n(la respuesta se cortó por largo; pídeme que continúe)"})
                    break
                resultados = []
                for b in pedidos:
                    texto_r, es_error = self._atender(b, emitir)
                    resultados.append({"type": "tool_result", "tool_use_id": b.id, "content": _recortar(texto_r),
                                       "is_error": bool(es_error)})
                self.mensajes.append({"role": "user", "content": resultados})
            else:
                emitir({"t": "texto", "d": f"\n(me detuve tras {MAX_PASOS} pasos; dime si sigo)"})
            emitir({"t": "fin", "tokens": self.tokens})
        finally:
            self.ocupada.release()


# ---------------------------------------------------------------------------------------------- HTTP

class Aplicacion:
    def __init__(self, config: Config, herramientas: Herramientas, crear_cliente: Optional[Callable[[str], Any]] = None):
        self.config, self.herr, self.crear_cliente = config, herramientas, crear_cliente
        self.token = secrets.token_urlsafe(18)
        self.sesiones: dict[str, Sesion] = {}
        self.port = 0
        self.apagar = threading.Event()

    def sesion(self, id_: str = "") -> Sesion:
        if id_ and id_ in self.sesiones:
            return self.sesiones[id_]
        s = Sesion(self.config, self.herr, self.crear_cliente)
        self.sesiones[s.id] = s
        return s

    def pagina(self) -> bytes:
        with open(os.path.join(AQUI, "chat_ui", "index.html"), encoding="utf-8") as fh:
            return fh.read().replace("__TOKEN__", self.token).encode("utf-8")


def _manejador(app: Aplicacion) -> type:
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *_a: Any) -> None:             # silencio
            pass

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def _json(self, codigo: int, obj: Any) -> None:
            cuerpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(cuerpo)

        def _autorizado(self) -> bool:
            return self._host_ok() and secrets.compare_digest(self.headers.get("X-Chat-Token", ""), app.token)

        def do_GET(self) -> None:                            # noqa: N802
            if not self._host_ok():
                return self._json(403, {"error": "host"})
            ruta = self.path.split("?")[0]
            if ruta == "/api/ping":
                return self._json(200, {"ok": True})
            if ruta == "/":
                cuerpo = app.pagina()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(cuerpo)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(cuerpo)
                return
            if ruta == "/api/estado":
                if not self._autorizado():
                    return self._json(401, {"error": "token"})
                c = app.config
                return self._json(200, {"clave": bool(c.clave), "modelo": c.modelo, "auto": c.auto,
                                        "modelos": [{"id": i, "nombre": n} for i, n in MODELOS]})
            self._json(404, {"error": "no existe"})

        def do_POST(self) -> None:                           # noqa: N802
            if not self._autorizado():
                return self._json(401, {"error": "token"})
            largo = int(self.headers.get("Content-Length") or 0)
            try:
                datos = json.loads(self.rfile.read(largo) or b"{}")
            except ValueError:
                return self._json(400, {"error": "json"})
            ruta = self.path.split("?")[0]
            c = app.config
            if ruta == "/api/config":
                try:
                    if "clave" in datos:
                        c.poner_clave(datos["clave"])
                    if datos.get("modelo") in [m for m, _ in MODELOS]:
                        c.modelo = datos["modelo"]
                    if "auto" in datos:
                        c.auto = bool(datos["auto"])
                    c.guardar()
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                return self._json(200, {"clave": bool(c.clave), "modelo": c.modelo, "auto": c.auto})
            if ruta == "/api/aprobar":
                s = app.sesion(datos.get("sesion", ""))
                return self._json(200, {"ok": s.resolver(datos.get("id", ""), bool(datos.get("ok")), bool(datos.get("siempre")))})
            if ruta == "/api/parar":
                app.sesion(datos.get("sesion", "")).parar.set()
                for a in list(app.sesion(datos.get("sesion", "")).aprobaciones.values()):
                    a["evento"].set()
                return self._json(200, {"ok": True})
            if ruta == "/api/nueva":
                app.sesiones.clear()
                return self._json(200, {"sesion": app.sesion().id})
            if ruta == "/api/salir":
                app.apagar.set()
                return self._json(200, {"ok": True})
            if ruta == "/api/chat":
                s = app.sesion(datos.get("sesion", ""))
                texto = (datos.get("texto") or "").strip()
                if not texto:
                    return self._json(400, {"error": "mensaje vacío"})
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()

                def emitir(ev: dict) -> None:
                    ev = {**ev, "sesion": s.id}
                    try:
                        self.wfile.write(("data: " + json.dumps(ev, ensure_ascii=False) + "\n\n").encode("utf-8"))
                        self.wfile.flush()
                    except OSError:
                        s.parar.set()
                s.correr(texto, emitir)
                return
            self._json(404, {"error": "no existe"})
    return H


def _puerto_libre(preferido: int) -> int:
    for p in (preferido, 0):
        with socket.socket() as sk:
            try:
                sk.bind(("127.0.0.1", p))
                return sk.getsockname()[1]
            except OSError:
                continue
    return 0


def ya_hay_uno() -> Optional[str]:
    """La URL del chat que ya está corriendo, si responde."""
    try:
        with open(ARCHIVO_URL, encoding="utf-8") as fh:
            url = fh.read().strip()
        import urllib.request
        base = url.split("?")[0]
        with urllib.request.urlopen(base + "api/ping", timeout=1.0) as r:
            if r.status == 200:
                return url
    except Exception:                                        # noqa: BLE001
        return None
    return None


def _vigilar_autocad(app: Aplicacion) -> None:
    """Si AutoCAD se cierra (el plugin deja de contestar) el chat se apaga solo, para no dejar procesos sueltos."""
    fallas = 0
    while not app.apagar.wait(20):
        try:
            import autocad_client as acad
            with socket.create_connection(("127.0.0.1", acad.PORT), timeout=2):
                fallas = 0
        except OSError:
            fallas += 1
            if fallas >= 3:
                app.apagar.set()


def servir(demo: bool = False, vigilar: bool = True) -> int:
    existente = None if demo else ya_hay_uno()
    if existente:
        if sys.stdout:
            print(existente)
        return 0
    config = Config()
    crear = None
    if demo:
        import chat_prueba
        crear = chat_prueba.cliente_demo
        config._clave = "sk-ant-demo"
    app = Aplicacion(config, Herramientas(), crear)
    puerto = _puerto_libre(8790)
    httpd = ThreadingHTTPServer(("127.0.0.1", puerto), _manejador(app))
    httpd.daemon_threads = True
    app.port = httpd.server_address[1]
    url = f"http://127.0.0.1:{app.port}/"
    os.makedirs(ESTADO, exist_ok=True)
    if not demo:        # el modo demostración no se anuncia: el comando MCPCHAT nunca debe abrir el de mentira
        with open(ARCHIVO_URL, "w", encoding="utf-8") as fh:
            fh.write(url)
        with open(ARCHIVO_LANZADOR, "w", encoding="utf-8") as fh:
            json.dump({"python": sys.executable, "script": os.path.abspath(__file__), "cwd": AQUI}, fh)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    threading.Thread(target=lambda: app.herr.existe("ping"), daemon=True).start()     # precarga: el primer mensaje no espera ~8 s
    if vigilar:
        threading.Thread(target=_vigilar_autocad, args=(app,), daemon=True).start()
    if sys.stdout:                                          # con pythonw no hay consola
        print(url, flush=True)
    app.apagar.wait()
    httpd.shutdown()
    if not demo:
        try:
            os.remove(ARCHIVO_URL)
        except OSError:
            pass
    return 0


def registrar() -> None:
    """Deja anotado dónde está Python y este script, para que el comando MCPCHAT pueda arrancar el servidor solo."""
    os.makedirs(ESTADO, exist_ok=True)
    with open(ARCHIVO_LANZADOR, "w", encoding="utf-8") as fh:
        json.dump({"python": sys.executable, "script": os.path.abspath(__file__), "cwd": AQUI}, fh)
    print("Registrado en " + ARCHIVO_LANZADOR)


if __name__ == "__main__":
    if "--registrar" in sys.argv:
        registrar()
        sys.exit(0)
    sys.exit(servir(demo="--demo" in sys.argv, vigilar="--sin-vigilar" not in sys.argv))
