"""Verificar que la anotacion no pise el dibujo, preguntandole al DIBUJO.

check_annotations compara contra un registro interno (space.OCCUPIED y
space.FOOTPRINTS) que llenan las tools de alto nivel: create_walls,
place_furniture, create_dimension_chain, create_axis_grid, y los textos que
se auto-registran.

El problema es que la mayor parte de un plano real se dibuja con primitivas
-create_polyline, create_line, create_circle- y eso no registra nada. Para
check_annotations ese dibujo esta VACIO. No es que la comparacion falle: no
tiene contra que comparar.

Paso de verdad: un corte de barda dibujado con create_polyline, con el titulo
"CORTE A-A / BARDA PERIMETRAL TIPO" cayendo sobre la dala de cerramiento.
check_annotations lo daba por bueno porque la dala nunca existio para el.

Aca la pregunta es otra: para cada texto, SE LE PIDE A AUTOCAD que diga que
hay dentro de su caja. No depende de ningun registro, ni de que quien dibujo
haya usado las tools "buenas", ni de que nadie se acuerde de nada. Y sirve
igual para un plano ajeno.

Unidades: las del dibujo.
"""
from __future__ import annotations

from typing import Any, Optional

import autocad_client as acad

# Lo que ES anotacion. Que dos de estos se toquen tambien es un problema,
# pero de otra clase: se reporta aparte porque se arregla distinto (mover el
# rotulo, contra rehacer la cadena de cotas).
TIPOS_ANOTACION = frozenset({
    "DBText", "MText", "MLeader", "Leader",
    "RotatedDimension", "AlignedDimension", "RadialDimension",
    "DiametricDimension", "LineAngularDimension2", "Point3AngularDimension",
    "ArcDimension", "OrdinateDimension",
})

# Los que se buscan como "texto a revisar".
TIPOS_TEXTO = ("DBText", "MText")


def _caja(handle: str) -> Optional[list[float]]:
    """La caja de una entidad, tal como la calcula AutoCAD."""
    try:
        d = acad.call("get_entity", {"handle": handle})
    except acad.AutoCadError:
        return None
    caja = d.get("bbox")
    if not caja or len(caja) != 4:
        return None
    return [float(c) for c in caja]


def check_text_placement(margin: float = 0.0,
                         layers: Optional[list[str]] = None,
                         ignore_layers: Optional[list[str]] = None,
                         limit: int = 400) -> dict[str, Any]:
    """Revisa que ningun texto del dibujo caiga encima de la geometria.

    Para cada texto pide su caja y pregunta que entidades la cruzan. Lo que
    no sea anotacion, es dibujo tapado.

    margin: aire que se le exige alrededor, en unidades del dibujo. 0 detecta
    solo el encimado franco; un valor chico ademas exige respiro.
    layers: revisar solo los textos de esas capas.
    ignore_layers: no contar como estorbo lo que este en esas capas (util
    para una capa de fondo o de referencia que a proposito va debajo).

    Devuelve 'ok' y la lista de problemas, cada uno con el texto, su caja y
    QUE lo esta tapando -- con handle y capa, para poder ir a mirarlo.
    """
    if margin < 0:
        raise ValueError("margin no puede ser negativo.")

    ignorar = {c.upper() for c in (ignore_layers or [])}

    sel = acad.call("select_entities", {
        "x1": None, "y1": None, "x2": None, "y2": None,
        "layers": layers, "types": list(TIPOS_TEXTO), "mode": "inside"})
    textos = sel.get("entities", [])[:limit]

    problemas: list[dict[str, Any]] = []
    revisados = 0
    sin_caja = 0

    for t in textos:
        caja = _caja(t["handle"])
        if caja is None:
            sin_caja += 1
            continue
        revisados += 1
        x0, y0, x1, y1 = caja
        cruzan = acad.call("select_entities", {
            "x1": x0 - margin, "y1": y0 - margin,
            "x2": x1 + margin, "y2": y1 + margin,
            "layers": None, "types": None, "mode": "crossing"})

        dibujo: list[dict[str, str]] = []
        otros_textos: list[dict[str, str]] = []
        for o in cruzan.get("entities", []):
            if o["handle"] == t["handle"]:
                continue
            if str(o.get("layer", "")).upper() in ignorar:
                continue
            destino = (otros_textos if o["type"] in TIPOS_ANOTACION else dibujo)
            destino.append({"handle": o["handle"], "type": o["type"],
                            "layer": o.get("layer")})

        if dibujo:
            problemas.append({
                "handle": t["handle"], "layer": t.get("layer"),
                "kind": "sobre el dibujo",
                "box": caja,
                "over": dibujo[:8],
                "problem": ("El texto %s (capa %s) cae sobre %d entidad(es) "
                            "de dibujo: %s"
                            % (t["handle"], t.get("layer"), len(dibujo),
                               ", ".join("%s %s" % (d["type"], d["handle"])
                                         for d in dibujo[:4]))),
            })
        elif otros_textos:
            problemas.append({
                "handle": t["handle"], "layer": t.get("layer"),
                "kind": "sobre otra anotacion",
                "box": caja,
                "over": otros_textos[:8],
                "problem": ("El texto %s se encima con %d anotacion(es): %s"
                            % (t["handle"], len(otros_textos),
                               ", ".join("%s %s" % (d["type"], d["handle"])
                                         for d in otros_textos[:4]))),
            })

    aviso = None
    if sin_caja:
        aviso = ("%d texto(s) no reportaron caja y no se pudieron revisar. "
                 "Suele ser texto vacio, o un plugin viejo: get_entity "
                 "devuelve 'bbox' desde la version 1.0.0." % sin_caja)
    if len(sel.get("entities", [])) > limit:
        aviso = ((aviso + " ") if aviso else "") + (
            "Hay %d textos y se revisaron los primeros %d; subi 'limit'."
            % (len(sel["entities"]), limit))

    return {
        "ok": not problemas,
        "checked": revisados,
        "problems": problemas,
        "warning": aviso,
    }
