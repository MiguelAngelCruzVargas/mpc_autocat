"""Host de agente para el MCP de AutoCAD, con el modelo que elijas.

El servidor MCP de este repo nunca supo quién lo llama: habla MCP por stdio
y nada más. Lo que ataba el proyecto a Claude Code no era el servidor, era
que faltaba el HOST — el proceso que lanza el servidor, le pide el catálogo
de tools, se lo traduce a un modelo y ejecuta lo que ese modelo pide.

    python -m agent.cli --proveedor openrouter --modelo <el que quieras>

Funciona con cualquier endpoint que hable el formato de OpenAI (OpenRouter,
OpenAI, Groq, DeepSeek, Together, LM Studio, Ollama) y también con la API
de Anthropic, que tiene el suyo propio.
"""
from .mcp_link import ConexionMcp, SERVIDOR_DEFECTO   # noqa: F401
from .loop import conversar                            # noqa: F401

__all__ = ["ConexionMcp", "SERVIDOR_DEFECTO", "conversar"]
