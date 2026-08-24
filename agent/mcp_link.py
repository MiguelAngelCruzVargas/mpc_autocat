"""Conexión al servidor MCP de AutoCAD, en el vocabulario que espera un LLM.

El servidor de este repo ya es agnóstico del modelo: habla MCP por stdio y
no sabe nada de quién lo llama. Lo que faltaba era el HOST — el proceso que
lanza el servidor, le pide el catálogo de tools, se lo traduce a un modelo
cualquiera y ejecuta lo que ese modelo pide. Eso es este módulo.

La traducción importa más de lo que parece: los schemas que genera FastMCP
usan `anyOf` para los opcionales, y varios modelos (sobre todo los que no
son de OpenAI) rechazan o ignoran esa forma. Acá se aplanan a un tipo
simple con el opcional marcado por ausencia en `required`, que es lo que
todos entienden.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Dónde vive el servidor de este repo, para no obligar a configurarlo.
_AQUI = os.path.dirname(os.path.abspath(__file__))
_RAIZ = os.path.dirname(_AQUI)
SERVIDOR_DEFECTO = os.path.join(_RAIZ, "mcp_server", "server.py")


def _aplanar_schema(schema: Any) -> Any:
    """Saca los `anyOf` de opcional que FastMCP genera para Optional[X].

    Un `{"anyOf": [{"type": "number"}, {"type": "null"}]}` se convierte en
    `{"type": "number"}`. El dato de que es opcional NO se pierde: vive en
    la lista `required` del objeto padre. Sin esto, modelos que no son de
    OpenAI mandan strings donde va un número, o directamente se niegan a
    usar la tool.
    """
    if isinstance(schema, list):
        return [_aplanar_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema

    if "anyOf" in schema:
        variantes = [v for v in schema["anyOf"]
                     if not (isinstance(v, dict) and v.get("type") == "null")]
        if len(variantes) == 1:
            fusionado = dict(variantes[0])
            for clave in ("default", "title", "description"):
                if clave in schema and clave not in fusionado:
                    fusionado[clave] = schema[clave]
            # Y se TIRA el `default: null`. Si se deja, el modelo lo ve y
            # manda literalmente null en un campo que ahora dice "string":
            # Groq rechaza la llamada entera con "expected string, but got
            # null" y la tool no se ejecuta. Pasó de verdad con
            # new_document(template=None). Un opcional no se manda como
            # null: se OMITE, y para eso ya está su ausencia en 'required'.
            if fusionado.get("default", "…") is None:
                del fusionado["default"]
            return _aplanar_schema(fusionado)

    return {k: _aplanar_schema(v) for k, v in schema.items()}


def _recortar(texto: str, limite: int) -> str:
    """Docstring recortado al primer párrafo si hace falta.

    Las tools de este repo tienen documentación larga a propósito — es lo
    que hace que el agente dibuje bien. Pero 128 tools por 800 caracteres
    son ~25k tokens SOLO de definiciones, y en un modelo de ventana corta
    eso no entra ni deja lugar para trabajar. El primer párrafo dice qué
    hace la tool; el detalle se pierde, y por eso el recorte es opcional.
    """
    if limite <= 0 or len(texto) <= limite:
        return texto
    corte = texto.find("\n\n")
    if 0 < corte <= limite:
        return texto[:corte].strip()
    return texto[:limite].rsplit(" ", 1)[0] + "…"


class ConexionMcp:
    """Sesión abierta contra el servidor MCP, lanzado como subproceso."""

    def __init__(self, servidor: Optional[str] = None,
                 python: Optional[str] = None,
                 env: Optional[dict[str, str]] = None) -> None:
        self.servidor = servidor or SERVIDOR_DEFECTO
        # El servidor importa sus módulos por nombre (import arch, no
        # from mcp_server import arch), así que tiene que correr desde su
        # propio directorio.
        self.directorio = os.path.dirname(self.servidor)
        self.python = python or sys.executable
        self.env = env
        self._session: Optional[ClientSession] = None
        self._ctx_stdio = None
        self._ctx_session = None
        self.tools: list[dict[str, Any]] = []

    async def __aenter__(self) -> "ConexionMcp":
        params = StdioServerParameters(
            command=self.python,
            args=[os.path.basename(self.servidor)],
            cwd=self.directorio,
            env={**os.environ, **(self.env or {})},
        )
        self._ctx_stdio = stdio_client(params)
        lectura, escritura = await self._ctx_stdio.__aenter__()
        self._ctx_session = ClientSession(lectura, escritura)
        self._session = await self._ctx_session.__aenter__()
        await self._session.initialize()
        listado = await self._session.list_tools()
        self.tools = [{
            "name": t.name,
            "description": t.description or "",
            "schema": _aplanar_schema(t.inputSchema or
                                      {"type": "object", "properties": {}}),
        } for t in listado.tools]
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._ctx_session is not None:
            await self._ctx_session.__aexit__(*exc)
        if self._ctx_stdio is not None:
            await self._ctx_stdio.__aexit__(*exc)
        self._session = None

    # ------------------------------------------------ catálogo para el LLM

    def catalogo(self, incluir: Optional[list[str]] = None,
                 limite_descripcion: int = 0) -> list[dict[str, Any]]:
        """Las tools en el formato de function calling de OpenAI.

        incluir: nombres exactos o prefijos ('create_', 'check_'). None son
        todas. Filtrar no es un lujo: con las 128 tools de este repo las
        definiciones solas ocupan miles de tokens en CADA vuelta del bucle.
        """
        salida = []
        for t in self.tools:
            if incluir and not any(t["name"] == n or t["name"].startswith(n)
                                   for n in incluir):
                continue
            salida.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": _recortar(t["description"],
                                             limite_descripcion),
                    "parameters": t["schema"],
                },
            })
        return salida

    async def ejecutar(self, nombre: str,
                       argumentos: dict[str, Any]) -> tuple[str, bool]:
        """Corre una tool y devuelve (texto del resultado, hubo_error).

        Un error NO se propaga como excepción: se devuelve como texto para
        que el modelo lo lea y corrija. Que el bucle se caiga porque una
        tool falló sería tirar la sesión entera por algo que el agente
        podría resolver — es la diferencia entre un asistente y un script.
        """
        if self._session is None:
            raise RuntimeError("La conexión MCP no está abierta.")
        try:
            r = await self._session.call_tool(nombre, argumentos or {})
        except Exception as exc:                      # noqa: BLE001
            return (f"ERROR al invocar '{nombre}': {exc}", True)

        partes = []
        for c in r.content:
            texto = getattr(c, "text", None)
            partes.append(texto if texto is not None else str(c))
        return ("\n".join(partes) or "(sin salida)", bool(r.isError))
