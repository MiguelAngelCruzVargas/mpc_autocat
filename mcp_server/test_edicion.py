"""Tests de trim_entity / extend_entity / fillet_entities / join_entities /
overkill_entities (edicion.py + server.py) contra el socket mockeado.
NO necesita AutoCAD.

La geometría la resuelve AutoCAD (se verifica en vivo); acá se verifica lo que
es de este lado: que se rechace antes de tocar AutoCAD lo que no tiene
sentido, que cada tool mande al plugin la operación y los parámetros
correctos, que espere el resultado, y que no se repita una operación que
tardó (repetirla la aplicaría dos veces).

Uso:  python test_edicion.py
"""
from __future__ import annotations

import edicion
import server
import session

FAILED: list[str] = []


def check(name: str, got, expected) -> None:
    ok = got == expected
    if not ok:
        FAILED.append(f"{name}: esperaba {expected!r}, obtuve {got!r}")
    print(("  ok  " if ok else " FALLA ") + name)


class Plugin:
    """Plugin falso: native_op devuelve un jobId; native_status tarda N
    consultas en terminar."""

    def __init__(self, consultas_hasta_terminar=1, resultado=None):
        self.llamadas: list[tuple[str, dict]] = []
        self.faltan = consultas_hasta_terminar
        self.resultado = resultado or {"state": "done", "created": [], "deleted": [],
                                       "deletedCount": 0, "modified": [{"handle": "A1"}],
                                       "changed": True}

    def __call__(self, cmd, params=None):
        self.llamadas.append((cmd, params or {}))
        if cmd == "native_op":
            return {"jobId": "op1", "state": "queued"}
        if cmd == "native_status":
            if self.faltan > 0:
                self.faltan -= 1
                return {"state": "running", "jobId": "op1"}
            return dict(self.resultado, jobId="op1")
        raise AssertionError(f"comando no mockeado: {cmd}")

    def n(self, cmd):
        return sum(1 for c, _ in self.llamadas if c == cmd)


def con_plugin(plugin, fn):
    real_call, real_paso = server.acad.call, edicion._PASO_S
    server.acad.call = plugin
    edicion._PASO_S = 0.0
    try:
        return fn()
    finally:
        server.acad.call = real_call
        edicion._PASO_S = real_paso


def sin_tocar_autocad(nombre, fn):
    p = Plugin()
    r = con_plugin(p, fn)
    check(f"{nombre}: se rechaza", r.get("ok"), False)
    check(f"{nombre}: dice por qué", bool(r.get("error")), True)
    check(f"{nombre}: no toca AutoCAD", p.llamadas, [])


def test_validaciones() -> None:
    sin_tocar_autocad("handle que no es hexadecimal",
                      lambda: server.trim_entity(["XYZ"], "A1", [0, 0]))
    sin_tocar_autocad("target vacío", lambda: server.trim_entity(["A1"], "", [0, 0]))
    sin_tocar_autocad("sin bordes", lambda: server.trim_entity([], "A1", [0, 0]))
    sin_tocar_autocad("punto de 1 coordenada", lambda: server.trim_entity(["A1"], "B2", [3]))
    sin_tocar_autocad("punto con texto", lambda: server.trim_entity(["A1"], "B2", ["a", "b"]))
    sin_tocar_autocad("punto NaN", lambda: server.extend_entity(["A1"], "B2", [float("nan"), 0]))
    sin_tocar_autocad("fillet con radio negativo",
                      lambda: server.fillet_entities("A1", "B2", -1, [0, 0], [1, 1]))
    sin_tocar_autocad("fillet con radio de texto",
                      lambda: server.fillet_entities("A1", "B2", "grande", [0, 0], [1, 1]))
    sin_tocar_autocad("fillet de una entidad consigo misma",
                      lambda: server.fillet_entities("A1", "a1", 0, [0, 0], [1, 1]))
    sin_tocar_autocad("join con una sola entidad", lambda: server.join_entities(["A1"]))
    sin_tocar_autocad("join con la misma repetida", lambda: server.join_entities(["A1", "a1"]))
    sin_tocar_autocad("overkill con handles y all a la vez",
                      lambda: server.overkill_entities(["A1", "B2"], True))
    sin_tocar_autocad("overkill sin nada", lambda: server.overkill_entities())


def test_trim_manda_lo_correcto() -> None:
    p = Plugin()
    r = con_plugin(p, lambda: server.trim_entity(["a1", "B2"], "c3", [1, 2], extend_edges=True))
    check("manda native_op", p.llamadas[0][0], "native_op")
    check("op trim con handles en mayúscula", p.llamadas[0][1],
          {"op": "trim", "edges": ["A1", "B2"], "target": "C3", "point": [1.0, 2.0],
           "extend_edges": True})
    check("espera el resultado", r["state"], "done")
    check("ok=True al terminar", r["ok"], True)
    check("devuelve lo que cambió", r["modified"], [{"handle": "A1"}])
    check("consultó el estado hasta terminar", p.n("native_status"), 2)


def test_extend_fillet_join_overkill() -> None:
    p = Plugin(0)
    con_plugin(p, lambda: server.extend_entity(["A1"], "B2", [5, 6, 0]))
    check("extend manda boundaries como edges", p.llamadas[0][1],
          {"op": "extend", "edges": ["A1"], "target": "B2", "point": [5.0, 6.0, 0.0],
           "extend_edges": False})
    p = Plugin(0)
    con_plugin(p, lambda: server.fillet_entities("a1", "b2", 0.5, [0, 0], [1, 1]))
    check("fillet", p.llamadas[0][1],
          {"op": "fillet", "first": "A1", "second": "B2", "radius": 0.5,
           "point1": [0.0, 0.0], "point2": [1.0, 1.0]})
    p = Plugin(0)
    con_plugin(p, lambda: server.fillet_entities("a1", "b2", 0, [0, 0], [1, 1]))
    check("fillet con radio 0 es válido", p.llamadas[0][1]["radius"], 0.0)
    p = Plugin(0)
    con_plugin(p, lambda: server.chamfer_entities("a1", "b2", 0.5, [0, 0], [1, 1]))
    check("chamfer: d2 por defecto igual a d1", p.llamadas[0][1],
          {"op": "chamfer", "first": "A1", "second": "B2", "d1": 0.5, "d2": 0.5,
           "point1": [0.0, 0.0], "point2": [1.0, 1.0]})
    p = Plugin(0)
    con_plugin(p, lambda: server.chamfer_entities("a1", "b2", 0.5, [0, 0], [1, 1], d2=0.2))
    check("chamfer con d2 distinto", (p.llamadas[0][1]["d1"], p.llamadas[0][1]["d2"]), (0.5, 0.2))
    r = server.chamfer_entities("a1", "a1", 0.5, [0, 0], [1, 1])
    check("chamfer con la misma entidad se rechaza", r.get("ok"), False)
    r = server.chamfer_entities("a1", "b2", -1, [0, 0], [1, 1])
    check("chamfer con distancia negativa se rechaza", r.get("ok"), False)
    class PluginRadio(Plugin):
        def __init__(self, crea=True):
            super().__init__(0)
            self.crea, self.listados = crea, 0

        def __call__(self, cmd, params=None):
            if cmd == "list_constraints":
                self.llamadas.append((cmd, params or {}))
                self.listados += 1
                return {"variables": ([{"name": "rad1", "expression": "3"}] if self.listados > 1 and self.crea else [])}
            if cmd == "set_constraint_value":
                self.llamadas.append((cmd, params or {}))
                return {"name": params["name"], "value": params["value"]}
            return super().__call__(cmd, params)

    p = PluginRadio()
    r = con_plugin(p, lambda: server.radius_constraint("a1", [5, 5], 7))
    check("radius_constraint: manda el comando nativo y luego fija el valor",
          [c for c, _ in p.llamadas], ["list_constraints", "native_op", "native_status", "list_constraints", "set_constraint_value"])
    check("radius_constraint: la operación nativa va sin valor", p.llamadas[1][1],
          {"op": "radius_constraint", "target": "A1", "point": [5.0, 5.0], "diameter": False})
    check("radius_constraint: set_constraint_value con la variable nueva", p.llamadas[-1][1], {"name": "rad1", "value": 7.0})
    p = PluginRadio()
    con_plugin(p, lambda: server.radius_constraint("a1", [5, 5], 14, diameter=True))
    check("radius_constraint como diametro", p.llamadas[1][1]["diameter"], True)
    p = PluginRadio(crea=False)
    r = con_plugin(p, lambda: server.radius_constraint("a1", [5, 5], 7))
    check("si AutoCAD no creó la restricción, lo dice", (r or {}).get("ok"), False)
    check("radius_constraint con valor 0 se rechaza", server.radius_constraint("a1", [5, 5], 0).get("ok"), False)
    check("radius_constraint con valor texto se rechaza", server.radius_constraint("a1", [5, 5], "siete").get("ok"), False)
    p = Plugin(0)
    con_plugin(p, lambda: server.join_entities(["a1", "b2", "c3"]))
    check("join", p.llamadas[0][1], {"op": "join", "handles": ["A1", "B2", "C3"]})
    p = Plugin(0)
    con_plugin(p, lambda: server.overkill_entities(["a1", "b2"]))
    check("overkill por handles", p.llamadas[0][1], {"op": "overkill", "handles": ["A1", "B2"]})
    p = Plugin(0)
    con_plugin(p, lambda: server.overkill_entities(all=True))
    check("overkill de todo el espacio", p.llamadas[0][1], {"op": "overkill", "all": True})


def test_error_del_plugin() -> None:
    p = Plugin(0, {"state": "error", "error": "AutoCAD rechazó la operación: eInvalidInput"})
    r = con_plugin(p, lambda: server.join_entities(["A1", "B2"]))
    check("un error del plugin sale ok=False", r["ok"], False)
    check("conserva el mensaje", "eInvalidInput" in r["error"], True)


def test_sin_cambios_se_ve() -> None:
    p = Plugin(0, {"state": "done", "created": [], "deleted": [], "deletedCount": 0,
                   "modified": [], "changed": False,
                   "warning": " La operación no cambió nada: ..."})
    r = con_plugin(p, lambda: server.trim_entity(["A1"], "B2", [0, 0]))
    check("terminó bien pero sin cambios", (r["ok"], r["changed"]), (True, False))
    check("el aviso viaja en el resultado", "no cambió nada" in r["warning"], True)


def test_si_tarda_no_se_repite() -> None:
    p = Plugin(10_000)
    r = con_plugin(p, lambda: server.trim_entity(["A1"], "B2", [0, 0], wait_s=0.0))
    check("sigue en curso", r["state"] in ("queued", "running"), True)
    check("avisa que no se repita", "NO repitas" in r["note"], True)
    check("una sola operación mandada", p.n("native_op"), 1)


def test_sesion() -> None:
    check("native_status es de lectura", session.retry_safe("native_status"), True)
    check("native_op NO se reintenta", session.retry_safe("native_op"), False)


class PluginUndo(Plugin):
    """Plugin falso con UNDO: una operación nativa se revierte recién al 2.º paso
    (como en AutoCAD: el comando registrado vacío + el comando de adentro)."""

    def __init__(self, version="1.10.1", pasos_para_revertir=2):
        super().__init__(0, {"state": "done", "changed": True, "op": "join", "created": [],
                             "deleted": [], "deletedCount": 0,
                             "modified": [{"handle": "A1", "before": [0, 0, 5, 0], "after": [0, 0, 10, 0]}]})
        self.version, self.necesarios, self.undos = version, pasos_para_revertir, 0

    def __call__(self, cmd, params=None):
        if cmd == "ping":
            return {"ok": True, "pluginVersion": self.version}
        if cmd == "undo":
            self.undos += 1
            self.llamadas.append((cmd, params or {}))
            return {"status": "encolado"}
        if cmd == "get_entity":
            self.llamadas.append((cmd, params or {}))
            caja = [0, 0, 5, 0] if self.undos >= self.necesarios else [0, 0, 10, 0]
            return {"handle": params["handle"], "bbox": caja}
        return super().__call__(cmd, params)


def test_undo() -> None:
    real_call, real_paso, real_espera = server.acad.call, edicion._PASO_S, edicion._ESPERA_PASO_S
    edicion._PASO_S, edicion._ESPERA_PASO_S = 0.0, 0.05
    try:
        # una operación nativa se deshace de a un paso, verificando
        session.reset()
        p = PluginUndo()
        server.acad.call = p
        server.join_entities(["A1", "B2"])
        r = server.undo(1)
        check("undo de una nativa: ok", r["ok"], True)
        check("usó 2 pasos (verificando, no contando)", r["done"][0]["autocadSteps"], 2)
        check("quedó revertida", r["done"][0]["reverted"], True)
        check("se pidieron 2 UNDO de a 1", [c for c in p.llamadas if c[0] == "undo"], [("undo", {"steps": 1})] * 2)

        # si no vuelve nunca, no se queda en un bucle y lo dice
        session.reset()
        p = PluginUndo(pasos_para_revertir=10_000)
        server.acad.call = p
        server.join_entities(["A1", "B2"])
        r = server.undo(1)
        check("si no revierte: ok=False", r["ok"], False)
        check("corta en el tope", r["done"][0]["autocadSteps"], edicion._MAX_PASOS_NATIVA)
        check("avisa", "warning" in r, True)

        # una tool de dibujo: un solo UNDO, sin verificar
        session.reset()
        session.note_undo_weight(1)
        p = PluginUndo()
        server.acad.call = p
        r = server.undo(1)
        check("tool de dibujo: un UNDO", [c for c in p.llamadas if c[0] == "undo"], [("undo", {"steps": 1})])
        check("tool de dibujo: ok", r["ok"], True)

        # plugin anterior a 1.10.1: conteo fijo y aviso, sin verificar
        session.reset()
        p = PluginUndo(version="1.10.0")
        server.acad.call = p
        server.join_entities(["A1", "B2"])
        r = server.undo(1)
        check("plugin viejo: pide 2 pasos de una vez", [c for c in p.llamadas if c[0] == "undo"], [("undo", {"steps": 2})])
        check("plugin viejo: avisa que no pudo verificar", "warning" in r["done"][0], True)
        check("plugin viejo: no marca fallo", r["ok"], True)
    finally:
        server.acad.call, edicion._PASO_S, edicion._ESPERA_PASO_S = real_call, real_paso, real_espera
        session.reset()


def main() -> int:
    test_validaciones()
    test_trim_manda_lo_correcto()
    test_extend_fillet_join_overkill()
    test_error_del_plugin()
    test_sin_cambios_se_ve()
    test_si_tarda_no_se_repite()
    test_sesion()
    test_undo()
    if FAILED:
        print("\nFALLARON:")
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
