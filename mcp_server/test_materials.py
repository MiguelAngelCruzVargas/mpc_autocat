"""Tests de materials.py (materiales cortados, piedras, terreno) y de
create_rebar (varilla por trayectoria). NO necesita AutoCAD.

Lo que fijan, en orden de importancia:

  - La escala del achurado sale de la LAMINA, no de una constante: ANSI31
    a 2 mm de papel en un dibujo en metros a 1:20 es 0.32, a 1:100 es 1.6.
    Era el motivo de que un corte de cimentacion saliera sin textura.
  - Un patron que no carga NO se traga en silencio: cae al de respaldo y
    lo dice; si ninguno carga, queda en 'warnings'.
  - Las piedras se empacan de verdad: ninguna pisa a otra, todas caen
    dentro del contorno (tambien en uno trapezoidal), y la cobertura
    supera lo que daba tirar circulos al azar.
  - El terreno se achura con las piezas como islas, borra su contorno
    auxiliar y corta la linea de terreno donde una pieza SALE del suelo.
  - Una varilla con gancho a 90 mide mas que su tramo recto (12db de pata
    + el arco), y el estribo cerrado lleva las dos puntas a 135.

Uso:  python test_materials.py
"""
from __future__ import annotations

import math

import geom
import preview

preview.install()

import materials  # noqa: E402
import rebar      # noqa: E402
import space      # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def cerca(a: float, b: float, tol: float = 1e-4) -> bool:
    return abs(a - b) <= tol


def de(cmd: str) -> list[dict]:
    return [e for e in preview.DRAWN if e["cmd"] == cmd]


def reset() -> None:
    preview.install()
    space.set_scale(0.02)   # 1:20 en metros


# --------------------------------------------------------- escala hatch

def test_escala_de_hatch_sale_de_la_lamina() -> None:
    reset()
    check("ANSI31 a 2 mm de papel, 1:20 en metros -> 0.32",
          cerca(materials.hatch_scale("ANSI31", 2.0, scale=0.02), 0.32),
          materials.hatch_scale("ANSI31", 2.0, scale=0.02))
    check("misma peticion a 1:100 -> 1.6 (5 veces mas)",
          cerca(materials.hatch_scale("ANSI31", 2.0, scale=0.1), 1.6),
          materials.hatch_scale("ANSI31", 2.0, scale=0.1))
    check("sin 'scale' toma la de space (0.02)",
          cerca(materials.hatch_scale("ANSI31", 2.0), 0.32))
    check("real_size manda sobre paper_mm: block de 0.40 con AR-B816 -> 0.025",
          cerca(materials.hatch_scale("AR-B816", 3.0, real_size=0.40), 0.025))
    check("patron desconocido: modulo 1",
          cerca(materials.hatch_scale("AR-RROOF", 2.0, scale=0.02), 0.04))
    # Un dibujo metrico usa acadiso.pat, donde los mismos patrones estan
    # definidos en mm: 25.4 veces mas grandes a la misma escala. Se vio en
    # AutoCAD real (INSUNITS en mm): AR-CONC a 0.024 salia solido.
    materials.set_pattern_units("mm")
    try:
        check("en dibujo metrico la escala baja 25.4 veces",
              cerca(materials.hatch_scale("ANSI31", 2.0, scale=0.02), 0.32 / 25.4, 1e-6),
              materials.hatch_scale("ANSI31", 2.0, scale=0.02))
    finally:
        materials.set_pattern_units("inch")
    materials.set_pattern_units(None)
    original = materials.acad.call

    def metrico(cmd, params=None):
        if cmd == "get_drawing_info":
            return {"units": "Millimeters"}
        return original(cmd, params)

    materials.acad.call = metrico
    try:
        check("se detecta solo con get_drawing_info (INSUNITS metrico)",
              materials.pattern_units() == "mm", materials.pattern_units())
    finally:
        materials.acad.call = original
        materials.set_pattern_units("inch")


# ------------------------------------------------------------ material

def test_material_dibuja_contorno_y_textura_calibrada() -> None:
    reset()
    r = materials.draw_material([[0, 0], [1, 0], [1, 0.2], [0, 0.2]], "concreto")
    pl = de("create_polyline")
    ha = de("create_hatch")
    check("un contorno cerrado", len(pl) == 1 and pl[0]["closed"], pl)
    check("contorno al grosor de corte (50)", pl[0]["lineweight"] == 50, pl[0])
    check("un achurado AR-CONC", len(ha) == 1 and ha[0]["pattern"] == "AR-CONC", ha)
    check("escala calibrada = 1.2 mm x 0.02 / 1.0",
          ha and cerca(ha[0]["scale"], 0.024), ha)
    check("area por shoelace", cerca(r["area"], 0.2), r["area"])
    check("devuelve los puntos para usarlos de isla", len(r["points"]) == 4, r)
    check("sin avisos", not r["warnings"], r["warnings"])


def test_material_acepta_poligono_cualquiera_y_alias() -> None:
    reset()
    trap = [[0, 0], [1, 0], [1, 0.15], [0.65, 0.3], [0.35, 0.3], [0, 0.15]]
    r = materials.draw_material(trap, "concrete")
    check("alias en ingles resuelve a concreto", r["material"] == "concreto", r)
    check("el trapecio se dibuja tal cual (6 vertices)",
          len(de("create_polyline")[0]["points"]) == 6)
    try:
        materials.draw_material(trap, "kriptonita")
        check("material desconocido se rechaza", False, "no tiro ValueError")
    except ValueError as exc:
        check("material desconocido se rechaza y lista el catalogo",
              "concreto" in str(exc), str(exc))
    r2 = materials.draw_material(trap, {"pattern": "AR-RROOF", "paper_mm": 2.0,
                                        "name": "teja"})
    check("material inline funciona sin tocar el catalogo",
          de("create_hatch")[-1]["pattern"] == "AR-RROOF", r2)


def test_patron_que_no_carga_cae_al_respaldo_y_avisa() -> None:
    reset()
    original = materials.acad.call

    def sin_arconc(cmd, params=None):
        if cmd == "create_hatch" and params.get("pattern") == "AR-CONC":
            raise materials.acad.AutoCadError("eInvalidInput: pattern")
        return original(cmd, params)

    materials.acad.call = sin_arconc
    try:
        r = materials.draw_material([[0, 0], [1, 0], [1, 0.2], [0, 0.2]], "concreto")
    finally:
        materials.acad.call = original
    ha = de("create_hatch")
    check("cayo a ANSI31", ha and ha[-1]["pattern"] == "ANSI31", ha)
    check("y lo dijo", any("ANSI31" in w for w in r["warnings"]), r["warnings"])

    reset()

    def nada(cmd, params=None):
        if cmd == "create_hatch":
            raise materials.acad.AutoCadError("eInvalidInput")
        return original(cmd, params)

    materials.acad.call = nada
    try:
        r = materials.draw_material([[0, 0], [1, 0], [1, 0.2], [0, 0.2]], "concreto")
    finally:
        materials.acad.call = original
    check("sin ningun patron: contorno igual, hatchHandle None y AVISO",
          r["hatchHandle"] is None and any("NO se pudo" in w for w in r["warnings"]),
          r)


# ------------------------------------------------------------- piedras

def _piedras_dibujadas() -> list[dict]:
    return [p for p in de("create_polyline") if p.get("bulges")]


def test_piedras_no_se_pisan_y_caen_dentro() -> None:
    reset()
    zanja = [[0, 0], [0.6, 0], [0.6, 0.6], [0, 0.6]]
    r = materials.fill_stones(zanja)
    piedras = de("create_polyline")
    check("empaca una cantidad razonable (>= 10)", r["count"] >= 10, r["count"])
    check("cobertura real > 45% (tirar circulos al azar daba 28%)",
          r["coverage"] > 0.45, r["coverage"])
    check("redondas: cada una lleva bulges", all(p.get("bulges") for p in piedras))
    adentro = all(geom.point_in_polygon(x, y, zanja) for p in piedras
                  for x, y in p["points"])
    check("todos los vertices dentro de la zanja", adentro)
    choques = 0
    polys = [[tuple(v) for v in p["points"]] for p in piedras]
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            if materials._polys_overlap(polys[i], polys[j]):
                choques += 1
    check("ninguna piedra pisa a otra", choques == 0, choques)
    check("determinista: misma semilla, mismo dibujo",
          materials.fill_stones(zanja)["count"] == r["count"])


def test_piedras_en_contorno_trapezoidal_y_angulosas() -> None:
    reset()
    trap = [[0, 0], [1.0, 0], [1.0, 0.2], [0.65, 0.45], [0.35, 0.45], [0, 0.2]]
    r = materials.fill_stones(trap, shape="angulosa")
    piedras = de("create_polyline")
    check("angulosas: sin bulges (caras planas)",
          all(not p.get("bulges") for p in piedras))
    adentro = all(geom.point_in_polygon(x, y, trap) for p in piedras
                  for x, y in p["points"])
    check("todas dentro del trapecio (los cortes inclinados tambien)", adentro)
    check("cobertura > 40%", r["coverage"] > 0.40, r["coverage"])


def test_hueco_mas_chico_que_una_piedra_avisa() -> None:
    reset()
    r = materials.fill_stones([[0, 0], [0.1, 0], [0.1, 0.1], [0, 0.1]],
                              stone_size=[0.15, 0.25])
    check("no dibuja ninguna y avisa", r["count"] == 0 and r["warnings"], r)


# ------------------------------------------------------------- terreno

def test_terreno_islas_borra_contorno_y_corta_la_linea() -> None:
    reset()
    zapata = materials.draw_material([[-0.5, 0], [0.5, 0], [0.5, 0.3], [-0.5, 0.3]],
                                     "concreto")
    muro = materials.draw_material([[-0.075, 0.3], [0.075, 0.3], [0.075, 1.0],
                                    [-0.075, 1.0]], "block")
    r = materials.soil_section(-0.9, 0.9, 0.3, -0.2, islands=[zapata, muro])
    ha = de("create_hatch")[-1]
    check("achurado EARTH a 45", ha["pattern"] == "EARTH" and ha["angleDeg"] == 45.0, ha)
    check("la zapata es isla, el muro (fuera de la masa) no",
          ha["islandHandles"] == [zapata["handle"]], ha["islandHandles"])
    check("el contorno auxiliar se borro",
          r["boundaryDeleted"] and r["boundaryHandle"] is None, r)
    contornos = [p for p in de("create_polyline") if len(p["points"]) == 4
                 and cerca(p["points"][0][1], -0.2)]
    check("y ya no esta entre lo dibujado", not contornos, contornos)
    lineas = [ln for ln in de("create_line") if cerca(ln["y1"], 0.3)]
    check("la linea de terreno son 2 tramos: se corta en el muro",
          len(lineas) == 2, lineas)
    if len(lineas) == 2:
        xs = sorted([lineas[0]["x2"], lineas[1]["x1"]])
        check("el hueco es exactamente el ancho del muro",
              cerca(xs[0], -0.075, 1e-3) and cerca(xs[1], 0.075, 1e-3), xs)


def test_terreno_pasa_de_largo_sobre_lo_que_termina_en_el_nivel() -> None:
    reset()
    cadena = materials.draw_material([[-0.1, 0], [0.1, 0], [0.1, 0.2], [-0.1, 0.2]],
                                     "concreto")
    materials.soil_section(-0.5, 0.5, 0.2, -0.1, islands=[cadena])
    lineas = [ln for ln in de("create_line") if cerca(ln["y1"], 0.2)]
    check("una sola linea continua (nada sale del suelo)", len(lineas) == 1, lineas)


# ------------------------------------------------------------- varilla

def _largo_polilinea(p: dict) -> float:
    pts, bul = p["points"], p.get("bulges") or [0] * len(p["points"])
    total = 0.0
    for i in range(len(pts) - 1):
        c = math.dist(pts[i], pts[i + 1])
        b = abs(bul[i])
        if b < 1e-12:
            total += c
        else:
            th = 4 * math.atan(b)
            total += c / (2 * math.sin(th / 2)) * th
    return total


def test_varilla_recta_mide_lo_que_mide() -> None:
    reset()
    r = rebar.create_rebar([[0, 0], [1.2, 0]], 0.0127)
    check("recta: 1.20 m", cerca(r["length_m"], 1.2), r["length_m"])
    check("una polilinea abierta",
          de("create_polyline")[0]["closed"] is False)


def test_gancho_a_90_agrega_12db_y_va_hacia_arriba() -> None:
    reset()
    db = 0.0127
    r = rebar.create_rebar([[0, 0], [1.0, 0]], db, end_hook="90", hook_side="left")
    p = de("create_polyline")[0]
    ys = [v[1] for v in p["points"]]
    check("el gancho sube (left de izquierda->derecha es arriba)",
          max(ys) > 0.1, ys)
    check("la pata mide 12db mas el doblez",
          cerca(max(ys), 12 * db + (6 / 2 + 0.5) * db, 1e-3), max(ys))
    check("la longitud desarrollada cuenta pata y arco",
          r["length_m"] > 1.0 + 12 * db, r["length_m"])
    check("length_m coincide con lo dibujado",
          cerca(r["length_m"], _largo_polilinea(p), 1e-3),
          (r["length_m"], _largo_polilinea(p)))
    check("hay un arco (bulge) en el doblez",
          any(abs(b) > 0 for b in p["bulges"]), p["bulges"])
    r2 = rebar.create_rebar([[0, 0], [1.0, 0]], db, end_hook="90", hook_side="right")
    p2 = de("create_polyline")[-1]
    check("right: el gancho baja", min(v[1] for v in p2["points"]) < -0.1)


def test_gancho_al_inicio_y_180() -> None:
    reset()
    db = 0.0127
    rebar.create_rebar([[0, 0], [1.0, 0]], db, start_hook="90", end_hook="90")
    p = de("create_polyline")[0]
    xs = [v[0] for v in p["points"]]
    ys = [v[1] for v in p["points"]]
    check("los dos ganchos suben", ys[0] > 0.1 and ys[-1] > 0.1, (ys[0], ys[-1]))
    check("y quedan en las puntas (x=0 y x=1)",
          cerca(min(xs), 0.0, 1e-6) and cerca(max(xs), 1.0, 1e-6), (min(xs), max(xs)))
    reset()
    r = rebar.create_rebar([[0, 0], [1.0, 0]], db, end_hook="180")
    p = de("create_polyline")[0]
    check("180: la pata vuelve hacia atras (x < 1.0 al final)",
          p["points"][-1][0] < 1.0 - 3 * db, p["points"][-1])
    check("180: semicirculo con bulge 1",
          any(cerca(abs(b), 1.0) for b in p["bulges"]), p["bulges"])


def test_estribo_cerrado_con_ganchos_a_135() -> None:
    reset()
    r = rebar.create_rebar([[0, 0], [0.3, 0], [0.3, 0.3], [0, 0.3]], 0.0095,
                           closed=True)
    p = de("create_polyline")[0]
    check("ganchos por default a 135 en las dos puntas",
          r["hooks"] == {"start": "135", "end": "135"}, r["hooks"])
    check("las puntas terminan ADENTRO del nucleo",
          all(0 < v[0] < 0.3 and 0 < v[1] < 0.3 for v in (p["points"][0], p["points"][-1])),
          (p["points"][0], p["points"][-1]))
    check("perimetro desarrollado > 4 x 0.30", r["length_m"] > 1.2, r["length_m"])
    check("estribo: radio de doblez a 4db",
          cerca(r["bendRadius"], (4 / 2 + 0.5) * 0.0095), r["bendRadius"])


def test_varilla_rechaza_lo_invalido() -> None:
    reset()
    for kwargs in ({"diameter": 0}, {"end_hook": "45"}, {"hook_side": "up"}):
        base = {"points": [[0, 0], [1, 0]], "diameter": 0.0127}
        base.update(kwargs)
        try:
            rebar.create_rebar(**base)
            check(f"rechaza {kwargs}", False, "no tiro ValueError")
        except ValueError:
            check(f"rechaza {kwargs}", True)


def test_puntos_de_varilla() -> None:
    reset()
    r = rebar.create_rebar_dots([[0, 0], [0.1, 0], [0.2, 0]], 0.0127)
    circ = de("create_circle")
    check("un circulo por varilla al radio real",
          len(circ) == 3 and all(cerca(c["radius"], 0.00635) for c in circ), circ)
    check("relleno solido", len(de("create_hatch")) == 3)
    check("cuenta", r["count"] == 3)


def main() -> int:
    for fn in [test_escala_de_hatch_sale_de_la_lamina,
               test_material_dibuja_contorno_y_textura_calibrada,
               test_material_acepta_poligono_cualquiera_y_alias,
               test_patron_que_no_carga_cae_al_respaldo_y_avisa,
               test_piedras_no_se_pisan_y_caen_dentro,
               test_piedras_en_contorno_trapezoidal_y_angulosas,
               test_hueco_mas_chico_que_una_piedra_avisa,
               test_terreno_islas_borra_contorno_y_corta_la_linea,
               test_terreno_pasa_de_largo_sobre_lo_que_termina_en_el_nivel,
               test_varilla_recta_mide_lo_que_mide,
               test_gancho_a_90_agrega_12db_y_va_hacia_arriba,
               test_gancho_al_inicio_y_180,
               test_estribo_cerrado_con_ganchos_a_135,
               test_varilla_rechaza_lo_invalido,
               test_puntos_de_varilla]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: materiales, piedras, terreno y varillas se dibujan como en un "
          "detalle de obra.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
