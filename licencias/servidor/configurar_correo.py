#!/usr/bin/env python3
"""Configura el correo que manda la clave de licencia (se corre EN EL VPS, en /opt/autocad-ia-licencias).

    printf '%s\\n' "$CONTRASENA" | python3 configurar_correo.py HOST PUERTO USUARIO REMITENTE CORREO_DE_PRUEBA

  HOST / PUERTO   p. ej. smtp.gmail.com 587  |  smtp-relay.brevo.com 587  |  smtp.resend.com 587
  USUARIO         el usuario SMTP (en Gmail, el correo completo; en Resend, la palabra "resend")
  REMITENTE       "Vigentra Technologies <licencias@vigentra.mx>" (con un proveedor, el dominio debe estar verificado)
  CORREO_DE_PRUEBA  a donde se manda un correo de ejemplo ANTES de guardar nada

La contrasena (en Gmail, una "contrasena de aplicacion"; en Resend/Brevo, la clave API/SMTP) llega por la entrada
estandar: no aparece en `ps` ni en el historial. Se prueba mandando un correo real; si falla no se cambia el .env.
Si sale bien: guarda SMTP_* en .env (con respaldo) y recrea el contenedor.
"""
import os
import shutil
import smtplib
import ssl
import subprocess
import sys
import time
from email.message import EmailMessage

AQUI = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(AQUI, ".env")


def guardar_env(valores):
    with open(ENV, encoding="utf-8") as f:
        lineas = f.read().splitlines()
    pendientes = dict(valores)
    nuevas = []
    for linea in lineas:
        clave = linea.split("=", 1)[0].strip()
        nuevas.append(f"{clave}={pendientes.pop(clave)}" if clave in pendientes else linea)
    nuevas += [f"{k}={v}" for k, v in pendientes.items()]
    temporal = ENV + ".nuevo"
    with open(temporal, "w", encoding="utf-8") as f:
        f.write("\n".join(nuevas) + "\n")
    os.chmod(temporal, 0o600)
    os.replace(temporal, ENV)


def main():
    if len(sys.argv) != 6:
        sys.exit(__doc__)
    host, puerto, usuario, remitente, prueba = sys.argv[1:]
    clave = sys.stdin.readline().strip()
    if not clave:
        sys.exit("No llego la contrasena por la entrada estandar.")
    sys.path.insert(0, AQUI)
    import correo
    msg = correo.armar(prueba, remitente, "anual", "AIA-PRUEBA-XXXXX-XXXXX-XXXXX", "prueba", "cs_live_prueba")
    msg.replace_header("Subject", "[PRUEBA] " + msg["Subject"])
    try:
        with smtplib.SMTP(host, int(puerto), timeout=25) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(usuario, clave)
            s.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        sys.exit("No se pudo mandar el correo de prueba (%s: %s). No cambie nada." % (type(exc).__name__, str(exc)[:200]))
    print("Correo de prueba enviado a", prueba, "- revisa tu bandeja (y spam).")
    shutil.copy2(ENV, f"{ENV}.bak-correo-{time.strftime('%Y%m%d%H%M%S')}")
    guardar_env({"SMTP_HOST": host, "SMTP_PORT": puerto, "SMTP_USER": usuario, "SMTP_PASS": clave, "SMTP_FROM": remitente})
    r = subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=AQUI, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("No pude recrear el contenedor:\n" + r.stderr[-600:])
    print("Servidor de licencias reiniciado: desde ahora cada compra manda su clave por correo.")


if __name__ == "__main__":
    main()
