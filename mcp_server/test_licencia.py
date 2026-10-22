"""Tests del sistema de licencias: servidor (en un hilo, SQLite temporal) + cliente (licencia.py). Sin AutoCAD ni internet.

Uso:  python test_licencia.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "licencias", "servidor"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

import licencia  # noqa: E402
import servidor  # noqa: E402

FAILED: list[str] = []


def check(name: str, got, expected) -> None:
    ok = got == expected
    if not ok:
        FAILED.append(f"{name}: esperaba {expected!r}, obtuve {got!r}")
    print(("  ok  " if ok else " FALLA ") + name)


def lanza(nombre: str, fn, codigo=None, frag: str = "") -> None:
    try:
        fn()
    except servidor.ErrorLicencia as exc:
        check(nombre + " (codigo)", exc.codigo if codigo else None, codigo)
        return
    except licencia.LicenciaError as exc:
        check(nombre + " (mensaje)", frag.lower() in str(exc).lower(), True)
        return
    FAILED.append(f"{nombre}: no lanzo error")
    print(" FALLA " + nombre)


class Reloj:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def dias(self, n: float) -> None:
        self.t += n * 86400


def guardar(d: dict) -> None:
    with open(licencia.ARCHIVO, "w") as fh:
        json.dump(d, fh)


def post(url: str, cuerpo: dict, token: str = "") -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode(), method="POST", headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def main() -> int:
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = base64.b64encode(priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode()
    tmp = tempfile.mkdtemp()
    reloj = Reloj()
    svc = servidor.Servicio(os.path.join(tmp, "l.db"), priv, ahora=reloj)
    M1, M2, M3 = "a" * 64, "b" * 64, "c" * 64

    # ---- crear y activar
    k = svc.crear("perpetua", nota="cliente 1")
    check("la clave tiene el formato AIA-", k["clave"].startswith("AIA-") and len(k["clave"]) == 27, True)
    r = svc.activar(k["clave"], M1, "PC1")
    p = licencia.verificar_token(r["token"], pub)
    check("el token verifica con la publica", (p["plan"], p["maquina"], p["licencia_hasta"]), ("perpetua", M1, None))
    check("el token vale 7 dias", p["valido_hasta"] - p["emitido"], 7 * 86400)
    check("clave en minusculas y sin guiones tambien activa", bool(svc.activar(k["clave"].lower().replace("-", ""), M1)["token"]), True)
    svc.activar(k["clave"], M2, "PC2")
    lanza("tercer equipo se rechaza", lambda: svc.activar(k["clave"], M3), 409)
    check("un equipo ya activado puede renovar", bool(svc.activar(k["clave"], M2)["token"]), True)
    svc.liberar(k["kid"], M2)
    check("tras liberar entra el tercero", bool(svc.activar(k["clave"], M3)["token"]), True)
    lanza("clave inexistente", lambda: svc.activar("AIA-AAAAA-AAAAA-AAAAA-AAAAA", M1), 403)
    lanza("clave demasiado corta", lambda: svc.activar("123", M1), 403)
    lanza("id de equipo invalido", lambda: svc.activar(k["clave"], "xyz"), 400)
    check("la clave no se guarda en claro", k["clave"] in open(os.path.join(tmp, "l.db"), "rb").read().decode("latin1"), False)

    # ---- plazos
    a = svc.crear("anual")
    ra = svc.activar(a["clave"], M1)
    pa = licencia.verificar_token(ra["token"], pub)
    check("anual vence en 365 dias", round((pa["licencia_hasta"] - pa["emitido"]) / 86400), 365)
    reloj.dias(366)
    lanza("anual vencida no activa", lambda: svc.activar(a["clave"], M1), 402)
    svc.extender(a["kid"], 30)
    check("tras extender vuelve a activar", bool(svc.activar(a["clave"], M1)["token"]), True)
    m = svc.crear("mensual")
    pm = licencia.verificar_token(svc.activar(m["clave"], M1)["token"], pub)
    check("mensual vence en 30 dias (el token tambien: no pasa de la licencia)", (round((pm["licencia_hasta"] - pm["emitido"]) / 86400), round((pm["valido_hasta"] - pm["emitido"]) / 86400)), (30, 7))
    lanza("extender una perpetua se rechaza", lambda: svc.extender(k["kid"], 10), 400)

    # ---- revocar
    svc.revocar(k["kid"])
    lanza("clave revocada no activa", lambda: svc.activar(k["clave"], M1), 403)
    svc.reactivar(k["kid"])
    check("reactivada vuelve a servir", bool(svc.activar(k["clave"], M1)["token"]), True)
    lanza("plan inexistente", lambda: svc.crear("gratis"), 400)
    lanza("no se crea una 'prueba' a mano", lambda: svc.crear("prueba"), 400)

    # ---- prueba
    t1 = svc.prueba("d" * 64)
    reloj.dias(3)
    check("la prueba repetida no da mas tiempo", svc.prueba("d" * 64)["licencia_hasta"], t1["licencia_hasta"])
    reloj.dias(5)
    lanza("la prueba termina a los 7 dias", lambda: svc.prueba("d" * 64), 402)
    check("otro equipo tiene su propia prueba", bool(svc.prueba("e" * 64)["token"]), True)

    # ---- cliente: estado local
    licencia.CARPETA = tmp
    licencia.ARCHIVO = os.path.join(tmp, "licencia.json")
    licencia.id_equipo = lambda: M1  # type: ignore[assignment]
    licencia._CACHE.update(t=0.0, mtime=None, estado=None)
    ahora = reloj.t
    check("sin archivo: sin_licencia", licencia.estado(ahora, pub)["motivo"], "sin_licencia")
    lanza("exigir sin licencia", lambda: licencia.exigir("create_line"), None, "no tiene licencia")
    licencia.exigir("ping")  # libre
    tok = svc.activar(k["clave"], M1)["token"]
    guardar({"token": tok, "visto": 0})
    check("token valido: valida", licencia.estado(ahora, pub)["valida"], True)
    check("pasados 8 dias sin renovar: token_vencido", licencia.estado(ahora + 8 * 86400, pub)["motivo"], "token_vencido")
    # el reloj se atrasa respecto de lo ya visto
    guardar({"token": tok, "visto": ahora + 5 * 86400})
    check("reloj atrasado: reloj", licencia.estado(ahora, pub)["motivo"], "reloj")
    # token de otro equipo
    guardar({"token": svc.activar(k["clave"], M3)["token"], "visto": 0})
    check("token de otro equipo: otro_equipo", licencia.estado(ahora, pub)["motivo"], "otro_equipo")
    # token adulterado (cambia el plan en el cuerpo, la firma ya no cuadra)
    cuerpo, firma = tok.split(".")
    datos = json.loads(licencia._b64u_dec(cuerpo))
    datos["licencia_hasta"] = 9_999_999_999
    falso = base64.urlsafe_b64encode(json.dumps(datos, separators=(",", ":"), sort_keys=True).encode()).rstrip(b"=").decode() + "." + firma
    guardar({"token": falso, "visto": 0})
    check("token adulterado: token_invalido", licencia.estado(ahora, pub)["motivo"], "token_invalido")
    # firmado con OTRA clave privada
    otra = ec.generate_private_key(ec.SECP256R1())
    ajeno = servidor.firmar(otra, {"v": 1, "plan": "perpetua", "maquina": M1, "valido_hasta": 9_999_999_999, "licencia_hasta": None})
    guardar({"token": ajeno, "visto": 0})
    check("firmado con otra clave: token_invalido", licencia.estado(ahora, pub)["motivo"], "token_invalido")
    guardar({"token": "basura", "visto": 0})
    check("basura: token_invalido", licencia.estado(ahora, pub)["motivo"], "token_invalido")
    # vencida (licencia anual de 30 dias ya extendida, ver el plazo)
    guardar({"token": ra["token"], "visto": 0})
    check("licencia vencida: vencida", licencia.estado(ahora, pub)["motivo"], "vencida")

    # ---- HTTP real
    srv = servidor.crear_servidor(svc, "x" * 30, "127.0.0.1", 0)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        c, d = post(base + "/admin/crear", {"plan": "anual"}, "mala")
        check("admin sin token correcto: 401", c, 401)
        c, d = post(base + "/admin/crear", {"plan": "anual", "max_equipos": 1}, "x" * 30)
        check("admin crea por HTTP", (c, d["plan"], d["max_equipos"]), (200, "anual", 1))
        clave_http = d["clave"]
        c, d = post(base + "/v1/activar", {"clave": clave_http, "maquina": M1, "equipo": "PC"})
        check("activar por HTTP", (c, "token" in d), (200, True))
        c, d = post(base + "/v1/activar", {"clave": clave_http, "maquina": M2})
        check("segundo equipo con max 1: 409", c, 409)
        c, d = post(base + "/v1/prueba", {"maquina": "f" * 64})
        check("prueba por HTTP", c, 200)
        # el cliente real contra el servidor real
        os.environ["AUTOCAD_IA_LICENCIAS_URL"] = base
        licencia.CLAVE_PUBLICA_B64 = pub
        try:
            os.remove(licencia.ARCHIVO)
        except OSError:
            pass
        reloj.t = __import__("time").time()  # el cliente usa la hora real
        svc.ahora = reloj
        k2 = svc.crear("mensual")
        e = licencia.activate(k2["clave"])
        check("activate() instala el token y queda valida", (e["valida"], e["plan"]), (True, "mensual"))
        licencia._CACHE.update(t=0.0, mtime=None, estado=None)
        licencia.exigir("create_line")
        check("exigir pasa con licencia", True, True)
        lanza("clave mala en el cliente", lambda: licencia.activate("AIA-ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ"), None, "invalida")
        t = licencia.start_trial()
        check("start_trial sobre otra licencia no rompe el estado", t["valida"], True)
        # fallos de red: el cliente no se cae
        os.environ["AUTOCAD_IA_LICENCIAS_URL"] = "http://127.0.0.1:1"
        lanza("sin servidor: error claro", lambda: licencia.activate(k2["clave"]), None, "contactar")
        licencia.renovar_si_hace_falta()
        check("renovar sin servidor no levanta", True, True)
    finally:
        srv.shutdown()

    if FAILED:
        print("\nFALLARON:")
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
