"""Estándar de oficina: revisar el dibujo contra las reglas de la oficina.

Cada oficina tiene su forma de dibujar —qué capas, de qué color, con qué
letra— y es lo primero que revisa quien recibe un DWG. Los check_* de este
proyecto validan el oficio (muros, cotas, lámina); esto valida la FORMA,
contra un archivo que la persona edita (desde el panel web o a mano):
%LOCALAPPDATA%\\AutoCadMcp\\estandar_oficina.json.

Sin archivo se usa un estándar mínimo que vale para cualquier oficina: nada
dibujado en la capa 0, ninguna fuente txt.shx (no tiene acentos ni Ø) y
ninguna capa en uso con los colores puros 1-6 (CLAUDE.md 6.ter: se lavan al
imprimir o no se ven en pantalla).

Formato (todo opcional):

    {
      "nombre": "Oficina X",
      "capas": {"MUROS": {"color": 7, "linetype": "Continuous"},
                "COTAS": {"color": 12}},
      "capas_obligatorias": ["MUROS", "COTAS", "TEXTOS"],
      "prohibir_capa_0": true,
      "fuentes_prohibidas": ["txt"],
      "colores_prohibidos": [1, 2, 3, 4, 5, 6]
    }
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import autocad_client as acad

ARCHIVO = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                       "AutoCadMcp", "estandar_oficina.json")

MINIMO: dict[str, Any] = {
    "nombre": "Estándar mínimo",
    "capas": {},
    "capas_obligatorias": [],
    "prohibir_capa_0": True,
    "fuentes_prohibidas": ["txt"],
    "colores_prohibidos": [1, 2, 3, 4, 5, 6],
}


def cargar(ruta: Optional[str] = None) -> dict[str, Any]:
    """El estándar de la oficina, o el mínimo si no hay archivo."""
    ruta = ruta or ARCHIVO
    try:
        with open(ruta, encoding="utf-8") as fh:
            datos = json.load(fh)
    except FileNotFoundError:
        return dict(MINIMO)
    except (OSError, ValueError) as exc:
        raise ValueError(f"El estándar de oficina ({ruta}) no se pudo leer: "
                         f"{exc}. Corregí el JSON o borralo para usar el mínimo.")
    if not isinstance(datos, dict):
        raise ValueError("El estándar de oficina tiene que ser un objeto JSON.")
    return {**MINIMO, **datos}


def guardar(estandar: dict[str, Any], ruta: Optional[str] = None) -> str:
    validar(estandar)
    ruta = ruta or ARCHIVO
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(estandar, fh, indent=2, ensure_ascii=False)
    return ruta


def validar(estandar: Any) -> None:
    """Que el estándar se pueda aplicar: un error de tipeo en el JSON tiene
    que decirse al guardarlo, no aparecer como "todo bien" al revisar."""
    if not isinstance(estandar, dict):
        raise ValueError("El estándar tiene que ser un objeto JSON {…}.")
    capas = estandar.get("capas", {})
    if not isinstance(capas, dict):
        raise ValueError("'capas' tiene que ser {\"NOMBRE\": {\"color\": n}}.")
    for nombre, regla in capas.items():
        if not isinstance(regla, dict):
            raise ValueError(f"La regla de la capa '{nombre}' tiene que ser un objeto.")
        color = regla.get("color")
        if color is not None and not (isinstance(color, int) and 1 <= color <= 255):
            raise ValueError(f"Capa '{nombre}': color {color!r} no es un índice 1-255.")
    for clave in ("capas_obligatorias", "fuentes_prohibidas", "colores_prohibidos"):
        if not isinstance(estandar.get(clave, []), list):
            raise ValueError(f"'{clave}' tiene que ser una lista.")


def revisar(estandar: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Compara el dibujo abierto contra el estándar. Problemas en el mismo
    formato que los demás check_* (rule / problem / fix)."""
    est = estandar if estandar is not None else cargar()
    validar(est)
    problemas: list[dict[str, str]] = []

    capas = acad.call("list_layers", {}).get("layers", [])
    por_nombre = {str(c.get("name", "")).upper(): c for c in capas}
    entidades = acad.call("list_entities", {"limit": 200000}).get("entities", [])
    usadas: dict[str, int] = {}
    for e in entidades:
        clave = str(e.get("layer", "")).upper()
        usadas[clave] = usadas.get(clave, 0) + 1

    for nombre in est.get("capas_obligatorias", []):
        if str(nombre).upper() not in por_nombre:
            problemas.append({
                "rule": "capa obligatoria",
                "problem": f"Falta la capa '{nombre}' del estándar de la oficina.",
                "fix": f"Creala con set_layer('{nombre}', …) y pasá ahí lo que corresponda."})

    for nombre, regla in (est.get("capas") or {}).items():
        capa = por_nombre.get(str(nombre).upper())
        if capa is None:
            continue
        color = regla.get("color")
        if color is not None and capa.get("colorIndex") != color:
            problemas.append({
                "rule": "color de capa",
                "problem": f"La capa '{capa['name']}' tiene color "
                           f"{capa.get('colorIndex')} y el estándar pide {color}.",
                "fix": f"set_layer('{capa['name']}', color_index={color})."})
        tipo = regla.get("linetype")
        if tipo and str(capa.get("linetype", "")).upper() != str(tipo).upper():
            problemas.append({
                "rule": "tipo de línea",
                "problem": f"La capa '{capa['name']}' usa {capa.get('linetype')} y "
                           f"el estándar pide {tipo}.",
                "fix": f"set_layer('{capa['name']}', linetype='{tipo}')."})

    if est.get("prohibir_capa_0") and usadas.get("0"):
        problemas.append({
            "rule": "capa 0",
            "problem": f"Hay {usadas['0']} entidad(es) dibujadas en la capa 0.",
            "fix": "Pasalas a la capa de su tipo (MUROS, COTAS, TEXTOS…): en la "
                   "capa 0 no se pueden apagar ni plotear aparte."})

    prohibidos = {int(c) for c in est.get("colores_prohibidos", [])}
    for c in capas:
        nombre = str(c.get("name", ""))
        if (c.get("colorIndex") in prohibidos and usadas.get(nombre.upper())
                and nombre.upper() not in {str(n).upper() for n in (est.get("capas") or {})}):
            problemas.append({
                "rule": "color puro",
                "problem": f"La capa '{nombre}' ({usadas[nombre.upper()]} entidades) "
                           f"usa el color puro {c['colorIndex']}.",
                "fix": "Usá el equivalente al 50-65% (ver CLAUDE.md 6.ter): ámbar 32 "
                       "en vez de 2/4, rojo oscuro 12 en vez de 1, azul acero 152…"})

    fuentes = [str(f).lower().replace(".shx", "") for f in est.get("fuentes_prohibidas", [])]
    if fuentes:
        estilos = acad.call("list_styles", {}).get("textStyles", [])
        for s in estilos:
            fuente = str(s.get("font", "")).lower().replace(".shx", "")
            if fuente in fuentes:
                problemas.append({
                    "rule": "fuente",
                    "problem": f"El estilo de texto '{s.get('name')}' usa {fuente}.shx.",
                    "fix": "set_text_style con una TrueType (arial.ttf): la .shx "
                           "de fábrica no tiene acentos ni el símbolo Ø."})

    return {"ok": not problemas, "problems": problemas, "count": len(problemas),
            "standard": est.get("nombre", "Estándar de la oficina")}
