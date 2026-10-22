"""Licencia de AutoCAD IA: activacion contra el servidor y verificacion local del token firmado.

Como funciona (resumen para quien lo use y para quien lo audite):
  1. El usuario compra y recibe una clave AIA-XXXXX-XXXXX-XXXXX-XXXXX. En su equipo corre `activate_license(clave)`
     (o la pantalla del panel). El servidor valida la clave, la ata al equipo (maximo 2 por defecto) y devuelve un TOKEN
     firmado con ECDSA P-256: plan, equipo, hasta cuando vale la licencia y hasta cuando vale el token (7 dias).
  2. El token se guarda en %LOCALAPPDATA%\\AutoCadMcp\\licencia.json. Cada comando a AutoCAD lo verifica ANTES de salir,
     sin internet (solo necesita la clave PUBLICA, que va en el producto). El plugin C# hace la misma verificacion.
  3. Cuando al token le quedan menos de 3 dias, se renueva solo con internet. Sin internet sigue funcionando hasta que
     el token venza (maximo 7 dias): asi una caida del servidor no deja a nadie sin trabajar de golpe.
  4. Prueba gratis: `start_trial()` pide 7 dias, una sola vez por equipo.

Limites que hay que decir en voz alta: la verificacion corre en la maquina del usuario, asi que alguien con tiempo y
herramientas puede parchear el programa. Esto frena la copia casual (pasarse el .zip, usar una clave en 10 equipos,
seguir despues de vencer) y permite revocar; no es a prueba de un crackeador decidido. Lo que SI es solido: nadie puede
fabricar una licencia nueva sin la clave privada, que nunca sale del servidor.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

# Clave PUBLICA de firma (punto P-256 sin comprimir). Se genera con licencias/generar_claves.py.
CLAVE_PUBLICA_B64 = "BKfr7hVUaeNp+zRv0GuwOi89ZOHrIBrT+FdcEIz0BHPkWjXVyQZ/sJs4oUM7hEBLUDbsl1ZgBsbrAeEslx19vvc="
# Direccion del servidor de licencias. Se fija al publicar; AUTOCAD_IA_LICENCIAS_URL la pisa (pruebas, o un servidor propio).
SERVIDOR_URL = "https://vigentra-architech.vigentra.mx"

DIA = 86400
RENOVAR_ANTES_DIAS = 3
CARPETA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AutoCadMcp")
ARCHIVO = os.path.join(CARPETA, "licencia.json")
# Comandos que funcionan sin licencia: el latido y el estado (para poder mostrar «falta activar»).
LIBRES = frozenset({"ping", "license_status"})
# La exigencia del lado Python solo corre en el paquete que se vende: empaquetar.ps1 deja este archivo junto a licencia.py.
# En el repo de desarrollo no existe y no se bloquea nada. (Es la capa de aviso amable: la que HACE cumplir es el plugin.)
OBLIGATORIA = os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "LICENCIA_OBLIGATORIA"))


class LicenciaError(RuntimeError):
    """Falta o no es valida la licencia (el mensaje dice que hacer)."""


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def id_equipo() -> str:
    """Identificador estable del equipo: hash del MachineGuid de Windows (no sale en claro del equipo)."""
    guid = ""
    try:
        import winreg  # type: ignore[import-not-found]

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            guid = str(winreg.QueryValueEx(k, "MachineGuid")[0])
    except Exception:  # noqa: BLE001
        import uuid

        guid = "mac:%012x" % uuid.getnode()
    return hashlib.sha256(("autocad-ia|" + guid).encode()).hexdigest()


def verificar_token(token: str, publica_b64: Optional[str] = None) -> dict[str, Any]:
    """Devuelve el payload si la firma es valida; si no, LicenciaError. NO mira fechas ni equipo."""
    try:
        cuerpo_b64, firma_b64 = token.split(".")
        cuerpo, firma = _b64u_dec(cuerpo_b64), _b64u_dec(firma_b64)
        if len(firma) != 64:
            raise ValueError("firma")
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), base64.b64decode(publica_b64 or CLAVE_PUBLICA_B64))
        pub.verify(encode_dss_signature(int.from_bytes(firma[:32], "big"), int.from_bytes(firma[32:], "big")), cuerpo, ec.ECDSA(hashes.SHA256()))
        return json.loads(cuerpo)
    except (InvalidSignature, ValueError, KeyError) as exc:
        raise LicenciaError("El archivo de licencia no es valido (firma incorrecta). Vuelve a activar la licencia.") from exc


def _leer() -> dict[str, Any]:
    try:
        with open(ARCHIVO, encoding="utf-8") as fh:
            d = json.load(fh)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _guardar(d: dict[str, Any]) -> None:
    os.makedirs(CARPETA, exist_ok=True)
    tmp = ARCHIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    os.replace(tmp, ARCHIVO)


def estado(ahora: Optional[float] = None, publica_b64: Optional[str] = None, tocar_reloj: bool = True) -> dict[str, Any]:
    """Estado de la licencia: {'valida': bool, 'plan', 'dias_restantes', 'motivo', ...}. No hace red."""
    ahora = time.time() if ahora is None else ahora
    d = _leer()
    token = d.get("token")
    if not token:
        return {"valida": False, "plan": None, "motivo": "sin_licencia",
                "mensaje": "AutoCAD IA no tiene licencia en este equipo. Activa una clave (activate_license) o empieza la prueba gratis de 7 dias (start_trial)."}
    try:
        p = verificar_token(token, publica_b64)
    except LicenciaError as exc:
        return {"valida": False, "plan": None, "motivo": "token_invalido", "mensaje": str(exc)}
    if p.get("maquina") != id_equipo():
        return {"valida": False, "plan": p.get("plan"), "motivo": "otro_equipo",
                "mensaje": "Esta licencia esta activada para otro equipo. Activala aqui con tu clave (si ya usaste todos tus equipos, pide a soporte liberar uno)."}
    visto = float(d.get("visto", 0))
    if ahora < visto - 2 * 3600:
        return {"valida": False, "plan": p.get("plan"), "motivo": "reloj",
                "mensaje": "El reloj del equipo esta atrasado respecto a la ultima vez que se uso. Corrige la fecha y hora de Windows."}
    if tocar_reloj and ahora > visto + 60:
        d["visto"] = ahora
        try:
            _guardar(d)
        except OSError:
            pass
    hasta, lic = float(p.get("valido_hasta", 0)), p.get("licencia_hasta")
    base = {"plan": p.get("plan"), "licencia_hasta": lic, "valido_hasta": hasta,
            "dias_restantes": None if lic is None else max(0, int((lic - ahora) // DIA))}
    if ahora > hasta:
        if lic is not None and ahora > lic:
            return {**base, "valida": False, "motivo": "vencida",
                    "mensaje": "La licencia vencio el %s. Renuevala para seguir usando AutoCAD IA." % time.strftime("%d/%m/%Y", time.localtime(lic))}
        return {**base, "valida": False, "motivo": "token_vencido",
                "mensaje": "No se pudo renovar la licencia (hace mas de 7 dias sin conexion con el servidor). Conectate a internet un momento."}
    return {**base, "valida": True, "motivo": "ok", "mensaje": "Licencia %s activa%s." % (
        p.get("plan"), "" if lic is None else " (vence el %s)" % time.strftime("%d/%m/%Y", time.localtime(lic))),
        "por_renovar": (hasta - ahora) < RENOVAR_ANTES_DIAS * DIA and (lic is None or lic > hasta)}


def _url() -> str:
    url = os.environ.get("AUTOCAD_IA_LICENCIAS_URL") or SERVIDOR_URL
    if ".invalid" in url:
        raise LicenciaError("Este paquete todavia no tiene configurado el servidor de licencias (AUTOCAD_IA_LICENCIAS_URL).")
    return url.rstrip("/")


def _pedir(ruta: str, cuerpo: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
    req = urllib.request.Request(_url() + ruta, data=json.dumps(cuerpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "AutoCAD-IA"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read()).get("error", "")
        except Exception:  # noqa: BLE001
            msg = ""
        raise LicenciaError(msg or "El servidor de licencias respondio %d." % exc.code) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise LicenciaError("No se pudo contactar al servidor de licencias (revisa tu internet): %s" % getattr(exc, "reason", exc)) from exc


def _instalar(resp: dict[str, Any], clave: Optional[str]) -> dict[str, Any]:
    verificar_token(resp["token"])  # nunca se guarda algo que no verifica
    d = _leer()
    d["token"] = resp["token"]
    if clave:
        d["clave"] = clave
    d.setdefault("visto", 0)
    _guardar(d)
    return estado()


def activate(clave: str) -> dict[str, Any]:
    if not isinstance(clave, str) or len(clave.strip()) < 12:
        raise LicenciaError("La clave tiene el formato AIA-XXXXX-XXXXX-XXXXX-XXXXX.")
    return _instalar(_pedir("/v1/activar", {"clave": clave.strip(), "maquina": id_equipo(), "equipo": os.environ.get("COMPUTERNAME", "")}), clave.strip())


def start_trial() -> dict[str, Any]:
    return _instalar(_pedir("/v1/prueba", {"maquina": id_equipo()}), None)


def renovar_si_hace_falta() -> None:
    """Renueva el token con internet cuando le quedan pocos dias. Falla en silencio: sin red, el token actual sigue valiendo."""
    e = estado(tocar_reloj=False)
    clave = _leer().get("clave")
    if clave and e.get("motivo") in ("ok", "token_vencido") and (e.get("por_renovar") or e.get("motivo") == "token_vencido"):
        try:
            activate(clave)
        except LicenciaError:
            pass


_CACHE: dict[str, Any] = {"t": 0.0, "mtime": None, "estado": None}


def exigir(cmd: str) -> None:
    """Llamar antes de mandar un comando a AutoCAD. Levanta LicenciaError si no hay licencia valida."""
    if cmd in LIBRES:
        return
    ahora = time.time()
    try:
        mtime = os.path.getmtime(ARCHIVO)
    except OSError:
        mtime = None
    if _CACHE["estado"] is None or mtime != _CACHE["mtime"] or ahora - _CACHE["t"] > 30:
        renovar_si_hace_falta()
        nuevo = estado(ahora)  # puede reescribir el archivo (reloj): el mtime se lee DESPUES
        try:
            mtime = os.path.getmtime(ARCHIVO)
        except OSError:
            mtime = None
        _CACHE.update(t=ahora, mtime=mtime, estado=nuevo)
    e = _CACHE["estado"]
    if not e["valida"]:
        raise LicenciaError(e["mensaje"])
