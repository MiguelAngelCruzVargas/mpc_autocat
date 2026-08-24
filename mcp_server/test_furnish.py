"""Tests del amueblado automático. NO necesita AutoCAD.

Lo que fijan, en orden de importancia:

  - Ningún mueble contra el muro donde abre una puerta. Una cama tapando
    la puerta de la recámara es el error que hace que un plano amueblado
    se vea peor que uno vacío.
  - Lo que no entra NO se dibuja. Meter una cama matrimonial en un cuarto
    de 2.40 es dibujar algo que en obra no existe.
  - En la cocina, la estufa y el fregadero SEPARADOS: pegados no queda
    superficie de trabajo entre los dos.
  - Todo mueble cae DENTRO de su recinto. Con cuatro rotaciones distintas
    y el punto de inserción en la esquina, un signo cambiado manda el
    mueble al cuarto de al lado y no se ve hasta abrir el DWG.

Uso:  python test_furnish.py
"""
from __future__ import annotations

import sys

import preview

preview.install()

import furniture as fur  # noqa: E402
import rules             # noqa: E402
import space             # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def limpiar() -> None:
    preview.DRAWN.clear()
    space.clear()
    fur.reset_footprints()


def test_colocacion_contra_los_cuatro_muros() -> None:
    """La cuenta que sostiene todo: la pieza tiene que quedar DENTRO del
    recinto y pegada al muro, en las cuatro rotaciones."""
    caja = (0.0, 0.0, 4.0, 3.0)
    for muro, esperado in (
            ("bottom", (1.0, 0.0, 3.0, 0.6)),
            ("top", (1.0, 2.4, 3.0, 3.0)),
            ("left", (0.0, 0.5, 0.6, 2.5)),
            ("right", (3.4, 0.5, 4.0, 2.5))):
        centro = fur._centro_muro(muro, caja)
        _x, _y, _rot, huella = fur._contra_muro(muro, caja, centro, 2.0, 0.6)
        ok = all(abs(a - b) < 1e-9 for a, b in zip(huella, esperado))
        check(f"apoyada contra {muro}", ok, f"{huella} != {esperado}")


def test_no_amuebla_el_muro_de_la_puerta() -> None:
    limpiar()
    rooms = [{"name": "RECÁMARA 1", "x0": 0, "y0": 0, "x1": 3.5, "y1": 4.0}]
    # Puerta en el muro de abajo, que es donde iria la cama por ser el
    # muro mas largo empatado.
    doors = [{"from": "PASILLO", "to": "RECÁMARA 1", "width": 0.8,
              "x": 1.75, "y": 0.0}]
    r = fur.suggest_furniture(rooms, doors, draw=False)
    camas = [p for p in r["items"] if p["type"] in ("bed", "single_bed")]
    check("pone una cama", len(camas) == 1, str(r["items"]))
    if camas:
        # Con la puerta abajo, la cabecera NO puede estar en y=0.
        check("la cama no se apoya en el muro de la puerta",
              abs(camas[0]["y"] - 0.0) > 1e-6 or camas[0]["rotation_deg"] != 0.0,
              str(camas[0]))


def test_cama_matrimonial_o_individual_segun_quepa() -> None:
    limpiar()
    grande = [{"name": "RECÁMARA PRINCIPAL", "x0": 0, "y0": 0,
               "x1": 3.5, "y1": 4.0}]
    r = fur.suggest_furniture(grande, [], draw=False)
    tipos = [p["type"] for p in r["items"]]
    check("en un cuarto grande va matrimonial", "bed" in tipos, str(tipos))

    limpiar()
    # 2.60 x 2.70 de EJE a eje -> 2.45 x 2.55 utiles descontando el medio
    # muro de cada lado. La matrimonial pide 2.60 de fondo (2.00 + 0.60 de
    # paso) y no entra; la individual pide 2.50 y entra justo.
    angosto = [{"name": "RECÁMARA 2", "x0": 0, "y0": 0, "x1": 2.6, "y1": 2.7}]
    r = fur.suggest_furniture(angosto, [], draw=False)
    tipos = [p["type"] for p in r["items"]]
    check("en uno chico va individual",
          "single_bed" in tipos and "bed" not in tipos, str(tipos))


def test_lo_que_no_entra_no_se_dibuja() -> None:
    limpiar()
    minusculo = [{"name": "RECÁMARA 3", "x0": 0, "y0": 0, "x1": 1.4,
                  "y1": 1.4}]
    r = fur.suggest_furniture(minusculo, [], draw=False)
    check("no mete una cama donde no cabe", r["count"] == 0, str(r["items"]))
    check("y lo reporta con motivo",
          any("cama" in s["problem"] for s in r["skipped"]), str(r["skipped"]))


def test_cocina_separa_estufa_y_fregadero() -> None:
    limpiar()
    cocina = [{"name": "COCINA", "x0": 0, "y0": 0, "x1": 3.5, "y1": 3.0}]
    r = fur.suggest_furniture(cocina, [], draw=False)
    tipos = [p["type"] for p in r["items"]]
    check("pone mesada, fregadero y estufa",
          {"counter", "kitchen_sink", "stove"} <= set(tipos), str(tipos))
    sink = next(p for p in r["items"] if p["type"] == "kitchen_sink")
    stove = next(p for p in r["items"] if p["type"] == "stove")
    sep = abs(sink["x"] - stove["x"]) + abs(sink["y"] - stove["y"])
    check("y no quedan pegados", sep >= 0.80, f"separacion {sep:.2f}")


def test_bano_usa_muros_distintos() -> None:
    limpiar()
    bano = [{"name": "BAÑO", "x0": 0, "y0": 0, "x1": 2.4, "y1": 2.2}]
    r = fur.suggest_furniture(bano, [], draw=False)
    tipos = [p["type"] for p in r["items"]]
    check("pone wc y lavabo", {"wc", "lavatory"} <= set(tipos), str(tipos))
    rots = {p["type"]: p["rotation_deg"] for p in r["items"]}
    check("el wc y el lavabo no comparten muro",
          rots.get("wc") != rots.get("lavatory"), str(rots))


def test_todo_cae_dentro_de_su_recinto() -> None:
    """La prueba de fuego contra un partido completo: ningun mueble puede
    salirse del ambiente al que pertenece."""
    limpiar()
    plan = rules.suggest_layout(9.0, 18.0, bedrooms=3, bathrooms=2)
    r = fur.suggest_furniture(plan["rooms"], plan["doors"], draw=False)
    check("amuebla varios ambientes", len(r["byRoom"]) >= 5, str(r["byRoom"]))

    # 'placements' dice a que ambiente pertenece CADA pieza: con dos banos
    # y tres recamaras, mirar solo el tipo no alcanza.
    por_nombre = {rm["name"]: rm for rm in plan["rooms"]}
    fuera = []
    for p in r["placements"]:
        rm = por_nombre[p["room"]]
        bx0, by0, bx1, by1 = p["box"]
        if not (rm["x0"] - 0.01 <= bx0 and bx1 <= rm["x1"] + 0.01
                and rm["y0"] - 0.01 <= by0 and by1 <= rm["y1"] + 0.01):
            fuera.append((p["room"], p["type"], p["box"]))
    check("ninguna huella se sale de su ambiente", not fuera, str(fuera[:4]))
    check("cada pieza sabe de que ambiente es",
          len(r["placements"]) == r["count"], str(len(r["placements"])))


def test_ningun_mueble_invade_el_muro() -> None:
    """El defecto que se vio en la primera casa amueblada: la mesada de la
    cocina cruzaba el muro y salia del otro lado. Pasaba porque 'rooms'
    viene en EJES y apoyar ahi mete el mueble media pared adentro."""
    limpiar()
    # Dos cuartos que comparten la frontera x=4 (el eje del divisorio).
    rooms = [{"name": "COCINA", "x0": 0, "y0": 0, "x1": 4, "y1": 3.5},
             {"name": "RECÁMARA 1", "x0": 4, "y0": 0, "x1": 8, "y1": 3.5}]
    r = fur.suggest_furniture(rooms, [], draw=False,
                              interior_thickness=0.10,
                              exterior_thickness=0.15)
    invasores = []
    for p in r["placements"]:
        bx0, by0, bx1, by1 = p["box"]
        if p["room"] == "COCINA" and bx1 > 4.0 - 0.05 + 1e-9:
            invasores.append((p["type"], "cruza el divisorio", p["box"]))
        if p["room"] == "RECÁMARA 1" and bx0 < 4.0 + 0.05 - 1e-9:
            invasores.append((p["type"], "cruza el divisorio", p["box"]))
        # Y ninguno puede meterse en el muro EXTERIOR (0.15 -> 0.075).
        if bx0 < 0.075 - 1e-9 or bx1 > 8.0 - 0.075 + 1e-9:
            invasores.append((p["type"], "invade el perimetro", p["box"]))
        if by0 < 0.075 - 1e-9 or by1 > 3.5 - 0.075 + 1e-9:
            invasores.append((p["type"], "invade el perimetro", p["box"]))
    check("ningun mueble se mete en el espesor del muro", not invasores,
          str(invasores[:3]))
    check("y aun asi amueblo los dos ambientes", len(r["byRoom"]) == 2,
          str(r["byRoom"]))


def test_ningun_mueble_se_pisa_con_otro() -> None:
    """Dos muebles superpuestos dibujan sus dos contornos: en pantalla se
    ven LINEAS DOBLES y el plano parece mal dibujado. Es lo que pasaba con
    la mesada de la cocina, que se dibujaba entera abajo del fregadero y
    de la estufa; ahora va interrumpida entre los aparatos."""
    limpiar()
    plan = rules.suggest_layout(8.0, 16.0, bedrooms=3, bathrooms=2)
    r = fur.suggest_furniture(plan["rooms"], plan["doors"], draw=False)
    choques = []
    for i, a in enumerate(r["placements"]):
        for b in r["placements"][i + 1:]:
            if a["room"] != b["room"]:
                continue
            ax0, ay0, ax1, ay1 = a["box"]
            bx0, by0, bx1, by1 = b["box"]
            dx = min(ax1, bx1) - max(ax0, bx0)
            dy = min(ay1, by1) - max(ay0, by0)
            if dx > 1e-6 and dy > 1e-6:
                choques.append((a["room"], a["type"], b["type"],
                                round(dx, 3), round(dy, 3)))
    check("ningun par de muebles se encima", not choques, str(choques[:3]))


def test_la_mesada_se_interrumpe_en_los_aparatos() -> None:
    limpiar()
    cocina = [{"name": "COCINA", "x0": 0, "y0": 0, "x1": 4.0, "y1": 3.0}]
    r = fur.suggest_furniture(cocina, [], draw=False)
    tipos = [p["type"] for p in r["items"]]
    check("la mesada sale en varios tramos", tipos.count("counter") >= 2,
          str(tipos))
    check("con su fregadero y su estufa",
          "kitchen_sink" in tipos and "stove" in tipos, str(tipos))
    # Y ningun tramo de mesada pisa un aparato.
    mesadas = [p for p in r["placements"] if p["type"] == "counter"]
    aparatos = [p for p in r["placements"]
                if p["type"] in ("kitchen_sink", "stove")]
    pisados = []
    for m in mesadas:
        for a in aparatos:
            dx = min(m["box"][2], a["box"][2]) - max(m["box"][0], a["box"][0])
            dy = min(m["box"][3], a["box"][3]) - max(m["box"][1], a["box"][1])
            if dx > 1e-6 and dy > 1e-6:
                pisados.append((m["box"], a["type"]))
    check("ningun tramo de mesada queda debajo de un aparato", not pisados,
          str(pisados[:2]))


def test_dibuja_de_verdad_y_deja_huella() -> None:
    limpiar()
    rooms = [{"name": "RECÁMARA 1", "x0": 0, "y0": 0, "x1": 3.5, "y1": 4.0}]
    r = fur.suggest_furniture(rooms, [], draw=True)
    check("dibuja las piezas", r["placed"]["count"] == r["count"],
          str(r.get("placed")))
    check("y quedan huellas para que label_rooms las esquive",
          len(space.FOOTPRINTS) >= r["count"], str(len(space.FOOTPRINTS)))


def test_errores_claros() -> None:
    try:
        fur.suggest_furniture([{"name": "X"}], [], draw=False)
    except ValueError as exc:
        check("un room incompleto se niega", "x0" in str(exc), str(exc))
    else:
        check("un room incompleto se niega", False, "no dio error")


def main() -> int:
    for fn in [test_colocacion_contra_los_cuatro_muros,
               test_no_amuebla_el_muro_de_la_puerta,
               test_cama_matrimonial_o_individual_segun_quepa,
               test_lo_que_no_entra_no_se_dibuja,
               test_cocina_separa_estufa_y_fregadero,
               test_bano_usa_muros_distintos,
               test_todo_cae_dentro_de_su_recinto,
               test_ningun_mueble_invade_el_muro,
               test_ningun_mueble_se_pisa_con_otro,
               test_la_mesada_se_interrumpe_en_los_aparatos,
               test_dibuja_de_verdad_y_deja_huella,
               test_errores_claros]:
        print(fn.__name__)
        fn()

    if FAILED:
        print("\n%d FALLAS:" % len(FAILED))
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK: el amueblado respeta puertas, muros y lo que de verdad cabe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
