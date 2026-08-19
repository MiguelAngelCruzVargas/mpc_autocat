"""Alta de capas que RESPETA lo que ya esta configurado en el dibujo.

Cada tool de la biblioteca se aseguraba su capa llamando set_layer con el
color y el grosor que trae por defecto. El efecto no se ve hasta que alguien
configura las capas a mano —o segun la norma de su oficina— y dibuja: la
primera calle le devuelve EJE a amarillo y su VIAL_EJE queda sin el tipo de
linea que habia puesto.

La regla correcta es que la capa existente manda. Estas defaults son para el
que no las configuro, no para pisar al que si.

El listado del dibujo se consulta una vez y se cachea; reset() lo invalida
cuando se cambia de documento.
"""
from __future__ import annotations

from typing import Optional

import autocad_client as acad

_EXISTING: Optional[set[str]] = None
_TEXT_CHECKED = [False]

# Fuente de fabrica de AutoCAD. No mapea acentos ni el simbolo de diametro:
# "SECCION" sale bien pero "SECCIÓN" y "Ø 30" salen con cuadraditos, y no se
# nota hasta abrir el DWG. Cualquier .ttf lo resuelve.
FUENTE_DEFECTO = "txt"
ESTILO_TEXTO = "MCP-ARIAL"


def reset() -> None:
    """Olvida lo cacheado. Al cambiar de dibujo, o si se crearon capas afuera."""
    global _EXISTING
    _EXISTING = None
    _TEXT_CHECKED[0] = False


def ensure_text_style() -> Optional[str]:
    """Si el dibujo sigue con la fuente de fabrica, pasa a una TrueType.

    Se corre una sola vez por dibujo y NO pisa un estilo elegido a proposito:
    solo actua cuando el estilo activo es el 'txt' que trae AutoCAD de fabrica,
    que es el que rompe los acentos. Devuelve el estilo que dejo activo, o None
    si no toco nada.
    """
    if _TEXT_CHECKED[0]:
        return None
    _TEXT_CHECKED[0] = True
    try:
        estilos = acad.call("list_styles", {}).get("textStyles", [])
    except (acad.AutoCadError, KeyError, TypeError, AttributeError):
        return None
    activo = next((e for e in estilos if e.get("isCurrent")), None)
    if not activo:
        return None
    fuente = str(activo.get("font", "")).lower().replace(".shx", "")
    if fuente != FUENTE_DEFECTO:
        return None      # alguien ya eligio; no se toca
    acad.call("set_text_style", {
        "name": ESTILO_TEXTO, "font": "arial.ttf", "height": 0.0,
        "widthFactor": 1.0, "oblique": 0.0, "setCurrent": True})
    return ESTILO_TEXTO


def _existing() -> set[str]:
    global _EXISTING
    if _EXISTING is None:
        try:
            capas = acad.call("list_layers", {}).get("layers", [])
            _EXISTING = {str(c.get("name", "")).upper() for c in capas}
        except (acad.AutoCadError, KeyError, TypeError, AttributeError):
            # Sin listado, mejor crear de mas que dejar la capa sin existir.
            _EXISTING = set()
    return _EXISTING


def ensure(name: str, color: int, lineweight: int,
           linetype: Optional[str] = None, force: bool = False) -> bool:
    """Crea la capa si no existe. Devuelve True si la creo.

    force=True aplica el color y el grosor aunque la capa ya exista; es para
    cuando la persona los esta pidiendo de forma explicita, no para los
    defaults de una tool de dibujo.
    """
    if not name:
        return False
    if not force and name.upper() in _existing():
        return False
    acad.call("set_layer", {"name": name, "colorIndex": color,
                            "linetype": linetype,
                            "lineweightHundredthsMm": lineweight})
    _existing().add(name.upper())
    return True
