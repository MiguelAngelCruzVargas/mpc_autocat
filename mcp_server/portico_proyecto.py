"""El pórtico con arco y su barda como PROYECTO: diseñar, dibujar, cuantificar y reportar con tools, sin scripts.

Todo lo que antes pasaba de mano en mano entre scripts (el diseño, lo que midieron los dibujos, las cantidades)
vive en UN archivo de proyecto (JSON) que cada paso lee y completa:

    {"d": design_gate_portal, "f": design_fence, "r": lo que midieron los dibujos,
     "cajas": caja de cada vista en el modelo, "q": cantidades}

Todos los valores se guardan como números y textos de Python (nada de bool o float de numpy convertidos a texto
con default=str: un 'False' hecho texto es verdadero para cualquier `if`, y así un diseño que NO cumplía llegó a
figurar como que cumplía).
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Optional

import numpy as np

import portico_arco as pa
import portico_cuadros as pc
import zapatas as zap


# --------------------------------------------------------------------------- archivo de proyecto

def seguro(x: Any) -> Any:
    """Convierte lo que devuelven los cálculos (numpy, tuplas) a tipos que JSON guarda sin perder el tipo."""
    if isinstance(x, dict):
        return {str(k): seguro(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [seguro(v) for v in x]
    if isinstance(x, np.ndarray):
        return seguro(x.tolist())
    if isinstance(x, np.bool_):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.floating):
        return float(x)
    return x


def cargar(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def guardar(path: str, **partes: Any) -> dict[str, Any]:
    """Agrega o reemplaza las partes dadas y deja lo demás como estaba."""
    proy = cargar(path)
    proy.update({k: seguro(v) for k, v in partes.items()})
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(proy, fh, ensure_ascii=False, indent=1)
    return proy


def _exigir(proy: dict[str, Any], *claves: str) -> None:
    faltan = [c for c in claves if c not in proy]
    nombres = {"d": "design_gate_portal", "f": "design_fence", "r": "draw_portico_set", "q": "quantify_portico"}
    if faltan:
        raise ValueError("El proyecto no tiene " + ", ".join(faltan) + ": falta correr "
                         + ", ".join(nombres.get(c, c) for c in faltan) + " antes de este paso.")


# --------------------------------------------------------------------------- resúmenes para quien llama

def resumen_portico(d: dict[str, Any]) -> dict[str, Any]:
    z, p, v = d["zapata"], d["pilastra"], d["viga"]
    out = {
        "pilastra": {"nucleo_m": d["nucleo"], "armado": p["bars"]["text"], "estribos": p["stirrups"]["text"],
                     "interaccion_PM": p["ratio"], "cumple": bool(p["ok"])},
        "trabe": {"seccion_m": [v["b"], v["h"]], "sup": v["zona_apoyos"]["top"]["text"], "inf": v["zona_apoyos"]["bottom"]["text"],
                  "estribos_apoyo": v["zona_apoyos"]["stirrups"]["text"]},
        "zapata": {"B": z["B"], "L": z["L"], "h": z["h"], "parrilla": z["bars_x"]["text"], "cumple": bool(z["ok"])},
        "liga": ({"seccion_m": [d["liga"]["b"], d["liga"]["h"]], "armado": d["liga"]["bars"]["text"] if "text" in d["liga"]["bars"]
                  else f"{d['liga']['bars']['count']} {d['liga']['bars']['bar']}"} if d.get("liga") else None),
        "reacciones": d["reacciones"],
        "decisiones": d.get("decisions", []),
        "supuestos": d.get("supuestos", []),
    }
    return seguro(out)


def resumen_barda(f: dict[str, Any]) -> dict[str, Any]:
    zc = f["cimentacion"]
    return seguro({"pilastra": {"nucleo_m": f["nucleo"], "armado": f["pilastra"]["bars"]["text"], "estribos": f["pilastra"]["stirrups"]["text"]},
                   "cimiento_corrido": {"B": zc["B"], "h": zc["h"], "transversal": f"{zc['bars_x']['bar']} @ {zc['bars_x']['spacing'] * 100:.0f}"},
                   "separacion_m": f["spacing"], "supuestos": f.get("supuestos", [])})


# --------------------------------------------------------------------------- cimentación impuesta por el proyecto

def imponer_cimentacion(proy: dict[str, Any], footing_width: float, footing_length: float, footing_thickness: float,
                        footing_bars: tuple[str, ...] = ("#3",), pedestal: Optional[list[float]] = None,
                        pedestal_height: float = 0.0, pilaster_bar_count: Optional[int] = None,
                        pilaster_bar: str = "#4", tie_beam: Optional[dict[str, Any]] = None,
                        bearing_reference: Optional[float] = None) -> dict[str, Any]:
    """Aplica al diseño la cimentación y la pilastra que DEFINE el proyecto (en vez de las que dimensiona el
    cálculo) y revisa todo con los mismos criterios: la zapata no crece sola (fixed_thickness) y cada revisión que
    no cumple queda con su demanda y NO CUMPLE. Devuelve el diseño completo ya modificado."""
    _exigir(proy, "d")
    d = json.loads(json.dumps(proy["d"]))
    datos = d.get("datos")
    if not datos:
        raise ValueError("Este diseño no trae 'datos' (f'c, desplante, peso del relleno): volvé a correr design_gate_portal.")
    rc, p = d["reacciones"], d["pilastra"]
    ped_h = pedestal_height if pedestal else 0.0
    # --- cargas sobre la zapata: la liga toma el empuje en el plano; queda la excentricidad de la carga extra
    extra = [tuple(e) for e in d.get("extra_loads", [])]
    M_in = sum(pt * em for pt, em in extra) if tie_beam else rc["M_in_serv_tm"]
    N0 = rc["V_serv_t"]
    z = zap.design_footing(
        kind="aislada", dead_load=N0, live_load=0.0, allowable_bearing=1000.0, fc=datos["fc"], depth=datos["depth"],
        column=[d["nucleo"], d["nucleo"]], soil_unit_weight=datos["soil_unit_weight"], fy=datos["fy"], code="NTC",
        moment_x=M_in, moment_y=rc["M_out_sismo_tm"], tie_beam=False, width=footing_width, length=footing_length,
        min_thickness=footing_thickness, pedestal=pedestal, pedestal_height=ped_h, column_bar=pilaster_bar,
        column_bar_count=pilaster_bar_count or p["bars"]["count"], bars=tuple(footing_bars), mark="Z-1",
        fixed_thickness=True)
    z["checks"].pop("capacidad", None)
    # --- volteo y contacto contra el suelo o la roca (contacto real sin tensión)
    q_adm = bearing_reference or datos["allowable_bearing"]
    ped_a = (pedestal[0] * pedestal[1]) if pedestal else d["nucleo"] ** 2
    B, L, h, depth, gs = footing_width, footing_length, footing_thickness, datos["depth"], datos["soil_unit_weight"]
    casos = [("sismo, solo P-1", N0, rc["M_out_sismo_tm"])]
    for pt, _ in extra[:1]:
        casos.append(("sismo, con la 1.a pilastra de barda", N0 + pt, rc["M_out_sismo_tm"]))
    casos.append(("viento", N0, rc["M_out_viento_tm"]))
    filas = []
    for nombre, n0, mo in casos:
        N = n0 + 2.4 * B * L * h + 2.4 * ped_a * max(depth - h, 0.0) + gs * (B * L - ped_a) * max(depth - h, 0.0)
        q, c = pa.contacto(B, L, N, mo, M_in)
        filas.append({"caso": nombre, "N_t": round(float(N), 2), "M_fuera_tm": round(float(mo), 2),
                      "q_max_t_m2": round(float(q), 1), "contacto": round(float(c), 2)})
    min_c = 0.90
    z["checks"]["volteo_contacto"] = {
        "ok": all(r["q_max_t_m2"] <= q_adm and r["contacto"] >= min_c for r in filas),
        "q_max_t_m2": filas[0]["q_max_t_m2"], "q_adm_t_m2": q_adm, "contacto": filas[0]["contacto"], "min_contacto": min_c,
        "casos": filas, "ref": "Contacto real sin tension (resultante de N y M); capacidad de referencia; contacto minimo 90 %"}
    z["checks_suelo"] = {"q_adm_t_m2": q_adm, "q_max_t_m2": filas[0]["q_max_t_m2"], "contacto": filas[0]["contacto"],
                         "ok": bool(z["checks"]["volteo_contacto"]["ok"]),
                         "ref": "Contacto real sin tension; sismo 100 %; capacidad de referencia (falta E.M.S.)"}
    z["ok"] = all(v.get("ok") for v in z["checks"].values())
    d["zapata"] = z
    # --- pilastra con el armado impuesto
    if pilaster_bar_count:
        dem = p.get("demanda")
        if not dem:
            raise ValueError("La pilastra no trae su demanda: volvé a correr design_gate_portal con esta versión.")
        ab = zap.VARILLAS[pilaster_bar][1]
        dprima = 0.04 + zap.VARILLAS[p["stirrups"]["bar"]][0] + zap.VARILLAS[pilaster_bar][0] / 2
        b = d["nucleo"]
        mx = pa._pm(b, b, datos["fc"], datos["fy"], pa._capas(b, b, dprima, pilaster_bar_count), ab, dem["Pu_kg"])
        ratio = max(abs(a) / mx + abs(c) / mx for a, c in dem["combos"])
        p["bars"] = {"count": pilaster_bar_count, "bar": pilaster_bar, "As_cm2": round(pilaster_bar_count * ab, 2),
                     "text": f"{pilaster_bar_count} {pilaster_bar}"}
        p["rho"] = round(pilaster_bar_count * ab / (b * b * 1e4), 4)
        p["phiMnx_tm"] = p["phiMny_tm"] = round(float(mx), 2)
        p["ratio"] = round(float(ratio), 3)
        p["ok"] = bool(ratio <= 0.95)
    # --- trabe de liga
    if tie_beam:
        bars = tie_beam.get("bars", {"count": 4, "bar": "#3"})
        Tu = max(1.3 * rc.get("H_D_t", rc["H_serv_t"]), 1.1 * rc["H_serv_t"])
        as_col = bars["count"] * zap.VARILLAS[bars["bar"]][1]
        as_req = Tu * 1000.0 / (0.9 * datos["fy"])
        d["liga"] = {"b": tie_beam.get("b", 0.20), "h": tie_beam.get("h", 0.40), "bars": bars,
                     "stirrup": tie_beam.get("stirrup", "#2"), "stirrup_spacing": tie_beam.get("stirrup_spacing", 0.20),
                     "a_lo_largo": bool(tie_beam.get("a_lo_largo", True)), "top_m": tie_beam.get("top_m", -0.15),
                     "bottom_m": tie_beam.get("bottom_m", -0.55), "Tu_t": round(Tu, 2), "As_req_cm2": round(as_req, 2),
                     "As_cm2": round(as_col, 2), "ok": bool(as_col >= as_req)}
    # --- lo que dice el diseño
    import portico_reporte as pr
    falla = [a for a, _, _, res in pr.revision(d) if res == pr.NO_CUMPLE]
    d["decisions"] = [
        f"Cimentación impuesta por el proyecto: zapata {B:.2f} x {L:.2f} x {h:.2f} m, parrilla {z['bars_x']['text']}"
        + (f", dado de {pedestal[0] * 100:.0f} x {pedestal[1] * 100:.0f} cm y {ped_h:.2f} m de alto" if pedestal else "")
        + (f"; NO CUMPLE: {'; '.join(falla)}." if falla else "; cumple todas las revisiones."),
    ] + [t for t in d.get("decisions", []) if t.startswith("Trabe curva")]
    d["opciones"] = {}
    return seguro(d)


# --------------------------------------------------------------------------- dibujo del conjunto

# Unidades de modelo por mm de papel con que se dimensiona el texto de cada vista (2 mm de papel = 2 * upm). Es la
# escala del TEXTO; la del viewport se elige al componer la lámina y puede ser otra (las pilastras de barda, por
# ejemplo, se ven a 1:15 con el texto de 1:20 para que se lea).
UPM_VISTAS = {"alzado_general": 0.05, "planta_general": 0.05, "alzado_portico": 0.025, "alzado_estructural": 0.025,
              "armado_trabe": 0.025, "corte_aa": 0.01, "pilastra_p1": 0.015, "pilastra_p2": 0.02,
              "planta_cimentacion": 0.05, "z1": 0.025, "zc": 0.02, "tl1_seccion": 0.01}


def dibujar_conjunto(proy: dict[str, Any], ox: float = 0.0, oy: float = 0.0, bays: int = 3, roca: bool = False,
                     depth_barda: Optional[float] = None, upm: Optional[dict[str, float]] = None) -> dict[str, Any]:
    """Dibuja TODAS las vistas del proyecto en el modelo, cada una en su zona (sin pisarse), y devuelve la caja
    de cada una con su escala y lo que midieron los dibujos (largos de trabe y varillas, estribos, castillo y
    dala) que las cantidades necesitan."""
    import portico_detalles as pd1
    import portico_detalles2 as pd2
    import portico_dibujo as pdi
    import zapatas_dibujo as zd

    _exigir(proy, "d", "f")
    d, f = proy["d"], proy["f"]
    z, zc = d["zapata"], f["cimentacion"]
    depth_barda = depth_barda or zc["depth"]
    vistas: dict[str, dict[str, Any]] = {}
    u = {**UPM_VISTAS, **(upm or {})}
    malos = [k for k in (upm or {}) if k not in UPM_VISTAS]
    if malos:
        raise ValueError(f"upm: vistas desconocidas {malos}; las válidas son {sorted(UPM_VISTAS)}.")

    def reg(nombre: str, caja: list[float], upm_: float) -> None:
        vistas[nombre] = {"box": [round(float(c), 3) for c in caja], "text_scale_denominator": round(upm_ * 1000)}

    r_alz = pdi.alzado_general(d, f, ox, oy, u["alzado_general"], bays=bays)
    reg("alzado_general", r_alz["box"], u["alzado_general"])
    r_pl = pdi.planta_general(d, f, ox, oy - 15.0, u["planta_general"], bays=bays)
    reg("planta_general", r_pl["box"], u["planta_general"])
    r_ap = pdi.alzado_portico(d, ox + 60.0, oy, u["alzado_portico"])
    reg("alzado_portico", r_ap["box"], u["alzado_portico"])
    r_ae = pd2.alzado_estructural(d, ox + 84.0, oy, u["alzado_estructural"])
    reg("alzado_estructural", r_ae["box"], u["alzado_estructural"])
    r_tr = pd1.armado_trabe(d, ox + 59.5, oy - 37.0, u["armado_trabe"])
    reg("armado_trabe", r_tr["box"], u["armado_trabe"])
    r_cf = pd2.corte_fronton(d, ox + 81.8, oy - 41.0, u["corte_aa"])
    reg("corte_aa", r_cf["box"], u["corte_aa"])
    r_p1 = pd1.armado_pilastra(d, ox + 109.625, oy - 48.0, u["pilastra_p1"])
    reg("pilastra_p1", r_p1["box"], u["pilastra_p1"])
    r_p2 = pd2.pilastra_barda(f, ox + 134.65, oy - 47.7, u["pilastra_p2"], depth_barda)
    reg("pilastra_p2", r_p2["box"], u["pilastra_p2"])
    r_ci = pd2.planta_cimentacion(d, f, ox, oy - 60.0, u["planta_cimentacion"], bays=bays)
    reg("planta_cimentacion", r_ci["box"], u["planta_cimentacion"])
    # zapata Z-1: corte y planta
    X1, Y1 = ox + 62.0, oy - 70.0
    r_z1 = zd.draw_footing_section(z, X1, Y1, u["z1"], working_space=0.30, slope=0.5, mark="Z-1", roca=roca)
    izq = z["column_offsets"][0]
    a1 = (z.get("pedestal") or z["column"])[0]
    r_z1p = zd.draw_footing_plan(z, r_z1["box"][2] + 3.0 + izq + a1 / 2, Y1 - 0.5, u["z1"])
    reg("z1_corte", r_z1["box"], u["z1"])
    reg("z1_planta", r_z1p["box"], u["z1"])
    # cimiento corrido ZC-1
    r_zc = zd.draw_footing_section(zc, ox + 100.5, oy - 69.0, u["zc"], working_space=0.30, slope=0.5, mark="ZC-1")
    r_zcp = zd.draw_strip_plan(zc, r_zc["box"][2] + 3.0 + 1.2, oy - 70.2, u["zc"], length=2.40)
    reg("zc_corte", r_zc["box"], u["zc"])
    reg("zc_planta", r_zcp["box"], u["zc"])
    if d.get("liga"):
        r_tl = pd2.seccion_trabe_liga(d, ox + 125.0, oy - 70.0, u["tl1_seccion"])
        reg("tl1_seccion", r_tl["box"], u["tl1_seccion"])
    solapes = []
    nombres = list(vistas)
    for i, a in enumerate(nombres):
        for b in nombres[i + 1:]:
            A, B_ = vistas[a]["box"], vistas[b]["box"]
            if min(A[2], B_[2]) > max(A[0], B_[0]) and min(A[3], B_[3]) > max(A[1], B_[1]):
                solapes.append([a, b])
    r = {"trabe": {k: r_tr[k] for k in ("arc_length_m", "stirrups", "bar_len_inf_m", "bar_len_sup_m", "hook_m")},
         "pil1": {"height_m": r_p1["height_m"], "bar_len_m": r_p1["bar_len_m"],
                  "stirrupCount": int((r_p1.get("elevation") or {}).get("stirrupCount", 0))},
         "pil2": {"height_m": r_p2.get("height_m"), "pata_m": r_p2.get("pata_m"),
                  "stirrupCount": int((r_p2.get("elevation") or {}).get("stirrupCount", r_p2.get("stirrupCount", 0)))},
         "fronton_h": r_ae["fronton_h"], "dala_len": r_ae["dala_len"]}
    faltan = [k for k in ("pil1", "pil2") if not r[k]["stirrupCount"]]
    return {"vistas": vistas, "r": seguro(r), "solapes": solapes,
            "avisos": ([f"No se pudo leer el número de estribos de {', '.join(faltan)}: las cantidades de acero saldrían incompletas."]
                       if faltan else [])}


# --------------------------------------------------------------------------- cantidades

def cuantificar(proy: dict[str, Any], depth_portico: Optional[float] = None, depth_barda: Optional[float] = None,
                bays: int = 3, roca: bool = False) -> dict[str, Any]:
    _exigir(proy, "d", "f", "r")
    d, f = proy["d"], proy["f"]
    dp = depth_portico or d["zapata"]["depth"]
    db = depth_barda or f["cimentacion"]["depth"]
    return seguro(pc.cantidades(d, f, proy["r"], dp, db, bays=bays, roca=roca))
