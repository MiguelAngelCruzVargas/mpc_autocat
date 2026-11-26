"""Leer un PDF de planos para el modo análisis (tool `read_pdf`).

Dos cosas por página:
  - el TEXTO (rótulos, cotas, notas, cuadros), con pypdf: es exacto y barato;
  - una IMAGEN de la página (pypdfium2), para que un modelo con visión la MIRE.
    Muchos planos son vectores sin texto extraíble, o escaneos: sin la imagen el
    modelo no vería nada. El chat de AutoCAD le pasa al modelo las rutas que
    vienen en `imagenes_para_ver`, igual que con capture_viewport.

Las imágenes se reducen a LADO_MAX px (lo que aprovechan los modelos de visión)
y se guardan en una carpeta temporal propia. Nunca modifica el PDF.
"""
from __future__ import annotations

import os
import tempfile
from typing import Any, Optional

LADO_MAX = 1568
MAX_PAGINAS = 6           # por llamada: más páginas son más costo por vuelta
TEXTO_MAX = 6000          # caracteres por página


def _rango(paginas: str, total: int) -> list[int]:
    """'1-3,5' -> [1, 2, 3, 5] dentro de 1..total."""
    if not paginas or not paginas.strip():
        return list(range(1, min(total, MAX_PAGINAS) + 1))
    salida: list[int] = []
    for parte in paginas.replace(" ", "").split(","):
        if not parte:
            continue
        if "-" in parte:
            a, _, b = parte.partition("-")
            ini, fin = int(a or 1), int(b or total)
            salida.extend(range(ini, fin + 1))
        else:
            salida.append(int(parte))
    vistas = []
    for n in salida:
        if 1 <= n <= total and n not in vistas:
            vistas.append(n)
    return vistas[:MAX_PAGINAS]


def _imagen(ruta: str, numero: int, carpeta: str) -> Optional[str]:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    try:
        doc = pdfium.PdfDocument(ruta)
        pagina = doc[numero - 1]
        ancho, alto = pagina.get_size()
        escala = min(LADO_MAX / max(ancho, alto, 1), 4.0)
        img = pagina.render(scale=escala).to_pil()
        destino = os.path.join(carpeta, f"pagina_{numero:03d}.png")
        img.save(destino, "PNG", optimize=True)
        doc.close()
        return destino
    except Exception:          # noqa: BLE001 - una página que no se dibuja no tumba el resto
        return None


def leer(ruta: str, paginas: str = "", con_imagenes: bool = True) -> dict[str, Any]:
    if not ruta or not os.path.isfile(ruta):
        return {"ok": False, "error": f"No existe el archivo: {ruta}"}
    if not ruta.lower().endswith(".pdf"):
        return {"ok": False, "error": "Solo PDF. Para un DWG usa open_document (de solo lectura) y las tools de consulta."}
    try:
        from pypdf import PdfReader
        lector = PdfReader(ruta)
        total = len(lector.pages)
    except Exception as exc:   # noqa: BLE001
        return {"ok": False, "error": f"No se pudo abrir el PDF (¿protegido o dañado?): {exc}"}
    try:
        numeros = _rango(paginas, total)
    except ValueError:
        return {"ok": False, "error": "Páginas inválidas: usa por ejemplo '1-3' o '2,5'."}
    carpeta = tempfile.mkdtemp(prefix="architech_pdf_") if con_imagenes else ""
    salida, imagenes = [], []
    for n in numeros:
        try:
            texto = (lector.pages[n - 1].extract_text() or "").strip()
        except Exception:      # noqa: BLE001
            texto = ""
        img = _imagen(ruta, n, carpeta) if con_imagenes else None
        if img:
            imagenes.append(img)
        salida.append({"pagina": n, "texto": texto[:TEXTO_MAX], "texto_recortado": len(texto) > TEXTO_MAX,
                       "sin_texto": not texto, "imagen": img})
    nota = []
    if any(p["sin_texto"] for p in salida):
        nota.append("Hay páginas sin texto extraíble (dibujo vectorial o escaneo): para esas, mira la imagen.")
    if con_imagenes and not imagenes:
        nota.append("No se pudieron generar imágenes de las páginas (falta pypdfium2): solo hay texto.")
    if total > len(numeros):
        nota.append(f"El PDF tiene {total} páginas; se leyeron {len(numeros)}. Pide otras con paginas='7-9'.")
    return {"ok": True, "archivo": os.path.basename(ruta), "paginas_total": total, "paginas": salida,
            "imagenes_para_ver": imagenes, "nota": " ".join(nota)}
