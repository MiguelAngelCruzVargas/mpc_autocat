"""Herramientas «bajo demanda»: cuando el catálogo no cabe en un pedido, el agente las descubre en vez de recibirlas todas.

El servidor tiene unas 300 herramientas. Mandar todas en cada vuelta cuesta ~100 mil tokens y muchos proveedores ni
las aceptan: Groq, OpenAI y DeepSeek rechazan más de 128 («'tools': maximum number of items is 128»). Una
especialidad (perfil) recorta, pero con «todo» no cabe. Entonces el modelo recibe SOLO TRES herramientas —buscar,
describir y ejecutar— y descubre las que necesita, igual que cuando una persona usa `list_tool_categories`: así las
300 siguen alcanzables y cada vuelta cuesta ~1 mil tokens en vez de 100 mil.

El bucle (loop.py) cambia a este modo solo: antes de empezar si ya se sabe el límite del proveedor (LIMITES), o al
vuelo si el proveedor se queja de la cantidad de herramientas (el límite de un modelo que no está en la tabla).
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

# Máximo de herramientas por pedido, donde está documentado. None = sin límite conocido (si lo hay, el bucle lo
# descubre por el error del proveedor y cambia de modo en ese momento).
LIMITES: dict[str, Optional[int]] = {"groq": 128, "openai": 128, "deepseek": 128}

# El mensaje con que los proveedores avisan que mandaste demasiadas herramientas.
PATRON_DEMASIADAS = re.compile(r"maximum number of items|too many tools|tools?.{0,40}(maximum|exceed|limit)", re.I)

NO_PERMITIDAS = {"run_code"}

TEXTO_SISTEMA = """\
Este servidor tiene unas 300 herramientas de AutoCAD y NO se te muestran todas: las descubres tú con tres herramientas.
1. `buscar_herramientas`: sin argumentos lista las categorías; `flujo` (casa, estructura, instalaciones, vial, 3d, laminas,
   portico) da los pasos EN ORDEN de un tipo de proyecto con la herramienta de cada uno; `categoria` lista las de una
   categoría; `texto` busca por palabras.
2. `describir_herramienta(nombre)`: sus parámetros exactos. Hazlo SIEMPRE antes de usarla: no los adivines.
3. `ejecutar_herramienta(nombre, argumentos)`: la corre. `argumentos` es un objeto JSON con los nombres que dio
   `describir_herramienta`.
Una herramienta por vez y lee su resultado antes de la siguiente. `run_code` no está disponible.
Que no veas una herramienta en la lista NO significa que no exista: casi todo lo que se hace en AutoCAD tiene la suya. Son tu trabajo, sin \
rechazarlos: abrir, cerrar, guardar y listar dibujos (la persona es la dueña de los archivos y te lo autoriza; si dice «sin guardar», se \
cierra sin guardar) y dibujar cualquier plano o pieza que alcances. Si el pedido es amplio o ambiguo, no rechaces ni preguntes de entrada: \
empieza con `buscar_herramientas` y elige tú lo más completo que alcances. NUNCA digas que hiciste algo que no ejecutaste con una \
herramienta: si no la llamaste, no ocurrió.
Para una casa, vivienda, estructura, instalaciones o láminas NO dibujes rectángulos a mano: empieza con `buscar_herramientas` con \
`flujo` (casa, estructura, instalaciones...) y sigue sus pasos en orden (en una casa: `suggest_layout` y `draw_layout`). No termines \
hasta haber hecho todo el pedido, y cierra siempre con un resumen de lo que quedó dibujado."""

META: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "buscar_herramientas",
        "description": "Busca herramientas de AutoCAD. Sin argumentos lista las categorías. `flujo` da los pasos EN ORDEN de un "
                       "tipo de proyecto; `categoria` lista las de una categoría; `texto` busca por palabras.",
        "parameters": {"type": "object", "properties": {
            "texto": {"type": "string"}, "categoria": {"type": "string"}, "flujo": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "describir_herramienta",
        "description": "Devuelve la descripción y los parámetros exactos de UNA herramienta. Hazlo antes de ejecutarla.",
        "parameters": {"type": "object", "properties": {"nombre": {"type": "string"}}, "required": ["nombre"]}}},
    {"type": "function", "function": {
        "name": "ejecutar_herramienta",
        "description": "Ejecuta una herramienta de AutoCAD con sus argumentos (un objeto JSON).",
        "parameters": {"type": "object", "properties": {"nombre": {"type": "string"}, "argumentos": {"type": "object"}},
                       "required": ["nombre"]}}},
]

NOMBRES = {m["function"]["name"] for m in META}


ENVOLTURAS = ("properties", "arguments", "parameters", "params", "args", "input")


def _esqueleto(params: Any) -> dict[str, str]:
    """Los argumentos obligatorios de una herramienta con su tipo: lo mínimo que hay que mandar."""
    props = (params or {}).get("properties") or {}
    req = set((params or {}).get("required") or [])
    return {k: "<" + str((v or {}).get("type", "valor")) + ">" for k, v in props.items() if k in req}


def _recortar(texto: str, limite: int = 8000) -> str:
    if len(texto) <= limite:
        return texto
    return texto[:limite] + f"\n[... recortado: {len(texto) - limite} caracteres más. Pide algo más acotado.]"


class Descubridor:
    """Atiende las tres herramientas de descubrimiento sobre una conexión MCP."""

    def __init__(self, conexion: Any) -> None:
        self.con = conexion
        self._por_nombre: Optional[dict[str, dict[str, Any]]] = None

    def _catalogo(self) -> dict[str, dict[str, Any]]:
        if self._por_nombre is None:
            self._por_nombre = {t["function"]["name"]: t["function"] for t in self.con.catalogo()}
        return self._por_nombre

    @staticmethod
    def visible(nombre: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Cómo se muestra la llamada en pantalla: `ejecutar_herramienta` se ve como la herramienta real."""
        if nombre == "ejecutar_herramienta":
            real = str(args.get("nombre", "?"))
            inner = args.get("argumentos")
            if isinstance(inner, str):
                try:
                    inner = json.loads(inner)
                except ValueError:
                    inner = {}
            return real, inner if isinstance(inner, dict) else {}
        return nombre, args

    def _desenvolver(self, real: str, inner: Any) -> Any:
        """Quita la envoltura que un modelo chico le pone a los argumentos: {"properties": {...}} (la forma del esquema),
        {"arguments": {...}}, {"parameters": {...}}... Solo si esa clave NO es un parámetro de la herramienta
        (create_object, por ejemplo, SÍ tiene uno llamado `properties`)."""
        if not isinstance(inner, dict) or len(inner) != 1:
            return inner
        (clave, valor), = inner.items()
        props = ((self._catalogo().get(real) or {}).get("parameters") or {}).get("properties") or {}
        if clave in ENVOLTURAS and clave not in props and isinstance(valor, dict):
            return valor
        return inner

    async def atender(self, nombre: str, args: dict[str, Any]) -> tuple[str, bool]:
        """(texto, hubo_error). Los errores vuelven al modelo como texto para que los corrija."""
        if "__json_invalido__" in args:
            return ("Los argumentos no son un JSON válido: " + str(args["__json_invalido__"])[:200], True)
        if nombre == "buscar_herramientas":
            pedido = {k: v for k, v in (("query", args.get("texto")), ("category", args.get("categoria")),
                                        ("workflow", args.get("flujo"))) if v}
            texto, error = await self.con.ejecutar("list_tool_categories", pedido)
            return _recortar(texto), error
        if nombre == "describir_herramienta":
            n = str(args.get("nombre", ""))
            t = self._catalogo().get(n)
            if t is None:
                return (f"No existe la herramienta '{n}'. Usa buscar_herramientas.", True)
            params = t.get("parameters", {})
            # Un modelo chico copia la FORMA de lo que ve: si le llega un esquema JSON con «properties», manda
            # {"properties": {...}} en vez de los argumentos. Por eso se le da, aparte, la forma exacta de lo que tiene que mandar.
            return (json.dumps({"nombre": n, "descripcion": _recortar(t.get("description", ""), 2500),
                                "argumentos_requeridos": _esqueleto(params),
                                "nota": "Manda los argumentos SUELTOS en `argumentos` (p. ej. {\"x1\": 0, \"y1\": 0}), sin envolverlos en "
                                        "«properties» ni en otra clave. Los opcionales solo si hacen falta.",
                                "parametros": params}, ensure_ascii=False), False)
        if nombre == "ejecutar_herramienta":
            real, inner = self.visible(nombre, args)
            inner = self._desenvolver(real, inner)
            if real in NO_PERMITIDAS:
                return (f"'{real}' no está disponible en este chat: usa las herramientas de oficio.", True)
            if real not in self._catalogo():
                return (f"No existe la herramienta '{real}'. Usa buscar_herramientas.", True)
            texto, error = await self.con.ejecutar(real, inner)
            return _recortar(texto), error
        return (f"Herramienta desconocida: {nombre}", True)
