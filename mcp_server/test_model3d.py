"""Tests de create_3d_model sin AutoCAD: el C# generado y el armado del
resultado, con engine.run_code reemplazado por uno falso.

Los volúmenes esperados son analíticos: la mampostería es el área de la
planta por el alto menos cada vano, y si un vano no se restara en AutoCAD
el volumen medido no cerraría y la tool lo tiene que decir.

Que el C# compile contra la API real de AutoCAD se verificó aparte con
dotnet (C# 5, net48 y net8, ensamblados de AutoCAD por NuGet).

Uso:  python test_model3d.py
"""
from __future__ import annotations

import re
import sys
import types

import preview

preview.install()

import model3d  # noqa: E402
import rules    # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def cerca(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


# Dos ambientes de 4x4: puerta de acceso en la fachada y una interior.
ROOMS = [{"name": "SALA", "x0": 0, "y0": 0, "x1": 4, "y1": 4},
         {"name": "RECAMARA", "x0": 4, "y0": 0, "x1": 8, "y1": 4}]
DOORS = [{"from": "EXTERIOR", "to": "SALA", "width": 0.9, "x": 2, "y": 0},
         {"from": "SALA", "to": "RECAMARA", "width": 0.8, "x": 4, "y": 2}]
AREA_PLANTA = 8.15 * 4.15 - 2 * 3.875 * 3.85


class MotorFalso:
    """Hace de engine.run_code: guarda el código y contesta lo que se le
    pida."""

    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.codigos: list[str] = []

    def run_code(self, code, description="", compile_only=False, force=False):
        self.codigos.append(code)
        return self.respuesta(code) if callable(self.respuesta) else self.respuesta


def con_motor(respuesta) -> MotorFalso:
    motor = MotorFalso(respuesta)
    modulo = types.ModuleType("engine")
    modulo.run_code = motor.run_code
    sys.modules["engine"] = modulo
    return motor


def salida_exacta(datos):
    """Lo que imprimiría AutoCAD si los volúmenes dan lo esperado."""
    def responder(code):
        return {"compiled": True, "result": 1, "errors": [], "blocked": None,
                "exception": None, "aborted": False, "created": [],
                "output": "@@MURO|A1|%r\n@@LOSA|B2|%r\n@@VISTA|iso SO\n" % (
                    datos["expectedMasonryVolume"],
                    datos["expectedSlabVolume"])}
    return responder


def test_volumenes_esperados() -> None:
    d = model3d.build(ROOMS, DOORS)
    vanos = 0.9 * 0.15 * 2.10 + 0.8 * 0.10 * 2.10
    check("mamposteria = area de planta x alto - vanos",
          cerca(d["expectedMasonryVolume"], AREA_PLANTA * 2.5 - vanos),
          str(d["expectedMasonryVolume"]))
    check("losa = paño exterior x espesor",
          cerca(d["expectedSlabVolume"], 8.15 * 4.15 * 0.12),
          str(d["expectedSlabVolume"]))
    check("dos vanos", d["openings"] == 2, str(d["openings"]))


def test_el_patio_no_se_techa() -> None:
    rooms = ROOMS + [{"name": "PATIO DE SERVICIO", "x0": 0, "y0": 4,
                      "x1": 8, "y1": 7}]
    d = model3d.build(rooms, DOORS)
    check("la losa no cubre el patio",
          cerca(d["expectedSlabVolume"], 8.15 * 4.15 * 0.12),
          str(d["expectedSlabVolume"]))


def test_ventanas_entre_antepecho_y_cabezal() -> None:
    # Puerta corrida a un lado: deja paño para la ventana con sus macizos.
    doors = [dict(DOORS[0], x=1.0), DOORS[1]]
    d = model3d.build(ROOMS, doors, [{"room": "SALA", "wall": "fachada"}],
                      sill_height=1.0, window_head=2.2)
    check("la ventana se ubico", len(d["plan"]["windowsPlaced"]) == 1,
          str(d["warnings"]))
    cajas = re.findall(r"CreateBox\(([^)]*)\)", d["code"])
    altos = sorted(round(float(c.split(",")[2].strip().rstrip("d")), 6)
                   for c in cajas)
    check("la ventana mide de 1.00 a 2.20 (1.20 de alto)", 1.2 in altos,
          str(altos))


def test_corrido_al_costado_de_la_planta() -> None:
    d = model3d.build(ROOMS, DOORS)
    check("offset por default = 1.5 x ancho", d["offset"] == [12.0, 0.0],
          str(d["offset"]))
    xs = [float(x) for x in re.findall(r"new double\[\] \{ (-?[\d.e-]+)d",
                                        d["code"])]
    check("ningun contorno queda sobre la planta 2D",
          xs and min(xs) >= 12.0 - 0.075 - 1e-9, str(min(xs) if xs else None))


def test_codigo_dentro_de_lo_que_el_filtro_deja() -> None:
    p = rules.suggest_layout(8.0, 20.0, bedrooms=3, bathrooms=2)
    code = model3d.build(p["rooms"], p["doors"], p["windows"])["code"]
    prohibidos = ("System.IO", "System.Net", "Process", "Registry",
                  "Reflection", "SendStringToExecute", ".Command(",
                  "DllImport", "Environment")
    check("no usa APIs que el filtro bloquea",
          not [x for x in prohibidos if x in code],
          str([x for x in prohibidos if x in code]))
    check("sintaxis de C# 5 (sin interpolacion $\"...\")",
          '$"' not in code)
    check("numeros con punto decimal, nunca coma",
          not re.search(r"\d,\d", code.replace(", ", ";")), "")
    check("capas 3D propias (la cubierta en la suya)",
          '"3D-MUROS"' in code and '"3D-LOSA_CUBIERTA"' in code)
    # Regla del usuario: el 3D se mira sin techo. La cubierta se modela
    # (remata los muros) pero su capa queda apagada.
    check("la cubierta queda apagada por default", ".IsOff = true" in code)
    visible = model3d.build(p["rooms"], p["doors"], p["windows"],
                            roof_visible=True)["code"]
    check("con roof_visible=True no se apaga", ".IsOff = true" not in visible)


def test_resultado_con_motor() -> None:
    d = model3d.build(ROOMS, DOORS)
    motor = con_motor(salida_exacta(d))
    r = model3d.create_3d_model(ROOMS, DOORS)
    check("ok con el motor andando", r.get("ok"), str(r))
    check("handles por categoria",
          r.get("wallHandles") == ["A1"] and r.get("slabHandles") == ["B2"],
          str(r))
    check("volumen medido igual al esperado: sin avisos",
          not r.get("warnings"), str(r.get("warnings")))
    check("vista iso", r.get("view") == "iso SO", str(r.get("view")))
    check("el codigo enviado es el generado", motor.codigos == [d["code"]])


def test_avisa_si_un_vano_no_se_resto() -> None:
    d = model3d.build(ROOMS, DOORS)
    con_motor({"compiled": True, "errors": [], "exception": None,
               "aborted": False, "blocked": None, "created": [],
               "output": "@@MURO|A1|%r\n@@AVISO|vano 2 (door) en (12.00, 2.00): "
                         "no se pudo restar de ningun muro\n"
                         % (d["expectedMasonryVolume"] + 0.168)})
    r = model3d.create_3d_model(ROOMS, DOORS, slab=False)
    avisos = " ".join(r.get("warnings", []))
    check("pasa el aviso del C#", "no se pudo restar" in avisos, avisos)
    check("y el volumen que no cierra", "no coincide" in avisos, avisos)


def test_motor_apagado() -> None:
    con_motor({"compiled": False, "disabled": True,
               "message": "run_code está apagado: activalo con "
                          "tools/run_code_acceso.py activar"})
    r = model3d.create_3d_model(ROOMS, DOORS)
    check("motor apagado: ok=False con el motivo",
          r.get("ok") is False and "apagado" in str(r.get("error")), str(r))
    check("y no inventa handles", "wallHandles" not in r, str(r))


def test_plantilla_que_no_compila() -> None:
    con_motor({"compiled": False, "errors": [{"line": 3, "column": 1,
                                              "message": "CS0103"}]})
    r = model3d.create_3d_model(ROOMS, DOORS)
    check("error de compilacion: devuelve el codigo para verlo",
          r.get("ok") is False and "code" in r, str(r)[:200])


def test_sin_vista() -> None:
    motor = con_motor(salida_exacta(model3d.build(ROOMS, DOORS)))
    model3d.create_3d_model(ROOMS, DOORS, view=False)
    check("view=False no toca la vista",
          "SetCurrentView" not in motor.codigos[0]
          and motor.codigos[0].rstrip().endswith("return muros.Count;"))


def test_errores_claros() -> None:
    for kw, frag in (({"door_height": 2.8}, "door_height"),
                     ({"sill_height": 2.2, "window_head": 2.1}, "antepecho"),
                     ({"wall_height": 0}, "wall_height"),
                     ({"slab_thickness": 0}, "slab_thickness")):
        try:
            model3d.build(ROOMS, DOORS, **kw)
            check(f"error claro ({frag})", False, "no fallo")
        except ValueError as exc:
            check(f"error claro ({frag})", frag in str(exc), str(exc))


def main() -> int:
    for t in (test_volumenes_esperados,
              test_el_patio_no_se_techa,
              test_ventanas_entre_antepecho_y_cabezal,
              test_corrido_al_costado_de_la_planta,
              test_codigo_dentro_de_lo_que_el_filtro_deja,
              test_resultado_con_motor,
              test_avisa_si_un_vano_no_se_resto,
              test_motor_apagado,
              test_plantilla_que_no_compila,
              test_sin_vista,
              test_errores_claros):
        print(t.__name__)
        t()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" - " + f)
        return 1
    print("\nOK: la planta se levanta en 3D con los volumenes que mide.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
