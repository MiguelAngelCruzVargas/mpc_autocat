"""Motor de acceso total: `run_code`, `describe_api` y `api_guide`.

Por qué existe. Cada capacidad nueva de AutoCAD costaba una cadena entera
—comando C#, recompilar, reiniciar AutoCAD, tool Python, párrafo en
CLAUDE.md— y la IA solo podía hacer lo que alguien le había fabricado antes
(ningún comando 3D, por ejemplo). `run_code` es UNA puerta genérica a toda
la API .NET: el plugin compila el cuerpo de un método C# y lo corre dentro
de una transacción. Ver docs/superpowers/specs/2026-10-09-motor-api-autocad-design.md.

Lo que este módulo agrega del lado Python, y que el plugin no puede hacer:

- **La contraseña.** run_code nace apagado; el usuario lo prende con
  `python tools/run_code_acceso.py activar`, que guarda la contraseña
  cifrada con DPAPI. Acá solo se LEE y se presenta. Sin clave no se llama al
  plugin: la IA no tiene forma de activarlo ni de saber la contraseña.
- **La red de seguridad contra la caída.** Una excepción .NET la ataja el
  plugin (aborta la transacción). Un AccessViolation no lo ataja nadie: se
  lleva AutoCAD entero con todo lo no guardado — ya pasó con un plano
  completo. Por eso, antes de ejecutar, si hay cambios sin guardar y se sabe
  dónde, se guarda; si el dibujo nunca se guardó, no se ejecuta salvo force.
- **La integración con la sesión.** Lo creado se registra en space (para
  que place_labels y check_annotations lo vean) y la ejecución cuenta como
  operación de dibujo en session — pero solo si de verdad pudo cambiar algo.
- **Errores legibles.** Línea:columna y mensaje, el símbolo bloqueado y por
  qué: es lo que le permite a la IA corregirse sola en el intento siguiente.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any, Optional

import autocad_client as acad
import session
import space

AQUI = os.path.dirname(os.path.abspath(__file__))
GUIAS_DIR = os.path.join(AQUI, "guias")

# El dueño del formato de la clave es el CLI del usuario: un solo lugar sabe
# dónde está y cómo se descifra, y este módulo nunca la escribe.
_TOOLS = os.path.join(os.path.dirname(AQUI), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
import run_code_acceso as acceso  # noqa: E402

APAGADO = ("run_code está apagado; el usuario lo activa con "
           "python tools/run_code_acceso.py activar. La IA no puede "
           "activarlo ni debe pedir la contraseña: si hace falta, decile al "
           "usuario que lo active él, o resolvé el pedido con las tools de "
           "oficio.")

# Más miembros que esto ya no es una consulta, es un volcado: se recorta y
# se avisa para que se repita con 'filter'.
MAX_MIEMBROS = 150

# Lo que el plugin dice cuando rechaza por acceso. No se conoce el texto
# exacto de antemano (lo escribe el lado C#), así que se reconoce por
# palabras clave.
_MARCAS_ACCESO = ("contraseña", "password", "deshabilitado", "desactivado",
                  "apagado", "no está habilitado", "no esta habilitado")
_MARCAS_TIMEOUT = ("no procesó el comando a tiempo", "timed out", "timeout",
                   "se cortó la conexión")


# ------------------------------------------------------------- run_code

def run_code(code: str, description: str = "", compile_only: bool = False,
             force: bool = False) -> dict[str, Any]:
    """Ejecuta C# contra la API de AutoCAD. Ver server.run_code."""
    return _ejecutar(code, description, compile_only=compile_only,
                     force=force, consulta=False)


def _ejecutar(code: str, description: str, compile_only: bool, force: bool,
              consulta: bool) -> dict[str, Any]:
    """consulta=True es para código propio de solo lectura (describe_api):
    no guarda antes ni cuenta como dibujo, porque no cambia nada."""
    if not code or not code.strip():
        raise ValueError("'code' está vacío: es el CUERPO de object Run().")

    clave = acceso.leer_clave()
    if clave is None:
        return {"executed": False, "disabled": True, "message": APAGADO}

    avisos: list[str] = []
    if not compile_only and not consulta:
        seguir, notas, rechazo = _red_de_seguridad(force)
        avisos.extend(notas)
        if not seguir:
            return {"executed": False, "message": rechazo,
                    "warnings": avisos}

    try:
        crudo = acad.call("run_code", {
            "code": code, "password": clave, "description": description,
            "compile_only": bool(compile_only)})
    except acad.AutoCadConnectionError:
        raise
    except acad.AutoCadError as exc:
        texto = str(exc)
        bajo = texto.lower()
        if any(m in bajo for m in _MARCAS_ACCESO):
            return {"executed": False, "disabled": True,
                    "message": f"El plugin rechazó run_code: {texto}. "
                               + APAGADO}
        if any(m in bajo for m in _MARCAS_TIMEOUT):
            # Un código que no terminó no se puede cortar desde afuera: corre
            # en el hilo de AutoCAD. Repetirlo encolaría otro igual detrás.
            raise acad.AutoCadError(
                texto + " — run_code no terminó a tiempo. Si el código tiene "
                "un bucle largo o infinito, AutoCAD queda ocupado hasta que "
                "termine: NO lo repitas; esperá y verificá con ping.") from exc
        raise

    r: dict[str, Any] = dict(crudo) if isinstance(crudo, dict) else {
        "result": crudo}
    r["executed"] = bool(r.get("compiled")) and not compile_only \
        and not r.get("blocked")
    fallo = _mensaje_de_fallo(r)
    if fallo:
        r["message"] = fallo

    exito = (r["executed"] and not r.get("exception")
             and not r.get("aborted"))
    if exito:
        # Lo abortado no dejó nada: registrar su caja haría que place_labels
        # esquive un fantasma.
        for ent in r.get("created") or []:
            caja = ent.get("bbox") if isinstance(ent, dict) else None
            if isinstance(caja, (list, tuple)) and len(caja) == 6:
                space.track(caja[0], caja[1], caja[3], caja[4], "run_code")
        if not consulta:
            r = session.note_mutation(r)

    if avisos:
        previos = r.get("warnings")
        r["warnings"] = (list(previos) if isinstance(previos, list)
                         else ([previos] if previos else [])) + avisos
    return r


def _documento_activo() -> Optional[dict[str, Any]]:
    """El documento activo según el plugin, o None si no se pudo saber."""
    try:
        docs = acad.call("list_documents", {}).get("documents") or []
    except acad.AutoCadError:
        return None
    for d in docs:
        if isinstance(d, dict) and d.get("isActive"):
            return d
    return None


def _es_archivo_real(ruta: Any) -> bool:
    """Un Drawing1 sin guardar tiene de nombre 'Drawing1.dwg', sin carpeta:
    eso no es un lugar donde guardar."""
    return (isinstance(ruta, str) and os.path.isabs(ruta)
            and ruta.lower().endswith(".dwg") and os.path.isfile(ruta))


def _red_de_seguridad(force: bool) -> tuple[bool, list[str], str]:
    """Guarda antes de ejecutar si hace falta. Devuelve (seguir, notas,
    motivo_del_rechazo)."""
    notas: list[str] = []
    activo = _documento_activo()
    recordado = session.last_save_path()
    propio = activo.get("fullPath") if activo else None
    # Mismo orden que save_drawing() sin path: el path de la sesión manda (el
    # plugin guarda con SaveAs y el nombre del documento no cambia), y si no
    # hay, el archivo propio del documento.
    destino = recordado or (propio if _es_archivo_real(propio) else None)

    # Si no se pudo preguntar, se asume lo peor: perder trabajo cuesta más
    # que un guardado de más.
    sucio = (session.ops_since_save() > 0 or activo is None
             or activo.get("hasUnsavedChanges", True) is not False)
    if not sucio:
        return True, notas, ""

    if destino is None:
        if force:
            notas.append(
                "force=True: se ejecutó sobre un dibujo con cambios SIN "
                "GUARDAR y sin archivo. Si AutoCAD se cae, se pierde todo. "
                "Guardalo con save_drawing(path=...) cuanto antes.")
            return True, notas, ""
        return False, notas, (
            "No se ejecutó: el dibujo tiene cambios sin guardar y nunca se "
            "guardó (es un Drawing sin nombre), así que no hay dónde "
            "guardarlo antes. Una caída de AutoCAD durante run_code no se "
            "puede atajar y se llevaría todo. Llamá save_drawing(path=...) y "
            "repetí, o pasá force=True si asumís el riesgo.")

    try:
        acad.call("save_drawing", {
            "path": recordado,
            "overwrite": recordado is not None})
    except acad.AutoCadConnectionError:
        raise
    except acad.AutoCadError as exc:
        if force:
            notas.append(f"force=True: no se pudo guardar antes ({exc}); se "
                         "ejecutó igual.")
            return True, notas, ""
        return False, notas, (
            f"No se ejecutó: falló el guardado previo ({exc}). Sin ese "
            "guardado una caída de AutoCAD se lleva lo no guardado. Revisá "
            "el path con save_drawing, o pasá force=True.")
    session.note_saved(destino)
    notas.append(f"Antes de ejecutar se guardó el dibujo en '{destino}' "
                 "(red de seguridad: una caída de AutoCAD no se ataja).")
    return True, notas, ""


def _mensaje_de_fallo(r: dict[str, Any]) -> str:
    """Errores de compilación, bloqueos y excepción, en texto que se lee."""
    partes: list[str] = []
    errores = [e for e in (r.get("errors") or []) if isinstance(e, dict)]
    graves = [e for e in errores
              if str(e.get("severity", "error")).lower() == "error"]
    if r.get("compiled") is False or graves:
        lista = graves or errores
        partes.append("No compiló:" if lista else "No compiló.")
        for e in lista:
            partes.append(f"  línea {e.get('line', '?')}:"
                          f"{e.get('column', '?')} — {e.get('message', '')}")
    bloqueos = [b for b in (r.get("blocked") or []) if isinstance(b, dict)]
    if bloqueos:
        partes.append("Bloqueado por el filtro del plugin (run_code solo "
                      "toca AutoCAD: nada de archivos, red, procesos, "
                      "registro ni comandos de línea):")
        for b in bloqueos:
            partes.append(f"  línea {b.get('line', '?')}:"
                          f"{b.get('column', '?')} — {b.get('symbol', '?')}: "
                          f"{b.get('reason', '')}")
    exc = r.get("exception")
    if isinstance(exc, dict) and exc:
        donde = (f" en la línea {exc['line']}"
                 if exc.get("line") is not None else "")
        partes.append(
            f"Excepción {exc.get('type', '?')}{donde}: "
            f"{exc.get('message', '')}. La transacción se abortó: el dibujo "
            "quedó exactamente como estaba.")
    elif r.get("aborted") and not partes:
        partes.append("La ejecución se abortó: el dibujo quedó como estaba.")
    if bloqueos or exc:
        partes.append("Si no sabés la firma exacta: describe_api(tipo, "
                      "filtro). Errores típicos: api_guide('errores-comunes').")
    return "\n".join(partes)


# ------------------------------------------------------------- describe_api

_RE_TIPO = re.compile(r"^[A-Za-z_][A-Za-z0-9_.+`]*$")
_RE_FILTRO = re.compile(r"^[A-Za-z0-9_]*$")

# C# 5 a propósito (sin $"", ?., funciones locales ni LINQ) y con nombres
# completos: no se sabe qué 'using' trae la plantilla, y si el plugin cae al
# compilador CodeDom de net48 solo entiende C# 5.
#
# Type.GetType(string) y Assembly.Load están BLOQUEADOS por el filtro: el
# tipo se busca recorriendo los assemblies que AutoCAD ya tiene cargados.
_PLANTILLA_DESCRIBE = r"""
string buscado = "__TIPO__";
string filtro = "__FILTRO__";
bool completo = buscado.IndexOf('.') >= 0;
var sb = new System.Text.StringBuilder();
var vistos = new System.Collections.Generic.HashSet<string>();
var candidatos = new System.Collections.Generic.List<System.Type>();
foreach (System.Reflection.Assembly asm in System.AppDomain.CurrentDomain.GetAssemblies())
{
    System.Type[] tipos;
    try { tipos = asm.GetTypes(); }
    catch (System.Reflection.ReflectionTypeLoadException ex) { tipos = ex.Types; }
    catch (System.Exception) { continue; }
    foreach (System.Type t in tipos)
    {
        if (t == null || (!t.IsPublic && !t.IsNestedPublic)) continue;
        string n = completo ? t.FullName : t.Name;
        if (n == null || !string.Equals(n, buscado, System.StringComparison.OrdinalIgnoreCase)) continue;
        if (vistos.Add(t.AssemblyQualifiedName ?? t.FullName)) candidatos.Add(t);
    }
}
System.Type elegido = null;
if (candidatos.Count == 1) elegido = candidatos[0];
else if (candidatos.Count > 1)
{
    int deAcad = 0;
    foreach (System.Type c in candidatos)
        if (c.Namespace != null && c.Namespace.StartsWith("Autodesk.AutoCAD")) { elegido = c; deAcad++; }
    if (deAcad != 1) elegido = null;
}
foreach (System.Type c in candidatos)
    sb.Append("T|" + c.FullName + "|" + c.Assembly.FullName + "\n");
if (elegido == null) return sb.ToString();

System.Func<System.Type, string> nom = null;
nom = t =>
{
    if (t == null) return "void";
    if (t.IsByRef) return "ref " + nom(t.GetElementType());
    if (t.IsArray) return nom(t.GetElementType()) + "[" + new string(',', t.GetArrayRank() - 1) + "]";
    if (t.IsGenericType)
    {
        string b = t.Name;
        int i = b.IndexOf('`');
        if (i > 0) b = b.Substring(0, i);
        var genArgs = new System.Collections.Generic.List<string>();
        foreach (System.Type a in t.GetGenericArguments()) genArgs.Add(nom(a));
        return b + "<" + string.Join(", ", genArgs.ToArray()) + ">";
    }
    switch (t.FullName)
    {
        case "System.Void": return "void";
        case "System.Double": return "double";
        case "System.Int32": return "int";
        case "System.Int64": return "long";
        case "System.Boolean": return "bool";
        case "System.String": return "string";
        case "System.Object": return "object";
    }
    return t.Name;
};
System.Func<System.Reflection.ParameterInfo[], string> pars = ps =>
{
    var l = new System.Collections.Generic.List<string>();
    foreach (System.Reflection.ParameterInfo p in ps)
    {
        System.Type pt = p.ParameterType;
        string pre = "";
        if (p.IsOut && pt.IsByRef) { pre = "out "; pt = pt.GetElementType(); }
        string s = pre + nom(pt) + " " + p.Name;
        if (p.IsOptional) s = "[" + s + "]";
        l.Add(s);
    }
    return string.Join(", ", l.ToArray());
};
System.Func<string, bool> pasa = n => filtro.Length == 0 || n.ToLowerInvariant().Contains(filtro);

string clase = elegido.IsEnum ? "enum" : elegido.IsInterface ? "interface"
    : elegido.IsValueType ? "struct" : elegido.IsAbstract ? "abstract class" : "class";
sb.Append("S|" + elegido.FullName + "|" + (elegido.BaseType == null ? "" : elegido.BaseType.FullName) + "|" + clase + "\n");

var flags = System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance
    | System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.FlattenHierarchy;

if (filtro.Length == 0 || pasa(elegido.Name))
    foreach (System.Reflection.ConstructorInfo c in elegido.GetConstructors())
        sb.Append("C|" + elegido.Name + "|" + elegido.Name + "(" + pars(c.GetParameters()) + ")\n");

if (elegido.IsEnum)
{
    foreach (string n in System.Enum.GetNames(elegido))
        if (pasa(n)) sb.Append("E|" + elegido.Name + "|" + n + "\n");
}
else
{
    foreach (System.Reflection.FieldInfo f in elegido.GetFields(flags))
        if (pasa(f.Name))
            sb.Append("F|" + f.DeclaringType.Name + "|" + (f.IsStatic ? "static " : "") + nom(f.FieldType) + " " + f.Name + "\n");
}

foreach (System.Reflection.PropertyInfo p in elegido.GetProperties(flags))
{
    if (!pasa(p.Name)) continue;
    System.Reflection.MethodInfo g = p.GetGetMethod();
    System.Reflection.MethodInfo s = p.GetSetMethod();
    bool st = (g != null && g.IsStatic) || (s != null && s.IsStatic);
    System.Reflection.ParameterInfo[] ix = p.GetIndexParameters();
    string idx = ix.Length > 0 ? "[" + pars(ix) + "]" : "";
    sb.Append("P|" + p.DeclaringType.Name + "|" + (st ? "static " : "") + nom(p.PropertyType) + " " + p.Name + idx
        + " { " + (g != null ? "get; " : "") + (s != null ? "set; " : "") + "}\n");
}

foreach (System.Reflection.MethodInfo m in elegido.GetMethods(flags))
{
    if (m.IsSpecialName || !pasa(m.Name)) continue;
    string gen = "";
    if (m.IsGenericMethodDefinition)
    {
        var ga = new System.Collections.Generic.List<string>();
        foreach (System.Type a in m.GetGenericArguments()) ga.Add(a.Name);
        gen = "<" + string.Join(", ", ga.ToArray()) + ">";
    }
    sb.Append("M|" + m.DeclaringType.Name + "|" + (m.IsStatic ? "static " : "") + nom(m.ReturnType) + " " + m.Name + gen
        + "(" + pars(m.GetParameters()) + ")\n");
}
return sb.ToString();
"""


def codigo_describe(type_name: str, filter: str = "") -> str:
    """El C# que describe un tipo. Aparte de describe_api para poder
    probarlo (y compilarlo con compile_only) sin ejecutarlo."""
    tipo = (type_name or "").strip()
    if not _RE_TIPO.match(tipo):
        raise ValueError(
            f"type_name inválido: {type_name!r}. Va el nombre corto "
            "('Solid3d') o completo ('Autodesk.AutoCAD.DatabaseServices."
            "Solid3d'), solo letras, números, '_' y '.'.")
    filtro = (filter or "").strip()
    if not _RE_FILTRO.match(filtro):
        raise ValueError(f"filter inválido: {filter!r}. Va un pedazo del "
                         "nombre del miembro ('Extrude'), sin espacios.")
    # Los dos ya pasaron por la regex: no pueden cerrar el literal de C#.
    return (_PLANTILLA_DESCRIBE.replace("__TIPO__", tipo)
            .replace("__FILTRO__", filtro.lower()))


def describe_api(type_name: str, filter: str = "") -> dict[str, Any]:
    """Constructores, propiedades y métodos reales de un tipo de la API."""
    codigo = codigo_describe(type_name, filter)
    r = _ejecutar(codigo, f"describe_api {type_name} {filter}".strip(),
                  compile_only=False, force=True, consulta=True)
    if not r.get("executed") or r.get("message"):
        return {"found": False,
                "message": r.get("message") or "describe_api no se ejecutó.",
                "run_code": r}
    return interpretar_describe(type_name, filter, r.get("result"))


def interpretar_describe(type_name: str, filter: str,
                         salida: Any) -> dict[str, Any]:
    """De las líneas 'X|...' que arma el C# a un resultado ordenado."""
    texto = salida if isinstance(salida, str) else ""
    candidatos: list[dict[str, str]] = []
    elegido: Optional[dict[str, str]] = None
    miembros: list[tuple[str, str, str]] = []   # (categoría, declara, firma)
    for linea in texto.splitlines():
        partes = linea.split("|", 3)
        if len(partes) < 3:
            continue
        cat = partes[0]
        if cat == "T":
            candidatos.append({"type": partes[1],
                               "assembly": partes[2].split(",")[0]})
        elif cat == "S" and len(partes) == 4:
            elegido = {"type": partes[1], "baseType": partes[2],
                       "kind": partes[3]}
        elif cat in ("C", "E", "F", "P", "M"):
            miembros.append((cat, partes[1], partes[2]))

    if elegido is None:
        if not candidatos:
            return {"found": False, "message": (
                f"No hay ningún tipo público '{type_name}' en los assemblies "
                "cargados en AutoCAD. Revisá mayúsculas/ortografía, o probá "
                "el nombre completo (p.ej. 'Autodesk.AutoCAD.DatabaseServices."
                "Solid3d').")}
        return {"found": False, "candidates": candidatos, "message": (
            f"Hay {len(candidatos)} tipos llamados '{type_name}'. Repetí con "
            "el nombre completo de uno de ellos.")}

    corto = elegido["type"].rsplit(".", 1)[-1].split("+")[-1]
    vistos: set[tuple[str, str]] = set()
    propios: list[tuple[str, str, str]] = []
    heredados: list[tuple[str, str, str]] = []
    for cat, declara, firma in miembros:
        if (cat, firma) in vistos:
            continue
        vistos.add((cat, firma))
        (propios if declara == corto or cat in ("C", "E")
         else heredados).append((cat, declara, firma))
    # Lo que declara el tipo primero: con el recorte, lo heredado de
    # DBObject/RXObject es lo que menos se extraña.
    orden = {"C": 0, "E": 1, "P": 2, "M": 3, "F": 4}
    todos = (sorted(propios, key=lambda m: orden[m[0]])
             + sorted(heredados, key=lambda m: orden[m[0]]))
    total = len(todos)
    todos = todos[:MAX_MIEMBROS]

    claves = {"C": "constructors", "E": "enumValues", "P": "properties",
              "M": "methods", "F": "fields"}
    salida_d: dict[str, Any] = {"found": True, **elegido}
    if candidatos:
        salida_d["assembly"] = next(
            (c["assembly"] for c in candidatos if c["type"] == elegido["type"]),
            candidatos[0]["assembly"])
    if len(candidatos) > 1:
        salida_d["otherCandidates"] = [c["type"] for c in candidatos
                                       if c["type"] != elegido["type"]]
    for cat, declara, firma in todos:
        texto_m = firma if declara == corto or cat in ("C", "E") \
            else f"{firma}  — de {declara}"
        salida_d.setdefault(claves[cat], []).append(texto_m)
    salida_d["total"] = total
    if total > MAX_MIEMBROS:
        salida_d["truncated"] = True
        salida_d["warning"] = (
            f"Se muestran {MAX_MIEMBROS} de {total} miembros (primero los "
            "propios del tipo, después los heredados). Repetí con 'filter' "
            "para acotar: describe_api('%s', 'Extrude')." % type_name)
    if filter and total == 0:
        salida_d["warning"] = (f"'{elegido['type']}' no tiene miembros "
                               f"públicos que contengan '{filter}'.")
    return salida_d


# ------------------------------------------------------------- api_guide

_RE_TEMA = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _temas() -> list[str]:
    try:
        return sorted(n[:-3] for n in os.listdir(GUIAS_DIR)
                      if n.endswith(".md"))
    except OSError:
        return []


def _resumen(ruta: str) -> tuple[str, str]:
    """Título (la línea '# ') y la primera línea de texto después."""
    titulo, linea = "", ""
    with open(ruta, encoding="utf-8") as fh:
        for crudo in fh:
            s = crudo.strip()
            if not titulo and s.startswith("# "):
                titulo = s[2:].strip()
            elif titulo and s and not s.startswith(("#", "```", "|", "-")):
                linea = s
                break
    return titulo, linea


def api_guide(topic: str = "") -> str:
    """Guía corta por tema, o el índice si no se pide ninguno."""
    tema = (topic or "").strip().lower()
    temas = _temas()
    if not tema:
        filas = ["Guías de la API de AutoCAD para run_code "
                 "(api_guide('<tema>') para leer una):", ""]
        for t in temas:
            titulo, linea = _resumen(os.path.join(GUIAS_DIR, t + ".md"))
            filas.append(f"- {t}: {titulo}" + (f" — {linea}" if linea else ""))
        return "\n".join(filas)
    # La regex no es estética: sin ella 'topic' podría ser '../../algo' y
    # leer cualquier archivo del disco.
    if not _RE_TEMA.match(tema) or tema not in temas:
        raise ValueError(f"No hay guía '{topic}'. Temas: "
                         + ", ".join(temas) + ".")
    with open(os.path.join(GUIAS_DIR, tema + ".md"), encoding="utf-8") as fh:
        return fh.read()
