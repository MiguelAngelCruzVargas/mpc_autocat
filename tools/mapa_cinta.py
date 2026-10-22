"""Mapa de la CINTA de AutoCAD: pestaña > panel > comando, leído de su propia definición de interfaz (acad.cuix).

AutoCAD organiza sus herramientas en la cinta (Inicio > Dibujo, Modificar, Anotación, Capas, Bloque...;
Anotar; Parametrizar; Vista; Gestionar; Salida; Insertar; Modelado 3D...). Esa organización es la que
usa la gente para encontrar una herramienta, y es la que este MCP debería seguir. Este script la extrae
SIN adivinar: abre el `acad.cuix` de la instalación, une cada botón de la cinta con su macro (el comando que
ejecuta) y escribe un JSON y un Markdown.

Uso:
  python tools/mapa_cinta.py [ruta_acad.cuix] [salida_base]
Sin argumentos usa la 2027 (es-es) y escribe `Desktop/Autodesk_descompilado/notas/cinta_autocad.{json,md}`.
"""
from __future__ import annotations

import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from typing import Any

CUIX_DEFECTO = r"C:\Program Files\Autodesk\AutoCAD 2027\UserDataCache\es-es\Support\acad.CUIX"
SALIDA_DEFECTO = os.path.join(os.path.expanduser("~"), "Desktop", "Autodesk_descompilado", "notas", "cinta_autocad")


def _limpio(t: str | None) -> str:
    return re.sub(r"\s+", " ", (t or "").replace("&#xD;", " ")).strip()


def comando_de_macro(macro: str) -> str:
    """El nombre del comando que dispara una macro de menú: '^C^C_line' -> 'LINE'; '^C^C_-layer' -> '-LAYER'."""
    m = macro or ""
    m = re.sub(r"\^[A-Za-z]", " ", m)              # ^C ^B ...
    m = m.replace("\\", " ")
    for tok in m.split():
        tok = tok.lstrip("'_.*")
        if re.match(r"^-?[A-Za-z0-9_]+$", tok):
            return tok.upper()
    return ""


def cargar(cuix: str) -> dict[str, Any]:
    z = zipfile.ZipFile(cuix)
    macros: dict[str, dict] = {}
    raiz_menu = ET.fromstring(z.read("MenuGroup.cui"))
    for mm in raiz_menu.iter("MenuMacro"):
        uid = mm.get("UID")
        nombre = _limpio((mm.find("Name").text if mm.find("Name") is not None else "")) or _limpio(mm.get("Name"))
        cmd_el = mm.find("MacroID") if mm.find("MacroID") is not None else None
        macro = ""
        for hijo in mm.iter():
            if hijo.tag in ("Command", "MacroText", "macro") and hijo.text:
                macro = hijo.text
                break
        if not macro:
            for hijo in mm.iter("Command"):
                macro = hijo.text or ""
        macros[uid] = {"nombre": nombre, "macro": macro, "comando": comando_de_macro(macro)}
    cinta = ET.fromstring(z.read("RibbonRoot.cui"))
    paneles: dict[str, dict] = {}
    for p in cinta.iter("RibbonPanelSource"):
        botones = []
        for b in p.iter("RibbonCommandButton"):
            mid = b.get("MenuMacroID")
            info = macros.get(mid, {})
            botones.append({"texto": _limpio(b.get("Text")) or info.get("nombre", ""), "macro_id": mid,
                            "comando": info.get("comando", ""), "macro": info.get("macro", "")})
        nombre_el = p.find("Name")
        paneles[p.get("UID")] = {"texto": _limpio(p.get("Text")) or _limpio(nombre_el.text if nombre_el is not None else ""),
                                 "botones": botones}
    pestanas = []
    for t in cinta.iter("RibbonTabSource"):
        refs = [r.get("PanelId") for r in t.iter("RibbonPanelSourceReference")]
        pestanas.append({"uid": t.get("UID"), "texto": _limpio(t.get("Text")),
                         "paneles": [{"uid": r, **paneles[r]} for r in refs if r in paneles]})
    return {"cuix": cuix, "pestanas": pestanas, "macros": len(macros)}


def a_markdown(d: dict) -> str:
    out = ["# La cinta de AutoCAD: pestaña > panel > comando", "",
           f"Leída de `{os.path.basename(d['cuix'])}` ({d['macros']} macros). Cada comando es el que dispara el botón.", ""]
    for t in d["pestanas"]:
        total = sum(len(p["botones"]) for p in t["paneles"])
        if not total:
            continue
        out += [f"## {t['texto']}  ({total} botones)", ""]
        for p in t["paneles"]:
            cmds = []
            for b in p["botones"]:
                c = b["comando"] or "?"
                if c not in cmds:
                    cmds.append(c)
            out.append(f"- **{p['texto']}**: " + ", ".join(cmds))
        out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    cuix = argv[0] if argv else CUIX_DEFECTO
    base = argv[1] if len(argv) > 1 else SALIDA_DEFECTO
    d = cargar(cuix)
    json.dump(d, open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(base + ".md", "w", encoding="utf-8").write(a_markdown(d))
    n_p = sum(len(t["paneles"]) for t in d["pestanas"])
    n_b = sum(len(p["botones"]) for t in d["pestanas"] for p in t["paneles"])
    print(f"{len(d['pestanas'])} pestañas, {n_p} paneles (con repetición), {n_b} botones -> {base}.json / .md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
