"""Servidor de licencias de AutoCAD IA.

Un servicio chico (solo biblioteca estandar + `cryptography`) que:
  - guarda las claves de licencia (SOLO su hash) y en que equipos se activaron;
  - al activar entrega un TOKEN firmado con ECDSA P-256 que dice: plan, equipo, hasta cuando vale la licencia y hasta
    cuando vale el token (7 dias; el producto lo renueva solo si hay internet);
  - permite revocar, extender, liberar un equipo y listar (API de administracion con token secreto).

Modelo de seguridad: la clave PRIVADA solo vive aca (variable de entorno); el producto lleva solo la publica y NO puede
fabricar licencias. Cada clave se ata a un maximo de equipos (por defecto 2); una copia del programa en otro equipo no
activa. Un token robado no sirve en otra maquina (lleva el identificador del equipo). Revocar surte efecto cuando el
token del cliente se renueve (maximo 7 dias).

Planes: perpetua (pago unico, sin vencimiento), anual (365 dias), mensual (30), prueba (7, una vez por equipo).
El plazo de anual/mensual empieza en la PRIMERA activacion; extender suma dias (renovacion).

Variables de entorno:
  LICENCIA_CLAVE_PRIVADA          contenido del .pem (o LICENCIA_CLAVE_PRIVADA_ARCHIVO = ruta)
  LICENCIA_ADMIN_TOKEN            secreto para /admin/*  (largo y aleatorio)
  LICENCIA_DB                     ruta del archivo SQLite (en Render: dentro del disco persistente)
  PORT                            puerto (Render lo pone solo)

    python licencias/servidor/servidor.py          # arranca el servicio
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

DIA = 86400
TOKEN_DIAS = 7
PLANES = {"perpetua": None, "anual": 365, "mensual": 30, "prueba": 7}
MAX_EQUIPOS_DEFECTO = 2
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O/1/I


class ErrorLicencia(Exception):
    def __init__(self, mensaje: str, codigo: int = 400):
        super().__init__(mensaje)
        self.codigo = codigo


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def hash_clave(clave: str) -> str:
    return hashlib.sha256(normalizar(clave).encode()).hexdigest()


def normalizar(clave: str) -> str:
    return "".join(c for c in str(clave).upper() if c.isalnum())


def generar_clave() -> str:
    grupos = ["".join(secrets.choice(ALFABETO) for _ in range(5)) for _ in range(4)]
    return "AIA-" + "-".join(grupos)


def firmar(privada: ec.EllipticCurvePrivateKey, payload: dict[str, Any]) -> str:
    cuerpo = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    der = privada.sign(cuerpo, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return b64u(cuerpo) + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def cargar_privada() -> ec.EllipticCurvePrivateKey:
    pem = os.environ.get("LICENCIA_CLAVE_PRIVADA")
    if not pem and os.environ.get("LICENCIA_CLAVE_PRIVADA_ARCHIVO"):
        with open(os.environ["LICENCIA_CLAVE_PRIVADA_ARCHIVO"], "rb") as fh:
            pem = fh.read().decode()
    if not pem:
        raise SystemExit("Falta LICENCIA_CLAVE_PRIVADA (o LICENCIA_CLAVE_PRIVADA_ARCHIVO): el contenido del privada.pem.")
    return serialization.load_pem_private_key(pem.replace("\\n", "\n").encode(), password=None)  # type: ignore[return-value]


class Servicio:
    """Toda la logica, sin HTTP: asi se prueba entera sin red."""

    def __init__(self, ruta_db: str, privada: ec.EllipticCurvePrivateKey, ahora=time.time):
        self.privada = privada
        self.ahora = ahora
        self._lock = threading.Lock()
        self.db = sqlite3.connect(ruta_db, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS licencias (
                kid TEXT PRIMARY KEY, clave_hash TEXT UNIQUE NOT NULL, plan TEXT NOT NULL, estado TEXT NOT NULL DEFAULT 'activa',
                max_equipos INTEGER NOT NULL, dias INTEGER, vence REAL, creada REAL NOT NULL, nota TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS activaciones (
                kid TEXT NOT NULL, maquina TEXT NOT NULL, equipo TEXT DEFAULT '', primera REAL NOT NULL, ultima REAL NOT NULL,
                PRIMARY KEY (kid, maquina));
            CREATE TABLE IF NOT EXISTS pruebas (maquina TEXT PRIMARY KEY, inicio REAL NOT NULL);
        """)
        self.db.commit()

    # ------------------------------------------------------------------ tokens
    def _token(self, kid: str, plan: str, maquina: str, licencia_hasta: Optional[float]) -> dict[str, Any]:
        ahora = self.ahora()
        valido = ahora + TOKEN_DIAS * DIA
        if licencia_hasta is not None:
            valido = min(valido, licencia_hasta)
        payload = {"v": 1, "kid": kid, "plan": plan, "maquina": maquina, "emitido": int(ahora), "valido_hasta": int(valido),
                   "licencia_hasta": None if licencia_hasta is None else int(licencia_hasta)}
        return {"token": firmar(self.privada, payload), "plan": plan, "licencia_hasta": payload["licencia_hasta"],
                "valido_hasta": payload["valido_hasta"]}

    @staticmethod
    def _maquina(m: Any) -> str:
        m = str(m or "")
        if len(m) != 64 or any(c not in "0123456789abcdef" for c in m):
            raise ErrorLicencia("Identificador de equipo invalido.")
        return m

    # ------------------------------------------------------------------ cliente
    def activar(self, clave: str, maquina: str, equipo: str = "") -> dict[str, Any]:
        """Activa (o renueva el token de) una clave en un equipo. Idempotente para el mismo equipo."""
        maquina = self._maquina(maquina)
        if len(normalizar(clave)) < 12:
            raise ErrorLicencia("Clave de licencia invalida.", 403)
        with self._lock:
            fila = self.db.execute("SELECT * FROM licencias WHERE clave_hash=?", (hash_clave(clave),)).fetchone()
            if fila is None:
                raise ErrorLicencia("Clave de licencia invalida.", 403)
            if fila["estado"] != "activa":
                raise ErrorLicencia("Esta licencia fue revocada. Escribe a soporte.", 403)
            ahora = self.ahora()
            vence = fila["vence"]
            if vence is None and fila["dias"]:
                vence = ahora + fila["dias"] * DIA  # el plazo corre desde la primera activacion
                self.db.execute("UPDATE licencias SET vence=? WHERE kid=?", (vence, fila["kid"]))
            if vence is not None and ahora > vence:
                raise ErrorLicencia("La licencia vencio el %s. Renuevala para seguir." % time.strftime("%d/%m/%Y", time.localtime(vence)), 402)
            ya = self.db.execute("SELECT 1 FROM activaciones WHERE kid=? AND maquina=?", (fila["kid"], maquina)).fetchone()
            if ya is None:
                n = self.db.execute("SELECT COUNT(*) FROM activaciones WHERE kid=?", (fila["kid"],)).fetchone()[0]
                if n >= fila["max_equipos"]:
                    raise ErrorLicencia("Esta licencia ya esta activada en %d equipo(s), el maximo de su plan. Pide a soporte liberar uno." % n, 409)
                self.db.execute("INSERT INTO activaciones VALUES (?,?,?,?,?)", (fila["kid"], maquina, str(equipo)[:80], ahora, ahora))
            else:
                self.db.execute("UPDATE activaciones SET ultima=? WHERE kid=? AND maquina=?", (ahora, fila["kid"], maquina))
            self.db.commit()
            return self._token(fila["kid"], fila["plan"], maquina, vence)

    def prueba(self, maquina: str) -> dict[str, Any]:
        """Prueba gratis de 7 dias, una sola vez por equipo."""
        maquina = self._maquina(maquina)
        with self._lock:
            fila = self.db.execute("SELECT inicio FROM pruebas WHERE maquina=?", (maquina,)).fetchone()
            ahora = self.ahora()
            if fila is None:
                self.db.execute("INSERT INTO pruebas VALUES (?,?)", (maquina, ahora))
                self.db.commit()
                inicio = ahora
            else:
                inicio = fila["inicio"]
            fin = inicio + PLANES["prueba"] * DIA
            if ahora > fin:
                raise ErrorLicencia("La prueba gratis de este equipo ya termino. Compra una licencia para seguir.", 402)
            return self._token("prueba", "prueba", maquina, fin)

    # ------------------------------------------------------------------ administracion
    def crear(self, plan: str, dias: Optional[int] = None, max_equipos: int = MAX_EQUIPOS_DEFECTO, nota: str = "") -> dict[str, Any]:
        if plan not in PLANES or plan == "prueba":
            raise ErrorLicencia("plan: perpetua, anual o mensual.")
        if dias is None:
            dias = PLANES[plan]
        if plan != "perpetua" and (not isinstance(dias, int) or dias < 1):
            raise ErrorLicencia("'dias' tiene que ser un entero positivo.")
        if not isinstance(max_equipos, int) or not 1 <= max_equipos <= 50:
            raise ErrorLicencia("'max_equipos' va de 1 a 50.")
        clave, kid = generar_clave(), secrets.token_hex(4)
        with self._lock:
            self.db.execute("INSERT INTO licencias (kid, clave_hash, plan, estado, max_equipos, dias, vence, creada, nota) VALUES (?,?,?,?,?,?,?,?,?)",
                            (kid, hash_clave(clave), plan, "activa", max_equipos, None if plan == "perpetua" else dias, None, self.ahora(), str(nota)[:200]))
            self.db.commit()
        return {"clave": clave, "kid": kid, "plan": plan, "dias": None if plan == "perpetua" else dias, "max_equipos": max_equipos}

    def _kid(self, kid: str) -> sqlite3.Row:
        fila = self.db.execute("SELECT * FROM licencias WHERE kid=?", (kid,)).fetchone()
        if fila is None:
            raise ErrorLicencia("No existe esa licencia (kid).", 404)
        return fila

    def revocar(self, kid: str) -> dict[str, Any]:
        with self._lock:
            self._kid(kid)
            self.db.execute("UPDATE licencias SET estado='revocada' WHERE kid=?", (kid,))
            self.db.commit()
        return {"kid": kid, "estado": "revocada"}

    def reactivar(self, kid: str) -> dict[str, Any]:
        with self._lock:
            self._kid(kid)
            self.db.execute("UPDATE licencias SET estado='activa' WHERE kid=?", (kid,))
            self.db.commit()
        return {"kid": kid, "estado": "activa"}

    def extender(self, kid: str, dias: int) -> dict[str, Any]:
        """Renovacion: suma dias a partir de hoy o del vencimiento actual, lo que sea mas tarde."""
        if not isinstance(dias, int) or not 1 <= dias <= 3650:
            raise ErrorLicencia("'dias' va de 1 a 3650.")
        with self._lock:
            fila = self._kid(kid)
            if fila["plan"] == "perpetua":
                raise ErrorLicencia("Una licencia perpetua no vence: no hay que extenderla.")
            base = max(fila["vence"] or self.ahora(), self.ahora())
            nuevo = base + dias * DIA
            self.db.execute("UPDATE licencias SET vence=? WHERE kid=?", (nuevo, kid))
            self.db.commit()
        return {"kid": kid, "vence": nuevo}

    def liberar(self, kid: str, maquina: Optional[str] = None) -> dict[str, Any]:
        """Libera un equipo (o todos) para poder activar la licencia en otro."""
        with self._lock:
            self._kid(kid)
            if maquina:
                self.db.execute("DELETE FROM activaciones WHERE kid=? AND maquina=?", (kid, maquina))
            else:
                self.db.execute("DELETE FROM activaciones WHERE kid=?", (kid,))
            self.db.commit()
        return {"kid": kid, "liberado": maquina or "todos"}

    def listar(self) -> list[dict[str, Any]]:
        with self._lock:
            filas = self.db.execute("SELECT * FROM licencias ORDER BY creada DESC").fetchall()
            salida = []
            for f in filas:
                equipos = [dict(equipo=a["equipo"], maquina=a["maquina"][:10], ultima=a["ultima"])
                           for a in self.db.execute("SELECT * FROM activaciones WHERE kid=?", (f["kid"],))]
                salida.append({"kid": f["kid"], "plan": f["plan"], "estado": f["estado"], "max_equipos": f["max_equipos"],
                               "vence": f["vence"], "nota": f["nota"], "creada": f["creada"], "equipos": equipos})
            return salida


# ---------------------------------------------------------------------- HTTP

class _Limite:
    """Freno simple a quien prueba claves a ciegas: 20 fallos por IP cada 10 minutos."""

    def __init__(self, ahora=time.time):
        self.ahora, self.fallos, self.lock = ahora, {}, threading.Lock()

    def bloqueado(self, ip: str) -> bool:
        with self.lock:
            lista = [t for t in self.fallos.get(ip, []) if self.ahora() - t < 600]
            self.fallos[ip] = lista
            return len(lista) >= 20

    def fallo(self, ip: str) -> None:
        with self.lock:
            self.fallos.setdefault(ip, []).append(self.ahora())


def crear_servidor(servicio: Servicio, admin_token: str, host: str = "0.0.0.0", puerto: int = 0) -> ThreadingHTTPServer:
    limite = _Limite()

    class Manejador(BaseHTTPRequestHandler):
        server_version = "AutoCADIA-Licencias"

        def log_message(self, *a):  # sin ruido ni claves en los logs
            pass

        def _responder(self, codigo: int, cuerpo: Any) -> None:
            datos = json.dumps(cuerpo).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def _leer(self) -> dict[str, Any]:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 8192:
                raise ErrorLicencia("Pedido demasiado grande.", 413)
            if n == 0:
                return {}
            try:
                d = json.loads(self.rfile.read(n))
            except ValueError as exc:
                raise ErrorLicencia("JSON invalido.") from exc
            if not isinstance(d, dict):
                raise ErrorLicencia("Se esperaba un objeto JSON.")
            return d

        def _admin(self) -> bool:
            enviado = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
            return bool(admin_token) and secrets.compare_digest(enviado, admin_token)

        def _atender(self, metodo: str) -> None:
            ip = self.client_address[0]
            ruta = self.path.split("?")[0]
            try:
                if ruta == "/salud":
                    return self._responder(200, {"ok": True})
                if ruta.startswith("/admin/"):
                    if limite.bloqueado(ip) or not self._admin():
                        limite.fallo(ip)
                        return self._responder(401, {"error": "no autorizado"})
                    if metodo == "GET" and ruta == "/admin/listar":
                        return self._responder(200, {"licencias": servicio.listar()})
                    d = self._leer()
                    if ruta == "/admin/crear":
                        return self._responder(200, servicio.crear(d.get("plan", ""), d.get("dias"), d.get("max_equipos", MAX_EQUIPOS_DEFECTO), d.get("nota", "")))
                    if ruta == "/admin/revocar":
                        return self._responder(200, servicio.revocar(str(d.get("kid", ""))))
                    if ruta == "/admin/reactivar":
                        return self._responder(200, servicio.reactivar(str(d.get("kid", ""))))
                    if ruta == "/admin/extender":
                        return self._responder(200, servicio.extender(str(d.get("kid", "")), d.get("dias")))
                    if ruta == "/admin/liberar":
                        return self._responder(200, servicio.liberar(str(d.get("kid", "")), d.get("maquina")))
                    return self._responder(404, {"error": "no existe"})
                if metodo == "POST" and ruta in ("/v1/activar", "/v1/prueba"):
                    if limite.bloqueado(ip):
                        return self._responder(429, {"error": "Demasiados intentos. Espera unos minutos."})
                    d = self._leer()
                    try:
                        if ruta == "/v1/activar":
                            r = servicio.activar(d.get("clave", ""), d.get("maquina", ""), d.get("equipo", ""))
                        else:
                            r = servicio.prueba(d.get("maquina", ""))
                    except ErrorLicencia as exc:
                        if exc.codigo == 403:
                            limite.fallo(ip)
                        raise
                    return self._responder(200, r)
                return self._responder(404, {"error": "no existe"})
            except ErrorLicencia as exc:
                self._responder(exc.codigo, {"error": str(exc)})
            except Exception:  # noqa: BLE001 - nunca filtrar detalles internos al cliente
                self._responder(500, {"error": "error interno"})

        def do_GET(self):  # noqa: N802
            self._atender("GET")

        def do_POST(self):  # noqa: N802
            self._atender("POST")

    return ThreadingHTTPServer((host, puerto), Manejador)


def main() -> int:
    token = os.environ.get("LICENCIA_ADMIN_TOKEN", "")
    if len(token) < 24:
        raise SystemExit("Falta LICENCIA_ADMIN_TOKEN (minimo 24 caracteres aleatorios).")
    servicio = Servicio(os.environ.get("LICENCIA_DB", "licencias.db"), cargar_privada())
    srv = crear_servidor(servicio, token, "0.0.0.0", int(os.environ.get("PORT", "8780")))
    print("Servidor de licencias escuchando en el puerto", srv.server_address[1], flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
