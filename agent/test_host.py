"""El anfitrión de herramientas para el agente NATIVO (agent/web.py: /api/h/preparar y /api/h/ejecutar).

El bucle, los proveedores y la conversación viven en C# (dentro de AutoCAD); de este lado queda el catálogo de las
herramientas, ejecutarlas y el texto de sistema. Aquí se prueba por HTTP, con un MCP de mentira: sin AutoCAD ni red.

Uso:  python -m agent.test_host
"""
from __future__ import annotations

import asyncio
import http.client
import json
import os
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

os.environ["AUTOCAD_IA_ESTADO"] = tempfile.mkdtemp(prefix="host_")

FALLAS: list[str] = []


def check(nombre: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FALLAS.append(f"{nombre}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + nombre + (f" -- {detalle}" if not ok else ""))


class McpFalso:
    def __init__(self, n=200):
        self.n = n
        self.ejecutadas: list[tuple[str, dict]] = []

    def catalogo(self, incluir=None, limite_descripcion=0):
        nombres = [f"tool_{i}" for i in range(self.n)] + ["create_line", "run_code"]
        if incluir:
            nombres = [x for x in nombres if any(x == i or x.startswith(i) for i in incluir)]
        return [{"type": "function", "function": {"name": x, "description": "d", "parameters": {"type": "object", "properties": {}}}}
                for x in nombres]

    async def ejecutar(self, nombre, argumentos):
        self.ejecutadas.append((nombre, argumentos))
        if nombre == "list_tool_categories":
            return ('{"categorias": ["dibujo"]}', False)
        if nombre == "falla":
            return ("ERROR: no", True)
        return ('{"handle": "2A0"}', False)


def main() -> int:
    from . import web
    from .cli import PERFILES

    mcp = McpFalso()
    web.MOTOR.usar = lambda trabajo: asyncio.run(trabajo(mcp))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    puerto = httpd.server_address[1]

    def post(ruta, cuerpo):
        c = http.client.HTTPConnection("127.0.0.1", puerto, timeout=30)
        c.request("POST", ruta, json.dumps(cuerpo), {"Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, json.loads(r.read().decode("utf-8") or "{}")

    print("test_preparar")
    perfil = next(p for p, inc in PERFILES.items() if inc and p != "descubrir")
    st, d = post("/api/h/preparar", {"perfil": perfil, "proveedor": "anthropic"})
    check("devuelve el catálogo del perfil y su sistema", st == 200 and d["tools"] and "AutoCAD" in d["sistema"], str(d)[:200])
    check("proveedor sin límite conocido: no va bajo demanda", d["bajoDemanda"] is False and d["nota"] == "")
    check("anthropic usa su formato", d["formato"] == "anthropic")
    check("trae los nombres de TODAS las herramientas", "create_line" in d["nombres"] and len(d["nombres"]) == mcp.n + 2)
    check("y el patrón de «demasiadas herramientas» y de dibujo", d["patronDemasiadas"] and d["regexDibujo"].startswith("^(run_command"))
    st, d = post("/api/h/preparar", {"perfil": "descubrir", "proveedor": "groq"})
    check("el perfil «descubrir» manda solo las 3 de descubrimiento", d["bajoDemanda"] and [t["function"]["name"] for t in d["tools"]]
          == ["buscar_herramientas", "describir_herramienta", "ejecutar_herramienta"], str(d["tools"])[:100])
    check("y lo cuenta con una nota", "bajo demanda" in d["nota"])
    check("el texto de descubrimiento va aparte del sistema base", "ejecutar_herramienta" in d["sistemaMeta"] and d["sistemaMeta"] not in d["sistema"])
    check("la URL y el modelo del proveedor salen del preset", d["url"].startswith("https://api.groq.com") and d["modelo"])
    st, d = post("/api/h/preparar", {"perfil": perfil, "proveedor": "groq", "forzarBajoDemanda": True})
    check("forzarBajoDemanda (el proveedor se quejó de la cantidad)", d["bajoDemanda"] and "rechazó" in d["nota"])
    st, d = post("/api/h/preparar", {"perfil": "no_existe", "proveedor": "groq"})
    check("perfil desconocido: 400", st == 400)
    st, d = post("/api/h/preparar", {"perfil": perfil, "proveedor": "no_existe"})
    check("proveedor desconocido: 400", st == 400)

    print("test_ejecutar")
    st, d = post("/api/h/ejecutar", {"nombre": "create_line", "args": {"x1": 0}})
    check("ejecuta una herramienta y devuelve su texto", st == 200 and d == {"texto": '{"handle": "2A0"}', "error": False}, str(d))
    check("con sus argumentos", mcp.ejecutadas[-1] == ("create_line", {"x1": 0}))
    st, d = post("/api/h/ejecutar", {"nombre": "falla", "args": {}})
    check("un error de la herramienta vuelve como texto con error=True", d["error"] is True and "ERROR" in d["texto"])
    st, d = post("/api/h/ejecutar", {"nombre": "run_code", "args": {}})
    check("run_code no se ejecuta nunca", d["error"] is True and "run_code" not in [n for n, _ in mcp.ejecutadas])
    st, d = post("/api/h/ejecutar", {"nombre": "ejecutar_herramienta", "meta": True,
                                      "args": {"nombre": "create_line", "argumentos": {"x1": 5}}})
    check("en modo bajo demanda, ejecutar_herramienta corre la real", mcp.ejecutadas[-1] == ("create_line", {"x1": 5}) and not d["error"], str(d))
    st, d = post("/api/h/ejecutar", {"nombre": "buscar_herramientas", "meta": True, "args": {"flujo": "casa"}})
    check("buscar_herramientas consulta el mapa", mcp.ejecutadas[-1] == ("list_tool_categories", {"workflow": "casa"}))
    st, d = post("/api/h/ejecutar", {"nombre": "ejecutar_herramienta", "meta": True, "args": {"nombre": "run_code"}})
    check("run_code tampoco por el descubrimiento", d["error"] is True)
    st, d = post("/api/h/ejecutar", {"nombre": "ejecutar_herramienta", "meta": True, "args": {"__json_invalido__": "{x"}})
    check("JSON roto vuelve como error en vez de ejecutarse", d["error"] is True and "JSON" in d["texto"])

    httpd.shutdown()
    if FALLAS:
        print("\n%d FALLAS:" % len(FALLAS))
        for f in FALLAS:
            print(" -", f)
        return 1
    print("\nOK: el anfitrión de herramientas sirve catálogo, sistema y ejecución al agente nativo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
