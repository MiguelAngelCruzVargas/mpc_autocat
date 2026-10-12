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
CAPA_ESCALERA = "3D-ESCALERA"
CAPA_AZOTEA = "3D-AZOTEA"
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


def _duela(path: str) -> tuple[float, float]:
    """Duela de madera de 19 x 120 cm, juntas cuatrapeadas. 1 px = 5 mm."""
    W, H = 240, 152                                   # 1.20 x 0.76 m: 4 duelas
    rnd = random.Random(21)
    tonos = [rnd.randint(-16, 16) for _ in range(8)]

    def px(x, y):
        fila = y // 38
        desfase = (fila * 97) % W
        xx = (x + desfase) % W
        if y % 38 == 0 or xx == 0:
            return 92, 62, 38
        t = tonos[fila * 2 + (1 if xx > W // 2 else 0)]
        veta = int(6 * math.sin((xx + fila * 13) / 7.0 + math.sin(y / 5.0)))
        n = rnd.randint(-5, 5)
        return 168 + t + veta + n, 122 + t + veta + n, 80 + t // 2 + n
    _bmp(path, W, H, px)
    return 1.20, 0.76


def _porcelanato(path: str) -> tuple[float, float]:
    """Porcelanato claro de 60 x 120 cm con junta de 2 mm. 1 px = 5 mm."""
    W, H = 240, 120
    rnd = random.Random(31)

    def px(x, y):
        if x == 0 or y == 0:
            return 176, 172, 164
        n = rnd.randint(-4, 4)
        nube = int(5 * math.sin(x / 31.0) * math.cos(y / 23.0))
        return 228 + n + nube, 225 + n + nube, 218 + n + nube
    _bmp(path, W, H, px)
    return 1.20, 0.60


def _loseta(path: str) -> tuple[float, float]:
    """Loseta de 30 x 30 cm, gris cálido, para baño y cocina. 1 px = 3 mm."""
    W = 100
    rnd = random.Random(41)

    def px(x, y):
        if x < 1 or y < 1:
            return 140, 136, 128
        n = rnd.randint(-6, 6)
        return 196 + n, 190 + n, 180 + n
    _bmp(path, W, W, px)
    return 0.30, 0.30


def _azulejo(path: str) -> tuple[float, float]:
    """Azulejo blanco de 20 x 30 cm en muro de baño, junta gris. 1 px = 2 mm."""
    W, H = 100, 150
    rnd = random.Random(51)

    def px(x, y):
        if x < 1 or y < 1:
            return 168, 168, 166
        n = rnd.randint(-3, 3)
        return 242 + n, 243 + n, 244 + n
    _bmp(path, W, H, px)
    return 0.20, 0.30


def _concreto_pulido(path: str) -> tuple[float, float]:
    W = 128
    rnd = random.Random(61)

    def px(x, y):
        n = rnd.randint(-10, 10)
        m = int(8 * math.sin(x / 17.0 + y / 29.0))
        return 160 + n + m, 158 + n + m, 154 + n + m
    _bmp(path, W, W, px)
    return 1.5, 1.5


def texturas() -> dict[str, tuple[str, float, float]]:
    """Genera (una vez) las imágenes y devuelve {nombre: (ruta, ancho m, alto m)}."""
    os.makedirs(CARPETA_TEXTURAS, exist_ok=True)
    salida = {}
    for nombre, fn in (("ladrillo", _ladrillo), ("madera", _madera), ("pasto", _pasto),
                       ("follaje", _follaje), ("piso", _piso), ("duela", _duela),
                       ("porcelanato", _porcelanato), ("loseta", _loseta), ("azulejo", _azulejo),
                       ("concreto_pulido", _concreto_pulido)):
        ruta = os.path.join(CARPETA_TEXTURAS, f"mcp_{nombre}.bmp")
        if not os.path.exists(ruta):
            tam = fn(ruta)
        else:
            tam = {"ladrillo": (0.50, 0.14), "madera": (0.40, 0.80), "pasto": (1.0, 1.0),
                   "follaje": (0.6, 0.6), "piso": (0.60, 0.60), "duela": (1.20, 0.76),
                   "porcelanato": (1.20, 0.60), "loseta": (0.30, 0.30), "azulejo": (0.20, 0.30),
                   "concreto_pulido": (1.5, 1.5)}[nombre]
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
// Barra de largo L (sección a x h) inclinada 'pitch' y con rumbo 'yaw',
// centrada en (cx, cy, cz): pasamanos, vigas.
System.Func<double, double, double, double, double, double, double, double, Solid3d> barra =
    delegate(double L, double a, double h, double pitch, double yaw, double cx, double cy, double cz)
{
    var s = new Solid3d();
    s.SetDatabaseDefaults();
    s.CreateBox(L, a, h);
    s.TransformBy(Matrix3d.Rotation(-pitch, Vector3d.YAxis, Point3d.Origin));
    s.TransformBy(Matrix3d.Rotation(yaw, Vector3d.ZAxis, Point3d.Origin));
    s.TransformBy(Matrix3d.Displacement(new Vector3d(cx, cy, cz)));
    return s;
};
// Contorno desplazado hacia afuera (true) o adentro (false) d metros.
System.Func<double[], double, bool, double[]> desplazar = delegate(double[] c, double d, bool afuera)
{
    if (System.Math.Abs(d) < 1e-9) return c;
    var pl = new Polyline();
    for (int i = 0; i < c.Length / 2; i++)
        pl.AddVertexAt(i, new Point2d(c[2 * i], c[2 * i + 1]), 0, 0, 0);
    pl.Closed = true;
    Polyline mejor = null;
    foreach (double sd in new double[] { d, -d })
    {
        var curvas = pl.GetOffsetCurves(sd);
        foreach (DBObject o in curvas)
        {
            var p = o as Polyline;
            if (p != null && (mejor == null || (afuera ? p.Area > mejor.Area : p.Area < mejor.Area)))
            { if (mejor != null) mejor.Dispose(); mejor = p; }
            else o.Dispose();
        }
    }
    pl.Dispose();
    var r = new double[mejor.NumberOfVertices * 2];
    for (int i = 0; i < mejor.NumberOfVertices; i++)
    { var v = mejor.GetPoint2dAt(i); r[2 * i] = v.X; r[2 * i + 1] = v.Y; }
    mejor.Dispose();
    return r;
};
// Anillo entre el contorno desplazado dOut hacia afuera y dIn hacia adentro.
System.Func<double[], double, double, double, double, Solid3d> anillo =
    delegate(double[] c, double dOut, double dIn, double z0, double alto)
{
    return extruir(desplazar(c, dOut, true), new double[][] { desplazar(c, dIn, false) }, z0, alto);
};
// Restar una caja de todo sólido de esas capas que la toque (hueco de escalera).
System.Action<string[], double, double, double, double, double, double> perforar =
    delegate(string[] capas, double x0, double y0, double x1, double y1, double z0, double z1)
{
    var ids = new System.Collections.Generic.List<ObjectId>();
    foreach (ObjectId id in space) ids.Add(id);
    foreach (var id in ids)
    {
        var e = tr.GetObject(id, OpenMode.ForRead) as Solid3d;
        if (e == null || System.Array.IndexOf(capas, e.Layer) < 0) continue;
        var ex = e.GeometricExtents;
        if (ex.MaxPoint.X <= x0 || ex.MinPoint.X >= x1 || ex.MaxPoint.Y <= y0 || ex.MinPoint.Y >= y1
            || ex.MaxPoint.Z <= z0 || ex.MinPoint.Z >= z1) continue;
        e.UpgradeOpen();
        var h = caja(x1 - x0, y1 - y0, z1 - z0, (x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2, 0);
        e.BooleanOperation(BooleanOperationType.BoolSubtract, h);
        h.Dispose();
    }
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
    # Cocina: gabinete con zoclo, cubierta de granito y alacena arriba (a
    # 1.45 del piso, 35 cm de fondo); sobre la estufa, campana. En todos
    # y=0 es el muro, igual que en furniture.py.
    if tipo in ("counter", "kitchen_sink"):
        p = [(0, 0, w, d - 0.05, 0, 0.10, "mNegro"), (0, 0, w, d, 0.10, 0.86, "mMadera"),
             (0, 0, w, d + 0.02, 0.86, 0.90, "mGranito"), (0, 0, w, 0.35, 1.45, 2.15, "mMadera"),
             (0, 0, w, 0.008, 0.90, 1.45, "mAzulejo")]
        if tipo == "kitchen_sink":
            p += [(0.06, 0.10, w * 0.56, d - 0.10, 0.90, 0.905, "mAcero"),
                  (w * 0.31 - 0.015, 0.03, w * 0.31 + 0.015, 0.07, 0.90, 1.20, "mAcero"),
                  (w * 0.31 - 0.015, 0.03, w * 0.31 + 0.015, 0.25, 1.17, 1.20, "mAcero")]
        return p
    if tipo == "stove":
        return [(0, 0, w, d, 0, 0.90, "mAcero"), (0.02, 0.02, w - 0.02, d - 0.02, 0.90, 0.92, "mNegro"),
                (0, 0, w, 0.008, 0.92, 1.60, "mAzulejo"),
                (0, 0, w, 0.50, 1.60, 1.75, "mAcero"),
                (w / 2 - 0.13, 0, w / 2 + 0.13, 0.26, 1.75, 2.40, "mAcero")]
    if tipo == "fridge":
        return [(0, 0, w, d, 0, 1.75, "mAcero")]
    if tipo == "laundry_sink":
        return [(0, 0, w, d, 0, 0.85, "mConcreto")]
    if tipo == "washer":
        return [(0, 0, w, d, 0, 0.90, "mPorcelana")]
    if tipo == "wc":
        # Tanque contra el muro con su tapa, pedestal y taza con asiento.
        return [(0.02, 0, w - 0.02, 0.18, 0.40, 0.78, "mPorcelana"), (0, 0, w, 0.20, 0.78, 0.81, "mPorcelana"),
                (0.10, 0.12, w - 0.10, d - 0.15, 0, 0.36, "mPorcelana"),
                (0.02, 0.15, w - 0.02, d, 0.36, 0.42, "mPorcelana")]
    if tipo == "lavatory":
        # Mueble de lavabo con cubierta, ovalín, llave y espejo en el muro.
        return [(0, 0.02, w, d, 0.10, 0.80, "mMadera"), (0, 0, w, d + 0.02, 0.80, 0.83, "mGranito"),
                (w / 2 - 0.20, 0.09, w / 2 + 0.20, d - 0.06, 0.83, 0.88, "mPorcelana"),
                (w / 2 - 0.015, 0.03, w / 2 + 0.015, 0.07, 0.83, 1.02, "mAcero"),
                (w / 2 - 0.015, 0.03, w / 2 + 0.015, 0.18, 0.99, 1.02, "mAcero"),
                (0.03, 0, w - 0.03, 0.015, 1.05, 1.85, "mEspejo")]
    if tipo == "shower":
        # Plato, cancel de vidrio templado con perfil negro en el lado
        # abierto (y=d), regadera de brazo y mezcladora en el muro (y=0).
        p = [(0, 0, w, d, 0, 0.06, "mPorcelana"), (0, d - 0.012, w, d, 0.06, 1.95, "mVidrio"),
             (0, d - 0.025, w, d + 0.005, 1.95, 1.98, "mAluminio"),
             (w / 2 - 0.015, 0, w / 2 + 0.015, 0.32, 2.02, 2.05, "mAcero"),
             (w / 2 - 0.11, 0.21, w / 2 + 0.11, 0.43, 1.99, 2.02, "mAcero"),
             (w / 2 - 0.06, 0, w / 2 + 0.06, 0.03, 1.10, 1.24, "mAcero")]
        for xp in (0, w / 2 - 0.0125, w - 0.025):
            p.append((xp, d - 0.025, xp + 0.025, d + 0.005, 0.06, 1.95, "mAluminio"))
        return p
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


def _lado_exterior(c: dict[str, Any], adentro: list, tw: float) -> int:
    """+1 / -1: hacia qué lado de la normal del muro queda la calle; 0 si
    el muro es interior (los dos lados caen dentro de la casa)."""
    nx, ny = -math.sin(c["angulo"]), math.cos(c["angulo"])
    d = tw / 2 + 0.20

    def dentro(x, y):
        return any(model3d.point_in_polygon(x, y, e) and
                   not any(model3d.point_in_polygon(x, y, h) for h in hs) for e, hs in adentro)
    a = dentro(c["cx"] + nx * d, c["cy"] + ny * d)
    b = dentro(c["cx"] - nx * d, c["cy"] - ny * d)
    return 0 if a == b else (1 if not a else -1)


BARANDAL_ALTO = 0.90       # sobre la línea de narices o el piso
BARROTE_CLARO = 0.10       # claro libre máximo entre barrotes (que no pase un niño)


def _barandal(ax: float, ay: float, bx: float, by: float, za: float, zb: float,
              base, alto: float = BARANDAL_ALTO, zoclo: bool = False,
              nudos: Optional[set] = None) -> list[str]:
    """Barandal completo de A a B: pasamanos que va de za+alto a zb+alto,
    postes en los extremos y a no más de 1.20, y barrotes con claro libre de
    BARROTE_CLARO que nacen en base(d) (el escalón o el piso) y MUEREN EN el
    pasamanos. Postes de altura fija contra un pasamanos inclinado quedaban
    unos cortos y otros pasados, y sin barrotes el barandal se veía a medias.

    El pasamanos se corta justo en A y B, y en cada extremo va un codo (un
    nudo de 6 cm): dos tubos rectos que se encuentran en ángulo dejan la
    esquina abierta y las puntas salidas. 'nudos' (compartido entre los
    tramos de una escalera) evita poner dos codos en la misma unión."""
    L = math.hypot(bx - ax, by - ay)
    if L < 0.05:
        return []
    ux, uy = (bx - ax) / L, (by - ay) / L
    yaw = math.atan2(uy, ux)
    pend = (zb - za) / L

    def riel(d):
        return za + alto + pend * d
    p = []
    sube = zb - za
    p.append(f'poner(barra({math.hypot(L, sube):.4f}, 0.05, 0.04, {math.atan2(sube, L):.6f}, '
             f'{yaw:.6f}, {ax + ux * L / 2:.4f}, {ay + uy * L / 2:.4f}, {riel(L / 2) + 0.02:.4f}), '
             f'"{CAPA_ESCALERA}", mAcero); n++;')
    for d in (0.0, L):
        clave = (round(ax + ux * d, 2), round(ay + uy * d, 2), round(riel(d), 2))
        if nudos is not None:
            if clave in nudos:
                continue
            nudos.add(clave)
        p.append(f'poner(caja(0.06, 0.06, 0.06, {ax + ux * d:.4f}, {ay + uy * d:.4f}, '
                 f'{riel(d) + 0.02:.4f}, {yaw:.6f}), "{CAPA_ESCALERA}", mAcero); n++;')

    def vertical(d, lado, alto_extra=0.0):
        z0_, z1_ = base(d), riel(d) + alto_extra
        if z1_ - z0_ < 0.05:
            return
        p.append(f'poner(caja({lado:.3f}, {lado:.3f}, {z1_ - z0_:.4f}, {ax + ux * d:.4f}, '
                 f'{ay + uy * d:.4f}, {(z0_ + z1_) / 2:.4f}, {yaw:.6f}), "{CAPA_ESCALERA}", mAcero); n++;')
    k = max(1, math.ceil(L / 1.20))
    for i in range(k + 1):
        vertical(min(max(L * i / k, 0.02), L - 0.02), 0.04)
    paso = BARROTE_CLARO + 0.016
    m = max(1, round(L / paso))
    for i in range(1, m):
        vertical(L * i / m, 0.016)
    if zoclo:
        p.append(f'poner(barra({math.hypot(L, sube):.4f}, 0.04, 0.03, {math.atan2(sube, L):.6f}, {yaw:.6f}, '
                 f'{ax + ux * L / 2:.4f}, {ay + uy * L / 2:.4f}, {base(L / 2) + 0.015:.4f}), '
                 f'"{CAPA_ESCALERA}", mAcero); n++;')
    return p


def _codigo_escalera(st: dict[str, Any], dx: float) -> str:
    """Escalera de concreto por tramos rectos (los mismos datos de
    create_stairs: arranque = centro de la primera contrahuella), descansos,
    huella de madera, barandal del lado indicado y el hueco en la losa."""
    p = []
    rieles = []          # (arranque, final, nivel de llegada) de cada barandal
    nudos: set = set()
    for f in st.get("flights", []):
        sx, sy = float(f["start"][0]) + dx, float(f["start"][1])
        a = math.radians(float(f.get("direction_deg", 90.0)))
        ux, uy = math.cos(a), math.sin(a)
        w = float(f.get("width", 1.0))
        n_ = int(f["risers"])
        r = float(f["riser"])
        t = float(f["tread"])
        z0 = float(f.get("base_z", 0.0))
        for i in range(n_ - 1):
            zt = z0 + (i + 1) * r
            dc = (i + 0.5) * t
            cx, cy = sx + ux * dc, sy + uy * dc
            fondo = (zt - z0) if z0 < 0.01 else (r + 0.12)   # el primer tramo apoya en el piso
            p.append(f'poner(caja({t:.4f}, {w:.4f}, {fondo:.4f}, {cx:.4f}, {cy:.4f}, '
                     f'{zt - fondo / 2:.4f}, {a:.6f}), "{CAPA_ESCALERA}", mConcretoAparente); n++;')
            p.append(f'poner(caja({t + 0.02:.4f}, {w:.4f}, 0.025, {cx + ux * 0.01:.4f}, '
                     f'{cy + uy * 0.01:.4f}, {zt + 0.0125:.4f}, {a:.6f}), "{CAPA_ESCALERA}", '
                     'mMadera); n++;')
        lado = f.get("railing")
        if lado in ("left", "right"):
            sg = 1 if lado == "left" else -1
            px_, py_ = -uy * sg * (w / 2 - 0.04), ux * sg * (w / 2 - 0.04)
            # De la nariz del primer escalón a la del último: el pasamanos
            # corre paralelo a la línea de narices, a BARANDAL_ALTO de ella.
            # Llega hasta el borde de lo que sigue (descanso o losa), donde
            # la línea de narices alcanza el nivel de llegada: ahí empalma
            # el tramo de unión del descanso.
            d0 = 0.03
            d1 = (n_ - 1) * t + 0.02
            za, zb = z0 + r, z0 + r + r / t * (d1 - d0)

            def escalon(d, z0=z0, r=r, t=t, n_=n_, d0=d0):
                return z0 + (min(int((d + d0) // t), n_ - 1) + 1) * r
            a3 = (sx + ux * d0 + px_, sy + uy * d0 + py_, za)
            b3 = (sx + ux * d1 + px_, sy + uy * d1 + py_, zb)
            p += _barandal(a3[0], a3[1], b3[0], b3[1], za, zb, escalon, nudos=nudos)
            rieles.append((a3, b3, z0 + n_ * r))
    # Unión en el descanso: el pasamanos no se corta entre una rampa y la
    # siguiente. Va del final de una al arranque de la otra, con postes y
    # barrotes que nacen en el descanso.
    for (_a, fin, llegada), (ini, _b, _l) in zip(rieles, rieles[1:]):
        if math.hypot(ini[0] - fin[0], ini[1] - fin[1]) > 1.5:
            continue
        p += _barandal(fin[0], fin[1], ini[0], ini[1], fin[2], ini[2],
                       lambda d, z=llegada: z, nudos=nudos)
    for d in st.get("landings", []):
        x0, y0, x1, y1 = (float(v) for v in d["box"])
        z = float(d["z"])
        e = float(d.get("thickness", 0.12))
        p.append(f'poner(caja({x1 - x0:.4f}, {y1 - y0:.4f}, {e:.4f}, {(x0 + x1) / 2 + dx:.4f}, '
                 f'{(y0 + y1) / 2:.4f}, {z - e / 2:.4f}, 0), "{CAPA_ESCALERA}", mConcretoAparente); n++;')
        p.append(f'poner(caja({x1 - x0:.4f}, {y1 - y0:.4f}, 0.025, {(x0 + x1) / 2 + dx:.4f}, '
                 f'{(y0 + y1) / 2:.4f}, {z + 0.0125:.4f}, 0), "{CAPA_ESCALERA}", mMadera); n++;')
    for g in st.get("guards", []):
        ax, ay = float(g["from"][0]) + dx, float(g["from"][1])
        bx, by = float(g["to"][0]) + dx, float(g["to"][1])
        z = float(g.get("z", 0.0))
        za_, zb_ = z, z
        # El extremo que cae a menos de 30 cm del final de un pasamanos se
        # pega a él: arrancar unos centímetros al lado dejaba el tubo cortado
        # justo donde la escalera llega a la planta alta.
        extremos = [pt for a3, b3, _l in rieles for pt in (a3, b3)]

        def pegar(x, y, zz):
            for px, py, pz in extremos:
                if math.hypot(px - x, py - y) < 0.30 and abs(pz - zz) < 0.30:
                    return px, py, pz
            return x, y, zz
        ax, ay, za_ = pegar(ax, ay, z)
        bx, by, zb_ = pegar(bx, by, z)
        # Protección en planta alta o descanso: barandal con zoclo; 'height'
        # por defecto 0.90 (en un vacío alto, pedir 1.00+).
        p += _barandal(ax, ay, bx, by, za_, zb_, lambda d, z=z: z, float(g.get("height", BARANDAL_ALTO)),
                       zoclo=True, nudos=nudos)
    for h in st.get("openings", []):
        x0, y0, x1, y1 = (float(v) for v in h["box"])
        p.append(f'perforar(new string[] {{ "{model3d.LAYER_LOSA_3D}", "{CAPA_PISO}" }}, '
                 f'{x0 + dx:.4f}, {y0:.4f}, {x1 + dx:.4f}, {y1:.4f}, {float(h["z0"]):.4f}, '
                 f'{float(h["z1"]):.4f});')
    return "\n".join(p)


PISOS_POR_USO = (("RECÁMARA", "mDuela"), ("RECAMARA", "mDuela"), ("ESTANCIA", "mDuela"),
                 ("VESTIDOR", "mDuela"), ("CLÓSET", "mDuela"), ("CLOSET", "mDuela"),
                 ("BAÑO", "mLoseta"), ("BANO", "mLoseta"), ("COCINA", "mLoseta"),
                 ("LAVADO", "mLoseta"), ("COCHERA", "mConcretoPulido"),
                 ("BODEGA", "mConcretoPulido"))


def _piso_de(nombre: str, propios: Optional[dict[str, str]] = None) -> str:
    """Material de piso por el nombre del recinto; 'floors' del nivel manda
    ({"SALA": "duela"}). Lo que no está en la lista: porcelanato claro."""
    u = nombre.upper()
    nombres = {"duela": "mDuela", "porcelanato": "mPorcelanato", "loseta": "mLoseta",
               "concreto": "mConcretoPulido", "madera": "mDuela"}
    for k, v in (propios or {}).items():
        if k.upper() in u:
            return nombres.get(v, "mPorcelanato")
    for clave, mat in PISOS_POR_USO:
        if clave in u:
            return mat
    return "mPorcelanato"


def _azulejo_bano(r: dict[str, Any], adentro: list, cajas: list, ext: float, inter: float,
                  dx: float, z0: float, alto: float = 2.10) -> str:
    """Azulejo en los muros del baño hasta 2.10 m: un forro de 8 mm sobre la
    cara interior de cada muro, con puertas y ventanas restadas. Cada lado
    se separa del eje lo que mide medio muro (exterior o divisorio)."""
    def afuera(x, y):
        return not any(model3d.point_in_polygon(x, y, e) for e, _h in adentro)
    cx, cy = (r["x0"] + r["x1"]) / 2, (r["y0"] + r["y1"]) / 2
    medio = {
        "x0": ext / 2 if afuera(r["x0"] - 0.2, cy) else inter / 2,
        "x1": ext / 2 if afuera(r["x1"] + 0.2, cy) else inter / 2,
        "y0": ext / 2 if afuera(cx, r["y0"] - 0.2) else inter / 2,
        "y1": ext / 2 if afuera(cx, r["y1"] + 0.2) else inter / 2,
    }
    x0, x1 = r["x0"] + medio["x0"], r["x1"] - medio["x1"]
    y0, y1 = r["y0"] + medio["y0"], r["y1"] - medio["y1"]
    e = 0.008
    caras = _arr([(x0 + dx, y0), (x1 + dx, y0), (x1 + dx, y1), (x0 + dx, y1)])
    dentro = _arr([(x0 + e + dx, y0 + e), (x1 - e + dx, y0 + e), (x1 - e + dx, y1 - e),
                   (x0 + e + dx, y1 - e)])
    p = [f"{{ var az = extruir({caras}, new double[][] {{ {dentro} }}, {z0 + 0.012:.4f}, {alto:.3f});"]
    for c in cajas:
        if (r["x0"] - 0.3 <= c["cx"] <= r["x1"] + 0.3) and (r["y0"] - 0.3 <= c["cy"] <= r["y1"] + 0.3):
            p.append(f"  {{ var v = caja({c['largo']:.4f}, {c['ancho'] + 0.06:.4f}, {c['alto']:.4f}, "
                     f"{c['cx'] + dx:.4f}, {c['cy']:.4f}, {c['cz']:.4f}, {c['angulo']:.6f}); "
                     "az.BooleanOperation(BooleanOperationType.BoolSubtract, v); v.Dispose(); }")
    p.append(f'  poner(az, "{CAPA_PISO}", mAzulejo); n++; }}')
    return "\n".join(p)


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
    fachada = "mLadrillo" if nivel.get("facade", "ladrillo") == "ladrillo" else "mFachada"
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
        partes.append(f'  poner(forro, "{CAPA_FORRO}", {fachada}); n++; }}')
    # Piso según el uso de cada recinto (duela en recámaras, porcelanato en
    # lo social, loseta en baño y cocina, concreto pulido en cochera): un
    # solo piso para toda la casa se veía de maqueta.
    for r in rooms:
        mat = _piso_de(r["name"], nivel.get("floors"))
        partes.append(f'poner(caja({r["x1"] - r["x0"]:.4f}, {r["y1"] - r["y0"]:.4f}, 0.012, '
                      f'{(r["x0"] + r["x1"]) / 2 + dx:.4f}, {(r["y0"] + r["y1"]) / 2:.4f}, '
                      f'{z0 + 0.006:.4f}, 0), "{CAPA_PISO}", {mat}); n++;')
        if "BAÑO" in r["name"].upper() or "BANO" in r["name"].upper():
            partes.append(_azulejo_bano(r, adentro, cajas, ext, inter, dx, z0))
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
        tw = c["ancho"] - 2 * model3d.HOLGURA_VANO          # espesor real del muro
        lado = _lado_exterior(c, adentro, tw)
        nx, ny = -math.sin(ang), math.cos(ang)
        ux, uy = math.cos(ang), math.sin(ang)
        if tipo == "door":
            zb = cz - A / 2
            # Chambrana (marco de madera) alrededor del vano, hoja y manijas.
            partes.append(
                f'{{ var ch = caja({L + 0.10:.4f}, {tw + 0.04:.4f}, {A + 0.05:.4f}, {cx:.4f}, {cy:.4f}, '
                f'{zb + (A + 0.05) / 2:.4f}, {ang:.6f}); var hu = caja({L:.4f}, {tw + 0.6:.4f}, {A:.4f}, '
                f'{cx:.4f}, {cy:.4f}, {cz:.4f}, {ang:.6f}); ch.BooleanOperation('
                f'BooleanOperationType.BoolSubtract, hu); hu.Dispose(); '
                f'poner(ch, "{CAPA_CARPINTERIA}", mMadera); n++; }}')
            partes.append(f'poner(caja({L - 0.02:.4f}, 0.045, {A - 0.01:.4f}, {cx:.4f}, '
                          f'{cy:.4f}, {cz - 0.005:.4f}, {ang:.6f}), "{CAPA_CARPINTERIA}", '
                          'mMadera); n++;')
            for sgn in (1, -1):
                hx = cx + ux * (L / 2 - 0.10) + nx * sgn * 0.045
                hy = cy + uy * (L / 2 - 0.10) + ny * sgn * 0.045
                partes.append(f'poner(caja(0.12, 0.03, 0.025, {hx:.4f}, {hy:.4f}, {zb + 1.0:.4f}, '
                              f'{ang:.6f}), "{CAPA_CARPINTERIA}", mAcero); n++;')
            continue
        if lado and tipo == "window":
            # Repisón de concreto que sobresale 6 cm de la fachada.
            sx = cx + nx * lado * (tw / 2 + 0.05)
            sy = cy + ny * lado * (tw / 2 + 0.05)
            partes.append(f'poner(caja({L + 0.10:.4f}, 0.16, 0.04, {sx:.4f}, {sy:.4f}, '
                          f'{cz - A / 2 - 0.02:.4f}, {ang:.6f}), "{CAPA_CARPINTERIA}", mRepison); n++;')
        # Ventana o corrediza: marco de aluminio + vidrio.
        partes.append(
            f'{{ var marco = caja({L:.4f}, 0.07, {A:.4f}, {cx:.4f}, {cy:.4f}, {cz:.4f}, {ang:.6f});'
            f' var luz = caja({L - 0.10:.4f}, 0.20, {A - 0.10:.4f}, {cx:.4f}, {cy:.4f}, {cz:.4f}, '
            f'{ang:.6f}); marco.BooleanOperation(BooleanOperationType.BoolSubtract, luz); '
            f'luz.Dispose(); poner(marco, "{CAPA_CARPINTERIA}", mAluminio); n++; }}')
        partes.append(f'poner(caja({L - 0.10:.4f}, 0.012, {A - 0.10:.4f}, {cx:.4f}, {cy:.4f}, '
                      f'{cz:.4f}, {ang:.6f}), "{CAPA_VIDRIO}", mVidrio); n++;')
        if (tipo in ("sliding", "corrediza") and L > 1.2) or L > 1.40:
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
                   sidewalk: bool = True,
                   stairs: Optional[list[dict[str, Any]]] = None,
                   parapet_height: float = 0.60,
                   tank: Optional[dict[str, Any]] = None,
                   terraces: Optional[list[dict[str, Any]]] = None,
                   lot: Optional[list[list[float]]] = None,
                   fence_height: float = 2.40,
                   paving: Optional[list[dict[str, Any]]] = None,
                   site_offset: float = 0.0,
                   cladding: Optional[list[dict[str, Any]]] = None,
                   canopies: Optional[list[dict[str, Any]]] = None,
                   hedges: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Acabados sobre un modelo ya levantado con create_3d_model (uno por
    nivel). Cada nivel: los mismos {rooms, doors, windows, base_z,
    wall_height, slab_thickness, offset} que se usaron para levantarlo, y
    opcionalmente 'furniture' (lo que devolvió suggest_furniture en 'items')
    para amueblarlo en 3D con alturas reales."""
    if not levels:
        raise ValueError("Pasá al menos un nivel (los mismos datos de create_3d_model).")
    tx = texturas()
    for capa, color in ((CAPA_FORRO, 21), (CAPA_VIDRIO, 151), (CAPA_CARPINTERIA, 8),
                        (CAPA_SITIO, 96), (CAPA_ARBOLES, 96), (CAPA_MUEBLES, 8), (CAPA_PISO, 8),
                        (CAPA_ESCALERA, 8), (CAPA_AZOTEA, 8)):
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
        'var mVidrio = material("MCP Vidrio claro", 150, 188, 205, "", 1, 1, 0.28);\n'
        # Cancelería negra mate: lo que se usa hoy; la gris se leía de 1990.
        'var mAluminio = material("MCP Aluminio negro", 36, 36, 38, "", 1, 1, 1.0);\n'
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
        'var mPorcelana = material("MCP Porcelana", 246, 246, 244, "", 1, 1, 1.0);\n'
        'var mFachada = material("MCP Aplanado exterior", 238, 234, 224, "", 1, 1, 1.0);\n'
        'var mRepison = material("MCP Repison de concreto", 200, 198, 192, "", 1, 1, 1.0);\n'
        'var mConcretoAparente = material("MCP Concreto aparente", 182, 180, 174, "", 1, 1, 1.0);\n'
        'var mTinaco = material("MCP Tinaco", 34, 34, 36, "", 1, 1, 1.0);\n'
        'var mAsfalto = material("MCP Asfalto", 58, 60, 62, "", 1, 1, 1.0);\n'
        f'var mDuela = material("MCP Duela de madera", 168, 122, 80, "{ruta("duela")}", '
        f'{tx["duela"][1]}, {tx["duela"][2]}, 1.0);\n'
        f'var mPorcelanato = material("MCP Porcelanato claro", 228, 225, 218, "{ruta("porcelanato")}", '
        f'{tx["porcelanato"][1]}, {tx["porcelanato"][2]}, 1.0);\n'
        f'var mLoseta = material("MCP Loseta", 196, 190, 180, "{ruta("loseta")}", '
        f'{tx["loseta"][1]}, {tx["loseta"][2]}, 1.0);\n'
        f'var mAzulejo = material("MCP Azulejo blanco", 242, 243, 244, "{ruta("azulejo")}", '
        f'{tx["azulejo"][1]}, {tx["azulejo"][2]}, 1.0);\n'
        f'var mConcretoPulido = material("MCP Concreto pulido", 160, 158, 154, '
        f'"{ruta("concreto_pulido")}", {tx["concreto_pulido"][1]}, {tx["concreto_pulido"][2]}, 1.0);\n'
        'var mEspejo = material("MCP Espejo", 196, 208, 214, "", 1, 1, 1.0);\n'
        'var mNegro = material("MCP Negro mate", 22, 22, 24, "", 1, 1, 1.0);\n'
        'var mSeto = material("MCP Seto", 52, 98, 44, "", 1, 1, 1.0);\n'
        'var mFollaje2 = material("MCP Follaje claro", 78, 126, 56, "", 1, 1, 1.0);\n')
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
    # create_3d_model deja la losa de arriba de CADA nivel en la capa de
    # cubierta; solo la del nivel más alto es azotea. Las de abajo son
    # entrepiso: a su capa, para que el techo se apague sin llevárselas y la
    # escalera las pueda perforar.
    z_tope = max(float(n_.get("base_z", 0.0)) + float(n_.get("wall_height", 2.5))
                 + float(n_.get("slab_thickness", 0.12)) for n_ in levels)
    cuerpo.append(f"""
foreach (ObjectId id in space)
{{{{
    var e = tr.GetObject(id, OpenMode.ForRead) as Solid3d;
    if (e == null || e.Layer != "{capa_cubierta}") continue;
    if (e.GeometricExtents.MaxPoint.Z < {z_tope - 0.01:.4f}) {{{{ e.UpgradeOpen(); e.Layer = "{slab_layer}"; }}}}
}}}}""".replace("{{{{", "{").replace("}}}}", "}"))
    xs, ys = [], []
    for nivel in levels:
        cuerpo.append(_codigo_nivel(nivel, exterior_thickness, interior_thickness,
                                    window_width, {}))
        dx = float(nivel.get("offset", 0.0))
        for r in nivel["rooms"]:
            xs += [r["x0"] + dx, r["x1"] + dx]
            ys += [r["y0"], r["y1"]]
    so = float(site_offset)
    for st in stairs or []:
        cuerpo.append(_codigo_escalera(st, so))
    # Pretil con remate sobre la azotea (el nivel más alto).
    arriba = max(levels, key=lambda n_: float(n_.get("base_z", 0.0)))
    if parapet_height > 0:
        tol = min(exterior_thickness, interior_thickness) / 2.0 * 1e-5
        z_azotea = (float(arriba.get("base_z", 0.0)) + float(arriba.get("wall_height", 2.5))
                    + float(arriba.get("slab_thickness", 0.12)))
        dxa = float(arriba.get("offset", 0.0))
        mat_p = "mLadrillo" if arriba.get("facade", "ladrillo") == "ladrillo" else "mFachada"
        for e_out, _h in model3d._agrupar(model3d._losa(arriba["rooms"], exterior_thickness + 0.024,
                                                        tol)):
            c = _arr([(p[0] + dxa, p[1]) for p in e_out])
            cuerpo.append(f'poner(anillo({c}, 0, 0.15, {z_azotea:.4f}, {parapet_height:.4f}), '
                          f'"{CAPA_AZOTEA}", {mat_p}); n++;')
            cuerpo.append(f'poner(anillo({c}, 0.025, 0.175, {z_azotea + parapet_height:.4f}, 0.05), '
                          f'"{CAPA_AZOTEA}", mRepison); n++;')
        if tank:
            tx_, ty_ = float(tank["point"][0]) + dxa, float(tank["point"][1])
            dia, alto = float(tank.get("diameter", 1.10)), float(tank.get("height", 1.45))
            cuerpo.append(f'poner(caja({dia + 0.30:.3f}, {dia + 0.30:.3f}, 0.40, {tx_:.4f}, {ty_:.4f}, '
                          f'{z_azotea + 0.20:.4f}, 0), "{CAPA_AZOTEA}", mConcreto); n++;')
            cuerpo.append(f'{{ var tk = new Solid3d(); tk.SetDatabaseDefaults(); '
                          f'tk.CreateFrustum({alto:.3f}, {dia / 2:.3f}, {dia / 2:.3f}, {dia / 2 * 0.9:.3f}); '
                          f'tk.TransformBy(Matrix3d.Displacement(new Vector3d({tx_:.4f}, {ty_:.4f}, '
                          f'{z_azotea + 0.40 + alto / 2:.4f}))); poner(tk, "{CAPA_AZOTEA}", mTinaco); n++; }}')
    # Terrazas con deck de madera y pérgola.
    for te in terraces or []:
        x0_, y0_, x1_, y1_ = (float(v) for v in te["box"])
        x0_, x1_ = x0_ + so, x1_ + so
        z = float(te.get("z", 0.0))
        cuerpo.append(f'poner(caja({x1_ - x0_:.3f}, {y1_ - y0_:.3f}, 0.05, {(x0_ + x1_) / 2:.4f}, '
                      f'{(y0_ + y1_) / 2:.4f}, {z - 0.025:.4f}, 0), "{CAPA_SITIO}", mMadera); n++;')
        if te.get("pergola", True):
            h = float(te.get("height", 2.60))
            for px_ in (x0_ + 0.15, x1_ - 0.15):
                for py_ in (y0_ + 0.15, y1_ - 0.15):
                    cuerpo.append(f'poner(caja(0.12, 0.12, {h:.3f}, {px_:.4f}, {py_:.4f}, {z + h / 2:.4f}, 0),'
                                  f' "{CAPA_SITIO}", mMadera); n++;')
            for py_ in (y0_ + 0.15, y1_ - 0.15):
                cuerpo.append(f'poner(caja({x1_ - x0_:.3f}, 0.10, 0.20, {(x0_ + x1_) / 2:.4f}, {py_:.4f}, '
                              f'{z + h - 0.10:.4f}, 0), "{CAPA_SITIO}", mMadera); n++;')
            k = 0
            xv = x0_ + 0.25
            while xv < x1_ - 0.2:
                # Del paño de la casa (y0 + 12 cm) hasta 15 cm más allá del
                # borde: entrando al muro asomaban adentro de la sala.
                ya, yb = y0_ + 0.12, y1_ + 0.15
                cuerpo.append(f'poner(caja(0.05, {yb - ya:.3f}, 0.15, {xv:.4f}, '
                              f'{(ya + yb) / 2:.4f}, {z + h + 0.075:.4f}, 0), "{CAPA_SITIO}", '
                              'mMadera); n++;')
                xv += 0.50
    # Lambrín de duelas de madera sobre la fachada: un acento entre vanos.
    for cl in cladding or []:
        ax, ay = float(cl["from"][0]) + so, float(cl["from"][1])
        bx, by = float(cl["to"][0]) + so, float(cl["to"][1])
        za, zb = float(cl["z0"]), float(cl["z1"])
        L = math.hypot(bx - ax, by - ay)
        a = math.atan2(by - ay, bx - ax)
        nx, ny = -math.sin(a), math.cos(a)
        # Del eje a la cara del forro (medio muro + 12 mm) y media duela afuera.
        sal = exterior_thickness / 2 + 0.012 + 0.015 + float(cl.get("gap", 0.0))
        # side: de qué mano queda la calle caminando de from a to.
        sg = 1 if cl.get("side", "left") == "left" else -1
        paso, ancho = 0.10, 0.075
        t = paso / 2
        while t < L:
            px_, py_ = ax + (bx - ax) * t / L + nx * sg * sal, ay + (by - ay) * t / L + ny * sg * sal
            cuerpo.append(f'poner(caja({ancho:.3f}, 0.03, {zb - za:.3f}, {px_:.4f}, {py_:.4f}, '
                          f'{(za + zb) / 2:.4f}, {a:.6f}), "{CAPA_FORRO}", mMadera); n++;')
            t += paso
    # Marquesinas de concreto (sobre accesos).
    for mq in canopies or []:
        x0_, y0_, x1_, y1_ = (float(v) for v in mq["box"])
        z = float(mq.get("z", 2.40))
        e = float(mq.get("thickness", 0.12))
        cuerpo.append(f'poner(caja({x1_ - x0_:.3f}, {y1_ - y0_:.3f}, {e:.3f}, {(x0_ + x1_) / 2 + so:.4f}, '
                      f'{(y0_ + y1_) / 2:.4f}, {z + e / 2:.4f}, 0), "{CAPA_FORRO}", mRepison); n++;')
    # Setos: una hilera de matas que se enciman, con dos verdes.
    for se in hedges or []:
        ax, ay = float(se["from"][0]) + so, float(se["from"][1])
        bx, by = float(se["to"][0]) + so, float(se["to"][1])
        h = float(se.get("height", 1.0))
        L = math.hypot(bx - ax, by - ay)
        k = max(1, int(L / 0.55))
        for i in range(k + 1):
            f_ = i / k
            rr = h / 2 * (0.9 + 0.2 * ((i * 7) % 3) / 2)
            mat = "mSeto" if i % 2 else "mFollaje2"
            cuerpo.append(f'{{ var sb = new Solid3d(); sb.SetDatabaseDefaults(); sb.CreateSphere({rr:.3f});'
                          f' sb.TransformBy(Matrix3d.Displacement(new Vector3d({ax + (bx - ax) * f_:.4f}, '
                          f'{ay + (by - ay) * f_:.4f}, {rr * 0.85:.4f}))); poner(sb, "{CAPA_ARBOLES}", {mat}); n++; }}')
    # Pavimentos (cochera, andadores).
    for pv in paving or []:
        x0_, y0_, x1_, y1_ = (float(v) for v in pv["box"])
        mat = {"concreto": "mConcretoAparente", "madera": "mMadera"}.get(pv.get("material", "concreto"),
                                                                          "mConcretoAparente")
        cuerpo.append(f'poner(caja({x1_ - x0_:.3f}, {y1_ - y0_:.3f}, 0.10, {(x0_ + x1_) / 2 + so:.4f}, '
                      f'{(y0_ + y1_) / 2:.4f}, -0.06, 0), "{CAPA_SITIO}", {mat}); n++;')
    # Barda perimetral del lote (abierta al frente: el lado de y mínima).
    if lot:
        pts = [(float(p[0]) + so, float(p[1])) for p in lot]
        y_frente = min(p[1] for p in pts)
        for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
            if abs(ay - y_frente) < 1e-6 and abs(by - y_frente) < 1e-6:
                continue
            L = math.hypot(bx - ax, by - ay)
            a = math.atan2(by - ay, bx - ax)
            cuerpo.append(f'poner(caja({L:.3f}, 0.15, {fence_height:.3f}, {(ax + bx) / 2:.4f}, '
                          f'{(ay + by) / 2:.4f}, {fence_height / 2 - 0.10:.4f}, {a:.6f}), "{CAPA_SITIO}", '
                          'mFachada); n++;')
            cuerpo.append(f'poner(caja({L + 0.05:.3f}, 0.20, 0.05, {(ax + bx) / 2:.4f}, '
                          f'{(ay + by) / 2:.4f}, {fence_height - 0.075:.4f}, {a:.6f}), "{CAPA_SITIO}", '
                          'mRepison); n++;')
    if lot:
        xs += [float(p[0]) + float(site_offset) for p in lot]
        ys += [float(p[1]) for p in lot]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    base = min(float(n.get("base_z", 0.0)) for n in levels)
    m = site_margin
    if lot:
        # Pasto en el lote y alrededor; al frente banqueta de 1.50 y calle
        # de asfalto de 8 m: pasto en la vía pública no existe.
        lx0, lx1 = min(float(p[0]) for p in lot) + so, max(float(p[0]) for p in lot) + so
        ly0, ly1 = min(float(p[1]) for p in lot), max(float(p[1]) for p in lot)
        cuerpo.append(f'poner(caja({lx1 - lx0 + 2 * m:.3f}, {ly1 - ly0 + m:.3f}, 0.10, '
                      f'{(lx0 + lx1) / 2:.3f}, {(ly0 + ly1 + m) / 2:.3f}, {base - 0.15:.3f}, 0), '
                      f'"{CAPA_SITIO}", mPasto); n++;')
        cuerpo.append(f'poner(caja({lx1 - lx0 + 2 * m:.3f}, 1.50, 0.15, {(lx0 + lx1) / 2:.3f}, '
                      f'{ly0 - 0.75:.3f}, {base - 0.075:.3f}, 0), "{CAPA_SITIO}", mBanqueta); n++;')
        cuerpo.append(f'poner(caja({lx1 - lx0 + 2 * m:.3f}, 0.15, 0.20, {(lx0 + lx1) / 2:.3f}, '
                      f'{ly0 - 1.575:.3f}, {base - 0.10:.3f}, 0), "{CAPA_SITIO}", mRepison); n++;')
        cuerpo.append(f'poner(caja({lx1 - lx0 + 2 * m:.3f}, 8.0, 0.10, {(lx0 + lx1) / 2:.3f}, '
                      f'{ly0 - 1.65 - 4.0:.3f}, {base - 0.20:.3f}, 0), "{CAPA_SITIO}", mAsfalto); n++;')
        sidewalk = False
    else:
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
        # Copa de varias esferas en dos verdes, tronco ahusado: una sola
        # esfera se leía como paleta.
        h = 2.3 + 0.35 * (k % 3)
        r = 1.05 + 0.2 * (k % 2)
        # La copa no se mete en la casa: un árbol de banqueta a 75 cm de la
        # fachada la atravesaba y aparecía adentro, junto a la escalera. La
        # copa alcanza ~1.27 r de lado; se achica hasta librar el paño.
        libre = math.hypot(max(x0 - tx_, 0.0, tx_ - x1), max(y0 - ty_, 0.0, ty_ - y1))
        r = min(r, max(0.40, (libre - 0.10) / 1.27))
        cuerpo.append(
            f'{{ var t = new Solid3d(); t.SetDatabaseDefaults(); t.CreateFrustum({h:.2f}, 0.14, 0.14, 0.07);'
            f' t.TransformBy(Matrix3d.Displacement(new Vector3d({tx_:.3f}, {ty_:.3f}, {base + h / 2 - 0.1:.3f})));'
            f' poner(t, "{CAPA_ARBOLES}", mTronco); n++; }}')
        bolas = [(0, 0, h + r * 0.55, r), (r * 0.55, r * 0.2, h + r * 0.25, r * 0.72),
                 (-r * 0.5, r * 0.3, h + r * 0.3, r * 0.68), (0.1, -r * 0.5, h + r * 0.2, r * 0.7),
                 (0.05, 0.1, h + r * 1.15, r * 0.6)]
        for j_, (ox, oy, oz, rb) in enumerate(bolas):
            mat = "mFollaje" if j_ % 2 == 0 else "mFollaje2"
            cuerpo.append(
                f'{{ var c = new Solid3d(); c.SetDatabaseDefaults(); c.CreateSphere({rb:.2f});'
                f' c.TransformBy(Matrix3d.Displacement(new Vector3d({tx_ + ox:.3f}, {ty_ + oy:.3f}, {base + oz:.3f})));'
                f' poner(c, "{CAPA_ARBOLES}", {mat}); n++; }}')
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
            "materials": _materiales_usados(codigo),
            "textures": CARPETA_TEXTURAS, "roofVisible": roof_visible}


def _materiales_usados(codigo: str) -> list[str]:
    """Los materiales que de verdad se asignaron, por su nombre en AutoCAD:
    los declarados que aparecen como último argumento de algún poner()."""
    import re
    declarados = dict(re.findall(r'var (m\w+) = material\("MCP ([^"]+)"', codigo))
    usados = set(re.findall(r'", (m\w+)\)', codigo))
    return sorted(nombre for var, nombre in declarados.items() if var in usados)


_VISTA = r"""
// El ícono de ejes quedaba flotando en medio de la vista en perspectiva.
var vpr = (ViewportTableRecord)tr.GetObject(ed.ActiveViewportId, OpenMode.ForWrite);
if (vpr.IconEnabled != {icono}) {{ vpr.IconEnabled = {icono}; ed.UpdateTiledViewportsFromDatabase(); }}
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
        # El techo es la losa de azotea Y lo que va arriba (pretil, tinaco):
        # apagando solo la losa, el tinaco quedaba flotando.
        techo = (f'var tl = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);\n'
                 f'foreach (var nc in new string[] {{ "{capa}", "{CAPA_AZOTEA}" }}) '
                 f'if (tl.Has(nc)) ((LayerTableRecord)tr.GetObject(tl[nc], '
                 f'OpenMode.ForWrite)).IsOff = {str(not roof_visible).lower()};')
    if isolate_3d is not None:
        cond = '!c.Name.StartsWith("3D-")' if isolate_3d else "false"
        techo += ("\nforeach (ObjectId lid in (LayerTable)tr.GetObject(db.LayerTableId, "
                  "OpenMode.ForRead)) { var c = (LayerTableRecord)tr.GetObject(lid, OpenMode.ForRead);"
                  f" bool apagar = {cond}; if (c.IsOff != apagar && !((c.Name == \"{slab_layer}_CUBIERTA\""
                  f" || c.Name == \"{CAPA_AZOTEA}\") && "
                  f"{'true' if roof_visible is not None else 'false'})) {{ c.UpgradeOpen(); c.IsOff = apagar; }} }}")
    alto = dist * 0.75
    codigo = _VISTA.format(tx=tx, ty=ty, tz=tz, vx=vx, vy=vy, vz=vz, alto=alto, ancho=alto * 1.6,
                           persp="true" if perspective else "false", lente=lens, techo=techo,
                           icono="false" if isolate_3d else "true")
    r = engine.run_code(codigo, description="set_3d_view: cámara 3D")
    ok = bool(r.get("compiled")) and not r.get("exception") and not r.get("blocked")
    return {"ok": ok, "camera": [cx, cy, cz], "target": [tx, ty, tz], "lens": lens,
            "error": None if ok else (r.get("exception") or r.get("errors") or r.get("message"))}
