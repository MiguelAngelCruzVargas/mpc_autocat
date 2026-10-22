"""Los OJOS de la herramienta: qué le pasó a AutoCAD, sin que nadie tenga que adivinar.

Antes, cuando un comando se colgaba o AutoCAD se cerraba, la única señal era «no se pudo conectar» o un
timeout, y la IA gastaba turnos averiguando qué pasó (¿hay un diálogo abierto? ¿se cayó? ¿qué comando fue?).
Esto lo mira directamente, desde afuera de AutoCAD —por eso funciona aun cuando AutoCAD está bloqueado por un
diálogo modal y el plugin no puede contestar—, igual que hace Autodesk en su servidor nativo, que mantiene el
estado del editor y la salida de la línea de comandos a la vista:

  - qué ventanas/diálogos tiene abiertos AutoCAD y qué texto traen («AutoCAD Error Aborting»: «INTERNAL ERROR…»);
  - lo que AutoCAD dejó escrito al caerse: `acad.err`, minivolcados `.dmp`, carpetas `ErrorReports`, y el
    registro de diálogos que el plugin cierra solo (`dialogos.log`);
  - los últimos comandos que este proceso le mandó, con parámetros resumidos y cómo terminó cada uno: el
    culpable de una caída casi siempre es uno de los últimos.

`diagnostico()` junta todo en un dict con una `conclusion` en una frase. `autocad_client` lo agrega solo al
mensaje de las fallas de conexión y de los cortes, y la tool `diagnose_autocad` lo da a pedido.

Solo lee: no cierra diálogos, no mata procesos, no escribe nada.
"""
from __future__ import annotations

import collections
import ctypes
import ctypes.wintypes
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Optional

# ------------------------------------------------------------------ últimos comandos

_ULTIMOS: collections.deque = collections.deque(maxlen=40)


def _resumir(params: Any, tope: int = 160) -> str:
    try:
        t = json.dumps(params, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        t = str(params)
    return t if len(t) <= tope else t[:tope] + "…"


def anotar_envio(cmd: str, params: Optional[dict]) -> dict:
    """Se llama justo antes de mandar un comando; devuelve la ficha para cerrarla con `anotar_fin`."""
    ficha = {"cmd": cmd, "params": _resumir(params or {}), "t": time.time(), "estado": "enviado"}
    _ULTIMOS.append(ficha)
    return ficha


def anotar_fin(ficha: dict, estado: str, detalle: str = "") -> None:
    ficha["estado"] = estado
    ficha["ms"] = round((time.time() - ficha["t"]) * 1000)
    if detalle:
        ficha["detalle"] = detalle[:200]


def ultimos_comandos(n: int = 8) -> list[dict]:
    salida = []
    for f in list(_ULTIMOS)[-n:]:
        d = {"cmd": f["cmd"], "params": f["params"], "estado": f["estado"], "hace_s": round(time.time() - f["t"], 1)}
        if "ms" in f:
            d["ms"] = f["ms"]
        if "detalle" in f:
            d["detalle"] = f["detalle"]
        salida.append(d)
    return salida


# ------------------------------------------------------------------ procesos y ventanas (Windows)

def _procesos_autocad() -> list[dict]:
    """pid y, si hay psutil, directorio de trabajo y hora de arranque de cada acad.exe."""
    try:
        import psutil  # opcional
        res = []
        for p in psutil.process_iter(["name", "pid", "create_time"]):
            if (p.info["name"] or "").lower() == "acad.exe":
                try:
                    cwd = p.cwd()
                except Exception:  # noqa: BLE001
                    cwd = None
                res.append({"pid": p.info["pid"], "cwd": cwd, "inicio": p.info["create_time"]})
        return res
    except ImportError:
        pass
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq acad.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [{"pid": int(m.group(1)), "cwd": None, "inicio": None} for m in re.finditer(r'"acad\.exe","(\d+)"', out)]


def ventanas(pids: Optional[list[int]] = None) -> list[dict]:
    """Ventanas visibles de nivel superior de AutoCAD con título, clase y el texto de sus controles. Un diálogo
    de error trae su mensaje en un control de texto: se lee sin hacer clic en nada."""
    if sys.platform != "win32":
        return []
    if pids is None:
        pids = [p["pid"] for p in _procesos_autocad()]
    if not pids:
        return []
    user32 = ctypes.windll.user32
    wt = ctypes.wintypes
    res: list[dict] = []
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def texto(h) -> str:
        n = user32.GetWindowTextLengthW(h)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(h, buf, n + 1)
        return buf.value

    def clase(h) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, buf, 256)
        return buf.value

    def cb(h, _):
        if not user32.IsWindowVisible(h):
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        titulo, cls = texto(h), clase(h)
        if not titulo and not cls:
            return True
        hijos: list[str] = []

        def cb_hijo(hh, __):
            t = texto(hh).strip()
            if t and t not in hijos:
                hijos.append(t)
            return True

        user32.EnumChildWindows(h, EnumProc(cb_hijo), 0)
        res.append({"titulo": titulo, "clase": cls, "pid": pid.value, "textos": hijos[:12],
                    "modal": bool(user32.GetWindow(h, 4))})        # GW_OWNER
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return res


_CLASES_NORMALES = ("AfxMDIFrame", "AcTaskBarWin", "HwndWrapper", "AcDockPaneContainer", "Afx:")


def dialogos_abiertos() -> list[dict]:
    """De las ventanas, las que son un diálogo o aviso: con título, que no son el marco principal de AutoCAD, la
    barra de tareas del dibujo ni los contenedores de paletas (esos no tienen título o son de la interfaz)."""
    res = []
    for v in ventanas():
        if not v["titulo"].strip():
            continue
        if v["clase"].startswith(_CLASES_NORMALES):
            continue
        res.append(v)
    return res


# ------------------------------------------------------------------ huellas de error

def _carpetas_candidatas() -> list[str]:
    c: list[str] = []
    for p in _procesos_autocad():
        if p.get("cwd"):
            c.append(p["cwd"])
    here = os.path.dirname(os.path.abspath(__file__))
    c += [os.getcwd(), os.path.dirname(here), here, os.environ.get("TEMP", ""), os.environ.get("TMP", ""),
          os.path.join(os.path.expanduser("~"), "Documents"), os.path.expanduser("~"),
          os.path.join(os.path.expanduser("~"), "Desktop")]
    vistas, salida = set(), []
    for d in c:
        if d and os.path.isdir(d) and os.path.normcase(os.path.abspath(d)) not in vistas:
            vistas.add(os.path.normcase(os.path.abspath(d)))
            salida.append(d)
    return salida


_RE_FECHA = re.compile(r"(\d{1,2}/\d{1,2}/\d{4}) at (\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)\s+Drawing:\s*(.*)")


def leer_acad_err(desde: float = 0.0, maximo: int = 5) -> list[dict]:
    """Entradas de cualquier `acad.err` modificado desde `desde` (epoch). AutoCAD lo deja en su directorio de
    trabajo al caerse; cada entrada trae el mensaje, el dibujo y la hora."""
    entradas: list[dict] = []
    for d in _carpetas_candidatas():
        ruta = os.path.join(d, "acad.err")
        try:
            if not os.path.isfile(ruta) or os.path.getmtime(ruta) < desde:
                continue
            texto = open(ruta, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for bloque in texto.split("-------------"):
            lineas = [x.rstrip() for x in bloque.strip().splitlines() if x.strip()]
            if not lineas:
                continue
            m = _RE_FECHA.search(bloque)
            entradas.append({
                "archivo": ruta,
                "mensaje": " ".join(x for x in lineas if not _RE_FECHA.search(x))[:300],
                "dibujo": m.group(3).strip() if m else None,
                "hora": (m.group(1) + " " + m.group(2)) if m else None,
                "mtime": os.path.getmtime(ruta),
            })
    entradas.sort(key=lambda e: e["mtime"], reverse=True)
    return entradas[:maximo]


def volcados(desde: float = 0.0) -> list[dict]:
    res = []
    for d in _carpetas_candidatas():
        try:
            for f in os.listdir(d):
                if f.lower().endswith(".dmp") and ("acminidump" in f.lower() or f.lower().startswith("acad")):
                    ruta = os.path.join(d, f)
                    mt = os.path.getmtime(ruta)
                    if mt >= desde:
                        res.append({"archivo": ruta, "mtime": mt, "hora": time.strftime("%H:%M:%S", time.localtime(mt))})
        except OSError:
            continue
    res.sort(key=lambda e: e["mtime"], reverse=True)
    return res[:4]


def ultimo_comando_plugin() -> Optional[dict]:
    """Lo que el plugin dejó anotado como su último comando (Bitacora.cs): `estado` «corriendo» si no llegó a
    terminar. Si AutoCAD se cayó, ese es el culpable; si sigue abierto y lleva mucho en «corriendo», está
    colgado o es una operación larga."""
    ruta = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AutoCadMcp", "ultimo_comando.json")
    try:
        d = json.load(open(ruta, encoding="utf-8"))
        d["edad_s"] = round(time.time() - os.path.getmtime(ruta), 1)
        return d
    except (OSError, ValueError):
        return None


def _registro_dialogos(desde: float = 0.0) -> list[str]:
    ruta = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "AutoCadMcp", "dialogos.log")
    try:
        if os.path.getmtime(ruta) < desde:
            return []
        return [l.strip() for l in open(ruta, encoding="utf-8", errors="replace").read().splitlines()[-5:]]
    except OSError:
        return []


# ------------------------------------------------------------------ diagnóstico

def diagnostico(ultimos: int = 8, ventana_s: float = 900.0) -> dict[str, Any]:
    """Todo junto, con una conclusión en una frase. `ventana_s`: cuánto atrás buscar huellas de caída."""
    desde = time.time() - ventana_s
    procs = _procesos_autocad()
    dlg = dialogos_abiertos() if procs else []
    errores = leer_acad_err(desde)
    dumps = volcados(desde)
    # Con AutoCAD abierto, lo escrito ANTES de que arrancara este proceso es de una sesión anterior: no cuenta.
    inicios = [p["inicio"] for p in procs if p.get("inicio")]
    if inicios:
        corte = max(inicios) - 5
        errores = [e for e in errores if e["mtime"] >= corte]
        dumps = [x for x in dumps if x["mtime"] >= corte]
    log = _registro_dialogos(desde)
    ult = ultimos_comandos(ultimos)
    d: dict[str, Any] = {
        "autocad_abierto": bool(procs), "procesos": [p["pid"] for p in procs],
        "dialogos_abiertos": dlg, "errores_recientes": errores, "volcados_recientes": dumps,
        "registro_dialogos_plugin": log, "ultimos_comandos": ult,
        "ultimo_comando_plugin": ultimo_comando_plugin(),
    }
    d["conclusion"] = _concluir(d)
    return d


def _concluir(d: dict[str, Any]) -> str:
    ult = d["ultimos_comandos"]
    ultimo = ult[-1] if ult else None
    pl = d.get("ultimo_comando_plugin")
    if pl and pl.get("estado") == "corriendo" and pl.get("edad_s", 0) < 3600:
        if not d["autocad_abierto"]:
            err = (" Error de AutoCAD: «" + d["errores_recientes"][0]["mensaje"] + "».") if d["errores_recientes"] else ""
            return (f"AutoCAD MURIÓ ejecutando «{pl['cmd']}» {pl.get('params', '')} (a las {pl.get('inicio', '?')}): ese comando no llegó a terminar."
                    + err + " Es el primer sospechoso.")
        if pl.get("edad_s", 0) > 20 and not d["dialogos_abiertos"]:
            return (f"AutoCAD lleva {pl['edad_s']} s sin terminar «{pl['cmd']}» {pl.get('params', '')}: o es una operación larga o está colgado.")
    sospechoso = ""
    if ultimo:
        sospechoso = f" El último comando enviado fue «{ultimo['cmd']}» {ultimo['params']} (estado: {ultimo['estado']})."
    if d["autocad_abierto"] and d["dialogos_abiertos"]:
        v = d["dialogos_abiertos"][0]
        txt = " / ".join(v["textos"]) if v["textos"] else "(sin texto legible: miralo en pantalla)"
        return (f"AutoCAD está abierto pero BLOQUEADO por un diálogo: «{v['titulo']}» — {txt}. "
                "Mientras siga abierto el plugin no contesta; lo cierra una persona." + sospechoso)
    if not d["autocad_abierto"]:
        if d["errores_recientes"]:
            e = d["errores_recientes"][0]
            return (f"AutoCAD NO está corriendo y dejó escrito un error: «{e['mensaje']}»"
                    + (f" (dibujo {e['dibujo']}, {e['hora']})" if e["dibujo"] else "") + "." + sospechoso)
        if d["volcados_recientes"]:
            return "AutoCAD NO está corriendo y dejó un volcado de memoria reciente (cayó)." + sospechoso
        return "AutoCAD no está corriendo (sin huellas de error recientes: se cerró normal o nunca se abrió)."
    if d["errores_recientes"] or d["volcados_recientes"]:
        return ("AutoCAD sigue abierto, pero hay huellas de un error reciente: "
                + (d["errores_recientes"][0]["mensaje"] if d["errores_recientes"] else "volcado de memoria") + "." + sospechoso)
    return "AutoCAD está abierto y sin diálogos ni errores recientes: si un comando no responde, está ocupado (mirá get_editor_state)." + sospechoso


def resumen_para_error() -> str:
    """Texto corto para pegar al mensaje de una falla de conexión o un corte."""
    try:
        d = diagnostico(ultimos=3)
    except Exception as exc:  # noqa: BLE001 — los ojos nunca deben tumbar el error original
        return f"(no se pudo diagnosticar: {exc})"
    return "DIAGNÓSTICO: " + d["conclusion"]
