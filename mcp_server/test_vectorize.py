"""Tests de vectorize.py (calco de imágenes a polilíneas). NO necesita
AutoCAD. Se omite si faltan numpy / opencv / scikit-image.

Uso:  python test_vectorize.py
"""
from __future__ import annotations

import os
import sys
import tempfile

try:
    import cv2
    import numpy as np
    import skimage  # noqa: F401
except ImportError:
    print("omitido: faltan numpy, opencv-python-headless o scikit-image")
    sys.exit(0)

import vectorize

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name + (f" -- {detalle}" if not ok else ""))


def imagen() -> str:
    img = np.zeros((200, 300, 3), np.uint8)
    cv2.rectangle(img, (20, 20), (120, 100), (255, 255, 255), 1)       # blanco
    cv2.circle(img, (200, 60), 30, (255, 255, 0), 1)                    # cian (BGR)
    cv2.line(img, (20, 150), (280, 150), (0, 0, 220), 1)                # rojo
    p = os.path.join(tempfile.gettempdir(), "vec_test.png")
    cv2.imwrite(p, img)
    return p


def test_colores_y_geometria() -> None:
    r = vectorize.vectorizar(imagen(), scale=2.0, origin=(100, 50), dry_run=True)
    check("separa por color", r["byColor"].get("blanco", 0) >= 1 and r["byColor"].get("cian", 0) >= 1
          and r["byColor"].get("rojo", 0) >= 1, r["byColor"])
    check("tamaño en unidades = píxeles x escala", r["sizeDrawing"] == [600.0, 400.0], r["sizeDrawing"])
    check("dry_run no dibuja", r["dryRun"] is True)


def test_recorte_y_errores() -> None:
    r = vectorize.vectorizar(imagen(), scale=1.0, crop=(0, 0, 150, 120), dry_run=True)
    check("el recorte deja solo el rectángulo blanco", r["byColor"].get("cian", 0) == 0, r["byColor"])
    for kw in ({"classes": ["naranja"]},):
        try:
            vectorize.vectorizar(imagen(), scale=1.0, dry_run=True, **kw)
            check("rechaza un color inexistente", False)
        except ValueError:
            check("rechaza un color inexistente", True)
    try:
        vectorize.vectorizar(r"C:\no_existe.png", scale=1.0, dry_run=True)
        check("rechaza una imagen ilegible", False)
    except ValueError:
        check("rechaza una imagen ilegible", True)


if __name__ == "__main__":
    for n, fn in list(globals().items()):
        if n.startswith("test_") and callable(fn):
            print(n)
            fn()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" -", f)
        sys.exit(1)
    print("\nOK")
