"""Vectorizar (calcar) un dibujo CAD que solo existe como imagen.

Toma una captura de pantalla o un raster de un plano de líneas finas sobre
fondo oscuro, separa los trazos por COLOR (blanco, cian, rojo, amarillo,
verde...), los adelgaza a un píxel, sigue cada trazo y lo simplifica a una
polilínea. Cada color va a su capa y a su índice ACI.

Es CALCADO, no diseño: el resultado es tan fiel como la imagen (del orden de
un píxel) y NO es paramétrico — las líneas no saben que forman una ventana.
Sirve para reproducir con exactitud visual un plano que no se tiene en DWG;
las medidas reales salen de la ESCALA que se le da (cm por píxel), que hay
que calibrar con una cota conocida de la imagen.

Dependencias opcionales (no vienen con el servidor):
    pip install numpy opencv-python-headless scikit-image
"""
from __future__ import annotations

import math
from typing import Any, Optional

import autocad_client as acad
import prim

# nombre -> (descripción, ACI, capa)
CLASES: dict[str, tuple[int, str]] = {
    "blanco": (7, "TRAZO-BLANCO"),
    "cian": (134, "TRAZO-CIAN"),
    "rojo": (12, "TRAZO-ROJO"),
    "amarillo": (42, "TRAZO-AMARILLO"),
    "verde": (94, "TRAZO-VERDE"),
    "azul": (150, "TRAZO-AZUL"),
    "magenta": (212, "TRAZO-MAGENTA"),
}


def _importar() -> tuple[Any, Any, Any]:
    try:
        import cv2
        import numpy as np
        from skimage.morphology import skeletonize
    except ImportError as ex:                          # pragma: no cover
        raise RuntimeError(
            "Faltan dependencias para vectorizar: pip install numpy "
            "opencv-python-headless scikit-image") from ex
    return cv2, np, skeletonize


def clasificar(rgb: Any, min_valor: int = 45, min_sat_color: int = 40,
               max_sat_blanco: int = 45, min_valor_blanco: int = 70
               ) -> dict[str, Any]:
    """Máscaras booleanas por color de una imagen RGB (alto, ancho, 3)."""
    cv2, np, _ = _importar()
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    vivo = (v >= min_valor) & (s >= min_sat_color)
    return {
        "blanco": (s <= max_sat_blanco) & (v >= min_valor_blanco),
        "cian": vivo & (h >= 68) & (h <= 102),
        "rojo": vivo & ((h <= 8) | (h >= 165)),
        "amarillo": vivo & (h >= 14) & (h <= 36),
        "verde": vivo & (h >= 45) & (h <= 67),
        "azul": vivo & (h >= 105) & (h <= 130),
        "magenta": vivo & (h >= 135) & (h <= 160),
    }


def seguir_esqueleto(esq: Any) -> list[list[tuple[int, int]]]:
    """Caminos (listas de (x, y) en píxeles) de un esqueleto de 1 px: cada
    tramo entre extremos y cruces."""
    ys, xs = esq.nonzero()
    pts = set(zip(xs.tolist(), ys.tolist()))
    vec = ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1))

    def vecinos(p: tuple[int, int]) -> list[tuple[int, int]]:
        return [(p[0] + dx, p[1] + dy) for dx, dy in vec if (p[0] + dx, p[1] + dy) in pts]

    grado = {p: len(vecinos(p)) for p in pts}
    visitado_arista: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    caminos: list[list[tuple[int, int]]] = []

    def marcar(a: tuple[int, int], b: tuple[int, int]) -> None:
        visitado_arista.add((a, b))
        visitado_arista.add((b, a))

    nodos = [p for p, g in grado.items() if g != 2]
    for n in nodos:
        for v in vecinos(n):
            if (n, v) in visitado_arista:
                continue
            camino = [n, v]
            marcar(n, v)
            prev, cur = n, v
            while grado[cur] == 2:
                sig = [q for q in vecinos(cur) if q != prev and (cur, q) not in visitado_arista]
                if not sig:
                    break
                nxt = sig[0]
                marcar(cur, nxt)
                camino.append(nxt)
                prev, cur = cur, nxt
            caminos.append(camino)
    # lazos cerrados sin nodos (círculos): lo que quedó sin visitar
    for p in pts:
        if grado[p] == 2:
            for v in vecinos(p):
                if (p, v) in visitado_arista:
                    continue
                camino = [p, v]
                marcar(p, v)
                prev, cur = p, v
                while True:
                    sig = [q for q in vecinos(cur) if q != prev and (cur, q) not in visitado_arista]
                    if not sig:
                        break
                    nxt = sig[0]
                    marcar(cur, nxt)
                    camino.append(nxt)
                    prev, cur = cur, nxt
                caminos.append(camino)
    return caminos


def vectorizar(path: str, scale: float, origin: tuple[float, float] = (0.0, 0.0),
               crop: Optional[tuple[int, int, int, int]] = None,
               classes: Optional[list[str]] = None, epsilon: float = 0.9,
               min_length_px: float = 3.0, max_paths: int = 20000,
               dry_run: bool = False) -> dict[str, Any]:
    """Calca `path` a polilíneas. `scale` = unidades del dibujo por píxel;
    `origin` = dónde cae la esquina INFERIOR izquierda del recorte;
    `crop` = (x0, y0, x1, y1) en píxeles (para quitar la cinta de
    comandos); `classes` = qué colores calcar (todos por defecto)."""
    cv2, np, skeletonize = _importar()
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"No se pudo leer la imagen: {path}")
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    if crop:
        x0, y0, x1, y1 = crop
        rgb = rgb[y0:y1, x0:x1]
    alto, ancho = rgb.shape[:2]
    masks = clasificar(rgb)
    elegidas = classes or list(CLASES)
    for c in elegidas:
        if c not in CLASES:
            raise ValueError(f"Color '{c}' no existe: {', '.join(CLASES)}.")
    resumen: dict[str, int] = {}
    todos: list[tuple[str, list[prim.Point]]] = []
    k = np.ones((2, 2), np.uint8)
    for nombre in elegidas:
        m = masks[nombre].astype(np.uint8)
        if m.sum() == 0:
            continue
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k)
        esq = skeletonize(m.astype(bool))
        n = 0
        for cam in seguir_esqueleto(esq):
            pts = np.array(cam, dtype=np.float32).reshape(-1, 1, 2)
            simp = cv2.approxPolyDP(pts, epsilon, False).reshape(-1, 2)
            if len(simp) < 2:
                continue
            largo = float(np.sum(np.hypot(*np.diff(simp, axis=0).T)))
            if largo < min_length_px:
                continue
            real = [(origin[0] + float(x) * scale, origin[1] + (alto - float(y)) * scale)
                    for x, y in simp]
            todos.append((nombre, real))
            n += 1
        resumen[nombre] = n
    if len(todos) > max_paths:
        raise ValueError(f"{len(todos)} trazos superan max_paths={max_paths}: "
                         "sube epsilon o min_length_px, o recorta la imagen.")
    if not dry_run:
        for nombre in elegidas:
            prim.capa(CLASES[nombre][1], CLASES[nombre][0], 13)
        with acad.lote():
            for nombre, real in todos:
                aci, capa = CLASES[nombre]
                prim.poly(real, capa, False, 13, None)
    return {"paths": len(todos), "byColor": resumen,
            "sizePx": [ancho, alto],
            "sizeDrawing": [round(ancho * scale, 2), round(alto * scale, 2)],
            "dryRun": dry_run}
