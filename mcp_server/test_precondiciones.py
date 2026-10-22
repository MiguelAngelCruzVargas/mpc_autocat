"""Test de tools/precondiciones.py (el escáner de precondiciones de la API) con código descompilado de juguete.
NO necesita AutoCAD ni el descompilado real.

Uso:  python test_precondiciones.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import precondiciones as pre  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name + (f" -- {detalle}" if not ok and detalle else ""))


ELIPSE = """namespace Autodesk.AutoCAD.DatabaseServices;

public class Ellipse : Curve
{
\tpublic unsafe bool IsNull
\t{
\t\tget { return false; }
\t}

\tpublic unsafe Ellipse(Point3d center, Vector3d unitNormal, Vector3d majorAxis, double radiusRatio, double startAngle, double endAngle)
\t{
\t}

\tpublic unsafe Ellipse()
\t{
\t}

\tpublic unsafe void Set(Point3d center, Vector3d unitNormal, Vector3d majorAxis, double radiusRatio, double startAngle, double endAngle)
\t{
\t}
}
"""

VALIDADOR = """public sealed class PlotSettingsValidator : DisposableWrapper
{
\tpublic unsafe void RefreshLists(PlotSettings plotSet)
\t{
\t}

\tpublic unsafe StringCollection GetPlotDeviceList()
\t{
\t}
}
"""


def main() -> int:
    a = pre.analizar(ELIPSE)
    check("Ellipse: detecta IsNull", a["isnull"] is True)
    check("Ellipse: dos constructores (vacío y con datos)", len(a["ctors"]) == 2, str(a["ctors"]))
    check("Ellipse: Set es un método que modifica", any(n == "Set" for _, n, _ in a["metodos"]))
    v = pre.analizar(VALIDADOR)
    check("Validador: sin constructor público", v["ctors"] == [])
    muta = [(n, p) for _, n, p in v["metodos"] if pre.MUTA.match(n)]
    check("Validador: RefreshLists modifica un PlotSettings (argumento de la base)",
          any(n == "RefreshLists" and "PlotSettings" in p for n, p in muta), str(muta))
    check("Validador: GetPlotDeviceList no se marca como modificador", all(n != "GetPlotDeviceList" for n, _ in muta))
    check("Ellipse figura como comprobada que cierra AutoCAD", "CIERRA" in pre.CONOCIDO["Ellipse"])
    if FAILED:
        print("\nFALLARON:")
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
