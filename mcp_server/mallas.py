"""Primitivas de malla (MESH): qué método de SubDMesh llamar y con qué argumentos, validado antes de tocar AutoCAD.

`SubDMesh` se crea vacía y un método Set* le da forma (verificado en vivo con SetSphere). Las firmas salen del
descompilado (acdbmgd, SubDMesh): Setbox(xlen, ylen, zlen, divx, divy, divz, smooth), SetSphere(radius, divAxis,
divHeight, smooth), SetCylinder(majorR, minorR, height, divAxis, divHeight, divCap, smooth), SetCone(majorR, minorR,
height, divAxis, divHeight, divCap, radiusRatio, smooth), SetPyramid(radius, height, divLength, divHeight, divCap,
nSides, radiusRatio, smooth), SetTorus(majorR, divSection, divSweepPath, sectionRadiusRatio, sectionRotate, smooth),
SetWedge(xLen, yLen, zLen, divLength, divWidth, divHeight, divSlope, divCap, smooth).
"""
from __future__ import annotations

from typing import Any, Optional

MODOS_SUAVIZADO = {"up": "SubdDivideUp", "down": "SubdDivideDown", "refine": "SubdRefine"}

FORMAS = {
    "box": ("Setbox", 3), "sphere": ("SetSphere", 1), "cylinder": ("SetCylinder", 2), "cone": ("SetCone", 2),
    "pyramid": ("SetPyramid", 2), "torus": ("SetTorus", 2), "wedge": ("SetWedge", 3),
}


class MallaError(ValueError):
    """Argumento inválido: se informa antes de tocar AutoCAD."""


def _pos(v: Any, cual: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) == float("inf") or v <= 0:
        raise MallaError(f"'{cual}' tiene que ser un número mayor que cero.")
    return float(v)


def mesh_primitiva(shape: str, size: Optional[list[float]], divisions: int, smooth: int) -> dict[str, Any]:
    if shape not in FORMAS:
        raise MallaError(f"'shape' es una de: {', '.join(FORMAS)}.")
    metodo, n = FORMAS[shape]
    if not isinstance(size, (list, tuple)) or len(size) != n:
        raise MallaError(f"{shape} necesita 'size' con {n} medida(s) "
                         + {"box": "[largo, ancho, alto]", "sphere": "[radio]", "cylinder": "[radio, alto]",
                            "cone": "[radio_base, alto]", "pyramid": "[radio, alto]", "torus": "[radio_mayor, radio_tubo]",
                            "wedge": "[largo, ancho, alto]"}[shape] + ".")
    medidas = [_pos(v, f"size[{i}]") for i, v in enumerate(size)]
    if isinstance(divisions, bool) or not isinstance(divisions, int) or not 1 <= divisions <= 64:
        raise MallaError("'divisions' es un entero de 1 a 64.")
    if isinstance(smooth, bool) or not isinstance(smooth, int) or not 0 <= smooth <= 4:
        raise MallaError("'smooth' es un entero de 0 a 4.")
    d = divisions
    if shape == "box":
        args = [medidas[0], medidas[1], medidas[2], d, d, d, smooth]
    elif shape == "sphere":
        args = [medidas[0], max(d * 2, 4), d, smooth]
    elif shape == "cylinder":
        args = [medidas[0], medidas[0], medidas[1], max(d * 2, 4), d, 1, smooth]
    elif shape == "cone":
        args = [medidas[0], 0.0, medidas[1], max(d * 2, 4), d, 1, 1.0, smooth]
    elif shape == "pyramid":
        args = [medidas[0], medidas[1], d, d, 1, 4, 1.0, smooth]
    elif shape == "torus":
        if medidas[1] >= medidas[0]:
            raise MallaError("El radio del tubo tiene que ser menor que el radio mayor del toro.")
        args = [medidas[0], max(d, 3), max(d * 2, 6), medidas[1] / medidas[0], 0.0, smooth]
    else:  # wedge
        args = [medidas[0], medidas[1], medidas[2], d, d, d, d, 1, smooth]
    return {"metodo": metodo, "args": args}
