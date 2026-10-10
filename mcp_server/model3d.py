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
            # Cada vano manda con su propio antepecho/alto (los trae de
            # arch.plan_walls): la ventana alta del baño no es la de la sala.
            if tipo == "window":
                z0 = base_z + float(h.get("sill", sill_height))
                z1 = (z0 + float(h["height"]) if "height" in h
                      else base_z + window_head)
            else:
                z0 = base_z
                z1 = base_z + float(h.get("height", door_height))
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
    unión de esos rectángulos es exactamente el paño exterior. Un patio de
    luz rodeado por la casa queda como HUECO de ese contorno: la losa no lo
    tapa, que es lo que lo hace "a cielo abierto"."""
    e = exterior_thickness / 2.0
    piezas = [[(r["x0"] - e, r["y0"] - e), (r["x1"] + e, r["y0"] - e),
               (r["x1"] + e, r["y1"] + e), (r["x0"] - e, r["y1"] + e)]
              for r in rooms if "PATIO" not in str(r["name"]).upper()]
    if not piezas:
        return []
    lazos, _abiertas = wall_network.outline(piezas, [], tol)
    return lazos


def _techado(x: float, y: float, contorno: list) -> bool:
    """¿El punto cae bajo la losa? (dentro de un contorno y fuera de sus
    huecos, como el patio de luz)."""
    for ext, huecos in contorno:
        if point_in_polygon(x, y, ext) and not any(
                point_in_polygon(x, y, h) for h in huecos):
            return True
    return False


def _bardas(muros: list[dict[str, Any]], contorno: list, fence: float,
            hf: float, pendiente: float, y_frente: float, h_max: float,
            tol: float) -> tuple[list[dict[str, Any]], float]:
    """Los tramos de muro SIN techo de ningún lado (bardas de patio), como
    cajas a restar por encima de 'fence', y el volumen que se va con ellas.

    Un muro de colindancia corre de la calle al fondo en UN solo eje: el
    tramo junto a la casa sigue a toda altura y el del patio baja a barda.
    Por eso se recorre el eje en pasos de 5 cm y se mira a los dos costados,
    en vez de clasificar el muro entero."""
    cortes: list[dict[str, Any]] = []
    rects: list[list] = []
    for m in muros:
        (x0, y0), (x1, y1) = m["points"][0], m["points"][-1]
        largo = math.hypot(x1 - x0, y1 - y0)
        if largo < 1e-9:
            continue
        ux, uy = (x1 - x0) / largo, (y1 - y0) / largo
        t = float(m["thickness"])
        sonda = t / 2.0 + 0.05

        def sin_techo(d: float) -> bool:
            px, py = x0 + ux * d, y0 + uy * d
            return not (_techado(px - uy * sonda, py + ux * sonda, contorno)
                        or _techado(px + uy * sonda, py - ux * sonda, contorno))

        def borde(a: float, b: float) -> float:
            # a y b de distinto lado: bisección hasta el borde exacto.
            ea = sin_techo(a)
            for _ in range(40):
                c = (a + b) / 2.0
                if sin_techo(c) == ea:
                    a = c
                else:
                    b = c
            return (a + b) / 2.0

        pasos = max(2, int(largo / 0.05))
        ds = [largo * k / pasos for k in range(pasos + 1)]
        estado = [sin_techo(d) for d in ds]
        k = 0
        while k <= pasos:
            if not estado[k]:
                k += 1
                continue
            j = k
            while j + 1 <= pasos and estado[j + 1]:
                j += 1
            a = 0.0 if k == 0 else borde(ds[k - 1], ds[k])
            b = largo if j == pasos else borde(ds[j], ds[j + 1])
            # En una punta libre o una esquina de bardas la caja sigue medio
            # muro, para llevarse el cuadrito de la esquina; donde empieza
            # el techo, corta justo en la cara.
            a -= t / 2.0 if k == 0 else 0.0
            b += t / 2.0 if j == pasos else 0.0
            if b - a > 1e-6:
                cortes.append({"cx": x0 + ux * (a + b) / 2.0,
                               "cy": y0 + uy * (a + b) / 2.0,
                               "largo": b - a, "ancho": t + 2 * HOLGURA_VANO,
                               "alto": h_max - fence + 1.0 + abs(pendiente) * 100.0,
                               "angulo": math.atan2(uy, ux)})
                px0, py0 = x0 + ux * a, y0 + uy * a
                px1, py1 = x0 + ux * b, y0 + uy * b
                nx, ny = -uy * t / 2.0, ux * t / 2.0
                rects.append([(px0 - nx, py0 - ny), (px1 - nx, py1 - ny),
                              (px1 + nx, py1 + ny), (px0 + nx, py0 + ny)])
            k = j + 1

    if not cortes:
        return [], 0.0
    lazos, _abiertas = wall_network.outline(rects, [], tol)
    area = sum(wall_network._signed_area(l) for l in lazos)
    iy = sum(_integral_y(l) for l in lazos)
    return cortes, (hf - fence) * area - pendiente * (iy - y_frente * area)


def _integral_y(poly: list) -> float:
    """∫ y dA del polígono, con signo (los huecos horarios restan). Es lo que
    da el volumen bajo una losa inclinada: altura media = la del centroide."""
    n = len(poly)
    total = 0.0
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        total += (x0 * y1 - x1 * y0) * (y0 + y1)
    return total / 6.0


def build(rooms: list[dict[str, Any]],
          doors: Optional[list[dict[str, Any]]] = None,
          windows: Optional[list[dict[str, Any]]] = None,
          wall_height: float = 2.50, door_height: float = 2.10,
          sill_height: float = 0.90, window_head: float = 2.10,
          slab_thickness: float = 0.12, base_z: float = 0.0,
          slab: bool = True, offset: Optional[float] = None,
          exterior_thickness: float = 0.15,
          interior_thickness: float = 0.10,
          window_width: float = 1.20,
          clear_height_front: Optional[float] = None,
          clear_height_back: Optional[float] = None,
          floor_thickness: float = 0.0,
          walls_layer: str = LAYER_MUROS_3D,
          slab_layer: str = LAYER_LOSA_3D,
          visual_style: str = "Realistic",
          roof_layer: Optional[str] = None,
          roof_visible: bool = False,
          fence_height: Optional[float] = None) -> dict[str, Any]:
    """Todo lo que hace falta para el 3D, calculado en Python: el C# a
    ejecutar y los volúmenes esperados. No toca AutoCAD.

    clear_height_front / clear_height_back: altura libre (de base_z a la
    cara inferior de la losa) en la fachada de adelante (y mínima) y en la
    de atrás (y máxima). Si vienen, la losa va INCLINADA entre las dos y
    los muros terminan contra ella; mandan sobre wall_height.
    floor_thickness: firme de piso bajo base_z (base_z es el N.P.T.).
    fence_height: alto de las BARDAS (muros sin techo de ningún lado, p.ej.
    los del patio). Sin esto suben hasta el plano de la losa, que es una
    barda de casi 3 m que nadie pidió y que infla los m² de block.
    roof_layer / roof_visible: la losa de CUBIERTA va en su propia capa
    (por default slab_layer + '_CUBIERTA') y APAGADA: el 3D es para ver la
    distribución por dentro, y el techo encima la tapa. Se modela igual
    (remata los muros) y se ve prendiendo la capa o con roof_visible=True.
    """
    hf = wall_height if clear_height_front is None else float(clear_height_front)
    hb = wall_height if clear_height_back is None else float(clear_height_back)
    if min(hf, hb) <= 0:
        raise ValueError(
            "wall_height tiene que ser > 0." if clear_height_front is None
            and clear_height_back is None
            else "Las alturas libres (clear_height_front/back) tienen que ser > 0.")
    h_min = min(hf, hb)
    if not 0 < door_height <= h_min:
        raise ValueError(
            f"door_height ({door_height:g}) tiene que estar entre 0 y la "
            f"altura libre más baja ({h_min:g}).")
    if not 0 <= sill_height < window_head <= h_min:
        raise ValueError(
            f"La ventana va de sill_height ({sill_height:g}) a window_head "
            f"({window_head:g}): el antepecho tiene que quedar abajo del "
            f"cabezal y el cabezal no puede pasar el muro ({h_min:g}).")
    if slab and slab_thickness <= 0:
        raise ValueError("slab_thickness tiene que ser > 0 (o slab=False).")
    if floor_thickness < 0:
        raise ValueError("floor_thickness no puede ser negativo.")

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
    contorno = _agrupar(_losa(rooms, exterior_thickness, tol))
    losa = ([(corrido(e), [corrido(h) for h in hs]) for e, hs in contorno]
            if slab else [])
    piso = ([(corrido(e), [corrido(h) for h in hs]) for e, hs in contorno]
            if floor_thickness > 0 else [])

    # La pendiente se mide de fachada a fachada de lo techado (y de lo
    # construido, si no hay losa).
    ys = [p[1] for e, _hs in (contorno or _agrupar(red["loops"])) for p in e]
    y_frente, y_fondo = min(ys), max(ys)
    pendiente = (hf - hb) / (y_fondo - y_frente) if y_fondo > y_frente else 0.0

    def altura_en(y: float) -> float:
        return hf - pendiente * (y - y_frente)

    # Muro bajo losa inclinada: ∫ h(y) dA = hf·A − pendiente·(∫y dA − y_frente·A).
    area_muros = red["area"]
    iy = sum(_integral_y(l) for l in red["loops"])
    vol_bruto = hf * area_muros - pendiente * (iy - y_frente * area_muros)
    vol_muros = vol_bruto - sum(c["volumen"] for c in cajas)

    bardas = []
    if fence_height is not None and contorno:
        bardas, vol_quitado = _bardas(muros, contorno, float(fence_height),
                                      hf, pendiente, y_frente, max(hf, hb), tol)
        vol_muros -= vol_quitado
        for b in bardas:
            b["cx"] += dx
            b["cz"] = base_z + float(fence_height) + b["alto"] / 2.0
    # Con losa inclinada el volumen sigue siendo área × espesor: es un prisma
    # vertical cortado por dos planos paralelos (espesor medido en vertical).
    area_techada = sum(
        wall_network._signed_area(e) + sum(wall_network._signed_area(h)
                                           for h in hs)
        for e, hs in contorno)

    avisos_vanos = []
    for c in cajas:
        tope = altura_en(c["cy"]) + base_z
        if c["cz"] + c["alto"] / 2.0 > tope + 1e-6:
            avisos_vanos.append(
                f"Un vano ({c['type']}) en ({c['cx'] - dx:.2f}, {c['cy']:.2f}) "
                f"llega a {c['cz'] + c['alto'] / 2.0 - base_z:.2f} m y la losa "
                f"ahí está a {tope - base_z:.2f} m: lo corta la losa.")

    return {
        "code": _codigo(grupos, cajas, losa, piso, base_z, hf, hb,
                        y_frente, y_fondo, slab_thickness, floor_thickness,
                        walls_layer, slab_layer, visual_style,
                        roof_layer or slab_layer + "_CUBIERTA", roof_visible,
                        bardas),
        "fences": len(bardas),
        "roofLayer": roof_layer or slab_layer + "_CUBIERTA",
        "offset": [dx, 0.0],
        "openings": len(cajas),
        "slope": pendiente,
        "expectedMasonryVolume": vol_muros,
        "expectedSlabVolume": area_techada * slab_thickness if losa else 0.0,
        "expectedFloorVolume": area_techada * floor_thickness if piso else 0.0,
        "plan": {k: plan[k] for k in ("doorsPlaced", "doorsTotal",
                                      "windowsPlaced")},
        "warnings": list(plan["warnings"]) + avisos_vanos,
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

// La losa inclinada es un plano z = zFrente - pendiente·(y - yFrente). La
// "cuchilla" es una caja enorme cuya cara cae justo en ese plano: restarla
// deja el muro terminado contra la cara inferior de la losa, y dos (una por
// arriba y otra por abajo) dejan la losa misma con su espesor.
System.Func<double, bool, Solid3d> cuchilla = delegate(double zFrente, bool quitaArriba)
{
    var c = new Solid3d();
    c.CreateBox(%CUCH_LX%, %CUCH_LY%, 50.0);
    c.TransformBy(Matrix3d.Displacement(new Vector3d(0, 0, quitaArriba ? 25.0 : -25.0)));
    c.TransformBy(Matrix3d.Rotation(-%CUCH_ANG%, Vector3d.XAxis, Point3d.Origin));
    c.TransformBy(Matrix3d.Displacement(new Vector3d(%CUCH_CX%, %CUCH_YF%, zFrente)));
    return c;
};
System.Action<Solid3d, Solid3d> recortar = delegate(Solid3d s, Solid3d c)
{
    s.BooleanOperation(BooleanOperationType.BoolSubtract, c);
    c.Dispose();
};

var muros = new System.Collections.Generic.List<Solid3d>();
%MUROS%
%RECORTE%
%BARDAS%

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
%APAGAR_CUBIERTA%
%PISO%

%VISTA%
return muros.Count;
"""

_MURO = "muros.Add(extruir({ext}, new double[][] {{ {huecos} }}, {z0}, {alto}));"

# Barda: lo que sobra por encima de su alto se quita con una caja; una caja
# nueva por muro, porque restar consume el sólido que se resta.
_BARDA = """foreach (var m in muros)
{{
    var corte = new Solid3d();
    corte.CreateBox({largo}, {ancho}, {alto});
    corte.TransformBy(Matrix3d.Rotation({ang}, Vector3d.ZAxis, Point3d.Origin));
    corte.TransformBy(Matrix3d.Displacement(new Vector3d({cx}, {cy}, {cz})));
    if (tocan(m.GeometricExtents, corte.GeometricExtents))
        m.BooleanOperation(BooleanOperationType.BoolSubtract, corte);
    corte.Dispose();
}}"""

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
    {recorte}
    losa.Layer = "%CAPA_CUBIERTA%";
    Print("@@LOSA|" + Add(losa) + "|" + losa.MassProperties.Volume.ToString(C));
}}"""

_PISO = """{{
    var piso = extruir({ext}, new double[][] {{ {huecos} }}, {z0}, {alto});
    piso.Layer = "%CAPA_LOSA%";
    Print("@@PISO|" + Add(piso) + "|" + piso.MassProperties.Volume.ToString(C));
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
    foreach (var nombre in new string[] {{ {estilos} }})
        if (estilos.Contains(nombre)) {{ vista.VisualStyleId = estilos.GetAt(nombre); break; }}
    ed.SetCurrentView(vista);
    Print("@@VISTA|iso SO");
}}
catch (System.Exception ex) {{ Print("@@AVISO|vista: " + ex.Message); }}"""

_APAGAR = """{
    var tabla = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
    if (tabla.Has("%CAPA_CUBIERTA%"))
        ((LayerTableRecord)tr.GetObject(tabla["%CAPA_CUBIERTA%"], OpenMode.ForWrite)).IsOff = true;
}"""

# El nombre del estilo visual puede venir traducido en un AutoCAD en
# castellano: se prueban los dos.
_ESTILOS = {
    "realistic": ("Realistic", "Realista"),
    "conceptual": ("Conceptual",),
    "shaded with edges": ("Shaded with edges", "Sombreado con aristas"),
    "shaded": ("Shaded", "Sombreado"),
    "2d wireframe": ("2dWireframe", "Estructura alámbrica 2D"),
}


def _codigo(grupos: list, cajas: list, losa: list, piso: list,
            base_z: float, hf: float, hb: float, y_frente: float,
            y_fondo: float, slab_thickness: float, floor_thickness: float,
            walls_layer: str, slab_layer: str, visual_style: str,
            roof_layer: str = "", roof_visible: bool = True,
            bardas: Optional[list] = None) -> str:
    def huecos(hs: list) -> str:
        return ", ".join(_arreglo(h) for h in hs)

    inclinada = abs(hf - hb) > 1e-9
    h_max, h_min = max(hf, hb), min(hf, hb)
    pendiente = (hf - hb) / (y_fondo - y_frente) if y_fondo > y_frente else 0.0

    todos = [p for e, _hs in grupos for p in e]
    x0, x1 = min(p[0] for p in todos), max(p[0] for p in todos)
    y0, y1 = min(p[1] for p in todos), max(p[1] for p in todos)

    # Muros: hasta la losa en su punto más alto, y si es inclinada se
    # recortan contra su cara inferior.
    muros_cs = "\n".join(
        _MURO.format(ext=_arreglo(e), huecos=huecos(hs), z0=_num(base_z),
                     alto=_num(h_max)) for e, hs in grupos)
    recorte_cs = ("foreach (var m in muros) recortar(m, cuchilla("
                  f"{_num(base_z + hf)}, true));" if inclinada else "")
    bardas_cs = "\n".join(
        _BARDA.format(largo=_num(b["largo"]), ancho=_num(b["ancho"]),
                      alto=_num(b["alto"]), ang=_num(b["angulo"]),
                      cx=_num(b["cx"]), cy=_num(b["cy"]), cz=_num(b["cz"]))
        for b in (bardas or []))
    vanos_cs = "\n".join(
        _VANO.format(largo=_num(c["largo"]), ancho=_num(c["ancho"]),
                     alto=_num(c["alto"]), ang=_num(c["angulo"]),
                     cx=_num(c["cx"]), cy=_num(c["cy"]), cz=_num(c["cz"]),
                     tipo=c["type"], px=f"{c['cx']:.2f}", py=f"{c['cy']:.2f}")
        for c in cajas)

    # Losa: plana, o un prisma que cubre todo el rango y se recorta entre
    # el plano inferior y el mismo plano subido 'slab_thickness'.
    if inclinada:
        z0_losa, alto_losa = base_z + h_min - 0.05, h_max - h_min + slab_thickness + 0.10
        recorte_losa = (f"recortar(losa, cuchilla({_num(base_z + hf + slab_thickness)}, true)); "
                        f"recortar(losa, cuchilla({_num(base_z + hf)}, false));")
    else:
        z0_losa, alto_losa, recorte_losa = base_z + hf, slab_thickness, ""
    losa_cs = "\n".join(
        _LOSA.format(ext=_arreglo(e), huecos=huecos(hs), z0=_num(z0_losa),
                     alto=_num(alto_losa), recorte=recorte_losa)
        for e, hs in losa)
    piso_cs = "\n".join(
        _PISO.format(ext=_arreglo(e), huecos=huecos(hs),
                     z0=_num(base_z - floor_thickness),
                     alto=_num(floor_thickness))
        for e, hs in piso)

    z1 = base_z + h_max + (slab_thickness if losa else 0.0)
    lado = max(x1 - x0, y1 - y0, z1 - base_z)
    nombres = _ESTILOS.get(visual_style.lower(), (visual_style,))
    vista_cs = _VISTA.format(cx=_num((x0 + x1) / 2), cy=_num((y0 + y1) / 2),
                             cz=_num((base_z + z1) / 2),
                             alto=_num(lado * 1.4), ancho=_num(lado * 2.0),
                             estilos=", ".join('"' + n + '"' for n in nombres))

    return (_PLANTILLA.replace("%MUROS%", muros_cs)
            .replace("%RECORTE%", recorte_cs)
            .replace("%BARDAS%", bardas_cs)
            .replace("%VANOS%", vanos_cs)
            .replace("%LOSA%", losa_cs)
            .replace("%PISO%", piso_cs)
            .replace("%VISTA%", vista_cs)
            .replace("%CUCH_LX%", _num(x1 - x0 + 20.0))
            .replace("%CUCH_LY%", _num(2.0 * (y1 - y0 + 20.0)))
            .replace("%CUCH_ANG%", _num(math.atan(pendiente)))
            .replace("%CUCH_CX%", _num((x0 + x1) / 2.0))
            .replace("%CUCH_YF%", _num(y_frente))
            .replace("%APAGAR_CUBIERTA%", "" if roof_visible or not losa else _APAGAR)
            .replace("%CAPA_CUBIERTA%", roof_layer or slab_layer)
            .replace("%CAPA_MUROS%", walls_layer)
            .replace("%CAPA_LOSA%", slab_layer))


# ----------------------------------------------------------- la tool

def _leer_salida(output: Any) -> dict[str, Any]:
    """Las líneas '@@TIPO|...' que imprime el C#."""
    muros, losas, pisos, avisos, vista = [], [], [], [], None
    for linea in str(output or "").splitlines():
        if not linea.startswith("@@"):
            continue
        tipo, _, resto = linea[2:].partition("|")
        if tipo in ("MURO", "LOSA", "PISO"):
            handle, _, vol = resto.partition("|")
            item = {"handle": handle, "volume": float(vol or 0)}
            {"MURO": muros, "LOSA": losas, "PISO": pisos}[tipo].append(item)
        elif tipo == "AVISO":
            avisos.append(resto)
        elif tipo == "VISTA":
            vista = resto
    return {"walls": muros, "slabs": losas, "floors": pisos,
            "warnings": avisos, "view": vista}


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
                    view: bool = True,
                    clear_height_front: Optional[float] = None,
                    clear_height_back: Optional[float] = None,
                    floor_thickness: float = 0.0,
                    walls_layer: str = LAYER_MUROS_3D,
                    slab_layer: str = LAYER_LOSA_3D,
                    visual_style: str = "Realistic",
                    roof_layer: Optional[str] = None,
                    roof_visible: bool = False,
                    fence_height: Optional[float] = None) -> dict[str, Any]:
    """Levanta la planta en 3D con run_code. Ver build() y la spec §4."""
    import engine  # diferido: el motor puede no estar (o estar apagado)

    datos = build(rooms, doors, windows, wall_height=wall_height,
                  door_height=door_height, sill_height=sill_height,
                  window_head=window_head, slab_thickness=slab_thickness,
                  base_z=base_z, slab=slab, offset=offset,
                  exterior_thickness=exterior_thickness,
                  interior_thickness=interior_thickness,
                  window_width=window_width,
                  clear_height_front=clear_height_front,
                  clear_height_back=clear_height_back,
                  floor_thickness=floor_thickness, walls_layer=walls_layer,
                  slab_layer=slab_layer, visual_style=visual_style,
                  roof_layer=roof_layer, roof_visible=roof_visible,
                  fence_height=fence_height)
    codigo = datos["code"]
    if not view:
        inicio = codigo.index("try\n{\n    var vista")
        fin = codigo.index("return muros.Count;")
        codigo = codigo[:inicio] + codigo[fin:]

    for capa, color in ((walls_layer, COLOR_MUROS_3D),
                        (slab_layer, COLOR_LOSA_3D),
                        (datos["roofLayer"], COLOR_LOSA_3D)):
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
    vol_piso = sum(s["volume"] for s in salida["floors"])
    for nombre, medido, esperado in (
            ("mampostería", vol_muros, datos["expectedMasonryVolume"]),
            ("losa", vol_losa, datos["expectedSlabVolume"]),
            ("firme", vol_piso, datos["expectedFloorVolume"])):
        if esperado > 0 and abs(medido - esperado) > TOLERANCIA_VOLUMEN * esperado:
            avisos.append(
                f"El volumen de {nombre} que mide AutoCAD ({medido:.3f} m3) "
                f"no coincide con el de la planta ({esperado:.3f} m3): "
                "revisá los vanos de cerca.")

    resultado.update({
        "ok": True,
        "wallHandles": [m["handle"] for m in salida["walls"]],
        "slabHandles": [s["handle"] for s in salida["slabs"]],
        "floorHandles": [s["handle"] for s in salida["floors"]],
        "masonryVolume": round(vol_muros, 4),
        "slabVolume": round(vol_losa, 4),
        "floorVolume": round(vol_piso, 4),
        "slope": round(datos["slope"], 5),
        "expectedMasonryVolume": round(datos["expectedMasonryVolume"], 4),
        "openingsTotal": datos["openings"],
        "view": salida["view"],
        "created": r.get("created", []),
    })
    if avisos:
        resultado["warnings"] = avisos
    return resultado
