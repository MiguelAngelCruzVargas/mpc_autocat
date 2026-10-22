"""Tests de query_entities / aggregate_entities / describe_entity_fields
(consulta.py + server.py) contra el socket mockeado. NO necesita AutoCAD.

Verifica el lenguaje de filtro, que lo barato no pida detalle, que el detalle
se pida en lotes y solo de lo que sobrevive, que un resultado parcial se
avise (nunca se corte en silencio) y las agregaciones con grupos.

Uso:  python test_consulta.py
"""
from __future__ import annotations

import consulta
import server

FAILED: list[str] = []


def check(name: str, got, expected) -> None:
    ok = got == expected
    if not ok:
        FAILED.append(f"{name}: esperaba {expected!r}, obtuve {got!r}")
    print(("  ok  " if ok else " FALLA ") + name)


def aprox(name: str, got, expected, tol=1e-9) -> None:
    ok = got is not None and abs(got - expected) <= tol
    if not ok:
        FAILED.append(f"{name}: esperaba ~{expected!r}, obtuve {got!r}")
    print(("  ok  " if ok else " FALLA ") + name)


# Un dibujo chico: 3 líneas en MUROS, 1 en EJES, 2 polilíneas cerradas, 1 abierta,
# 2 textos y un bloque.
ENTS = [
    {"handle": "A1", "type": "Line", "layer": "MUROS", "box": [0, 0, 4, 0]},
    {"handle": "A2", "type": "Line", "layer": "MUROS", "box": [0, 0, 0, 3]},
    {"handle": "A3", "type": "Line", "layer": "MUROS", "box": [0, 0, 6, 0]},
    {"handle": "A4", "type": "Line", "layer": "EJES", "box": [0, 0, 10, 0]},
    {"handle": "B1", "type": "Polyline", "layer": "LOSAS", "box": [0, 0, 4, 3]},
    {"handle": "B2", "type": "Polyline", "layer": "LOSAS", "box": [0, 0, 5, 4]},
    {"handle": "B3", "type": "Polyline", "layer": "LOSAS", "box": [0, 0, 1, 1]},
    {"handle": "T1", "type": "DBText", "layer": "TEXTOS", "text": "N.P.T. +0.00",
     "box": [1, 1, 2, 1.2]},
    {"handle": "T2", "type": "MText", "layer": "TEXTOS", "text": "COCINA",
     "box": [3, 1, 4, 1.2]},
    {"handle": "K1", "type": "BlockReference", "layer": "PUERTAS", "box": [0, 0, 1, 0.1]},
]
DETALLE = {
    "A1": {"handle": "A1", "type": "Line", "layer": "MUROS", "length": 4.0, "colorIndex": 7},
    "A2": {"handle": "A2", "type": "Line", "layer": "MUROS", "length": 3.0, "colorIndex": 7},
    "A3": {"handle": "A3", "type": "Line", "layer": "MUROS", "length": 6.0, "colorIndex": 256},
    "A4": {"handle": "A4", "type": "Line", "layer": "EJES", "length": 10.0, "colorIndex": 32},
    "B1": {"handle": "B1", "type": "Polyline", "layer": "LOSAS", "closed": True,
           "area": 12.0, "length": 14.0},
    "B2": {"handle": "B2", "type": "Polyline", "layer": "LOSAS", "closed": True,
           "area": 20.0, "length": 18.0},
    "B3": {"handle": "B3", "type": "Polyline", "layer": "LOSAS", "closed": False,
           "area": 0.0, "length": 1.0},
    "K1": {"handle": "K1", "type": "BlockReference", "layer": "PUERTAS",
           "blockName": "PUERTA-90", "attributes": {"TAG": "P1"}},
}


class Mock:
    def __init__(self, entidades=ENTS, detalle=DETALLE):
        self.entidades, self.detalle = entidades, detalle
        self.llamadas: list[tuple[str, dict]] = []

    def __call__(self, cmd, params=None):
        params = params or {}
        self.llamadas.append((cmd, params))
        if cmd == "list_entities":
            r = [e for e in self.entidades
                 if not params.get("type") or e["type"].lower() == params["type"].lower()]
            r = r[:params.get("limit", 200)]
            if not params.get("includeExtents"):
                r = [{k: v for k, v in e.items() if k != "box"} for e in r]
            if not params.get("includeText"):
                r = [{k: v for k, v in e.items() if k != "text"} for e in r]
            return {"entities": r, "count": len(r)}
        if cmd == "batch":
            res = []
            for c in params["commands"]:
                assert c["cmd"] == "get_entity"
                d = self.detalle.get(c["params"]["handle"])
                res.append({"id": c["id"], "ok": d is not None,
                            **({"result": d} if d is not None else {"error": "no existe"})})
            return {"results": res, "errors": 0}
        raise AssertionError(f"comando no mockeado: {cmd}")

    def n(self, cmd):
        return sum(1 for c, _ in self.llamadas if c == cmd)


def con_mock(fn):
    real = server.acad.call
    m = Mock()
    server.acad.call = m
    try:
        fn(m)
    finally:
        server.acad.call = real


# ---------------------------------------------------------------- filtro

def test_parseo_del_filtro() -> None:
    g = consulta.parsear_filtro("a = 1 AND b > 2 OR c contains 'x y'")
    check("dos grupos OR", len(g), 2)
    check("AND liga mas fuerte: primer grupo 2 condiciones", len(g[0]), 2)
    check("valor con comillas y espacios", g[1][0], ("c", "contains", "x y"))
    check("sin filtro -> sin grupos", consulta.parsear_filtro("  "), [])
    check("AND dentro de comillas no parte",
          len(consulta.parsear_filtro("text = 'A AND B'")[0]), 1)
    for malo in ("layer", "layer = MUROS AND", "text = 'abierta", "x ~ 3"):
        try:
            consulta.parsear_filtro(malo)
            check(f"filtro invalido rechazado: {malo!r}", False, True)
        except consulta.ConsultaError:
            check(f"filtro invalido rechazado: {malo!r}", True, True)


def test_comparaciones() -> None:
    e = {"layer": "Muros", "length": 4.0, "closed": True, "center": [1.0, 2.0],
         "attributes": {"TAG": "P1"}}
    c = consulta.cumple
    check("= sin distinguir mayusculas", c(e, ("layer", "=", "MUROS")), True)
    check("!= texto", c(e, ("layer", "!=", "MUROS")), False)
    check("> numerico", c(e, ("length", ">", 3.5)), True)
    check("<= numerico (borde)", c(e, ("length", "<=", 4.0)), True)
    check("true como booleano", c(e, ("closed", "=", True)), True)
    check("ruta con indice", c(e, ("center.1", "=", 2.0)), True)
    check("ruta en diccionario", c(e, ("attributes.TAG", "=", "p1")), True)
    check("contains", c(e, ("layer", "contains", "uro")), True)
    check("startswith", c(e, ("layer", "startswith", "mu")), True)
    check("endswith", c(e, ("layer", "endswith", "ros")), True)
    check("campo que falta no cumple =", c(e, ("area", "=", 0.0)), False)
    check("campo que falta no cumple !=", c(e, ("area", "!=", 5.0)), False)
    check("= null en campo faltante", c(e, ("area", "=", None)), True)
    check("!= null en campo presente", c(e, ("length", "!=", None)), True)
    try:
        c(e, ("layer", ">", 3.0))
        check("comparar texto con > se rechaza", False, True)
    except consulta.ConsultaError:
        check("comparar texto con > se rechaza", True, True)


# ---------------------------------------------------------------- consulta

def test_consulta_barata_no_pide_detalle(m: Mock) -> None:
    r = server.query_entities(entity_type="Line", filter="layer = MUROS")
    check("3 lineas en MUROS", r["matches"], 3)
    check("sin viaje de detalle", m.n("batch"), 0)
    check("un solo list_entities", m.n("list_entities"), 1)


def test_caja_se_pide_sola(m: Mock) -> None:
    r = server.query_entities(filter="bboxArea > 10", fields=["layer", "bboxArea"])
    check("pidio la caja", m.llamadas[0][1].get("includeExtents"), True)
    check("solo B1 (3x4) y B2 (5x4) pasan",
          sorted(e["handle"] for e in r["entities"]), ["B1", "B2"])
    check("B2 (5x4=20) pasa", any(e["handle"] == "B2" for e in r["entities"]), True)
    check("B3 (1x1) no pasa", any(e["handle"] == "B3" for e in r["entities"]), False)
    check("sin detalle", m.n("batch"), 0)


def test_texto_se_pide_solo_si_se_usa(m: Mock) -> None:
    r = server.query_entities(filter="text contains npt")
    check("sin coincidencia con 'npt' pegado", r["matches"], 0)
    r = server.query_entities(filter="text contains 'N.P.T.'", fields=["text"])
    check("encuentra el texto de nivel", [e["handle"] for e in r["entities"]], ["T1"])
    check("trajo includeText", m.llamadas[-1][1].get("includeText"), True)


def test_detalle_solo_de_lo_que_sobrevive(m: Mock) -> None:
    r = server.query_entities(
        filter="type = Polyline AND closed = true AND area > 12",
        fields=["area", "layer"])
    check("solo B2 cumple", [e["handle"] for e in r["entities"]], ["B2"])
    check("el tipo se filtro en el plugin", m.llamadas[0][1].get("type"), "Polyline")
    pedidos = [c["id"] for cmd, p in m.llamadas if cmd == "batch" for c in p["commands"]]
    check("detalle solo de las 3 polilineas, no de todo el dibujo", sorted(pedidos),
          ["B1", "B2", "B3"])
    check("un solo viaje de detalle", m.n("batch"), 1)
    check("devuelve el campo pedido", r["entities"][0]["area"], 20.0)


def test_condicion_barata_previa_acota_el_detalle(m: Mock) -> None:
    server.query_entities(filter="layer = MUROS AND length > 3.5")
    pedidos = [c["id"] for cmd, p in m.llamadas if cmd == "batch" for c in p["commands"]]
    check("solo las 3 lineas de MUROS se leen en detalle", sorted(pedidos),
          ["A1", "A2", "A3"])


def test_or_obliga_a_leer_todo(m: Mock) -> None:
    r = server.query_entities(filter="layer = EJES OR length > 5")
    pedidos = [c["id"] for cmd, p in m.llamadas if cmd == "batch" for c in p["commands"]]
    check("con OR se leen todos los candidatos", len(pedidos), len(ENTS))
    check("resultado A3 (6) y A4 (EJES, 10), B2 (18 de perimetro) y B1 (14)",
          sorted(e["handle"] for e in r["entities"]), ["A3", "A4", "B1", "B2"])


def test_paginacion(m: Mock) -> None:
    r = server.query_entities(entity_type="Line", skip=1, take=2)
    check("matches es el total, no la pagina", r["matches"], 4)
    check("returned", r["returned"], 2)
    check("pagina correcta", [e["handle"] for e in r["entities"]], ["A2", "A3"])


def test_resultado_parcial_se_avisa(m: Mock) -> None:
    r = server.query_entities(filter="length > 0", hydrate_limit=3)
    check("parcial marcado", r.get("partial"), True)
    check("el aviso lo dice", any("PARCIAL" in n for n in r["notices"]), True)
    check("solo leyo el tope", m.llamadas[-1][1]["commands"].__len__(), 3)


def test_entidad_ilegible_se_informa(m: Mock) -> None:
    m.detalle = {k: v for k, v in DETALLE.items() if k != "A2"}
    r = server.query_entities(entity_type="Line", filter="length > 0")
    check("A2 omitida", "A2" not in [e["handle"] for e in r["entities"]], True)
    check("avisa cual no pudo leer", any("A2" in n for n in r["notices"]), True)


def test_tope_de_escaneo_se_avisa(m: Mock) -> None:
    r = server.query_entities(scan_limit=4)
    check("avisa que puede haber mas", any("tope del escaneo" in n for n in r["notices"]), True)


def test_error_de_filtro_no_revienta(m: Mock) -> None:
    r = server.query_entities(filter="layer =")
    check("devuelve error legible", "error" in r, True)
    check("no toco AutoCAD", m.n("list_entities"), 0)


# ---------------------------------------------------------------- agregados

def test_conteo_por_capa(m: Mock) -> None:
    r = server.aggregate_entities([{"type": "count", "group_by": "layer"}])
    g = r["results"][0]["groups"]
    check("MUROS primero (mas entidades)", g[0], {"group": "MUROS", "value": 3})
    check("LOSAS tambien 3 (orden estable por valor)", {x["group"]: x["value"] for x in g},
          {"MUROS": 3, "LOSAS": 3, "EJES": 1, "TEXTOS": 2, "PUERTAS": 1})
    check("conteo no necesita detalle", m.n("batch"), 0)


def test_conteo_simple_y_sin_especificar(m: Mock) -> None:
    r = server.aggregate_entities()
    check("un conteo total", r["results"][0]["value"], 10)
    r = server.aggregate_entities(entity_type="Line", filter="layer = MUROS")
    check("conteo con filtro", r["results"][0]["value"], 3)


def test_suma_de_largos_por_capa(m: Mock) -> None:
    r = server.aggregate_entities(
        [{"type": "sum", "field": "length", "group_by": "layer"}], entity_type="Line")
    g = {x["group"]: x["value"] for x in r["results"][0]["groups"]}
    aprox("metros de MUROS", g["MUROS"], 13.0)
    aprox("metros de EJES", g["EJES"], 10.0)
    check("ordenado de mayor a menor", r["results"][0]["groups"][0]["group"], "MUROS")


def test_estadisticos(m: Mock) -> None:
    r = server.aggregate_entities(
        [{"type": "avg", "field": "length"}, {"type": "min", "field": "length"},
         {"type": "max", "field": "length"}], entity_type="Line")
    aprox("promedio", r["results"][0]["value"], (4 + 3 + 6 + 10) / 4)
    aprox("minimo", r["results"][1]["value"], 3.0)
    aprox("maximo", r["results"][2]["value"], 10.0)
    check("un solo viaje de detalle para las tres", m.n("batch"), 1)


def test_minabs_maxabs() -> None:
    ents = [{"handle": "P1", "type": "X", "layer": "L"}, {"handle": "P2", "type": "X", "layer": "L"},
            {"handle": "P3", "type": "X", "layer": "L"}]
    det = {"P1": {"handle": "P1", "type": "X", "layer": "L", "slope": -5.0},
           "P2": {"handle": "P2", "type": "X", "layer": "L", "slope": 2.0},
           "P3": {"handle": "P3", "type": "X", "layer": "L", "slope": -1.0}}
    real = server.acad.call
    server.acad.call = Mock(ents, det)
    try:
        r = server.aggregate_entities([{"type": "maxabs", "field": "slope"},
                                       {"type": "minabs", "field": "slope"}])
        check("maxabs conserva el signo", r["results"][0]["value"], -5.0)
        check("minabs", r["results"][1]["value"], -1.0)
    finally:
        server.acad.call = real


def test_campo_no_numerico_se_salta_y_se_informa(m: Mock) -> None:
    r = server.aggregate_entities([{"type": "sum", "field": "length"}], entity_type="Line")
    check("ninguna se salta si todas tienen length", "skippedNonNumeric" in r["results"][0], False)
    r = server.aggregate_entities([{"type": "sum", "field": "area"}])
    check("las que no tienen area se informan", r["results"][0].get("skippedNonNumeric", 0) > 0, True)


def test_agregacion_invalida(m: Mock) -> None:
    for malo in ([{"type": "mediana", "field": "length"}], [{"type": "sum"}]):
        r = server.aggregate_entities(malo)
        check(f"rechaza {malo}", "error" in r, True)


def test_orden_por_grupo_y_ascendente(m: Mock) -> None:
    r = server.aggregate_entities([{"type": "count", "group_by": "layer",
                                    "order_by": "layer", "ascending": True}])
    check("alfabetico ascendente", [x["group"] for x in r["results"][0]["groups"]],
          ["EJES", "LOSAS", "MUROS", "PUERTAS", "TEXTOS"])


def test_grupo_por_campo_de_detalle(m: Mock) -> None:
    r = server.aggregate_entities([{"type": "count", "group_by": "blockName"}],
                                  entity_type="BlockReference")
    check("agrupa por nombre de bloque", r["results"][0]["groups"],
          [{"group": "PUERTA-90", "value": 1}])


# ---------------------------------------------------------------- esquema

def test_esquema() -> None:
    e = server.describe_entity_fields()
    check("lista los operadores", "contains" in e["operadores"], True)
    check("lista las agregaciones", "maxabs" in e["agregaciones"], True)
    e = server.describe_entity_fields("polyline")
    check("campos de Polyline sin distinguir mayusculas",
          "bulges" in e["detalle"]["por_tipo"]["Polyline"], True)
    e = server.describe_entity_fields("RotatedDimension")
    check("las cotas comparten la lista", "measurement" in e["detalle"]["por_tipo"]["Dimension"], True)
    e = server.describe_entity_fields("Spline")
    check("tipo sin lista: lo avisa", "aviso" in e["detalle"], True)


def main() -> int:
    test_parseo_del_filtro()
    test_comparaciones()
    for t in (test_consulta_barata_no_pide_detalle, test_caja_se_pide_sola,
              test_texto_se_pide_solo_si_se_usa, test_detalle_solo_de_lo_que_sobrevive,
              test_condicion_barata_previa_acota_el_detalle, test_or_obliga_a_leer_todo,
              test_paginacion, test_resultado_parcial_se_avisa,
              test_entidad_ilegible_se_informa, test_tope_de_escaneo_se_avisa,
              test_error_de_filtro_no_revienta, test_conteo_por_capa,
              test_conteo_simple_y_sin_especificar, test_suma_de_largos_por_capa,
              test_estadisticos, test_campo_no_numerico_se_salta_y_se_informa,
              test_agregacion_invalida, test_orden_por_grupo_y_ascendente,
              test_grupo_por_campo_de_detalle):
        con_mock(t)
    test_minabs_maxabs()
    test_esquema()
    if FAILED:
        print("\nFALLARON:")
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
