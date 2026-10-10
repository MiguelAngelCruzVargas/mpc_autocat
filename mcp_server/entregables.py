"""Entrega de un proyecto: una carpeta con el NOMBRE DEL PROYECTO, adentro
una subcarpeta por tipo de archivo (DWG para abrir en AutoCAD, PDF, XLSX...)
y el juego completo en UN PDF, sin tocar los individuales.

Regla del usuario: los archivos de un proyecto no quedan sueltos en una
carpeta de pruebas con nombres técnicos; se entregan ordenados y con el
juego en un solo archivo. Nada se borra: los archivos se MUEVEN a su lugar
(o se copian con move=False) y si ya existe uno con ese nombre se avisa en
vez de pisarlo.
"""
from __future__ import annotations

import os
import re
import shutil
from typing import Any, Optional

# Subcarpeta por extensión. Lo que no está acá va a OTROS.
SUBCARPETA = {".dwg": "DWG", ".bak": "DWG", ".dxf": "DWG", ".dwt": "DWG",
              ".pdf": "PDF", ".xlsx": "XLSX", ".xls": "XLSX", ".csv": "XLSX",
              ".json": "DATOS", ".png": "IMAGENES", ".jpg": "IMAGENES"}

# Orden del juego: arquitectónico, estructural, instalaciones, cuantificación.
ORDEN_DISCIPLINA = ["A", "E", "IE", "IH", "IS", "IP", "IG", "C"]


def nombre_de_carpeta(proyecto: str) -> str:
    """El nombre del proyecto tal cual, sin lo que Windows no admite en una
    carpeta (<>:"/\\|?*) ni punto o espacio al final."""
    limpio = re.sub(r'[<>:"/\\|?*]+', " ", proyecto)
    limpio = re.sub(r"\s+", " ", limpio).strip().rstrip(". ")
    if not limpio:
        raise ValueError("El nombre del proyecto queda vacío: pasá un nombre real.")
    return limpio


def clave_de_lamina(ruta: str) -> tuple:
    """Orden de una lámina por su clave al final del nombre (A-01, IE-02...)."""
    base = os.path.splitext(os.path.basename(ruta))[0]
    m = re.search(r"([A-Z]{1,3})-(\d+)$", base.upper())
    if not m:
        return (len(ORDEN_DISCIPLINA), base)
    pref, num = m.group(1), int(m.group(2))
    return (ORDEN_DISCIPLINA.index(pref) if pref in ORDEN_DISCIPLINA else len(ORDEN_DISCIPLINA),
            pref, num)


def package_deliverables(project: str, base_dir: str, files: list[str],
                         move: bool = True, combine_pdf: bool = True,
                         sheet_order: Optional[list[str]] = None) -> dict[str, Any]:
    """Arma la carpeta de entrega del proyecto.

    project: nombre del proyecto (es el nombre de la carpeta).
    base_dir: dónde se crea la carpeta del proyecto.
    files: los archivos a entregar (DWG, PDF por lámina, XLSX...).
    move: True los mueve (no se borra ninguno: cambian de lugar); False copia.
    combine_pdf: además une los PDF en '<proyecto> - JUEGO COMPLETO.pdf', en
    el orden de las claves de lámina (A, E, IE, IH, IS, IG, C) o en
    sheet_order si se pasa (lista de nombres de archivo).
    """
    carpeta = os.path.join(base_dir, nombre_de_carpeta(project))
    os.makedirs(carpeta, exist_ok=True)
    ubicados, avisos = [], []
    for f in files:
        if not os.path.isfile(f):
            avisos.append(f"No existe, no se entregó: {f}")
            continue
        sub = SUBCARPETA.get(os.path.splitext(f)[1].lower(), "OTROS")
        destino_dir = os.path.join(carpeta, sub)
        os.makedirs(destino_dir, exist_ok=True)
        destino = os.path.join(destino_dir, os.path.basename(f))
        if os.path.abspath(destino) == os.path.abspath(f):
            ubicados.append(destino)
            continue
        if os.path.exists(destino):
            avisos.append(f"Ya existe {destino}: no se pisó (se dejó el original en {f}).")
            continue
        (shutil.move if move else shutil.copy2)(f, destino)
        ubicados.append(destino)

    resultado: dict[str, Any] = {"folder": carpeta, "files": ubicados}
    pdfs = [p for p in ubicados if p.lower().endswith(".pdf")]
    if combine_pdf and pdfs:
        if sheet_order:
            orden = {os.path.basename(n): i for i, n in enumerate(sheet_order)}
            pdfs.sort(key=lambda p: (orden.get(os.path.basename(p), len(orden)), p))
        else:
            pdfs.sort(key=clave_de_lamina)
        try:
            import logging
            # Los PDF de AutoCAD repiten /PageMode: pypdf lo avisa por cada
            # archivo y es inofensivo. Ruido, no información.
            logging.getLogger("pypdf").setLevel(logging.ERROR)
            from pypdf import PdfWriter
        except ImportError as exc:
            raise RuntimeError("Falta pypdf para unir el juego: pip install pypdf "
                               "(está en requirements.txt).") from exc
        juego = os.path.join(carpeta, f"{nombre_de_carpeta(project)} - JUEGO COMPLETO.pdf")
        escritor = PdfWriter()
        for p in pdfs:
            escritor.append(p)
        with open(juego, "wb") as fh:
            escritor.write(fh)
        escritor.close()
        resultado.update({"combinedPdf": juego, "sheetsInOrder": [os.path.basename(p) for p in pdfs],
                          "pages": len(pdfs)})
    if avisos:
        resultado["warnings"] = avisos
    return resultado
