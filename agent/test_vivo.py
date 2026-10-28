"""El modo «En vivo» del panel (agent/web.py + mcp_server/canal_panel.py) sin AutoCAD ni agente real.

Un agente con su propia suscripción (Claude Code, OpenCode...) trabaja en su programa y llama al servidor MCP; el
servidor anota cada llamada y el panel la muestra. Aquí se juega los dos lados: «el agente» escribe actividad con
canal_panel, y se mira lo que el panel expone por HTTP.

Uso:  python -m agent.test_vivo
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

ESTADO = tempfile.mkdtemp(prefix="vivo_")
os.environ["AUTOCAD_IA_ESTADO"] = ESTADO
os.environ.pop("AUTOCAD_IA_PUENTES", None)

FALLAS: list[str] = []


def check(nombre: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FALLAS.append(f"{nombre}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + nombre + (f" -- {detalle}" if not ok else ""))


def main() -> int:
    from . import web
    from .cli import PERFILES
    canal = web._canal_mod()
    web.Sesion.ARCHIVO = os.path.join(ESTADO, "conversacion.json")
    web._CONTEO.update({p: 1 for p in PERFILES})            # sin levantar el servidor MCP real para contar tools
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    puerto = httpd.server_address[1]

    def http_(metodo, ruta, cuerpo=None):
        c = http.client.HTTPConnection("127.0.0.1", puerto, timeout=30)
        c.request(metodo, ruta, json.dumps(cuerpo) if cuerpo is not None else None, {"Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, r.read().decode("utf-8")

    print("test_proveedor_en_vivo")
    st, cuerpo = http_("GET", "/api/estado")
    provs = {p["id"]: p for p in json.loads(cuerpo)["proveedores"]}
    check("'en-vivo' es un proveedor más, sin clave", st == 200 and provs["en-vivo"]["vivo"] is True and provs["en-vivo"]["clave"])
    check("los puentes de lanzar `claude -p` quedan ocultos por defecto", "claude-code" not in provs)
    os.environ["AUTOCAD_IA_PUENTES"] = "1"
    check("y se pueden mostrar con AUTOCAD_IA_PUENTES=1",
          "claude-code" in {p["id"] for p in json.loads(http_("GET", "/api/estado")[1])["proveedores"]})
    os.environ.pop("AUTOCAD_IA_PUENTES")
    st, cuerpo = http_("POST", "/api/chat", {"mensaje": "hola", "proveedor": "en-vivo"})
    check("el chat de API rechaza 'en-vivo' con una explicación", st == 400 and "propio programa" in json.loads(cuerpo)["error"])

    print("test_actividad_en_vivo")
    st, cuerpo = http_("GET", "/api/vivo/actividad?desde=0")
    check("sin actividad no hay nada", st == 200 and json.loads(cuerpo) == {"eventos": [], "pos": 0})
    canal.registrar({"t": "inicio", "id": "a1", "tool": "create_wall_network", "args": {"walls": 12}})
    canal.registrar({"t": "fin", "id": "a1", "tool": "create_wall_network", "ok": True, "ms": 830, "texto": "{\"created\": 12}"})
    st, cuerpo = http_("GET", "/api/vivo/actividad?desde=0")
    d = json.loads(cuerpo)
    check("lo que el servidor MCP anota, el panel lo ve", [e["t"] for e in d["eventos"]] == ["inicio", "fin"] and d["eventos"][1]["ms"] == 830)
    canal.registrar({"t": "inicio", "id": "a2", "tool": "place_labels"})
    d2 = json.loads(http_("GET", f"/api/vivo/actividad?desde={d['pos']}")[1])
    check("pidiendo desde la posición anterior llegan solo las novedades", [e["id"] for e in d2["eventos"]] == ["a2"] and d2["pos"] > d["pos"])
    for i in range(10):
        canal.registrar({"t": "inicio", "id": f"m{i}", "tool": "t"})
    d3 = json.loads(http_("GET", "/api/vivo/actividad?desde=0&limite=3")[1])
    check("`limite` trae lo más reciente (así la primera carga no inunda el panel)",
          [e["id"] for e in d3["eventos"]] == ["m7", "m8", "m9"])
    check("un `desde` absurdo no rompe", http_("GET", "/api/vivo/actividad?desde=abc")[0] == 200)

    print("test_mensajes_en_los_dos_sentidos")
    st, cuerpo = http_("POST", "/api/vivo/mensaje", {"texto": "  revisa el eje B  "})
    check("la persona escribe en el panel y queda en la bandeja", st == 200 and json.loads(cuerpo)["ok"] is True)
    check("un mensaje vacío se rechaza", http_("POST", "/api/vivo/mensaje", {"texto": "   "})[0] == 400)
    check("el agente lo recibe (canal_panel.mensajes_pendientes)", [m["texto"] for m in canal.mensajes_pendientes()] == ["revisa el eje B"])
    canal.enviar("claude", "Listo, el eje B está a 3.50 m.", "listo")
    d = json.loads(http_("GET", "/api/vivo/bandeja?desde=0")[1])
    check("el panel ve los dos sentidos, en orden y con su tipo",
          [(m["de"], m["tipo"]) for m in d["mensajes"]] == [("usuario", "info"), ("claude", "listo")])

    print("test_herramientas_por_especialidad")
    web._NOMBRES_PERFIL["estructura"] = ["design_beam", "create_line"]       # sin levantar el servidor MCP real
    d = json.loads(http_("GET", "/api/perfil_tools?perfil=estructura")[1])
    check("el panel puede leer qué herramientas trae una especialidad", d == {"perfil": "estructura", "tools": ["design_beam", "create_line"]})
    check("una especialidad que no existe es 404", http_("GET", "/api/perfil_tools?perfil=nada")[0] == 404)

    print("test_la_vista_se_ajusta_sola_al_dibujar")
    import asyncio

    class McpFalso:
        def __init__(self):
            self.ejecutadas = []

        def catalogo(self, incluir=None, limite_descripcion=0):
            return [{"type": "function", "function": {"name": n, "description": "x", "parameters": {"type": "object", "properties": {}}}}
                    for n in ("create_line", "list_layers", "zoom_extents")]

        async def ejecutar(self, nombre, argumentos):
            self.ejecutadas.append(nombre)
            return ('{"handle": "2A0"}', False)

    class ProveedorGuion:
        formato, modelo = "openai", "falso"

        def __init__(self, herramienta):
            self.herramienta, self.n = herramienta, 0

        def completar(self, mensajes, tools):
            self.n += 1
            if self.n == 1:
                return {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "c1", "type": "function", "function": {"name": self.herramienta, "arguments": "{}"}}]}
            return {"role": "assistant", "content": "Listo."}

    def pedir(herramienta):
        mcp = McpFalso()
        web.MOTOR.usar = lambda trabajo: asyncio.run(trabajo(mcp))
        web.providers.construir = lambda *a, **k: ProveedorGuion(herramienta)
        web.EN_AUTOCAD = True
        st, cuerpo = http_("POST", "/api/chat", {"mensaje": "hazlo", "proveedor": "groq", "perfil": "arquitectura"})
        web.EN_AUTOCAD = False
        return mcp, [json.loads(l[6:]) for l in cuerpo.split("\n\n") if l.startswith("data: ")]
    mcp, ev = pedir("create_line")
    check("dentro de AutoCAD, tras dibujar se ajusta la vista (zoom_extents)", mcp.ejecutadas == ["create_line", "zoom_extents"], str(mcp.ejecutadas))
    check("y lo cuenta con una nota", any(e["tipo"] == "nota" and "Vista ajustada" in e["texto"] for e in ev))
    mcp, ev = pedir("list_layers")
    check("una consulta que no dibuja NO mueve la vista", mcp.ejecutadas == ["list_layers"], str(mcp.ejecutadas))

    print("test_como_conectar")
    d = json.loads(http_("GET", "/api/vivo/info")[1])
    check("da el comando exacto para Claude Code, con la ruta real del servidor MCP",
          d["claude"].startswith("claude mcp add autocad") and d["servidor"] in d["claude"] and os.path.exists(d["servidor"]), str(d))
    check("y el python que lo lanza", os.path.exists(d["python"]) and d["python"].lower().endswith("python.exe") or os.name != "nt")
    check("una ruta /api/vivo/ inexistente es 404", http_("GET", "/api/vivo/nada")[0] == 404)

    httpd.shutdown()
    if FALLAS:
        print("\n%d FALLAS:" % len(FALLAS))
        for f in FALLAS:
            print(" -", f)
        return 1
    print("\nOK: el panel muestra en vivo la actividad del agente y es el canal de mensajes con él.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
