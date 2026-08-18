"""Prueba rápida de la capa plugin<->socket, SIN pasar por MCP/Claude.

Sirve para validar que el plugin está cargado y respondiendo antes de
meter la capa de Claude encima.

Uso:
  1. Abrí AutoCAD con un dibujo nuevo.
  2. NETLOAD -> el DLL que corresponda a tu versión (ver README).
  3. Confirmá en la línea de comandos de AutoCAD el mensaje "[MCP] Plugin cargado...".
  4. python smoke_test.py
"""
import autocad_client as acad

if __name__ == "__main__":
    print("-> get_drawing_info")
    print(acad.call("get_drawing_info"))

    print("-> set_layer (MUROS, rojo, grosor 0.30mm)")
    print(acad.call("set_layer", {"name": "MUROS", "colorIndex": 1, "lineweightHundredthsMm": 30}))

    print("-> create_line")
    line = acad.call("create_line", {"x1": 0, "y1": 0, "x2": 100, "y2": 100, "layer": "MUROS"})
    print(line)

    print("-> create_polyline (cuadrado cerrado)")
    pline = acad.call("create_polyline", {
        "points": [[0, 0], [50, 0], [50, 50], [0, 50]],
        "closed": True,
        "layer": "MUROS",
    })
    print(pline)

    print("-> calculate_area")
    print(acad.call("calculate_area", {"handle": pline["handle"]}))

    print("-> create_circle")
    circle = acad.call("create_circle", {"x": 25, "y": 25, "radius": 10})
    print(circle)

    print("-> create_text")
    print(acad.call("create_text", {"text": "PLANTA BAJA", "x": 0, "y": -10, "height": 5}))

    print("-> get_entity (círculo)")
    print(acad.call("get_entity", {"handle": circle["handle"]}))

    print("-> move_entity (círculo +20,+0)")
    print(acad.call("move_entity", {"handle": circle["handle"], "dx": 20, "dy": 0}))

    print("-> list_layers")
    print(acad.call("list_layers"))

    print("-> list_entities")
    print(acad.call("list_entities", {"limit": 10}))

    print("-> zoom_extents")
    print(acad.call("zoom_extents"))

    print("\nOK: pipeline completo funcionando.")
