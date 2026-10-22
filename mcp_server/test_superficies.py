"""Tests de las tools de superficies y mallas (bd_extra.py + mallas.py + server.py) contra el socket mockeado. Sin AutoCAD.

Uso:  python test_superficies.py
"""
from __future__ import annotations

import mallas
import server
import session

FAILED: list[str] = []


def check(name: str, got, expected) -> None:
    ok = got == expected
    if not ok:
        FAILED.append(f"{name}: esperaba {expected!r}, obtuve {got!r}")
    print(("  ok  " if ok else " FALLA ") + name)


def con_plugin(fn):
    llamadas: list[tuple[str, dict]] = []

    def fake(cmd, params=None):
        llamadas.append((cmd, params or {}))
        return {"ok": True, "handle": "AB"}

    real = server.acad.call
    server.acad.call = fake
    try:
        return fn(), llamadas
    finally:
        server.acad.call = real


def rechazada(nombre, fn):
    r, ll = con_plugin(fn)
    check(f"{nombre}: se rechaza", r.get("ok"), False)
    check(f"{nombre}: no toca AutoCAD", ll, [])


def main() -> int:
    # ---- create_surface
    r, ll = con_plugin(lambda: server.create_surface("plane", "a1"))
    check("plane", ll[0], ("create_surface", {"kind": "plane", "delete_sources": False, "profile": "A1"}))
    r, ll = con_plugin(lambda: server.create_surface("extrude", "a1", height=3, taper_deg=2, layer="SUP"))
    check("extrude con altura", (ll[0][1]["height"], ll[0][1]["taper_deg"], ll[0][1]["layer"]), (3.0, 2.0, "SUP"))
    r, ll = con_plugin(lambda: server.create_surface("revolve", "a1", axis_point=[0, 0], axis_dir=[0, 1], angle_deg=180))
    check("revolve con eje 2D", (ll[0][1]["axis_point"], ll[0][1]["axis_dir"], ll[0][1]["angle_deg"]), ([0.0, 0.0, 0.0], [0.0, 1.0, 0.0], 180.0))
    r, ll = con_plugin(lambda: server.create_surface("sweep", "a1", path="b2", scale=0.5))
    check("sweep", (ll[0][1]["path"], ll[0][1]["scale"]), ("B2", 0.5))
    r, ll = con_plugin(lambda: server.create_surface("loft", sections=["a1", "b2"], ruled=True))
    check("loft reglado (RULESURF)", (ll[0][1]["sections"], ll[0][1]["ruled"]), (["A1", "B2"], True))
    rechazada("kind inexistente", lambda: server.create_surface("pizza"))
    rechazada("plane sin perfil", lambda: server.create_surface("plane"))
    rechazada("extrude sin altura ni direccion", lambda: server.create_surface("extrude", "a1"))
    rechazada("extrude con altura 0", lambda: server.create_surface("extrude", "a1", height=0))
    rechazada("extrude con las dos", lambda: server.create_surface("extrude", "a1", height=1, direction=[0, 0, 1]))
    rechazada("revolve sin eje", lambda: server.create_surface("revolve", "a1"))
    rechazada("revolve angulo 0", lambda: server.create_surface("revolve", "a1", axis_point=[0, 0], axis_dir=[0, 1], angle_deg=0))
    rechazada("sweep sin trayectoria", lambda: server.create_surface("sweep", "a1"))
    rechazada("sweep perfil igual a trayectoria", lambda: server.create_surface("sweep", "a1", path="a1"))
    rechazada("loft con una seccion", lambda: server.create_surface("loft", sections=["a1"]))
    rechazada("loft con guias y trayectoria", lambda: server.create_surface("loft", sections=["a1", "b2"], guides=["c3"], path="d4"))

    # ---- offset, NURBS, malla desde caras
    r, ll = con_plugin(lambda: server.offset_surface("a1", -0.5))
    check("offset_surface", ll[0], ("offset_surface", {"handle": "A1", "distance": -0.5}))
    rechazada("offset de 0", lambda: server.offset_surface("a1", 0))
    grilla = [[[0, 0, 0], [1, 0, 1], [2, 0, 0], [3, 0, 1]], [[0, 1, 1], [1, 1, 2], [2, 1, 1], [3, 1, 2]],
              [[0, 2, 0], [1, 2, 1], [2, 2, 0], [3, 2, 1]], [[0, 3, 1], [1, 3, 2], [2, 3, 1], [3, 3, 2]]]
    r, ll = con_plugin(lambda: server.create_nurb_surface(grilla))
    check("nurbs: 4 filas de 4 puntos", (ll[0][0], len(ll[0][1]["points"]), ll[0][1]["degree"]), ("create_nurb_surface", 4, 3))
    rechazada("nurbs con una fila", lambda: server.create_nurb_surface([[[0, 0, 0], [1, 0, 0]]]))
    rechazada("nurbs con filas desiguales", lambda: server.create_nurb_surface([[[0, 0, 0], [1, 0, 0]], [[0, 1, 0]]]))
    rechazada("nurbs con punto mal formado", lambda: server.create_nurb_surface([[[0, 0, 0], [1]], [[0, 1, 0], [1, 1, 0]]]))
    r, ll = con_plugin(lambda: server.create_mesh_from_faces([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], [[0, 1, 3], [0, 3, 2]], 1))
    check("malla desde caras", (ll[0][0], ll[0][1]["faces"], ll[0][1]["smooth"]), ("create_mesh_from_faces", [[0, 1, 3], [0, 3, 2]], 1))
    rechazada("malla con indice inexistente", lambda: server.create_mesh_from_faces([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 5]]))
    rechazada("malla con cara de 2 vertices", lambda: server.create_mesh_from_faces([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1]]))
    rechazada("malla con vertice repetido en una cara", lambda: server.create_mesh_from_faces([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 1]]))
    rechazada("malla con smooth 9", lambda: server.create_mesh_from_faces([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]], 9))

    # ---- primitivas de malla
    m = mallas.mesh_primitiva("box", [2, 3, 4], 2, 1)
    check("box: Setbox con 7 argumentos", (m["metodo"], len(m["args"])), ("Setbox", 7))
    m = mallas.mesh_primitiva("sphere", [2], 4, 0)
    check("sphere: SetSphere con 4 argumentos y radio", (m["metodo"], len(m["args"]), m["args"][0]), ("SetSphere", 4, 2.0))
    for forma, size, n_args, metodo in (("cylinder", [1, 2], 7, "SetCylinder"), ("cone", [1, 2], 8, "SetCone"), ("pyramid", [1, 2], 8, "SetPyramid"),
                                        ("torus", [3, 1], 6, "SetTorus"), ("wedge", [1, 2, 3], 9, "SetWedge")):
        m = mallas.mesh_primitiva(forma, size, 3, 0)
        check(f"{forma}: {metodo} con {n_args} argumentos", (m["metodo"], len(m["args"])), (metodo, n_args))
    for nombre, args in (("forma inexistente", ("pizza", [1], 2, 0)), ("medidas de menos", ("box", [1, 2], 2, 0)),
                         ("medida negativa", ("sphere", [-1], 2, 0)), ("divisiones 0", ("box", [1, 1, 1], 0, 0)),
                         ("smooth 7", ("box", [1, 1, 1], 2, 7)), ("toro con tubo mayor que el radio", ("torus", [1, 2], 2, 0))):
        try:
            mallas.mesh_primitiva(*args)
            check(f"mallas: {nombre} se rechaza", True, False)
        except mallas.MallaError:
            check(f"mallas: {nombre} se rechaza", True, True)
    r, ll = con_plugin(lambda: server.create_mesh("sphere", 5, 6, 0, [2], 3))
    check("create_mesh crea con create_object", ll[0][0], "create_object")
    r = server.create_mesh("box", size=[1, 2])
    check("create_mesh con medidas de menos se rechaza", r.get("ok"), False)
    r = server.mesh_smooth("a1", "pizza")
    check("mesh_smooth con modo inexistente se rechaza", r.get("ok"), False)
    r = server.convert_mesh("a1", "rueda")
    check("convert_mesh con destino inexistente se rechaza", r.get("ok"), False)
    for cambio in ("create_surface", "offset_surface", "create_nurb_surface", "create_mesh_from_faces"):
        check(f"{cambio} NO se reintenta", session.retry_safe(cambio), False)
        check(f"{cambio}: el docstring dice que está verificado", "verificado en vivo" in (getattr(server, cambio).__doc__ or ""), True)

    if FAILED:
        print("\nFALLARON:")
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
