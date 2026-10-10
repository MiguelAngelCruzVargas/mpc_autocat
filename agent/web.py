"""Interfaz web local: configurar el modelo y dibujar, sin tocar la consola.

Es un servidor HTTP que corre en tu máquina y se abre en el navegador. Se
eligió web y no Tkinter por dos razones: se ve como una aplicación de hoy
(CSS moderno, tipografía decente, animaciones) y no agrega ni una
dependencia — `http.server` viene con Python.

Nada sale de esta computadora salvo las llamadas al proveedor de IA que
elijas. El servidor escucha SOLO en 127.0.0.1.
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import socket
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from . import credenciales, providers
from .cli import ENTREGABLES, PERFILES, _system_prompt
from .loop import conversar
from .mcp_link import ConexionMcp, SERVIDOR_DEFECTO

_AQUI = os.path.dirname(os.path.abspath(__file__))
_MCP_DIR = os.path.join(os.path.dirname(_AQUI), "mcp_server")


def _estandar_mod() -> Any:
    """estandar.py vive con el servidor MCP (lo usa check_all): se importa
    de ahí para que el panel valide y guarde con las MISMAS reglas."""
    import sys
    if _MCP_DIR not in sys.path:
        sys.path.insert(0, _MCP_DIR)
    import estandar
    return estandar
_WEB_DIR = os.path.join(_AQUI, "web")
_HTML = os.path.join(_WEB_DIR, "index.html")


class Sesion:
    """La conversación en curso. Una sola: esto es una app local.

    Se guarda en disco después de cada vuelta: antes vivía solo en memoria,
    así que recargar la página dejaba el chat en blanco (aunque el agente
    siguiera recordando todo) y apagar el panel perdía la conversación
    entera. 'eventos' es lo que se vio en pantalla, para reconstruirla tal
    cual; 'mensajes' es el contexto del modelo, para seguir donde quedó.
    """

    ARCHIVO = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                           "AutoCadMcp", "conversacion.json")
    MAX_EVENTOS = 600

    def __init__(self) -> None:
        self.mensajes: list[dict[str, Any]] = []
        self.eventos: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.cancelar = threading.Event()
        # Un chat por vez: dos pestañas mandando a la vez mezclaban sus
        # mensajes en la misma conversación del modelo.
        self.ocupada = threading.Lock()
        self._cargar()

    def reiniciar(self, system: str) -> None:
        self.mensajes = [{"role": "system", "content": system}]

    def borrar(self) -> None:
        with self.lock:
            self.mensajes, self.eventos = [], []
        try:
            os.remove(self.ARCHIVO)
        except OSError:
            pass

    def anotar(self, evento: dict[str, Any]) -> None:
        if evento.get("tipo") in ("usuario", "texto", "tool", "resultado", "aviso"):
            # Lo que la pantalla muestra de una tool son ~200 caracteres:
            # guardar el resultado entero (listas de handles, rooms...)
            # inflaba el archivo sin que nadie lo fuera a ver.
            if evento.get("tipo") == "resultado":
                evento = {**evento, "texto": str(evento.get("texto", ""))[:400]}
            if evento.get("tipo") == "tool":
                args = json.dumps(evento.get("args"), ensure_ascii=False)
                if len(args) > 400:
                    evento = {**evento, "args": args[:397] + "…"}
            with self.lock:
                self.eventos.append(evento)
                del self.eventos[:-self.MAX_EVENTOS]

    def guardar(self) -> None:
        def sin_imagenes(m: dict[str, Any]) -> dict[str, Any]:
            # Las imágenes van en base64 (megas): al disco va solo el texto.
            if isinstance(m.get("content"), list):
                partes = [b.get("text", "") for b in m["content"]
                          if isinstance(b, dict) and b.get("type") == "text"]
                return {**m, "content": " ".join(partes) + " [imagen adjunta]"}
            return m
        try:
            os.makedirs(os.path.dirname(self.ARCHIVO), exist_ok=True)
            with self.lock:
                datos = {"mensajes": [sin_imagenes(m) for m in self.mensajes],
                         "eventos": self.eventos}
            tmp = self.ARCHIVO + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(datos, fh, ensure_ascii=False)
            os.replace(tmp, self.ARCHIVO)
        except (OSError, TypeError, ValueError):
            pass        # el historial es una comodidad: no tumba el chat

    def _cargar(self) -> None:
        try:
            with open(self.ARCHIVO, encoding="utf-8") as fh:
                datos = json.load(fh)
            self.mensajes = list(datos.get("mensajes") or [])
            self.eventos = list(datos.get("eventos") or [])
        except (OSError, ValueError):
            pass


SESION = Sesion()

# Dónde se dejan las capturas del plano que se muestran en la interfaz.
# En temp y no en el repo: son de una corrida, igual que las de test_live.
CAPTURAS = os.path.join(os.environ.get("TEMP", "."), "autocad_mcp_ui")

# Cuántas tools ofrece cada perfil DE VERDAD. Los perfiles se definen por
# prefijos ("create_", "check_"), así que contar la lista da el número de
# patrones y no de herramientas: la interfaz decía "Arquitectura (29
# tools)" cuando en realidad ofrecía 48. Se resuelve una vez contra el
# catálogo real y se cachea — abrir el servidor MCP en cada request para
# esto sería absurdo.
_CONTEO: dict[str, int] = {}


# ---------------------------------------------------------- estado del plugin

# Mismo puerto que usa mcp_server/autocad_client.py, para no depender de
# él: ese módulo asume que corre desde su propia carpeta (importa 'session'
# por nombre pelado) y traerlo acá solo para un chequeo de conectividad
# complica más de lo que ahorra. Es la misma lógica, duplicada a propósito.
_ACAD_HOST = os.environ.get("ACAD_MCP_HOST", "127.0.0.1")
_ACAD_PORT_FILE = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AutoCadMcp", "port")


def _puerto_plugin() -> int:
    explicito = os.environ.get("ACAD_MCP_PORT")
    if explicito:
        return int(explicito)
    try:
        with open(_ACAD_PORT_FILE, encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return 8765


def _verificar_autocad(timeout: float = 1.5) -> dict[str, Any]:
    """Chequeo rápido e independiente del bucle del agente.

    Antes la única forma de saber si AutoCAD estaba conectado era pedirle
    algo al modelo y esperar: si el perfil de tools no incluía 'ping' (le
    faltaba a arquitectura/civil/estructura — ver PERFILES en cli.py, ya
    corregido) el modelo ni sabía que existía esa pregunta, y si el pedido
    SÍ llegaba a intentar dibujar, tardaba 30+ segundos en fallar. Esto
    contesta en ~1.5s como mucho, sin gastar un solo token, y la interfaz
    lo consulta sola cada 15s (ver actualizarEstadoAutoCAD en app.js).
    """
    puerto = _puerto_plugin()
    try:
        with socket.create_connection((_ACAD_HOST, puerto), timeout=timeout) as sock:
            pedido = json.dumps({"id": "estado-ui", "cmd": "ping", "params": {}})
            sock.sendall(pedido.encode("utf-8") + b"\n")
            sock.settimeout(timeout)
            buffer = b""
            while not buffer.endswith(b"\n"):
                trozo = sock.recv(4096)
                if not trozo:
                    break
                buffer += trozo
    except (OSError, socket.timeout):
        return {"conectado": False,
                "detalle": f"No se pudo conectar en {_ACAD_HOST}:{puerto}."}

    if not buffer:
        return {"conectado": False,
                "detalle": "El plugin cerró la conexión sin responder."}
    try:
        respuesta = json.loads(buffer.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"conectado": False, "detalle": "Respuesta del plugin ilegible."}

    if not respuesta.get("ok"):
        return {"conectado": False,
                "detalle": respuesta.get("error", "Error desconocido en el plugin.")}
    return {"conectado": True, **(respuesta.get("result") or {})}


def _contar_perfiles() -> dict[str, int]:
    if _CONTEO:
        return _CONTEO

    async def trabajo(mcp: ConexionMcp) -> dict[str, int]:
        return {p: len(mcp.catalogo(incluir=pats or None))
                for p, pats in PERFILES.items()}

    try:
        _CONTEO.update(MOTOR.usar(trabajo))
    except Exception:                                   # noqa: BLE001
        # Sin servidor MCP la interfaz tiene que abrir igual: se cae al
        # número de patrones, que es aproximado pero no rompe nada.
        _CONTEO.update({p: len(v) for p, v in PERFILES.items() if v})
    return _CONTEO


class Motor:
    """El servidor MCP, levantado UNA vez y compartido por todos los requests.

    Antes cada request abría el suyo con `async with ConexionMcp(...)`, y eso
    son 2.78 s de arranque de subproceso Python ANTES de la primera tool
    (medido). En la captura del visor era casi un tercio de los ~10 s que
    tardaba en aparecer la imagen — y todo ese rato el panel se ve blanco,
    que es lo que hacía pensar que el visor estaba roto.

    Vive en su propio hilo con su propio event loop, porque `http.server` es
    síncrono y la librería MCP no tolera que sus cancel scopes se abran en un
    task y se cierren en otro: un solo loop, siempre el mismo, evita el
    "Attempted to exit cancel scope in a different task".

    Si el subproceso se muere, el hilo termina y el siguiente request lo
    vuelve a levantar solo.
    """

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._mcp: Optional[ConexionMcp] = None
        self._apagar: Optional[asyncio.Event] = None
        self._listo = threading.Event()
        self._error: Optional[BaseException] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------ ciclo de vida

    def _vivir(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def sesion() -> None:
            apagar = asyncio.Event()
            try:
                async with ConexionMcp(servidor=SERVIDOR_DEFECTO) as mcp:
                    self._mcp, self._loop, self._apagar = mcp, loop, apagar
                    self._error = None
                    self._listo.set()
                    await apagar.wait()
            except BaseException as exc:                # noqa: BLE001
                self._error = exc
                self._listo.set()

        try:
            loop.run_until_complete(sesion())
        finally:
            self._mcp = None
            self._loop = None
            self._apagar = None
            loop.close()

    def _conexion(self) -> tuple[ConexionMcp, asyncio.AbstractEventLoop]:
        with self._lock:
            mcp, loop = self._mcp, self._loop
            if mcp is not None and loop is not None and not loop.is_closed():
                return mcp, loop
            self._listo.clear()
            self._error = None
            threading.Thread(target=self._vivir, name="mcp",
                             daemon=True).start()
            if not self._listo.wait(timeout=120):
                raise RuntimeError("El servidor MCP no respondió al arrancar.")
            mcp, loop = self._mcp, self._loop
            if mcp is None or loop is None:
                raise RuntimeError(
                    "No se pudo levantar el servidor MCP"
                    + (f": {self._error}" if self._error else "."))
            return mcp, loop

    # ------------------------------------------------------------- uso

    def usar(self, trabajo: Any) -> Any:
        """Corre `await trabajo(mcp)` en el hilo del motor y espera."""
        mcp, loop = self._conexion()
        return asyncio.run_coroutine_threadsafe(trabajo(mcp), loop).result()

    def precalentar(self) -> None:
        """Levanta el MCP de fondo, para que la PRIMERA captura no lo pague."""
        threading.Thread(target=self._precalentar, daemon=True).start()

    def _precalentar(self) -> None:
        try:
            _contar_perfiles()
        except Exception:                               # noqa: BLE001
            pass        # sin AutoCAD/MCP la interfaz igual tiene que abrir


MOTOR = Motor()


class CapturaUnica:
    """Un plot por vez, y los pedidos iguales que lleguen mientras tanto se
    cuelgan del que ya corre en vez de encolar otro.

    Pasó de verdad: con el visor tardando, se toca "Actualizar" dos o tres
    veces, cada clic es un request nuevo y cada request era un plot nuevo.
    AutoCAD los sirve de a uno, así que el tercero esperaba a los dos
    anteriores — 12 plots seguidos en plot.log, ~40 s cada uno, y un visor
    que parecía muerto. Ahora el segundo clic con los mismos parámetros
    recibe la MISMA foto que el primero, apenas termina.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._en_curso: dict[str, tuple[threading.Event, dict[str, Any]]] = {}

    def correr(self, clave: str, fabrica: Any) -> Any:
        with self._lock:
            espera = self._en_curso.get(clave)
            if espera is None:
                listo: threading.Event = threading.Event()
                caja: dict[str, Any] = {}
                self._en_curso[clave] = (listo, caja)
                titular = True
            else:
                listo, caja = espera
                titular = False

        if not titular:
            listo.wait()
            if "error" in caja:
                raise caja["error"]
            return caja["valor"]

        try:
            caja["valor"] = fabrica()
            return caja["valor"]
        except BaseException as exc:                    # noqa: BLE001
            caja["error"] = exc
            raise
        finally:
            with self._lock:
                self._en_curso.pop(clave, None)
            listo.set()


CAPTURA_UNICA = CapturaUnica()


def _listar_entregables() -> list[dict[str, Any]]:
    """Lo que el agente dejó para descargar, lo más nuevo primero."""
    try:
        nombres = os.listdir(ENTREGABLES)
    except OSError:
        return []
    archivos = []
    for n in nombres:
        ruta = os.path.join(ENTREGABLES, n)
        if n.startswith(".") or not os.path.isfile(ruta):
            continue
        st = os.stat(ruta)
        archivos.append({"nombre": n, "bytes": st.st_size, "mtime": st.st_mtime})
    return sorted(archivos, key=lambda a: -a["mtime"])


def pedido_confiable(headers: Any, puerto: int, escribe: bool) -> bool:
    """¿El pedido viene de la propia interfaz y no de otra página?

    Escuchar solo en 127.0.0.1 no alcanza: cualquier página que el usuario
    tenga abierta en el navegador puede hacer un fetch a 127.0.0.1:8770, y
    un POST con text/plain ni siquiera pasa por el preflight de CORS. Sin
    esto, una página ajena le mandaba instrucciones al agente: gastaba la
    API key del usuario y dibujaba —o borraba— en su AutoCAD.

    - Host: tiene que ser el nuestro. Un dominio ajeno que resuelve a
      127.0.0.1 (DNS rebinding) llega con SU nombre en Host.
    - Origin / Sec-Fetch-Site: el navegador los pone solo y una página no
      los puede falsificar. Si vienen, tienen que ser de acá. Si no vienen
      es un cliente sin navegador (curl, un test): ese ya corre como el
      usuario, no hay nada que proteger de él.
    """
    propios = {f"127.0.0.1:{puerto}", f"localhost:{puerto}"}
    if str(headers.get("Host") or "").lower() not in propios:
        return False
    if not escribe:
        return True
    origen = headers.get("Origin")
    if origen is not None and str(origen).lower() not in {
            f"http://{h}" for h in propios}:
        return False
    if str(headers.get("Sec-Fetch-Site") or "").lower() == "cross-site":
        return False
    return True


class Handler(BaseHTTPRequestHandler):
    server_version = "AutoCadMcpUI"

    # El log de cada request ensucia la consola sin aportar nada.
    def log_message(self, formato: str, *args: Any) -> None:
        pass

    # ------------------------------------------------------------ helpers

    def _json(self, datos: Any, codigo: int = 200) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _leer_json(self) -> dict[str, Any]:
        largo = int(self.headers.get("Content-Length") or 0)
        if not largo:
            return {}
        try:
            return json.loads(self.rfile.read(largo).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # ------------------------------------------------------------ GET

    def _servir_entregable(self, nombre: str) -> None:
        # Solo un nombre de archivo de ESA carpeta: nada de rutas, así una
        # página no puede pedir ../../ y leer cualquier archivo del disco.
        nombre = urllib.parse.unquote(nombre)
        if (not nombre or nombre != os.path.basename(nombre)
                or nombre.startswith(".") or "\\" in nombre):
            self.send_error(404)
            return
        try:
            with open(os.path.join(ENTREGABLES, nombre), "rb") as fh:
                cuerpo = fh.read()
        except OSError:
            self.send_error(404)
            return
        tipo = mimetypes.guess_type(nombre)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Disposition",
                         "attachment; filename*=UTF-8''" + urllib.parse.quote(nombre))
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(cuerpo)

    def _rechazar_ajeno(self, escribe: bool) -> bool:
        if pedido_confiable(self.headers, self.server.server_address[1],
                            escribe):
            return False
        self._json({"error": "Pedido rechazado: no viene de la interfaz "
                             "de AutoCAD-IA."}, 403)
        return True

    def do_GET(self) -> None:                          # noqa: N802
        # Los GET no cambian nada, pero /api/estado y la captura del plano
        # tampoco son para que los lea otra página: alcanza con el Host.
        if self._rechazar_ajeno(escribe=False):
            return
        # Rutas de la API y capturas
        if self.path.startswith("/vista.png"):
            ruta = os.path.join(CAPTURAS, "vista.png")
            try:
                with open(ruta, "rb") as fh:
                    cuerpo = fh.read()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
            return

        if self.path == "/api/ping":
            # Liviano a propósito: no toca el MCP ni AutoCAD. Lo usa un
            # segundo arranque para saber si el puerto lo tiene este panel.
            self._json({"app": "autocad-ia"})
            return

        if self.path == "/api/historial":
            with SESION.lock:
                self._json({"eventos": list(SESION.eventos)})
            return

        if self.path == "/api/estandar":
            est = _estandar_mod()
            try:
                datos = est.cargar()
                error = None
            except ValueError as exc:
                datos, error = est.MINIMO, str(exc)
            self._json({"estandar": datos, "archivo": est.ARCHIVO,
                        "existe": os.path.exists(est.ARCHIVO), "error": error})
            return

        if self.path == "/api/layouts":
            self._layouts()
            return

        if self.path == "/api/entregables":
            self._json({"carpeta": ENTREGABLES,
                        "archivos": _listar_entregables()})
            return

        if self.path.startswith("/entregables/"):
            self._servir_entregable(self.path[len("/entregables/"):])
            return

        if self.path == "/api/autocad_estado":
            self._json(_verificar_autocad())
            return

        if self.path == "/api/estado":
            guardadas = {f["proveedor"]: f for f in credenciales.listar()}
            conteo = _contar_perfiles()
            self._json({
                "proveedores": [
                    {"id": nombre,
                     "modeloSugerido": preset.get("modelo", ""),
                     "variable": preset.get("env", ""),
                     "clave": guardadas.get(nombre, {}).get("clave"),
                     "proteccion": guardadas.get(nombre, {}).get("proteccion")}
                    for nombre, preset in sorted(providers.PRESETS.items())],
                "perfiles": [
                    {"id": p, "tools": conteo.get(p, len(v) if v else 0)}
                    for p, v in PERFILES.items()],
                "archivoClaves": credenciales.ARCHIVO,
                # Los ajustes viajan con el estado: la interfaz los aplica
                # al arrancar sin depender del localStorage del navegador,
                # que se pierde al cambiar el puerto del servidor.
                "preferencias": credenciales.leer_preferencias(),
            })
            return

        # Archivos estáticos en agent/web/
        ruta_rel = self.path.split("?")[0].lstrip("/")
        if ruta_rel in ("", "index.html"):
            ruta_rel = "index.html"

        ruta_archivo = os.path.normpath(os.path.join(_WEB_DIR, ruta_rel))
        # Prevenir path traversal fuera de _WEB_DIR
        if os.path.commonpath([_WEB_DIR, ruta_archivo]) == _WEB_DIR and os.path.isfile(ruta_archivo):
            mimes = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".ico": "image/x-icon",
            }
            _, ext = os.path.splitext(ruta_archivo)
            mime = mimes.get(ext.lower(), "application/octet-stream")

            try:
                with open(ruta_archivo, "rb") as fh:
                    cuerpo = fh.read()
            except OSError:
                self.send_error(500, f"Error leyendo {ruta_rel}")
                return

            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)
            return

        self.send_error(404)

    # ------------------------------------------------------------ POST

    def do_POST(self) -> None:                         # noqa: N802
        if self._rechazar_ajeno(escribe=True):
            return
        datos = self._leer_json()

        if self.path == "/api/clave":
            proveedor = str(datos.get("proveedor", ""))
            clave = str(datos.get("clave", ""))
            if not proveedor:
                self._json({"error": "Falta el proveedor."}, 400)
                return
            if datos.get("borrar"):
                credenciales.borrar(proveedor)
                self._json({"ok": True, "borrada": True})
                return
            try:
                modo = credenciales.guardar(proveedor, clave)
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            self._json({"ok": True, "proteccion": modo,
                        "clave": credenciales.enmascarar(clave.strip())})
            return

        if self.path == "/api/preferencias":
            self._json({"ok": True,
                        "preferencias": credenciales.guardar_preferencias(
                            datos.get("preferencias") or datos)})
            return

        if self.path == "/api/vision":
            # ¿El modelo elegido puede MIRAR una imagen? La interfaz lo
            # usa para habilitar o no el adjuntar, y para decir por qué.
            modelo = str(datos.get("modelo", ""))
            if str(datos.get("proveedor", "")) == "openrouter":
                providers.catalogo_openrouter()
            puede = providers.soporta_imagenes(modelo)
            self._json({
                "modelo": modelo,
                "soportaImagenes": puede,
                "motivo": ("" if puede else
                           f"'{modelo}' es un modelo de solo texto: no puede "
                           "ver imágenes. Si le adjuntas un croquis, o lo "
                           "ignora en silencio o rechaza el pedido entero. "
                           "Para trabajar con imágenes elige uno marcado con "
                           "📷 en la lista de modelos (botón Listar)."),
            })
            return

        if self.path == "/api/modelos":
            try:
                filas = providers.modelos_disponibles(
                    str(datos.get("proveedor", "")),
                    url=datos.get("url") or None,
                    probar=bool(datos.get("probar")))
            except providers.ErrorProveedor as exc:
                self._json({"error": str(exc)}, 400)
                return
            self._json({"modelos": filas})
            return

        if self.path == "/api/reset":
            SESION.borrar()
            self._json({"ok": True})
            return

        if self.path == "/api/estandar":
            est = _estandar_mod()
            try:
                ruta = est.guardar(datos.get("estandar"))
            except (ValueError, OSError) as exc:
                self._json({"error": str(exc)}, 400)
                return
            self._json({"ok": True, "archivo": ruta})
            return

        if self.path == "/api/revisar":
            self._revisar()
            return

        if self.path == "/api/cancelar":
            SESION.cancelar.set()
            self._json({"ok": True})
            return

        if self.path == "/api/apagar":
            # Sin consola visible (lanzado con pythonw), este es el único
            # botón de apagado que le queda al usuario — antes era cerrar
            # la ventana negra.
            self._json({"ok": True, "mensaje": "Apagando…"})
            threading.Thread(target=_apagar_en_hilo_aparte, daemon=True).start()
            return

        if self.path == "/api/captura":
            self._captura(datos)
            return

        if self.path == "/api/chat":
            self._chat(datos)
            return

        self.send_error(404)

    # --------------------------------------------------------- captura

    def _captura(self, datos: dict[str, Any]) -> None:
        """Foto del dibujo, para verlo sin cambiar de ventana.

        Es la diferencia entre confiar en que el agente dibujó bien y
        mirarlo. Con zona (min/max) se puede acercar a un detalle, que es
        donde aparecen los defectos que a la extensión completa no se ven.
        """
        os.makedirs(CAPTURAS, exist_ok=True)
        destino = os.path.join(CAPTURAS, "vista.png")
        zona = datos.get("zona") or {}
        # Una lámina (layout) se captura entera, como va a imprimirse: es el
        # entregable, y antes el visor solo mostraba el espacio modelo.
        lamina = str(datos.get("layout") or "").strip()
        if lamina.lower() in ("model", "modelo"):
            lamina = ""
        params: dict[str, Any] = {"path": destino, "layout": lamina or None}
        if all(k in zona for k in ("minX", "minY", "maxX", "maxY")):
            params.update({k: float(zona[k]) for k in
                           ("minX", "minY", "maxX", "maxY")})

        async def trabajo(mcp: ConexionMcp) -> dict[str, Any]:
            if not zona and not lamina:
                await mcp.ejecutar("zoom_extents", {})
            salida, error = await mcp.ejecutar("capture_viewport", params)
            extension = None
            if not lamina:
                extension, _ = await mcp.ejecutar("get_extents", {})
            return {"error": error, "salida": salida,
                    "extension": extension}

        try:
            r = CAPTURA_UNICA.correr(json.dumps(params, sort_keys=True),
                                     lambda: MOTOR.usar(trabajo))
        except Exception as exc:                        # noqa: BLE001
            self._json({"error": f"No se pudo capturar: {exc}"}, 500)
            return
        if r["error"] or not os.path.exists(destino):
            self._json({"error": r["salida"]}, 400)
            return

        try:
            extension = json.loads(r["extension"])
        except (ValueError, TypeError):
            extension = None
        # La marca de tiempo fuerza al navegador a recargar la imagen en
        # vez de mostrar la anterior de su caché.
        self._json({"ok": True, "url": f"/vista.png?t={os.path.getmtime(destino)}",
                    "extension": extension})

    # ----------------------------------------------- láminas y revisión

    def _herramienta(self, nombre: str, args: dict[str, Any]) -> Any:
        """Corre UNA tool del servidor MCP directo, sin pasar por el modelo:
        no gasta tokens y contesta en segundos."""
        async def trabajo(mcp: ConexionMcp) -> tuple[str, bool]:
            return await mcp.ejecutar(nombre, args)
        salida, error = MOTOR.usar(trabajo)
        if error:
            raise RuntimeError(salida)
        try:
            return json.loads(salida)
        except (ValueError, TypeError):
            return salida

    def _sin_autocad(self) -> bool:
        """Con AutoCAD cerrado la tool tarda ~13 s en rendirse (reintentos
        de conexión): el ping directo lo sabe en 1.5 s."""
        estado = _verificar_autocad()
        if estado.get("conectado"):
            return False
        self._json({"error": "AutoCAD no está conectado: "
                             + str(estado.get("detalle", ""))}, 503)
        return True

    def _layouts(self) -> None:
        if self._sin_autocad():
            return
        try:
            r = self._herramienta("list_layouts", {})
        except Exception as exc:                        # noqa: BLE001
            self._json({"error": f"No se pudieron leer las láminas: {exc}"}, 500)
            return
        filas = r.get("layouts", []) if isinstance(r, dict) else []
        nombres = [f.get("name") for f in filas
                   if f.get("name") and f.get("name") != "Model"]
        self._json({"layouts": nombres})

    def _revisar(self) -> None:
        """check_all sin el modelo: el semáforo del plano en un clic."""
        if self._sin_autocad():
            return
        try:
            r = self._herramienta("check_all", {})
        except Exception as exc:                        # noqa: BLE001
            self._json({"error": f"No se pudo revisar el plano: {exc}"}, 500)
            return
        if not isinstance(r, dict):
            self._json({"error": str(r)}, 500)
            return
        self._json({"ok": r.get("ok"), "count": r.get("count", 0),
                    "problems": r.get("problems", [])[:60],
                    "checks": sorted((r.get("checks") or {}).keys()),
                    "skipped": r.get("skipped", [])})

    # ------------------------------------------------------------ chat

    def _chat(self, datos: dict[str, Any]) -> None:
        """Corre una vuelta del agente y emite los eventos por SSE.

        Server-Sent Events y no una respuesta al final: un plano son
        decenas de llamadas y minutos de trabajo. Ver cada tool a medida
        que pasa es la diferencia entre acompañar al agente y mirar una
        pantalla congelada preguntándose si se colgó.
        """
        pedido = str(datos.get("mensaje", "")).strip()
        imagenes = [i for i in (datos.get("imagenes") or [])
                    if isinstance(i, str) and i.startswith("data:image/")]
        if not pedido and not imagenes:
            self._json({"error": "El mensaje está vacío."}, 400)
            return

        try:
            proveedor = providers.construir(
                str(datos.get("proveedor", "openrouter")),
                modelo=datos.get("modelo") or None,
                url=datos.get("url") or None,
                temperatura=datos.get("temperatura"))
        except providers.ErrorProveedor as exc:
            self._json({"error": str(exc)}, 400)
            return

        # Se corta ACÁ y no se manda: un modelo de solo texto con una
        # imagen adjunta o la ignora sin decir nada -- y entonces contesta
        # sobre algo que no vio -- o devuelve un 400 incomprensible.
        if imagenes and str(datos.get("proveedor", "")) == "openrouter":
            providers.catalogo_openrouter()
        if imagenes and not providers.soporta_imagenes(proveedor.modelo):
            self._json({"error":
                        f"'{proveedor.modelo}' no puede ver imágenes. "
                        "Elige uno marcado con 📷 en la lista de modelos "
                        "o manda el pedido sin adjuntos."},
                       400)
            return

        perfil = str(datos.get("perfil", "arquitectura"))
        incluir = PERFILES.get(perfil)
        if incluir is None:
            self._json({"error": f"Perfil desconocido: {perfil}"}, 400)
            return

        if not SESION.ocupada.acquire(blocking=False):
            self._json({"error": "Ya hay un pedido en curso (¿otra pestaña "
                                 "abierta?). Espera a que termine o "
                                 "cancélalo."}, 409)
            return
        try:
            self._chat_en_curso(datos, pedido, imagenes, proveedor, incluir)
        finally:
            SESION.ocupada.release()
            SESION.guardar()

    def _chat_en_curso(self, datos: dict[str, Any], pedido: str,
                       imagenes: list[str], proveedor: Any,
                       incluir: Any) -> None:
        SESION.anotar({"tipo": "usuario", "texto": pedido,
                       "imagenes": len(imagenes)})
        # Costo en vivo: precio que puso el usuario para este modelo, o el
        # que publica el proveedor. Con tope, la corrida se detiene sola al
        # pasarlo -- un plano son decenas de vueltas y un modelo caro con el
        # perfil 'todo' se come el presupuesto sin que nadie lo note.
        precio = _precio_manual(datos) or providers.precio_de(
            str(datos.get("proveedor", "")), proveedor.modelo)
        try:
            tope = float(datos.get("topeUSD") or 0)
        except (TypeError, ValueError):
            tope = 0.0
        topado = {"ya": False}
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        # NO "keep-alive": esta respuesta no manda Content-Length ni va
        # chunked (se escribe evento a evento a medida que el agente
        # trabaja), así que la única forma en que un cliente HTTP sabe
        # dónde termina el cuerpo es viendo que el socket se cierra. Decir
        # "keep-alive" sin eso es mentirle al cliente: curl y el navegador
        # se quedan esperando para siempre después del último evento —
        # confirmado en vivo, con AutoCAD real conectado: el chat quedaba
        # con "Agente procesando…" y Enviar bloqueado hasta refrescar la
        # página, aunque la respuesta ya estuviera completa y renderizada.
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()

        def emitir(tipo: str, cuerpo: dict) -> None:
            if tipo == "uso":
                costo = providers.costo_usd(cuerpo, precio)
                if costo is not None:
                    cuerpo = {**cuerpo, "costoUSD": round(costo, 5)}
                    if tope > 0 and costo >= tope and not topado["ya"]:
                        topado["ya"] = True
                        SESION.cancelar.set()
                        emitir("aviso", {"texto": (
                            f"Se alcanzó el tope de US${tope:g} por pedido "
                            f"(van US${costo:.4f}): la corrida se detiene "
                            "al terminar esta vuelta. Lo dibujado se queda; "
                            "sube el tope en el panel si hace falta seguir.")})
            SESION.anotar({"tipo": tipo, **cuerpo})
            try:
                paquete = json.dumps({"tipo": tipo, **cuerpo},
                                     ensure_ascii=False)
                self.wfile.write(f"data: {paquete}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ValueError):
                pass        # el navegador cerró la pestaña; no es un error

        async def trabajo(mcp: ConexionMcp) -> None:
            tools = mcp.catalogo(
                incluir=incluir or None,
                limite_descripcion=int(datos.get("limiteDescripcion") or 0))
            emitir("inicio", {"tools": len(tools),
                              "modelo": proveedor.modelo})
            with SESION.lock:
                if not SESION.mensajes:
                    sistema = _system_prompt(
                        bool(datos.get("conReglas", True)),
                        int(datos.get("limiteReglas") or 0))
                    # El contexto fijo del preset (formato, escala,
                    # reglamento...) entra una vez, al empezar la sesión.
                    contexto = str(datos.get("contexto") or "").strip()[:2000]
                    if contexto:
                        sistema += ("\n\n--- Contexto fijo de este proyecto "
                                    "(lo definió la persona) ---\n" + contexto)
                    SESION.reiniciar(sistema)
                if imagenes:
                    formato = getattr(proveedor, "formato", "openai")
                    bloques: list[dict[str, Any]] = [
                        {"type": "text",
                         "text": pedido or "Mira esta imagen."}]
                    bloques += [providers.bloque_imagen(i, formato)
                                for i in imagenes]
                    SESION.mensajes.append({"role": "user",
                                            "content": bloques})
                else:
                    SESION.mensajes.append({"role": "user",
                                            "content": pedido})
                mensajes = SESION.mensajes
            await conversar(mcp, proveedor, mensajes, tools,
                            lambda t, d: emitir(t, d),
                            vueltas_max=int(datos.get("vueltas") or 40),
                            cancelado=SESION.cancelar.is_set)

        SESION.cancelar.clear()
        try:
            MOTOR.usar(trabajo)
        except Exception as exc:                        # noqa: BLE001
            emitir("aviso", {"texto": f"Se cortó la corrida: {exc}"})
        emitir("fin", {})


_SERVIDOR: Optional[ThreadingHTTPServer] = None


class _ServidorExclusivo(ThreadingHTTPServer):
    """Un puerto, un panel. HTTPServer trae allow_reuse_address=True y en
    Windows eso es SO_REUSEADDR: un SEGUNDO panel se enlazaba al mismo
    puerto sin error y los pedidos caían en uno u otro al azar (visto en
    prueba: el segundo arranque se quedaba escuchando en vez de detectar
    al primero)."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET,
                                   socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _apagar_en_hilo_aparte() -> None:
    """servidor.shutdown() bloquea hasta que serve_forever() para — llamarlo
    desde el mismo hilo que está corriendo serve_forever() (el del pedido
    HTTP que llega a /api/apagar) se queda esperando a sí mismo para
    siempre. Por eso corre en un hilo aparte, con un respiro corto para que
    la respuesta HTTP de "apagando" le alcance a llegar al navegador antes.
    """
    import time
    time.sleep(0.3)
    if _SERVIDOR is not None:
        _SERVIDOR.shutdown()


def _precio_manual(datos: dict[str, Any]) -> Optional[dict[str, float]]:
    p = datos.get("precio")
    if not isinstance(p, dict):
        return None
    try:
        entrada, salida = float(p.get("entrada") or 0), float(p.get("salida") or 0)
    except (TypeError, ValueError):
        return None
    if entrada <= 0 and salida <= 0:
        return None
    return {"entrada": entrada, "salida": salida}


def _es_este_panel(puerto: int) -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/ping",
                                    timeout=3) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == "autocad-ia"
    except Exception:                                   # noqa: BLE001
        return False


def iniciar(puerto: int = 8770, abrir: bool = True) -> None:
    global _SERVIDOR
    # 127.0.0.1 y no 0.0.0.0: nadie más en la red puede llegar acá, que es
    # lo que corresponde para algo que tiene tus API keys.
    servidor = None
    for intento in range(puerto, puerto + 10):
        try:
            servidor = _ServidorExclusivo(("127.0.0.1", intento), Handler)
            puerto = intento
            break
        except OSError:
            # Puerto tomado. Si es ESTE panel ya abierto (doble clic dos
            # veces en el lanzador), se abre ese en vez de un segundo; si es
            # otro programa, se prueba el siguiente. Antes se caía sin aviso
            # y, lanzado sin consola, no quedaba ni el error a la vista.
            if _es_este_panel(intento):
                print(f"  Ya hay un panel abierto en http://127.0.0.1:{intento}/")
                if abrir:
                    webbrowser.open(f"http://127.0.0.1:{intento}/")
                return
    if servidor is None:
        raise SystemExit(f"No hay un puerto libre entre {puerto} y {puerto + 9}.")
    _SERVIDOR = servidor
    # El MCP se levanta YA, de fondo, mientras el navegador todavía está
    # abriendo: así la primera captura no arranca pagando el subproceso.
    MOTOR.precalentar()
    url = f"http://127.0.0.1:{puerto}/"
    print(f"\n  AutoCAD IA — interfaz lista en {url}")
    print("  (Ctrl+C para cerrar)\n")
    if abrir:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n  Cerrando.\n")
    finally:
        servidor.server_close()
