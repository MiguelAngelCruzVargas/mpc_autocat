"""Tests del corte de cimentacion de muro (create_footing_section). NO
necesita AutoCAD.

Lo que fijan, en orden de importancia:

  - El corte es una COMPOSICION de las primitivas de detalle: cada pieza
    sale de materials.draw_material (poligono + material), la piedra de
    fill_stones, la tierra de soil_section, el acero de create_rebar. No
    hay rectangulos con patron adivinado.
  - Las variantes de obra no se mezclan: pasarle acero de zapata a un
    relleno de piedra se rechaza.
  - lean_concrete_thickness no tiene default en 0: sin plantilla, la
    cimentacion apoyaria directo en tierra suelta.
  - La zapata con talud sale como trapecio de 6 vertices y el gancho de la
    transversal cabe en el espesor DEL BORDE.
  - Los niveles que devuelve ('levels') son los que quedaron dibujados.

Uso:  python test_footing_section.py
"""
from __future__ import annotations

import preview

preview.install()

import rebar   # noqa: E402
import space   # noqa: E402

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


def por_handle(h: str) -> dict | None:
    return next((e for e in preview.DRAWN if e.get("handle") == h), None)


def reset() -> None:
    preview.install()
    space.set_scale(0.02)


BASE = dict(x=0.0, y=0.0, wall_thickness=0.15, footing_width=0.60,
            footing_thickness=0.20, text_height=0.05)


def test_zapata_concreto_apila_los_niveles() -> None:
    reset()
    r = rebar.create_footing_section(
        foundation_type="zapata_concreto",
        grade_beam_height=0.20, wall_height=0.5, dowel_count=4,
        stirrup_spacing=0.15, footing_bar_count=3, **BASE)

    check("plantilla arranca en y=0", cerca(r["levels"]["desplante"], 0.0), r)
    check("zapata arranca donde termina la plantilla (0.10)",
          cerca(r["levels"]["topPlantilla"], 0.10), r["levels"])
    check("cadena arranca donde termina la zapata (0.30)",
          cerca(r["levels"]["topFooting"], 0.30), r["levels"])
    check("el muro arranca donde termina la cadena (0.50)",
          cerca(r["levels"]["topGradeBeam"], 0.50), r["levels"])
    check("el tope es cadena + muro (1.00)",
          cerca(r["levels"]["top"], 1.00), r["levels"])
    check("el terreno natural queda al tope de la cadena",
          cerca(r["levels"]["groundLevel"], 0.50), r["levels"])
    check("3 varillas longitudinales de punta",
          len(r["footingBarHandles"]) == 3, r["footingBarHandles"])
    check("y la transversal con gancho mide mas que el ancho",
          r["footingBarLength_m"] > 0.60 - 2 * 0.05, r["footingBarLength_m"])
    check("4 arranques en L", len(r["dowelHandles"]) == 4 and
          r["totalDowelLength_m"] > 0, r)
    check("estribos de la cadena vistos de canto",
          r["stirrupCount"] >= 2, r["stirrupCount"])


def test_cada_pieza_es_un_material_con_textura() -> None:
    reset()
    r = rebar.create_footing_section(foundation_type="zapata_concreto",
                                     grade_beam_height=0.20, **BASE)
    hatches = de("create_hatch")
    patrones = {h["pattern"] for h in hatches}
    check("plantilla, zapata y cadena con textura de concreto",
          "AR-CONC" in patrones, patrones)
    check("muro de block con rayado", "ANSI31" in patrones, patrones)
    check("tierra alrededor con EARTH", "EARTH" in patrones, patrones)
    tierra = next(h for h in hatches if h["pattern"] == "EARTH")
    check("la tierra tiene las piezas enterradas como islas (3)",
          len(tierra["islandHandles"]) == 3, tierra["islandHandles"])
    check("las escalas salen calibradas (1:20 -> AR-CONC 0.024)",
          any(cerca(h["scale"], 0.024) for h in hatches),
          [h["scale"] for h in hatches])
    check("el terreno borro su contorno auxiliar",
          r["soil"]["boundaryDeleted"], r["soil"])


def test_zapata_con_talud_es_un_trapecio() -> None:
    reset()
    base = dict(BASE)
    base.update(footing_width=1.0, footing_thickness=0.25,
                footing_edge_thickness=0.15, pedestal_height=0.4,
                pedestal_width=0.30, footing_bar_count=4)
    r = rebar.create_footing_section(foundation_type="zapata_concreto", **base)
    zapata = por_handle(r["footingHandle"])
    check("la zapata tiene 6 vertices (talud)",
          zapata and len(zapata["points"]) == 6, zapata and zapata["points"])
    if zapata:
        ys = sorted({round(p[1], 6) for p in zapata["points"]})
        check("borde a 0.10+0.15, centro a 0.10+0.25",
              ys == [0.10, 0.25, 0.35], ys)
    check("el dado queda registrado", r["levels"]["topPedestal"] and
          cerca(r["levels"]["topPedestal"], 0.75), r["levels"])
    # El gancho de la transversal cabe en el espesor del BORDE (0.15):
    # 0.15 - 2 x 0.05 - db, no en los 0.25 del centro.
    barras = [p for p in de("create_polyline") if p.get("bulges")
              and not p.get("closed") and len(p["points"]) >= 4]
    transversal = max(barras, key=lambda p: max(v[0] for v in p["points"])
                      - min(v[0] for v in p["points"]))
    top = max(v[1] for v in transversal["points"])
    check("el gancho no se sale por el talud",
          top < 0.10 + 0.15, top)


def test_piedra_bola_no_lleva_acero_de_zapata() -> None:
    reset()
    try:
        rebar.create_footing_section(foundation_type="piedra_bola",
                                     footing_bar_count=2, **BASE)
        check("rechaza acero de zapata en un relleno", False, "no tiro ValueError")
    except ValueError as exc:
        check("rechaza acero de zapata en un relleno",
              "armado" in str(exc), str(exc))


def test_piedra_bola_dibuja_piedras_empacadas() -> None:
    reset()
    base = dict(BASE)
    base["footing_thickness"] = 0.6
    r = rebar.create_footing_section(foundation_type="piedra_bola", **base)
    check("no hay acero", not r["footingBarHandles"] and not r["dowelHandles"], r)
    check("dibuja piedras de verdad (>= 8)", r["stoneCount"] >= 8, r["stoneCount"])
    piedras = [por_handle(h) for h in r["stoneHandles"]]
    check("cada piedra es una polilinea cerrada con bulge, no un circulo",
          all(p and p.get("bulges") and p.get("closed") for p in piedras)
          and not de("create_circle"))
    zanja = por_handle(r["footingHandle"])
    x0 = min(p[0] for p in zanja["points"])
    x1 = max(p[0] for p in zanja["points"])
    y0 = min(p[1] for p in zanja["points"])
    y1 = max(p[1] for p in zanja["points"])
    check("todas dentro de la zanja",
          all(x0 <= v[0] <= x1 and y0 <= v[1] <= y1
              for p in piedras for v in p["points"]))


def test_mamposteria_y_ciclopeo_existen() -> None:
    reset()
    base = dict(BASE)
    base["footing_thickness"] = 0.5
    r = rebar.create_footing_section(foundation_type="mamposteria", **base)
    check("mamposteria: piedras angulosas sin bulge",
          r["stoneCount"] > 0 and all(not por_handle(h).get("bulges")
                                      for h in r["stoneHandles"]), r["stoneCount"])
    reset()
    r = rebar.create_footing_section(foundation_type="ciclopeo", **base)
    check("ciclopeo: concreto + piedras",
          r["stoneCount"] > 0 and any(h["pattern"] == "AR-CONC" for h in de("create_hatch")))


def test_sin_plantilla_se_rechaza() -> None:
    reset()
    base = dict(BASE)
    base["lean_concrete_thickness"] = 0.0
    try:
        rebar.create_footing_section(foundation_type="zapata_concreto", **base)
        check("rechaza plantilla en 0", False, "no tiro ValueError")
    except ValueError as exc:
        check("rechaza plantilla en 0", "cimentación" in str(exc) or
              "cimentacion" in str(exc), str(exc))


def test_estribar_sin_cadena_ni_dado_se_rechaza() -> None:
    reset()
    base = dict(BASE)
    base.update(dowel_count=4, stirrup_spacing=0.15)
    try:
        rebar.create_footing_section(foundation_type="zapata_concreto", **base)
        check("rechaza estribar sin cadena ni dado", False, "no tiro ValueError")
    except ValueError as exc:
        check("rechaza estribar sin cadena ni dado", "cadena" in str(exc), str(exc))


def test_estribar_sin_arranque_se_rechaza() -> None:
    reset()
    base = dict(BASE)
    base.update(grade_beam_height=0.20, stirrup_spacing=0.15)
    try:
        rebar.create_footing_section(foundation_type="zapata_concreto", **base)
        check("rechaza estribar sin varilla de arranque", False, "no tiro ValueError")
    except ValueError as exc:
        check("rechaza estribar sin varilla de arranque",
              "arranque" in str(exc), str(exc))


def test_los_rotulos_llevan_la_especificacion_y_no_se_pisan() -> None:
    reset()
    base = dict(BASE)
    base["wall_height"] = 0.0
    rebar.create_footing_section(
        foundation_type="zapata_concreto",
        specs={"plantilla": "f'c=100 kg/cm²", "footing": "f'c=200 kg/cm²"},
        **base)
    textos = [t for t in de("create_text") if "PLANTILLA" in t["text"]
              or "ZAPATA" in t["text"]]
    check("hay 2 rotulos (plantilla + zapata)", len(textos) == 2, textos)
    check("cada uno con su f'c",
          all("kg/cm" in t["text"] for t in textos), [t["text"] for t in textos])
    ys = sorted(t["y"] for t in textos)
    check("separados al menos 1.9x la altura de texto",
          ys[1] - ys[0] >= 0.05 * 1.9 - 1e-9, ys)


def test_titulo_sin_letras_separadas_y_con_globo() -> None:
    reset()
    rebar.create_footing_section(foundation_type="piedra_bola",
                                 title="CIMENTACION CON PIEDRA BOLA", mark="A",
                                 **BASE)
    titulo = [t for t in de("create_text") if "CIMENTACION" in t["text"]]
    check("el titulo va seguido, no 'C I M E N T A C I O N'",
          titulo and titulo[0]["text"] == "CIMENTACION CON PIEDRA BOLA",
          titulo and titulo[0]["text"])
    check("hay un globo con la A",
          any(t["text"] == "A" for t in de("create_text")) and de("create_circle"))


def test_cotas_con_estilo_de_punto_decimal() -> None:
    reset()
    rebar.create_footing_section(foundation_type="piedra_bola", **BASE)
    # ensure_dim_style deja MCP-COTAS y la cadena lo pasa como style.
    cotas = [d for d in preview.DRAWN if d["cmd"] == "create_text"
             and d.get("layer") == "COTAS"]
    check("hay cotas dibujadas", len(cotas) >= 3, len(cotas))
    check("ninguna con coma decimal",
          all("," not in c["text"] for c in cotas), [c["text"] for c in cotas])


def test_espesor_implausible_avisa() -> None:
    reset()
    base = dict(BASE)
    base["footing_thickness"] = 0.01
    r = rebar.create_footing_section(foundation_type="zapata_concreto", **base)
    check("0.01 de zapata: avisa que puede estar en otra unidad",
          any("unidad" in w for w in r["warnings"]), r["warnings"])


def test_footing_width_menor_que_el_muro_se_rechaza() -> None:
    reset()
    base = dict(BASE)
    base["footing_width"] = 0.10
    try:
        rebar.create_footing_section(foundation_type="piedra_bola", **base)
        check("rechaza zapata mas angosta que el muro", False, "no tiro ValueError")
    except ValueError as exc:
        check("rechaza zapata mas angosta que el muro", "apoyaría" in str(exc) or
              "apoyaria" in str(exc), str(exc))


def test_excavacion_se_puede_omitir() -> None:
    reset()
    con = rebar.create_footing_section(foundation_type="piedra_bola", **BASE)
    base_sin = dict(BASE)
    base_sin.update(excavation_margin=0.0, soil_depth_below=0.0)
    reset()
    sin = rebar.create_footing_section(foundation_type="piedra_bola", **base_sin)
    check("con margen dibuja el terreno", con["soil"] is not None, con["soil"])
    check("con 0 y 0 lo omite", sin["soil"] is None, sin["soil"])


def test_foundation_type_invalido_se_rechaza() -> None:
    reset()
    try:
        rebar.create_footing_section(foundation_type="flotante", **BASE)
        check("rechaza foundation_type invalido", False, "no tiro ValueError")
    except ValueError:
        check("rechaza foundation_type invalido", True)


def main() -> int:
    for fn in [test_zapata_concreto_apila_los_niveles,
               test_cada_pieza_es_un_material_con_textura,
               test_zapata_con_talud_es_un_trapecio,
               test_piedra_bola_no_lleva_acero_de_zapata,
               test_piedra_bola_dibuja_piedras_empacadas,
               test_mamposteria_y_ciclopeo_existen,
               test_sin_plantilla_se_rechaza,
               test_estribar_sin_cadena_ni_dado_se_rechaza,
               test_estribar_sin_arranque_se_rechaza,
               test_los_rotulos_llevan_la_especificacion_y_no_se_pisan,
               test_titulo_sin_letras_separadas_y_con_globo,
               test_cotas_con_estilo_de_punto_decimal,
               test_espesor_implausible_avisa,
               test_footing_width_menor_que_el_muro_se_rechaza,
               test_excavacion_se_puede_omitir,
               test_foundation_type_invalido_se_rechaza]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: el corte de cimentacion se compone con materiales, piedras, "
          "terreno y varillas de verdad.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
