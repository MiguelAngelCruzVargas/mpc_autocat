"""IA incluida: el servidor de licencias hace de intermediario con la IA de Vigentra.

El cliente elige en su configuración entre «IA incluida en mi plan» (este
módulo) o «mi propia clave» (OpenAI, Anthropic, OpenRouter...). Con la incluida:

  - Se autentica con el TOKEN firmado de su licencia (el mismo de licencia.json),
    no con la clave de licencia: la clave nunca viaja y la de la IA de Vigentra
    nunca sale de este servidor.
  - Cada plan trae un crédito mensual en dólares de costo de IA (IA_CREDITO_USD),
    que se reinicia el día 1. La prueba de 7 días trae el suyo, por equipo.
    Vigentra puede sumar paquetes extra a una licencia (/admin/ia_credito), que
    se gastan después del mensual y no caducan.
  - Se cobra lo que reporta el proveedor (OpenRouter devuelve el costo de cada
    llamada); si no lo reporta, se calcula con IA_PRECIOS. Se revisa el saldo
    antes de cada llamada y se descuenta al terminar: como mucho se pasa por
    una llamada.
  - Al acabarse, responde 402 con un mensaje que dice qué hacer: usar su propia
    clave o pedir un paquete.

Habla el formato de OpenAI (/chat/completions con tools), así que para el
producto es un proveedor más. Sin IA_UPSTREAM_KEY o sin IA_CREDITO_USD queda
APAGADO (404): nunca gasta por accidente.

Variables de entorno:
  IA_UPSTREAM_URL       por defecto https://openrouter.ai/api/v1
  IA_UPSTREAM_KEY       la clave de IA de Vigentra (secreta)
  IA_MODELO             el modelo que se usa (el cliente no lo puede cambiar)
  IA_CREDITO_USD        JSON por plan, ej. {"mensual": 4, "anual": 4, "perpetua": 0, "prueba": 1}
  IA_PRECIOS            opcional: {"modelo": {"entrada": 3.0, "salida": 15.0}} en US$ por millón de tokens
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

MAX_CUERPO = 4 * 1024 * 1024        # las definiciones de herramientas pesan
TIEMPO_LIMITE = 300
MENSAJE_SIN_CREDITO = ("Se acabó el crédito de IA incluido en tu plan este mes. Puedes seguir con tu propia clave "
                       "(Configuración → Proveedor de IA) o pedir un paquete de crédito a Vigentra. "
                       "El crédito del plan se renueva el día 1.")


class ErrorIA(Exception):
    def __init__(self, mensaje: str, codigo: int = 400):
        super().__init__(mensaje)
        self.codigo = codigo


def _b64u_dec(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def verificar_token(publica: ec.EllipticCurvePublicKey, token: str) -> dict[str, Any]:
    """El payload del token si la firma es nuestra; ErrorIA si no."""
    try:
        cuerpo_b64, firma_b64 = token.split(".")
        cuerpo, firma = _b64u_dec(cuerpo_b64), _b64u_dec(firma_b64)
        if len(firma) != 64:
            raise ValueError("firma")
        der = encode_dss_signature(int.from_bytes(firma[:32], "big"), int.from_bytes(firma[32:], "big"))
        publica.verify(der, cuerpo, ec.ECDSA(hashes.SHA256()))
        payload = json.loads(cuerpo)
        if not isinstance(payload, dict):
            raise ValueError("payload")
        return payload
    except (ValueError, InvalidSignature, TypeError):
        raise ErrorIA("Licencia no válida para la IA incluida. Vuelve a activar tu licencia.", 401) from None


class ServicioIA:
    def __init__(self, ruta_db: str, publica: ec.EllipticCurvePublicKey, *, upstream_url: str, upstream_key: str,
                 modelo: str, creditos: dict[str, float], precios: Optional[dict[str, dict[str, float]]] = None,
                 estado_licencia: Optional[Callable[[str], Optional[str]]] = None,
                 llamar: Optional[Callable[[str, dict[str, str], bytes], tuple[int, bytes]]] = None,
                 ahora: Callable[[], float] = time.time):
        self.publica = publica
        self.upstream_url = upstream_url.rstrip("/")
        self.upstream_key = upstream_key
        self.modelo = modelo
        self.creditos = {k: max(0.0, float(v)) for k, v in creditos.items()}
        self.precios = precios or {}
        # Para no aceptar tokens de una licencia revocada (el token dura 7 días).
        self.estado_licencia = estado_licencia or (lambda kid: "activa")
        self.llamar = llamar or self._llamar_http
        self.ahora = ahora
        self._lock = threading.Lock()
        self.db = sqlite3.connect(ruta_db, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS ia_uso (
                cuenta TEXT NOT NULL, mes TEXT NOT NULL, usd REAL NOT NULL DEFAULT 0,
                tokens_entrada INTEGER NOT NULL DEFAULT 0, tokens_salida INTEGER NOT NULL DEFAULT 0,
                llamadas INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (cuenta, mes));
            CREATE TABLE IF NOT EXISTS ia_extra (
                cuenta TEXT PRIMARY KEY, comprado REAL NOT NULL DEFAULT 0, gastado REAL NOT NULL DEFAULT 0);
        """)
        self.db.commit()

    # ------------------------------------------------------------------ cuentas
    def _mes(self) -> str:
        return time.strftime("%Y-%m", time.gmtime(self.ahora()))

    def cuenta_de(self, token: str) -> tuple[str, str]:
        """(cuenta, plan) del token. La prueba es una cuenta por equipo."""
        p = verificar_token(self.publica, token)
        if int(p.get("valido_hasta") or 0) < self.ahora():
            raise ErrorIA("Tu licencia necesita renovarse (abre Architech con internet).", 401)
        kid, plan, maquina = str(p.get("kid") or ""), str(p.get("plan") or ""), str(p.get("maquina") or "")
        if not kid or not plan:
            raise ErrorIA("Licencia no válida para la IA incluida.", 401)
        if kid == "prueba":
            return "prueba:" + maquina, "prueba"
        if self.estado_licencia(kid) != "activa":
            raise ErrorIA("Esta licencia no está activa.", 403)
        return kid, plan

    def saldo(self, cuenta: str, plan: str) -> dict[str, Any]:
        mes = self._mes()
        with self._lock:
            fila = self.db.execute("SELECT * FROM ia_uso WHERE cuenta=? AND mes=?", (cuenta, mes)).fetchone()
            extra = self.db.execute("SELECT * FROM ia_extra WHERE cuenta=?", (cuenta,)).fetchone()
        del_plan = self.creditos.get(plan, 0.0)
        usado = fila["usd"] if fila else 0.0
        extra_libre = (extra["comprado"] - extra["gastado"]) if extra else 0.0
        return {"mes": mes, "plan": plan, "credito_del_plan_usd": round(del_plan, 4),
                "usado_este_mes_usd": round(usado, 4),
                "restante_del_plan_usd": round(max(0.0, del_plan - usado), 4),
                "extra_usd": round(max(0.0, extra_libre), 4),
                "restante_usd": round(max(0.0, del_plan - usado) + max(0.0, extra_libre), 4),
                "llamadas_este_mes": fila["llamadas"] if fila else 0, "modelo": self.modelo}

    def _cobrar(self, cuenta: str, plan: str, usd: float, entrada: int, salida: int) -> None:
        mes = self._mes()
        with self._lock:
            fila = self.db.execute("SELECT usd FROM ia_uso WHERE cuenta=? AND mes=?", (cuenta, mes)).fetchone()
            extra = self.db.execute("SELECT comprado, gastado FROM ia_extra WHERE cuenta=?", (cuenta,)).fetchone()
            usado = fila["usd"] if fila else 0.0
            libre_plan = max(0.0, self.creditos.get(plan, 0.0) - usado)
            libre_extra = max(0.0, (extra["comprado"] - extra["gastado"]) if extra else 0.0)
            # Lo que no cubre el crédito del mes sale de los paquetes extra, hasta donde alcancen. Lo que se pase
            # en la ÚLTIMA llamada lo absorbe Vigentra: no se le cobra al cliente de su próximo paquete.
            al_extra = min(max(0.0, usd - libre_plan), libre_extra)
            self.db.execute("""INSERT INTO ia_uso (cuenta, mes, usd, tokens_entrada, tokens_salida, llamadas)
                               VALUES (?,?,?,?,?,1) ON CONFLICT(cuenta, mes) DO UPDATE SET
                               usd=usd+excluded.usd, tokens_entrada=tokens_entrada+excluded.tokens_entrada,
                               tokens_salida=tokens_salida+excluded.tokens_salida, llamadas=llamadas+1""",
                            (cuenta, mes, usd - al_extra, entrada, salida))
            if al_extra > 0:
                self.db.execute("INSERT INTO ia_extra (cuenta, comprado, gastado) VALUES (?,0,?) "
                                "ON CONFLICT(cuenta) DO UPDATE SET gastado=gastado+excluded.gastado", (cuenta, al_extra))
            self.db.commit()

    def sumar_extra(self, cuenta: str, usd: float) -> dict[str, Any]:
        """Paquete de crédito comprado (lo usa la administración o el cobro)."""
        if not isinstance(usd, (int, float)) or not 0 < usd <= 1000:
            raise ErrorIA("'usd' va de 0 a 1000.")
        with self._lock:
            self.db.execute("INSERT INTO ia_extra (cuenta, comprado, gastado) VALUES (?,?,0) "
                            "ON CONFLICT(cuenta) DO UPDATE SET comprado=comprado+excluded.comprado", (cuenta, float(usd)))
            self.db.commit()
            fila = self.db.execute("SELECT * FROM ia_extra WHERE cuenta=?", (cuenta,)).fetchone()
        return {"cuenta": cuenta, "comprado_usd": fila["comprado"], "gastado_usd": round(fila["gastado"], 4)}

    def uso(self, mes: Optional[str] = None) -> list[dict[str, Any]]:
        with self._lock:
            filas = self.db.execute("SELECT * FROM ia_uso WHERE mes=? ORDER BY usd DESC", (mes or self._mes(),)).fetchall()
        return [dict(f) for f in filas]

    # ------------------------------------------------------------------ llamada
    def costo(self, uso: dict[str, Any]) -> float:
        if isinstance(uso.get("cost"), (int, float)):
            return float(uso["cost"])
        precio = self.precios.get(self.modelo)
        entrada, salida = int(uso.get("prompt_tokens") or 0), int(uso.get("completion_tokens") or 0)
        if not precio:
            # Sin costo reportado ni precio configurado, cobrar cero sería regalar la IA.
            raise ErrorIA("La IA incluida no está bien configurada (falta el precio del modelo).", 503)
        return (entrada * precio.get("entrada", 0) + salida * precio.get("salida", 0)) / 1_000_000

    def _llamar_http(self, url: str, headers: dict[str, str], cuerpo: bytes) -> tuple[int, bytes]:
        req = urllib.request.Request(url, data=cuerpo, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIEMPO_LIMITE) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ErrorIA("No se pudo contactar a la IA en este momento. Intenta de nuevo.", 502) from exc

    def completar(self, token: str, pedido: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, Any]]:
        """(código, respuesta del proveedor, saldo después)."""
        cuenta, plan = self.cuenta_de(token)
        antes = self.saldo(cuenta, plan)
        if antes["restante_usd"] <= 0:
            raise ErrorIA(MENSAJE_SIN_CREDITO, 402)
        cuerpo = {k: v for k, v in pedido.items() if k in ("messages", "tools", "tool_choice", "temperature", "max_tokens")}
        if not isinstance(cuerpo.get("messages"), list) or not cuerpo["messages"]:
            raise ErrorIA("Falta 'messages'.")
        cuerpo["model"] = self.modelo          # el cliente no elige un modelo más caro
        cuerpo["usage"] = {"include": True}    # OpenRouter: que devuelva el costo de la llamada
        cuerpo["stream"] = False
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + self.upstream_key,
                   "HTTP-Referer": "https://vigentra.mx", "X-Title": "Vigentra Architech"}
        codigo, crudo = self.llamar(self.upstream_url + "/chat/completions", headers, json.dumps(cuerpo).encode())
        try:
            datos = json.loads(crudo or b"{}")
        except ValueError:
            raise ErrorIA("La IA respondió algo que no se entiende. Intenta de nuevo.", 502) from None
        if codigo >= 400:
            # Sin detalles del proveedor (podrían mencionar nuestra cuenta).
            return (502 if codigo >= 500 or codigo in (401, 403) else codigo,
                    {"error": {"message": "La IA no pudo responder (%d). Intenta de nuevo en un momento." % codigo}},
                    antes)
        uso = datos.get("usage") or {}
        self._cobrar(cuenta, plan, self.costo(uso), int(uso.get("prompt_tokens") or 0),
                     int(uso.get("completion_tokens") or 0))
        datos.pop("provider", None)
        return 200, datos, self.saldo(cuenta, plan)


def desde_entorno(ruta_db: str, publica: ec.EllipticCurvePublicKey,
                  estado_licencia: Callable[[str], Optional[str]]) -> Optional[ServicioIA]:
    """El servicio si está configurado; None (apagado) si falta la clave o los créditos."""
    clave = os.environ.get("IA_UPSTREAM_KEY", "").strip()
    creditos = os.environ.get("IA_CREDITO_USD", "").strip()
    if not clave or not creditos:
        return None
    return ServicioIA(ruta_db, publica, upstream_url=os.environ.get("IA_UPSTREAM_URL", "https://openrouter.ai/api/v1"),
                      upstream_key=clave, modelo=os.environ.get("IA_MODELO", "anthropic/claude-sonnet-5.5"),
                      creditos=json.loads(creditos), precios=json.loads(os.environ.get("IA_PRECIOS") or "{}"),
                      estado_licencia=estado_licencia)
