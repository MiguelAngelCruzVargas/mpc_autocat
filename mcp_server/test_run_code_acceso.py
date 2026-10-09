"""Tests del CLI que prende y apaga run_code (tools/run_code_acceso.py).

Es la llave del motor: si el formato de run_code.json no es EXACTAMENTE el
que lee el plugin, o si el hash no se calcula igual, el usuario activa y el
plugin rechaza igual (o peor: queda prendido algo que el usuario cree
apagado). Y la contraseña no puede aparecer en ninguna salida.

NO necesita AutoCAD. LOCALAPPDATA va a un directorio temporal y getpass /
input se reemplazan: nada toca la configuración real del usuario.

Uso:  python test_run_code_acceso.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile

_TMP = tempfile.TemporaryDirectory(prefix="test_acceso_")
os.environ["LOCALAPPDATA"] = _TMP.name

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "tools"))
import run_code_acceso as acceso  # noqa: E402

FAILED: list[str] = []
CLAVE = "mi-clave-secreta-9"


def check(name: str, ok: bool, detalle: object = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


if sys.platform != "win32":
    acceso._dpapi = lambda datos, proteger: bytes(b ^ 0x5A for b in datos)


def _respuestas(*valores: str):
    pendientes = list(valores)
    return lambda _prompt="": pendientes.pop(0)


def _salida(fn) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        codigo = fn()
    return codigo, buf.getvalue()


def _config() -> dict:
    with open(acceso.ruta_config(), encoding="utf-8") as fh:
        return json.load(fh)


def test_rutas_en_el_temporal() -> None:
    check("la config va al LOCALAPPDATA del test (no la real)",
          acceso.ruta_config().startswith(_TMP.name), acceso.ruta_config())


def test_activar_formato_exacto() -> None:
    codigo, texto = _salida(
        lambda: acceso.activar(pedir=_respuestas(CLAVE, CLAVE)))
    check("activar devuelve 0", codigo == 0, texto)
    datos = _config()
    check("las cuatro claves exactas que lee el plugin",
          set(datos) == {"habilitado", "sal", "hash", "permitir_sistema"},
          sorted(datos))
    check("habilitado true, permitir_sistema false",
          datos["habilitado"] is True and datos["permitir_sistema"] is False,
          datos)
    sal = bytes.fromhex(datos["sal"])
    check("sal de 16 bytes en hex", len(sal) == 16, datos["sal"])
    check("hash = sha256(sal + contraseña utf-8)",
          datos["hash"] == hashlib.sha256(sal + CLAVE.encode("utf-8"))
          .hexdigest(), datos["hash"])
    check("la clave se puede presentar", acceso.leer_clave() == CLAVE)
    with open(acceso.ruta_clave(), encoding="utf-8") as fh:
        crudo = fh.read()
    check("la clave NO queda en claro en disco", CLAVE not in crudo)
    check("ni en el json", CLAVE not in json.dumps(datos))
    check("la contraseña nunca se imprime", CLAVE not in texto)
    check("explica cómo desactivar", "desactivar" in texto, texto)


def test_activar_rechaza() -> None:
    _salida(acceso.desactivar)
    os.remove(acceso.ruta_config())
    codigo, texto = _salida(
        lambda: acceso.activar(pedir=_respuestas("corta", "corta")))
    check("menos de 8 caracteres: no activa",
          codigo == 1 and not os.path.exists(acceso.ruta_config()), texto)
    codigo, texto = _salida(
        lambda: acceso.activar(pedir=_respuestas(CLAVE, CLAVE + "x")))
    check("si no coinciden: no activa",
          codigo == 1 and not os.path.exists(acceso.ruta_config())
          and acceso.leer_clave() is None, texto)


def test_desactivar() -> None:
    _salida(lambda: acceso.activar(pedir=_respuestas(CLAVE, CLAVE)))
    codigo, texto = _salida(acceso.desactivar)
    check("desactivar apaga", codigo == 0
          and _config()["habilitado"] is False, _config())
    check("y borra la clave", not os.path.exists(acceso.ruta_clave())
          and acceso.leer_clave() is None)


def test_permitir_sistema() -> None:
    _salida(lambda: acceso.activar(pedir=_respuestas(CLAVE, CLAVE)))
    codigo, texto = _salida(
        lambda: acceso.permitir_sistema("on", preguntar=_respuestas("no")))
    check("sin confirmar no prende", codigo == 1
          and _config()["permitir_sistema"] is False, texto)
    codigo, texto = _salida(
        lambda: acceso.permitir_sistema("on", preguntar=_respuestas("si")))
    check("confirmado prende", _config()["permitir_sistema"] is True, texto)
    check("con advertencia clara", "ADVERTENCIA" in texto
          and "archivos" in texto, texto)
    _, texto = _salida(acceso.estado)
    check("estado lo muestra prendido", "PRENDIDO" in texto, texto)
    _salida(lambda: acceso.activar(pedir=_respuestas(CLAVE, CLAVE)))
    check("reactivar vuelve a apagar el acceso al sistema",
          _config()["permitir_sistema"] is False, _config())
    _salida(lambda: acceso.permitir_sistema("off"))
    check("off apaga", _config()["permitir_sistema"] is False)


def test_estado() -> None:
    _salida(lambda: acceso.activar(pedir=_respuestas(CLAVE, CLAVE)))
    codigo, texto = _salida(acceso.estado)
    check("estado: activo y clave que coincide", codigo == 0
          and "ACTIVADO" in texto and "coincide con la configuración" in texto,
          texto)
    check("dice dónde está el log", "run_code.log" in texto, texto)
    check("y no imprime la contraseña", CLAVE not in texto)
    _salida(acceso.desactivar)
    _, texto = _salida(acceso.estado)
    check("estado: apagado y cómo activarlo",
          "apagado" in texto and "activar" in texto, texto)


def test_permitir_sistema_sin_config() -> None:
    _salida(acceso.desactivar)
    try:
        os.remove(acceso.ruta_config())
    except FileNotFoundError:
        pass
    codigo, texto = _salida(lambda: acceso.permitir_sistema(
        "on", preguntar=_respuestas("si")))
    check("sin activar antes no se puede permitir el sistema",
          codigo == 1 and not os.path.exists(acceso.ruta_config()), texto)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    for fn in [test_rutas_en_el_temporal,
               test_activar_formato_exacto,
               test_activar_rechaza,
               test_desactivar,
               test_permitir_sistema,
               test_estado,
               test_permitir_sistema_sin_config]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: la llave de run_code queda en el formato del plugin y la "
          "contraseña no aparece en ningún lado.")
    return 0


if __name__ == "__main__":
    codigo = main()
    try:
        _TMP.cleanup()
    except OSError:
        pass
    sys.exit(codigo)
