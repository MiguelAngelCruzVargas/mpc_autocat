"""Portico con arco y barda: geometria, marco, zapata con contacto real, cantidades y mezclas.
No necesita AutoCAD."""
from __future__ import annotations

import math
import sys

import portico_arco as pa
import portico_cuadros as pc

FALLAS: list[str] = []


def ok(cond: bool, msg: str) -> None:
    print(("  ok    " if cond else "  FALLA ") + msg)
    if not cond:
        FALLAS.append(msg)


def test_geometria():
    g = pa.geometria_arco(5.0, 3.45, 4.20, 0.95, 0.5)
    ok(abs(g["f"] - 0.75) < 1e-9, "flecha = clave - arranque")
    # el intrados pasa por el arranque y por la clave
    ok(abs(pa.y_intrados(g, 2.5) - 3.45) < 0.01 and abs(pa.y_intrados(g, 0.0) - 4.20) < 0.01, "el intrados pasa por arranque y clave")
    ok(abs(pa.y_top(g, 0.0) - 5.92) < 1e-9 and pa.y_top(g, 3.3) <= pa.y_top(g, 0.0), "perfil de la cornisa medido de la foto")


def test_zapata_contacto():
    q1, c1 = pa.contacto(2.0, 2.0, 20.0, 0.0, 0.0)
    ok(abs(q1 - 5.0) < 0.05 and c1 > 0.99, "carga centrada: presion = N/A")
    q2, c2 = pa.contacto(2.0, 2.0, 20.0, 0.0, 6.0)          # e = 0.3 > B/6 = 0.33? no: 0.3 < 0.33
    ok(q2 > q1, "con momento la presion maxima sube")
    q3, c3 = pa.contacto(2.0, 2.0, 20.0, 0.0, 12.0)         # e = 0.6 > B/6: se levanta
    ok(c3 < 1.0 and q3 > q2, "fuera del tercio medio se pierde contacto (sin tension)")
    z = pa.tamano_zapata(5.0, [(3.0, 5.0)], 5.0, 1.2, 1.6, 0.4)
    ok(z["q_max"] <= 5.0 and z["contacto"] >= 0.9, "la zapata elegida cumple")
    ok(z["L"] >= z["B"], "el momento grande va fuera del plano: la zapata se alarga hacia alla")


def test_diseno():
    f = pa.design_fence(250, 5.0, 0.8, 1.6, total_h=2.80, wall_h=1.40, pilaster_h=3.15)
    d = pa.design_gate_portal(5.0, 3.45, 4.20, 250, 5.0, 1.2, 1.6, core_options=(0.45,),
                              extra_loads=[(f["cargas"]["N_t_m"] * f["spacing"], 0.68)])
    ok(d["zapata"]["ok"], "la zapata pasa todas sus revisiones")
    ok(d["pilastra"]["ratio"] <= 0.95, "pilastra P-M dentro del limite")
    ok(d["viga"]["zona_apoyos"]["stirrups"]["spacing"] < d["viga"]["zona_centro"]["stirrups"]["spacing"],
       "estribos mas juntos en apoyos que al centro")
    ok(f["cimentacion"]["ok"], "cimiento corrido de la barda pasa")
    for dato in ("allowable_bearing", "depth", "soil_unit_weight", "fc"):
        kw = dict(clear_span=5.0, spring_h=3.45, crown_h=4.2, fc=250, allowable_bearing=5.0, depth=1.2, soil_unit_weight=1.6)
        kw[dato] = 0
        try:
            pa.design_gate_portal(**kw)
            ok(False, f"sin {dato} tiene que rechazar")
        except ValueError:
            ok(True, f"sin {dato} rechaza (no lo inventa)")
    return d, f


def test_limite_de_zapata():
    """Roca a 1.50 m y solo 1.60 m perpendicular al muro: la zapata respeta el limite o dice por que no se puede."""
    f = pa.design_fence(250, 5.0, 0.8, 1.6, total_h=2.80, wall_h=1.40, pilaster_h=3.15)
    ex = [(f["cargas"]["N_t_m"] * f["spacing"], 0.68)]
    d = pa.design_gate_portal(5.0, 3.45, 4.20, 250, 19.0, 1.5, 1.6, core_options=(0.45,), extra_loads=ex, footing_max_L=1.60)
    z = d["zapata"]
    ok(z["L"] <= 1.60 + 1e-9 and z["ok"], "la zapata respeta L <= 1.60 y pasa todas sus revisiones (L=%.2f B=%.2f)" % (z["L"], z["B"]))
    libre = pa.design_gate_portal(5.0, 3.45, 4.20, 250, 19.0, 1.5, 1.6, core_options=(0.45,), extra_loads=ex)
    ok(libre["zapata"]["L"] >= z["L"], "sin limite la zapata no es mas corta que con limite")
    try:
        pa.design_gate_portal(5.0, 3.45, 4.20, 250, 19.0, 1.5, 1.6, core_options=(0.45,), extra_loads=ex, footing_max_L=1.0)
        ok(False, "con L <= 1.00 no hay zapata: tiene que decirlo")
    except ValueError as e:
        ok("anclar" in str(e), "con un limite imposible lo dice y sugiere anclar a la roca")


def test_cantidades_roca():
    """Sobre roca la excavacion es en el suelo que la cubre y se agrega la limpieza de la roca."""
    f = pa.design_fence(250, 5.0, 0.8, 1.6, total_h=2.80, wall_h=1.40, pilaster_h=3.15)
    ex = [(f["cargas"]["N_t_m"] * f["spacing"], 0.68)]
    d = pa.design_gate_portal(5.0, 3.45, 4.20, 250, 19.0, 1.5, 1.6, core_options=(0.45,), extra_loads=ex, footing_max_L=1.60)
    rr = {"trabe": {"arc_length_m": 5.2, "stirrups": 36, "bar_len_inf_m": 6.4, "bar_len_sup_m": 6.7},
          "pil1": {"height_m": 5.6, "bar_len_m": 6.0, "stirrupCount": 40},
          "pil2": {"height_m": 3.7, "pata_m": 0.3, "stirrupCount": 35}, "fronton_h": 0.8, "dala_len": 7.2}
    q = pc.cantidades(d, f, rr, 1.5, 0.8, bays=3, roca=True)
    c = [i["concept"] for i in q["items"]]
    ok(any("hasta la roca de apoyo" in x for x in c) and not any("arcilloso" in x for x in c), "la excavacion dice que llega a la roca")
    ok(any("Limpieza, lavado y nivelación de la roca" in x for x in c), "agrega la limpieza de la roca de apoyo")
    area = [i["qty"] for i in q["items"] if "Limpieza" in i["concept"]][0]
    ok(abs(area - 2 * d["zapata"]["B"] * d["zapata"]["L"]) < 0.01, "la limpieza mide el area de las 2 zapatas")
    q0 = pc.cantidades(d, f, rr, 1.5, 0.8, bays=3)
    ok(any("arcilloso" in i["concept"] for i in q0["items"]), "sin roca=True sigue como antes")


def test_cantidades_dado_y_liga():
    """Con dado en la zapata y liga a lo largo de la barda se cuentan el dado y la liga completa."""
    f = pa.design_fence(250, 5.0, 0.8, 1.6, total_h=2.80, wall_h=1.40, pilaster_h=3.15)
    ex = [(f["cargas"]["N_t_m"] * f["spacing"], 0.68)]
    d = pa.design_gate_portal(5.0, 3.45, 4.20, 250, 19.0, 1.5, 1.6, core_options=(0.45,), extra_loads=ex, footing_max_L=1.60)
    d["zapata"]["pedestal"], d["zapata"]["pedestal_height"] = [0.5, 0.5], 1.3
    d["liga"] = {"b": 0.20, "h": 0.40, "bars": {"count": 4, "bar": "#3"}, "stirrup": "#2", "stirrup_spacing": 0.20,
                 "a_lo_largo": True}
    rr = {"trabe": {"arc_length_m": 5.2, "stirrups": 36, "bar_len_inf_m": 6.4, "bar_len_sup_m": 6.7},
          "pil1": {"height_m": 6.1, "bar_len_m": 6.5, "stirrupCount": 46},
          "pil2": {"height_m": 3.7, "pata_m": 0.3, "stirrupCount": 35}, "fronton_h": 0.8, "dala_len": 7.2}
    q = pc.cantidades(d, f, rr, 1.5, 0.8, bays=3, roca=True)
    por = {i["concept"]: i for i in q["items"]}
    dado = [i for c, i in por.items() if "dados de las zapatas" in c and i["unit"] == "m³"]
    ok(dado and abs(dado[0]["qty"] - 2 * 0.5 * 0.5 * 1.3) < 0.01, "cuenta el concreto de los dos dados")
    liga = [i for c, i in por.items() if "trabe de liga TL-1" in c and i["unit"] == "m³"]
    ok(liga and liga[0]["qty"] > 0.20 * 0.40 * 15.0, "la liga mide el largo de toda la barda, no solo el claro del portón")
    ok(any("hasta la última pilastra" in c for c in por), "el concepto de la liga dice hasta donde llega")


def test_cantidades(d, f):
    rr = {"trabe": {"arc_length_m": 5.2, "stirrups": 36, "bar_len_inf_m": 6.4, "bar_len_sup_m": 6.7},
          "pil1": {"height_m": 5.3, "bar_len_m": 6.0, "stirrupCount": 40},
          "pil2": {"height_m": 3.7, "pata_m": 0.3, "stirrupCount": 35}, "fronton_h": 0.8, "dala_len": 7.2}
    q = pc.cantidades(d, f, rr, 1.2, 0.8, bays=3)
    m = q["materiales"]
    vol250 = sum(i["qty"] for i in q["items"] if "f'c = 250" in i["concept"] and i["unit"] == "m³")
    ok(abs(q["volumen_concreto_250"] - vol250) < 0.05, "el volumen de concreto de las mezclas = suma de los conceptos")
    ok(abs(m["cemento_kg"] - sum(x["cemento"] for x in q["mezclas"])) < 1e-6, "el cemento total = suma por mezcla")
    c250 = pc.MEZCLAS["concreto_250"]
    # volumen absoluto del concreto: 1 m³ cierra con cemento, agua, aire y agregados
    sol = c250["cemento"] / 3150.0 + c250["agua"] / 1000.0 + 0.02
    ok(sol < 0.40, "la dosificacion deja lugar para los agregados")
    ok(q["acero_total_kg"] > 0 and abs(sum(q["acero_kg"].values()) - q["acero_total_kg"]) < 1.0, "acero total = suma por diametro")
    ok(q["materiales"]["bultos_50kg"] * 50 == m["cemento_kg"], "bultos de 50 kg")


if __name__ == "__main__":
    test_geometria()
    test_zapata_contacto()
    d, f = test_diseno()
    test_limite_de_zapata()
    test_cantidades_roca()
    test_cantidades_dado_y_liga()
    test_cantidades(d, f)
    if FALLAS:
        print(f"\n{len(FALLAS)} fallas")
        sys.exit(1)
    print("\nOK")
