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
        "modelo": "llama-3.3-70b-versatile",
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


class ProveedorOpenAI:
    """Cliente de /chat/completions con tools (el formato mayoritario)."""

    formato = "openai"

    def __init__(self, url: str, api_key: Optional[str], modelo: str,
                 timeout: float = 180.0,
                 temperatura: Optional[float] = None) -> None:
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
            raise ErrorProveedor(
                f"El modelo respondió {r.status_code}: {r.text[:600]}")
        datos = r.json()
        if not datos.get("choices"):
            raise ErrorProveedor(
                f"Respuesta sin 'choices': {json.dumps(datos)[:400]}")
        return datos["choices"][0]["message"]


class ProveedorAnthropic:
    """Cliente de /messages. Anthropic no usa el formato de OpenAI."""

    formato = "anthropic"

    def __init__(self, url: str, api_key: Optional[str], modelo: str,
                 timeout: float = 180.0, max_tokens: int = 8192,
                 temperatura: Optional[float] = None) -> None:
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
        return r.json()


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
