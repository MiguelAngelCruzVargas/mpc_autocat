"""El espacio del plano: que escala rige y que franjas ya estan ocupadas.

Existe porque las cotas y las burbujas de eje se ubicaban por dos caminos que
no se hablaban. `create_axis_grid` calculaba su extension y su radio con el
tamano del dibujo, y quien acotaba elegia el offset a mano: en una casa de
9x12 la burbuja cae entre -1.56 y -0.96, y una cota general a -1.10 le pasa
por adentro. No hay valor fijo que acierte, porque uno de los dos se mueve con
el tamano del plano.

La solucion es que cada cosa que se dibuja al margen del plano **reserve** la
franja que ocupa, y que la siguiente se apile afuera. Es la misma idea que ya
resuelve bien los rotulos de ambiente en furniture.OCCUPIED, aplicada al
aparato de anotacion.

Ademas guarda la escala de la lamina (unidades del modelo por mm de papel),
que create_sheet ya calcula y hasta ahora se perdia: es lo que permite pedir
"6 mm de papel" y que salga bien en metros a 1:50 y en milimetros a 1:20.

Unidades: las del modelo. Nada de esto habla con AutoCAD.
"""
from __future__ import annotations

from typing import Any, Optional

# Franjas ocupadas al margen del dibujo. Cada una es un bounding box mas una
# etiqueta de quien la reservo, que es lo que se le muestra a la persona
# cuando algo no entra.
OCCUPIED: list[dict[str, Any]] = []

# Unidades del modelo por milimetro de papel. Es el mismo numero que
# create_sheet devuelve como unitsPerPaperMm y que DIMSCALE espera: dibujando
# en metros a 1:50, 1 mm de papel son 0.05 unidades.
_UNITS_PER_PAPER_MM = [0.1]

SIDES = ("bottom", "top", "left", "right")

# Huella de lo que YA esta dibujado adentro del plano: muros, zapatas, muebles,
# rotulos ya puestos. Es lo que mira place_labels para no escribir encima. Es
# el mismo registro que furniture usaba solo para los rotulos de ambiente,
# subido aca para que sirva a cualquier plano.
FOOTPRINTS: list[dict[str, Any]] = []


def track(x0: float, y0: float, x1: float, y1: float,
          what: str = "") -> dict[str, Any]:
    """Registra el rectangulo que ocupa algo ya dibujado."""
    huella = {"x0": min(x0, x1), "y0": min(y0, y1),
              "x1": max(x0, x1), "y1": max(y0, y1), "what": what}
    FOOTPRINTS.append(huella)
    return huella


def clear_footprints() -> None:
    FOOTPRINTS.clear()


def hits(x0: float, y0: float, x1: float, y1: float,
         margin: float = 0.0) -> list[dict[str, Any]]:
    """Que huellas estorban en ese rectangulo."""
    a0, b0 = min(x0, x1) - margin, min(y0, y1) - margin
    a1, b1 = max(x0, x1) + margin, max(y0, y1) + margin
    return [h for h in FOOTPRINTS
            if h["x0"] < a1 and h["x1"] > a0 and h["y0"] < b1 and h["y1"] > b0]


def set_scale(units_per_paper_mm: float) -> None:
    if units_per_paper_mm <= 0:
        raise ValueError("units_per_paper_mm tiene que ser > 0.")
    _UNITS_PER_PAPER_MM[0] = float(units_per_paper_mm)


def units_per_paper_mm() -> float:
    return _UNITS_PER_PAPER_MM[0]


def paper(mm: float, scale: Optional[float] = None) -> float:
    """Milimetros de papel -> unidades del modelo."""
    return mm * (scale if scale else _UNITS_PER_PAPER_MM[0])


def clear() -> None:
    OCCUPIED.clear()
    FOOTPRINTS.clear()


def reserve(x0: float, y0: float, x1: float, y1: float,
            what: str = "") -> dict[str, Any]:
    """Marca un rectangulo como ocupado por el aparato de anotacion."""
    banda = {"x0": min(x0, x1), "y0": min(y0, y1),
             "x1": max(x0, x1), "y1": max(y0, y1), "what": what}
    OCCUPIED.append(banda)
    return banda


# ------------------------------------------------- geometria de las franjas

def _to_offset(banda: dict[str, Any], side: str,
               reference: float) -> tuple[float, float, float, float]:
    """La franja vista desde un lado: (offset_desde, offset_hasta, a_lo_largo).

    'offset' es la distancia hacia AFUERA del dibujo, asi los cuatro lados se
    resuelven con la misma cuenta en vez de con cuatro casos repetidos.
    """
    if side == "bottom":
        return (reference - banda["y1"], reference - banda["y0"],
                banda["x0"], banda["x1"])
    if side == "top":
        return (banda["y0"] - reference, banda["y1"] - reference,
                banda["x0"], banda["x1"])
    if side == "left":
        return (reference - banda["x1"], reference - banda["x0"],
                banda["y0"], banda["y1"])
    if side == "right":
        return (banda["x0"] - reference, banda["x1"] - reference,
                banda["y0"], banda["y1"])
    raise ValueError(f"side tiene que ser uno de {SIDES}, no {side!r}.")


def band_box(side: str, reference: float, offset: float, thickness: float,
             along_min: float, along_max: float) -> tuple[float, float, float, float]:
    """El rectangulo (x0,y0,x1,y1) de una franja puesta a 'offset' del borde."""
    a, b = offset, offset + thickness
    if side == "bottom":
        return (along_min, reference - b, along_max, reference - a)
    if side == "top":
        return (along_min, reference + a, along_max, reference + b)
    if side == "left":
        return (reference - b, along_min, reference - a, along_max)
    if side == "right":
        return (reference + a, along_min, reference + b, along_max)
    raise ValueError(f"side tiene que ser uno de {SIDES}, no {side!r}.")


def free_offset(side: str, reference: float, along_min: float, along_max: float,
                thickness: float, gap: float, start: float = 0.0) -> float:
    """A que distancia del borde cabe una franja de 'thickness' sin pisar nada.

    Recorre lo reservado de adentro hacia afuera y se corre al primer hueco
    donde entra, dejando 'gap' de aire. Es lo que hace que la segunda cadena
    de cotas salga sola donde va, y que la tercera salga afuera de las
    burbujas si los ejes se dibujaron antes.
    """
    if along_max < along_min:
        along_min, along_max = along_max, along_min

    estorbos = []
    for banda in OCCUPIED:
        desde, hasta, a0, a1 = _to_offset(banda, side, reference)
        if hasta <= 0:
            continue  # queda del lado del dibujo, no en el margen de este lado
        if a1 < along_min - gap or a0 > along_max + gap:
            continue  # no se cruza con el tramo que vamos a acotar
        estorbos.append((desde, hasta))

    offset = max(start, 0.0)
    for desde, hasta in sorted(estorbos):
        if hasta + gap <= offset:
            continue                      # ya lo pasamos
        if desde >= offset + thickness + gap:
            break                         # entra antes de este estorbo
        offset = hasta + gap
    return offset


def bands(side: Optional[str] = None) -> list[dict[str, Any]]:
    """Lo reservado hasta ahora, para inspeccionar o para check_annotations."""
    return [dict(b) for b in OCCUPIED]


def overlaps(extra: Optional[list[dict[str, Any]]] = None,
             tol: float = 1e-6) -> list[dict[str, Any]]:
    """Pares de franjas que se pisan, entre lo reservado y lo que se pase.

    Con las tools de anotacion no deberia haber ninguno: si aparece uno es
    porque se ubico algo a mano, que es exactamente lo que hay que avisar.
    """
    todo = OCCUPIED + list(extra or [])
    choques = []
    for i, a in enumerate(todo):
        for b in todo[i + 1:]:
            dx = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
            dy = min(a["y1"], b["y1"]) - max(a["y0"], b["y0"])
            if dx > tol and dy > tol:
                choques.append({
                    "a": a.get("what", ""), "b": b.get("what", ""),
                    "overlapX": round(dx, 3), "overlapY": round(dy, 3),
                    "box": [round(max(a["x0"], b["x0"]), 3),
                            round(max(a["y0"], b["y0"]), 3),
                            round(min(a["x1"], b["x1"]), 3),
                            round(min(a["y1"], b["y1"]), 3)],
                })
    return choques
