"""El examen de edificio sin AutoCAD: que apruebe un proyecto que cumple y
que repruebe —con la regla y la fuente correctas— cada error típico."""
from __future__ import annotations

import copy
import sys

import examen_edificio as ex

FALLAS: list[str] = []


def check(nombre: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FALLAS.append(f"{nombre}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + nombre + (f" -- {detalle}" if not ok else ""))


def depto() -> dict:
    rooms = [
        {"name": "SALA-COMEDOR", "x0": 0, "y0": 0, "x1": 5.0, "y1": 4.0},
        {"name": "COCINA", "x0": 0, "y0": 4.0, "x1": 2.8, "y1": 7.4},
        {"name": "RECÁMARA PRINCIPAL", "x0": 5.0, "y0": 0, "x1": 8.6, "y1": 4.0},
        {"name": "RECÁMARA 2", "x0": 8.6, "y0": 0, "x1": 12.0, "y1": 4.0},
        {"name": "PASILLO", "x0": 2.8, "y0": 4.0, "x1": 12.0, "y1": 5.2},
        {"name": "BAÑO", "x0": 5.0, "y0": 5.2, "x1": 7.6, "y1": 7.4},
        {"name": "CIRCULACIÓN COMÚN", "x0": 2.8, "y0": 7.4, "x1": 4.6, "y1": 10.6},
    ]
    doors = [
        {"from": "CIRCULACIÓN COMÚN", "to": "PASILLO", "width": 0.9, "x": 3.7, "y": 7.4},
        {"from": "COCINA", "to": "SALA-COMEDOR", "width": 1.8, "open": True, "type": "pass",
         "x": 1.4, "y": 4.0},
        {"from": "PASILLO", "to": "RECÁMARA PRINCIPAL", "width": 0.9, "x": 6.8, "y": 4.0},
        {"from": "PASILLO", "to": "RECÁMARA 2", "width": 0.9, "x": 10.3, "y": 4.0},
        {"from": "PASILLO", "to": "BAÑO", "width": 0.8, "x": 6.3, "y": 5.2},
    ]
    windows = [
        {"room": "SALA-COMEDOR", "wall": "fachada", "width": 3.6, "height": 1.5},
        {"room": "RECÁMARA PRINCIPAL", "wall": "fachada", "width": 1.8, "height": 1.5},
        {"room": "RECÁMARA 2", "wall": "fachada", "width": 1.8, "height": 1.5},
        {"room": "BAÑO", "wall": "patio", "width": 1.0, "height": 0.9},
    ]
    return {"name": "N1", "floor_to_floor": 2.80, "slab": 0.12,
            "rooms": rooms, "doors": doors, "windows": windows}


def proyecto() -> dict:
    return {
        "lot": [12.0, 27.0], "levels": [depto()], "levels_total": [1, 2, 3, 4],
        "height": 11.35, "dwellings": 7, "parking": 3, "parking_size": [5.0, 2.5],
        "stair": {"riser": 0.175, "tread": 0.28, "width": 1.10, "landing": 1.24,
                  "rise_per_flight": 1.40},
        "patios": [{"name": "PATIO POSTERIOR", "min_side": 4.0, "wall_height": 11.5,
                    "serves": "habitable"},
                   {"name": "PATIO DE LUZ", "min_side": 3.2, "wall_height": 11.5,
                    "serves": "complementario"}],
        "structure": {"fc": 250, "fy": 4200, "seismic_zone": "II",
                      "seismic_coefficient": 0.32, "soil_study": True},
        "equipment": ["calentador solar"],
    }


def reglas(r: dict) -> set:
    return {f["rule"] for f in r["failures"]}


def main() -> int:
    print("proyecto que cumple")
    r = ex.revisar_proyecto(proyecto())
    check("aprueba el proyecto que cumple", r["ok"], str(r["failures"]))
    check("revisa de verdad (no 0 reglas)", r["checked"] >= 25, str(r["checked"]))

    print("cada error, con su regla")
    casos = []

    def caso(nombre, regla, mutar):
        p = proyecto()
        mutar(p)
        casos.append((nombre, regla, p))

    caso("puerta de recámara de 0.80", "puerta_ancho",
         lambda p: p["levels"][0]["doors"][2].update(width=0.8))
    caso("puerta de baño de 0.70", "puerta_ancho",
         lambda p: p["levels"][0]["doors"][4].update(width=0.7))
    caso("sala con ventana chica (2.4 x 1.2)", "iluminacion",
         lambda p: p["levels"][0]["windows"][0].update(width=2.4, height=1.2))
    caso("patio posterior de 2.00 m", "patio_iluminacion",
         lambda p: p["patios"][0].update(min_side=2.0))
    caso("peralte de 19 cm", "escalera_peralte", lambda p: p["stair"].update(riser=0.19))
    caso("descanso de 1.00 m", "escalera_descanso", lambda p: p["stair"].update(landing=1.0))
    caso("8 viviendas sin calentador solar", "calentador_solar",
         lambda p: p.update(equipment=[]))
    caso("f'c 200", "fc", lambda p: p["structure"].update(fc=200))
    caso("sin estudio de mecánica de suelos", "mecanica_de_suelos",
         lambda p: p["structure"].update(soil_study=False))
    caso("sin zona sísmica declarada", "sismo", lambda p: p["structure"].update(seismic_zone=None))
    caso("circulación común de 1.00", "circulacion_comun",
         lambda p: p["levels"][0]["rooms"][6].update(x1=3.8))
    caso("recámara de 2.10 de lado", "local_lado",
         lambda p: p["levels"][0]["rooms"][3].update(x1=10.7))
    caso("7 niveles sin elevador", "elevador",
         lambda p: p.update(levels_total=list(range(7))))
    caso("cocina cerrada sin ventana", "iluminacion",
         lambda p: p["levels"][0]["doors"][1].update(open=False, width=0.8))
    for nombre, regla, p in casos:
        r = ex.revisar_proyecto(p)
        check(f"reprueba: {nombre} -> {regla}", regla in reglas(r), str(sorted(reglas(r))))
        fuente = next((f["source"] for f in r["failures"] if f["rule"] == regla), "")
        check(f"  y cita la norma ({regla})", bool(fuente), fuente)

    print("juego de planos")
    vacio = ex.revisar_juego([], ["Model"])
    check("un dibujo vacío reprueba todo", not vacio["ok"] and not vacio["present"])
    completo = ["CROQUIS DE LOCALIZACIÓN", "PLANTA DE CONJUNTO", "P L A N T A   B A J A",
                "PLANTA TIPO", "PLANTA DE AZOTEA", "CORTE A-A'", "CORTE C-C' (ESCALERA)",
                "FACHADA PRINCIPAL", "CUADRO DE ÁREAS", "N", "PLANTA DE CIMENTACIÓN",
                "PLANTA ESTRUCTURAL DE ENTREPISO", "ZAPATA Z-1", "COLUMNA C-1", "TRABE T-1",
                "f'c = 250 kg/cm2", "fy = 4200 kg/cm2", "CARGA VIVA 190 kg/m2",
                "COEFICIENTE SÍSMICO c = 0.32", "INSTALACIÓN HIDRÁULICA", "ISOMÉTRICO",
                "CISTERNA", "TINACO", "CALENTADOR SOLAR", "INSTALACIÓN SANITARIA",
                "ALBAÑAL Ø150", "BAP Ø100", "INSTALACIÓN ELÉCTRICA", "CUADRO DE CARGAS",
                "DIAGRAMA UNIFILAR", "INSTALACIÓN DE GAS", "CUADRO DE VOLÚMENES DE OBRA",
                "DRO", "CÉDULA"]
    r = ex.revisar_juego(completo, ["A-01", "Model"])
    check("un juego completo aprueba", r["ok"], str([m["id"] for m in r["missing"]]))
    r = ex.revisar_juego([t for t in completo if "UNIFILAR" not in t and t != "INSTALACIÓN DE GAS"],
                        ["A-01"])
    check("dice exactamente qué falta", {m["id"] for m in r["missing"]} == {"ie_unifilar", "gas"},
          str([m["id"] for m in r["missing"]]))
    r = ex.revisar_juego(completo, ["Model"])
    check("sin láminas reprueba aunque esté todo dibujado",
          any(m["id"] == "laminas" for m in r["missing"]))

    if FALLAS:
        print(f"\n{len(FALLAS)} FALLAS")
        return 1
    print("\nOK: el examen aprueba lo que cumple y reprueba cada error con su norma.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
