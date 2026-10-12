"""Acabados del 3D sin AutoCAD: texturas, código generado y muebles.

Lo que salió al armarlo en AutoCAD: el forro de ladrillo tapaba la cochera
(vano abierto), sin piso se veía el pasto adentro, una caja por mueble se
leía como baúl y los planos 2D flotaban en el cielo de la vista.

Uso:  python test_acabados_3d.py
"""
from __future__ import annotations

import math
import os
import sys

import engine
import model3d_acabados as acab

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


ROOMS = [{"name": "COCHERA", "x0": 0.0, "y0": 0.0, "x1": 5.6, "y1": 6.0},
         {"name": "SALA", "x0": 5.6, "y0": 0.0, "x1": 12.0, "y1": 6.0}]
DOORS = [{"from": "EXTERIOR", "to": "COCHERA", "width": 5.0, "type": "pass", "open": True,
          "x": 2.8, "y": 0.0},
         {"from": "EXTERIOR", "to": "SALA", "width": 1.0, "x": 8.5, "y": 0.0},
         {"from": "COCHERA", "to": "SALA", "width": 0.9, "x": 5.6, "y": 3.0}]
WINS = [{"room": "SALA", "x": 10.5, "y": 0.0, "width": 1.5, "height": 1.2}]


def test_texturas() -> None:
    t = acab.texturas()
    check("texturas de muro, madera, sitio y pisos por uso",
          {"ladrillo", "madera", "pasto", "follaje", "piso", "duela", "porcelanato", "loseta",
           "azulejo", "concreto_pulido"} <= set(t), str(sorted(t)))
    ruta, ancho, alto = t["ladrillo"]
    check("ladrillo a escala real (dos hiladas de 7 cm)", (ancho, alto) == (0.50, 0.14),
          str((ancho, alto)))
    with open(ruta, "rb") as f:
        check("es un BMP", f.read(2) == b"BM")


def test_codigo_del_nivel() -> None:
    nivel = {"rooms": ROOMS, "doors": DOORS, "windows": WINS, "base_z": 0.0,
             "wall_height": 2.75, "slab_thickness": 0.15, "offset": 100.0,
             "furniture": [{"type": "dining_table", "x": 9.0, "y": 3.0, "rotation_deg": 0.0},
                           {"type": "sofa", "x": 6.0, "y": 0.5, "rotation_deg": 0.0}]}
    c = acab._codigo_nivel(nivel, 0.15, 0.12, 1.2, {})
    check("hay forro de ladrillo", "mLadrillo" in c)
    check("el vano abierto de la cochera se resta del forro (5.00 m)", "caja(5.0000" in c, c[:400])
    check("puerta de madera", "mMadera" in c)
    check("ventana con vidrio y marco", "mVidrio" in c and "mAluminio" in c)
    check("piso por uso: concreto pulido en cochera, porcelanato en sala",
          "mConcretoPulido" in c and "mPorcelanato" in c)
    check("muebles por piezas (mesa + sillas son muchas)", c.count("CAPA_MUEBLES") == 0
          and c.count("3D-MUEBLES") > 20, str(c.count("3D-MUEBLES")))
    check("corrido al offset", "100." in c or "10" in c)


def test_mueble_girado() -> None:
    # Una cama girada 90°: sus piezas quedan del lado correcto del ancla.
    linea = acab._mueble({"type": "bed", "x": 2.0, "y": 1.0, "rotation_deg": 90.0,
                          "width": 1.6, "length": 2.0}, 0.0, 0.0)
    check("cama con base, colchón, cobertor, cabecera y 2 almohadas", linea.count("poner(") == 6,
          str(linea.count("poner(")))
    # girada 90°, todo cae a la izquierda del ancla (x <= 2.0)
    import re
    xs = [float(m) for m in re.findall(r"caja\([^,]+, [^,]+, [^,]+, ([-\d.]+),", linea)]
    check("girada 90° queda a la izquierda del ancla", all(x <= 2.0 + 1e-6 for x in xs), str(xs))


def test_pisos_y_azulejo() -> None:
    check("duela en recámara", acab._piso_de("RECÁMARA PRINCIPAL") == "mDuela")
    check("loseta en baño y cocina", acab._piso_de("BAÑO 2") == "mLoseta"
          and acab._piso_de("COCINA") == "mLoseta")
    check("lo demás porcelanato", acab._piso_de("SALA-COMEDOR") == "mPorcelanato")
    check("floors del nivel manda", acab._piso_de("SALA", {"SALA": "duela"}) == "mDuela")
    rooms = ROOMS + [{"name": "BAÑO", "x0": 0.0, "y0": 6.0, "x1": 2.0, "y1": 8.0}]
    nivel = {"rooms": rooms, "doors": DOORS + [{"from": "COCHERA", "to": "BAÑO", "width": 0.7,
                                                 "x": 1.0, "y": 6.0}],
             "windows": WINS, "base_z": 0.0, "wall_height": 2.75, "slab_thickness": 0.15,
             "offset": 0.0}
    c = acab._codigo_nivel(nivel, 0.15, 0.12, 1.2, {})
    check("azulejo en el baño hasta 2.10 con la puerta restada",
          "mAzulejo" in c and ", 2.100);" in c, c[-600:])


def test_barandal_completo() -> None:
    # Rampa de 9 peraltes de 0.17 y huella 0.27, barandal sobre x: cada
    # barrote y poste nace en su escalón y muere EN el pasamanos.
    import re
    r, t, n = 0.17, 0.27, 9
    run = (n - 2) * t

    def escalon(d):
        return (min(int((d + 0.03) // t), n - 2) + 1) * r
    lineas = acab._barandal(0.03, 0.0, run + 0.03, 0.0, r, (n - 1) * r, escalon)
    verticales = [tuple(float(v) for v in m) for m in re.findall(
        r"caja\(([\d.]+), [\d.]+, ([\d.]+), ([-\d.]+), [-\d.]+, ([-\d.]+), ", "\n".join(lineas))]
    malos = []
    verticales = [v for v in verticales if v[0] < 0.05]      # sin los codos
    for lado, alto, x, cz in verticales:
        d = x - 0.03
        riel = r + acab.BARANDAL_ALTO + ((n - 1) * r - r) / run * d
        if abs(cz + alto / 2 - riel) > 0.002 or abs(cz - alto / 2 - escalon(d)) > 0.002:
            malos.append((x, cz - alto / 2, cz + alto / 2, round(riel, 3)))
    check("barrotes y postes del escalón al pasamanos, sin quedar cortos ni pasados",
          verticales and not malos, str(malos[:3]))
    xs = sorted(v[2] for v in verticales)
    claros = [b_ - a_ - 0.016 for a_, b_ in zip(xs, xs[1:])]
    check("claro entre barrotes <= 10 cm", max(claros) <= acab.BARROTE_CLARO + 0.012,
          str(round(max(claros), 3)))
    check("pasamanos inclinado", any("barra(" in l for l in lineas))
    # Escalera en U: el pasamanos sigue de una rampa a la otra por el
    # descanso (antes se cortaba ahí). Tres pasamanos: rampa, unión, rampa,
    # y la unión arranca donde termina la primera.
    esc = {"flights": [{"start": [10.06, 1.3], "direction_deg": 90, "width": 1.2, "risers": 8,
                        "riser": r, "tread": t, "base_z": 0.0, "railing": "right"},
                       {"start": [11.325, 3.19], "direction_deg": 270, "width": 1.2, "risers": 9,
                        "riser": r, "tread": t, "base_z": 8 * r, "railing": "right"}]}
    c = acab._codigo_escalera(esc, 0.0)
    rieles = re.findall(r"barra\(([\d.]+), 0\.05, 0\.04, ([-\d.]+), ([-\d.]+), ([-\d.]+), "
                        r"([-\d.]+), ([-\d.]+)\)", c)
    check("pasamanos continuo en el descanso (rampa + unión + rampa)", len(rieles) == 3, str(len(rieles)))
    if len(rieles) == 3:
        def extremos(m):
            L, pitch, yaw, cx, cy, cz = (float(v) for v in m)
            h = L / 2
            ex, ey, ez = math.cos(pitch) * math.cos(yaw) * h, math.cos(pitch) * math.sin(yaw) * h, \
                math.sin(pitch) * h
            return (cx - ex, cy - ey, cz - ez), (cx + ex, cy + ey, cz + ez)
        _a1, fin1 = extremos(rieles[0])
        ini_u, fin_u = extremos(rieles[2])
        ini2, _b2 = extremos(rieles[1])
        check("la unión empalma con las dos rampas",
              math.dist(fin1, ini_u) < 0.01 and math.dist(fin_u, ini2) < 0.01,
              str((fin1, ini_u, fin_u, ini2)))
        # El barandal de planta alta, pedido a 4 cm del final del pasamanos,
        # se pega a él (antes quedaba el tubo cortado al llegar arriba).
        esc["guards"] = [{"from": [9.46, 1.03], "to": [10.725, 1.03], "z": 17 * r}]
        c = acab._codigo_escalera(esc, 0.0)
        rieles = re.findall(r"barra\(([\d.]+), 0\.05, 0\.04, ([-\d.]+), ([-\d.]+), ([-\d.]+), "
                            r"([-\d.]+), ([-\d.]+)\)", c)
        _a2, fin2 = extremos(rieles[1])
        g0, g1 = extremos(rieles[3])
        check("el barandal de arriba empalma con el pasamanos",
              min(math.dist(fin2, g0), math.dist(fin2, g1)) < 0.01, str((fin2, g0, g1)))
        codos = re.findall(r"caja\(0\.06, 0\.06, 0\.06, ([-\d.]+), ([-\d.]+), ([-\d.]+),", c)
        check("un codo por unión, sin repetidos (5 extremos: 2 arranques/llegadas + 3 uniones)",
              len(codos) == len(set(codos)) == 5, str(len(codos)))


def test_vista_aisla_el_2d(monkeypatch=None) -> None:
    capturado = {}

    def falso(code, description="", **k):
        capturado["code"] = code
        return {"compiled": True, "executed": True}
    original = engine.run_code
    engine.run_code = falso
    try:
        r = acab.set_3d_view([0, -10, 1.6], [0, 0, 1.6], lens=20, roof_visible=True)
    finally:
        engine.run_code = original
    c = capturado["code"]
    check("vista ok", r["ok"], str(r))
    check("perspectiva", "PerspectiveEnabled = true" in c)
    check("aísla el 3D (apaga lo que no es 3D-)", 'StartsWith("3D-")' in c)
    check("la cámara queda 10 m atrás del objetivo", "new Vector3d(0.0000, -10.0000, 0.0000)" in c,
          c[:300])
    try:
        acab.set_3d_view([1, 1, 1], [1, 1, 1])
        check("cámara = objetivo falla", False)
    except ValueError:
        check("cámara = objetivo falla", True)


def test_detalle_completo() -> None:
    # Todo el detalle de la etapa A en el código que se manda a AutoCAD.
    capturado = {}

    def falso(code, description="", **k):
        capturado["code"] = code
        return {"compiled": True, "executed": True, "output": "@@PIEZAS|300"}
    original = engine.run_code
    engine.run_code = falso
    try:
        nivel = {"rooms": ROOMS, "doors": DOORS, "windows": WINS, "base_z": 0.0,
                 "wall_height": 2.75, "slab_thickness": 0.15, "offset": 0.0, "facade": "aplanado"}
        esc = {"flights": [{"start": [10.0, 1.3], "direction_deg": 90, "width": 1.2, "risers": 8,
                            "riser": 0.17, "tread": 0.27, "base_z": 0.0, "railing": "right"}],
               "landings": [{"box": [9.4, 3.2, 11.9, 4.4], "z": 1.36}],
               "openings": [{"box": [9.4, 1.0, 11.9, 4.4], "z0": 2.6, "z1": 3.0}],
               "guards": [{"from": [9.4, 1.0], "to": [10.6, 1.0], "z": 2.9}]}
        r = acab.dress_3d_model([nivel], stairs=[esc], tank={"point": [2.0, 3.0]},
                                terraces=[{"box": [3.6, 6.0, 12.0, 9.0]}],
                                lot=[[0, 0], [12, 0], [12, 25], [0, 25]],
                                paving=[{"box": [0, 6, 3.6, 8]}],
                                cladding=[{"from": [5.6, 0], "to": [7.6, 0], "z0": 0.3, "z1": 2.7,
                                           "side": "right"}],
                                canopies=[{"box": [7.8, -1.2, 9.4, 0.0], "z": 2.4}],
                                hedges=[{"from": [0.5, 24], "to": [11.5, 24]}])
    finally:
        engine.run_code = original
    c = capturado["code"]
    check("ok y cuenta piezas", r["ok"] and r["pieces"] == 300, str(r))
    check("fachada de aplanado en ese nivel", "mFachada); n++; }" in c)
    check("pretil con remate (anillo)", c.count("anillo(") >= 2)
    check("tinaco", "mTinaco" in c)
    check("escalera: escalones, huella de madera y barandal", c.count("3D-ESCALERA") > 15)
    check("hueco de escalera en losa y piso", "perforar(" in c)
    check("losa de entrepiso deja de ser cubierta", 'e.Layer = "3D-LOSA"' in c)
    check("calle de asfalto y banqueta con el lote", "mAsfalto" in c and "mBanqueta" in c)
    check("barda en 3 lados (no al frente)", c.count("mRepison); n++;") >= 3)
    check("lambrín de duelas", c.count("mMadera); n++;") >= 15)
    check("informa los materiales que usó de verdad",
          "Porcelanato claro" in r["materials"] and "Asfalto" in r["materials"]
          and "Espejo" not in r["materials"], str(r["materials"]))
    check("marquesina", "2.4600, 0)" in c, "")
    check("seto en dos verdes", "mSeto" in c and "mFollaje2" in c)
    check("árbol de varias copas", c.count("mFollaje") >= 3)
    import re
    # Árbol de banqueta a 75 cm de la fachada: la copa no entra en la casa.
    capturado.clear()
    engine.run_code = falso
    try:
        acab.dress_3d_model([nivel], trees=[[6.0, -0.75]])
    finally:
        engine.run_code = original
    esferas = [(float(rr), float(yy)) for rr, yy in re.findall(
        r"CreateSphere\(([\d.]+)\); c\.TransformBy\(Matrix3d\.Displacement\(new Vector3d\([-\d.]+, "
        r"([-\d.]+),", capturado["code"])]
    check("la copa del árbol de banqueta no atraviesa la fachada",
          esferas and all(yy + rr < 0.0 for rr, yy in esferas), str(esferas))
    vigas = [float(m) for m in re.findall(r"poner\(caja\(0\.05, ([\d.]+), 0\.15", c)]
    check("vigas de pérgola sin entrar a la casa", vigas and all(v < 3.4 for v in vigas), str(vigas[:3]))


def main() -> int:
    for t in (test_texturas, test_codigo_del_nivel, test_pisos_y_azulejo, test_barandal_completo,
              test_mueble_girado,
              test_vista_aisla_el_2d,
              test_detalle_completo):
        print(t.__name__)
        t()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" - " + f)
        return 1
    print("\nOK: acabados del 3D.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
