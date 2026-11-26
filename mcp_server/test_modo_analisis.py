"""Tests del modo análisis: read_pdf (texto e imagen por página), consultar_norma (solo citas respaldadas, con su
estatus), la especialidad «analisis» (solo herramientas que no cambian el dibujo) y su texto de sistema.
Sin AutoCAD.

Uso:  python test_modo_analisis.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.insert(0, os.path.dirname(AQUI))

import normas_base  # noqa: E402
import pdf_lector  # noqa: E402

FAILED: list[str] = []


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    if not condicion:
        FAILED.append(nombre + (f" -- {detalle}" if detalle else ""))
    print(("  ok  " if condicion else " FALLA ") + nombre)


def pdf_de_prueba(paginas: list[str]) -> str:
    """Un PDF mínimo con una línea de texto por página (sin librerías: el formato a mano)."""
    objetos = ["<< /Type /Catalog /Pages 2 0 R >>", None,
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for texto in paginas:
        flujo = f"BT /F1 18 Tf 72 720 Td ({texto}) Tj ET 72 100 m 500 100 l S".encode("latin-1")
        objetos.append(f"<< /Length {len(flujo)} >>\nstream\n" + flujo.decode("latin-1") + "\nendstream")
        objetos.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {len(objetos)} 0 R "
                       f"/Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(f"{len(objetos)} 0 R")
    objetos[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    salida, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objetos, start=1):
        offsets.append(len(salida))
        salida += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    salida += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    ruta = os.path.join(tempfile.mkdtemp(), "plano.pdf")
    with open(ruta, "wb") as fh:
        fh.write(salida)
    return ruta


def test_read_pdf():
    print("read_pdf")
    ruta = pdf_de_prueba(["PLANTA BAJA ESC 1:100", "INSTALACION ELECTRICA", "CORTE A-A"])
    r = pdf_lector.leer(ruta)
    check("abre el PDF", r["ok"], str(r))
    check("cuenta las páginas", r["paginas_total"] == 3)
    check("lee el texto de cada página", "PLANTA BAJA" in r["paginas"][0]["texto"] and "CORTE" in r["paginas"][2]["texto"])
    check("una imagen por página para el modelo con visión", len(r["imagenes_para_ver"]) == 3
          and all(os.path.isfile(p) for p in r["imagenes_para_ver"]))
    from PIL import Image
    with Image.open(r["imagenes_para_ver"][0]) as img:
        check("reducida al tamaño que aprovechan los modelos", max(img.size) <= pdf_lector.LADO_MAX, str(img.size))
    solo = pdf_lector.leer(ruta, "2")
    check("páginas pedidas", [p["pagina"] for p in solo["paginas"]] == [2] and "ELECTRICA" in solo["paginas"][0]["texto"])
    check("sin imágenes si no se piden", pdf_lector.leer(ruta, "1", False)["imagenes_para_ver"] == [])
    check("no existe: error claro", not pdf_lector.leer(ruta + "x")["ok"])
    check("un dwg: dice qué usar", "open_document" in pdf_lector.leer(__file__)["error"])
    check("páginas inválidas", not pdf_lector.leer(ruta, "a-b")["ok"])
    largo = pdf_de_prueba([f"LAMINA {i}" for i in range(1, 10)])
    r9 = pdf_lector.leer(largo)
    check("como mucho 6 páginas por llamada y lo dice", len(r9["paginas"]) == pdf_lector.MAX_PAGINAS and "9 páginas" in r9["nota"])


def test_consultar_norma():
    print("consultar_norma")
    r = normas_base.consultar("eléctrica", "contactos cocina")
    check("encuentra la regla de la cocina", any(e["articulo"] == "210-52(c)(1)" for e in r["encontradas"]))
    check("cada entrada con fuente, artículo y estatus",
          all(e["fuente"] and e["articulo"] and e["estatus"] in ("norma", "práctica", "sin verificar") for e in normas_base.ENTRADAS))
    check("dice cómo citar y que manda el reglamento local", "NO cites" in r["como_citar"] and "municipio" in r["aviso"])
    arq = normas_base.consultar("arquitectura", "recámara")
    check("los mínimos de recintos salen como «sin verificar», sin artículo inventado",
          arq["encontradas"] and all(e["estatus"] == "sin verificar" and "sin artículo cargado" in e["articulo"] for e in arq["encontradas"]))
    import instalaciones
    pend = normas_base.consultar("sanitaria", "pendiente")["encontradas"][0]
    check("los valores salen de las mismas constantes que usan las tools",
          f"{instalaciones.NORMA['pendiente_drenaje'] * 100:.0f} %" in pend["regla"])
    check("sin coincidencias: lista vacía (para decir «no lo tengo»)", normas_base.consultar("", "elevador montacargas")["count"] == 0)
    check("acentos no importan", normas_base.consultar("electrica", "LAVABO")["count"] >= 1)


def test_especialidad_analisis():
    print("especialidad «analisis»")
    from agent import cli, permisos
    import categorias
    incluir = cli.PERFILES["analisis"]
    check("existe", bool(incluir))
    check("trae read_pdf y consultar_norma", "read_pdf" in incluir and "consultar_norma" in incluir)
    patrones_que_cambian = [p for p in incluir if p not in ("open_document", "list_documents")
                            and not permisos.SOLO_LECTURA.match(p.rstrip("_") + ("_x" if p.endswith("_") else ""))]
    check("todo lo demás es de solo lectura", not patrones_que_cambian, str(patrones_que_cambian))
    check("read_pdf y consultar_norma cuentan como solo lectura",
          permisos.SOLO_LECTURA.match("read_pdf") and permisos.SOLO_LECTURA.match("consultar_norma"))
    check("tienen categoría", categorias.categoria_de("read_pdf") and categorias.categoria_de("consultar_norma"))
    texto = cli._system_prompt(False, 0, "analisis")
    check("el texto de sistema empieza por el modo análisis", texto.startswith("=== MODO ANÁLISIS ==="))
    for frase in ("NO LE DES LA RAZÓN", "consultar_norma", "NUNCA cites un artículo de memoria", "NO MODIFIQUES NADA",
                  "¿lo aplico?", "read_only=True", "PDF: <ruta>"):
        check("pide: " + frase, frase in texto)
    check("las demás especialidades no cambian", "MODO ANÁLISIS" not in cli._system_prompt(False, 0, "arquitectura"))


def test_tools_registradas():
    print("tools en el servidor MCP")
    with open(os.path.join(AQUI, "server.py"), encoding="utf-8") as fh:
        fuente = fh.read()
    for nombre in ("read_pdf", "consultar_norma"):
        check(nombre + " registrada", re.search(r"@mcp\.tool\(\)\s*\ndef " + nombre + r"\(", fuente) is not None)


if __name__ == "__main__":
    for prueba in (test_read_pdf, test_consultar_norma, test_especialidad_analisis, test_tools_registradas):
        prueba()
    print()
    if FAILED:
        print("FALLARON %d:" % len(FAILED))
        for f in FAILED:
            print("  - " + f)
        sys.exit(1)
    print("Todo bien.")
