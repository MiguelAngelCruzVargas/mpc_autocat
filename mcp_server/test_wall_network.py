"""Tests de la red de muros: que cada encuentro quede rematado, sin AutoCAD.

El defecto que esto cubre se veía en todo plano con muros de llamadas
distintas: líneas que se cruzan y sobresalen en cada encuentro ("le sobran
puntas"), y aun fusionando, la esquina exterior de cada L mordida por un
cuadrito de medio espesor. Las áreas esperadas son analíticas: si el
contorno tiene una punta de más o un cuadrito de menos, el área no cierra.

Uso:  python test_wall_network.py
"""
from __future__ import annotations

import math
import sys

import preview

preview.install()

import arch          # noqa: E402
import rules         # noqa: E402
import space         # noqa: E402
import wall_network as wn  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detalle: str = "") -> None:
    if not ok:
        FAILED.append(f"{name}: {detalle}")
    print(("  ok  " if ok else " FALLA ") + name
          + (f" -- {detalle}" if not ok else ""))


def cerca(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def vertices(r: dict) -> set[tuple[float, float]]:
    return {(round(p[0], 6), round(p[1], 6)) for l in r["loops"] for p in l}


def test_esquina_en_l_cerrada() -> None:
    r = wn.resolve([{"points": [[0, 0], [4, 0]], "thickness": 0.15},
                    {"points": [[0, 0], [0, 3]], "thickness": 0.15}])
    check("L: un solo contorno", len(r["loops"]) == 1, str(r["loops"]))
    check("L: area = espesor x largos (ni punta ni mordida)",
          cerca(r["area"], 0.15 * 7), str(r["area"]))
    check("L: la arista exterior llega al vertice (-0.075, -0.075)",
          (-0.075, -0.075) in vertices(r), str(vertices(r)))
    check("L: seis vertices, ni uno de mas",
          len(r["loops"][0]) == 6, str(r["loops"][0]))


def test_l_de_espesores_distintos() -> None:
    r = wn.resolve([{"points": [[0, 0], [4, 0]], "thickness": 0.20},
                    {"points": [[0, 0], [0, 3]], "thickness": 0.10}])
    check("L mixta: esquina exterior en (-0.05, -0.10)",
          (-0.05, -0.1) in vertices(r), str(vertices(r)))
    # Rectangulo de abajo entero + el de arriba desde la cara superior.
    esperado = 0.20 * 4.05 + 0.10 * (3 - 0.10)
    check("L mixta: area exacta", cerca(r["area"], esperado),
          f"{r['area']} vs {esperado}")


def test_t_remata_contra_la_cara() -> None:
    r = wn.resolve([{"points": [[0, 0], [6, 0]], "thickness": 0.15},
                    {"points": [[3, 0], [3, 3]], "thickness": 0.10}])
    check("T: un solo contorno", len(r["loops"]) == 1, str(len(r["loops"])))
    check("T: area exacta", cerca(r["area"], 6 * 0.15 + 0.10 * 2.925),
          str(r["area"]))
    abajo = [p for p in vertices(r) if p[1] < 0]
    check("T: la cara de abajo sigue recta (nada asoma)",
          all(cerca(p[1], -0.075) for p in abajo), str(abajo))
    check("T: el divisorio arranca en la cara, no en el eje",
          (2.95, 0.075) in vertices(r) and (3.05, 0.075) in vertices(r),
          str(sorted(vertices(r))))


def test_t_inclinada_no_asoma_del_otro_lado() -> None:
    """Un muro grueso que llega en diagonal a uno fino: con el extremo a
    escuadra en el eje, una esquina asomaba por la cara de enfrente."""
    d = 3.0 / math.sqrt(2)
    r = wn.resolve([{"points": [[0, 0], [6, 0]], "thickness": 0.10},
                    {"points": [[3, 0], [3 + d, d]], "thickness": 0.20}])
    peor = min(p[1] for p in vertices(r))
    check("T a 45: nada por debajo de la cara inferior del muro fino",
          peor >= -0.05 - 1e-9, str(peor))


def test_cruce() -> None:
    r = wn.resolve([{"points": [[0, 0], [6, 0]], "thickness": 0.15},
                    {"points": [[3, -3], [3, 3]], "thickness": 0.15}])
    check("cruce: un contorno de 12 vertices",
          len(r["loops"]) == 1 and len(r["loops"][0]) == 12,
          str([len(l) for l in r["loops"]]))
    check("cruce: area sin contar dos veces el centro",
          cerca(r["area"], 2 * 6 * 0.15 - 0.15 * 0.15), str(r["area"]))


def test_anillo_cerrado_con_hueco() -> None:
    r = wn.resolve([{"points": [[0, 0], [5, 0], [5, 4], [0, 4]],
                     "thickness": 0.15, "closed": True}])
    check("anillo: contorno exterior + interior", len(r["loops"]) == 2,
          str(len(r["loops"])))
    check("anillo: el hueco resta", cerca(r["area"], 5.15 * 4.15 - 4.85 * 3.85),
          str(r["area"]))


def test_angulo_cualquiera() -> None:
    for grados in (30, 60, 120, 150):
        a = math.radians(grados)
        r = wn.resolve([{"points": [[0, 0], [4, 0]], "thickness": 0.15},
                        {"points": [[0, 0], [3 * math.cos(a), 3 * math.sin(a)]],
                         "thickness": 0.15}])
        # A inglete, lo que gana la cara de afuera lo pierde la de adentro.
        check(f"L a {grados}: un contorno con area espesor x largos",
              len(r["loops"]) == 1 and cerca(r["area"], 0.15 * 7),
              f"{len(r['loops'])} lazos, {r['area']}")


def test_angulo_agudo_se_bisela() -> None:
    a = math.radians(8)
    r = wn.resolve([{"points": [[0, 0], [4, 0]], "thickness": 0.15},
                    {"points": [[0, 0], [4 * math.cos(a), 4 * math.sin(a)]],
                     "thickness": 0.15}])
    lejos = max(math.hypot(*p) for p in vertices(r) if p[0] < 0.5)
    check("agudo: sin espina (bisel dentro del limite de inglete)",
          lejos <= wn.MITER_LIMIT * 0.075 + 1e-9, str(lejos))


def test_casi_t_se_ajusta_y_se_informa() -> None:
    r = wn.resolve([{"points": [[0, 0], [6, 0]], "thickness": 0.15},
                    {"points": [[3, 0.02], [3, 3]], "thickness": 0.10}])
    check("casi-T: se ajusta y queda la T exacta",
          len(r["snapped"]) == 1 and cerca(r["area"], 6 * 0.15 + 0.10 * 2.925),
          f"{r['snapped']} / {r['area']}")
    r0 = wn.resolve([{"points": [[0, 0], [6, 0]], "thickness": 0.15},
                     {"points": [[3, 0.02], [3, 3]], "thickness": 0.10}],
                    snap=0)
    check("snap=0 no mueve nada", not r0["snapped"], str(r0["snapped"]))


def test_extremo_casi_en_esquina() -> None:
    r = wn.resolve([{"points": [[0, 0], [4, 0]], "thickness": 0.15},
                    {"points": [[0.01, -0.01], [0, 3]], "thickness": 0.15}])
    check("L mal tipeada: se junta en la esquina",
          len(r["snapped"]) == 1 and (-0.075, -0.075) in vertices(r),
          f"{r['snapped']}")


def test_muros_sueltos() -> None:
    r = wn.resolve([{"points": [[0, 0], [4, 0]], "thickness": 0.15},
                    {"points": [[0, 2], [4, 2]], "thickness": 0.15}])
    check("dos muros que no se tocan: dos contornos",
          len(r["loops"]) == 2 and cerca(r["area"], 2 * 0.6), str(r["area"]))


def test_arch_red_con_vanos() -> None:
    preview.DRAWN.clear()
    space.clear()
    r = arch.create_wall_network([
        {"points": [[0, 0], [6, 0], [6, 4], [0, 4]], "thickness": 0.15,
         "closed": True,
         "openings": [{"segment": 0, "offset": 1.5, "width": 0.9}]},
        {"points": [[3, 0], [3, 4]], "thickness": 0.10,
         "openings": [{"distance": 2.0, "width": 0.8}]},
    ])
    exterior = 6.15 * 4.15 - 5.85 * 3.85
    divisorio = 0.10 * 3.85
    esperado = exterior + divisorio - 0.9 * 0.15 - 0.8 * 0.10
    check("red: area con los dos vanos descontados",
          cerca(r["masonryArea"], esperado),
          f"{r['masonryArea']} vs {esperado}")
    puertas = [e for e in preview.DRAWN if e["cmd"] == "create_arc"]
    check("red: una puerta por vano", len(puertas) == 2, str(len(puertas)))
    check("red: sin avisos", not r.get("warnings"), str(r.get("warnings")))
    chk = rules.check_walls(walls=r["axes"])
    check("red: los ejes que devuelve pasan check_walls", chk["ok"],
          str(chk["problems"]))
    barreras = space.barriers()
    check("red: la huella va por tramo, no por anillo (place_labels)",
          barreras and max(b["x1"] - b["x0"] for b in barreras) <= 6.2
          and max(b["y1"] - b["y0"] for b in barreras) <= 4.2
          and not any(b["x1"] - b["x0"] > 1 and b["y1"] - b["y0"] > 1
                      for b in barreras),
          str(barreras))


def test_avisa_vano_en_un_encuentro() -> None:
    preview.DRAWN.clear()
    space.clear()
    r = arch.create_wall_network([
        {"points": [[0, 0], [6, 0]], "thickness": 0.15,
         "openings": [{"distance": 3.0, "width": 0.9}]},
        {"points": [[3, 0], [3, 3]], "thickness": 0.10}])
    check("avisa el vano donde llega otro muro",
          any("cae justo donde llega el muro #2" in w
              for w in r.get("warnings", [])), str(r.get("warnings")))


def test_arch_errores_claros() -> None:
    for walls, frag in (([], "al menos un muro"),
                        ([{"points": [[0, 0]], "thickness": 0.15}], "points"),
                        ([{"points": [[0, 0], [1, 0]], "thickness": 0}],
                         "thickness"),
                        ([{"points": [[0, 0], [2, 0]], "thickness": 0.15,
                           "openings": [{"distance": 1.9, "width": 0.9}]}],
                         "se sale")):
        try:
            arch.create_wall_network(walls)
            check(f"error claro ({frag})", False, "no fallo")
        except ValueError as exc:
            check(f"error claro ({frag})", frag in str(exc), str(exc))


def main() -> int:
    for t in (test_esquina_en_l_cerrada,
              test_l_de_espesores_distintos,
              test_t_remata_contra_la_cara,
              test_t_inclinada_no_asoma_del_otro_lado,
              test_cruce,
              test_anillo_cerrado_con_hueco,
              test_angulo_cualquiera,
              test_angulo_agudo_se_bisela,
              test_casi_t_se_ajusta_y_se_informa,
              test_extremo_casi_en_esquina,
              test_muros_sueltos,
              test_arch_red_con_vanos,
              test_avisa_vano_en_un_encuentro,
              test_arch_errores_claros):
        print(t.__name__)
        t()
    if FAILED:
        print(f"\n{len(FAILED)} FALLAS:")
        for f in FAILED:
            print(" - " + f)
        return 1
    print("\nOK: cada encuentro de muros queda rematado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
