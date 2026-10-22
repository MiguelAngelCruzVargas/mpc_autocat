"""Tests de las tools de caras y aristas (bd_extra.py + server.py) contra el socket mockeado. Sin AutoCAD.

Uso:  python test_subentidades.py
"""
from __future__ import annotations

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
        return {"ok": True}

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
    # ---- list_subentities
    r, ll = con_plugin(lambda: server.list_subentities("a1"))
    check("list_subentities por defecto", ll[0], ("list_subentities", {"handle": "A1", "kind": "faces", "limit": 200}))
    r, ll = con_plugin(lambda: server.list_subentities("a1", "edges", {"on_face": {"normal": [0, 0, 1]}}, 50))
    check("aristas de la tapa", ll[0][1]["select"], {"on_face": {"normal": [0.0, 0.0, 1.0]}})
    r, ll = con_plugin(lambda: server.list_subentities("a1", "faces", {"z": 5, "normal": [0, 0, 1], "tol_deg": 2}))
    check("selector combinado", ll[0][1]["select"], {"normal": [0.0, 0.0, 1.0], "tol_deg": 2.0, "z": 5.0})
    r, ll = con_plugin(lambda: server.list_subentities("a1", "faces", {"all": True}))
    check("selector all", ll[0][1]["select"], {"all": True})
    rechazada("kind inexistente", lambda: server.list_subentities("a1", "bordes"))
    rechazada("selector vacio", lambda: server.list_subentities("a1", "faces", {}))
    rechazada("selector con all falso", lambda: server.list_subentities("a1", "faces", {"all": False}))
    rechazada("clave de tipeo", lambda: server.list_subentities("a1", "faces", {"normals": [0, 0, 1]}))
    rechazada("indices vacios", lambda: server.list_subentities("a1", "faces", {"indices": []}))
    rechazada("indice negativo", lambda: server.list_subentities("a1", "faces", {"indices": [-1]}))
    rechazada("indice bool", lambda: server.list_subentities("a1", "faces", {"indices": [True]}))
    rechazada("normal nula", lambda: server.list_subentities("a1", "faces", {"normal": [0, 0, 0]}))
    rechazada("tipo de cara inexistente", lambda: server.list_subentities("a1", "faces", {"kind": "cubo"}))
    rechazada("tipo de arista inexistente", lambda: server.list_subentities("a1", "edges", {"kind": "plane"}))
    rechazada("vertical y horizontal", lambda: server.list_subentities("a1", "edges", {"vertical": True, "horizontal": True}))
    rechazada("vertices con select", lambda: server.list_subentities("a1", "vertices", {"all": True}))
    rechazada("limit 0", lambda: server.list_subentities("a1", "faces", None, 0))
    rechazada("handle invalido", lambda: server.list_subentities("zz"))
    check("list_subentities es de lectura", session.retry_safe("list_subentities"), True)

    # ---- edit_solid_faces
    r, ll = con_plugin(lambda: server.edit_solid_faces("a1", "extrude", {"normal": [0, 0, 1]}, height=3))
    check("extrude", ll[0][1], {"handle": "A1", "op": "extrude", "faces": {"normal": [0.0, 0.0, 1.0]}, "height": 3.0, "taper_deg": 0.0})
    r, ll = con_plugin(lambda: server.edit_solid_faces("a1", "offset", {"indices": [2]}, distance=-0.5, dry_run=True))
    check("offset con dry_run", (ll[0][1]["distance"], ll[0][1]["dry_run"]), (-0.5, True))
    r, ll = con_plugin(lambda: server.edit_solid_faces("a1", "taper", {"indices": [2]}, base_point=[0, 0], direction=[0, 0, 1], angle_deg=10))
    check("taper arma base_point 3D", ll[0][1]["base_point"], [0.0, 0.0, 0.0])
    r, ll = con_plugin(lambda: server.edit_solid_faces("a1", "shell", None, thickness=0.2))
    check("shell cerrado (sin caras)", "faces" in ll[0][1], False)
    r, ll = con_plugin(lambda: server.edit_solid_faces("a1", "shell", {"normal": [0, 0, 1]}, thickness=0.2))
    check("shell con tapa abierta", ll[0][1]["thickness"], 0.2)
    r, ll = con_plugin(lambda: server.edit_solid_faces("a1", "remove", {"kind": "cylinder"}))
    check("remove", ll[0][1]["op"], "remove")
    rechazada("op inexistente", lambda: server.edit_solid_faces("a1", "girar", {"all": True}))
    rechazada("extrude sin caras", lambda: server.edit_solid_faces("a1", "extrude", None, height=3))
    rechazada("extrude sin height", lambda: server.edit_solid_faces("a1", "extrude", {"all": True}))
    rechazada("extrude height 0", lambda: server.edit_solid_faces("a1", "extrude", {"all": True}, height=0))
    rechazada("extrude taper de 90", lambda: server.edit_solid_faces("a1", "extrude", {"all": True}, height=1, taper_deg=90))
    rechazada("offset sin distance", lambda: server.edit_solid_faces("a1", "offset", {"all": True}))
    rechazada("taper sin angulo", lambda: server.edit_solid_faces("a1", "taper", {"all": True}, base_point=[0, 0, 0], direction=[0, 0, 1]))
    rechazada("taper direccion nula", lambda: server.edit_solid_faces("a1", "taper", {"all": True}, base_point=[0, 0, 0], direction=[0, 0, 0], angle_deg=5))
    rechazada("shell sin espesor", lambda: server.edit_solid_faces("a1", "shell", {"all": True}))
    rechazada("shell espesor 0", lambda: server.edit_solid_faces("a1", "shell", None, thickness=0))
    rechazada("remove con selector vacio", lambda: server.edit_solid_faces("a1", "remove", {}))
    check("edit_solid_faces NO se reintenta", session.retry_safe("edit_solid_faces"), False)

    # ---- chamfer_solid_edges
    r, ll = con_plugin(lambda: server.chamfer_solid_edges("a1", {"on_face": {"normal": [0, 0, 1]}}, {"normal": [0, 0, 1]}, 0.5))
    check("chamfer", ll[0][1]["distance"], 0.5)
    check("chamfer sin distance2", "distance2" in ll[0][1], False)
    r, ll = con_plugin(lambda: server.chamfer_solid_edges("a1", {"indices": [1]}, {"indices": [0]}, 0.5, 0.25, True))
    check("chamfer asimetrico y dry_run", (ll[0][1]["distance2"], ll[0][1]["dry_run"]), (0.25, True))
    rechazada("chamfer distancia 0", lambda: server.chamfer_solid_edges("a1", {"all": True}, {"indices": [0]}, 0))
    rechazada("chamfer distancia2 negativa", lambda: server.chamfer_solid_edges("a1", {"all": True}, {"indices": [0]}, 1, -1))
    rechazada("chamfer sin selector de aristas", lambda: server.chamfer_solid_edges("a1", {}, {"indices": [0]}, 1))
    rechazada("chamfer base mal formada", lambda: server.chamfer_solid_edges("a1", {"all": True}, [0], 1))
    check("chamfer NO se reintenta", session.retry_safe("chamfer_solid_edges"), False)

    # ---- edit_mesh_faces
    r, ll = con_plugin(lambda: server.edit_mesh_faces("a1", "extrude", {"normal": [0, 0, 1]}, length=2))
    check("mesh extrude", ll[0][1], {"handle": "A1", "op": "extrude", "faces": {"normal": [0.0, 0.0, 1.0]}, "length": 2.0, "taper_deg": 0.0})
    r, ll = con_plugin(lambda: server.edit_mesh_faces("a1", "extrude", {"all": True}, length=2, direction=[0, 0, 1], connected=True))
    check("mesh extrude con direccion y conectadas", (ll[0][1]["direction"], ll[0][1]["connected"]), ([0.0, 0.0, 1.0], True))
    r, ll = con_plugin(lambda: server.edit_mesh_faces("a1", "merge", {"indices": [1, 2]}))
    check("mesh merge", ll[0][1]["faces"], {"indices": [1, 2]})
    r, ll = con_plugin(lambda: server.edit_mesh_faces("a1", "split", face=0, edge_a=0, edge_b=2))
    check("mesh split", (ll[0][1]["t_a"], ll[0][1]["t_b"]), (0.5, 0.5))
    r, ll = con_plugin(lambda: server.edit_mesh_faces("a1", "crease", edges={"indices": [1]}, level=1))
    check("mesh crease en aristas", ll[0][1]["edges"], {"indices": [1]})
    r, ll = con_plugin(lambda: server.edit_mesh_faces("a1", "crease", level=2, whole_mesh=True))
    check("mesh crease toda la malla", ll[0][1]["whole_mesh"], True)
    r, ll = con_plugin(lambda: server.edit_mesh_faces("a1", "collapse", edge=3))
    check("mesh collapse arista", ll[0][1]["edge"], 3)
    r, ll = con_plugin(lambda: server.edit_mesh_faces("a1", "cap", edges={"indices": [0, 1, 2, 3]}))
    check("mesh cap", ll[0][1]["op"], "cap")
    r, ll = con_plugin(lambda: server.edit_mesh_faces("a1", "spin", edge=4))
    check("mesh spin", ll[0][1]["edge"], 4)
    rechazada("mesh op inexistente", lambda: server.edit_mesh_faces("a1", "pegar"))
    rechazada("mesh extrude sin length", lambda: server.edit_mesh_faces("a1", "extrude", {"all": True}))
    rechazada("mesh extrude length 0", lambda: server.edit_mesh_faces("a1", "extrude", {"all": True}, length=0))
    rechazada("mesh merge sin caras", lambda: server.edit_mesh_faces("a1", "merge"))
    rechazada("mesh split sin aristas", lambda: server.edit_mesh_faces("a1", "split", face=0))
    rechazada("mesh split aristas iguales", lambda: server.edit_mesh_faces("a1", "split", face=0, edge_a=1, edge_b=1))
    rechazada("mesh split en el extremo", lambda: server.edit_mesh_faces("a1", "split", face=0, edge_a=1, edge_b=2, t_a=0))
    rechazada("mesh split indice negativo", lambda: server.edit_mesh_faces("a1", "split", face=-1, edge_a=1, edge_b=2))
    rechazada("mesh crease sin level", lambda: server.edit_mesh_faces("a1", "crease", faces={"all": True}))
    rechazada("mesh crease sin nada", lambda: server.edit_mesh_faces("a1", "crease", level=1))
    rechazada("mesh crease negativo", lambda: server.edit_mesh_faces("a1", "crease", faces={"all": True}, level=-1))
    rechazada("mesh collapse con las dos", lambda: server.edit_mesh_faces("a1", "collapse", face=1, edge=2))
    rechazada("mesh collapse con ninguna", lambda: server.edit_mesh_faces("a1", "collapse"))
    rechazada("mesh cap sin aristas", lambda: server.edit_mesh_faces("a1", "cap"))
    rechazada("mesh spin sin arista", lambda: server.edit_mesh_faces("a1", "spin"))
    check("edit_mesh_faces NO se reintenta", session.retry_safe("edit_mesh_faces"), False)

    # ---- superficies
    r, ll = con_plugin(lambda: server.trim_surface("a1", [15, 100, 5], tools=["b2"]))
    check("trim_surface", ll[0][1], {"blank": "A1", "pick_point": [15.0, 100.0, 5.0], "tools": ["B2"]})
    r, ll = con_plugin(lambda: server.trim_surface("a1", [15, 100, 5], curves=["b2", "c3"], project_dir=[0, 0, -1], auto_extend=True))
    check("trim_surface con curvas", (ll[0][1]["curves"], ll[0][1]["project_dir"], ll[0][1]["auto_extend"]), (["B2", "C3"], [0.0, 0.0, -1.0], True))
    rechazada("trim sin corte", lambda: server.trim_surface("a1", [0, 0, 0]))
    rechazada("trim contra si misma", lambda: server.trim_surface("a1", [0, 0, 0], tools=["a1"]))
    rechazada("trim punto invalido", lambda: server.trim_surface("a1", [0], tools=["b2"]))
    rechazada("trim proyeccion nula", lambda: server.trim_surface("a1", [0, 0, 0], curves=["b2"], project_dir=[0, 0, 0]))
    r, ll = con_plugin(lambda: server.extend_surface("a1", {"indices": [2]}, 1.5, "stretch"))
    check("extend_surface", ll[0][1], {"handle": "A1", "edges": {"indices": [2]}, "distance": 1.5, "mode": "stretch"})
    rechazada("extend modo inexistente", lambda: server.extend_surface("a1", {"indices": [2]}, 1.5, "doblar"))
    rechazada("extend distancia 0", lambda: server.extend_surface("a1", {"indices": [2]}, 0))
    rechazada("extend sin selector", lambda: server.extend_surface("a1", {}, 1))
    r, ll = con_plugin(lambda: server.fillet_surfaces("a1", [1, 2, 3], "b2", [4, 5, 6], 2, "first"))
    check("fillet_surfaces", ll[0][1], {"surface1": "A1", "pick1": [1.0, 2.0, 3.0], "surface2": "B2", "pick2": [4.0, 5.0, 6.0], "radius": 2.0, "trim": "first"})
    rechazada("fillet con la misma superficie", lambda: server.fillet_surfaces("a1", [0, 0, 0], "a1", [1, 1, 1], 2))
    rechazada("fillet radio 0", lambda: server.fillet_surfaces("a1", [0, 0, 0], "b2", [1, 1, 1], 0))
    rechazada("fillet trim inexistente", lambda: server.fillet_surfaces("a1", [0, 0, 0], "b2", [1, 1, 1], 1, "todo"))
    for t in ("trim_surface", "extend_surface", "fillet_surfaces"):
        check(f"{t} NO se reintenta", session.retry_safe(t), False)

    if FAILED:
        print("\nFALLARON:")
        for f in FAILED:
            print(" -", f)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
