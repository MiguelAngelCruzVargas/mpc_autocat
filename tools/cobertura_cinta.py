"""Cobertura de este MCP contra la CINTA de AutoCAD: qué comando de cada panel tiene tool, cuál se alcanza por las
herramientas genéricas (reflexión) y cuál falta.

Cruza dos cosas leídas, no recordadas:
  - la cinta real de AutoCAD (`tools/mapa_cinta.py` -> `cinta_autocad.json`: pestaña > panel > comando);
  - las tools del MCP y los comandos que declaran cubrir (`mcp_server/categorias.py`).

Cada comando queda en UNO de estos estados:
  CUBIERTO       hay una tool propia (la que declara el comando en categorias.py);
  REFLEXION      no hay tool propia pero se logra HOY con create_object / call_object_method /
                 set_object_properties / set_system_variable (las genéricas);
  SOLO_INTERFAZ  no tiene sentido sin una persona frente a la pantalla (portapapeles, órbita, paletas...);
  FUERA_DE_ALCANCE  geolocalización, nubes de puntos, materiales y luces de render, OLE: no es dibujo de planos;
  PENDIENTE      candidato a implementar (con la API administrada o con native_op);
  SIN_CLASIFICAR no se ha mirado todavía.

Uso:  python tools/cobertura_cinta.py [cinta_autocad.json] [salida.md]
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import OrderedDict

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(AQUI), "mcp_server"))
import categorias as cat  # noqa: E402

CINTA_DEFECTO = os.path.join(os.path.expanduser("~"), "Desktop", "Autodesk_descompilado", "notas", "cinta_autocad.json")

# Equivalencias: comando de AutoCAD -> tool que lo cubre aunque no lo declare (variantes del mismo trabajo).
EQUIV = {
    "DIM": "create_dimension", "QDIM": "create_dimension_chain", "DIMEDIT": "set_dim_style", "DIMOVERRIDE": "set_dim_style",
    "DIMSPACE": "create_dimension_chain", "DIMTEDIT": "set_object_properties", "TEXTEDIT": "find_replace_text",
    "-DIMSTYLE": "set_dim_style", "MLEADERSTYLE": "create_database_object", "TABLESTYLE": "create_database_object",
    "AIOBJECTSCALEADD": "add_annotation_scale", "AIOBJECTSCALEREMOVE": "remove_annotation_scale", "SCALELISTEDIT": "add_annotation_scale",
    "OBJECTSCALE": "set_current_annotation_scale", "LAYON": "set_layer", "LAYTHW": "set_layer", "LAYFRZ": "set_layer",
    "LAYULK": "set_layer", "LAYMCH": "match_properties", "COPYTOLAYER": "set_object_properties", "LAYERP": "undo",
    "BATTMAN": "set_block_attributes", "BASE": "set_system_variable", "BEDIT": "define_block", "MEASUREGEOM": "calculate_area",
    "QSELECT": "query_entities", "AI_SELALL": "select_entities", "ID": "get_object_properties", "LIST": "get_object_properties",
    "STYLE": "set_text_style", "TABLE": "create_table", "WIPEOUT": "create_object", "DONUT": "create_object",
    "HELIX": "create_object", "3DPOLY": "create_object", "REVCLOUD": "create_object", "PTYPE": "set_system_variable",
    "BOX": "create_object", "CYLINDER": "create_object", "CONE": "create_object", "SPHERE": "create_object",
    "PYRAMID": "create_object", "WEDGE": "create_object", "TORUS": "create_object", "POLYSOLID": "create_object",
    "SLICE": "call_object_method", "INTERFERE": "call_object_method", "THICKEN": "call_object_method",
    "IMPRINT": "call_object_method", "REVERSE": "call_object_method", "LENGTHEN": "call_object_method",
    "PEDIT": "set_object_properties", "SPLINEDIT": "set_object_properties", "HATCHEDIT": "set_object_properties",
    "ALIGN": "call_object_method", "3DMOVE": "call_object_method", "3DROTATE": "call_object_method", "3DSCALE": "call_object_method",
    "MIRROR3D": "call_object_method", "3DALIGN": "call_object_method", "CHSPACE": "set_object_properties",
    "SETBYLAYER": "set_object_properties", "AI_DRAWORDER": "call_object_method", "TEXTTOFRONT": "call_object_method",
    "HATCHTOBACK": "call_object_method", "MESHSMOOTH": "call_object_method", "MESHSMOOTHMORE": "call_object_method",
    "MESHSMOOTHLESS": "call_object_method", "MESHREFINE": "call_object_method", "CONVTOSOLID": "call_object_method",
    "CONVTOSURFACE": "call_object_method", "SOLIDEDIT": "call_object_method", "PRESSPULL": "call_object_method",
    "UCS": "create_database_object", "UCSICON": "set_system_variable", "XEDGES": "call_object_method",
    "ATTDEF": "create_object", "BLOCK": "define_block", "NCOPY": "copy_entity", "BREPLACE": "insert_block",
    "BSEARCH": "list_children", "SECTIONPLANE": "create_object", "LAYWALK": "list_layers", "LAYMCUR": "set_current",
    "DATAEXTRACTION": "calculate_quantities", "TEXTALIGN": "set_object_properties", "JUSTIFYTEXT": "set_object_properties",
    "SCALETEXT": "scale_entity", "DIMBREAK": "call_object_method", "DIMJOGLINE": "call_object_method",
    "DIMREASSOCIATE": "call_object_method", "MLEADERALIGN": "call_object_method", "MLEADERCOLLECT": "call_object_method",
    "CENTERMARK": "create_object", "CENTERLINE": "create_object", "DIMINSPECT": "create_object", "TOLERANCE": "create_object",
    "DIMORDINATE": "create_dimension", "DIMJOGGED": "create_dimension", "ANNORESET": "call_object_method",
    "ARRAYEDIT": "call_object_method", "BREAKATPOINT": "break_curve",
}
EQUIV_REFLEXION = {"create_object", "call_object_method", "set_object_properties", "set_system_variable", "list_children",
                   "get_object_properties"}

# Sin sentido sin una persona: portapapeles, órbita, selección interactiva, paletas...
SOLO_INTERFAZ_PREF = ("PASTE", "CUT", "COPYCLIP", "COPYBASE", "-VPORTS", "VPORTS", "AI_EMPTYPRINC", "3DORBIT", "NAVSWHEEL", "SPELL",
                      "ADCENTER", "TOOLPALETTES", "PROPERTIES", "DESIGNCENTER", "QUICKCALC", "PUBLISH", "ETRANSMIT", "SHEETSET",
                      "CLASSICGROUP", "SELECTSIMILAR", "AI_", "RECOVER", "AUDIT", "OPTIONS", "CUSTOMIZE", "CUI", "TOOLBAR",
                      "APPLOAD", "RIBBON", "MENU", "QNEW", "NEW", "OPEN", "CLOSE", "OSNAP", "DSETTINGS", "UNDO", "REDO", "DIST",
                      "LIVESECTION", "CAMERA", "WALK", "FLY", "STEERING", "SHOWMOTION", "VIEWPLAY", "NAVV", "DVIEW", "RENDER",
                      "MATBROWSER", "LIGHT", "SUNPROPERTIES", "GEOGRAPHICLOCATION", "MAPCONNECT", "POINTCLOUD", "RCS", "REALITY")

# Candidatos reales a implementar (por la API administrada o native_op).
PENDIENTE = {
    "STRETCH", "CHAMFER", "BLEND", "LENGTHEN", "ALIGN", "FILLETEDGE", "CHAMFEREDGE", "SHELL", "FLATSHOT", "SOLDRAW", "SOLVIEW",
    "SOLPROF", "SECTIONPLANETOBLOCK", "SECTIONPLANEJOG", "EATTEDIT", "-ATTEDIT", "BCOUNT", "DATALINK", "DATALINKUPDATE",
    "FIELD", "TEXTEDIT", "PURGE", "LAYMRG", "LAYDEL", "DIMSTYLE", "MLEADEREDIT", "AIMLEADEREDITADD", "AIMLEADEREDITREMOVE",
    "TABLEEXPORT", "TABLEDIT", "GROUPEDIT", "MVIEW", "MSPACE", "PSPACE", "PAGESETUP", "PLOT", "EXPORTPDF", "SAVEAS", "WBLOCK",
}


# Familias que se clasifican por patrón: (regex del comando, estado, nota).
FAMILIAS = [
    (r"^(ARRAY|-ARRAYCLOSE|3DARRAY)$", "CUBIERTO", "array_entity"),
    (r"^(CHECKSTANDARDS|STANDARDS)$", "CUBIERTO", "check_office_standard"),
    (r"^(PAGESETUP|PLOTTERMANAGER|EXPORTSETTINGS)$", "CUBIERTO", "configure_layout"),
    (r"^(GC[A-Z]+|DC[A-Z]+|AUTOCONSTRAIN|DELCONSTRAINT|CONSTRAINTBAR|BPARAMETER|BCPARAMETER|BCONSTRUCTION|BTABLE)$", "PENDIENTE",
     "restricciones: faltan SIMETRÍA/SUAVE/PUNTO-CURVA (GCSYMMETRIC, GCSMOOTH), DCCONVERT, AUTOCONSTRAIN y las de bloque (BPARAMETER, BTABLE)"),
    (r"^(MESH[A-Z]*|SURF[A-Z]+|EDGESURF|CONVTONURBS|CV[A-Z]+|OFFSETEDGE|PROJECTGEOMETRY|EDGE)$", "PENDIENTE",
     "superficies y mallas que piden elegir caras, aristas o puntos de control (FullSubentityPath): MESHEXTRUDE/SPLIT/MERGE/CREASE/COLLAPSE/CAP/SPIN, SURFTRIM/BLEND/FILLET/EXTEND..."),
    (r"^(CLIP|XCLIP|IMAGECLIP|PDFCLIP|DGNCLIP|DWFCLIP|ATTACH|PDFIMPORT|ADJUST)$", "PENDIENTE", "recortes y calcos subyacentes (underlays)"),
    (r"^(EDITTABLECELL|UPDATEFIELD|ATTSYNC|BDETECT|LAYTRANS)$", "PENDIENTE", "datos de tablas, campos, atributos y traductor de capas"),
    (r"^(GEO[A-Z]+|PCEXTRACT[A-Z]+|MATERIAL[A-Z]+|POINTLIGHT|SPOTLIGHT|WEBLIGHT|PDFSHXTEXT[A-Z]*|INSERTOBJ|ANALYSIS[A-Z]+|HYPERLINK)$",
     "FUERA_DE_ALCANCE", "geolocalización, nubes de puntos, materiales/luces de render, OLE"),
    (r"^(3DCORBIT|3DFORBIT|3DFLY|3DWALK|3DSWIVEL|3DEDITBAR|ANIPATH|PAN|PREVIEW|HIDE|VIEW|VIEWBACK|VIEWFORWARD|VIEWPLOTDETAILS|TEXTSCR|SCRIPT|SHARE|"
     r"PERFANALYZER|MARKUPIMPORT|CHECKOUT|COMPARE|SHOWRENDERGALLERY|REFCLOSE|REFSET|BCLOSE|BSAVE|BSAVEAS|BTESTBLOCK|BACTIONBAR|BACTIONTOOL|"
     r"ULAYERS|SKETCH|VBA[A-Z]+|VLIDE|3DDWF)$", "SOLO_INTERFAZ", ""),
    (r"^[0-9T]$", "IGNORAR", ""),
]


def normalizar(c: str) -> str:
    return c.lstrip("-").upper()


def clasificar(cmd: str, mapa: dict[str, list[str]]) -> tuple[str, str]:
    c = cmd.upper()
    n = normalizar(c)
    for k in (c, n, "-" + n):
        if k in mapa:
            return "CUBIERTO", ", ".join(sorted(set(mapa[k])))
    if c in EQUIV or n in EQUIV:
        t = EQUIV.get(c) or EQUIV.get(n)
        return ("REFLEXION", t) if t in EQUIV_REFLEXION else ("CUBIERTO", t)
    for patron, estado, nota in FAMILIAS:
        if re.match(patron, c):
            return estado, nota
    if any(n.startswith(p.lstrip("-")) for p in SOLO_INTERFAZ_PREF if p):
        return "SOLO_INTERFAZ", ""
    if c in PENDIENTE or n in PENDIENTE:
        return "PENDIENTE", ""
    return "SIN_CLASIFICAR", ""


def main(argv: list[str]) -> int:
    ruta = argv[0] if argv else CINTA_DEFECTO
    salida = argv[1] if len(argv) > 1 else os.path.join(os.path.dirname(AQUI), "COBERTURA_CINTA.md")
    d = json.load(open(ruta, encoding="utf-8"))
    mapa = cat.comando_a_tools()
    # una vez por (pestaña, panel, comando); las pestañas repetidas (Inicio 2D / 3D) se unen por nombre
    arbol: "OrderedDict[str, OrderedDict[str, OrderedDict[str, tuple[str, str]]]]" = OrderedDict()
    vistos_global: dict[str, tuple[str, str]] = {}
    for t in d["pestanas"]:
        for p in t["paneles"]:
            for b in p["botones"]:
                cmd = b["comando"]
                if not cmd or not re.match(r"^-?[A-Z0-9_]+$", cmd):
                    continue
                est = clasificar(cmd, mapa)
                if est[0] == "IGNORAR":
                    continue
                vistos_global[cmd] = est
                arbol.setdefault(t["texto"], OrderedDict()).setdefault(p["texto"], OrderedDict())[cmd] = est
    cont: dict[str, int] = {}
    for est, _ in vistos_global.values():
        cont[est] = cont.get(est, 0) + 1
    total = len(vistos_global)
    util = total - cont.get("SOLO_INTERFAZ", 0) - cont.get("FUERA_DE_ALCANCE", 0)
    cubiertos = cont.get("CUBIERTO", 0) + cont.get("REFLEXION", 0)
    out = ["# Cobertura de este MCP contra la cinta de AutoCAD", "",
           "Generado por `python tools/cobertura_cinta.py` (cinta real de AutoCAD 2027 × `mcp_server/categorias.py`). No se edita a mano: se corrige `categorias.py` o este script.", "",
           f"**{total} comandos distintos en la cinta.** {cont.get('CUBIERTO', 0)} con tool propia, {cont.get('REFLEXION', 0)} alcanzables hoy con las "
           f"tools genéricas (reflexión), {cont.get('SOLO_INTERFAZ', 0)} que solo tienen sentido con una persona frente a la pantalla, {cont.get('FUERA_DE_ALCANCE', 0)} fuera de alcance (render, geolocalización, nubes de puntos), "
           f"{cont.get('PENDIENTE', 0)} candidatos a implementar y {cont.get('SIN_CLASIFICAR', 0)} sin clasificar. "
           f"De los {util} que tienen sentido automatizar, {cubiertos} están cubiertos ({100 * cubiertos // max(util, 1)} %).", "",
           "Leyenda: ✔ tool propia · ◐ por reflexión (`create_object`, `call_object_method`, `set_object_properties`) · ○ solo interfaz · ▫ fuera de alcance · ✖ pendiente · ? sin clasificar", ""]
    simb = {"CUBIERTO": "✔", "REFLEXION": "◐", "SOLO_INTERFAZ": "○", "FUERA_DE_ALCANCE": "▫", "PENDIENTE": "✖", "SIN_CLASIFICAR": "?"}
    notas: dict[str, str] = {}
    for tab, paneles in arbol.items():
        out += [f"## {tab}", ""]
        for pan, cmds in paneles.items():
            fila = []
            for cmd, (est, tool) in cmds.items():
                fila.append(f"{simb[est]} {cmd}" + (f" → `{tool}`" if tool and est in ("CUBIERTO", "REFLEXION") else ""))
            notas.update({cmd: nota for cmd, (est, nota) in cmds.items() if est == "PENDIENTE" and nota})
            out.append(f"- **{pan}**: " + " · ".join(fila))
        out.append("")
    pend = sorted(c for c, (e, _) in vistos_global.items() if e in ("PENDIENTE", "SIN_CLASIFICAR"))
    out += ["## Para hacer (pendientes y sin clasificar)", ""]
    por_nota: dict[str, list[str]] = {}
    for c in pend:
        por_nota.setdefault(notas.get(c, "pendientes sin nota (o sin clasificar)"), []).append(c)
    for nota, cs in sorted(por_nota.items()):
        out.append(f"- **{nota}**: " + ", ".join(cs))
    out.append("")
    open(salida, "w", encoding="utf-8").write("\n".join(out))
    print(f"{total} comandos: " + ", ".join(f"{k}={v}" for k, v in sorted(cont.items())) + f" -> {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
