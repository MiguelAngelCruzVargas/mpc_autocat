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


def _caja(handle: str,
          cache: Optional[dict[str, Optional[list[float]]]] = None
          ) -> Optional[list[float]]:
    """La caja de una entidad, tal como la calcula AutoCAD.

    Con `cache`, cada handle se le pregunta a AutoCAD UNA vez. No es un
    detalle: la misma entidad grande -- el contorno de muros, el cajon de la
    lamina -- cae en la caja de casi todos los textos, y sin cache se pedia
    su bbox una vez por texto. En un plano de 104 textos eso eran ~200
    llamadas de mas, y cada llamada al plugin cuesta ~0.5 s.
    """
    if cache is not None and handle in cache:
        return cache[handle]
    try:
        d = acad.call("get_entity", {"handle": handle})
    except acad.AutoCadError:
        caja = None
    else:
        cruda = d.get("bbox")
        caja = ([float(c) for c in cruda]
                if cruda and len(cruda) == 4 else None)
    if cache is not None:
        cache[handle] = caja
    return caja


def _contiene(afuera: Optional[list[float]],
              adentro: list[float]) -> bool:
    """El primer rectangulo contiene ENTERO al segundo."""
    if not afuera:
        return False
    return (afuera[0] <= adentro[0] and afuera[1] <= adentro[1]
            and afuera[2] >= adentro[2] and afuera[3] >= adentro[3])


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
    cajas: dict[str, Optional[list[float]]] = {}

    sel = acad.call("select_entities", {
        "x1": None, "y1": None, "x2": None, "y2": None,
        "layers": layers, "types": list(TIPOS_TEXTO), "mode": "inside"})
    textos = sel.get("entities", [])[:limit]

    problemas: list[dict[str, Any]] = []
    revisados = 0
    sin_caja = 0
    encerrados = 0

    for t in textos:
        caja = _caja(t["handle"], cajas)
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
        recuadros: list[dict[str, str]] = []
        for o in cruzan.get("entities", []):
            if o["handle"] == t["handle"]:
                continue
            if str(o.get("layer", "")).upper() in ignorar:
                continue
            if o["type"] in TIPOS_ANOTACION:
                otros_textos.append({"handle": o["handle"], "type": o["type"],
                                     "layer": o.get("layer")})
                continue
            # Un contorno que CONTIENE al texto entero no lo esta tapando: lo
            # esta encerrando. Es la celda de una tabla, la casilla de un
            # rotulo, el contorno de un ambiente. Sin distinguirlo, cada celda
            # de cada tabla sale como problema -- 107 falsos positivos en una
            # sola lamina, medidos.
            #
            # Un Hatch es la excepcion: si el texto cae adentro de un achurado,
            # el achurado le pasa POR ENCIMA aunque lo contenga.
            if (o["type"] != "Hatch"
                    and _contiene(_caja(o["handle"], cajas), caja)):
                recuadros.append({"handle": o["handle"], "type": o["type"],
                                  "layer": o.get("layer")})
                continue
            dibujo.append({"handle": o["handle"], "type": o["type"],
                           "layer": o.get("layer")})

        if recuadros and not dibujo:
            encerrados += 1

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
        "enclosed": encerrados,
        "problems": problemas,
        "warning": aviso,
    }
