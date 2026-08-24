"""Estado de sesión: lo que ninguna llamada suelta puede vigilar.

Tres cosas salieron mal en sesiones reales y ninguna tool individual podía
verlas, porque son propiedades de la SESIÓN entera y no de una llamada:

- AutoCAD se cayó con un FATAL ERROR a mitad de una sesión larga y se llevó
  un plano entero sin guardar. Ninguna tool falló: murió el proceso completo,
  y con él todo lo dibujado en memoria. La única defensa es guardar seguido,
  así que acá se cuentan las operaciones de dibujo desde el último
  save_drawing y se inyecta un aviso cuando se acumulan.

- save_drawing() sin path, después de un save_drawing(path=...) anterior,
  puede terminar en Documents\\Drawing1.dwg en vez de pisar ese mismo archivo
  (pasó de verdad). Acá se recuerda el último path usado, para que el
  siguiente guardado sin path caiga donde corresponde.

- Los check_* de cierre existen, pero nada exigía correrlos: un plano se
  podía exportar a PDF sin que nadie mirara si las cotas se pisan. Acá se
  recuerda si hubo dibujo nuevo desde el último check_all, y export_pdf lo
  pregunta antes de plotear.

Mismo criterio que space.py: globals de proceso, cero llamadas a AutoCAD.
Se resetea al cambiar de dibujo (server._reset_drawing_state). El enganche
con el tráfico real es after_call(), que autocad_client.call invoca en cada
comando que responde bien — así el conteo no depende de que cada tool se
acuerde de reportarse.
"""
from __future__ import annotations

from typing import Any, Optional

# Cada cuántas operaciones de dibujo sin guardar se repite el aviso. No es
# "guardá en cada llamada": es el punto en el que perder lo hecho ya duele.
UMBRAL_SIN_GUARDAR = 40

# Comandos que no tocan el DWG: mirar no ensucia.
_READ_ONLY_PREFIXES = ("list_", "get_")
_READ_ONLY = frozenset({
    "ping", "select_entities", "measure_text", "calculate_area",
    "calculate_properties", "capture_viewport", "zoom_extents",
    "export_pdf", "export_block", "export_quantities_csv",
})

# Comandos de ciclo de vida: no son "dibujo sin guardar" (save_drawing lo
# resetea, y los de documento pasan por _reset_drawing_state en server.py).
_LIFECYCLE = frozenset({
    "save_drawing", "open_document", "new_document", "close_document",
    "set_active_document",
})

_OPS_SINCE_SAVE = [0]
_SAVE_PATH: list[Optional[str]] = [None]
_DIRTY_SINCE_CHECK = [False]


def _is_mutation(cmd: str) -> bool:
    if cmd in _READ_ONLY or cmd in _LIFECYCLE:
        return False
    return not cmd.startswith(_READ_ONLY_PREFIXES)


def retry_safe(cmd: str) -> bool:
    """¿Se puede REPETIR el comando sin efectos dobles?

    Los de lectura (y los plots, que pisan su propio archivo) sí: repetirlos
    solo cuesta un par de segundos. Los que dibujan NO: un create_line
    reintentado tras un timeout puede haber llegado la primera vez, y quedan
    dos líneas superpuestas — de esas que check_drawing_hygiene después
    reporta como duplicados."""
    return not _is_mutation(cmd) and cmd not in _LIFECYCLE


def after_call(cmd: str, params: dict[str, Any],
               result: Any) -> Any:
    """Contabiliza un comando que el plugin ya ejecutó bien.

    Si el conteo cruza el umbral, inyecta el aviso en el propio resultado —
    el aviso viaja en el dato, no depende de que alguien lo pregunte.
    """
    if cmd == "save_drawing":
        note_saved(params.get("path") or _SAVE_PATH[0])
        return result
    if not _is_mutation(cmd):
        return result

    _OPS_SINCE_SAVE[0] += 1
    _DIRTY_SINCE_CHECK[0] = True

    n = _OPS_SINCE_SAVE[0]
    if n and n % UMBRAL_SIN_GUARDAR == 0 and isinstance(result, dict):
        aviso = (
            f"Van {n} operaciones de dibujo sin save_drawing. AutoCAD se "
            "puede caer a mitad de sesión y llevarse todo lo no guardado: "
            "guardá ahora"
            + (f" (el último path fue '{_SAVE_PATH[0]}')." if _SAVE_PATH[0]
               else " (con path explícito si el dibujo aún no tiene).")
        )
        if "warning" not in result and "warnings" not in result:
            result = dict(result)
            result["warning"] = aviso
    return result


def note_saved(path: Optional[str]) -> None:
    """El dibujo se guardó: arranca el conteo de nuevo y recuerda el path."""
    _OPS_SINCE_SAVE[0] = 0
    if path:
        _SAVE_PATH[0] = str(path)


def note_opened(path: Optional[str]) -> None:
    """Se abrió un DWG existente: su path es el destino natural del próximo
    guardado sin path."""
    if path:
        _SAVE_PATH[0] = str(path)


def last_save_path() -> Optional[str]:
    return _SAVE_PATH[0]


def ops_since_save() -> int:
    return _OPS_SINCE_SAVE[0]


def note_checked() -> None:
    """check_all corrió: lo dibujado hasta acá quedó revisado."""
    _DIRTY_SINCE_CHECK[0] = False


def dirty_since_check() -> bool:
    """¿Hubo dibujo nuevo desde el último check_all?"""
    return _DIRTY_SINCE_CHECK[0]


def reset() -> None:
    """Cambio de dibujo: nada de esto vale para el DWG nuevo."""
    _OPS_SINCE_SAVE[0] = 0
    _SAVE_PATH[0] = None
    _DIRTY_SINCE_CHECK[0] = False
