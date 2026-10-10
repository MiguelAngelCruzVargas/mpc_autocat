"""La carpeta de entrega sin AutoCAD: subcarpetas por tipo, nada borrado,
juego en un solo PDF y en el orden de las disciplinas."""
from __future__ import annotations

import os
import sys
import tempfile

import entregables as ent

FALLAS: list[str] = []


def check(nombre: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FALLAS.append(f"{nombre}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + nombre + (f" -- {detalle}" if not ok else ""))


def pdf_vacio(ruta: str) -> None:
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=200, height=100)
    with open(ruta, "wb") as fh:
        w.write(fh)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        origen = os.path.join(tmp, "pruebas")
        os.makedirs(origen)
        nombres = ["casa_IE-01.pdf", "casa_A-02.pdf", "casa_E-01.pdf", "casa_A-01.pdf", "casa_C-01.pdf"]
        archivos = []
        for n in nombres:
            pdf_vacio(os.path.join(origen, n))
            archivos.append(os.path.join(origen, n))
        for n in ("casa.dwg", "casa.bak", "casa_catalogo.xlsx"):
            open(os.path.join(origen, n), "wb").write(b"x")
            archivos.append(os.path.join(origen, n))
        r = ent.package_deliverables('CASA "LA LOMA": 2 NIVELES.', tmp, archivos)
        carpeta = r["folder"]
        check("carpeta con el nombre del proyecto (sin caracteres inválidos)",
              os.path.basename(carpeta) == "CASA LA LOMA 2 NIVELES", carpeta)
        check("DWG y .bak en DWG/", sorted(os.listdir(os.path.join(carpeta, "DWG"))) == ["casa.bak", "casa.dwg"])
        check("PDF individuales en PDF/ (los 5, ninguno borrado)",
              len(os.listdir(os.path.join(carpeta, "PDF"))) == 5)
        check("Excel en XLSX/", os.listdir(os.path.join(carpeta, "XLSX")) == ["casa_catalogo.xlsx"])
        check("juego completo en un solo PDF", os.path.isfile(r["combinedPdf"]) and r["pages"] == 5)
        check("orden por disciplina: A-01, A-02, E-01, IE-01, C-01",
              r["sheetsInOrder"] == ["casa_A-01.pdf", "casa_A-02.pdf", "casa_E-01.pdf",
                                     "casa_IE-01.pdf", "casa_C-01.pdf"], str(r["sheetsInOrder"]))
        from pypdf import PdfReader
        check("el PDF unido tiene una página por lámina", len(PdfReader(r["combinedPdf"]).pages) == 5)
        # Volver a entregar no pisa nada.
        pdf_vacio(os.path.join(origen, "casa_A-01.pdf"))
        r2 = ent.package_deliverables('CASA "LA LOMA": 2 NIVELES.', tmp,
                                      [os.path.join(origen, "casa_A-01.pdf")])
        check("si ya existe, no se pisa y se avisa",
              any("no se pisó" in w for w in r2.get("warnings", []))
              and os.path.isfile(os.path.join(origen, "casa_A-01.pdf")))
    if FALLAS:
        print(f"\n{len(FALLAS)} FALLAS")
        return 1
    print("\nOK: entrega en carpeta del proyecto, por tipo, sin borrar nada y con el juego unido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
