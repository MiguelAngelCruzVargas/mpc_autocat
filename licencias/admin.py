"""Administracion de licencias desde tu PC (habla con el servidor por HTTPS; nunca toca la base directamente).

Antes, una vez por sesion de terminal:
    set LICENCIA_URL=https://tu-servidor.onrender.com
    set LICENCIA_ADMIN_TOKEN=<el mismo secreto que tiene el servidor>

Uso:
    python licencias/admin.py crear anual --nota "Juan Perez juan@correo.com"   # imprime la CLAVE: se la mandas al cliente
    python licencias/admin.py crear mensual
    python licencias/admin.py crear perpetua --equipos 3
    python licencias/admin.py listar
    python licencias/admin.py extender <kid> 365        # renovacion (suma dias desde hoy o desde el vencimiento)
    python licencias/admin.py revocar <kid>             # reembolso, abuso: deja de servir al renovar el token (max 7 dias)
    python licencias/admin.py reactivar <kid>
    python licencias/admin.py liberar <kid> [maquina]   # el cliente cambio de PC: libera un equipo (o todos)

La clave sale UNA sola vez: el servidor guarda solo su hash. Guardala junto con el correo del cliente.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def llamar(ruta: str, cuerpo: dict | None = None) -> dict:
    url, token = os.environ.get("LICENCIA_URL", ""), os.environ.get("LICENCIA_ADMIN_TOKEN", "")
    if not url or not token:
        raise SystemExit("Faltan LICENCIA_URL y LICENCIA_ADMIN_TOKEN (ver el encabezado de este archivo).")
    req = urllib.request.Request(url.rstrip("/") + ruta, method="GET" if cuerpo is None else "POST",
                                 data=None if cuerpo is None else json.dumps(cuerpo).encode(),
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit("Error %d: %s" % (exc.code, exc.read().decode(errors="replace")))


def fecha(t) -> str:
    return "-" if t is None else time.strftime("%d/%m/%Y", time.localtime(t))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crear")
    c.add_argument("plan", choices=["perpetua", "anual", "mensual"])
    c.add_argument("--dias", type=int, help="otro plazo que el del plan")
    c.add_argument("--equipos", type=int, default=2, help="equipos permitidos (2 por defecto)")
    c.add_argument("--nota", default="", help="a quien se vendio")
    sub.add_parser("listar")
    for n in ("revocar", "reactivar"):
        sub.add_parser(n).add_argument("kid")
    e = sub.add_parser("extender")
    e.add_argument("kid")
    e.add_argument("dias", type=int)
    li = sub.add_parser("liberar")
    li.add_argument("kid")
    li.add_argument("maquina", nargs="?")
    a = ap.parse_args()
    if a.cmd == "crear":
        r = llamar("/admin/crear", {"plan": a.plan, "dias": a.dias, "max_equipos": a.equipos, "nota": a.nota})
        print("CLAVE (no se vuelve a mostrar):", r["clave"])
        print("kid:", r["kid"], "| plan:", r["plan"], "| equipos:", r["max_equipos"])
    elif a.cmd == "listar":
        for lic in llamar("/admin/listar")["licencias"]:
            print("%s  %-8s %-9s vence %-10s equipos %d/%d  %s" % (lic["kid"], lic["plan"], lic["estado"], fecha(lic["vence"]), len(lic["equipos"]), lic["max_equipos"], lic["nota"]))
            for q in lic["equipos"]:
                print("      - %s (%s…) ultimo uso %s" % (q["equipo"] or "?", q["maquina"], fecha(q["ultima"])))
    elif a.cmd in ("revocar", "reactivar"):
        print(llamar("/admin/" + a.cmd, {"kid": a.kid}))
    elif a.cmd == "extender":
        r = llamar("/admin/extender", {"kid": a.kid, "dias": a.dias})
        print("Nuevo vencimiento:", fecha(r["vence"]))
    elif a.cmd == "liberar":
        print(llamar("/admin/liberar", {"kid": a.kid, "maquina": a.maquina}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
