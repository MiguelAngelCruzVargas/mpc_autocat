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
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from . import credenciales, providers
from .cli import PERFILES, _system_prompt
from .loop import conversar
from .mcp_link import ConexionMcp, SERVIDOR_DEFECTO

_AQUI = os.path.dirname(os.path.abspath(__file__))
_WEB_DIR = os.path.join(_AQUI, "web")
_HTML = os.path.join(_WEB_DIR, "index.html")


class Sesion:
    """La conversación en curso. Una sola: esto es una app local."""

    def __init__(self) -> None:
        self.mensajes: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.cancelar = threading.Event()

    def reiniciar(self, system: str) -> None:
        self.mensajes = [{"role": "system", "content": system}]


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

    def do_GET(self) -> None:                          # noqa: N802
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
            puede = providers.soporta_imagenes(modelo)
            self._json({
                "modelo": modelo,
                "soportaImagenes": puede,
                "motivo": ("" if puede else
                           f"'{modelo}' es un modelo de solo texto: no puede "
                           "ver imágenes. Si le adjuntás un croquis, o lo "
                           "ignora en silencio o rechaza el pedido entero. "
                           "Para trabajar con imágenes usá uno multimodal "
                           "(gpt-4o, claude-3.5+, gemini, qwen-vl, "
                           "llama-3.2-vision…)."),
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
            with SESION.lock:
                SESION.mensajes = []
            self._json({"ok": True})
            return

        if self.path == "/api/cancelar":
            SESION.cancelar.set()
            self._json({"ok": True})
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
        params: dict[str, Any] = {"path": destino, "layout": None}
        if all(k in zona for k in ("minX", "minY", "maxX", "maxY")):
            params.update({k: float(zona[k]) for k in
                           ("minX", "minY", "maxX", "maxY")})

        async def trabajo(mcp: ConexionMcp) -> dict[str, Any]:
            if not zona:
                await mcp.ejecutar("zoom_extents", {})
            salida, error = await mcp.ejecutar("capture_viewport", params)
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
        if imagenes and not providers.soporta_imagenes(proveedor.modelo):
            self._json({"error":
                        f"'{proveedor.modelo}' no puede ver imágenes. "
                        "Elegí un modelo multimodal (gpt-4o, claude-3.5+, "
                        "gemini, qwen-vl…) o mandá el pedido sin adjuntos."},
                       400)
            return

        perfil = str(datos.get("perfil", "arquitectura"))
        incluir = PERFILES.get(perfil)
        if incluir is None:
            self._json({"error": f"Perfil desconocido: {perfil}"}, 400)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def emitir(tipo: str, cuerpo: dict) -> None:
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
                    SESION.reiniciar(_system_prompt(
                        bool(datos.get("conReglas", True)),
                        int(datos.get("limiteReglas") or 0)))
                if imagenes:
                    formato = getattr(proveedor, "formato", "openai")
                    bloques: list[dict[str, Any]] = [
                        {"type": "text",
                         "text": pedido or "Mirá esta imagen."}]
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


def iniciar(puerto: int = 8770, abrir: bool = True) -> None:
    # 127.0.0.1 y no 0.0.0.0: nadie más en la red puede llegar acá, que es
    # lo que corresponde para algo que tiene tus API keys.
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Handler)
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
