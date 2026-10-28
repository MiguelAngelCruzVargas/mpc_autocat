"""Los modelos que puede usar el chat: Claude (API de Anthropic) y Groq (API compatible con OpenAI).

El agente (chat_server.Sesion) no sabe con quién habla. Guarda la conversación en un formato NEUTRO y cada
proveedor la traduce al suyo y le devuelve un `Turno`:

    historial = [{"role": "user", "texto": "..."},
                 {"role": "assistant", "texto": "...", "llamadas": [{"id", "nombre", "entrada"}]},
                 {"role": "herramienta", "id": "...", "contenido": "...", "error": False}]

Las herramientas de AutoCAD son las mismas para los dos: lo único que cambia es el modelo que decide cuál usar.
Un modelo abierto en Groq es mucho más barato y rápido que Claude, pero se equivoca más al elegir herramientas y al
armar sus argumentos: por eso un argumento que no es JSON válido vuelve al modelo como error en vez de ejecutarse
a medias, y por eso lo que modifica el dibujo se pide siempre al usuario, con el modelo que sea.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Turno:
    texto: str = ""
    llamadas: list[dict[str, Any]] = field(default_factory=list)    # {"id", "nombre", "entrada", "error"?}
    parada: str = ""
    uso: dict[str, int] = field(default_factory=lambda: {"entrada": 0, "salida": 0, "cache": 0})


class ErrorAPI(Exception):
    """Un error de la API del proveedor, con su código HTTP y el código de error que dio el proveedor."""

    def __init__(self, estado: int, mensaje: str, codigo: str = ""):
        super().__init__(mensaje)
        self.status_code = estado
        self.codigo = codigo


class Proveedor:
    id = ""
    nombre = ""
    sitio_clave = ""
    prefijo_clave = ""

    def __init__(self, clave: str):
        self.clave = clave

    def turno(self, modelo: str, sistema: str, herramientas: list[dict[str, Any]], historial: list[dict[str, Any]],
              emitir_texto: Callable[[str], None], parar: Callable[[], bool]) -> Turno:
        raise NotImplementedError

    def modelos(self) -> list[tuple[str, str]]:
        raise NotImplementedError


# -------------------------------------------------------------------------------------------------- Anthropic

MODELOS_ANTHROPIC = [("claude-sonnet-5-5", "Sonnet 5.5 (recomendado)"), ("claude-haiku-5-5", "Haiku 5.5 (rápido y barato)"),
                     ("claude-opus-5-5", "Opus 5.5 (el más capaz)")]


class ProvAnthropic(Proveedor):
    id = "anthropic"
    nombre = "Claude (Anthropic)"
    sitio_clave = "console.anthropic.com"
    prefijo_clave = "sk-ant-"

    def __init__(self, clave: str, cliente: Any = None):
        super().__init__(clave)
        self._cliente = cliente

    @property
    def cliente(self) -> Any:
        if self._cliente is None:
            import anthropic
            self._cliente = anthropic.Anthropic(api_key=self.clave, max_retries=2)
        return self._cliente

    @staticmethod
    def convertir(historial: list[dict[str, Any]]) -> list[dict[str, Any]]:
        mensajes: list[dict[str, Any]] = []
        for m in historial:
            if m["role"] == "user":
                mensajes.append({"role": "user", "content": m["texto"]})
            elif m["role"] == "assistant":
                bloques: list[dict[str, Any]] = []
                if m.get("texto"):
                    bloques.append({"type": "text", "text": m["texto"]})
                for ll in m.get("llamadas", []):
                    bloques.append({"type": "tool_use", "id": ll["id"], "name": ll["nombre"], "input": ll["entrada"]})
                mensajes.append({"role": "assistant", "content": bloques or [{"type": "text", "text": "(sin texto)"}]})
            else:
                bloque = {"type": "tool_result", "tool_use_id": m["id"], "content": m["contenido"], "is_error": bool(m.get("error"))}
                if mensajes and mensajes[-1]["role"] == "user" and isinstance(mensajes[-1]["content"], list):
                    mensajes[-1]["content"].append(bloque)
                else:
                    mensajes.append({"role": "user", "content": [bloque]})
        return mensajes

    def turno(self, modelo, sistema, herramientas, historial, emitir_texto, parar) -> Turno:
        with self.cliente.messages.stream(
                model=modelo, max_tokens=8192,
                system=[{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
                tools=herramientas, messages=self.convertir(historial)) as flujo:
            for trozo in flujo.text_stream:
                emitir_texto(trozo)
                if parar():
                    break
            final = flujo.get_final_message()
        t = Turno(parada=getattr(final, "stop_reason", "") or "")
        for b in final.content:
            tipo = getattr(b, "type", None)
            if tipo == "text":
                t.texto += b.text
            elif tipo == "tool_use":
                t.llamadas.append({"id": b.id, "nombre": b.name, "entrada": b.input or {}})
        u = getattr(final, "usage", None)
        if u:
            t.uso = {"entrada": getattr(u, "input_tokens", 0) or 0, "salida": getattr(u, "output_tokens", 0) or 0,
                     "cache": getattr(u, "cache_read_input_tokens", 0) or 0}
        return t

    def modelos(self) -> list[tuple[str, str]]:
        return list(MODELOS_ANTHROPIC)


# -------------------------------------------------------------------------------------------------- Groq

URL_GROQ = "https://api.groq.com/openai/v1"
# Respaldo mientras no hay clave (con ella la lista sale de la API de Groq, que es la que manda: los modelos cambian).
MODELOS_GROQ = [("openai/gpt-oss-120b", "gpt-oss-120b (el más capaz)"), ("openai/gpt-oss-20b", "gpt-oss-20b (más rápido y barato)")]
NO_SON_DE_CHAT = ("whisper", "tts", "guard", "embed", "orpheus", "playai", "compound", "safeguard", "moderation")


class ProvGroq(Proveedor):
    id = "groq"
    nombre = "Groq (modelos abiertos)"
    sitio_clave = "console.groq.com"
    prefijo_clave = "gsk_"

    def __init__(self, clave: str, transporte: Any = None, url: str = URL_GROQ):
        super().__init__(clave)
        self.transporte = transporte
        self.url = url

    def _cliente(self, limite: float = 120.0) -> Any:
        import httpx
        return httpx.Client(timeout=httpx.Timeout(limite, connect=10.0), transport=self.transporte,
                            headers={"Authorization": f"Bearer {self.clave}", "Content-Type": "application/json"})

    @staticmethod
    def convertir(sistema: str, historial: list[dict[str, Any]]) -> list[dict[str, Any]]:
        mensajes: list[dict[str, Any]] = [{"role": "system", "content": sistema}]
        for m in historial:
            if m["role"] == "user":
                mensajes.append({"role": "user", "content": m["texto"]})
            elif m["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": m.get("texto") or (None if m.get("llamadas") else "")}
                if m.get("llamadas"):
                    msg["tool_calls"] = [{"id": ll["id"], "type": "function",
                                          "function": {"name": ll["nombre"], "arguments": json.dumps(ll["entrada"], ensure_ascii=False)}}
                                         for ll in m["llamadas"]]
                mensajes.append(msg)
            else:
                mensajes.append({"role": "tool", "tool_call_id": m["id"], "content": m["contenido"]})
        return mensajes

    @staticmethod
    def herramientas(herramientas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {"name": h["name"], "description": h["description"], "parameters": h["input_schema"]}}
                for h in herramientas]

    @staticmethod
    def _error(r: Any) -> ErrorAPI:
        try:
            cuerpo = json.loads(r.read().decode("utf-8", "replace"))
            e = cuerpo.get("error", {}) if isinstance(cuerpo, dict) else {}
            return ErrorAPI(r.status_code, e.get("message") or str(cuerpo)[:300], e.get("code") or e.get("type") or "")
        except (ValueError, AttributeError):
            return ErrorAPI(r.status_code, "respuesta sin detalle")

    def turno(self, modelo, sistema, herramientas, historial, emitir_texto, parar) -> Turno:
        carga = {"model": modelo, "messages": self.convertir(sistema, historial), "tools": self.herramientas(herramientas),
                 "stream": True, "max_completion_tokens": 8192}
        t = Turno()
        parciales: dict[int, dict[str, Any]] = {}
        with self._cliente() as c:
            with c.stream("POST", self.url + "/chat/completions", json=carga) as r:
                if r.status_code != 200:
                    raise self._error(r)
                for linea in r.iter_lines():
                    if not linea.startswith("data:"):
                        continue
                    dato = linea[5:].strip()
                    if dato == "[DONE]":
                        break
                    try:
                        trozo = json.loads(dato)
                    except ValueError:
                        continue
                    if trozo.get("error"):
                        e = trozo["error"]
                        raise ErrorAPI(int(e.get("status", 500) or 500), e.get("message", "error"), e.get("code", ""))
                    uso = trozo.get("usage") or (trozo.get("x_groq") or {}).get("usage")
                    if uso:
                        det = uso.get("prompt_tokens_details") or {}
                        t.uso = {"entrada": uso.get("prompt_tokens", 0) or 0, "salida": uso.get("completion_tokens", 0) or 0,
                                 "cache": det.get("cached_tokens", 0) or 0}
                    for ch in trozo.get("choices") or []:
                        d = ch.get("delta") or {}
                        if d.get("content"):
                            t.texto += d["content"]
                            emitir_texto(d["content"])
                        for tc in d.get("tool_calls") or []:
                            p = parciales.setdefault(tc.get("index", 0), {"id": "", "nombre": "", "args": ""})
                            if tc.get("id"):
                                p["id"] = tc["id"]
                            f = tc.get("function") or {}
                            if f.get("name"):
                                p["nombre"] += f["name"]
                            if f.get("arguments"):
                                p["args"] += f["arguments"]
                        if ch.get("finish_reason"):
                            t.parada = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens"}.get(ch["finish_reason"], ch["finish_reason"])
                    if parar():
                        break
        for i in sorted(parciales):
            p = parciales[i]
            entrada, error = {}, False
            if p["args"].strip():
                try:
                    entrada = json.loads(p["args"])
                    error = not isinstance(entrada, dict)
                except ValueError:
                    error = True
            t.llamadas.append({"id": p["id"] or f"call_{i}", "nombre": p["nombre"], "entrada": entrada if isinstance(entrada, dict) else {},
                               "error": error, "crudo": p["args"][:300]})
        if t.llamadas:
            t.parada = "tool_use"
        return t

    def modelos(self) -> list[tuple[str, str]]:
        if not self.clave:
            return list(MODELOS_GROQ)
        try:
            with self._cliente(8.0) as c:
                r = c.get(self.url + "/models")
            if r.status_code != 200:
                return list(MODELOS_GROQ)
            ids = [m["id"] for m in r.json().get("data", []) if m.get("active", True)
                   and not any(x in m["id"].lower() for x in NO_SON_DE_CHAT)]
        except Exception:                                   # noqa: BLE001
            return list(MODELOS_GROQ)
        ids.sort(key=lambda i: (i != "openai/gpt-oss-120b", i != "openai/gpt-oss-20b", i))
        return [(i, i) for i in ids] or list(MODELOS_GROQ)


PROVEEDORES: dict[str, type] = {"anthropic": ProvAnthropic, "groq": ProvGroq}


def mensaje_amable(e: Exception, proveedor: str = "anthropic") -> str:
    """El error de la API en español y sin traza."""
    de = "de Groq" if proveedor == "groq" else "de API"
    estado = getattr(e, "status_code", None)
    codigo = getattr(e, "codigo", "") or ""
    if estado == 401:
        return f"La clave {de} no es válida. Revísala en Ajustes."
    if estado == 403:
        return f"La clave {de} no tiene permiso para este modelo."
    if estado == 404:
        return "Ese modelo no existe o tu cuenta no tiene acceso. Elige otro en la lista."
    if estado == 413 or codigo == "rate_limit_exceeded" and "tokens per minute" in str(e).lower():
        return "Se pasó el límite de tokens por minuto del plan. Espera un momento o elige un modelo con más margen."
    if estado == 429:
        return "Se alcanzó el límite de uso. Espera un momento e inténtalo de nuevo."
    if estado == 400 and codigo == "tool_use_failed":
        return "El modelo armó mal una llamada a herramienta. Reintenta, o elige un modelo más capaz."
    if estado == 400 and "credit" in str(e).lower():
        return "La cuenta de la API se quedó sin saldo."
    if estado in (500, 502, 503, 529):
        return "El servicio del modelo está saturado. Inténtalo de nuevo en un momento."
    return f"Error al hablar con el modelo: {e}"
