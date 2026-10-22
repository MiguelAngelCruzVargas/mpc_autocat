"""Tests de ojos.py (el diagnóstico de qué le pasó a AutoCAD) sin AutoCAD: lectura de acad.err, conclusiones y
que las fallas de conexión traigan el diagnóstico pegado.

Uso:  python test_ojos.py
"""
from __future__ import annotations

import os
import tempfile
import time

import autocad_client as acad
import ojos
import server

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name + (f" -- {detalle}" if not ok and detalle else ""))


def main() -> int:
    # ---- acad.err
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "acad.err"), "w", encoding="utf-8") as f:
            f.write("INTERNAL ERROR:  !dbobji.cpp@8673: eNotOpenForWrite\n\n10/22/2026 at 11:15:56.000  Drawing: Drawing2.dwg\n-------------\n"
                    "FATAL ERROR:  Unhandled Access Violation Reading 0x0000\n\n10/22/2026 at 11:20:01.000  Drawing: Casa.dwg\n-------------\n")
        real = ojos._carpetas_candidatas
        ojos._carpetas_candidatas = lambda: [d]
        try:
            e = ojos.leer_acad_err(0)
            check("acad.err: dos entradas", len(e) == 2, str(e))
            check("acad.err: mensaje y dibujo", e and "eNotOpenForWrite" in e[0]["mensaje"] + e[1]["mensaje"] and {x["dibujo"] for x in e} == {"Drawing2.dwg", "Casa.dwg"}, str(e))
            check("acad.err viejo se descarta con 'desde'", ojos.leer_acad_err(time.time() + 100) == [])
        finally:
            ojos._carpetas_candidatas = real

    # ---- conclusiones
    base = {"autocad_abierto": False, "dialogos_abiertos": [], "errores_recientes": [], "volcados_recientes": [], "ultimos_comandos": []}
    c = ojos._concluir(dict(base, errores_recientes=[{"mensaje": "INTERNAL ERROR: x", "dibujo": "A.dwg", "hora": "11:15"}],
                            ultimos_comandos=[{"cmd": "configure_layout", "params": "{}", "estado": "enviado"}]))
    check("cerrado con error: lo dice y nombra el último comando", "INTERNAL ERROR: x" in c and "configure_layout" in c and "NO está corriendo" in c, c)
    c = ojos._concluir(dict(base, autocad_abierto=True, dialogos_abiertos=[{"titulo": "AutoCAD Error Aborting", "textos": ["INTERNAL ERROR"]}]))
    check("abierto con diálogo: BLOQUEADO y el texto", "BLOQUEADO" in c and "INTERNAL ERROR" in c, c)
    c = ojos._concluir(dict(base))
    check("cerrado sin huellas: se cerró normal", "sin huellas" in c, c)
    c = ojos._concluir(dict(base, autocad_abierto=True))
    check("abierto y limpio: ocupado", "ocupado" in c, c)

    c = ojos._concluir(dict(base, ultimo_comando_plugin={"cmd": "list_plot_options", "params": "{}", "estado": "corriendo", "inicio": "11:15", "edad_s": 30},
                            errores_recientes=[{"mensaje": "INTERNAL ERROR: eNotOpenForWrite", "dibujo": "A.dwg", "hora": "11:15"}]))
    check("murió ejecutando: nombra el comando culpable", "MURIÓ" in c and "list_plot_options" in c and "eNotOpenForWrite" in c, c)
    c = ojos._concluir(dict(base, autocad_abierto=True, ultimo_comando_plugin={"cmd": "x", "params": "{}", "estado": "corriendo", "edad_s": 50}))
    check("abierto y sin terminar hace rato: colgado o largo", "sin terminar" in c, c)
    c = ojos._concluir(dict(base, ultimo_comando_plugin={"cmd": "x", "params": "{}", "estado": "ok", "edad_s": 5}))
    check("comando terminado bien no acusa a nadie", "MURIÓ" not in c, c)

    # ---- últimos comandos
    f = ojos.anotar_envio("create_line", {"x1": 1})
    ojos.anotar_fin(f, "ok")
    f2 = ojos.anotar_envio("configure_layout", {"layout": "A"})
    u = ojos.ultimos_comandos(2)
    check("últimos comandos: orden y estado", [x["cmd"] for x in u][-2:] == ["create_line", "configure_layout"] and u[-1]["estado"] == "enviado", str(u))

    # ---- la falla de conexión trae el diagnóstico
    real_port = acad._discover_port
    acad._discover_port = lambda: 1            # nada escucha ahí
    real_sleep = acad.time.sleep
    acad.time.sleep = lambda s: None
    try:
        try:
            acad.call("ping")
            check("sin conexión lanza", False)
        except acad.AutoCadConnectionError as exc:
            check("la falla de conexión trae DIAGNÓSTICO", "DIAGNÓSTICO:" in str(exc), str(exc)[-200:])
    finally:
        acad._discover_port = real_port
        acad.time.sleep = real_sleep

    # ---- la tool
    r = server.diagnose_autocad(3, 5)
    check("diagnose_autocad devuelve conclusión y últimos comandos", "conclusion" in r and isinstance(r["ultimos_comandos"], list), str(r)[:200])

    if FAILED:
        print("\nFALLARON:")
        for x in FAILED:
            print(" -", x)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
