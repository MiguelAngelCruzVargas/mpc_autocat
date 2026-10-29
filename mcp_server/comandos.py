"""Ejecutar CUALQUIER comando de AutoCAD (run_command), con una lista negra.

Lo que hace Autodesk con su módulo nativo (Editor.Command): el comando y lo que
se le contesta (puntos, opciones, texto, Enter) van como una lista de «tokens»,
exactamente lo que alguien tecleó en la línea de comandos. Con esto el chat
alcanza TODO lo que se hace en AutoCAD, también lo que ninguna tool cubre.

Qué NO pasa por acá (la lista negra, que el plugin repite en
Commands/NativeOpsCommand.cs y `test_comandos.py` comprueba que coincidan):
  - lo que carga o ejecuta código ajeno (NETLOAD, APPLOAD, LISP, SCRIPT, menús,
    macros) o abre otros programas (SHELL, START, BROWSER): es la puerta para
    saltarse la seguridad, y para eso ya está run_code, que apaga y prende la
    persona con su contraseña;
  - lo que cambia la seguridad (OPTIONS, las variables de SECURELOAD,
    TRUSTEDPATHS...: las mismas que protege set_system_variable);
  - lo que tumba la sesión o cierra todo (QUIT, EXIT, CLOSEALL): para cerrar
    dibujos están close_document y save_drawing, que avisan y verifican;
  - cualquier token que empiece con «(» o «!»: AutoCAD lo evalúa como LISP aunque
    se escriba en medio de otro comando.

Las ventanas de diálogo bloquearían a AutoCAD y con él el socket: el plugin pone
FILEDIA=0 y CMDDIA=0 mientras corre (los comandos piden todo por línea de
comandos) y los restaura. La salida de la línea de comandos no se puede leer;
se verifica mirando el dibujo (`created` / `deleted` del resultado, list_entities).
"""
from __future__ import annotations

from typing import Any

MAX_TOKENS = 400
MAX_LARGO = 2000

# Debe ser IGUAL a NativeOpsCommand.ComandosDenegados (lo comprueba test_comandos.py).
DENEGADOS = (
    "NETLOAD", "APPLOAD", "ARX", "LISP", "VLISP", "VLIDE", "VLLOAD", "VLRUN",
    "VBARUN", "VBAIDE", "VBALOAD", "VBAMAN", "VBAUNLOAD", "VBASTMT",
    "SCRIPT", "RSCRIPT", "RESUME", "ACTRUN",
    "SHELL", "SH", "START", "STARTAPP", "BROWSER",
    "CUI", "CUILOAD", "CUIUNLOAD", "CUIEXPORT", "CUIIMPORT", "MENU", "MENULOAD", "MENUUNLOAD",
    "CUSTOMIZE", "ALIASEDIT", "OPTIONS", "SECURITYOPTIONS",
    "QUIT", "EXIT", "CLOSEALL",
)

# Las mismas que protege set_system_variable (SystemVariableCommands.Protegidas).
PROTEGIDAS = (
    "SECURELOAD", "TRUSTEDPATHS", "TRUSTEDDOMAINS", "LEGACYCODESEARCH",
    "DEMANDLOAD", "SAVEFILEPATH", "SAVEFILE", "ACADLSPASDOC",
    "LISPSYS", "SECURITYFLAGS", "STARTUP", "FILEDIA", "CMDDIA",
    "PROXY", "WEBMESSAGES",
)


class ComandoError(ValueError):
    """Pedido inválido o no permitido: se informa antes de tocar AutoCAD."""


def base(token: str) -> str:
    """El nombre del comando sin prefijos (_ . ' * -) y en mayúsculas."""
    t = token.strip().lstrip("_.'*").lstrip("-")
    return t.upper()


def motivo_denegado(textos: list[str]) -> str | None:
    """Por qué NO se ejecuta, o None si se puede. `textos` son los tokens como texto."""
    if not textos or not textos[0].strip():
        return "Falta el comando: el primer token es su nombre (p. ej. \"LINE\")."
    nombre = base(textos[0])
    if nombre in DENEGADOS:
        return (f"«{nombre}» no se ejecuta por aquí: carga código, abre otro programa, cambia la seguridad "
                "o cierra AutoCAD. Para cerrar o guardar dibujos usa close_document / save_drawing.")
    if nombre in PROTEGIDAS:
        return f"«{nombre}» es una variable de seguridad o de carga automática: la cambia una persona."
    if nombre == "SETVAR" and len(textos) > 1 and base(textos[1]) in PROTEGIDAS:
        return f"«{base(textos[1])}» es una variable de seguridad o de carga automática: la cambia una persona."
    for t in textos:
        if t.lstrip().startswith(("(", "!")):
            return ("Un token que empieza con «(» o «!» lo evalúa AutoCAD como LISP: no se permite. "
                    "Si el texto lleva paréntesis, ponlos después de alguna letra.")
    return None


def validar(tokens: Any) -> list[Any]:
    """Los tokens ya revisados (texto, número o None = Enter) o ComandoError."""
    if not isinstance(tokens, (list, tuple)) or not tokens:
        raise ComandoError("'tokens' tiene que ser una lista: el comando y, uno por elemento, lo que se le contesta "
                           "(puntos como \"0,0\", opciones, texto; null = Enter).")
    if len(tokens) > MAX_TOKENS:
        raise ComandoError(f"Demasiados tokens ({len(tokens)}; máximo {MAX_TOKENS}): parte el trabajo en varios comandos.")
    limpios: list[Any] = []
    textos: list[str] = []
    for i, t in enumerate(tokens):
        if t is None:
            limpios.append(None)
            textos.append("")
        elif isinstance(t, bool):
            raise ComandoError(f"El token {i} es un booleano: usa texto (\"Yes\", \"No\"), número o null.")
        elif isinstance(t, (int, float)):
            if t != t or abs(t) == float("inf"):
                raise ComandoError(f"El token {i} es un número inválido (NaN o infinito).")
            limpios.append(t)
            textos.append(repr(float(t)))
        elif isinstance(t, str):
            if len(t) > MAX_LARGO:
                raise ComandoError(f"El token {i} mide {len(t)} caracteres (máximo {MAX_LARGO}).")
            limpios.append(t)
            textos.append(t)
        else:
            raise ComandoError(f"El token {i} tiene que ser texto, número o null, no {type(t).__name__}.")
    if not isinstance(limpios[0], str):
        raise ComandoError("El primer token es el nombre del comando y tiene que ser texto.")
    motivo = motivo_denegado(textos)
    if motivo:
        raise ComandoError(motivo)
    return limpios
