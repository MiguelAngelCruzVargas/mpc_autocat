"""Tests de la IA incluida (licencias/servidor/ia.py): token de la licencia, crédito mensual por plan, paquetes
extra, prueba por equipo, licencia revocada y que nunca se filtre la clave de Vigentra. Sin internet: el proveedor
de IA es una función que responde como OpenRouter.

Uso:  python test_ia_incluida.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "licencias", "servidor"))

from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

import ia  # noqa: E402
import servidor  # noqa: E402

FAILED: list[str] = []


def check(nombre: str, obtenido, esperado) -> None:
    ok = obtenido == esperado
    if not ok:
        FAILED.append(f"{nombre}: esperaba {esperado!r}, obtuve {obtenido!r}")
    print(("  ok  " if ok else " FALLA ") + nombre)


class Reloj:
    def __init__(self, t: float = 1_800_000_000.0):  # 15/01/2027
        self.t = t

    def __call__(self) -> float:
        return self.t


class ProveedorFalso:
    """Responde como OpenRouter: cada llamada cuesta `costo` dólares."""

    def __init__(self, costo: float = 0.40):
        self.costo, self.llamadas, self.ultimo = costo, 0, None
        self.codigo = 200

    def __call__(self, url, headers, cuerpo):
        self.llamadas += 1
        self.ultimo = (url, headers, json.loads(cuerpo))
        if self.codigo != 200:
            return self.codigo, b'{"error": {"message": "cuenta sk-or-VIGENTRA sin saldo"}}'
        return 200, json.dumps({"choices": [{"message": {"role": "assistant", "content": "listo"}}],
                                "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "cost": self.costo},
                                "provider": "Anthropic"}).encode()


def armar(costo=0.40, creditos=None):
    privada = ec.generate_private_key(ec.SECP256R1())
    reloj = Reloj()
    db = os.path.join(tempfile.mkdtemp(), "lic.db")
    svc = servidor.Servicio(db, privada, ahora=reloj)
    falso = ProveedorFalso(costo)
    servicio_ia = ia.ServicioIA(db, privada.public_key(), upstream_url="https://openrouter.test/api/v1",
                                upstream_key="sk-or-VIGENTRA-SECRETA", modelo="anthropic/claude-sonnet-5.5",
                                creditos=creditos or {"mensual": 1.0, "anual": 1.0, "perpetua": 0, "prueba": 0.5},
                                estado_licencia=svc.estado, llamar=falso, ahora=reloj)
    return svc, servicio_ia, falso, reloj


MAQUINA = "a" * 64
PEDIDO = {"model": "openai/gpt-6-ultra-caro", "messages": [{"role": "user", "content": "dibuja"}], "tools": []}


_CLAVES = {}


def token_de(svc, plan="mensual"):
    lic = svc.crear(plan)
    _CLAVES[lic["kid"]] = lic["clave"]
    return svc.activar(lic["clave"], MAQUINA)["token"], lic["kid"]


def lanza(nombre, fn, codigo):
    try:
        fn()
    except ia.ErrorIA as exc:
        check(nombre, exc.codigo, codigo)
        return str(exc)
    FAILED.append(nombre + ": no lanzó error")
    print(" FALLA " + nombre)
    return ""


def test_credito_mensual():
    print("crédito mensual del plan")
    svc, s, falso, reloj = armar()
    token, kid = token_de(svc)
    cod, datos, saldo = s.completar(token, PEDIDO)
    check("responde", (cod, datos["choices"][0]["message"]["content"]), (200, "listo"))
    check("usa el modelo de Vigentra, no el que pide el cliente", falso.ultimo[2]["model"], "anthropic/claude-sonnet-5.5")
    check("con la clave de Vigentra", falso.ultimo[1]["Authorization"], "Bearer sk-or-VIGENTRA-SECRETA")
    check("no devuelve el proveedor de fondo", "provider" in datos, False)
    check("descuenta el costo reportado", saldo["restante_usd"], 0.6)
    s.completar(token, PEDIDO)
    s.completar(token, PEDIDO)          # pasa de 1.0: se permite una llamada de más, no más
    msg = lanza("sin crédito: 402", lambda: s.completar(token, PEDIDO), 402)
    check("el mensaje dice qué hacer", "propia clave" in msg, True)
    check("no llama al proveedor sin crédito", falso.llamadas, 3)
    reloj.t += 25 * 86400               # mes siguiente (el programa renueva su token solo)
    token = svc.activar(_CLAVES[kid], MAQUINA)["token"]
    check("el día 1 se renueva", s.completar(token, PEDIDO)[0], 200)


def test_paquete_extra():
    print("paquetes extra")
    svc, s, falso, _ = armar(costo=0.6)
    token, kid = token_de(svc)
    s.completar(token, PEDIDO)
    s.completar(token, PEDIDO)          # 1.2 de 1.0
    lanza("se acaba el del plan", lambda: s.completar(token, PEDIDO), 402)
    s.sumar_extra(kid, 1.0)
    check("con paquete vuelve a responder", s.completar(token, PEDIDO)[0], 200)
    saldo = s.saldo(kid, "mensual")
    check("el extra se gasta después del plan", round(saldo["extra_usd"], 2), 0.4)


def test_prueba_por_equipo():
    print("prueba gratis: crédito por equipo")
    svc, s, _, _ = armar(costo=0.3)
    t1 = svc.prueba(MAQUINA)["token"]
    t2 = svc.prueba("b" * 64)["token"]
    s.completar(t1, PEDIDO)
    s.completar(t1, PEDIDO)
    lanza("el equipo 1 agotó su prueba", lambda: s.completar(t1, PEDIDO), 402)
    check("el equipo 2 sigue con la suya", s.completar(t2, PEDIDO)[0], 200)


def test_perpetua_sin_credito():
    print("perpetua: el pago único no incluye IA mensual (salvo que se configure)")
    svc, s, _, _ = armar()
    token, _ = token_de(svc, "perpetua")
    lanza("perpetua con crédito 0", lambda: s.completar(token, PEDIDO), 402)


def test_tokens_malos():
    print("tokens")
    svc, s, _, reloj = armar()
    lanza("token inventado", lambda: s.completar("abc.def", PEDIDO), 401)
    otra = ec.generate_private_key(ec.SECP256R1())
    falso_token = servidor.firmar(otra, {"kid": "x", "plan": "anual", "maquina": MAQUINA, "valido_hasta": 2_000_000_000})
    lanza("firmado con otra llave", lambda: s.completar(falso_token, PEDIDO), 401)
    token, kid = token_de(svc)
    svc.revocar(kid)
    lanza("licencia revocada", lambda: s.completar(token, PEDIDO), 403)
    token2, _ = token_de(svc)
    reloj.t += 8 * 86400
    lanza("token vencido", lambda: s.completar(token2, PEDIDO), 401)


def test_error_del_proveedor_no_cobra_ni_filtra():
    print("error del proveedor")
    svc, s, falso, _ = armar()
    token, kid = token_de(svc)
    falso.codigo = 401
    cod, datos, _ = s.completar(token, PEDIDO)
    check("responde 502", cod, 502)
    check("sin detalles de nuestra cuenta", "VIGENTRA" in json.dumps(datos), False)
    check("no se cobra", s.saldo(kid, "mensual")["usado_este_mes_usd"], 0.0)


def test_sin_costo_ni_precio_no_regala():
    print("sin costo reportado")
    svc, s, falso, _ = armar()
    token, _ = token_de(svc)
    falso.costo = None
    lanza("sin precio configurado: 503", lambda: s.completar(token, PEDIDO), 503)
    s.precios = {"anthropic/claude-sonnet-5.5": {"entrada": 3.0, "salida": 15.0}}
    _, _, saldo = s.completar(token, PEDIDO)
    check("con IA_PRECIOS calcula el costo", saldo["usado_este_mes_usd"], round((1000 * 3 + 50 * 15) / 1e6, 4))


def test_http():
    print("por HTTP (rutas, encabezado de saldo, apagado)")
    svc, s, _, _ = armar()
    token, kid = token_de(svc)
    srv = servidor.crear_servidor(svc, "x" * 30, "127.0.0.1", 0, ia=s)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def pedir(ruta, cuerpo=None, tok=token, admin=False):
        req = urllib.request.Request(base + ruta, data=None if cuerpo is None else json.dumps(cuerpo).encode(),
                                     method="GET" if cuerpo is None else "POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": "Bearer " + ("x" * 30 if admin else tok)})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read()), dict(r.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read()), dict(exc.headers)

    cod, datos, cab = pedir("/ia/v1/chat/completions", PEDIDO)
    check("chat 200", cod, 200)
    check("encabezado con el saldo", cab.get("X-Credito-Restante-USD"), "0.6000")
    check("modelos", pedir("/ia/v1/models")[1]["data"][0]["id"], "anthropic/claude-sonnet-5.5")
    check("saldo", pedir("/ia/v1/saldo")[1]["restante_usd"], 0.6)
    check("sin token: 401", pedir("/ia/v1/saldo", tok="nada")[0], 401)
    check("admin suma crédito", pedir("/admin/ia_credito", {"kid": kid, "usd": 5}, admin=True)[0], 200)
    check("admin ve el uso", pedir("/admin/ia_uso", admin=True)[1]["uso"][0]["cuenta"], kid)
    srv.shutdown()

    apagado = servidor.crear_servidor(svc, "x" * 30, "127.0.0.1", 0)
    threading.Thread(target=apagado.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % apagado.server_address[1]
    check("sin configurar: 404", pedir("/ia/v1/chat/completions", PEDIDO)[0], 404)
    apagado.shutdown()


class FlujoFalso:
    """Como OpenRouter con stream: trozos de texto y, al final, el uso con su costo."""

    def __init__(self, costo=0.25, codigo=200):
        self.costo, self.codigo, self.cuerpo = costo, codigo, None

    def __call__(self, url, headers, cuerpo):
        self.cuerpo = json.loads(cuerpo)
        if self.codigo != 200:
            return self.codigo, b'{"error": {"message": "sk-or-VIGENTRA"}}'
        trozos = [{"choices": [{"delta": {"content": "Ho"}}], "provider": "Anthropic"},
                  {"choices": [{"delta": {"content": "la"}}]},
                  {"choices": [], "usage": {"prompt_tokens": 900, "completion_tokens": 20, "cost": self.costo}}]
        fin = b"\n\n"
        return 200, iter([b"data: " + json.dumps(t).encode() + fin for t in trozos] + [b"data: [DONE]" + fin])


def test_flujo_en_vivo():
    print("respuesta en vivo (stream), como la pide el chat de AutoCAD")
    svc, s, _, _ = armar()
    flujo = FlujoFalso()
    s.abrir_flujo = flujo
    token, kid = token_de(svc)
    salida, empezo = [], []
    error = s.completar_flujo(token, dict(PEDIDO, stream=True), lambda: empezo.append(1), salida.append)
    texto = b"".join(salida).decode()
    check("sin error", error, None)
    check("pide stream con el uso al final", (flujo.cuerpo["stream"], flujo.cuerpo["stream_options"]), (True, {"include_usage": True}))
    check("pasa el texto", '"Ho"' in texto and '"la"' in texto and "[DONE]" in texto, True)
    check("quita el proveedor de fondo", "Anthropic" in texto, False)
    check("cobra el costo del último trozo", s.saldo(kid, "mensual")["usado_este_mes_usd"], 0.25)
    s.abrir_flujo = FlujoFalso(codigo=500)
    cod, cuerpo = s.completar_flujo(token, dict(PEDIDO, stream=True), lambda: None, salida.append)
    check("error antes de empezar: 502 limpio", (cod, "VIGENTRA" in json.dumps(cuerpo)), (502, False))

    srv = servidor.crear_servidor(svc, "x" * 30, "127.0.0.1", 0, ia=s)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    s.abrir_flujo = FlujoFalso(costo=0.1)
    req = urllib.request.Request("http://127.0.0.1:%d/ia/v1/chat/completions" % srv.server_address[1],
                                 data=json.dumps(dict(PEDIDO, stream=True)).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=10) as r:
        tipo, cuerpo = r.headers.get("Content-Type"), r.read().decode()
    check("por HTTP: event-stream", tipo, "text/event-stream")
    check("por HTTP: llega todo", cuerpo.count("data:"), 4)
    srv.shutdown()


def test_apagado_sin_variables():
    print("desde_entorno")
    os.environ.pop("IA_UPSTREAM_KEY", None)
    privada = ec.generate_private_key(ec.SECP256R1())
    check("sin clave queda apagada", ia.desde_entorno(os.path.join(tempfile.mkdtemp(), "x.db"),
                                                      privada.public_key(), lambda k: "activa"), None)


if __name__ == "__main__":
    for prueba in (test_credito_mensual, test_paquete_extra, test_prueba_por_equipo, test_perpetua_sin_credito,
                   test_tokens_malos, test_error_del_proveedor_no_cobra_ni_filtra, test_sin_costo_ni_precio_no_regala,
                   test_http, test_flujo_en_vivo, test_apagado_sin_variables):
        prueba()
    print()
    if FAILED:
        print("FALLARON %d:" % len(FAILED))
        for f in FAILED:
            print("  - " + f)
        sys.exit(1)
    print("Todo bien.")
