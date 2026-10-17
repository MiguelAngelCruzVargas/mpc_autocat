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

# Comandos que se cuentan DESDE QUIEN LOS LLAMA y no acá. run_code no se
# puede clasificar por su nombre: el mismo comando es una consulta de solo
# lectura (describe_api, compile_only) o un dibujo entero, y si falla la
# transacción se aborta y no ensució nada. engine.py sabe cuál de los casos
# fue y llama a note_mutation() solo cuando corresponde.
_COUNTED_BY_CALLER = frozenset({"run_code"})

_OPS_SINCE_SAVE = [0]
_SAVE_PATH: list[Optional[str]] = [None]
_DIRTY_SINCE_CHECK = [False]

# Path donde se guardó CADA documento, por su clave (ver doc_key). El path
# "de la sesión" de arriba es uno solo, y con dos dibujos abiertos eso pisó un
# archivo con el contenido del otro: el autoguardado previo de run_code
# escribía el documento ACTIVO en el último path guardado, que era de otro
# dibujo. Hasta el cambio de documento se desincroniza sin que este proceso
# se entere: capture_viewport plotea y deja activo otro documento, y nada
# pasa por _reset_drawing_state. Por eso el destino de un guardado se busca
# por documento y nunca se hereda del "último path" global.
_SAVE_PATH_BY_DOC: dict[str, str] = {}


def doc_key(doc: Any) -> Optional[str]:
    """Clave estable de un documento, a partir de la entrada de
    list_documents (dict con fullPath/name). Un dibujo sin guardar conserva
    el nombre 'Drawing1.dwg' aunque se lo haya guardado con SaveAs, así que
    el nombre sirve de clave cuando no hay carpeta."""
    if not isinstance(doc, dict):
        return None
    clave = doc.get("fullPath") or doc.get("name")
    return str(clave).replace("/", "\\").lower() if clave else None


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
    reporta como duplicados.

    run_code nunca: no se sabe si el código dibuja, y uno que tardó más que
    el timeout probablemente SIGUE corriendo dentro de AutoCAD."""
    if cmd in _COUNTED_BY_CALLER:
        return False
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
    if cmd in _COUNTED_BY_CALLER or not _is_mutation(cmd):
        return result
    return note_mutation(result)


def note_mutation(result: Any = None) -> Any:
    """Cuenta UNA operación de dibujo y, si cruza el umbral, mete el aviso
    en el resultado. Es lo mismo que after_call hace solo para cada comando
    que dibuja; existe aparte para los que cuenta quien los llama."""
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


def note_saved(path: Optional[str], doc: Optional[str] = None) -> None:
    """El dibujo se guardó: arranca el conteo de nuevo y recuerda el path.

    doc: la clave (doc_key) del documento que se guardó. Con ella el path
    queda atado a ESE documento; sin ella solo se actualiza el path global,
    que ninguna decisión de guardado debe usar para otro documento."""
    _OPS_SINCE_SAVE[0] = 0
    if path:
        _SAVE_PATH[0] = str(path)
        if doc:
            _SAVE_PATH_BY_DOC[doc] = str(path)


def note_opened(path: Optional[str], doc: Optional[str] = None) -> None:
    """Se abrió un DWG existente: su path es el destino natural del próximo
    guardado sin path."""
    if path:
        _SAVE_PATH[0] = str(path)
        if doc:
            _SAVE_PATH_BY_DOC[doc] = str(path)


def last_save_path(doc: Optional[str] = None) -> Optional[str]:
    """Path de guardado recordado. Con doc: el de ESE documento (None si no
    se guardó con path explícito). Sin doc: el último global, solo para
    mensajes — no para decidir dónde escribir."""
    if doc is not None:
        return _SAVE_PATH_BY_DOC.get(doc)
    return _SAVE_PATH[0]


def forget_doc(doc: Optional[str]) -> None:
    """Un documento se cerró o nació uno nuevo con ese nombre: AutoCAD
    reutiliza 'Drawing1.dwg', y heredar el path del dibujo anterior que se
    llamaba igual sería pisar su archivo."""
    if doc:
        _SAVE_PATH_BY_DOC.pop(doc, None)


def ops_since_save() -> int:
    return _OPS_SINCE_SAVE[0]


def note_checked() -> None:
    """check_all corrió: lo dibujado hasta acá quedó revisado."""
    _DIRTY_SINCE_CHECK[0] = False


def dirty_since_check() -> bool:
    """¿Hubo dibujo nuevo desde el último check_all?"""
    return _DIRTY_SINCE_CHECK[0]


def reset() -> None:
    """Cambio de dibujo: nada de esto vale para el DWG nuevo.

    Los paths por documento NO se tocan: describen cada archivo, no la
    sesión, y hay que conservarlos al volver a un dibujo ya guardado."""
    _OPS_SINCE_SAVE[0] = 0
    _SAVE_PATH[0] = None
    _DIRTY_SINCE_CHECK[0] = False


def reset_all() -> None:
    """Todo, incluidos los paths por documento (para tests)."""
    reset()
    _SAVE_PATH_BY_DOC.clear()
