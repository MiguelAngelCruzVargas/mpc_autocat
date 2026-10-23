"""Correo con la clave de licencia (SMTP). Opcional: sin SMTP_* en el entorno no se manda nada y la clave se ve en /gracias.

Variables: SMTP_HOST (smtp.gmail.com), SMTP_PORT (587), SMTP_USER, SMTP_PASS (en Gmail: contrasena de aplicacion), SMTP_FROM.
El cuerpo solo lleva lo que ya sabe el cliente: su clave, su plan, su referencia y los enlaces de descarga y soporte.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Callable, Optional

SITIO = "https://vigentra.mx"

PLAN = {"mensual": "mensual (30 dias de uso)", "anual": "anual (365 dias de uso)", "perpetua": "perpetua (sin vencimiento)"}
SOPORTE = {"mensual": "Soporte prioritario por correo y WhatsApp mientras tu licencia este vigente.",
           "anual": "Soporte prioritario por correo y WhatsApp mientras tu licencia este vigente.",
           "perpetua": "Soporte estandar por correo, sin prioridad."}


def armar(destino: str, de: str, plan: str, clave: Optional[str], referencia: str, sesion: str, renovada: bool = False) -> EmailMessage:
    m = EmailMessage()
    m["To"], m["From"] = destino, de
    if renovada:
        m["Subject"] = "Renovamos tu licencia de Vigentra Architech"
        cuerpo = ("Hola,\n\nRecibimos tu pago y renovamos tu licencia %s. Sigues usando la misma clave; no hace falta hacer nada.\n"
                  "\nReferencia de pedido: %s\n" % (PLAN.get(plan, plan), referencia))
    else:
        m["Subject"] = "Tu clave de Vigentra Architech"
        cuerpo = ("Hola,\n\nGracias por tu compra. Esta es tu clave de licencia %s:\n\n    %s\n\n"
                  "Sirve en 2 computadoras. Guarda este correo.\n\nReferencia de pedido: %s\n\n"
                  "1) Descarga el instalador: %s/descargas/AutoCAD-IA-1.22.0.zip\n"
                  "2) Cierra AutoCAD, descomprime y haz doble clic en INSTALAR.bat\n"
                  "3) Abre AutoCAD IA del escritorio y pega tu clave en Primeros pasos.\n"
                  "Guia completa: %s/instalacion\n" % (PLAN.get(plan, plan), clave, referencia, SITIO, SITIO))
    cuerpo += ("\n%s\nSoporte: vigentra.inf@gmail.com\n"
               "Tu resumen de compra: %s/gracias?session_id=%s\n"
               "Terminos de licencia y soporte: %s/terminos\n\n"
               "Vigentra Technologies - Tuxtepec, Oaxaca. Vigentra Architech es un producto independiente; no es un producto de Autodesk.\n"
               % (SOPORTE.get(plan, ""), SITIO, sesion, SITIO))
    m.set_content(cuerpo)
    return m


def correo_desde_entorno() -> Optional[Callable[..., None]]:
    host, user, clave = os.environ.get("SMTP_HOST", ""), os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASS", "")
    if not (host and user and clave):
        return None
    puerto = int(os.environ.get("SMTP_PORT", "587"))
    de = os.environ.get("SMTP_FROM") or "Vigentra Technologies <%s>" % user

    def enviar(destino: str, plan: str, clave_licencia: Optional[str], referencia: str, sesion: str, renovada: bool = False) -> None:
        msg = armar(destino, de, plan, clave_licencia, referencia, sesion, renovada)
        with smtplib.SMTP(host, puerto, timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(user, clave)
            s.send_message(msg)

    return enviar
