"""Hablar con cualquier LLM que entienda el formato de OpenAI.

Se usa HTTP directo (httpx) y no el SDK de OpenAI a propósito: el formato
`/chat/completions` con `tools` es el mismo en OpenRouter, OpenAI, Groq,
Together, DeepSeek, Mistral y en cualquier servidor local (LM Studio,
Ollama, llama.cpp). Un solo adaptador los cubre a todos, sin arrastrar una
dependencia que ata el proyecto a un proveedor.

Anthropic tiene su propio formato de tools y va aparte, en la clase
ProveedorAnthropic, para que el mismo bucle sirva también con Claude por
API (que no es lo mismo que Claude Code: acá el host es este programa).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import httpx

# Proveedores conocidos: URL base y de qué variable sale la clave. Sirven
# para que `--proveedor openrouter` funcione sin configurar nada más.
PRESETS: dict[str, dict[str, str]] = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1",
        "env": "OPENROUTER_API_KEY",
        "modelo": "anthropic/claude-3.5-sonnet",
    },
    "openai": {
        "url": "https://api.openai.com/v1",
        "env": "OPENAI_API_KEY",
        "modelo": "gpt-4o",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1",
        "env": "GROQ_API_KEY",
        # Era llama-3.3-70b-versatile y Groq lo retiró de su catálogo: el
        # default fallaba con 404 apenas alguien abría la interfaz. Un
        # default tiene que ser un modelo que exista HOY, y si este también
        # se retira, el botón "Probar cuáles sirven" lo dice al instante.
        "modelo": "openai/gpt-oss-120b",
    },
    "deepseek": {
        "url": "https://api.deepseek.com/v1",
        "env": "DEEPSEEK_API_KEY",
        "modelo": "deepseek-chat",
    },
    "together": {
        "url": "https://api.together.xyz/v1",
        "env": "TOGETHER_API_KEY",
        "modelo": "Qwen/Qwen2.5-72B-Instruct-Turbo",
    },
    "local": {
        # LM Studio / Ollama / llama.cpp con su servidor compatible.
        "url": "http://localhost:1234/v1",
        "env": "LOCAL_API_KEY",
        "modelo": "local-model",
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1",
        "env": "ANTHROPIC_API_KEY",
        "modelo": "claude-sonnet-4-5",
    },
}


class ErrorProveedor(RuntimeError):
    """Falla al hablar con la API del modelo."""


class ToolInvalida(ErrorProveedor):
    """El modelo pidio una tool que no esta en el catalogo que se le mando.

    Groq (y otros con validacion del lado del servidor) rechazan el request
    ENTERO con un 400 en vez de devolver la llamada para que el host la
    conteste. Tratarlo como fatal tira la corrida por un nombre mal puesto;
    es un error del modelo, y como cualquier otro error de tool tiene que
    volverle a EL para que lo corrija.
    """

    def __init__(self, mensaje: str, tool: str = "") -> None:
        super().__init__(mensaje)
        self.tool = tool


def _error_de_respuesta(codigo: int, texto: str) -> ErrorProveedor:
    """El 400 que corresponda: tool inexistente se distingue del resto."""
    try:
        detalle = json.loads(texto).get("error") or {}
    except (ValueError, AttributeError, TypeError):
        detalle = {}
    mensaje = str(detalle.get("message", ""))
    if detalle.get("code") == "tool_use_failed" or (
            "not in request.tools" in mensaje):
        m = re.search(r"tool '([^']+)'", mensaje)
        nombre = m.group(1) if m else ""
        return ToolInvalida(
            f"El modelo pidió la tool '{nombre or '?'}', que no está en el "
            "perfil elegido.", nombre)
    return ErrorProveedor(f"El modelo respondió {codigo}: {texto[:600]}")


# Modelos que ACEPTAN imágenes. No hay ninguna API estándar que lo informe,
# así que se reconoce por el nombre — y se falla del lado seguro: si no
# está acá, la interfaz no deja adjuntar. Mandarle una imagen a un modelo
# que no las entiende no da un error claro: unos la ignoran en silencio
# (el agente responde sobre algo que no vio) y otros rechazan el request
# entero con un 400 críptico.
#
# El caso concreto de este proyecto: gpt-oss-120b, el que anda en Groq,
# NO es multimodal. Por eso la interfaz tiene que decirlo en vez de dejar
# subir un croquis que nunca se va a mirar.
PATRONES_VISION = (
    "gpt-4o", "gpt-4-turbo", "gpt-4-vision", "gpt-4.1", "gpt-5",
    "o1", "o3", "o4-mini", "chatgpt-4o",
    "claude-3", "claude-4", "claude-sonnet", "claude-opus", "claude-haiku",
    "gemini", "llava", "bakllava", "pixtral", "molmo", "internvl",
    "qwen-vl", "qwen2-vl", "qwen2.5-vl", "qwen3-vl",
    "llama-3.2-11b", "llama-3.2-90b", "llama-4", "vision",
    "grok-2-vision", "grok-4", "phi-3-vision", "phi-4-multimodal",
    "deepseek-vl", "mistral-small-3", "step-1v", "yi-vision",
)


def soporta_imagenes(modelo: str) -> bool:
    """¿Este modelo puede MIRAR una imagen que se le adjunte?"""
    if not modelo:
        return False
    n = modelo.lower()
    # 'gpt-oss' contiene 'gpt' pero es de solo texto: se descarta primero
    # para que ningún patrón amplio lo dé por multimodal.
    if "gpt-oss" in n or "oss-safeguard" in n:
        return False
    return any(p in n for p in PATRONES_VISION)


def bloque_imagen(data_url: str, formato: str) -> dict[str, Any]:
    """Una imagen en el formato que espera cada proveedor.

    OpenAI la quiere como image_url con el data: adentro; Anthropic la
    quiere partida en media_type y base64 puro. Es la misma imagen
    expresada distinto, y equivocarse acá da un 400 sin explicación.
    """
    if formato == "anthropic":
        cabecera, _, datos = data_url.partition(",")
        tipo = "image/png"
        if cabecera.startswith("data:") and ";" in cabecera:
            tipo = cabecera[5:cabecera.index(";")]
        return {"type": "image",
                "source": {"type": "base64", "media_type": tipo,
                           "data": datos}}
    return {"type": "image_url", "image_url": {"url": data_url}}


class ContadorUso:
    """Tokens consumidos, tal como los informa el proveedor.

    No se estiman: cada respuesta trae su 'usage' exacto. Con ~20k tokens
    de definiciones de tools en CADA vuelta, saber el consumo real mientras
    se trabaja es lo que evita la sorpresa a fin de mes.
    """

    def __init__(self) -> None:
        self.entrada = 0
        self.salida = 0
        self.vueltas = 0

    def anotar_uso(self, uso: dict[str, Any]) -> None:
        if not uso:
            return
        self.entrada += int(uso.get("prompt_tokens")
                            or uso.get("input_tokens") or 0)
        self.salida += int(uso.get("completion_tokens")
                           or uso.get("output_tokens") or 0)
        self.vueltas += 1

    @property
    def total(self) -> int:
        return self.entrada + self.salida

    def resumen(self) -> dict[str, int]:
        return {"entrada": self.entrada, "salida": self.salida,
                "total": self.total, "vueltas": self.vueltas}


class ProveedorOpenAI(ContadorUso):
    """Cliente de /chat/completions con tools (el formato mayoritario)."""

    formato = "openai"

    def __init__(self, url: str, api_key: Optional[str], modelo: str,
                 timeout: float = 180.0,
                 temperatura: Optional[float] = None) -> None:
        super().__init__()
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.modelo = modelo
        self.timeout = timeout
        self.temperatura = temperatura

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        # OpenRouter los pide para atribuir el tráfico; los demás los ignoran.
        h["HTTP-Referer"] = "https://github.com/MiguelAngelCruzVargas/mpc_autocat"
        h["X-Title"] = "AutoCAD MCP"
        return h

    def completar(self, mensajes: list[dict[str, Any]],
                  tools: list[dict[str, Any]]) -> dict[str, Any]:
        cuerpo: dict[str, Any] = {"model": self.modelo, "messages": mensajes}
        if tools:
            cuerpo["tools"] = tools
            cuerpo["tool_choice"] = "auto"
        if self.temperatura is not None:
            cuerpo["temperature"] = self.temperatura

        try:
            r = httpx.post(f"{self.url}/chat/completions", json=cuerpo,
                           headers=self._headers(), timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise ErrorProveedor(
                f"No se pudo llamar a {self.url}: {exc}") from exc

        if r.status_code >= 400:
            raise _error_de_respuesta(r.status_code, r.text)
        datos = r.json()
        if not datos.get("choices"):
            raise ErrorProveedor(
                f"Respuesta sin 'choices': {json.dumps(datos)[:400]}")
        # El consumo se acumula acá y no lo estima nadie: los proveedores
        # lo informan exacto, y con 20k tokens de definiciones por vuelta
        # conviene tenerlo a la vista antes de que llegue la factura.
        self.anotar_uso(datos.get("usage") or {})
        return datos["choices"][0]["message"]


class ProveedorAnthropic(ContadorUso):
    """Cliente de /messages. Anthropic no usa el formato de OpenAI."""

    formato = "anthropic"

    def __init__(self, url: str, api_key: Optional[str], modelo: str,
                 timeout: float = 180.0, max_tokens: int = 8192,
                 temperatura: Optional[float] = None) -> None:
        super().__init__()
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.modelo = modelo
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperatura = temperatura

    def completar(self, mensajes: list[dict[str, Any]],
                  tools: list[dict[str, Any]]) -> dict[str, Any]:
        # El system va en su propio campo, no como un mensaje más.
        system = "\n\n".join(m["content"] for m in mensajes
                             if m.get("role") == "system")
        conversacion = [m for m in mensajes if m.get("role") != "system"]

        cuerpo: dict[str, Any] = {
            "model": self.modelo,
            "max_tokens": self.max_tokens,
            "messages": conversacion,
        }
        if system:
            cuerpo["system"] = system
        if tools:
            cuerpo["tools"] = [{
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "input_schema": t["function"]["parameters"],
            } for t in tools]
        if self.temperatura is not None:
            cuerpo["temperature"] = self.temperatura

        try:
            r = httpx.post(f"{self.url}/messages", json=cuerpo, timeout=self.timeout,
                           headers={"Content-Type": "application/json",
                                    "x-api-key": self.api_key or "",
                                    "anthropic-version": "2023-06-01"})
        except httpx.HTTPError as exc:
            raise ErrorProveedor(
                f"No se pudo llamar a {self.url}: {exc}") from exc
        if r.status_code >= 400:
            raise ErrorProveedor(
                f"El modelo respondió {r.status_code}: {r.text[:600]}")
        datos = r.json()
        self.anotar_uso(datos.get("usage") or {})
        return datos


def modelos_disponibles(proveedor: str, api_key: Optional[str] = None,
                        url: Optional[str] = None,
                        probar: bool = False) -> list[dict[str, Any]]:
    """Qué modelos ofrece el proveedor, y opcionalmente cuáles FUNCIONAN.

    Listar no alcanza: una cuenta puede tener modelos en su catálogo que
    la organización tiene bloqueados, y eso solo se ve al llamarlos. Pasó
    de verdad con una clave de Groq -- los siete modelos de chat figuraban
    en /models y los siete devolvían 403 'blocked at the organization
    level'. Con probar=True se le manda un "hola" de 5 tokens a cada uno,
    que cuesta centavos y ahorra descubrir el bloqueo a mitad de un plano.
    """
    preset = PRESETS.get(proveedor, {})
    base = (url or preset.get("url", "")).rstrip("/")
    from . import credenciales
    clave = credenciales.resolver(proveedor, api_key, preset.get("env", ""))

    headers = {"Content-Type": "application/json"}
    if proveedor == "anthropic":
        headers["x-api-key"] = clave or ""
        headers["anthropic-version"] = "2023-06-01"
    elif clave:
        headers["Authorization"] = f"Bearer {clave}"

    try:
        r = httpx.get(f"{base}/models", headers=headers, timeout=30.0)
    except httpx.HTTPError as exc:
        raise ErrorProveedor(f"No se pudo listar modelos: {exc}") from exc
    if r.status_code >= 400:
        raise ErrorProveedor(
            f"El proveedor respondió {r.status_code}: {r.text[:400]}")

    datos = r.json()
    crudos = datos.get("data", datos.get("models", []))
    salida: list[dict[str, Any]] = []
    for m in crudos:
        nombre = m.get("id") or m.get("name") or str(m)
        salida.append({"modelo": nombre, "estado": "?"})

    if not probar:
        return salida

    for fila in salida:
        nombre = fila["modelo"]
        # Los de audio y los clasificadores no hacen chat: probarlos solo
        # gasta tiempo y devuelve un error que confunde.
        if any(p in nombre.lower() for p in ("whisper", "tts", "embed",
                                             "guard", "orpheus")):
            fila["estado"] = "no es de chat"
            continue
        try:
            rr = httpx.post(
                f"{base}/chat/completions", headers=headers, timeout=30.0,
                json={"model": nombre, "max_tokens": 5,
                      "messages": [{"role": "user", "content": "hola"}],
                      "tools": [{"type": "function", "function": {
                          "name": "ping", "description": "prueba",
                          "parameters": {"type": "object", "properties": {}}}}]})
            if rr.status_code < 400:
                fila["estado"] = "OK (acepta tools)"
            elif rr.status_code == 403:
                fila["estado"] = "bloqueado por la organizacion"
            elif "tool" in rr.text.lower():
                fila["estado"] = "responde, pero NO acepta tools"
            else:
                fila["estado"] = f"error {rr.status_code}"
        except httpx.HTTPError as exc:
            fila["estado"] = f"sin respuesta ({type(exc).__name__})"
    return salida


def construir(proveedor: str, modelo: Optional[str] = None,
              url: Optional[str] = None, api_key: Optional[str] = None,
              temperatura: Optional[float] = None) -> Any:
    """Arma el cliente del proveedor pedido, con sus defaults."""
    preset = PRESETS.get(proveedor)
    if preset is None and not url:
        raise ErrorProveedor(
            f"Proveedor '{proveedor}' desconocido. Conocidos: "
            f"{', '.join(sorted(PRESETS))}. O pasá --url con un endpoint "
            "compatible con OpenAI.")
    preset = preset or {}
    base = url or preset.get("url", "")
    # --api-key > variable de entorno > lo guardado con `config set`.
    from . import credenciales
    clave = credenciales.resolver(proveedor, api_key,
                                  preset.get("env", "")) or ""
    nombre_modelo = modelo or preset.get("modelo", "")

    if not nombre_modelo:
        raise ErrorProveedor("Falta --modelo.")
    # Un endpoint local no necesita clave; uno remoto sí, y decirlo acá
    # ahorra un 401 incomprensible más adelante.
    if not clave and base.startswith("https://"):
        raise ErrorProveedor(
            f"Falta la API key de '{proveedor}'. Guardala una sola vez con:\n"
            f"    python -m agent.cli config set {proveedor}\n"
            f"(te la pide sin mostrarla en pantalla y queda cifrada). "
            f"O usá la variable {preset.get('env', 'API_KEY')}.")

    if proveedor == "anthropic":
        return ProveedorAnthropic(base, clave, nombre_modelo,
                                  temperatura=temperatura)
    return ProveedorOpenAI(base, clave, nombre_modelo,
                           temperatura=temperatura)
