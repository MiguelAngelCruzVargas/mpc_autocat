"""Genera el par de claves que firma las licencias (ECDSA P-256).

    python licencias/generar_claves.py

- La PRIVADA queda en licencias/secreto/privada.pem (esta en .gitignore: NUNCA se sube ni se manda a un cliente).
  Es lo que el servidor de licencias necesita en la variable LICENCIA_CLAVE_PRIVADA (el contenido del .pem).
- La PUBLICA se imprime en base64 (punto sin comprimir, 65 bytes) para pegarla en mcp_server/licencia.py y en
  plugin/AutoCadMcpPlugin/LicenciaGuard.cs. Es publica: va dentro del producto.

Si ya existe una privada NO la pisa (perderla invalida todas las licencias emitidas): hay que borrarla a mano.
"""
from __future__ import annotations

import base64
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

AQUI = os.path.dirname(os.path.abspath(__file__))
RUTA = os.path.join(AQUI, "secreto", "privada.pem")


def publica_b64(privada: ec.EllipticCurvePrivateKey) -> str:
    raw = privada.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.b64encode(raw).decode()


def main() -> int:
    os.makedirs(os.path.dirname(RUTA), exist_ok=True)
    if os.path.exists(RUTA):
        with open(RUTA, "rb") as fh:
            priv = serialization.load_pem_private_key(fh.read(), password=None)
        print("Ya hay una clave privada; no se toca. Publica:")
    else:
        priv = ec.generate_private_key(ec.SECP256R1())
        with open(RUTA, "wb") as fh:
            fh.write(priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        print("Clave privada creada en", RUTA, "(GUARDALA en un gestor de contrasenas: sin ella no se pueden emitir mas licencias)")
        print("Publica:")
    print(publica_b64(priv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
