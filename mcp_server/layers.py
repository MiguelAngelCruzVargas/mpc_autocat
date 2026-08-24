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


# ----------------------------------------------------------------- color
#
# Los colores 1 a 7 son los "puros" de AutoCAD, pensados para la pantalla
# negra del espacio modelo. En un plano hay que evitarlos salvo dos, y por
# razones OPUESTAS:
#
#   2 amarillo, 4 cian, 3 verde  -> muy claros. En una impresion a color
#       sobre papel blanco casi desaparecen. El amarillo es el peor.
#   5 azul                       -> muy oscuro. Sobre el fondo negro del
#       modelo no se lee; en papel imprime bien. Es al reves de lo que
#       parece: el azul no se pierde al imprimir, se pierde en pantalla.
#   7 blanco/negro y 8 gris      -> los unicos dos que se comportan igual
#       en pantalla y en papel. Son la base de cualquier plano.
#
# Del 10 al 249 estan los tonos por matiz: el indice es matiz + brillo, y
# los pares 2/4/6 bajan la intensidad. Un 32 es el mismo naranja que el 30
# pero al 65%, que es lo que se lee bien en los dos medios.
#
# Nota: si la lamina se traza en MONOCROMO (lo mas comun en obra, con un
# .ctb que manda todo a negro), el color solo define el GROSOR y nada de
# esto afecta la impresion. Igual hay que elegirlo bien, porque el dibujo
# se trabaja en pantalla.

COLOR_PRINCIPAL = 7      # muros, cortes, contornos: negro al imprimir
COLOR_SECUNDARIO = 8     # achurados, rellenos, lo que va atras
COLOR_TENUE = 253        # gris claro, para lo mas liviano
COLOR_EJES = 32          # ambar oscuro (era 4 cian: se lavaba en papel)
COLOR_COTAS = 12         # rojo oscuro (era 1: chillon en pantalla)
COLOR_HIDRAULICA = 152   # azul acero (era 4/5: uno se lava, el otro no se ve)
COLOR_VEGETACION = 96    # verde oliva (era 3: muy claro)
COLOR_REGISTROS = 172    # violeta oscuro (era 6 magenta)

# Los que NO conviene usar, y por que. Lo consulta quien quiera avisar.
EVITAR = {1: "rojo puro: chillon en pantalla, usa 12",
          2: "amarillo: se lava en papel blanco, usa 32 o 42",
          3: "verde puro: muy claro en papel, usa 96",
          4: "cian: el que peor se imprime, usa 152",
          5: "azul puro: tan oscuro que no se lee sobre el fondo del modelo,"
             " usa 152",
          6: "magenta: chillon, usa 172",
          9: "gris muy claro: casi no imprime, usa 8 o 253"}


# ------------------------------------------------------ tipos de linea
#
# Un plano profesional distingue por TRAZO, no solo por color: el eje va
# trazo-punto, lo que esta arriba o detras del plano de corte va punteado,
# el limite de predio va con su trazo propio. Dibujando todo continuo, esa
# informacion se pierde -y en monocromo se pierde del todo, porque ahi el
# color ni siquiera esta.
#
# Los nombres son los de acad.lin (el que trae AutoCAD en cualquier idioma).
# Un AutoCAD en espanol suele traer ADEMAS acadiso.lin con los mismos
# patrones en castellano (CENTRO, OCULTA, TRAZOS): el plano de referencia
# usaba CENTRO1, PHANTOM2, DASHED2 y OCULTA2 mezclados, que son justamente
# esas dos familias conviviendo. ensure_linetype() prueba el nombre pedido
# y, si el dibujo no lo tiene, cae al equivalente en la otra familia en vez
# de fallar.
#
# El sufijo 2 es el MISMO patron a la mitad de escala; dibujando en metros
# casi siempre se quiere el 2 (o directamente ajustar LTSCALE con
# set_display_options, ver CLAUDE.md 4.bis).

LT_EJE = "CENTER2"          # eje de trazo y punto
LT_OCULTO = "HIDDEN2"       # lo que queda detras o debajo del corte
LT_PROYECCION = "DASHED2"   # proyeccion de lo que esta ARRIBA (volados, losas)
LT_LIMITE = "PHANTOM2"      # limite de predio, colindancia, area de proyecto
LT_CONTINUO = "Continuous"

# Equivalencias entre la familia inglesa (acad.lin) y la castellana
# (acadiso.lin). Se prueban en los dos sentidos.
EQUIVALENTES = {
    "CENTER": "CENTRO", "CENTER2": "CENTRO2", "CENTERX2": "CENTROX2",
    "HIDDEN": "OCULTA", "HIDDEN2": "OCULTA2", "HIDDENX2": "OCULTAX2",
    "DASHED": "TRAZOS", "DASHED2": "TRAZOS2", "DASHEDX2": "TRAZOSX2",
    "PHANTOM": "FANTASMA", "PHANTOM2": "FANTASMA2",
    "DASHDOT": "TRAZOYPUNTO", "DIVIDE": "DIVIDIR", "BORDER": "BORDE",
}
_EQUIV_INVERSO = {v: k for k, v in EQUIVALENTES.items()}


def equivalente(linetype: str) -> Optional[str]:
    """El mismo patron en la otra familia (ingles <-> castellano)."""
    if not linetype:
        return None
    n = linetype.upper()
    return EQUIVALENTES.get(n) or _EQUIV_INVERSO.get(n)


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

    def _set(lt: Optional[str]) -> None:
        acad.call("set_layer", {"name": name, "colorIndex": color,
                                "linetype": lt,
                                "lineweightHundredthsMm": lineweight})

    try:
        _set(linetype)
    except acad.AutoCadError:
        # El dibujo no tiene ese patron cargado ni pudo traerlo de acad.lin.
        # Casi siempre es un AutoCAD en el otro idioma (CENTER2 vs CENTRO2):
        # se prueba el equivalente antes de rendirse, y si tampoco, la capa
        # se crea CONTINUA -- una capa sin su trazo se ve peor que perfecta,
        # pero quedarse sin la capa rompe todo lo que iba a dibujarse en ella.
        alterno = equivalente(linetype) if linetype else None
        hecho = False
        if alterno:
            try:
                _set(alterno)
                hecho = True
            except acad.AutoCadError:
                hecho = False
        if not hecho:
            _set(None)
    _existing().add(name.upper())
    return True
