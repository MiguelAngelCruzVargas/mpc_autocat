"""Coordinación entre sesiones de Claude Code que trabajan sobre ESTE repo.

Por qué existe. Dos sesiones (de cuentas distintas, así que SendMessage no
las une) editaban la misma carpeta a la vez: una commiteaba mientras la
otra tenía un archivo a medio escribir, y ninguna sabía de la otra. Lo único
que comparten es el disco, así que la coordinación va por un archivo:
`.claude/coordinacion/estado.json` (fuera de git).

Lo usan los hooks de `.claude/settings.json`, sin que nadie tenga que
acordarse:

- hook-start / hook-prompt  (SessionStart, UserPromptSubmit)
    registra la sesión y le muestra quién más está, qué tiene tomado y los
    mensajes que le dejaron.
- hook-pre   (PreToolUse: Edit|Write|NotebookEdit|Bash)
    niega editar un archivo que tiene reclamado OTRA sesión activa, y niega
    los git masivos (add -A, commit -a, stash, reset --hard...) mientras la
    otra tenga archivos tomados: así se mezcló trabajo ajeno en un commit.
- hook-post  (PostToolUse: Edit|Write|NotebookEdit|Bash)
    reclama solo el archivo recién editado y entrega mensajes nuevos.

Y a mano (la identidad sale de CLAUDE_CODE_SESSION_ID, o de --yo):

    python tools/coordinacion.py estado
    python tools/coordinacion.py nombre "sesion-muros"
    python tools/coordinacion.py tarea "red de muros: wall_network.py"
    python tools/coordinacion.py reclamar mcp_server/arch.py --min 60
    python tools/coordinacion.py liberar [archivo ...]
    python tools/coordinacion.py mensaje "ya commiteé, podés seguir" [--para nombre]
    python tools/coordinacion.py leer

Nunca rompe una sesión: ante cualquier error propio sale con 0 y no opina.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(RAIZ, ".claude", "coordinacion")
ESTADO = os.path.join(DIR, "estado.json")
LOCK = os.path.join(DIR, ".lock")

ACTIVA_S = 60 * 60       # una sesión sin actividad en 1 h ya no cuenta
RECLAMO_S = 30 * 60      # lo editado queda reclamado 30 min desde el último toque
MAX_MENSAJES = 200

def _git_masivo(cmd: str) -> bool:
    """¿Este comando arrastra o pisa archivos que no son de uno? Se mira
    token por token (shlex): con una regex, el '-a' DENTRO de un mensaje de
    commit contaba como flag."""
    for tramo in re.split(r"&&|\|\||[;|\n]", cmd):
        try:
            t = shlex.split(tramo)
        except ValueError:
            t = tramo.split()
        while t and "=" in t[0] and not t[0].startswith("-"):
            t = t[1:]  # VAR=x git ...
        if len(t) < 2 or os.path.basename(t[0]).lower() not in ("git", "git.exe"):
            continue
        sub, resto = t[1], t[2:]
        cortos = [x for x in resto if x.startswith("-") and not x.startswith("--")]
        if sub == "add" and ({"-A", "--all", ".", "-u", "--update"} & set(resto)
                             or any("A" in x or "u" in x for x in cortos)):
            return True
        if sub == "commit" and ("--all" in resto or any(
                "a" in x[1:] for x in cortos if not x.startswith("-m"))):
            return True
        if sub in ("stash", "restore", "clean"):
            return True
        if sub == "reset" and "--hard" in resto:
            return True
        if sub == "checkout" and ("--" in resto or "." in resto):
            return True
    return False


# ---------------------------------------------------------------- estado

class _Lock:
    def __enter__(self):
        os.makedirs(DIR, exist_ok=True)
        fin = time.time() + 5
        while True:
            try:
                self.fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:  # un lock de más de 15 s es de un proceso que murió
                    if time.time() - os.path.getmtime(LOCK) > 15:
                        os.remove(LOCK)
                        continue
                except OSError:
                    pass
                if time.time() > fin:
                    raise TimeoutError("lock de coordinación ocupado")
                time.sleep(0.05)

    def __exit__(self, *exc):
        os.close(self.fd)
        try:
            os.remove(LOCK)
        except OSError:
            pass


def _leer() -> dict:
    try:
        with open(ESTADO, encoding="utf-8") as f:
            e = json.load(f)
    except (OSError, ValueError):
        e = {}
    for k, v in (("sesiones", {}), ("reclamos", {}), ("mensajes", []),
                 ("leidos", {})):
        e.setdefault(k, v)
    return e


def _guardar(e: dict) -> None:
    ahora = time.time()
    e["reclamos"] = {k: r for k, r in e["reclamos"].items()
                     if r["hasta"] > ahora}
    e["mensajes"] = e["mensajes"][-MAX_MENSAJES:]
    tmp = ESTADO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ESTADO)


def _clave(path: str) -> str | None:
    """Ruta relativa al repo, normalizada; None si cae fuera de él."""
    if not path:
        return None
    p = os.path.abspath(path if os.path.isabs(path) else os.path.join(RAIZ, path))
    rel = os.path.relpath(p, RAIZ)
    if rel.startswith(".."):
        return None
    return rel.replace("\\", "/").lower()


def _activa(e: dict, sid: str) -> bool:
    s = e["sesiones"].get(sid)
    return bool(s) and time.time() - s["visto"] < ACTIVA_S


def _nombre(e: dict, sid: str) -> str:
    s = e["sesiones"].get(sid) or {}
    return s.get("nombre") or sid[:8]


def _tocar(e: dict, sid: str, cwd: str = "") -> None:
    s = e["sesiones"].setdefault(sid, {"desde": time.time()})
    s["visto"] = time.time()
    if cwd:
        s["cwd"] = cwd


def _hhmm(t: float) -> str:
    return time.strftime("%H:%M", time.localtime(t))


def _otros(e: dict, sid: str) -> list[str]:
    return [o for o in e["sesiones"] if o != sid and _activa(e, o)]


def _reclamos_de(e: dict, sid: str) -> list[str]:
    ahora = time.time()
    return sorted(r["ruta"] for r in e["reclamos"].values()
                  if r["sid"] == sid and r["hasta"] > ahora)


def _no_leidos(e: dict, sid: str, marcar: bool = True) -> list[dict]:
    ult = e["leidos"].get(sid, 0)
    nombre = _nombre(e, sid)
    nuevos = [m for m in e["mensajes"] if m["id"] > ult and m["de"] != sid
              and m["para"] in ("todos", sid, nombre)]
    if marcar and e["mensajes"]:
        e["leidos"][sid] = max(ult, e["mensajes"][-1]["id"])
    return nuevos


def _fmt_mensajes(e: dict, ms: list[dict]) -> str:
    return "\n".join(f"  [{_hhmm(m['ts'])}] {_nombre(e, m['de'])}: {m['texto']}"
                     for m in ms)


def _panorama(e: dict, sid: str) -> str:
    """Las otras sesiones activas, qué hacen y qué tienen tomado."""
    lineas = []
    for o in _otros(e, sid):
        s = e["sesiones"][o]
        lineas.append(f"- {_nombre(e, o)} (activa {_hhmm(s['visto'])})"
                      + (f" — {s['tarea']}" if s.get("tarea") else ""))
        recl = _reclamos_de(e, o)
        if recl:
            lineas.append("  tiene tomados: " + ", ".join(recl))
    return "\n".join(lineas)


# ---------------------------------------------------------------- hooks

def _salida(evento: str, contexto: str = "", **extra) -> None:
    out: dict = dict(extra)
    if contexto:
        out["hookSpecificOutput"] = {"hookEventName": evento,
                                     "additionalContext": contexto}
    if out:
        sys.stdout.write(json.dumps(out, ensure_ascii=True))


def hook_start(d: dict, evento: str) -> None:
    sid = d.get("session_id", "")
    with _Lock():
        e = _leer()
        _tocar(e, sid, d.get("cwd", ""))
        otros, nuevos = _panorama(e, sid), _no_leidos(e, sid)
        _guardar(e)
        nombre = _nombre(e, sid)
    partes = []
    if evento == "SessionStart":
        partes.append(
            f"Coordinación de sesiones activa en este repo. Sos «{nombre}». "
            "Lo que edites con Edit/Write queda reclamado solo 30 min; lo que "
            "reclame otra sesión no se puede editar. Avisos y estado: "
            "`python tools/coordinacion.py estado|tarea|mensaje|liberar` "
            "(ver su docstring). Si escribís archivos por Bash, reclamalos "
            "antes con `reclamar`.")
    if otros:
        partes.append("Otras sesiones trabajando en este repo AHORA:\n" + otros
                      + "\nNo toques sus archivos, no hagas git add -A ni "
                      "commits de lo que no es tuyo; coordiná con `mensaje`.")
    if nuevos:
        partes.append("Mensajes de otras sesiones:\n" + _fmt_mensajes(e, nuevos))
    _salida(evento, "\n\n".join(partes))


def hook_pre(d: dict) -> None:
    sid = d.get("session_id", "")
    herr = d.get("tool_name", "")
    ti = d.get("tool_input") or {}
    e = _leer()  # lectura sin lock: alcanza para decidir
    ahora = time.time()
    motivo = ""
    if herr == "Bash":
        cmd = ti.get("command", "")
        if _git_masivo(cmd):
            ajenos = [(o, _reclamos_de(e, o)) for o in _otros(e, sid)]
            ajenos = [(o, r) for o, r in ajenos if r]
            if ajenos:
                detalle = "; ".join(f"{_nombre(e, o)}: {', '.join(r)}"
                                    for o, r in ajenos)
                motivo = ("Otra sesión está trabajando en este repo y tiene "
                          f"archivos tomados ({detalle}). Este git arrastraría "
                          "o pisaría su trabajo: agregá solo tus archivos por "
                          "nombre (git add <ruta>) y avisale con "
                          "`python tools/coordinacion.py mensaje`.")
    else:
        k = _clave(ti.get("file_path") or ti.get("notebook_path") or "")
        r = e["reclamos"].get(k) if k else None
        if r and r["sid"] != sid and r["hasta"] > ahora and _activa(e, r["sid"]):
            motivo = (f"{r['ruta']} lo tiene tomado la sesión "
                      f"«{_nombre(e, r['sid'])}» desde {_hhmm(r['desde'])}"
                      + (f" ({r['nota']})" if r.get("nota") else "")
                      + ". No lo edites: pedíselo con `python tools/"
                      "coordinacion.py mensaje \"...\"` o esperá a que lo "
                      "libere.")
    if motivo:
        _salida("PreToolUse", hookSpecificOutput={
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": motivo})


def hook_post(d: dict) -> None:
    sid = d.get("session_id", "")
    ti = d.get("tool_input") or {}
    with _Lock():
        e = _leer()
        _tocar(e, sid, d.get("cwd", ""))
        if d.get("tool_name") != "Bash":
            ruta = ti.get("file_path") or ti.get("notebook_path") or ""
            k = _clave(ruta)
            if k:
                r = e["reclamos"].get(k)
                if not r or r["sid"] == sid or r["hasta"] < time.time():
                    _reclamar(e, sid, k, RECLAMO_S, (r or {}).get("nota", ""))
        nuevos = _no_leidos(e, sid)
        _guardar(e)
    if nuevos:
        _salida("PostToolUse", "Mensaje de otra sesión que trabaja en este "
                "repo:\n" + _fmt_mensajes(e, nuevos))


def _reclamar(e: dict, sid: str, k: str, dur: float, nota: str = "") -> None:
    viejo = e["reclamos"].get(k)
    e["reclamos"][k] = {
        "ruta": k, "sid": sid, "nota": nota,
        "desde": viejo["desde"] if viejo and viejo["sid"] == sid else time.time(),
        "hasta": time.time() + dur}


# ---------------------------------------------------------------- CLI

def _cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="coordinacion.py")
    ap.add_argument("--yo", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
                    help="id de sesión (por defecto CLAUDE_CODE_SESSION_ID)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("estado")
    sub.add_parser("leer")
    p = sub.add_parser("nombre"); p.add_argument("alias")
    p = sub.add_parser("tarea"); p.add_argument("texto")
    p = sub.add_parser("reclamar"); p.add_argument("rutas", nargs="+")
    p.add_argument("--min", type=float, default=RECLAMO_S / 60)
    p.add_argument("--nota", default="")
    p = sub.add_parser("liberar"); p.add_argument("rutas", nargs="*")
    p = sub.add_parser("mensaje"); p.add_argument("texto")
    p.add_argument("--para", default="todos")
    a = ap.parse_args(argv)
    sid = a.yo or "manual"

    with _Lock():
        e = _leer()
        _tocar(e, sid)
        if a.cmd == "nombre":
            e["sesiones"][sid]["nombre"] = a.alias
            print(f"ahora sos «{a.alias}»")
        elif a.cmd == "tarea":
            e["sesiones"][sid]["tarea"] = a.texto
            print("tarea anotada")
        elif a.cmd == "reclamar":
            for ruta in a.rutas:
                k = _clave(ruta)
                r = e["reclamos"].get(k) if k else None
                if not k:
                    print(f"fuera del repo, ignorado: {ruta}")
                elif r and r["sid"] != sid and r["hasta"] > time.time() \
                        and _activa(e, r["sid"]):
                    print(f"NO: {k} es de «{_nombre(e, r['sid'])}»")
                else:
                    _reclamar(e, sid, k, a.min * 60, a.nota)
                    print(f"reclamado {k} por {a.min:g} min")
        elif a.cmd == "liberar":
            claves = {_clave(r) for r in a.rutas} if a.rutas else None
            sueltos = [k for k, r in e["reclamos"].items() if r["sid"] == sid
                       and (claves is None or k in claves)]
            for k in sueltos:
                del e["reclamos"][k]
            print("liberados: " + (", ".join(sueltos) or "ninguno"))
        elif a.cmd == "mensaje":
            nid = (e["mensajes"][-1]["id"] + 1) if e["mensajes"] else 1
            e["mensajes"].append({"id": nid, "de": sid, "para": a.para,
                                  "ts": time.time(), "texto": a.texto})
            print(f"mensaje #{nid} dejado para {a.para}")
        elif a.cmd == "leer":
            ms = _no_leidos(e, sid)
            print(_fmt_mensajes(e, ms) if ms else "sin mensajes nuevos")
        elif a.cmd == "estado":
            print(f"yo: «{_nombre(e, sid)}»"
                  + (f" — {e['sesiones'][sid].get('tarea')}"
                     if e["sesiones"][sid].get("tarea") else ""))
            mios = _reclamos_de(e, sid)
            print("  tengo tomados: " + (", ".join(mios) or "nada"))
            print(_panorama(e, sid) or "no hay otras sesiones activas")
            ms = _no_leidos(e, sid, marcar=False)
            if ms:
                print("mensajes sin leer:\n" + _fmt_mensajes(e, ms))
        _guardar(e)
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1].startswith("hook-"):
        try:
            d = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
            modo = sys.argv[1]
            if modo == "hook-start":
                hook_start(d, "SessionStart")
            elif modo == "hook-prompt":
                hook_start(d, "UserPromptSubmit")
            elif modo == "hook-pre":
                hook_pre(d)
            elif modo == "hook-post":
                hook_post(d)
        except Exception:
            pass  # la coordinación nunca puede trabar una sesión
        return 0
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return _cli(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
