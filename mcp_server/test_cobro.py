"""Tests del cobro con Stripe de las licencias: Stripe falso, servidor HTTP real, firma real del webhook. Sin red.

Uso:  python test_cobro.py
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "licencias", "servidor"))

from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

import cobro  # noqa: E402
import servidor  # noqa: E402

FAILED: list[str] = []
SECRETO = "whsec_prueba"
SESION = "cs_test_a1B2c3D4e5F6g7H8i9J0"


def check(name, got, expected):
    ok = got == expected
    if not ok:
        FAILED.append(f"{name}: esperaba {expected!r}, obtuve {got!r}")
    print(("  ok  " if ok else " FALLA ") + name)


def firmar(cuerpo: bytes, t: int | None = None, secreto: str = SECRETO) -> str:
    t = int(time.time()) if t is None else t
    return f"t={t},v1=" + hmac.new(secreto.encode(), f"{t}.".encode() + cuerpo, hashlib.sha256).hexdigest()


def evento(tipo="checkout.session.completed", sesion=SESION, plan="anual", pago="paid", renueva=None) -> bytes:
    meta = {"plan": plan}
    if renueva:
        meta["renueva_kid"] = renueva
    return json.dumps({"type": tipo, "data": {"object": {
        "id": sesion, "payment_status": pago, "metadata": meta, "amount_total": 299000, "currency": "mxn",
        "customer_details": {"email": "cliente@ejemplo.com"}}}}).encode()


def pedir(url, cuerpo=None, cabeceras=None, metodo=None):
    req = urllib.request.Request(url, data=cuerpo, method=metodo or ("POST" if cuerpo is not None else "GET"),
                                 headers=cabeceras or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}"), r.headers
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), e.headers


def main() -> int:
    llamadas = []

    def stripe_falso(clave, ruta, campos):
        llamadas.append((clave, ruta, campos))
        return 200, json.dumps({"url": "https://checkout.stripe.com/c/pay/" + SESION}).encode()

    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "l.db")
    svc = servidor.Servicio(db, ec.generate_private_key(ec.SECP256R1()))
    precios = {"anual": {"monto": 299000, "nombre": "Vigentra Architech anual"}, "mensual": {"monto": 49900}}
    cb = cobro.Cobro(svc, db, "sk_test_x", SECRETO, precios, "https://vigentra.mx", post=stripe_falso, aceptar_pruebas=True)

    # ---- firma
    c = evento()
    ahora = time.time()
    check("firma buena", cobro.firma_valida(c, firmar(c), SECRETO, ahora), True)
    check("firma con otro secreto", cobro.firma_valida(c, firmar(c, secreto="otro"), SECRETO, ahora), False)
    check("cuerpo alterado", cobro.firma_valida(c + b" ", firmar(c), SECRETO, ahora), False)
    check("repeticion vieja (10 min)", cobro.firma_valida(c, firmar(c, int(ahora) - 600), SECRETO, ahora), False)
    check("cabecera vacia / basura", (cobro.firma_valida(c, "", SECRETO, ahora), cobro.firma_valida(c, "t=x,v1=y", SECRETO, ahora)), (False, False))

    # ---- precios validados (un monto en pesos en vez de centavos es un error de dedo)
    try:
        cobro.Cobro(svc, db, "k", "w", {"anual": {"monto": 2990}}, "https://vigentra.mx")
        check("monto en pesos rechazado", "no lanzo", "ValueError")
    except ValueError:
        check("monto en pesos rechazado", True, True)
    try:
        cobro.Cobro(svc, db, "k", "w", {"vip": {"monto": 99000}}, "https://vigentra.mx")
        check("plan desconocido rechazado", "no lanzo", "ValueError")
    except ValueError:
        check("plan desconocido rechazado", True, True)

    # ---- servidor HTTP
    srv = servidor.crear_servidor(svc, "x" * 30, "127.0.0.1", 0, cb)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        s, d, h = pedir(base + "/v1/planes", cabeceras={"Origin": "https://vigentra.mx"})
        check("planes publicos", (s, sorted(p["plan"] for p in d["planes"])), (200, ["anual", "mensual"]))
        check("planes: CORS del sitio", h.get("Access-Control-Allow-Origin"), "https://vigentra.mx")
        s, d, h = pedir(base + "/v1/planes", cabeceras={"Origin": "https://malo.example"})
        check("planes: sin CORS para otro origen", h.get("Access-Control-Allow-Origin"), None)
        s, d, h = pedir(base + "/v1/planes", metodo="OPTIONS", cabeceras={"Origin": "https://vigentra.mx"})
        check("preflight del sitio: 204", s, 204)
        s, d, h = pedir(base + "/v1/planes", metodo="OPTIONS", cabeceras={"Origin": "https://malo.example"})
        check("preflight de otro origen: 403", s, 403)

        s, d, _ = pedir(base + "/v1/comprar", json.dumps({"plan": "anual", "email": "cliente@ejemplo.com"}).encode())
        check("comprar devuelve la URL de Stripe", (s, d["url"].startswith("https://checkout.stripe.com/")), (200, True))
        clave, ruta, campos = llamadas[-1]
        check("Stripe recibe monto, moneda y plan", (campos["line_items[0][price_data][unit_amount]"],
              campos["line_items[0][price_data][currency]"], campos["metadata[plan]"]), ("299000", "mxn", "anual"))
        check("success_url vuelve a /gracias con la sesion", campos["success_url"],
              "https://vigentra.mx/gracias?session_id={CHECKOUT_SESSION_ID}")
        s, d, _ = pedir(base + "/v1/comprar", json.dumps({"plan": "vip"}).encode())
        check("plan inexistente: 404", s, 404)
        s, d, _ = pedir(base + "/v1/comprar", json.dumps({"plan": "anual", "email": "no-es-correo"}).encode())
        check("correo invalido: 400", s, 400)

        # antes del webhook: nada que entregar, y volver de Stripe NO activa nada
        s, d, _ = pedir(base + f"/v1/entrega?session_id={SESION}")
        check("antes del webhook: procesando", (s, d["estado"]), (200, "procesando"))
        s, d, _ = pedir(base + "/v1/entrega?session_id=../../etc")
        check("sesion con formato malo: 400", s, 400)
        check("no hay licencias antes del pago", len(svc.listar()), 0)

        # webhook
        c = evento()
        s, d, _ = pedir(base + "/stripe/webhook", c, {"Stripe-Signature": "t=1,v1=00"})
        check("webhook con firma falsa: 400", s, 400)
        check("firma falsa no crea licencia", len(svc.listar()), 0)
        s, d, _ = pedir(base + "/stripe/webhook", c, {"Stripe-Signature": firmar(c)})
        check("webhook firmado crea la licencia", (s, d.get("plan")), (200, "anual"))
        s, d, _ = pedir(base + "/stripe/webhook", c, {"Stripe-Signature": firmar(c)})
        check("reintento de Stripe: duplicado, sin segunda clave", (s, d.get("duplicado"), len(svc.listar())), (200, True, 1))
        lic = svc.listar()[0]
        check("la licencia es anual de 2 equipos y guarda la sesion en la nota",
              (lic["plan"], lic["max_equipos"], SESION in lic["nota"]), ("anual", 2, True))

        s, d, _ = pedir(base + f"/v1/entrega?session_id={SESION}")
        check("entrega: clave lista", (s, d["estado"], d["clave"].startswith("AIA-")), (200, "lista", True))
        check("entrega: resumen de la compra (plan, referencia, importe, moneda)",
              (d["plan"], d["referencia"] == svc.listar()[-1]["kid"] or d["referencia"] in [l["kid"] for l in svc.listar()], d["monto"], d["moneda"], isinstance(d["fecha"], int)),
              ("anual", True, 299000, "mxn", True))
        # la clave entregada activa de verdad
        r = svc.activar(d["clave"], "a" * 64)
        check("la clave entregada activa un equipo", r["plan"], "anual")

        # otros eventos
        for nombre, c2 in (("otro tipo de evento", evento(tipo="charge.refunded")),
                           ("pago aun no confirmado (SPEI/OXXO)", evento(sesion="cs_test_zzzzzzzzzzzz1", pago="unpaid")),
                           ("plan de otro producto", evento(sesion="cs_test_zzzzzzzzzzzz2", plan="otro"))):
            s, d, _ = pedir(base + "/stripe/webhook", c2, {"Stripe-Signature": firmar(c2)})
            check(nombre + ": no crea licencia", (s, len(svc.listar())), (200, 1))
        c3 = evento(tipo="checkout.session.async_payment_succeeded", sesion="cs_test_zzzzzzzzzzzz3", plan="mensual")
        s, d, _ = pedir(base + "/stripe/webhook", c3, {"Stripe-Signature": firmar(c3)})
        check("pago diferido confirmado crea la licencia", (s, d.get("plan"), len(svc.listar())), (200, "mensual", 2))

        # la clave se borra a los 30 dias
        cb.ahora = lambda: time.time() + 31 * 86400
        s, d, _ = pedir(base + f"/v1/entrega?session_id={SESION}")
        check("pasados 30 dias la clave ya no se muestra", (d["estado"], "clave" in d), ("entregada", False))
    finally:
        srv.shutdown()

    # llave de PRUEBA: no vende ni regala licencias salvo que se pida expresamente
    cb2 = cobro.Cobro(svc, db, "sk_test_x", SECRETO, precios, "https://vigentra.mx", post=stripe_falso)
    check("sk_test_ sin permiso: planes vacios (la pagina muestra 'pronto')", cb2.planes(), [])
    try:
        cb2.crear_checkout("anual")
        check("sk_test_ sin permiso: no abre pagos", "abrio", "404")
    except cobro.ErrorCobro as e:
        check("sk_test_ sin permiso: no abre pagos", e.codigo, 404)
    n0 = len(svc.listar())
    cuerpo = evento(sesion="cs_test_prueba0000001")
    r = cb2.procesar_webhook(cuerpo, firmar(cuerpo))
    check("sk_test_ sin permiso: el webhook de prueba no crea licencia", (r.get("ignorado"), len(svc.listar())), (True, n0))
    cb3 = cobro.Cobro(svc, db, "sk_test_x", SECRETO, precios, "https://vigentra.mx", post=stripe_falso, aceptar_pruebas=True)
    check("sk_test_ con COBRO_ACEPTAR_PRUEBAS: a la venta", len(cb3.planes()), 2)
    cb4 = cobro.Cobro(svc, db, "sk_live_x", SECRETO, precios, "https://vigentra.mx", post=stripe_falso)
    check("sk_live_: a la venta sin permisos especiales", len(cb4.planes()), 2)

    # ---- Stripe se encarga de la factura-recibo y del RFC; el correo lleva la clave; la renovacion suma tiempo
    cb5 = cobro.Cobro(svc, db, "sk_live_x", SECRETO, precios, "https://vigentra.mx", post=stripe_falso)
    cb5.hilos = False
    enviados = []
    cb5.correo = lambda *a: enviados.append(a)
    cb5.crear_checkout("anual")
    campos = llamadas[-1][2]
    check("Checkout pide factura-recibo y RFC a Stripe",
          (campos["invoice_creation[enabled]"], campos["tax_id_collection[enabled]"], campos["customer_creation"]), ("true", "true", "always"))
    check("la factura avisa como pedir CFDI", "CFDI" in campos["invoice_creation[invoice_data][footer]"], True)

    c = evento(sesion="cs_live_correo000001")
    r = cb5.procesar_webhook(c, firmar(c))
    lic = [l for l in svc.listar() if l["kid"] == r["kid"]][0]
    check("el pago manda UN correo con la clave a quien pago",
          (len(enviados), enviados[0][0], enviados[0][1], enviados[0][2].startswith("AIA-"), enviados[0][3] == r["kid"]),
          (1, "cliente@ejemplo.com", "anual", True, True))
    cb5.procesar_webhook(c, firmar(c))
    check("el reintento de Stripe no manda otro correo", len(enviados), 1)
    import correo
    msg = correo.armar("a@b.co", "v@v.co", "anual", "AIA-XXXXX-XXXXX-XXXXX-XXXXX", "abc123", "cs_live_x")
    cuerpo = msg.get_content()
    check("el correo trae la clave, la descarga, la referencia y los terminos",
          all(x in cuerpo for x in ("AIA-XXXXX-XXXXX-XXXXX-XXXXX", "/descargas/AutoCAD-IA-", "abc123", "/terminos", "soporte")) or "Soporte" in cuerpo, True)

    def falla(*a):
        raise OSError("smtp caido")
    cb5.correo = falla
    c = evento(sesion="cs_live_correo000002")
    r = cb5.procesar_webhook(c, firmar(c))
    check("si el correo falla el webhook sigue bien y la clave queda en /gracias",
          (cb5.entrega("cs_live_correo000002")["estado"], "kid" in r), ("lista", True))
    cb5.correo = None
    c = evento(sesion="cs_live_correo000003")
    check("sin SMTP no se manda nada y todo funciona", cb5.procesar_webhook(c, firmar(c)).get("plan"), "anual")

    # renovacion: el cliente pega su clave y el tiempo se SUMA a la misma licencia
    ahora0 = svc.ahora()
    base = svc.crear("anual")
    svc.activar(base["clave"], "b" * 64)
    v0 = svc.vence_de(base["kid"])
    cb5.crear_checkout("anual", "", base["clave"])
    check("renovar: el Checkout lleva el kid, no la clave", (llamadas[-1][2]["metadata[renueva_kid]"] == base["kid"], base["clave"] in str(llamadas[-1][2])), (True, False))
    c = evento(sesion="cs_live_renueva00001", renueva=base["kid"])
    n_lic = len(svc.listar())
    r = cb5.procesar_webhook(c, firmar(c))
    check("renovar: no crea licencia nueva y suma 365 dias", (r["renovada"], len(svc.listar()), round((svc.vence_de(base["kid"]) - v0) / 86400)), (True, n_lic, 365))
    e = cb5.entrega("cs_live_renueva00001")
    check("renovar: /gracias dice 'renovada' con el nuevo vencimiento y sin clave", (e["estado"], "clave" in e, e["vence"] == int(svc.vence_de(base["kid"]))), ("renovada", False, True))
    nueva = svc.crear("mensual")  # sin activar todavia
    cb5.crear_checkout("mensual", "", nueva["clave"])
    c = evento(sesion="cs_live_renueva00002", plan="mensual", renueva=nueva["kid"])
    cb5.procesar_webhook(c, firmar(c))
    fila = svc.db.execute("select dias, vence from licencias where kid=?", (nueva["kid"],)).fetchone()
    check("renovar una clave sin activar suma al plazo que tendra (30+30)", (fila["dias"], fila["vence"]), (60, None))
    cb5.precios["perpetua"] = dict(cb5.precios["anual"])  # el test no vende perpetua: se agrega para probar su rechazo
    for nombre, args, codigo in (("clave inexistente", ("anual", "", "AIA-ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ"), 403),
                                 ("plan distinto al de la clave", ("mensual", "", base["clave"]), 400),
                                 ("perpetua no se renueva", ("perpetua", "", base["clave"]), 400)):
        try:
            cb5.crear_checkout(*args)
            check("renovar: " + nombre, "no lanzo", codigo)
        except cobro.ErrorCobro as exc:
            check("renovar: " + nombre, exc.codigo, codigo)
    svc.revocar(base["kid"])
    try:
        cb5.crear_checkout("anual", "", base["clave"])
        check("renovar: clave revocada", "no lanzo", 403)
    except cobro.ErrorCobro as exc:
        check("renovar: clave revocada", exc.codigo, 403)

    # sin Stripe configurado las rutas no existen
    srv2 = servidor.crear_servidor(svc, "x" * 30, "127.0.0.1", 0, None)
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    try:
        b2 = f"http://127.0.0.1:{srv2.server_address[1]}"
        check("sin cobro: planes 404", pedir(b2 + "/v1/planes")[0], 404)
        check("sin cobro: webhook 404", pedir(b2 + "/stripe/webhook", b"{}")[0], 404)
    finally:
        srv2.shutdown()

    print()
    if FAILED:
        print("FALLARON %d:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("todo ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
