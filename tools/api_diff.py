"""Compara la API administrada de AutoCAD entre versiones, miembro por miembro.

Parte de las carpetas que deja ilspycmd (`ilspycmd -p -o <dir> <dll>`) sobre los ensamblados de
referencia de cada versión (`acdbmgd`, `accoremgd`, `acmgd`), una carpeta por versión:

    <raiz>/2019/acdbmgd/..., <raiz>/2019/accoremgd/..., <raiz>/2019/acmgd/...
    <raiz>/2022/..., <raiz>/2024/..., <raiz>/2025/..., <raiz>/2026/..., <raiz>/2027/...

y escribe un informe en Markdown con: cuántas clases, propiedades y métodos tiene cada versión,
qué aparece o desaparece entre versiones consecutivas, y —lo que más importa para este
proyecto— los miembros de la lista `USADOS` (lo que el plugin y las tools llaman por nombre) que
faltan en alguna versión.

El análisis es por texto sobre el C# descompilado (expresiones regulares), no por reflexión: sirve
para ver qué cambió, no como garantía de firma. Para eso está `tools/matriz_api.py`, que COMPILA el
plugin contra cada versión.

Uso:  python tools/api_diff.py <raiz> [salida.md]
"""
from __future__ import annotations

import os
import re
import sys
from typing import Iterable

DLLS = ("acdbmgd", "accoremgd", "acmgd")
RE_CLASE = re.compile(r"^public (?:(?:sealed|abstract|static|unsafe|partial) )*(class|struct|interface|enum)\s+(\w+)", re.M)
RE_NS = re.compile(r"^namespace ([\w.]+)", re.M)
RE_LINEA = re.compile(r"^\tpublic(?:(?:static|virtual|override|unsafe|abstract|new|sealed|readonly) )*(.+)$")
RE_METODO = re.compile(r"^(.+?) (\w+)(?:<[^>]*>)?\((.*)\)\s*(?:where .*)?$")
RE_PROP = re.compile(r"^(.+?) (\w+)\s*(?:=>.*|\{.*)?$")
RESERVADAS = ("class", "struct", "enum", "interface", "delegate", "event", "new", "const")

# Lo que el plugin y las tools llaman por nombre (clase, miembro). Si falta en una versión, esa
# versión no va a poder ejecutar la función que lo usa.
USADOS = [
    ("Database", "Handseed"), ("Database", "Purge"), ("Database", "UndoRecording"), ("Database", "DisableUndoRecording"),
    ("Database", "SetDimstyleData"), ("Database", "ObjectContextManager"), ("Database", "GroupDictionaryId"),
    ("Database", "LayoutDictionaryId"), ("Database", "RegAppTableId"), ("Database", "CurrentSpaceId"),
    ("Database", "UpdateExt"), ("Database", "Clayer"), ("Database", "Textstyle"), ("Database", "Dimstyle"),
    ("DBObject", "XData"), ("DBObject", "GetXDataForApplication"), ("DBObject", "ExtensionDictionary"),
    ("DBObject", "CreateExtensionDictionary"), ("DBObject", "UpgradeOpen"), ("DBObject", "Erase"),
    ("Curve", "GetOffsetCurves"), ("Curve", "GetSplitCurves"),
    ("Curve", "GetClosestPointTo"), ("Entity", "IntersectWith"), ("Entity", "TransformBy"),
    ("Solid3d", "MassProperties"), ("Solid3d", "CreateBox"), ("Solid3d", "BooleanOperation"), ("Solid3d", "Slice"),
    ("Solid3d", "Extrude"), ("Solid3d", "OffsetBody"), ("Solid3d", "CheckInterference"),
    ("SubDMesh", "ComputeVolume"), ("SubDMesh", "ConvertToSolid"), ("SubDMesh", "SetSphere"),
    ("BlockReference", "DynamicBlockReferencePropertyCollection"), ("BlockReference", "IsDynamicBlock"),
    ("BlockReference", "AttributeCollection"), ("DynamicBlockReferenceProperty", "GetAllowedValues"),
    ("BlockTableRecord", "GetBlockReferenceIds"), ("Group", "Append"), ("Group", "NumEntities"),
    ("Xrecord", "Data"), ("AnnotationScale", "PaperUnits"), ("AnnotationScale", "DrawingUnits"),
    ("ObjectContextCollection", "CurrentContext"), ("ObjectContextCollection", "AddContext"),
    ("PlotSettingsValidator", "SetPlotConfigurationName"), ("PlotSettingsValidator", "SetCanonicalMediaName"),
    ("PlotSettingsValidator", "SetCurrentStyleSheet"), ("PlotSettingsValidator", "SetCustomPrintScale"),
    ("PlotSettingsValidator", "SetStdScaleType"), ("PlotSettingsValidator", "SetPlotWindowArea"),
    ("PlotSettingsValidator", "GetPlotDeviceList"), ("PlotSettingsValidator", "GetCanonicalMediaNameList"),
    ("TableStyle", "PostTableStyleToDatabase"), ("MLeaderStyle", "PostMLeaderStyleToDb"),
    ("Editor", "Command"), ("Editor", "IsQuiescent"), ("Editor", "GetCurrentView"), ("Editor", "SetCurrentView"),
    ("Document", "SendStringToExecute"), ("Document", "LockDocument"), ("Application", "GetSystemVariable"),
    ("Application", "SetSystemVariable"), ("DocumentCollection", "ExecuteInCommandContextAsync"),
]


CLAVE = ["Database", "DBObject", "Entity", "Curve", "BlockReference", "Solid3d", "Document", "DocumentCollection", "Editor", "Application", "Layout", "PlotSettingsValidator", "Autodesk"]


def archivos_cs(base: str) -> Iterable[str]:
    for dp, _, fs in os.walk(base):
        for f in fs:
            if f.endswith(".cs"):
                yield os.path.join(dp, f)


def catalogo(carpeta_version: str) -> dict[str, dict[str, set[str]]]:
    """{clase: {'props': {...}, 'methods': {...}}} de una versión (suma de los tres ensamblados)."""
    cat: dict[str, dict[str, set[str]]] = {}
    for dll in DLLS:
        base = os.path.join(carpeta_version, dll)
        if not os.path.isdir(base):
            continue
        for ruta in archivos_cs(base):
            try:
                t = open(ruta, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            m = RE_CLASE.search(t)
            if not m:
                continue
            ns = RE_NS.search(t)
            clave = f"{ns.group(1) if ns else ''}.{m.group(2)}"
            e = cat.setdefault(clave, {"props": set(), "methods": set()})
            lineas = t.split("\n")
            for i, ln in enumerate(lineas):
                lm = RE_LINEA.match(ln.rstrip("\r"))
                if not lm:
                    continue
                resto = lm.group(1).strip()
                if resto.split(" ")[0] in RESERVADAS or resto.startswith(("class ", "struct ", "enum ", "interface ")):
                    continue
                if "(" in resto and not resto.split("(")[0].endswith("=>"):
                    mm = RE_METODO.match(resto)
                    if mm:
                        e["methods"].add(mm.group(2) + "(" + re.sub(r"\[[^\]]*\]\s*", "", mm.group(3)).strip() + ")")
                else:
                    sig = lineas[i + 1].strip() if i + 1 < len(lineas) else ""
                    if "=>" in resto or sig == "{" or resto.endswith("{ get; }") or "{" in resto:
                        pm = RE_PROP.match(resto)
                        if pm:
                            e["props"].add(pm.group(2))
    return cat


def corto(clave: str) -> str:
    return clave.rsplit(".", 1)[-1]


def existe(cat, clase: str, miembro: str) -> bool:
    for k, v in cat.items():
        if corto(k) != clase:
            continue
        if miembro in v["props"] or any(x.startswith(miembro + "(") for x in v["methods"]):
            return True
    return False


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    raiz = sys.argv[1]
    salida = sys.argv[2] if len(sys.argv) > 2 else os.path.join(raiz, "informe_api.md")
    versiones = sorted(d for d in os.listdir(raiz) if d.isdigit() and os.path.isdir(os.path.join(raiz, d)))
    cats = {v: catalogo(os.path.join(raiz, v)) for v in versiones}
    md = ["# API administrada de AutoCAD por versión (acdbmgd + accoremgd + acmgd)", "",
          "Por análisis de texto del C# descompilado de los ensamblados de referencia. Dice QUÉ existe, no cómo se comporta.", "",
          "| Versión | Clases | Propiedades | Métodos |", "|---|---|---|---|"]
    for v in versiones:
        c = cats[v]
        md.append(f"| {v} | {len(c)} | {sum(len(x['props']) for x in c.values())} | {sum(len(x['methods']) for x in c.values())} |")
    md += ["", "## Cambios entre versiones consecutivas", "", "| De → a | Clases nuevas | Clases quitadas | Propiedades nuevas | Propiedades quitadas | Métodos nuevos | Métodos quitados |", "|---|---|---|---|---|---|---|"]
    detalle: list[str] = []
    for a, b in zip(versiones, versiones[1:]):
        ca, cb = cats[a], cats[b]
        nuevas = sorted(set(cb) - set(ca))
        quitadas = sorted(set(ca) - set(cb))
        pn = pq = mn = mq = 0
        for k in set(ca) & set(cb):
            pn += len(cb[k]["props"] - ca[k]["props"])
            pq += len(ca[k]["props"] - cb[k]["props"])
            mn += len(cb[k]["methods"] - ca[k]["methods"])
            mq += len(ca[k]["methods"] - cb[k]["methods"])
        md.append(f"| {a} → {b} | {len(nuevas)} | {len(quitadas)} | {pn} | {pq} | {mn} | {mq} |")
        ruido = re.compile(r"[<$]|__|vc\.|std\.|\?A0x|Impl|_003C")
        limpias = [corto(x) for x in nuevas if not ruido.search(x)]
        if limpias:
            detalle.append(f"- **{a} → {b}, clases nuevas:** " + ", ".join(limpias[:60]) + (" …" if len(limpias) > 60 else ""))
    md += ["", "### Clases nuevas por salto (sin ruido interno)", ""] + detalle
    md += ["", "## Lo que usa este proyecto, por versión", "",
           "`sí` = el miembro existe en esa versión; `NO` = falta (la función que lo usa no anda ahí).", "",
           "| Clase.miembro | " + " | ".join(versiones) + " |", "|---|" + "---|" * len(versiones)]
    faltantes = 0
    for clase, miembro in USADOS:
        fila = []
        for v in versiones:
            ok = existe(cats[v], clase, miembro)
            fila.append("sí" if ok else "**NO**")
            if not ok:
                faltantes += 1
        md.append(f"| {clase}.{miembro} | " + " | ".join(fila) + " |")
    md += ["", "## Miembros que cambian en las clases clave (solo nombres)", "",
           "Un miembro se compara por nombre (sin firma). Desde 2025 los ensamblados de referencia vienen de ModPlus (net8) y el descompilado trae mas miembros que los de AutoCAD.NET: un salto grande 2024 a 2025 o 2026 a 2027 en metodos es en buena parte ESE efecto, no cambios reales.", ""]
    for clase in CLAVE:
        ult = None
        filas = []
        for a, b in zip(versiones, versiones[1:]):
            def nombres(cat):
                r = set()
                for k, v in cat.items():
                    if corto(k) == clase:
                        r |= v["props"] | {x.split("(")[0] for x in v["methods"]}
                return r
            na, nb = nombres(cats[a]), nombres(cats[b])
            if not na and not nb:
                continue
            ag, qu = sorted(nb - na), sorted(na - nb)
            if ag or qu:
                filas.append(f"  - {a} a {b}: " + (f"+{len(ag)} " + ", ".join(ag[:12]) + (" ..." if len(ag) > 12 else "") if ag else "") + ("; " if ag and qu else "") + (f"-{len(qu)} " + ", ".join(qu[:12]) + (" ..." if len(qu) > 12 else "") if qu else ""))
        if filas:
            md += [f"- **{clase}**"] + filas
    md += [""]
    md += ["", f"Faltantes en total: **{faltantes}** de {len(USADOS) * len(versiones)} comprobaciones."]
    open(salida, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("informe:", salida, "| versiones:", versiones, "| faltantes:", faltantes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
