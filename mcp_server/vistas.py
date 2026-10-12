"""¿Cada dibujo del modelo dice qué es?

Salió mirando el modelo de un proyecto entero: plantas, secciones y
detalles desparramados por el espacio modelo, varios sin título, y nadie
—ni el dueño del proyecto— sabía qué eran "esas líneas rojas". Las láminas
salían bien porque compose_layout titula cada viewport, pero el modelo es
lo que abre quien sigue trabajando el DWG.

check_view_titles agrupa el modelo en VISTAS (entidades cuyas cajas quedan
a menos de 'gap' entre sí) y reporta cada vista que no tiene un título
(create_view_title escribe en TITULOS). Un título que quedó separado de su
dibujo se asigna a la vista sin título más cercana, que es lo que lee
cualquiera que mira el plano.

Una sola llamada al plugin (list_entities con includeExtents): pedir la
caja entidad por entidad eran miles de viajes de ~0.5 s.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Optional

import autocad_client as acad

CAPAS_TITULO = ("TITULOS",)
# Lo que no es dibujo: el cajón y el rótulo de create_sheet, las ventanas
# de los viewports.
CAPAS_IGNORADAS = ("CAJON", "ROTULO", "DEFPOINTS", "NORTE")
# Una tabla ya trae su título adentro ("CUADRO DE CONSTRUCCIÓN",
# "SIMBOLOGÍA — INSTALACIÓN ELÉCTRICA"): no es una vista sin nombre.
TITULOS_PROPIOS = ("CUADRO DE", "CUADRO DE ", "SIMBOLOG", "TABLA", "CATÁLOGO", "CATALOGO",
                   "NOTAS")


def agrupar(cajas: list[list[float]], gap: float) -> list[list[int]]:
    """Índices de las cajas agrupados por cercanía (unión-búsqueda con una
    grilla de celdas de tamaño 'gap' para no comparar todas contra todas)."""
    padre = list(range(len(cajas)))

    def raiz(i: int) -> int:
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    celda = max(gap, 1e-6)
    grilla: dict[tuple[int, int], list[int]] = {}
    for i, (x0, y0, x1, y1) in enumerate(cajas):
        # Cajas gigantes (un terreno de 40 m) ocupan muchas celdas: se
        # limita para que una sola no haga explotar la grilla.
        cx0, cx1 = math.floor((x0 - gap) / celda), math.floor((x1 + gap) / celda)
        cy0, cy1 = math.floor((y0 - gap) / celda), math.floor((y1 + gap) / celda)
        if (cx1 - cx0 + 1) * (cy1 - cy0 + 1) > 40000:
            celda_i = [(cx0, cy0)]
        else:
            celda_i = [(a, b) for a in range(cx0, cx1 + 1) for b in range(cy0, cy1 + 1)]
        for c in celda_i:
            for j in grilla.get(c, []):
                a, b = cajas[i], cajas[j]
                if (a[0] - gap <= b[2] and b[0] - gap <= a[2]
                        and a[1] - gap <= b[3] and b[1] - gap <= a[3]):
                    ri, rj = raiz(i), raiz(j)
                    if ri != rj:
                        padre[ri] = rj
            grilla.setdefault(c, []).append(i)
    grupos: dict[int, list[int]] = {}
    for i in range(len(cajas)):
        grupos.setdefault(raiz(i), []).append(i)
    return list(grupos.values())


def _caja(cajas: list[list[float]], idx: list[int]) -> list[float]:
    return [min(cajas[i][0] for i in idx), min(cajas[i][1] for i in idx),
            max(cajas[i][2] for i in idx), max(cajas[i][3] for i in idx)]


def _distancia(a: list[float], b: list[float]) -> float:
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return math.hypot(dx, dy)


def revisar(entidades: list[dict[str, Any]], gap: float,
            capas_titulo: tuple[str, ...] = CAPAS_TITULO,
            capas_ignoradas: tuple[str, ...] = CAPAS_IGNORADAS,
            min_entidades: int = 3) -> dict[str, Any]:
    """La parte que no habla con AutoCAD (testeable): entidades con 'box'
    y 'layer' -> vistas con y sin título."""
    tit = {c.upper() for c in capas_titulo}
    ign = {c.upper() for c in capas_ignoradas}
    ents = [e for e in entidades if e.get("box") and e["layer"].upper() not in ign]
    cajas = [list(map(float, e["box"])) for e in ents]
    grupos = agrupar(cajas, gap)
    vistas = []
    solo_titulo = []
    for g in grupos:
        capas = Counter(ents[i]["layer"] for i in g)
        con_titulo = any(c.upper() in tit for c in capas) or any(
            str(ents[i].get("text") or "").strip().upper().startswith(TITULOS_PROPIOS) for i in g)
        dibujo = sum(n for c, n in capas.items() if c.upper() not in tit)
        v = {"box": [round(v_, 2) for v_ in _caja(cajas, g)], "entities": len(g),
             "layers": [c for c, _ in capas.most_common(4)], "titled": con_titulo,
             "titles": [ents[i].get("text") for i in g
                        if ents[i]["layer"].upper() in tit and ents[i].get("text")]}
        if con_titulo and dibujo == 0:
            solo_titulo.append(v)
        else:
            vistas.append(v)
    # Un título que quedó lejos de su dibujo titula la vista sin título más
    # cercana (a no más de 4 gaps).
    for t in solo_titulo:
        sin = [v for v in vistas if not v["titled"]]
        if not sin:
            break
        cerca = min(sin, key=lambda v: _distancia(v["box"], t["box"]))
        if _distancia(cerca["box"], t["box"]) <= 4.0 * gap:
            cerca["titled"] = True
            cerca["titles"] += t["titles"]
    sin_titulo = [v for v in vistas if not v["titled"] and v["entities"] >= min_entidades]
    sueltas = [v for v in vistas if not v["titled"] and v["entities"] < min_entidades]
    problemas = [{"rule": "vista-con-titulo",
                  "problem": f"Hay un dibujo sin título en el modelo, caja "
                             f"{v['box']} ({v['entities']} entidades; capas "
                             f"{', '.join(v['layers'])}). Quien abra el DWG no sabe qué es.",
                  "fix": "create_view_title arriba a la izquierda del dibujo, con su escala."}
                 for v in sin_titulo]
    return {"ok": not problemas, "problems": problemas, "views": len(vistas),
            "untitled": sin_titulo, "loose": sueltas, "gap": gap}


def check_view_titles(gap: Optional[float] = None, min_entities: int = 6,
                      title_layers: Optional[list[str]] = None,
                      ignore_layers: Optional[list[str]] = None,
                      limit: int = 200000) -> dict[str, Any]:
    """Corre la revisión sobre el MODELO del dibujo activo (aunque haya una
    lámina abierta)."""
    import space
    if gap is None:
        # 15 mm de papel a la escala de la lámina: más que el aire entre
        # una planta y sus cotas, menos que el que se deja entre vistas.
        gap = space.paper(15.0)
    r = acad.call("list_entities", {"type": None, "limit": limit, "allSpaces": True,
                                    "includeText": True, "includeExtents": True})
    modelo = [e for e in r.get("entities", []) if str(e.get("space", "Model")).lower() == "model"]
    out = revisar(modelo, gap, tuple(title_layers or CAPAS_TITULO),
                  tuple(ignore_layers or CAPAS_IGNORADAS), min_entities)
    if r.get("count", 0) >= limit:
        out["warning"] = f"Se revisaron solo las primeras {limit} entidades."
    return out
