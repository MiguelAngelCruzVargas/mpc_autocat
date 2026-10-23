"""Cobro con Stripe de las licencias de AutoCAD IA (Vigentra Architech).

Flujo:
  1. La pagina del sitio pide `GET /v1/planes` (los precios viven aqui, no en el HTML) y al elegir uno hace
     `POST /v1/comprar {plan, email}`: el servidor crea una sesion de Stripe Checkout y devuelve su URL.
  2. El cliente paga en Stripe. Volver de la pagina de pago NO entrega nada.
  3. Stripe avisa a `POST /stripe/webhook` (firmado). Solo ahi, con el pago confirmado, se crea la licencia.
     Es idempotente: Stripe reintenta, y la misma sesion de pago nunca genera dos claves.
  4. La pagina de gracias consulta `GET /v1/entrega?session_id=...` y muestra la clave.

Los planes mensual y anual son pagos unicos que dan 30 / 365 dias (renovar = volver a pagar y que se extienda con
admin.py); no son suscripciones de Stripe. La llave secreta de Stripe vive SOLO en el .env del servidor.

La clave se guarda en claro en `compras` unicamente para poder mostrarla en la pagina de gracias y se borra a los
RETENCION_DIAS; en `licencias` solo queda su hash, como siempre.

Variables de entorno (las lee servidor.main):
  STRIPE_SECRET_KEY        sk_live_... (o sk_test_... para probar)
  COBRO_WEBHOOK_SECRET     whsec_... del webhook que apunta a /stripe/webhook
  COBRO_PRECIOS            JSON: {"mensual": {"monto": 29900, "nombre": "..."}, "anual": {...}, "perpetua": {...}}
                           `monto` en centavos de la moneda (MXN por defecto, `moneda` para cambiarla)
  COBRO_URL_SITIO          https://vigentra.mx (a donde vuelve el cliente: /gracias y /instalacion)
  COBRO_ACEPTAR_PRUEBAS    1 solo para probar con sk_test_; sin esto una llave de prueba no vende nada
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

STRIPE_API = "https://api.stripe.com/v1"
TOLERANCIA_FIRMA_S = 300
RETENCION_DIAS = 30
UTM_VALOR = re.compile(r"^[A-Za-z0-9_\-. ]{1,100}$")
SESION = re.compile(r"^cs_(live|test)_[A-Za-z0-9]{10,200}$")
CORREO = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
DIAS = {"mensual": 30, "anual": 365, "perpetua": None}  # los mismos que servidor.PLANES
EVENTOS_PAGADOS = ("checkout.session.completed", "checkout.session.async_payment_succeeded")


class ErrorCobro(Exception):
    def __init__(self, mensaje: str, codigo: int = 400):
        super().__init__(mensaje)
        self.codigo = codigo


def _post_stripe(clave: str, ruta: str, campos: dict[str, str]) -> tuple[int, bytes]:
    """(status, bytes). Se reemplaza en las pruebas."""
    req = urllib.request.Request(
        STRIPE_API + ruta, data=urllib.parse.urlencode(campos).encode(), method="POST",
        headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read()
        except Exception:  # noqa: BLE001
            return exc.code, b""


def firma_valida(cuerpo: bytes, cabecera: str, secreto: str, ahora: float) -> bool:
    """Verifica `Stripe-Signature: t=...,v1=...` (HMAC-SHA256 de "t.cuerpo") y que no sea una repeticion vieja."""
    partes: dict[str, list[str]] = {}
    for trozo in (cabecera or "").split(","):
        k, _, v = trozo.strip().partition("=")
        partes.setdefault(k, []).append(v)
    try:
        t = int(partes.get("t", [""])[0])
    except ValueError:
        return False
    if abs(ahora - t) > TOLERANCIA_FIRMA_S:
        return False
    esperada = hmac.new(secreto.encode(), f"{t}.".encode() + cuerpo, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(esperada, v) for v in partes.get("v1", []))


class Cobro:
    def __init__(self, servicio, ruta_db: str, secret_key: str, webhook_secret: str, precios: dict[str, dict[str, Any]],
                 url_sitio: str, post: Callable[..., tuple[int, bytes]] = _post_stripe, ahora=time.time,
                 aceptar_pruebas: bool = False):
        self.servicio, self.secret_key, self.webhook_secret = servicio, secret_key, webhook_secret
        self.url_sitio = url_sitio.rstrip("/")
        self.post, self.ahora = post, ahora
        # Con una llave de PRUEBA (sk_test_) cualquiera paga con la tarjeta 4242 sin cobrarse nada: por defecto eso no
        # vende ni regala licencias. Solo con COBRO_ACEPTAR_PRUEBAS=1 (para probar el flujo de punta a punta).
        self.en_prueba = secret_key.startswith("sk_test_")
        self.aceptar_pruebas = aceptar_pruebas
        self.precios = self._validar(precios)
        self.correo: Optional[Callable[..., None]] = None  # correo.correo_desde_entorno(); None = no se manda
        self.hilos = True  # el correo sale en un hilo para no hacer esperar a Stripe (las pruebas lo ponen en False)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(ruta_db, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS compras (
                sesion TEXT PRIMARY KEY, plan TEXT NOT NULL, kid TEXT NOT NULL, clave TEXT, correo TEXT DEFAULT '',
                monto INTEGER, moneda TEXT, creada REAL NOT NULL, renovacion INTEGER DEFAULT 0,
                utm_source TEXT DEFAULT '', utm_medium TEXT DEFAULT '', utm_campaign TEXT DEFAULT '', utm_content TEXT DEFAULT '');
        """)
        columnas = [r[1] for r in self.db.execute("PRAGMA table_info(compras)")]
        for col in ("renovacion INTEGER DEFAULT 0", "utm_source TEXT DEFAULT ''", "utm_medium TEXT DEFAULT ''",
                    "utm_campaign TEXT DEFAULT ''", "utm_content TEXT DEFAULT ''"):
            if col.split()[0] not in columnas:
                self.db.execute("ALTER TABLE compras ADD COLUMN " + col)  # bases de antes de la renovacion / de la medicion
        self.db.commit()

    @staticmethod
    def _validar(precios: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        limpios = {}
        for plan, p in precios.items():
            if plan not in ("mensual", "anual", "perpetua"):
                raise ValueError(f"COBRO_PRECIOS: plan desconocido {plan!r}")
            if not isinstance(p.get("monto"), int) or p["monto"] < 10000:  # menos de 100.00 es casi seguro pesos en vez de centavos
                raise ValueError(f"COBRO_PRECIOS[{plan}].monto va en CENTAVOS (entero, minimo 10000)")
            limpios[plan] = {"monto": p["monto"], "moneda": str(p.get("moneda", "mxn")).lower(),
                             "nombre": str(p.get("nombre") or f"Vigentra Architech ({plan})")[:100]}
        return limpios

    # ------------------------------------------------------------------ publico
    @property
    def a_la_venta(self) -> bool:
        return self.aceptar_pruebas or not self.en_prueba

    def planes(self) -> list[dict[str, Any]]:
        if not self.a_la_venta:
            return []  # la pagina muestra "pronto"
        return [{"plan": plan, "nombre": p["nombre"], "monto": p["monto"], "moneda": p["moneda"], "dias": DIAS[plan]}
                for plan, p in self.precios.items()]

    def crear_checkout(self, plan: str, correo: str = "", clave_renovar: str = "", utm: Optional[dict] = None) -> str:
        p = self.precios.get(plan)
        if p is None or not self.a_la_venta:
            raise ErrorCobro("Ese plan no esta a la venta.", 404)
        correo = (correo or "").strip()
        if correo and not CORREO.match(correo):
            raise ErrorCobro("Revisa el correo.")
        campos = {
            "mode": "payment", "locale": "es-419",
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": p["moneda"],
            "line_items[0][price_data][unit_amount]": str(p["monto"]),
            "line_items[0][price_data][product_data][name]": p["nombre"],
            "success_url": f"{self.url_sitio}/gracias?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{self.url_sitio}/comprar?cancelado=1",
            "metadata[plan]": plan, "metadata[producto]": "autocad-ia",
            "payment_intent_data[metadata][plan]": plan,
            "payment_intent_data[description]": p["nombre"],
            # Stripe genera la factura-recibo en PDF del pago y deja capturar el RFC / ID fiscal y la direccion. La factura
            # fiscal mexicana (CFDI) es otra cosa: la emite un PAC, Stripe no la da.
            "invoice_creation[enabled]": "true",
            "invoice_creation[invoice_data][description]": p["nombre"],
            "invoice_creation[invoice_data][footer]": "Para factura fiscal (CFDI) escribe a vigentra.inf@gmail.com con tu constancia de situacion fiscal y tu referencia de pedido.",
            "invoice_creation[invoice_data][metadata][plan]": plan,
            "tax_id_collection[enabled]": "true", "customer_creation": "always",
            "billing_address_collection": "auto",
        }
        # de que anuncio o video vino la compra (parametros utm de la pagina); solo texto corto y seguro
        if isinstance(utm, dict):
            for k in ("source", "medium", "campaign", "content"):
                v = str(utm.get(k, "")).strip()
                if v and UTM_VALOR.match(v):
                    campos[f"metadata[utm_{k}]"] = v
        clave_renovar = (clave_renovar or "").strip()
        if clave_renovar:
            if plan == "perpetua":
                raise ErrorCobro("La licencia perpetua no vence: no hay nada que renovar.")
            fila = self.servicio.por_clave(clave_renovar)
            if fila is None:
                raise ErrorCobro("No reconocemos esa clave. Revisa que este completa (AIA-XXXXX-XXXXX-XXXXX-XXXXX).", 403)
            if fila["estado"] != "activa":
                raise ErrorCobro("Esa licencia no esta activa. Escribe a soporte.", 403)
            if fila["plan"] != plan:
                raise ErrorCobro("Tu clave es del plan %s: renueva con el plan %s (para cambiar de plan escribe a soporte)." % (fila["plan"], fila["plan"]))
            campos["metadata[renueva_kid]"] = fila["kid"]
        if correo:
            campos["customer_email"] = correo
        try:
            status, crudo = self.post(self.secret_key, "/checkout/sessions", campos)
            datos = json.loads(crudo or b"{}")
        except Exception as exc:  # noqa: BLE001
            raise ErrorCobro("No se pudo abrir el pago. Intenta de nuevo en unos minutos.", 502) from exc
        url = datos.get("url") if isinstance(datos, dict) else None
        if status != 200 or not isinstance(url, str) or not url.startswith("https://"):
            raise ErrorCobro("No se pudo abrir el pago. Intenta de nuevo en unos minutos.", 502)
        return url

    # ------------------------------------------------------------------ webhook
    def procesar_webhook(self, cuerpo: bytes, cabecera: str) -> dict[str, Any]:
        if not firma_valida(cuerpo, cabecera, self.webhook_secret, self.ahora()):
            raise ErrorCobro("Firma invalida.", 400)
        try:
            evento = json.loads(cuerpo)
        except ValueError as exc:
            raise ErrorCobro("JSON invalido.") from exc
        if not isinstance(evento, dict) or evento.get("type") not in EVENTOS_PAGADOS:
            return {"ignorado": True}
        obj = (evento.get("data") or {}).get("object") or {}
        sesion, plan = str(obj.get("id", "")), str((obj.get("metadata") or {}).get("plan", ""))
        if not SESION.match(sesion) or plan not in self.precios:
            return {"ignorado": True}
        if sesion.startswith("cs_test_") and not self.aceptar_pruebas:
            return {"ignorado": True, "motivo": "pago de prueba"}
        if obj.get("payment_status") != "paid":  # p. ej. OXXO/SPEI: el aviso de pago llega despues
            return {"pendiente": True}
        detalle = obj.get("customer_details") or {}
        correo = str(detalle.get("email") or obj.get("customer_email") or "")[:200]
        meta = obj.get("metadata") or {}
        renueva = str(meta.get("renueva_kid", ""))
        utm = [str(meta.get(f"utm_{k}", ""))[:100] for k in ("source", "medium", "campaign", "content")]
        with self._lock:
            if self.db.execute("SELECT 1 FROM compras WHERE sesion=?", (sesion,)).fetchone():
                return {"duplicado": True}  # Stripe reintenta: la misma compra nunca da dos claves
            if renueva:
                self.servicio.renovar(renueva, DIAS[plan])
                kid, clave = renueva, None
            else:
                lic = self.servicio.crear(plan, nota=f"stripe {sesion} {correo}"[:200])
                kid, clave = lic["kid"], lic["clave"]
            self.db.execute("INSERT INTO compras (sesion, plan, kid, clave, correo, monto, moneda, creada, renovacion, "
                            "utm_source, utm_medium, utm_campaign, utm_content) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (sesion, plan, kid, clave, correo, obj.get("amount_total"), obj.get("currency"), self.ahora(),
                             1 if renueva else 0, *utm))
            self.db.commit()
        self._avisar(correo, plan, clave, kid, sesion, bool(renueva))
        return {"kid": kid, "plan": plan, "renovada": bool(renueva)}

    def _avisar(self, correo: str, plan: str, clave: Optional[str], kid: str, sesion: str, renovada: bool) -> None:
        """Manda la clave por correo si hay SMTP. Nunca rompe el webhook: si falla, la clave sigue en /gracias."""
        if not (self.correo and CORREO.match(correo or "")):
            return

        def enviar() -> None:
            try:
                self.correo(correo, plan, clave, kid, sesion, renovada)
            except Exception as exc:  # noqa: BLE001
                print("No se pudo mandar el correo de", kid, "-", type(exc).__name__, flush=True)

        if self.hilos:
            threading.Thread(target=enviar, daemon=True).start()
        else:
            enviar()

    # ------------------------------------------------------------------ estadisticas
    def estadisticas(self, dias: int = 30) -> dict[str, Any]:
        """Ventas de los ultimos `dias` por canal (utm), para saber que video o anuncio vende. Solo lectura."""
        limite = self.ahora() - max(1, int(dias)) * 86400
        with self._lock:
            filas = self.db.execute(
                "SELECT utm_source, utm_medium, utm_campaign, utm_content, plan, renovacion, COUNT(*) n, COALESCE(SUM(monto), 0) total "
                "FROM compras WHERE creada>=? AND sesion NOT LIKE 'cs_test_%' "
                "GROUP BY utm_source, utm_medium, utm_campaign, utm_content, plan, renovacion ORDER BY total DESC", (limite,)).fetchall()
        canales = [{"source": f["utm_source"] or "(directo)", "medium": f["utm_medium"], "campaign": f["utm_campaign"],
                    "content": f["utm_content"], "plan": f["plan"], "renovacion": bool(f["renovacion"]),
                    "compras": f["n"], "monto": f["total"]} for f in filas]
        return {"dias": dias, "compras": sum(c["compras"] for c in canales), "monto": sum(c["monto"] for c in canales),
                "por_canal": canales}

    # ------------------------------------------------------------------ entrega
    def entrega(self, sesion: str) -> dict[str, Any]:
        if not SESION.match(sesion or ""):
            raise ErrorCobro("Sesion invalida.")
        with self._lock:
            limite = self.ahora() - RETENCION_DIAS * 86400
            self.db.execute("UPDATE compras SET clave=NULL WHERE creada<? AND clave IS NOT NULL", (limite,))
            self.db.commit()
            fila = self.db.execute("SELECT plan, clave, kid, monto, moneda, creada, renovacion FROM compras WHERE sesion=?", (sesion,)).fetchone()
        if fila is None:
            return {"estado": "procesando"}  # el webhook todavia no llego (o el pago no se completo)
        # `referencia` (el kid) no sirve para activar nada: es el numero de pedido que el cliente cita a soporte
        datos = {"plan": fila["plan"], "referencia": fila["kid"], "monto": fila["monto"], "moneda": fila["moneda"],
                 "fecha": int(fila["creada"])}
        if fila["renovacion"]:
            vence = self.servicio.vence_de(fila["kid"])
            return {"estado": "renovada", **datos, "vence": None if vence is None else int(vence)}
        if fila["clave"] is None:
            return {"estado": "entregada", **datos}
        return {"estado": "lista", "clave": fila["clave"], **datos}
