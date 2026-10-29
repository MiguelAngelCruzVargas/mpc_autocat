"""Qué NO puede hacer el modelo elegido, dicho con palabras para la persona.

El panel muestra estos avisos al elegir un modelo («este modelo está limitado: no ve imágenes»), en vez de dejar que
se descubra por un 400 críptico o por un agente que responde sobre algo que nunca vio. Se reconoce por el nombre (no hay
API estándar que lo informe) y se falla del lado cauteloso: un aviso de más es mejor que una promesa falsa.
"""
from __future__ import annotations

from typing import Any

from . import descubrir, providers

# No son modelos de conversación: no pueden llevar el agente.
NO_CHAT = ("whisper", "tts", "playai", "orpheus", "embed", "guard", "moderation", "rerank", "dall-e", "stable-diffusion", "sdxl")

# Modelos chicos: sirven para pedidos simples, fallan con pedidos largos y muchas herramientas.
PALABRAS_CHICO = {"mini", "nano", "lite", "tiny", "small", "instant", "flash-lite"}
MAX_B_CHICO = 20.0      # hasta 20 mil millones de parametros se considera chico


def es_pequeno(nombre: str) -> bool:
    """Por palabras sueltas («mini» no esta en «gemini») y por tamano en miles de millones («8b», «20b»)."""
    import re
    fichas = re.split(r"[^a-z0-9.]+", nombre.lower())
    if any(f in PALABRAS_CHICO for f in fichas):
        return True
    for f in fichas:
        m = re.fullmatch(r"(\d+(?:\.\d+)?)b", f)
        if m and float(m.group(1)) <= MAX_B_CHICO:
            return True
    return False


def evaluar(proveedor: str, modelo: str) -> dict[str, Any]:
    """{limitado, imagenes, avisos: [{nivel, etiqueta, texto}]} para un proveedor y modelo."""
    n = (modelo or "").lower()
    avisos: list[dict[str, str]] = []

    def aviso(nivel: str, etiqueta: str, texto: str) -> None:
        avisos.append({"nivel": nivel, "etiqueta": etiqueta, "texto": texto})

    imagenes = providers.soporta_imagenes(modelo)
    if not modelo:
        return {"limitado": False, "imagenes": False, "avisos": []}

    if any(p in n for p in NO_CHAT):
        aviso("alto", "no es de chat", "Este no es un modelo de conversación (voz, moderación o búsqueda): no puede dibujar ni usar herramientas. Elige otro.")
        return {"limitado": True, "imagenes": False, "avisos": avisos}

    if not imagenes:
        aviso("medio", "no ve imágenes", "Este modelo está limitado: no puede ver imágenes. No va a poder mirar capturas del dibujo ni croquis que le adjuntes; trabaja solo con lo que le cuentan las herramientas.")

    if es_pequeno(n):
        aviso("medio", "modelo pequeño", "Modelo pequeño: sirve para dibujo simple, pero puede equivocarse en pedidos largos, planos completos o al elegir entre muchas herramientas. Para algo serio usa uno más grande.")

    if proveedor == "local":
        aviso("medio", "herramientas dudosas", "Los modelos locales muchas veces no saben llamar herramientas: si no dibuja, es el modelo, no AutoCAD.")

    limite = descubrir.LIMITES.get(proveedor)
    if limite:
        aviso("bajo", f"máx. {limite} herramientas", f"Este proveedor acepta máximo {limite} herramientas por pedido: el agente las busca bajo demanda (cada pedido tarda una vuelta más).")

    return {"limitado": any(a["nivel"] != "bajo" for a in avisos), "imagenes": imagenes, "avisos": avisos}
