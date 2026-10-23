#!/usr/bin/env python3
"""Activa el cobro con Stripe en el servidor de licencias (se corre EN EL VPS, en /opt/autocad-ia-licencias).

    python3 configurar_stripe.py [--prueba] [--aceptar-pruebas]

La llave NO se pasa ni se imprime: se lee del .env de la consola de Vigentra (/opt/vigentra-nube/.env), que ya la usa
para cobrar Access, asi las dos cosas siempre comparten modo (prueba o real). Este script:
  1. prueba la llave contra Stripe y dice el modo (sin mostrarla);
  2. crea el webhook de /stripe/webhook (reemplaza el anterior con la misma direccion) y guarda su whsec_;
  3. escribe en .env: STRIPE_SECRET_KEY, COBRO_WEBHOOK_SECRET, COBRO_PRECIOS, COBRO_URL_SITIO (y COBRO_ACEPTAR_PRUEBAS);
  4. recrea el contenedor.
Cuando la consola pase de sk_test_ a sk_live_ hay que volver a correrlo: el webhook y su firma son distintos en cada modo.
Solo biblioteca estandar.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.stripe.com/v1"
VERSION_API = "2024-06-20"
EVENTOS = ("checkout.session.completed", "checkout.session.async_payment_succeeded")
URL_WEBHOOK = "https://vigentra-architech.vigentra.mx/stripe/webhook"
CONSOLA_ENV = "/opt/vigentra-nube/.env"
AQUI = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(AQUI, ".env")
# Centavos de MXN, IVA incluido. Para cambiar un precio: editar aqui, volver a correr el script.
PRECIOS = {
    "mensual": {"monto": 34900, "moneda": "mxn", "nombre": "Vigentra Architech - licencia mensual"},
    "anual": {"monto": 229000, "moneda": "mxn", "nombre": "Vigentra Architech - licencia anual"},
    "perpetua": {"monto": 580000, "moneda": "mxn", "nombre": "Vigentra Architech - licencia perpetua"},
}


def stripe(llave, metodo, ruta, datos=None):
    cuerpo = urllib.parse.urlencode(datos or [], doseq=True).encode() if datos is not None else None
    req = urllib.request.Request(f"{API}{ruta}", data=cuerpo, method=metodo)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{llave}:".encode()).decode())
    req.add_header("Stripe-Version", VERSION_API)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            mensaje = json.loads(exc.read())["error"]["message"]
        except Exception:  # noqa: BLE001
            mensaje = f"HTTP {exc.code}"
        sys.exit(f"Stripe rechazo la peticion: {mensaje}")


def leer_env(ruta, clave):
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            if linea.startswith(clave + "="):
                return linea.split("=", 1)[1].strip()
    return ""


def guardar_env(valores):
    with open(ENV, encoding="utf-8") as f:
        lineas = f.read().splitlines()
    pendientes = dict(valores)
    nuevas = []
    for linea in lineas:
        clave = linea.split("=", 1)[0].strip()
        if clave in pendientes:
            nuevas.append(f"{clave}={pendientes.pop(clave)}")
        elif clave in ("COBRO_ACEPTAR_PRUEBAS",) and clave not in valores:
            continue  # se quita si ya no se pide
        else:
            nuevas.append(linea)
    nuevas += [f"{k}={v}" for k, v in pendientes.items()]
    temporal = ENV + ".nuevo"
    with open(temporal, "w", encoding="utf-8") as f:
        f.write("\n".join(nuevas) + "\n")
    os.chmod(temporal, 0o600)
    os.replace(temporal, ENV)


def main():
    aceptar = "--aceptar-pruebas" in sys.argv[1:]
    llave = leer_env(CONSOLA_ENV, "STRIPE_SECRET_KEY")
    if not (llave.startswith("sk_live_") or llave.startswith("sk_test_")):
        sys.exit("La consola no tiene una Secret key de Stripe valida en " + CONSOLA_ENV)
    en_prueba = llave.startswith("sk_test_")
    cuenta = stripe(llave, "GET", "/account")
    print("Cuenta de Stripe: %s - pais %s - modo %s" % (
        (cuenta.get("business_profile") or {}).get("name") or cuenta.get("email") or "-", cuenta.get("country"),
        "PRUEBA" if en_prueba else "REAL"))
    if not en_prueba and not cuenta.get("charges_enabled"):
        sys.exit("Stripe todavia no le permite cobrar a esta cuenta.")
    if en_prueba and not aceptar:
        print("Modo PRUEBA sin --aceptar-pruebas: el servidor NO venderá ni dará licencias hasta que haya llave real.")

    shutil.copy2(ENV, f"{ENV}.bak-{time.strftime('%Y%m%d%H%M%S')}")
    for viejo in stripe(llave, "GET", "/webhook_endpoints?limit=100").get("data", []):
        if viejo.get("url") == URL_WEBHOOK:
            stripe(llave, "DELETE", f"/webhook_endpoints/{viejo['id']}")
            print("Webhook anterior reemplazado.")
    nuevo = stripe(llave, "POST", "/webhook_endpoints", [
        ("url", URL_WEBHOOK), ("api_version", VERSION_API),
        ("description", "Licencias de Vigentra Architech (AutoCAD IA)"),
        *[("enabled_events[]", e) for e in EVENTOS]])
    secreto = nuevo.get("secret", "")
    if not secreto.startswith("whsec_"):
        sys.exit("Stripe no devolvio la firma del webhook; no cambie .env.")
    valores = {"STRIPE_SECRET_KEY": llave, "COBRO_WEBHOOK_SECRET": secreto,
               "COBRO_PRECIOS": json.dumps(PRECIOS, separators=(",", ":")), "COBRO_URL_SITIO": "https://vigentra.mx"}
    if en_prueba and aceptar:
        valores["COBRO_ACEPTAR_PRUEBAS"] = "1"
    guardar_env(valores)
    print("Webhook creado: %s (eventos: %s). Llaves guardadas en .env (no se muestran)." % (URL_WEBHOOK, ", ".join(EVENTOS)))
    r = subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=AQUI, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("No pude recrear el contenedor:\n" + r.stderr[-800:])
    print("Servidor de licencias reiniciado con el cobro configurado.")


if __name__ == "__main__":
    main()
