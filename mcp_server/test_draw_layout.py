"""Tests del ciclo completo: suggest_layout → draw_layout, sin AutoCAD.

La promesa es que el servidor dibuja la vivienda entera sin que nadie
calcule una coordenada de muro: fronteras sin duplicar, puertas en su muro
abriendo al recinto correcto, ventanas esquivando puertas, y la muraria
resultante pasa check_walls.

Uso:  python test_draw_layout.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import arch    # noqa: E402
import rules   # noqa: E402
import server  # noqa: E402
import space   # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def test_dibuja_el_partido_completo() -> None:
    preview.DRAWN.clear()
    space.clear()
    plan = rules.suggest_layout(8.0, 15.0, bedrooms=2, bathrooms=1)
    r = arch.draw_layout(plan["rooms"], plan["doors"], plan["windows"])
    check("todas las puertas encontraron su muro",
          r["doorsPlaced"] == len(plan["doors"]),
          f"{r['doorsPlaced']} de {len(plan['doors'])}: "
          + str(r.get("warnings")))
    check("se dibujaron muros", len(r["wallHandles"]) > 0, str(r))
    check("hay ventanas ubicadas (fachada y patio)",
          len(r["windowsPlaced"]) >= 3, str(r["windowsPlaced"]))
    chk = rules.check_walls(walls=r["axes"])
    check("la muraria dibujada cierra (check_walls)", chk["ok"],
          str(chk["problems"]))
    check("ninguna puerta quedo sin ubicar",
          not any("puerta" in str(w).lower()
                  for w in r.get("warnings", [])),
          str(r.get("warnings")))


def test_toda_la_grilla_se_dibuja() -> None:
    """Lo que suggest_layout propone, draw_layout lo tiene que poder dibujar
    con la muraria cerrando, para CUALQUIER combinacion admitida."""
    fallas = 0
    for w in (6.4, 9.0, 12.0):
        for beds in (1, 3, 6):
            for baths in (1, 2):
                preview.DRAWN.clear()
                space.clear()
                plan = rules.suggest_layout(w, 40.0, bedrooms=beds,
                                            bathrooms=baths)
                r = arch.draw_layout(plan["rooms"], plan["doors"],
                                     plan["windows"])
                chk = rules.check_walls(walls=r["axes"])
                if (r["doorsPlaced"] != len(plan["doors"])) or not chk["ok"]:
                    fallas += 1
                    FAILED.append(
                        f"grilla w={w} beds={beds} baths={baths}: "
                        f"puertas {r['doorsPlaced']}/{len(plan['doors'])}, "
                        f"walls={chk['problems']}")
    check("toda la grilla se dibuja y cierra", fallas == 0,
          f"{fallas} combinaciones fallaron")


def test_frontera_compartida_una_sola_vez() -> None:
    """Dos recintos vecinos comparten UN muro, no dos superpuestos."""
    preview.DRAWN.clear()
    space.clear()
    r = arch.draw_layout(
        [{"name": "A", "x0": 0, "y0": 0, "x1": 4, "y1": 4},
         {"name": "B", "x0": 4, "y0": 0, "x1": 8, "y1": 4}],
        doors=[{"from": "A", "to": "B", "width": 0.9, "x": 4.0, "y": 2.0}])
    # Lineas unicas: x=0, x=4, x=8, y=0, y=4 -> 5 tramos, no 8.
    check("5 tramos de muro para dos cuartos pegados", r["segments"] == 5,
          str(r["segments"]))
    chk = rules.check_walls(walls=r["axes"])
    check("y la muraria cierra", chk["ok"], str(chk["problems"]))


def test_puerta_sin_posicion_avisa() -> None:
    preview.DRAWN.clear()
    space.clear()
    r = arch.draw_layout(
        [{"name": "A", "x0": 0, "y0": 0, "x1": 4, "y1": 4}],
        doors=[{"from": "EXTERIOR", "to": "A", "width": 0.9}])
    check("la puerta sin x,y no se dibuja y se avisa",
          r["doorsPlaced"] == 0
          and any("posición" in w for w in r.get("warnings", [])),
          str(r))


def test_tool_del_server_rotula_y_verifica() -> None:
    preview.DRAWN.clear()
    space.clear()
    plan = rules.suggest_layout(8.0, 15.0, bedrooms=2, bathrooms=2)
    r = server.draw_layout(rooms=plan["rooms"], doors=plan["doors"],
                           windows=plan["windows"])
    check("la tool devuelve el check_walls corrido",
          r.get("checkWalls", {}).get("ok"), str(r.get("checkWalls")))
    textos = [e["text"] for e in preview.DRAWN if e["cmd"] == "create_text"]
    check("rotula los ambientes", any("SALA" in t for t in textos),
          str(textos[:10]))
    check("el pasillo no se rotula (no entra ni hace falta)",
          not any("PASILLO" in t for t in textos), str(textos))


def test_remata_los_encuentros() -> None:
    """Tramo por tramo, la linea de cierre de cada muro quedaba ATRAVESANDO
    el muro al que llega (puntas que sobran en cada encuentro) y, aun
    fusionando con union_regions, a la esquina exterior de cada L le
    faltaba un cuadrito de medio espesor. La red remata todo en Python:
    sin Regions y sin depender de una booleana de AutoCAD."""
    preview.DRAWN.clear()
    space.clear()
    llamadas = []
    real = arch.acad.call

    def espia(cmd, params=None):
        llamadas.append((cmd, params or {}))
        if cmd == "union_regions":
            raise arch.acad.AutoCadError("no se tendria que llamar")
        return real(cmd, params)

    try:
        arch.acad.call = espia
        rooms = [{"name": "A", "x0": 0, "y0": 0, "x1": 4, "y1": 4},
                 {"name": "B", "x0": 4, "y0": 0, "x1": 8, "y1": 4}]
        r = arch.draw_layout(rooms)
        check("no pasa por union_regions",
              not [c for c, _ in llamadas if c == "union_regions"],
              "la llamo")
        check("sin avisos", not r.get("warnings"), str(r.get("warnings")))
        # Contorno exterior + un hueco por ambiente.
        check("tres lazos cerrados (perimetro + 2 ambientes)",
              len(r["wallHandles"]) == 3, str(r["wallHandles"]))
        # 8.15 x 4.15 menos los dos interiores de 3.875 x 3.85: la esquina
        # exterior completa, la T del divisorio sin solapes.
        esperado = 8.15 * 4.15 - 2 * 3.875 * 3.85
        check("el area de mamposteria es la exacta",
              abs(r.get("masonryArea", 0) - esperado) < 1e-6,
              f"{r.get('masonryArea')} vs {esperado}")
        polis = [e for e in preview.DRAWN if e["cmd"] == "create_polyline"
                 and e.get("layer") == "MUROS"]
        check("todos los lazos son polilineas cerradas",
              all(e.get("closed") for e in polis), str(polis))
        esquinas = {tuple(round(c, 6) for c in p)
                    for e in polis for p in e["points"]}
        check("la esquina exterior llega al vertice (-0.075, -0.075)",
              (-0.075, -0.075) in esquinas, str(sorted(esquinas)[:6]))

        preview.DRAWN.clear()
        r2 = arch.draw_layout(rooms, merge=False)
        check("merge=False deja un contorno suelto por tramo",
              len(r2["wallHandles"]) == r2["segments"] == 5,
              f"{len(r2['wallHandles'])} / {r2['segments']}")
    finally:
        arch.acad.call = real


def test_ningun_partido_deja_muros_sueltos_ni_machones() -> None:
    """Barrido completo de lo que suggest_layout admite. Antes: la puerta
    COMEDOR -> PASILLO (0.90) caia sobre un muro comun de 0.50, montada
    sobre dos encuentros -- dejaba suelto el muro sala/comedor y la hoja
    barria contra el de la cocina; y la ventana de fachada quedaba a 0.15
    de la puerta, un machon de 0.30 que no se levanta."""
    malos = []
    n = 0
    for w in (6.4, 7.0, 8.0, 9.0, 12.0):
        for beds in range(1, 7):
            for baths in (1, 2):
                preview.DRAWN.clear()
                space.clear()
                p = rules.suggest_layout(w, 40.0, bedrooms=beds,
                                         bathrooms=baths)
                r = arch.draw_layout(p["rooms"], p["doors"], p["windows"])
                n += 1
                chk = rules.check_walls(walls=r["axes"])
                if (r.get("warnings") or not chk["ok"]
                        or r["doorsPlaced"] != r["doorsTotal"]
                        or len(r["windowsPlaced"]) != len(p["windows"])):
                    malos.append((w, beds, baths, r.get("warnings"),
                                  chk["problems"]))
                xm = w / 2.0
                tabique = [a for a in r["axes"]
                           if all(abs(pt[0] - xm) < 1e-6 for pt in a["points"])
                           and min(pt[1] for pt in a["points"]) < 4.0 - 1e-6]
                if tabique:
                    malos.append((w, beds, baths, "muro entre sala y comedor",
                                  tabique))
    check(f"{n} partidos sin avisos, sin muros sueltos ni machones",
          not malos, str(malos[:3]))


def test_acota_el_partido_solo() -> None:
    """Los cortes de la cadena son las fronteras entre recintos: nadie las
    lista a mano."""
    preview.DRAWN.clear()
    space.clear()
    plan = rules.suggest_layout(8.0, 15.0, bedrooms=2, bathrooms=1)
    arch.draw_layout(plan["rooms"], plan["doors"], plan["windows"])
    r = arch.dimension_layout(plan["rooms"], scale=0.1)
    check("acota dos lados por default (detalle + total = 4 cadenas)",
          r["count"] == 4, str(r["count"]))
    check("los cortes en X son las fronteras verticales",
          r["xCuts"][0] == 0.0 and r["xCuts"][-1] == 8.0, str(r["xCuts"]))
    check("los cortes en Y llegan al fondo del lote",
          r["yCuts"][-1] == 15.0, str(r["yCuts"]))
    check("la caja es el lote entero", r["box"] == [0.0, 0.0, 8.0, 15.0],
          str(r["box"]))


def test_cada_lado_acota_su_propio_pano() -> None:
    """La cadena de abajo acota los recintos que APOYAN abajo, no todas las
    fronteras del plano. Mezclarlas metia en la cadena inferior divisiones
    del fondo y los numeros salian encimados ('0.500.50')."""
    preview.DRAWN.clear()
    space.clear()
    plan = rules.suggest_layout(8.0, 16.0, bedrooms=3, bathrooms=2)
    r = arch.dimension_layout(plan["rooms"], sides=["bottom"], scale=0.1)
    detalle = next(c for c in r["chains"] if c["kind"] == "detalle")
    cortes = detalle["positions"]
    # Abajo solo apoyan SALA (0..4) y COMEDOR (4..8): la cadena tiene que
    # ser 0 | 4 | 8, sin el 3.5 ni el 4.5 del pasillo, que esta 4 m arriba.
    check("la cadena de abajo es la del pano de abajo", cortes == [0.0, 4.0, 8.0],
          str(cortes))
    tramos = [round(b - a, 2) for a, b in zip(cortes, cortes[1:])]
    check("no quedan tramos de 0.50 apretados",
          not any(abs(t - 0.5) < 1e-6 for t in tramos), str(tramos))


def test_las_cotas_no_se_enciman() -> None:
    """La prueba que importa: dibujar + acotar y que check_annotations
    salga limpio. Es lo que garantiza que el offset se apila solo."""
    preview.DRAWN.clear()
    space.clear()
    plan = rules.suggest_layout(9.0, 18.0, bedrooms=3, bathrooms=2)
    arch.draw_layout(plan["rooms"], plan["doors"], plan["windows"])
    arch.dimension_layout(plan["rooms"], sides=["bottom", "left", "top"],
                          scale=0.1)
    chk = rules.check_annotations()
    check("con cotas en tres lados nada se encima", chk["ok"],
          str(chk["problems"]))


def test_funde_fronteras_muy_juntas() -> None:
    """Dos fronteras a 5 cm darian una cota ilegible: se funden."""
    preview.DRAWN.clear()
    space.clear()
    rooms = [{"name": "A", "x0": 0, "y0": 0, "x1": 3.0, "y1": 3},
             {"name": "B", "x0": 3.05, "y0": 0, "x1": 6.0, "y1": 3}]
    r = arch.dimension_layout(rooms, sides=["bottom"], scale=0.1)
    check("3.00 y 3.05 se funden en un corte", len(r["xCuts"]) == 3,
          str(r["xCuts"]))
    check("y se queda el ultimo del grupo", 3.05 in r["xCuts"],
          str(r["xCuts"]))


def test_dimension_layout_errores() -> None:
    try:
        arch.dimension_layout([])
    except ValueError as exc:
        check("sin rooms se niega", "room" in str(exc), str(exc))
    else:
        check("sin rooms se niega", False, "no dio error")
    try:
        arch.dimension_layout([{"name": "A", "x0": 0, "y0": 0,
                                "x1": 1, "y1": 1}], sides=["diagonal"])
    except ValueError as exc:
        check("un side invalido se niega", "side" in str(exc), str(exc))
    else:
        check("un side invalido se niega", False, "no dio error")


def main() -> int:
    for fn in [test_dibuja_el_partido_completo, test_toda_la_grilla_se_dibuja,
               test_frontera_compartida_una_sola_vez,
               test_puerta_sin_posicion_avisa,
               test_tool_del_server_rotula_y_verifica,
               test_remata_los_encuentros,
               test_ningun_partido_deja_muros_sueltos_ni_machones,
               test_acota_el_partido_solo, test_cada_lado_acota_su_propio_pano,
               test_las_cotas_no_se_enciman,
               test_funde_fronteras_muy_juntas,
               test_dimension_layout_errores]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: del lote al plano dibujado sin calcular un solo muro a mano.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
