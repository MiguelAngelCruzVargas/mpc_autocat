"""Guardar las API keys sin dejarlas tiradas en texto plano.

Una clave de API es una tarjeta de crédito: quien la tiene, gasta. Los tres
lugares donde terminan por descuido son el código fuente (y de ahí a un
commit público), el historial del shell (`--api-key sk-...` queda escrito
en el archivo de historial), y un .env que alguien copia sin mirar.

Acá se guardan en un archivo FUERA del repo, y en Windows además cifradas
con DPAPI (la API de protección de datos del sistema): el resultado solo lo
puede descifrar la misma cuenta de usuario en la misma máquina. Copiar el
archivo a otra computadora no sirve de nada. No hace falta instalar nada:
DPAPI es parte de Windows y se llama por ctypes.

En Linux/macOS no hay equivalente sin dependencias, así que el archivo va
en texto plano con permisos 0600 (solo el dueño lee) y se avisa.

Orden de búsqueda de una clave, de más a menos prioritario:
  1. lo que se pase por --api-key
  2. la variable de entorno del proveedor (OPENROUTER_API_KEY, etc.)
  3. lo que haya guardado acá
"""
from __future__ import annotations

import base64
import json
import os
import stat
import sys
from typing import Any, Optional

if sys.platform == "win32":
    DIRECTORIO = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "AutoCadMcp")
else:
    DIRECTORIO = os.path.join(
        os.environ.get("XDG_CONFIG_HOME",
                       os.path.join(os.path.expanduser("~"), ".config")),
        "autocad-mcp")

ARCHIVO = os.path.join(DIRECTORIO, "credenciales.json")


# ------------------------------------------------------------ cifrado

def _dpapi(datos: bytes, proteger: bool) -> Optional[bytes]:
    """CryptProtectData / CryptUnprotectData de Windows.

    Devuelve None si no se puede (no es Windows, o el blob viene de otra
    cuenta): el llamador decide si eso es un error o un fallback.
    """
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def a_blob(b: bytes) -> BLOB:
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    entrada, salida = a_blob(datos), BLOB()
    crypt32 = ctypes.windll.crypt32
    fn = crypt32.CryptProtectData if proteger else crypt32.CryptUnprotectData
    # El flag 0x4 (CRYPTPROTECT_LOCAL_MACHINE) NO se usa a propósito: sin
    # él, el secreto queda atado a ESTE usuario y no a la máquina entera.
    ok = fn(ctypes.byref(entrada), None, None, None, None, 0,
            ctypes.byref(salida))
    if not ok:
        return None
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def _proteger(valor: str) -> dict[str, str]:
    cifrado = _dpapi(valor.encode("utf-8"), proteger=True)
    if cifrado is not None:
        return {"modo": "dpapi",
                "valor": base64.b64encode(cifrado).decode("ascii")}
    return {"modo": "plano", "valor": valor}


def _revelar(entrada: Any) -> Optional[str]:
    if isinstance(entrada, str):          # formato viejo, sin envoltorio
        return entrada
    if not isinstance(entrada, dict):
        return None
    if entrada.get("modo") == "dpapi":
        crudo = base64.b64decode(entrada.get("valor", ""))
        claro = _dpapi(crudo, proteger=False)
        return claro.decode("utf-8") if claro else None
    return entrada.get("valor")


# ------------------------------------------------------------ archivo

def _blindar(ruta: str) -> None:
    """Deja el archivo legible SOLO por su dueño."""
    try:
        if sys.platform == "win32":
            # icacls: se quita la herencia y se deja al usuario actual.
            import subprocess
            usuario = os.environ.get("USERNAME", "")
            subprocess.run(["icacls", ruta, "/inheritance:r"],
                           capture_output=True, check=False)
            if usuario:
                subprocess.run(["icacls", ruta, "/grant:r",
                                f"{usuario}:(R,W)"],
                               capture_output=True, check=False)
        else:
            os.chmod(ruta, stat.S_IRUSR | stat.S_IWUSR)   # 0600
    except OSError:
        pass


def _leer_todo() -> dict[str, Any]:
    try:
        with open(ARCHIVO, encoding="utf-8") as fh:
            datos = json.load(fh)
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def _escribir_todo(datos: dict[str, Any]) -> None:
    os.makedirs(DIRECTORIO, exist_ok=True)
    with open(ARCHIVO, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, indent=2)
    _blindar(ARCHIVO)


# ------------------------------------------------------------ API

def guardar(proveedor: str, clave: str) -> str:
    """Guarda la clave de un proveedor. Devuelve cómo quedó protegida."""
    if not clave or not clave.strip():
        raise ValueError("La clave está vacía.")
    datos = _leer_todo()
    entrada = _proteger(clave.strip())
    datos[proveedor] = entrada
    _escribir_todo(datos)
    return entrada["modo"]


def obtener(proveedor: str) -> Optional[str]:
    return _revelar(_leer_todo().get(proveedor))


def borrar(proveedor: str) -> bool:
    datos = _leer_todo()
    if proveedor not in datos:
        return False
    del datos[proveedor]
    _escribir_todo(datos)
    return True


def enmascarar(clave: str) -> str:
    """'sk-or-v1-abc…xyz9' — suficiente para reconocerla, inútil para usarla."""
    if not clave:
        return "(vacía)"
    if len(clave) <= 12:
        return clave[:2] + "…" + clave[-2:]
    return f"{clave[:8]}…{clave[-4:]}"


def listar() -> list[dict[str, str]]:
    """Qué hay guardado, SIEMPRE enmascarado. Nunca imprime una clave."""
    salida = []
    for proveedor, entrada in sorted(_leer_todo().items()):
        clave = _revelar(entrada)
        modo = entrada.get("modo", "plano") if isinstance(entrada, dict) \
            else "plano"
        salida.append({
            "proveedor": proveedor,
            "clave": enmascarar(clave) if clave else "(no se pudo descifrar)",
            "proteccion": modo,
        })
    return salida


# ------------------------------------------------- preferencias de la UI
#
# Van al lado de las credenciales y NO en el localStorage del navegador,
# que es por ORIGEN: cambiar el puerto del servidor (8770 -> 8771) hace que
# el navegador vea otro sitio y los ajustes desaparezcan. También se
# perdían al limpiar datos del navegador o al abrir desde otro. Acá
# sobreviven a todo eso, igual que las claves.
ARCHIVO_PREFS = os.path.join(DIRECTORIO, "preferencias.json")

# Solo estas claves se guardan: una lista blanca evita que la interfaz
# escriba cualquier cosa en el disco del usuario.
PREFS_VALIDAS = ("proveedor", "modelo", "perfil", "temperatura",
                 "conReglas", "configurado", "autoPlano", "modelos")


def leer_preferencias() -> dict[str, Any]:
    try:
        with open(ARCHIVO_PREFS, encoding="utf-8") as fh:
            datos = json.load(fh)
        return datos if isinstance(datos, dict) else {}
    except (OSError, ValueError):
        return {}


def guardar_preferencias(nuevas: dict[str, Any]) -> dict[str, Any]:
    datos = leer_preferencias()
    for clave, valor in (nuevas or {}).items():
        if clave in PREFS_VALIDAS:
            datos[clave] = valor
    try:
        os.makedirs(DIRECTORIO, exist_ok=True)
        with open(ARCHIVO_PREFS, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, indent=2, ensure_ascii=False)
    except OSError:
        pass          # no poder guardar no debe romper la sesión en curso
    return datos


def resolver(proveedor: str, explicita: Optional[str],
             variable_entorno: str) -> Optional[str]:
    """La clave a usar, en orden de prioridad. Ver el docstring del módulo."""
    if explicita:
        return explicita
    del_entorno = os.environ.get(variable_entorno)
    if del_entorno:
        return del_entorno
    return obtener(proveedor)
