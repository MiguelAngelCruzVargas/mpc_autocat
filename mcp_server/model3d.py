"""La planta levantada en 3D: muros, vanos y losa como sólidos de AutoCAD.

Es la primera capacidad escrita SOLO del lado Python sobre el motor
`run_code` (ver docs/superpowers/specs/2026-10-09-motor-api-autocad-design.md
§4): este módulo calcula todo —contornos, cajas de los vanos, losa, volumen
esperado— y genera el C# que AutoCAD solo tiene que ejecutar. No toca el
plugin ni pide reiniciar AutoCAD.

Parte de la MISMA muraria que la planta (arch.plan_walls → wall_network):
el 3D tiene los encuentros rematados igual que el 2D y las puertas y
ventanas en el mismo lugar. Si la planta cambia, el 3D se regenera de ella;
no hay un segundo modelo que mantener a mano.

El C# generado se limita a lo que el filtro semántico del motor deja pasar
(geometría y base de datos; nada de archivos, red ni comandos) y a sintaxis
de C# 5, por si en net48 el motor cae al compilador de respaldo.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import arch
import layers
import wall_network
from geom import Axis, point_in_polygon

LAYER_MUROS_3D = "3D-MUROS"
LAYER_LOSA_3D = "3D-LOSA"
# Paleta del proyecto, nunca los puros 1-7 (CLAUDE.md 6.ter): gris claro
# para los muros y gris medio para la losa, que en estilo realista se
# separan sin colores chillones.
COLOR_MUROS_3D = layers.COLOR_TENUE
COLOR_LOSA_3D = layers.COLOR_SECUNDARIO

# Lo que la caja de un vano sobresale de cada cara del muro: sin esto la
# resta deja una película de espesor cero que AutoCAD dibuja como una cara.
HOLGURA_VANO = 0.02

# Una diferencia mayor entre el volumen que mide AutoCAD y el que se espera
# de la geometría se avisa: es un vano que no se restó o un sólido roto.
TOLERANCIA_VOLUMEN = 0.01


def _num(v: float) -> str:
    """Número como literal C#: punto decimal siempre (no depende del
    idioma de Windows) y sufijo explícito de double."""
    return repr(float(v)) + "d" if math.isfinite(v) else "0d"


def _arreglo(puntos: list) -> str:
    return "new double[] { " + ", ".join(
        f"{_num(p[0])}, {_num(p[1])}" for p in puntos) + " }"


def _agrupar(lazos: list[list]) -> list[tuple[list, list[list]]]:
    """Cada contorno exterior (antihorario) con los huecos que encierra."""
    def area(l: list) -> float:
        return sum(l[i][0] * l[(i + 1) % len(l)][1]
                   - l[(i + 1) % len(l)][0] * l[i][1]
                   for i in range(len(l))) / 2.0

    exteriores = [l for l in lazos if area(l) > 0]
    grupos: list[tuple[list, list[list]]] = [(e, []) for e in exteriores]
    for h in (l for l in lazos if area(l) < 0):
        # El hueco va con el exterior MÁS CHICO que lo contiene: un patio
        # dentro de un recinto dentro de la casa no es del contorno general.
        candidatos = [g for g in grupos
                      if point_in_polygon(h[0][0], h[0][1], g[0])]
        if candidatos:
            min(candidatos, key=lambda g: area(g[0]))[1].append(h)
    return grupos


def _cajas_de_vanos(muros: list[dict[str, Any]], base_z: float,
                    door_height: float, sill_height: float,
                    window_head: float) -> list[dict[str, Any]]:
    """Una caja por hueco: ancho del vano × espesor del muro × su alto."""
    cajas = []
    for i, m in enumerate(muros):
        axis = Axis([(p[0], p[1]) for p in m["points"]],
                    closed=bool(m.get("closed")))
        for h in arch._resolver_huecos(axis, m.get("openings")):
            tipo = str(h.get("type", "door")).lower()
            d = (h["start"] + h["end"]) / 2.0
            seg, _ = axis.segment_at(d)
            u = axis.dirs[seg]
            cx, cy = axis.point_at(d)
            if tipo == "window":
                z0, z1 = base_z + sill_height, base_z + window_head
            else:
                z0, z1 = base_z, base_z + door_height
            cajas.append({
                "wall": i, "type": tipo,
                "cx": cx, "cy": cy, "cz": (z0 + z1) / 2.0,
                "largo": h["end"] - h["start"],
                "ancho": float(m["thickness"]) + 2 * HOLGURA_VANO,
                "alto": z1 - z0,
                "angulo": math.atan2(u[1], u[0]),
                # Lo que de verdad saca del muro (sin la holgura).
                "volumen": (h["end"] - h["start"]) * float(m["thickness"])
                           * (z1 - z0),
            })
    return cajas


def _losa(rooms: list[dict[str, Any]], exterior_thickness: float,
          tol: float) -> list[list]:
    """Contorno de lo techado: los recintos que no son patio, hasta la cara
    exterior de sus muros. Cada recinto se agranda medio muro exterior y la
    unión de esos rectángulos es exactamente el paño exterior."""
    e = exterior_thickness / 2.0
    piezas = [[(r["x0"] - e, r["y0"] - e), (r["x1"] + e, r["y0"] - e),
               (r["x1"] + e, r["y1"] + e), (r["x0"] - e, r["y1"] + e)]
              for r in rooms if "PATIO" not in str(r["name"]).upper()]
    if not piezas:
        return []
    lazos, _abiertas = wall_network.outline(piezas, [], tol)
    return lazos


def build(rooms: list[dict[str, Any]],
          doors: Optional[list[dict[str, Any]]] = None,
          windows: Optional[list[dict[str, Any]]] = None,
          wall_height: float = 2.50, door_height: float = 2.10,
          sill_height: float = 0.90, window_head: float = 2.10,
          slab_thickness: float = 0.12, base_z: float = 0.0,
          slab: bool = True, offset: Optional[float] = None,
          exterior_thickness: float = 0.15,
          interior_thickness: float = 0.10,
          window_width: float = 1.20) -> dict[str, Any]:
    """Todo lo que hace falta para el 3D, calculado en Python: el C# a
    ejecutar y los volúmenes esperados. No toca AutoCAD."""
    if wall_height <= 0:
        raise ValueError("wall_height tiene que ser > 0.")
    if not 0 < door_height <= wall_height:
        raise ValueError(
            f"door_height ({door_height:g}) tiene que estar entre 0 y el "
            f"alto del muro ({wall_height:g}).")
    if not 0 <= sill_height < window_head <= wall_height:
        raise ValueError(
            f"La ventana va de sill_height ({sill_height:g}) a window_head "
            f"({window_head:g}): el antepecho tiene que quedar abajo del "
            f"cabezal y el cabezal no puede pasar el muro ({wall_height:g}).")
    if slab and slab_thickness <= 0:
        raise ValueError("slab_thickness tiene que ser > 0 (o slab=False).")

    plan = arch.plan_walls(rooms, doors, windows,
                           exterior_thickness=exterior_thickness,
                           interior_thickness=interior_thickness,
                           window_width=window_width)
    muros = plan["walls"]
    if not muros:
        raise ValueError("La distribución no tiene muros que levantar.")

    # Al costado de la planta, para no encimarse con el dibujo 2D.
    xs = [float(r[k]) for r in rooms for k in ("x0", "x1")]
    ancho = max(xs) - min(xs)
    dx = 1.5 * ancho if offset is None else float(offset)

    def corrido(puntos: list) -> list:
        return [(p[0] + dx, p[1]) for p in puntos]

    tol = min(exterior_thickness, interior_thickness) / 2.0 * 1e-5
    # Muros de altura completa: los vanos se restan en 3D, con su alto.
    red = wall_network.resolve(
        [{"points": m["points"], "thickness": m["thickness"]} for m in muros],
        tol=tol, snap=0)
    grupos = [(corrido(e), [corrido(h) for h in hs])
              for e, hs in _agrupar(red["loops"])]
    cajas = _cajas_de_vanos(muros, base_z, door_height, sill_height,
                            window_head)
    for c in cajas:
        c["cx"] += dx
    losa = ([(corrido(e), [corrido(h) for h in hs])
             for e, hs in _agrupar(_losa(rooms, exterior_thickness, tol))]
            if slab else [])

    vol_muros = red["area"] * wall_height - sum(c["volumen"] for c in cajas)
    area_losa = sum(
        wall_network._signed_area(e) + sum(wall_network._signed_area(h)
                                           for h in hs)
        for e, hs in losa)

    return {
        "code": _codigo(grupos, cajas, losa, base_z, wall_height,
                        slab_thickness),
        "offset": [dx, 0.0],
        "openings": len(cajas),
        "expectedMasonryVolume": vol_muros,
        "expectedSlabVolume": area_losa * slab_thickness if slab else 0.0,
        "plan": {k: plan[k] for k in ("doorsPlaced", "doorsTotal",
                                      "windowsPlaced")},
        "warnings": list(plan["warnings"]),
    }


# --------------------------------------------------------------- el C#

_PLANTILLA = r"""
// Generado por model3d.py: la planta levantada en 3D.
var C = System.Globalization.CultureInfo.InvariantCulture;
System.Func<double[], Region> region = delegate(double[] c)
{
    var pl = new Polyline();
    for (int i = 0; i < c.Length / 2; i++)
        pl.AddVertexAt(i, new Point2d(c[2 * i], c[2 * i + 1]), 0, 0, 0);
    pl.Closed = true;
    var curvas = new DBObjectCollection();
    curvas.Add(pl);
    var regs = Region.CreateFromCurves(curvas);
    pl.Dispose();
    for (int i = 1; i < regs.Count; i++) regs[i].Dispose();
    return (Region)regs[0];
};
System.Func<double[], double[][], double, double, Solid3d> extruir =
    delegate(double[] exterior, double[][] huecos, double z0, double alto)
{
    var r = region(exterior);
    foreach (var h in huecos)
    {
        var rh = region(h);
        r.BooleanOperation(BooleanOperationType.BoolSubtract, rh);
        rh.Dispose();
    }
    var s = new Solid3d();
    s.Extrude(r, alto, 0.0);
    r.Dispose();
    s.TransformBy(Matrix3d.Displacement(new Vector3d(0, 0, z0)));
    return s;
};
System.Func<Extents3d, Extents3d, bool> tocan = delegate(Extents3d a, Extents3d b)
{
    return a.MinPoint.X < b.MaxPoint.X && b.MinPoint.X < a.MaxPoint.X
        && a.MinPoint.Y < b.MaxPoint.Y && b.MinPoint.Y < a.MaxPoint.Y
        && a.MinPoint.Z < b.MaxPoint.Z && b.MinPoint.Z < a.MaxPoint.Z;
};

var muros = new System.Collections.Generic.List<Solid3d>();
%MUROS%

// Vanos: cada caja se resta del muro que toca. Si ninguno pierde volumen,
// el vano no se restó y se avisa.
int vano = 0;
%VANOS%

foreach (var m in muros)
{
    m.Layer = "%CAPA_MUROS%";
    Print("@@MURO|" + Add(m) + "|" + m.MassProperties.Volume.ToString(C));
}

%LOSA%

%VISTA%
return muros.Count;
"""

_MURO = "muros.Add(extruir({ext}, new double[][] {{ {huecos} }}, {z0}, {alto}));"

_VANO = """vano++;
{{
    var caja = new Solid3d();
    caja.CreateBox({largo}, {ancho}, {alto});
    caja.TransformBy(Matrix3d.Rotation({ang}, Vector3d.ZAxis, Point3d.Origin));
    caja.TransformBy(Matrix3d.Displacement(new Vector3d({cx}, {cy}, {cz})));
    bool restado = false;
    foreach (var m in muros)
    {{
        if (!tocan(m.GeometricExtents, caja.GeometricExtents)) continue;
        double antes = m.MassProperties.Volume;
        try {{ m.BooleanOperation(BooleanOperationType.BoolSubtract, caja); }}
        catch (System.Exception ex) {{ Print("@@AVISO|vano " + vano + " ({tipo}): " + ex.Message); }}
        if (m.MassProperties.Volume < antes - 1e-9) {{ restado = true; break; }}
    }}
    if (!restado) Print("@@AVISO|vano " + vano + " ({tipo}) en ({px}, {py}): no se pudo restar de ningun muro");
    caja.Dispose();
}}"""

_LOSA = """{{
    var losa = extruir({ext}, new double[][] {{ {huecos} }}, {z0}, {alto});
    losa.Layer = "%CAPA_LOSA%";
    Print("@@LOSA|" + Add(losa) + "|" + losa.MassProperties.Volume.ToString(C));
}}"""

# Vista isométrica SO (desde abajo a la izquierda, mirando al NE) con estilo
# realista. Lo que falle acá no invalida el modelo: se avisa y listo. El
# estilo se busca por los dos nombres porque la clave del diccionario
# puede venir traducida en un AutoCAD en castellano.
_VISTA = """try
{{
    var vista = ed.GetCurrentView();
    vista.ViewDirection = new Vector3d(-1, -1, 1);
    vista.Target = new Point3d({cx}, {cy}, {cz});
    vista.CenterPoint = Point2d.Origin;
    vista.Height = {alto};
    vista.Width = {ancho};
    var estilos = (DBDictionary)tr.GetObject(db.VisualStyleDictionaryId, OpenMode.ForRead);
    foreach (var nombre in new string[] {{ "Realistic", "Realista" }})
        if (estilos.Contains(nombre)) {{ vista.VisualStyleId = estilos.GetAt(nombre); break; }}
    ed.SetCurrentView(vista);
    Print("@@VISTA|iso SO");
}}
catch (System.Exception ex) {{ Print("@@AVISO|vista: " + ex.Message); }}"""


def _codigo(grupos: list, cajas: list, losa: list, base_z: float,
            wall_height: float, slab_thickness: float) -> str:
    def huecos(hs: list) -> str:
        return ", ".join(_arreglo(h) for h in hs)

    muros_cs = "\n".join(
        _MURO.format(ext=_arreglo(e), huecos=huecos(hs), z0=_num(base_z),
                     alto=_num(wall_height)) for e, hs in grupos)
    vanos_cs = "\n".join(
        _VANO.format(largo=_num(c["largo"]), ancho=_num(c["ancho"]),
                     alto=_num(c["alto"]), ang=_num(c["angulo"]),
                     cx=_num(c["cx"]), cy=_num(c["cy"]), cz=_num(c["cz"]),
                     tipo=c["type"], px=f"{c['cx']:.2f}", py=f"{c['cy']:.2f}")
        for c in cajas)
    losa_cs = "\n".join(
        _LOSA.format(ext=_arreglo(e), huecos=huecos(hs),
                     z0=_num(base_z + wall_height), alto=_num(slab_thickness))
        for e, hs in losa)

    todos = [p for e, _hs in grupos for p in e]
    x0, x1 = min(p[0] for p in todos), max(p[0] for p in todos)
    y0, y1 = min(p[1] for p in todos), max(p[1] for p in todos)
    z1 = base_z + wall_height + (slab_thickness if losa else 0.0)
    lado = max(x1 - x0, y1 - y0, z1 - base_z)
    vista_cs = _VISTA.format(cx=_num((x0 + x1) / 2), cy=_num((y0 + y1) / 2),
                             cz=_num((base_z + z1) / 2),
                             alto=_num(lado * 1.4), ancho=_num(lado * 2.0))

    return (_PLANTILLA.replace("%MUROS%", muros_cs)
            .replace("%VANOS%", vanos_cs)
            .replace("%LOSA%", losa_cs)
            .replace("%VISTA%", vista_cs)
            .replace("%CAPA_MUROS%", LAYER_MUROS_3D)
            .replace("%CAPA_LOSA%", LAYER_LOSA_3D))


# ----------------------------------------------------------- la tool

def _leer_salida(output: Any) -> dict[str, Any]:
    """Las líneas '@@TIPO|...' que imprime el C#."""
    muros, losas, avisos, vista = [], [], [], None
    for linea in str(output or "").splitlines():
        if not linea.startswith("@@"):
            continue
        tipo, _, resto = linea[2:].partition("|")
        if tipo in ("MURO", "LOSA"):
            handle, _, vol = resto.partition("|")
            item = {"handle": handle, "volume": float(vol or 0)}
            (muros if tipo == "MURO" else losas).append(item)
        elif tipo == "AVISO":
            avisos.append(resto)
        elif tipo == "VISTA":
            vista = resto
    return {"walls": muros, "slabs": losas, "warnings": avisos, "view": vista}


def create_3d_model(rooms: list[dict[str, Any]],
                    doors: Optional[list[dict[str, Any]]] = None,
                    windows: Optional[list[dict[str, Any]]] = None,
                    wall_height: float = 2.50, door_height: float = 2.10,
                    sill_height: float = 0.90, window_head: float = 2.10,
                    slab_thickness: float = 0.12, base_z: float = 0.0,
                    slab: bool = True, offset: Optional[float] = None,
                    exterior_thickness: float = 0.15,
                    interior_thickness: float = 0.10,
                    window_width: float = 1.20,
                    view: bool = True) -> dict[str, Any]:
    """Levanta la planta en 3D con run_code. Ver build() y la spec §4."""
    import engine  # diferido: el motor puede no estar (o estar apagado)

    datos = build(rooms, doors, windows, wall_height=wall_height,
                  door_height=door_height, sill_height=sill_height,
                  window_head=window_head, slab_thickness=slab_thickness,
                  base_z=base_z, slab=slab, offset=offset,
                  exterior_thickness=exterior_thickness,
                  interior_thickness=interior_thickness,
                  window_width=window_width)
    codigo = datos["code"]
    if not view:
        inicio = codigo.index("try\n{\n    var vista")
        fin = codigo.index("return muros.Count;")
        codigo = codigo[:inicio] + codigo[fin:]

    for capa, color in ((LAYER_MUROS_3D, COLOR_MUROS_3D),
                        (LAYER_LOSA_3D, COLOR_LOSA_3D)):
        layers.ensure(capa, color, 25)

    r = engine.run_code(codigo, description="create_3d_model: planta en 3D")
    resultado: dict[str, Any] = {"offset": datos["offset"],
                                 "plan": datos["plan"]}
    avisos = list(datos["warnings"])

    # El motor apagado, bloqueado o con error de compilación no es un
    # modelo a medias: no se dibujó nada y hay que decir por qué.
    if not r.get("compiled", False) or r.get("blocked") or r.get("exception") \
            or r.get("aborted"):
        motivo = (r.get("message") or r.get("blocked") or r.get("exception")
                  or r.get("errors") or "run_code no ejecutó el modelo")
        resultado.update({"ok": False, "error": motivo})
        if r.get("errors"):
            # Una plantilla que no compila es un bug de ESTE módulo, no algo
            # que la IA tenga que arreglar: se devuelve el código para verlo.
            resultado["code"] = codigo
        if avisos:
            resultado["warnings"] = avisos
        return resultado

    salida = _leer_salida(r.get("output"))
    avisos += salida["warnings"]
    vol_muros = sum(m["volume"] for m in salida["walls"])
    vol_losa = sum(s["volume"] for s in salida["slabs"])
    for nombre, medido, esperado in (
            ("mampostería", vol_muros, datos["expectedMasonryVolume"]),
            ("losa", vol_losa, datos["expectedSlabVolume"])):
        if esperado > 0 and abs(medido - esperado) > TOLERANCIA_VOLUMEN * esperado:
            avisos.append(
                f"El volumen de {nombre} que mide AutoCAD ({medido:.3f} m3) "
                f"no coincide con el de la planta ({esperado:.3f} m3): "
                "revisá los vanos de cerca.")

    resultado.update({
        "ok": True,
        "wallHandles": [m["handle"] for m in salida["walls"]],
        "slabHandles": [s["handle"] for s in salida["slabs"]],
        "masonryVolume": round(vol_muros, 4),
        "slabVolume": round(vol_losa, 4),
        "expectedMasonryVolume": round(datos["expectedMasonryVolume"], 4),
        "openingsTotal": datos["openings"],
        "view": salida["view"],
        "created": r.get("created", []),
    })
    if avisos:
        resultado["warnings"] = avisos
    return resultado
