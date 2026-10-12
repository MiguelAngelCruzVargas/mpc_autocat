"""Acabados del modelo 3D: que se vea como una casa y no como una maqueta gris.

create_3d_model levanta muros, vanos y losas en un solo gris. Eso sirve para
revisar volúmenes, no para mostrarle la casa a nadie. dress_3d_model le pone
encima, sobre los MISMOS rooms/doors/windows de cada nivel:

- ladrillo aparente en la fachada: un forro de 12 mm sobre la cara exterior
  de los muros, con los vanos restados (por dentro los muros quedan con
  aplanado blanco, que es lo que se ve en una vista interior);
- vidrio y marco en cada ventana, hoja de madera en cada puerta, vidrio en
  las corredizas; los vanos de paso quedan abiertos;
- losas de concreto, terreno con pasto, banqueta al frente y árboles.

Las texturas son imágenes reales (ladrillo, madera, pasto, follaje) que se
generan acá en Python -- run_code no escribe archivos -- y se mapean a escala
real: un ladrillo de 24 x 6 cm con junta de 1 cm mide eso en el modelo.

set_3d_view pone la cámara: exterior en perspectiva, interior a la altura
de los ojos parado en un recinto, o el corte sin techo para ver la
distribución.

Todo corre con run_code: necesita que el usuario lo haya activado.
"""
from __future__ import annotations

import math
import os
import random
import struct
from typing import Any, Optional

import engine
import layers
import model3d

CAPA_FORRO = "3D-FACHADA"
CAPA_VIDRIO = "3D-VIDRIO"
CAPA_CARPINTERIA = "3D-CARPINTERIA"
CAPA_SITIO = "3D-SITIO"
CAPA_ARBOLES = "3D-ARBOLES"
CAPA_MUEBLES = "3D-MUEBLES"
CAPA_PISO = "3D-PISO"

CARPETA_TEXTURAS = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                                "AutoCadMcp", "texturas")


# ------------------------------------------------------------- texturas

def _bmp(path: str, w: int, h: int, pixel) -> None:
    """BMP de 24 bits sin dependencias (no hay PIL en el entorno)."""
    fila = (w * 3 + 3) // 4 * 4
    datos = bytearray()
    for y in range(h - 1, -1, -1):                 # BMP va de abajo hacia arriba
        linea = bytearray()
        for x in range(w):
            r, g, b = pixel(x, y)
            linea += bytes((max(0, min(255, b)), max(0, min(255, g)), max(0, min(255, r))))
        linea += b"\0" * (fila - w * 3)
        datos += linea
    cab = struct.pack("<2sIHHI", b"BM", 54 + len(datos), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(datos), 2835, 2835, 0, 0)
    with open(path, "wb") as f:
        f.write(cab + info + datos)


def _ladrillo(path: str) -> tuple[float, float]:
    """Tabique rojo recocido 24 x 6 cm con junta de 1 cm, dos hiladas
    cuatrapeadas. 1 px = 2 mm. Devuelve el tamaño real del mosaico (m)."""
    W, H = 250, 70                                 # 0.50 x 0.14 m
    rnd = random.Random(7)
    tonos = {}

    def px(x, y):
        hilada = y // 35
        yy = y % 35
        xx = (x + (62 if hilada else 0)) % W
        if yy < 4 or xx % 125 < 4:                 # junta de mortero
            n = rnd.randint(-8, 8)
            return 178 + n, 172 + n, 160 + n
        pieza = (hilada, (x + (62 if hilada else 0)) // 125 % 2)
        base = tonos.setdefault(pieza, (rnd.randint(150, 185), rnd.randint(68, 92),
                                        rnd.randint(48, 66)))
        n = rnd.randint(-12, 12)
        return base[0] + n, base[1] + n // 2, base[2] + n // 2
    _bmp(path, W, H, px)
    return 0.50, 0.14


def _madera(path: str) -> tuple[float, float]:
    W, H = 128, 256
    rnd = random.Random(3)

    def px(x, y):
        veta = math.sin((x + 6 * math.sin(y / 23.0)) / 3.1) * 14
        n = rnd.randint(-6, 6)
        return int(128 + veta + n), int(82 + veta * 0.7 + n), int(46 + veta * 0.4 + n)
    _bmp(path, W, H, px)
    return 0.40, 0.80


def _pasto(path: str) -> tuple[float, float]:
    W, H = 128, 128
    rnd = random.Random(11)

    def px(x, y):
        n = rnd.randint(-28, 28)
        return 62 + n // 2, 118 + n, 48 + n // 3
    _bmp(path, W, H, px)
    return 1.0, 1.0


def _follaje(path: str) -> tuple[float, float]:
    W, H = 64, 64
    rnd = random.Random(5)

    def px(x, y):
        n = rnd.randint(-35, 35)
        return 40 + n // 2, 96 + n, 38 + n // 3
    _bmp(path, W, H, px)
    return 0.6, 0.6


def _piso(path: str) -> tuple[float, float]:
    """Loseta cerámica de 60 x 60 cm con junta de 3 mm. 1 px = 5 mm."""
    W = 120
    rnd = random.Random(9)

    def px(x, y):
        if x < 1 or y < 1:
            return 150, 146, 138
        n = rnd.randint(-5, 5)
        return 222 + n, 214 + n, 198 + n
    _bmp(path, W, W, px)
    return 0.60, 0.60


def texturas() -> dict[str, tuple[str, float, float]]:
    """Genera (una vez) las imágenes y devuelve {nombre: (ruta, ancho m, alto m)}."""
    os.makedirs(CARPETA_TEXTURAS, exist_ok=True)
    salida = {}
    for nombre, fn in (("ladrillo", _ladrillo), ("madera", _madera), ("pasto", _pasto),
                       ("follaje", _follaje), ("piso", _piso)):
        ruta = os.path.join(CARPETA_TEXTURAS, f"mcp_{nombre}.bmp")
        if not os.path.exists(ruta):
            tam = fn(ruta)
        else:
            tam = {"ladrillo": (0.50, 0.14), "madera": (0.40, 0.80), "pasto": (1.0, 1.0),
                   "follaje": (0.6, 0.6), "piso": (0.60, 0.60)}[nombre]
        salida[nombre] = (ruta, tam[0], tam[1])
    return salida


# ------------------------------------------------------------- el C#

_BASE = r"""
var C = System.Globalization.CultureInfo.InvariantCulture;
var GI = typeof(Autodesk.AutoCAD.GraphicsInterface.Mapper);
System.Func<string, int, int, int, string, double, double, double, ObjectId> material =
    delegate(string nombre, int r, int g, int b, string tex, double sx, double sy, double opac)
{
    var dic = (DBDictionary)tr.GetObject(db.MaterialDictionaryId, OpenMode.ForWrite);
    if (dic.Contains(nombre)) return dic.GetAt(nombre);
    var m = new Material();
    m.Name = nombre;
    var color = new Autodesk.AutoCAD.GraphicsInterface.MaterialColor(
        Autodesk.AutoCAD.GraphicsInterface.Method.Override, 1.0, new EntityColor((byte)r, (byte)g, (byte)b));
    Autodesk.AutoCAD.GraphicsInterface.MaterialMap mapa = new Autodesk.AutoCAD.GraphicsInterface.MaterialMap();
    if (tex != "")
    {
        var t = new Autodesk.AutoCAD.GraphicsInterface.ImageFileTexture();
        t.SourceFileName = tex;
        var escala = new Matrix3d(new double[] { 1.0 / sx, 0, 0, 0, 0, 1.0 / sy, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1 });
        var mp = new Autodesk.AutoCAD.GraphicsInterface.Mapper(
            Autodesk.AutoCAD.GraphicsInterface.Projection.Box,
            Autodesk.AutoCAD.GraphicsInterface.Tiling.Tile, Autodesk.AutoCAD.GraphicsInterface.Tiling.Tile,
            Autodesk.AutoCAD.GraphicsInterface.AutoTransform.None, escala);
        mapa = new Autodesk.AutoCAD.GraphicsInterface.MaterialMap(
            Autodesk.AutoCAD.GraphicsInterface.Source.File, t, 1.0, mp);
    }
    m.Diffuse = new Autodesk.AutoCAD.GraphicsInterface.MaterialDiffuseComponent(color, mapa);
    if (opac < 1.0)
        m.Opacity = new Autodesk.AutoCAD.GraphicsInterface.MaterialOpacityComponent(
            opac, new Autodesk.AutoCAD.GraphicsInterface.MaterialMap());
    var id = dic.SetAt(nombre, m);
    tr.AddNewlyCreatedDBObject(m, true);
    return id;
};
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
    s.SetDatabaseDefaults();
    s.Extrude(r, alto, 0.0);
    r.Dispose();
    s.TransformBy(Matrix3d.Displacement(new Vector3d(0, 0, z0)));
    return s;
};
// Caja de largo x ancho x alto centrada en (cx, cy, cz) y girada 'ang'.
System.Func<double, double, double, double, double, double, double, Solid3d> caja =
    delegate(double lx, double ly, double lz, double cx, double cy, double cz, double ang)
{
    var s = new Solid3d();
    s.SetDatabaseDefaults();
    s.CreateBox(lx, ly, lz);
    s.TransformBy(Matrix3d.Rotation(ang, Vector3d.ZAxis, Point3d.Origin));
    s.TransformBy(Matrix3d.Displacement(new Vector3d(cx, cy, cz)));
    return s;
};
System.Func<Solid3d, string, ObjectId, string> poner = delegate(Solid3d s, string capa, ObjectId mat)
{
    s.Layer = capa;
    s.MaterialId = mat;
    return Add(s);
};
int n = 0;
"""


# Muebles en 3D por piezas (cama con cabecera y almohadas, sofá con
# respaldo, mesa con patas y sillas): una caja por mueble se leía como baúl.
MUEBLES_3D = {
    "bed": (1.60, 2.00), "single_bed": (1.00, 1.90), "nightstand": (0.45, 0.45),
    "closet": (1.50, 0.60), "sofa": (1.90, 0.85), "armchair": (0.85, 0.85),
    "coffee_table": (1.10, 0.55), "dining_table": (1.60, 0.90), "counter": (2.40, 0.60),
    "stove": (0.60, 0.60), "kitchen_sink": (0.80, 0.60), "fridge": (0.70, 0.70),
    "laundry_sink": (0.70, 0.60), "washer": (0.70, 0.70), "wc": (0.40, 0.70),
    "lavatory": (0.60, 0.45), "shower": (0.90, 0.90),
}


def _patas(x0, y0, x1, y1, alto, lado=0.05, mat="mMadera"):
    return [(x0, y0, x0 + lado, y0 + lado, 0, alto, mat), (x1 - lado, y0, x1, y0 + lado, 0, alto, mat),
            (x0, y1 - lado, x0 + lado, y1, 0, alto, mat), (x1 - lado, y1 - lado, x1, y1, 0, alto, mat)]


def _silla(cx, cy, respaldo_y):
    """Silla de 45 x 45 centrada en (cx, cy); respaldo del lado respaldo_y (+1/-1)."""
    s = 0.45
    piezas = [(cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2, 0.43, 0.47, "mMadera")]
    piezas += _patas(cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2, 0.43, 0.04)
    yb = cy + respaldo_y * (s / 2 - 0.02)
    piezas.append((cx - s / 2, yb - 0.02, cx + s / 2, yb + 0.02, 0.47, 0.92, "mMadera"))
    return piezas


def _piezas(tipo: str, w: float, d: float) -> list[tuple]:
    """Piezas del mueble en coordenadas LOCALES (las mismas de furniture.py:
    sin girar, la cabecera de la cama y el respaldo del sofá quedan en y=0;
    la mesa de comedor va centrada). Cada una (x0, y0, x1, y1, z0, z1, mat)."""
    if tipo in ("bed", "single_bed"):
        p = [(0, 0.06, w, d, 0, 0.28, "mMadera"), (0.02, 0.06, w - 0.02, d - 0.02, 0.28, 0.50, "mPorcelana"),
             (0, 0.55, w, d, 0.50, 0.54, "mTela"), (0, 0, w, 0.06, 0, 1.05, "mMadera")]
        n = 2 if w >= 1.40 else 1
        ancho = (w - 0.06 * (n + 1)) / n
        for k in range(n):
            xa = 0.06 + k * (ancho + 0.06)
            p.append((xa, 0.10, xa + ancho, 0.45, 0.50, 0.63, "mPorcelana"))
        return p
    if tipo in ("sofa", "armchair"):
        return [(0, 0, w, d, 0, 0.42, "mTelaGris"), (0, 0, w, 0.20, 0.42, 0.85, "mTelaGris"),
                (0, 0.20, 0.20, d, 0.42, 0.62, "mTelaGris"), (w - 0.20, 0.20, w, d, 0.42, 0.62, "mTelaGris")]
    if tipo == "dining_table":
        x0, y0, x1, y1 = -w / 2, -d / 2, w / 2, d / 2
        p = [(x0, y0, x1, y1, 0.72, 0.76, "mMadera")] + _patas(x0, y0, x1, y1, 0.72, 0.07)
        por_lado = 3 if w >= 1.5 else 2
        for i in range(por_lado):
            cx = x0 + w / por_lado * (i + 0.5)
            p += _silla(cx, y0 - 0.10 - 0.225, -1) + _silla(cx, y1 + 0.10 + 0.225, 1)
        return p
    if tipo == "coffee_table":
        return [(0, 0, w, d, 0.38, 0.42, "mMadera")] + _patas(0, 0, w, d, 0.38)
    if tipo == "nightstand":
        return [(0, 0, w, d, 0, 0.55, "mMadera")]
    if tipo == "closet":
        return [(0, 0, w, d, 0, 2.10, "mMadera")]
    if tipo in ("counter", "kitchen_sink"):
        return [(0, 0, w, d, 0, 0.86, "mAplanado"), (0, 0, w, d, 0.86, 0.90, "mGranito")]
    if tipo == "stove":
        return [(0, 0, w, d, 0, 0.92, "mAcero")]
    if tipo == "fridge":
        return [(0, 0, w, d, 0, 1.75, "mAcero")]
    if tipo == "laundry_sink":
        return [(0, 0, w, d, 0, 0.85, "mConcreto")]
    if tipo == "washer":
        return [(0, 0, w, d, 0, 0.90, "mPorcelana")]
    if tipo == "wc":
        return [(0, 0, w, 0.18, 0, 0.80, "mPorcelana"), (0.03, 0.18, w - 0.03, d, 0, 0.42, "mPorcelana")]
    if tipo == "lavatory":
        return [(0, 0, w, d, 0.65, 0.85, "mPorcelana"), (w / 2 - 0.08, 0.05, w / 2 + 0.08, 0.21, 0, 0.65,
                                                           "mPorcelana")]
    if tipo == "shower":
        return [(0, 0, w, d, 0, 0.06, "mPorcelana")]
    return []


def _mueble(f: dict[str, Any], dx: float, z0: float) -> Optional[str]:
    tipo = f.get("type")
    if tipo not in MUEBLES_3D:
        return None
    w0, d0 = MUEBLES_3D[tipo]
    w = float(f.get("width") or f.get("size") or w0)
    d = float(f.get("depth") or f.get("length") or f.get("size") or d0)
    ang = math.radians(float(f.get("rotation_deg", 0.0)))
    ax, ay = float(f["x"]), float(f["y"])
    c, s = math.cos(ang), math.sin(ang)
    lineas = []
    for x0, y0, x1, y1, za, zb, mat in _piezas(tipo, w, d):
        lx, ly = (x0 + x1) / 2, (y0 + y1) / 2
        cx, cy = ax + lx * c - ly * s, ay + lx * s + ly * c
        lineas.append(f'poner(caja({x1 - x0:.3f}, {y1 - y0:.3f}, {zb - za:.3f}, {cx + dx:.4f}, '
                      f'{cy:.4f}, {z0 + 0.012 + (za + zb) / 2:.4f}, {ang:.6f}), "{CAPA_MUEBLES}", '
                      f'{mat}); n++;')
    return "\n".join(lineas)


def _arr(pts) -> str:
    return "new double[] { " + ", ".join(f"{v:.6f}" for p in pts for v in p) + " }"


def _codigo_nivel(nivel: dict[str, Any], ext: float, inter: float, ventana: float,
                  m: dict[str, str]) -> str:
    """Forro de ladrillo, vidrios, marcos y puertas de un nivel."""
    rooms = [r for r in nivel["rooms"]]
    dx = float(nivel.get("offset", 0.0))
    z0 = float(nivel.get("base_z", 0.0))
    alto_muro = float(nivel.get("wall_height", 2.50))
    losa = float(nivel.get("slab_thickness", 0.12))
    plan = model3d.arch.plan_walls(rooms, nivel.get("doors"), nivel.get("windows"),
                                   exterior_thickness=ext, interior_thickness=inter,
                                   window_width=ventana)
    cajas = model3d._cajas_de_vanos(plan["walls"], z0, float(nivel.get("door_height", 2.10)),
                                    float(nivel.get("sill_height", 0.90)),
                                    float(nivel.get("window_head", 2.10)))
    tol = min(ext, inter) / 2.0 * 1e-5
    adentro = model3d._agrupar(model3d._losa(rooms, ext, tol))
    afuera = model3d._agrupar(model3d._losa(rooms, ext + 0.024, tol))   # +12 mm por lado
    partes = []
    # Forro: anillo entre la cara exterior y 12 mm afuera, de piso a remate
    # de losa, con los vanos restados.
    for (e_out, _h1), (e_in, _h2) in zip(afuera, adentro):
        partes.append(
            "{ var forro = extruir(" + _arr([(p[0] + dx, p[1]) for p in e_out]) +
            ", new double[][] { " + _arr([(p[0] + dx, p[1]) for p in e_in]) + " }, " +
            f"{z0:.4f}, {alto_muro + losa:.4f});")
        for c in cajas:
            partes.append(f"  {{ var v = caja({c['largo']:.4f}, {c['ancho'] + 0.06:.4f}, "
                          f"{c['alto']:.4f}, {c['cx'] + dx:.4f}, {c['cy']:.4f}, {c['cz']:.4f}, "
                          f"{c['angulo']:.6f}); forro.BooleanOperation("
                          "BooleanOperationType.BoolSubtract, v); v.Dispose(); }")
        # Vanos ABIERTOS de fachada (la cochera): ahí no hay muro, el forro
        # no puede taparlos.
        for dd in nivel.get("doors") or []:
            if not dd.get("open") or "x" not in dd:
                continue
            px_, py_, w_ = float(dd["x"]), float(dd["y"]), float(dd.get("width", 0.9))
            horizontal = any(abs(py_ - r[k]) < 1e-6 for r in rooms for k in ("y0", "y1"))
            ang_ = 0.0 if horizontal else math.pi / 2
            partes.append(f"  {{ var v = caja({w_:.4f}, {ext + 0.10:.4f}, {alto_muro:.4f}, "
                          f"{px_ + dx:.4f}, {py_:.4f}, {z0 + alto_muro / 2:.4f}, {ang_:.6f}); "
                          "forro.BooleanOperation(BooleanOperationType.BoolSubtract, v); "
                          "v.Dispose(); }")
        partes.append(f'  poner(forro, "{CAPA_FORRO}", mLadrillo); n++; }}')
    # Piso cerámico sobre todo lo techado del nivel.
    for e_in, huecos in adentro:
        partes.append("poner(extruir(" + _arr([(p[0] + dx, p[1]) for p in e_in]) +
                      ", new double[][] { " + ", ".join(_arr([(p[0] + dx, p[1]) for p in h])
                                                      for h in huecos) +
                      f" }}, {z0:.4f}, 0.012), \"{CAPA_PISO}\", mPiso); n++;")
    for f in nivel.get("furniture") or []:
        linea = _mueble(f, dx, z0)
        if linea:
            partes.append(linea)
    # Carpintería: por vano, según el tipo.
    for c in cajas:
        tipo, L, A, cx, cy, cz, ang = (c["type"], c["largo"], c["alto"], c["cx"] + dx, c["cy"],
                                       c["cz"], c["angulo"])
        if tipo in ("pass", "vano", "opening"):
            continue
        if tipo == "door":
            partes.append(f'poner(caja({L - 0.02:.4f}, 0.045, {A - 0.01:.4f}, {cx:.4f}, '
                          f'{cy:.4f}, {cz - 0.005:.4f}, {ang:.6f}), "{CAPA_CARPINTERIA}", '
                          'mMadera); n++;')
            continue
        # Ventana o corrediza: marco de aluminio + vidrio.
        partes.append(
            f'{{ var marco = caja({L:.4f}, 0.07, {A:.4f}, {cx:.4f}, {cy:.4f}, {cz:.4f}, {ang:.6f});'
            f' var luz = caja({L - 0.10:.4f}, 0.20, {A - 0.10:.4f}, {cx:.4f}, {cy:.4f}, {cz:.4f}, '
            f'{ang:.6f}); marco.BooleanOperation(BooleanOperationType.BoolSubtract, luz); '
            f'luz.Dispose(); poner(marco, "{CAPA_CARPINTERIA}", mAluminio); n++; }}')
        partes.append(f'poner(caja({L - 0.10:.4f}, 0.012, {A - 0.10:.4f}, {cx:.4f}, {cy:.4f}, '
                      f'{cz:.4f}, {ang:.6f}), "{CAPA_VIDRIO}", mVidrio); n++;')
        if tipo in ("sliding", "corrediza") and L > 1.2:
            # parteluz al centro: se lee como dos hojas
            partes.append(f'poner(caja(0.05, 0.07, {A - 0.10:.4f}, {cx:.4f}, {cy:.4f}, '
                          f'{cz:.4f}, {ang:.6f}), "{CAPA_CARPINTERIA}", mAluminio); n++;')
    return "\n".join(partes)


def dress_3d_model(levels: list[dict[str, Any]],
                   exterior_thickness: float = 0.15, interior_thickness: float = 0.10,
                   window_width: float = 1.20,
                   walls_layer: str = model3d.LAYER_MUROS_3D,
                   slab_layer: str = model3d.LAYER_LOSA_3D,
                   roof_visible: bool = True,
                   site_margin: float = 6.0,
                   trees: Optional[list[list[float]]] = None,
                   sidewalk: bool = True) -> dict[str, Any]:
    """Acabados sobre un modelo ya levantado con create_3d_model (uno por
    nivel). Cada nivel: los mismos {rooms, doors, windows, base_z,
    wall_height, slab_thickness, offset} que se usaron para levantarlo, y
    opcionalmente 'furniture' (lo que devolvió suggest_furniture en 'items')
    para amueblarlo en 3D con alturas reales."""
    if not levels:
        raise ValueError("Pasá al menos un nivel (los mismos datos de create_3d_model).")
    tx = texturas()
    for capa, color in ((CAPA_FORRO, 21), (CAPA_VIDRIO, 151), (CAPA_CARPINTERIA, 8),
                        (CAPA_SITIO, 96), (CAPA_ARBOLES, 96), (CAPA_MUEBLES, 8), (CAPA_PISO, 8)):
        layers.ensure(capa, color, 25)

    def ruta(k):
        return tx[k][0].replace("\\", "\\\\")
    mats = (
        f'var mLadrillo = material("MCP Ladrillo aparente", 160, 80, 56, "{ruta("ladrillo")}", '
        f'{tx["ladrillo"][1]}, {tx["ladrillo"][2]}, 1.0);\n'
        'var mAplanado = material("MCP Aplanado blanco", 236, 233, 226, "", 1, 1, 1.0);\n'
        'var mConcreto = material("MCP Concreto", 168, 168, 164, "", 1, 1, 1.0);\n'
        # Losas: plafón blanco (arriba se lee como impermeabilizante blanco);
        # en concreto gris el techo interior salía casi negro.
        'var mLosa = material("MCP Losa (plafon blanco)", 232, 230, 224, "", 1, 1, 1.0);\n'
        'var mVidrio = material("MCP Vidrio", 120, 170, 200, "", 1, 1, 0.35);\n'
        'var mAluminio = material("MCP Aluminio", 70, 72, 76, "", 1, 1, 1.0);\n'
        f'var mMadera = material("MCP Madera", 128, 82, 46, "{ruta("madera")}", '
        f'{tx["madera"][1]}, {tx["madera"][2]}, 1.0);\n'
        f'var mPasto = material("MCP Pasto", 70, 120, 50, "{ruta("pasto")}", '
        f'{tx["pasto"][1]}, {tx["pasto"][2]}, 1.0);\n'
        f'var mFollaje = material("MCP Follaje", 46, 100, 40, "{ruta("follaje")}", '
        f'{tx["follaje"][1]}, {tx["follaje"][2]}, 1.0);\n'
        'var mTronco = material("MCP Tronco", 92, 64, 40, "", 1, 1, 1.0);\n'
        'var mBanqueta = material("MCP Banqueta", 190, 188, 182, "", 1, 1, 1.0);\n'
        f'var mPiso = material("MCP Piso ceramico", 222, 214, 198, "{ruta("piso")}", '
        f'{tx["piso"][1]}, {tx["piso"][2]}, 1.0);\n'
        'var mTela = material("MCP Tela colchas", 86, 116, 156, "", 1, 1, 1.0);\n'
        'var mTelaGris = material("MCP Tela gris", 112, 116, 124, "", 1, 1, 1.0);\n'
        'var mGranito = material("MCP Granito", 58, 56, 54, "", 1, 1, 1.0);\n'
        'var mAcero = material("MCP Acero", 182, 186, 190, "", 1, 1, 1.0);\n'
        'var mPorcelana = material("MCP Porcelana", 246, 246, 244, "", 1, 1, 1.0);\n')
    # El plafón y el aplanado con algo de luz propia: la iluminación por
    # defecto viene de arriba y el techo interior salía casi negro.
    mats += ('((Material)tr.GetObject(mLosa, OpenMode.ForWrite)).SelfIllumination = 0.55;\n'
             '((Material)tr.GetObject(mAplanado, OpenMode.ForWrite)).SelfIllumination = 0.12;\n')
    cuerpo = [mats]
    # Lo que ya levantó create_3d_model: muros con aplanado, losas de concreto.
    capa_cubierta = slab_layer + "_CUBIERTA"
    cuerpo.append(f"""
foreach (ObjectId id in space)
{{
    var e = tr.GetObject(id, OpenMode.ForRead) as Solid3d;
    if (e == null) continue;
    if (e.Layer == "{walls_layer}") {{ e.UpgradeOpen(); e.MaterialId = mAplanado; }}
    else if (e.Layer == "{slab_layer}" || e.Layer == "{capa_cubierta}")
    {{ e.UpgradeOpen(); e.MaterialId = mLosa; }}
}}
{{
    var tabla = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
    if (tabla.Has("{capa_cubierta}"))
        ((LayerTableRecord)tr.GetObject(tabla["{capa_cubierta}"], OpenMode.ForWrite)).IsOff = {str(not roof_visible).lower()};
}}""")
    xs, ys = [], []
    for nivel in levels:
        cuerpo.append(_codigo_nivel(nivel, exterior_thickness, interior_thickness,
                                    window_width, {}))
        dx = float(nivel.get("offset", 0.0))
        for r in nivel["rooms"]:
            xs += [r["x0"] + dx, r["x1"] + dx]
            ys += [r["y0"], r["y1"]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    base = min(float(n.get("base_z", 0.0)) for n in levels)
    m = site_margin
    # Terreno con pasto, 10 cm bajo el piso; banqueta al frente (y menor).
    cuerpo.append(f'poner(caja({x1 - x0 + 2 * m:.3f}, {y1 - y0 + 2 * m:.3f}, 0.10, '
                  f'{(x0 + x1) / 2:.3f}, {(y0 + y1) / 2:.3f}, {base - 0.15:.3f}, 0), '
                  f'"{CAPA_SITIO}", mPasto); n++;')
    if sidewalk:
        cuerpo.append(f'poner(caja({x1 - x0 + 2 * m:.3f}, 1.50, 0.12, {(x0 + x1) / 2:.3f}, '
                      f'{y0 - m + 0.75:.3f}, {base - 0.08:.3f}, 0), "{CAPA_SITIO}", mBanqueta); n++;')
    if trees is None:
        trees = [[x0 - m * 0.55, y0 - m * 0.35], [x1 + m * 0.55, y0 - m * 0.35],
                 [x0 - m * 0.55, y1 + m * 0.45], [x1 + m * 0.6, y1 + m * 0.5],
                 [(x0 + x1) / 2, y1 + m * 0.6]]
    for k, (tx_, ty_) in enumerate(trees):
        h = 2.4 + 0.3 * (k % 3)
        r = 1.2 + 0.2 * (k % 2)
        cuerpo.append(
            f'{{ var t = new Solid3d(); t.SetDatabaseDefaults(); t.CreateFrustum({h:.2f}, 0.13, 0.13, 0.09);'
            f' t.TransformBy(Matrix3d.Displacement(new Vector3d({tx_:.3f}, {ty_:.3f}, {base + h / 2 - 0.1:.3f})));'
            f' poner(t, "{CAPA_ARBOLES}", mTronco);'
            f' var c1 = new Solid3d(); c1.SetDatabaseDefaults(); c1.CreateSphere({r:.2f});'
            f' c1.TransformBy(Matrix3d.Displacement(new Vector3d({tx_:.3f}, {ty_:.3f}, {base + h + r * 0.6:.3f})));'
            f' var c2 = new Solid3d(); c2.SetDatabaseDefaults(); c2.CreateSphere({r * 0.75:.2f});'
            f' c2.TransformBy(Matrix3d.Displacement(new Vector3d({tx_ + r * 0.5:.3f}, {ty_ - r * 0.3:.3f}, {base + h + r * 0.2:.3f})));'
            f' c1.BooleanOperation(BooleanOperationType.BoolUnite, c2); c2.Dispose();'
            f' poner(c1, "{CAPA_ARBOLES}", mFollaje); n += 2; }}')
    cuerpo.append("Print(\"@@PIEZAS|\" + n);\nreturn n;")
    codigo = _BASE + "\n".join(cuerpo)
    r = engine.run_code(codigo, description="dress_3d_model: acabados del 3D")
    if not r.get("compiled", False) or r.get("exception") or r.get("blocked") or r.get("aborted"):
        return {"ok": False, "error": r.get("message") or r.get("exception") or r.get("errors")
                or r.get("blocked") or "run_code no ejecutó los acabados",
                "errors": r.get("errors")}
    piezas = 0
    for linea in str(r.get("output", "")).splitlines():
        if linea.startswith("@@PIEZAS|"):
            piezas = int(linea.split("|")[1])
    return {"ok": True, "pieces": piezas, "box": [x0 - m, y0 - m, x1 + m, y1 + m],
            "materials": ["Ladrillo aparente", "Aplanado blanco", "Concreto", "Vidrio",
                          "Aluminio", "Madera", "Pasto", "Follaje", "Tronco", "Banqueta"],
            "textures": CARPETA_TEXTURAS, "roofVisible": roof_visible}


_VISTA = r"""
var v = ed.GetCurrentView();
v.Target = new Point3d({tx:.4f}, {ty:.4f}, {tz:.4f});
v.ViewDirection = new Vector3d({vx:.4f}, {vy:.4f}, {vz:.4f});
v.ViewTwist = 0.0;
v.CenterPoint = Point2d.Origin;
v.Height = {alto:.4f};
v.Width = {ancho:.4f};
v.PerspectiveEnabled = {persp};
v.LensLength = {lente:.2f};
var estilos = (DBDictionary)tr.GetObject(db.VisualStyleDictionaryId, OpenMode.ForRead);
foreach (var nombre in new string[] {{ "Realistic", "Realista" }})
    if (estilos.Contains(nombre)) {{ v.VisualStyleId = estilos.GetAt(nombre); break; }}
ed.SetCurrentView(v);
{techo}
return 1;
"""


def set_3d_view(camera: list[float], target: list[float], lens: float = 35.0,
                perspective: bool = True, roof_visible: Optional[bool] = None,
                slab_layer: str = model3d.LAYER_LOSA_3D,
                isolate_3d: Optional[bool] = True) -> dict[str, Any]:
    """Cámara 3D: 'camera' es dónde está el ojo [x, y, z] y 'target' adónde
    mira. Interior: el ojo a 1.60 m sobre el piso, dentro de un recinto,
    lente 18-24 (gran angular). Exterior: lente 35-50 desde afuera.
    roof_visible prende o apaga la losa de cubierta (el corte sin techo).
    isolate_3d=True apaga las capas que no son 3D (los planos 2D se veían
    flotando en el cielo de la vista); False las vuelve a prender todas --
    hacelo antes de guardar o de volver a la planta."""
    cx, cy, cz = (float(v) for v in camera)
    tx, ty, tz = (float(v) for v in target)
    vx, vy, vz = cx - tx, cy - ty, cz - tz
    dist = math.sqrt(vx * vx + vy * vy + vz * vz)
    if dist < 1e-6:
        raise ValueError("La cámara y el objetivo no pueden ser el mismo punto.")
    techo = ""
    if roof_visible is not None:
        capa = slab_layer + "_CUBIERTA"
        techo = (f'var tl = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);\n'
                 f'if (tl.Has("{capa}")) ((LayerTableRecord)tr.GetObject(tl["{capa}"], '
                 f'OpenMode.ForWrite)).IsOff = {str(not roof_visible).lower()};')
    if isolate_3d is not None:
        cond = '!c.Name.StartsWith("3D-")' if isolate_3d else "false"
        techo += ("\nforeach (ObjectId lid in (LayerTable)tr.GetObject(db.LayerTableId, "
                  "OpenMode.ForRead)) { var c = (LayerTableRecord)tr.GetObject(lid, OpenMode.ForRead);"
                  f" bool apagar = {cond}; if (c.IsOff != apagar && !(c.Name == \"{slab_layer}_CUBIERTA\" && "
                  f"{'true' if roof_visible is not None else 'false'})) {{ c.UpgradeOpen(); c.IsOff = apagar; }} }}")
    alto = dist * 0.75
    codigo = _VISTA.format(tx=tx, ty=ty, tz=tz, vx=vx, vy=vy, vz=vz, alto=alto, ancho=alto * 1.6,
                           persp="true" if perspective else "false", lente=lens, techo=techo)
    r = engine.run_code(codigo, description="set_3d_view: cámara 3D")
    ok = bool(r.get("compiled")) and not r.get("exception") and not r.get("blocked")
    return {"ok": ok, "camera": [cx, cy, cz], "target": [tx, ty, tz], "lens": lens,
            "error": None if ok else (r.get("exception") or r.get("errors") or r.get("message"))}
