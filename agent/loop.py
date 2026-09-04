"""El bucle agéntico: pedirle al modelo, ejecutar sus tools, repetir.

Es lo único que faltaba para que este MCP no dependa de Claude Code. El
servidor ya expone las tools; acá está el ciclo

    modelo -> pide tools -> se ejecutan -> el resultado vuelve al modelo

que es lo que convierte un catálogo de funciones en un agente que dibuja.

Dos decisiones que valen la pena explicar:

- Los errores de tool vuelven al modelo COMO TEXTO, no como excepción. Este
  servidor está diseñado para eso: sus errores dicen qué pasó y cómo
  arreglarlo ("el hueco se sale del muro, que mide 10"). Un modelo que lee
  eso corrige y sigue; un bucle que se cae pierde la sesión entera.
- Hay un tope de vueltas. Un modelo chico puede quedarse en un lazo
  llamando la misma tool para siempre, y sin tope eso es una factura
  corriendo sola.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from .mcp_link import ConexionMcp
from .providers import ErrorProveedor, ToolInvalida

VUELTAS_MAX = 40


def _texto_de(mensaje: dict[str, Any]) -> str:
    """El texto visible de un mensaje, en cualquiera de los dos formatos."""
    contenido = mensaje.get("content")
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        partes = [c.get("text", "") for c in contenido
                  if isinstance(c, dict) and c.get("type") == "text"]
        return "\n".join(p for p in partes if p)
    return ""


def _llamadas_de(mensaje: dict[str, Any], formato: str) -> list[dict[str, Any]]:
    """Las tools que el modelo pidió, normalizadas a {id, nombre, args}."""
    salida: list[dict[str, Any]] = []
    if formato == "anthropic":
        for c in mensaje.get("content", []) or []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                salida.append({"id": c.get("id", ""),
                               "nombre": c.get("name", ""),
                               "args": c.get("input") or {}})
        return salida

    for c in mensaje.get("tool_calls") or []:
        fn = c.get("function") or {}
        crudo = fn.get("arguments") or "{}"
        try:
            args = json.loads(crudo) if isinstance(crudo, str) else crudo
        except json.JSONDecodeError:
            # Un modelo chico a veces manda JSON roto. Se le devuelve el
            # error como resultado de la tool y casi siempre se corrige.
            args = {"__json_invalido__": crudo}
        salida.append({"id": c.get("id", ""), "nombre": fn.get("name", ""),
                       "args": args})
    return salida


async def conversar(conexion: ConexionMcp, proveedor: Any,
                    mensajes: list[dict[str, Any]],
                    tools: list[dict[str, Any]],
                    al_evento: Optional[Callable[[str, dict], None]] = None,
                    vueltas_max: int = VUELTAS_MAX,
                    cancelado: Optional[Callable[[], bool]] = None
                    ) -> list[dict[str, Any]]:
    """Corre el ciclo hasta que el modelo deja de pedir tools.

    Devuelve la conversación completa (para poder seguirla después). El
    callback 'al_evento' recibe ('texto'|'tool'|'resultado'|'aviso', datos)
    y es lo que la interfaz usa para mostrar lo que va pasando — sin él, el
    usuario mira una pantalla quieta mientras el agente dibuja.
    """
    formato = getattr(proveedor, "formato", "openai")

    def avisar(tipo: str, datos: dict) -> None:
        if al_evento:
            al_evento(tipo, datos)

    def se_corto() -> bool:
        return bool(cancelado and cancelado())

    invalidas = 0        # veces seguidas que pidió una tool inexistente

    for vuelta in range(vueltas_max):
        if se_corto():
            avisar("aviso", {"texto": "Cancelado. Lo que ya se dibujó queda "
                                      "en el DWG: revisalo antes de seguir."})
            break
        try:
            respuesta = proveedor.completar(mensajes, tools)
        except ToolInvalida as exc:
            # Pidió una tool que no está en este perfil. Es un error del
            # MODELO, no de la conexión: se le dice cuáles tiene y sigue,
            # igual que con cualquier error de tool. Cortar acá tiraba dos
            # minutos de dibujo por un nombre mal puesto — pasó de verdad:
            # check_all avisó de 16 grupos de entidades duplicadas, el
            # modelo quiso arreglarlo con delete_entities (que no estaba en
            # el perfil) y Groq rechazó el request entero con un 400.
            invalidas += 1
            if invalidas > 3:
                avisar("aviso", {"texto":
                                 f"{exc} Insistió {invalidas} veces con tools "
                                 "que no tiene; se corta."})
                break
            avisar("aviso", {"texto": f"{exc} Se le avisa y sigue."})
            disponibles = ", ".join(
                t.get("function", {}).get("name", "") for t in tools)
            mensajes.append({
                "role": "user",
                "content": (f"ERROR: la tool '{exc.tool or '?'}' no existe en "
                            "este perfil, así que la llamada NO se ejecutó. "
                            "Las que tenés son: " + disponibles + ". Si "
                            "necesitás una que no está, decilo y seguí con el "
                            "resto del trabajo.")})
            continue
        except ErrorProveedor as exc:
            avisar("aviso", {"texto": str(exc)})
            break
        invalidas = 0

        if hasattr(proveedor, "resumen"):
            avisar("uso", proveedor.resumen())

        texto = _texto_de(respuesta)
        if texto:
            avisar("texto", {"texto": texto})

        llamadas = _llamadas_de(respuesta, formato)
        mensajes.append(_como_mensaje_asistente(respuesta, formato, texto,
                                                llamadas))
        if not llamadas:
            break

        resultados = []
        for llamada in llamadas:
            # Se corta ENTRE tools, nunca a mitad de una: abandonar un
            # create_walls a medio camino dejaría el dibujo inconsistente.
            if se_corto():
                avisar("aviso", {"texto":
                                 "Cancelado. La tool en curso terminó; las "
                                 "que faltaban no se ejecutaron."})
                return mensajes
            avisar("tool", {"nombre": llamada["nombre"],
                            "args": llamada["args"]})
            salida, hubo_error = await conexion.ejecutar(llamada["nombre"],
                                                         llamada["args"])
            avisar("resultado", {"nombre": llamada["nombre"],
                                 "texto": salida, "error": hubo_error})
            resultados.append((llamada, salida))

        mensajes.extend(_como_mensajes_resultado(resultados, formato))
    else:
        avisar("aviso", {"texto":
                         f"Se llegó al tope de {vueltas_max} vueltas. Si la "
                         "tarea era larga, seguí con otra instrucción; si el "
                         "modelo se quedó en un lazo, revisá qué tool repite."})
    return mensajes


def _como_mensaje_asistente(respuesta: dict[str, Any], formato: str,
                            texto: str,
                            llamadas: list[dict[str, Any]]) -> dict[str, Any]:
    if formato == "anthropic":
        return {"role": "assistant",
                "content": respuesta.get("content", [])}
    mensaje: dict[str, Any] = {"role": "assistant", "content": texto or None}
    if llamadas:
        mensaje["tool_calls"] = respuesta.get("tool_calls")
    return mensaje


def _como_mensajes_resultado(resultados: list[tuple[dict, str]],
                             formato: str) -> list[dict[str, Any]]:
    if formato == "anthropic":
        # Anthropic espera TODOS los resultados en un solo mensaje 'user'.
        return [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": llamada["id"],
             "content": salida} for llamada, salida in resultados]}]
    return [{"role": "tool", "tool_call_id": llamada["id"],
             "name": llamada["nombre"], "content": salida}
            for llamada, salida in resultados]
