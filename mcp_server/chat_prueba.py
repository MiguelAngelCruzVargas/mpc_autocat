"""Un 'Claude' de mentira para probar el chat sin clave ni gasto: el mismo contrato que usa chat_server
(`cliente.messages.stream(...)` como contexto, con `text_stream` y `get_final_message()`).

Dos usos:
  - las pruebas (test_chat.py) le dan un GUION: la lista de respuestas que debe dar, una por vuelta del agente;
  - `python chat_server.py --demo` usa `cliente_demo`, que contesta según lo que se le escribe, para ver la interfaz.
"""
from __future__ import annotations

import itertools
import uuid
from types import SimpleNamespace
from typing import Any, Callable, Optional

_ids = itertools.count(1)


def texto(t: str) -> Any:
    return SimpleNamespace(type="text", text=t)


def usa(nombre: str, /, **entrada: Any) -> Any:
    return SimpleNamespace(type="tool_use", id=f"toolu_{next(_ids):04d}_{uuid.uuid4().hex[:4]}", name=nombre, input=entrada)


def respuesta(*bloques: Any, parada: Optional[str] = None) -> Any:
    hay_herramienta = any(getattr(b, "type", "") == "tool_use" for b in bloques)
    return SimpleNamespace(content=list(bloques), stop_reason=parada or ("tool_use" if hay_herramienta else "end_turn"),
                           usage=SimpleNamespace(input_tokens=1200, output_tokens=150, cache_read_input_tokens=900))


class _Flujo:
    def __init__(self, resp: Any):
        self._resp = resp
        self.text_stream: Any = iter(())

    def __enter__(self) -> "_Flujo":
        # una "pieza" por trozo de 12 letras, para ver el efecto de escritura
        trozos: list[str] = []
        for b in self._resp.content:
            if b.type == "text":
                trozos += [b.text[i:i + 12] for i in range(0, len(b.text), 12)]
        self.text_stream = iter(trozos)
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def get_final_message(self) -> Any:
        return self._resp


class Cliente:
    """Responde con `generar(mensajes)` en cada vuelta."""

    def __init__(self, generar: Callable[[list[dict[str, Any]]], Any]):
        self._generar = generar
        self.llamadas: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kw: Any) -> _Flujo:
        self.llamadas.append(kw)
        return _Flujo(self._generar(kw["messages"]))


def con_guion(*respuestas: Any) -> Cliente:
    pendientes = list(respuestas)

    def generar(_m: list[dict[str, Any]]) -> Any:
        if not pendientes:
            return respuesta(texto("(sin más guion)"))
        return pendientes.pop(0)
    return Cliente(generar)


# ------------------------------------------------------------------------------------------ demo con interfaz

def _ultimo_usuario(mensajes: list[dict[str, Any]]) -> str:
    for m in reversed(mensajes):
        if m["role"] == "user" and isinstance(m["content"], str):
            return m["content"].lower()
    return ""


def _hay_resultado_nuevo(mensajes: list[dict[str, Any]]) -> bool:
    return bool(mensajes) and mensajes[-1]["role"] == "user" and isinstance(mensajes[-1]["content"], list)


def _demo(mensajes: list[dict[str, Any]]) -> Any:
    pregunta = _ultimo_usuario(mensajes)
    if _hay_resultado_nuevo(mensajes):
        ultimo = mensajes[-1]["content"][0]
        if ultimo.get("is_error"):
            return respuesta(texto("No se pudo hacer eso: " + str(ultimo["content"])[:160] + " ¿Quieres que lo intente de otra forma?"))
        if "portico" in pregunta or "pórtico" in pregunta or "flujo" in pregunta:
            return respuesta(texto("Ese es el flujo del pórtico: diseñar la barda y el portal, imponer la cimentación si "
                                   "el cliente la define, dibujar las vistas, cuantificar y sacar la memoria. "
                                   "**Antes de empezar** necesito la capacidad del suelo, el f'c y el desplante: "
                                   "son datos del proyecto y no los invento."))
        if "linea" in pregunta or "línea" in pregunta:
            return respuesta(texto("Listo: la línea quedó dibujada de (0,0) a (5,0)."))
        return respuesta(texto("Hecho."))
    if "portico" in pregunta or "pórtico" in pregunta or "flujo" in pregunta:
        return respuesta(texto("Voy a consultar el flujo de trabajo del pórtico. "),
                         usa("buscar_herramientas", flujo="portico"))
    if "linea" in pregunta or "línea" in pregunta:
        return respuesta(texto("Voy a dibujar una línea de (0,0) a (5,0) en la capa actual. "),
                         usa("ejecutar_herramienta", nombre="create_line",
                             argumentos={"x1": 0, "y1": 0, "x2": 5, "y2": 0}))
    if "borra" in pregunta or "elimina" in pregunta:
        return respuesta(texto("Voy a borrar la entidad indicada. "),
                         usa("ejecutar_herramienta", nombre="delete_entities", argumentos={"handles": ["ABC"]}))
    if "estado" in pregunta or "dibujo" in pregunta:
        return respuesta(texto("Reviso el dibujo activo. "), usa("estado_del_dibujo"))
    return respuesta(texto("Esto es el **modo demostración**: no estoy hablando con Claude de verdad. "
                           "Prueba con «¿cómo es el flujo del pórtico?», «dibuja una línea» o «borra una entidad» "
                           "para ver cómo se piden los permisos."))


def cliente_demo(_clave: str) -> Cliente:
    return Cliente(_demo)
