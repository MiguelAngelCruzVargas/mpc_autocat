"""Prender, apagar y revisar `run_code` — lo corre el USUARIO, nunca la IA.

Por qué existe. `run_code` compila y ejecuta C# dentro de acad.exe con los
permisos del usuario: es acceso total a AutoCAD y, sin el filtro del plugin,
a la máquina entera. Por eso nace APAGADO y la única forma de prenderlo es
que una persona, sentada frente a la computadora, elija una contraseña acá.
La IA no tiene cómo hacerlo: no conoce la contraseña, y el servidor MCP solo
sabe PRESENTARLA (la lee cifrada), no crearla ni cambiarla.

Qué deja en %LOCALAPPDATA%\\AutoCadMcp\\:

  run_code.json   lo que lee el PLUGIN:
                  {"habilitado": true, "sal": "<hex 16 bytes>",
                   "hash": "<hex sha256(sal + contraseña utf-8)>",
                   "permitir_sistema": false}
                  Guarda el hash y no la contraseña: quien lea el archivo no
                  puede presentarla.
  run_code.clave  la contraseña cifrada con DPAPI (alcance USUARIO): solo esta
                  cuenta en esta máquina la descifra. Es lo que el servidor
                  MCP manda en cada run_code. Copiarla a otra máquina no sirve.
  run_code.log    lo escribe el plugin: cada código ejecutado, con su
                  descripción y su resultado. Auditoría, no prevención.

Uso:
    python tools/run_code_acceso.py activar
    python tools/run_code_acceso.py desactivar
    python tools/run_code_acceso.py estado
    python tools/run_code_acceso.py permitir-sistema on|off

Solo stdlib. La contraseña nunca se imprime ni se escribe en ningún log.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import importlib.util
import json
import os
import secrets
import sys
from typing import Any, Callable, Optional

MIN_LARGO = 8
COMANDO_ACTIVAR = "python tools/run_code_acceso.py activar"

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------- rutas
#
# Se calculan en cada llamada y no al importar: los tests apuntan
# LOCALAPPDATA a un directorio temporal, y una ruta congelada al importar
# terminaría tocando la configuración REAL del usuario.

def directorio() -> str:
    return os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AutoCadMcp")


def ruta_config() -> str:
    return os.path.join(directorio(), "run_code.json")


def ruta_clave() -> str:
    return os.path.join(directorio(), "run_code.clave")


def ruta_log() -> str:
    return os.path.join(directorio(), "run_code.log")


# ------------------------------------------------------------- cifrado
#
# DPAPI ya está resuelto (y probado en uso) en agent/credenciales.py. Se
# carga por ruta y no con `import agent.credenciales`: el __init__ del
# paquete agent arrastra el cliente MCP, y este script tiene que correr con
# el python pelado del sistema, sin el venv.

def _cargar_credenciales() -> Any:
    ruta = os.path.join(RAIZ, "agent", "credenciales.py")
    spec = importlib.util.spec_from_file_location("_credenciales_agente", ruta)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se encontró {ruta}.")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


_CRED: list[Any] = [None]


def _cred() -> Any:
    if _CRED[0] is None:
        _CRED[0] = _cargar_credenciales()
    return _CRED[0]


def _dpapi(datos: bytes, proteger: bool) -> Optional[bytes]:
    """Indirección a propósito: los tests la reemplazan en máquinas sin
    DPAPI, y así no hace falta tocar agent/credenciales."""
    return _cred()._dpapi(datos, proteger)


def hash_de(sal: bytes, contrasena: str) -> str:
    """El mismo cálculo que hace el plugin al verificar."""
    return hashlib.sha256(sal + contrasena.encode("utf-8")).hexdigest()


# ------------------------------------------------------------- archivos

def leer_config() -> dict[str, Any]:
    try:
        with open(ruta_config(), encoding="utf-8") as fh:
            datos = json.load(fh)
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def _escribir_config(datos: dict[str, Any]) -> None:
    """Escritura atómica: el plugin puede leer el archivo justo mientras se
    escribe, y un JSON a medias lo dejaría sin config (o peor, con una
    lectura parcial)."""
    os.makedirs(directorio(), exist_ok=True)
    tmp = ruta_config() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, indent=2)
    os.replace(tmp, ruta_config())


def guardar_clave(contrasena: str) -> None:
    cifrado = _dpapi(contrasena.encode("utf-8"), proteger=True)
    if cifrado is None:
        # Sin DPAPI la única alternativa sería texto plano, y una contraseña
        # que da acceso a ejecutar código no se deja en texto plano.
        raise RuntimeError(
            "No se pudo cifrar la contraseña con DPAPI (¿no es Windows?). "
            "No se guarda en texto plano: run_code queda apagado.")
    os.makedirs(directorio(), exist_ok=True)
    # Se borra antes de reescribir: la anterior quedó blindada (sin
    # herencia), y crear de cero evita depender de qué permisos le quedaron.
    _borrar_clave()
    with open(ruta_clave(), "w", encoding="utf-8") as fh:
        json.dump({"modo": "dpapi",
                   "valor": base64.b64encode(cifrado).decode("ascii")}, fh)
    # Mismo blindaje que las API keys: sin herencia de permisos, solo el
    # usuario actual. DPAPI ya la ata a la cuenta; esto evita además que
    # otra cuenta de la máquina siquiera lea el blob.
    try:
        _cred()._blindar(ruta_clave())
    except Exception:
        pass


def leer_clave() -> Optional[str]:
    """La contraseña descifrada, o None si no hay clave (o no se descifra).

    La usa el servidor MCP (engine.py) para presentarla al plugin. None es
    "apagado" para todos los efectos: no se intenta nada sin ella."""
    try:
        with open(ruta_clave(), encoding="utf-8") as fh:
            entrada = json.load(fh)
        if not isinstance(entrada, dict) or entrada.get("modo") != "dpapi":
            return None
        claro = _dpapi(base64.b64decode(entrada.get("valor", "")),
                       proteger=False)
        return claro.decode("utf-8") if claro else None
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _borrar_clave() -> bool:
    try:
        os.remove(ruta_clave())
        return True
    except FileNotFoundError:
        return False


# ------------------------------------------------------------- comandos

def activar(pedir: Callable[[str], str] = getpass.getpass) -> int:
    print("Activar run_code: la IA podrá ejecutar código C# dentro de "
          "AutoCAD.")
    print(f"Elegí una contraseña (mínimo {MIN_LARGO} caracteres). No se "
          "muestra al tipearla ni se guarda en claro.\n")
    primera = pedir("Contraseña: ")
    if len(primera) < MIN_LARGO:
        print(f"ERROR: tiene que tener al menos {MIN_LARGO} caracteres. "
              "No se activó nada.")
        return 1
    segunda = pedir("Repetila: ")
    if not hmac.compare_digest(primera, segunda):
        print("ERROR: las dos no coinciden. No se activó nada.")
        return 1

    sal = secrets.token_bytes(16)
    previa = leer_config()
    try:
        # La clave ANTES que la config: si cifrar falla, no queda un
        # run_code.json habilitado con una contraseña que nadie puede
        # presentar.
        guardar_clave(primera)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1
    _escribir_config({
        "habilitado": True,
        "sal": sal.hex(),
        "hash": hash_de(sal, primera),
        # Reactivar (o cambiar la contraseña) NUNCA prende el acceso al
        # sistema: eso es una decisión aparte y explícita.
        "permitir_sistema": False,
    })

    print("\nListo. Quedó así:")
    print("  - run_code ACTIVADO. El servidor MCP presenta la contraseña "
          "solo; la IA no la ve.")
    print("  - Filtro del plugin PRENDIDO: el código no puede tocar archivos, "
          "red, procesos ni registro, solo AutoCAD.")
    if previa.get("permitir_sistema"):
        print("    (estaba en permitir-sistema on: se volvió a apagar).")
    print(f"  - Todo lo ejecutado queda registrado en {ruta_log()}")
    print("\nPara apagarlo:   python tools/run_code_acceso.py desactivar")
    print("Para revisarlo:  python tools/run_code_acceso.py estado")
    return 0


def desactivar() -> int:
    datos = leer_config()
    if datos:
        datos["habilitado"] = False
        _escribir_config(datos)
    borrada = _borrar_clave()
    print("run_code APAGADO." + (" Se borró la clave guardada."
                                 if borrada else ""))
    print("El plugin rechaza cualquier run_code hasta que vuelvas a correr:")
    print(f"    {COMANDO_ACTIVAR}")
    return 0


def estado() -> int:
    datos = leer_config()
    clave = leer_clave()
    habilitado = bool(datos.get("habilitado"))
    print(f"Configuración: {ruta_config()}"
          + ("" if datos else "  (no existe)"))
    print(f"run_code: {'ACTIVADO' if habilitado else 'apagado'}")
    if os.path.exists(ruta_clave()):
        if clave is None:
            print("Clave guardada: existe pero NO se pudo descifrar (¿otra "
                  "cuenta de Windows?). El servidor no puede presentarla.")
        else:
            try:
                coincide = hmac.compare_digest(
                    hash_de(bytes.fromhex(datos.get("sal", "")), clave),
                    str(datos.get("hash", "")))
            except ValueError:
                coincide = False
            print("Clave guardada: sí, "
                  + ("coincide con la configuración."
                     if coincide else
                     "pero NO coincide con la configuración: reactivá."))
    else:
        print("Clave guardada: no")
    if datos.get("permitir_sistema"):
        print("permitir_sistema: PRENDIDO -- el filtro del plugin está "
              "desactivado; el código puede tocar archivos, red y procesos.")
    else:
        print("permitir_sistema: apagado (el código solo toca AutoCAD).")
    print(f"Registro de ejecuciones: {ruta_log()}"
          + ("" if os.path.exists(ruta_log()) else "  (todavía vacío)"))
    if not habilitado:
        print(f"\nPara activarlo: {COMANDO_ACTIVAR}")
    return 0


def permitir_sistema(valor: str,
                     preguntar: Callable[[str], str] = input) -> int:
    datos = leer_config()
    if not datos:
        print(f"Primero hay que activar run_code: {COMANDO_ACTIVAR}")
        return 1
    if valor == "off":
        datos["permitir_sistema"] = False
        _escribir_config(datos)
        print("permitir_sistema apagado: el filtro del plugin vuelve a "
              "bloquear archivos, red, procesos y registro.")
        return 0

    print("ADVERTENCIA: con permitir-sistema on el plugin deja de filtrar.")
    print("El código que mande la IA podrá leer y borrar archivos, conectarse")
    print("a internet, lanzar programas y tocar el registro, con TUS permisos.")
    print("Un texto malicioso que la IA lea (un PDF, un DWG ajeno, una web)")
    print("puede dictarle ese código. Prendelo solo para una tarea puntual y")
    print("apagalo después con: python tools/run_code_acceso.py "
          "permitir-sistema off")
    if preguntar("\nEscribí 'si' para confirmar: ").strip().lower() \
            not in ("si", "sí"):
        print("No se cambió nada.")
        return 1
    datos["permitir_sistema"] = True
    _escribir_config(datos)
    print("permitir_sistema PRENDIDO.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(
        description="Prender, apagar y revisar run_code (acceso de la IA a "
                    "la API de AutoCAD).")
    sub = ap.add_subparsers(dest="accion", required=True)
    sub.add_parser("activar", help="elegir contraseña y prender run_code")
    sub.add_parser("desactivar", help="apagar run_code y borrar la clave")
    sub.add_parser("estado", help="mostrar cómo está configurado")
    ps = sub.add_parser("permitir-sistema",
                        help="dejar (o no) que el código salga de AutoCAD")
    ps.add_argument("valor", choices=("on", "off"))
    args = ap.parse_args(argv)

    if args.accion == "activar":
        return activar()
    if args.accion == "desactivar":
        return desactivar()
    if args.accion == "estado":
        return estado()
    return permitir_sistema(args.valor)


if __name__ == "__main__":
    raise SystemExit(main())
