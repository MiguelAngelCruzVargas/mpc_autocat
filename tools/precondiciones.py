"""Escáner de PRECONDICIONES de la API de AutoCAD, sobre el código descompilado.

Existe por dos cierres de AutoCAD que la lectura superficial no vio:
  - `PlotSettingsValidator.RefreshLists(layout)` con el layout abierto en LECTURA: modifica el objeto que recibe
    y, sin escritura, no lanza excepción sino una aserción fatal («INTERNAL ERROR: eNotOpenForWrite»).
  - `new Ellipse()` agregada al dibujo: nace NULA (`Ellipse.IsNull`) y agregarla es una violación de acceso.

El descompilado es un envoltorio fino sobre código nativo: dice QUÉ hay (constructores, propiedades, firmas), no
qué exige cada método por dentro. Lo que SÍ se puede leer y este script lee:
  1. clases que pueden estar NULAS (`IsNull`) y cuáles tienen constructor con datos (la forma segura de crearlas);
  2. clases sin constructor público (se obtienen de la base de datos, no con `new`);
  3. métodos que MODIFICAN lo que reciben (nombres Set/Add/Remove/Refresh/Update/Append/Erase/Transform...) y
     sus parámetros que son objetos de la base de datos: ahí el argumento tiene que estar abierto para ESCRITURA
     o ser una copia suelta (fuera de la base);
  4. métodos que reciben `ObjectId`/`Database`: el objeto tiene que existir en esa base.
Es una HEURÍSTICA para saber dónde mirar y qué probar en un dibujo descartable ANTES de escribir la herramienta; no
reemplaza la prueba en vivo (una lista de «sospechosos», no de «culpables»).

Uso:
  python tools/precondiciones.py Ellipse PlotSettingsValidator Group     # informe de esas clases
  python tools/precondiciones.py --catalogo [salida.md]                  # barrido de todo (clases nulas, sin ctor...)
Opciones: --version 2022|2027 (default 2022), --raiz <carpeta de api_por_version o autocad>.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Optional

RAIZ_DEFECTO = os.path.join(os.path.expanduser("~"), "Desktop", "Autodesk_descompilado", "autocad")
DLLS = ("acdbmgd", "accoremgd", "acmgd")

RE_CLASE = re.compile(r"^public (?:(?:sealed|abstract|static|unsafe|partial) )*(class|struct|interface|enum)\s+(\w+)(?:\s*:\s*([^\r\n{]+))?", re.M)
RE_MIEMBRO = re.compile(r"^\tpublic (?:(?:static|virtual|override|unsafe|abstract|new|sealed|readonly) )*(.+)$", re.M)
MUTA = re.compile(r"^(Set|Add|Remove|Refresh|Update|Append|Insert|Erase|Transform|Move|Rotate|Scale|Mirror|Delete|Clear|Replace|"
                  r"Reverse|Extend|Trim|Join|Explode|Offset|Fillet|Chamfer|Boolean|Slice|Extrude|Revolve|Sweep|Loft|Create|"
                  r"Copy|Paste|Attach|Detach|Bind|Unload|Reload|Purge|Save|Restore|Import|Convert|Align|Close|Open|Upgrade|Downgrade)")
TIPOS_BD = ("Entity", "DBObject", "PlotSettings", "Layout", "BlockTableRecord", "LayerTableRecord", "SymbolTableRecord",
            "Viewport", "Polyline", "Curve", "Solid3d", "Region", "Surface", "Table", "Group", "Hatch", "Database")


# Lo que se COMPROBÓ en vivo sobre las clases nulas (lo demás es «sospechoso», no «culpable»).
CONOCIDO = {
    "Ellipse": "CIERRA AutoCAD si se agrega vacía (violación de acceso; verificado en 2022): construir con datos. create_ellipse lo hace.",
    "Spline": "NO probada; create_object la bloquea por precaución (create_spline la crea con sus datos).",
    "Solid3d": "SEGURA vacía: se usa así con CreateBox/Extrude (verificado en 2022 y 2027).",
    "Region": "SEGURA vacía (verificado en 2027).",
    "Body": "SEGURA vacía (verificado en 2027).",
}


def _buscar_clase(raiz: str, version: str, nombre: str) -> list[tuple[str, str]]:
    """[(ruta, texto)] de los archivos de esa clase."""
    res = []
    for dll in DLLS:
        base = os.path.join(raiz, version, dll)
        if not os.path.isdir(base):
            continue
        for dp, _, fs in os.walk(base):
            if nombre + ".cs" in fs:
                ruta = os.path.join(dp, nombre + ".cs")
                res.append((ruta, open(ruta, encoding="utf-8", errors="ignore").read()))
    return res


def analizar(texto: str) -> dict:
    m = RE_CLASE.search(texto)
    if not m:
        return {}
    nombre, base = m.group(2), (m.group(3) or "").strip()
    ctors, props, metodos = [], [], []
    for x in RE_MIEMBRO.findall(texto):
        x = x.strip()
        if x.startswith(("class ", "struct ", "enum ", "interface ")):
            continue
        if re.match(rf"^{re.escape(nombre)}\(", x):
            ctors.append(x)
            continue
        mm = re.match(r"^(.+?) (\w+)(?:<[^>]*>)?\((.*)\)", x)
        if mm and "=>" not in x.split("(")[0]:
            metodos.append((mm.group(1), mm.group(2), mm.group(3)))
        else:
            pm = re.match(r"^(.+?) (\w+)\s*(?:=>.*)?$", x)
            if pm:
                props.append((pm.group(1), pm.group(2)))
    tiene_isnull = any(n == "IsNull" for _, n in props)
    return {"nombre": nombre, "base": base, "ctors": ctors, "props": props, "metodos": metodos, "isnull": tiene_isnull,
            "setters": len(re.findall(r"\bset\b\s*\{|\bset\s*$", texto))}


def informe_clase(raiz: str, version: str, nombre: str) -> str:
    archivos = _buscar_clase(raiz, version, nombre)
    if not archivos:
        return f"## {nombre}\n  (no está en el descompilado de {version})\n"
    out = []
    for ruta, texto in archivos:
        a = analizar(texto)
        if not a:
            continue
        out.append(f"## {a['nombre']}   (hereda de: {a['base'] or '-'})   [{os.path.basename(os.path.dirname(os.path.dirname(ruta)))}]")
        con_args = [c for c in a["ctors"] if not re.match(rf"^{a['nombre']}\(\)", c)]
        sin_args = [c for c in a["ctors"] if re.match(rf"^{a['nombre']}\(\)", c)]
        if not a["ctors"]:
            out.append("  CREACIÓN: sin constructor público → no se hace con `new`: se obtiene de la base de datos o de otro objeto.")
        else:
            out.append("  Constructores: " + "; ".join(c[:110] for c in a["ctors"][:6]))
            if sin_args and con_args:
                out.append("  ⚠ Tiene constructor VACÍO y otros con datos: el vacío puede dejar un objeto en estado por defecto/nulo; usar el de datos.")
        if a["nombre"] in CONOCIDO:
            out.append("  ► COMPROBADO: " + CONOCIDO[a["nombre"]])
        if a["isnull"]:
            out.append("  ⚠ NACE NULA (tiene `IsNull`): construida vacía es un objeto sin forma. Agregarla a la base de datos "
                       "sin darle forma (Set/constructor con datos) puede cerrar AutoCAD. Dale forma ANTES de agregarla y verificá `IsNull`.")
        muta = [(r, n, p) for r, n, p in a["metodos"] if MUTA.match(n)]
        con_bd = [(r, n, p) for r, n, p in a["metodos"] if any(re.search(rf"\b{t}\b", p) for t in TIPOS_BD)]
        if muta:
            out.append(f"  Métodos que MODIFICAN ({len(muta)}): el objeto sobre el que se llaman debe estar abierto ForWrite → "
                       + ", ".join(sorted({n for _, n, _ in muta})[:25]) + (" …" if len({n for _, n, _ in muta}) > 25 else ""))
        arg_bd = [(n, p) for _, n, p in muta if any(re.search(rf"\b{t}\b", p) for t in TIPOS_BD)]
        if arg_bd:
            out.append("  ⚠ Modifican un ARGUMENTO que es objeto de la base de datos (debe estar abierto para ESCRITURA o ser una copia suelta; "
                       "en lectura es una aserción fatal, no una excepción):")
            for n, p in arg_bd[:12]:
                out.append(f"      {n}({p[:100]})")
        elif con_bd:
            out.append("  Reciben objetos de la base de datos (tienen que existir en ESA base): "
                       + ", ".join(sorted({n for _, n, _ in con_bd})[:15]))
        if a["setters"]:
            out.append(f"  Propiedades escribibles: ~{a['setters']} (cambiarlas exige ForWrite si el objeto ya está en la base).")
    return "\n".join(out) + "\n"


def catalogo(raiz: str, version: str) -> str:
    nulas, sin_ctor, vacio_y_datos = [], [], []
    for dll in DLLS:
        base = os.path.join(raiz, version, dll)
        for dp, _, fs in os.walk(base):
            if "DatabaseServices" not in dp:
                continue
            for f in fs:
                if not f.endswith(".cs"):
                    continue
                a = analizar(open(os.path.join(dp, f), encoding="utf-8", errors="ignore").read())
                if not a or not re.search(r"\b(Entity|Curve|DBObject|Surface|Dimension|Solid3d|Region)\b", a["base"] + " " + a["nombre"]):
                    continue
                if a["isnull"]:
                    nulas.append(a["nombre"])
                if not a["ctors"]:
                    sin_ctor.append(a["nombre"])
                elif any(re.match(rf"^{a['nombre']}\(\)", c) for c in a["ctors"]) and len(a["ctors"]) > 1:
                    vacio_y_datos.append(a["nombre"])
    salida = [f"# Precondiciones de la API (AutoCAD {version}, por lectura del descompilado)", "",
              "## Clases que pueden estar NULAS (`IsNull`)", "",
              "Construidas con `new X()` quedan sin forma. "
              "Lo comprobado en vivo está al lado de cada una; lo que dice «sin probar» se prueba en un dibujo descartable antes de usarlo.", "",
              chr(10).join(f"- **{n}**: {CONOCIDO.get(n, 'sin probar')}" for n in sorted(set(nulas))), "",
              "## Entidades/objetos SIN constructor público", "", ", ".join(sorted(set(sin_ctor))), "",
              "## Con constructor vacío Y constructores con datos (preferir los de datos)", "", ", ".join(sorted(set(vacio_y_datos))), ""]
    return "\n".join(salida)


def main(argv: list[str]) -> int:
    version, raiz = "2022", RAIZ_DEFECTO
    args = []
    i = 0
    while i < len(argv):
        if argv[i] == "--version":
            version = argv[i + 1]; i += 2; continue
        if argv[i] == "--raiz":
            raiz = argv[i + 1]; i += 2; continue
        args.append(argv[i]); i += 1
    if not args:
        print(__doc__)
        return 2
    if args[0] == "--catalogo":
        t = catalogo(raiz, version)
        if len(args) > 1:
            open(args[1], "w", encoding="utf-8").write(t)
            print("catálogo escrito en", args[1])
        else:
            print(t)
        return 0
    for n in args:
        print(informe_clase(raiz, version, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
