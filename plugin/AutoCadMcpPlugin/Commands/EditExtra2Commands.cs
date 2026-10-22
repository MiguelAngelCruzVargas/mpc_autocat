using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using SysException = System.Exception;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// STRETCH, LENGTHEN, ALIGN y WIPEOUT con la API administrada, cada una en UNA transacción y validada entera
    /// antes de tocar el dibujo (se sacaron de la lista de pendientes de la cinta de AutoCAD:
    /// COBERTURA_CINTA.md). Antes de escribirlas se corrió tools/precondiciones.py: Wipeout nace vacía y SetFrom
    /// la modifica, así que se le da forma ANTES de agregarla al dibujo (agregarla vacía no es seguro).
    /// </summary>
    public static class EditExtra2Commands
    {
        private static Point3d Punto(JsonNode n, string cual)
        {
            var a = n as JsonArray;
            if (a == null || a.Count < 2 || a.Count > 3) throw new ArgumentException("'" + cual + "' es [x, y] o [x, y, z].");
            double x = a[0].GetValue<double>(), y = a[1].GetValue<double>(), z = a.Count == 3 ? a[2].GetValue<double>() : 0.0;
            if (double.IsNaN(x) || double.IsNaN(y) || double.IsNaN(z) || double.IsInfinity(x) || double.IsInfinity(y) || double.IsInfinity(z))
                throw new ArgumentException("'" + cual + "' tiene coordenadas inválidas.");
            return new Point3d(x, y, z);
        }

        private static List<ObjectId> Ids(Document doc, JsonNode n, string cual, int max = 2000)
        {
            var a = n as JsonArray;
            if (a == null || a.Count == 0) throw new ArgumentException("'" + cual + "' necesita al menos un handle.");
            if (a.Count > max) throw new ArgumentException("'" + cual + "': máximo " + max + " handles.");
            var l = new List<ObjectId>();
            foreach (var x in a)
            {
                var id = HandleHelper.GetObjectId(doc.Database, x.GetValue<string>());
                if (!l.Contains(id)) l.Add(id);
            }
            return l;
        }

        private static bool Dentro(Point3d p, Point3d a, Point3d b)
        {
            return p.X >= Math.Min(a.X, b.X) - 1e-9 && p.X <= Math.Max(a.X, b.X) + 1e-9 &&
                   p.Y >= Math.Min(a.Y, b.Y) - 1e-9 && p.Y <= Math.Max(a.Y, b.Y) + 1e-9;
        }

        // ============================================================ STRETCH

        /// <summary>params: window [[x1,y1],[x2,y2]], delta [dx,dy,(dz)], [handles] (sin ellas, lo que cae en el espacio activo).
        /// Como STRETCH con ventana de captura: líneas y polilíneas mueven SOLO los vértices dentro de la ventana; círculos,
        /// textos, bloques, puntos y elipses se mueven enteros si su punto de inserción o centro está dentro. Arcos y el
        /// resto solo se mueven si quedan ENTEROS dentro; los que cruzan la ventana se informan en 'skipped'.</summary>
        public static JsonObject Stretch(Document doc, JsonObject pars)
        {
            var w = pars["window"] as JsonArray;
            if (w == null || w.Count != 2) throw new ArgumentException("'window' es [[x1, y1], [x2, y2]].");
            var a = Punto(w[0], "window[0]"); var b = Punto(w[1], "window[1]");
            if (Math.Abs(a.X - b.X) < 1e-12 || Math.Abs(a.Y - b.Y) < 1e-12) throw new ArgumentException("'window' tiene que tener área.");
            var d3 = Punto(pars["delta"], "delta");
            var delta = new Vector3d(d3.X, d3.Y, d3.Z);
            if (delta.Length < 1e-12) throw new ArgumentException("'delta' no puede ser nulo.");
            var db = doc.Database;
            int movidos = 0, vertices = 0;
            var saltados = new JsonArray();
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var espacio = (BlockTableRecord)tr.GetObject(db.CurrentSpaceId, OpenMode.ForRead);
                    IEnumerable<ObjectId> ids = pars["handles"] != null ? Ids(doc, pars["handles"], "handles") : espacio.Cast<ObjectId>().ToList();
                    foreach (var id in ids)
                    {
                        var e = tr.GetObject(id, OpenMode.ForRead) as Entity;
                        if (e == null) continue;
                        Extents3d ext;
                        try { ext = e.GeometricExtents; } catch (AcException) { continue; }
                        bool toca = !(ext.MaxPoint.X < Math.Min(a.X, b.X) || ext.MinPoint.X > Math.Max(a.X, b.X) ||
                                      ext.MaxPoint.Y < Math.Min(a.Y, b.Y) || ext.MinPoint.Y > Math.Max(a.Y, b.Y));
                        if (!toca) continue;
                        bool todoDentro = Dentro(ext.MinPoint, a, b) && Dentro(ext.MaxPoint, a, b);
                        if (e is Line ln)
                        {
                            bool s = Dentro(ln.StartPoint, a, b), f = Dentro(ln.EndPoint, a, b);
                            if (!s && !f) continue;
                            var w2 = (Line)tr.GetObject(id, OpenMode.ForWrite, false, true);
                            if (s) { w2.StartPoint = ln.StartPoint + delta; vertices++; }
                            if (f) { w2.EndPoint = ln.EndPoint + delta; vertices++; }
                            movidos++;
                        }
                        else if (e is Polyline pl)
                        {
                            var dentro = new List<int>();
                            for (int i = 0; i < pl.NumberOfVertices; i++)
                                if (Dentro(pl.GetPoint3dAt(i), a, b)) dentro.Add(i);
                            if (dentro.Count == 0) continue;
                            var w2 = (Polyline)tr.GetObject(id, OpenMode.ForWrite, false, true);
                            foreach (int i in dentro)
                            {
                                var p2 = w2.GetPoint2dAt(i);
                                w2.SetPointAt(i, new Point2d(p2.X + delta.X, p2.Y + delta.Y));
                                vertices++;
                            }
                            movidos++;
                        }
                        else
                        {
                            Point3d? ancla = null;
                            if (e is Circle c) ancla = c.Center;
                            else if (e is Ellipse el) ancla = el.Center;
                            else if (e is DBText t) ancla = t.Position;
                            else if (e is MText mt) ancla = mt.Location;
                            else if (e is BlockReference br) ancla = br.Position;
                            else if (e is DBPoint pt) ancla = pt.Position;
                            bool mover = ancla.HasValue ? Dentro(ancla.Value, a, b) : todoDentro;
                            if (!mover)
                            {
                                saltados.Add(new JsonObject { ["handle"] = id.Handle.ToString(), ["type"] = e.GetType().Name });
                                continue;
                            }
                            var w2 = (Entity)tr.GetObject(id, OpenMode.ForWrite, false, true);
                            w2.TransformBy(Matrix3d.Displacement(delta));
                            movidos++;
                        }
                    }
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó el estiramiento (" + ex.ErrorStatus + "): " + ex.Message + ". No se cambió nada.");
                }
                catch (SysException) { tr.Abort(); throw; }
            }
            return new JsonObject { ["entitiesChanged"] = movidos, ["verticesMoved"] = vertices, ["skipped"] = saltados };
        }

        // ============================================================ LENGTHEN

        /// <summary>params: handle (línea, arco o polilínea ABIERTA con el tramo extremo recto), end ("start"|"end"), y UNO de:
        /// delta (largo a sumar; negativo acorta), total (largo final), percent (porcentaje del largo actual).</summary>
        public static JsonObject Lengthen(Document doc, JsonObject pars)
        {
            string h = pars["handle"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(h)) throw new ArgumentException("Falta 'handle'.");
            string extremo = (pars["end"]?.GetValue<string>() ?? "end").ToLowerInvariant();
            if (extremo != "start" && extremo != "end") throw new ArgumentException("'end' es start o end.");
            int n = (pars["delta"] != null ? 1 : 0) + (pars["total"] != null ? 1 : 0) + (pars["percent"] != null ? 1 : 0);
            if (n != 1) throw new ArgumentException("Pasá uno solo de 'delta', 'total' o 'percent'.");
            var db = doc.Database;
            var id = HandleHelper.GetObjectId(db, h);
            double antes, despues;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var e = tr.GetObject(id, OpenMode.ForRead) as Curve;
                    if (e == null) throw new ArgumentException("Solo se alarga una línea, un arco o una polilínea abierta.");
                    antes = e.GetDistanceAtParameter(e.EndParam) - e.GetDistanceAtParameter(e.StartParam);
                    double nuevo = pars["delta"] != null ? antes + pars["delta"].GetValue<double>()
                                 : pars["total"] != null ? pars["total"].GetValue<double>()
                                 : antes * pars["percent"].GetValue<double>() / 100.0;
                    if (double.IsNaN(nuevo) || double.IsInfinity(nuevo) || nuevo <= 1e-9)
                        throw new ArgumentException("El largo resultante (" + nuevo + ") no es válido: tiene que ser mayor que cero.");
                    double d = nuevo - antes;
                    if (e is Line ln)
                    {
                        var w = (Line)tr.GetObject(id, OpenMode.ForWrite, false, true);
                        var dir = (ln.EndPoint - ln.StartPoint).GetNormal();
                        if (extremo == "end") w.EndPoint = ln.EndPoint + dir * d; else w.StartPoint = ln.StartPoint - dir * d;
                    }
                    else if (e is Arc ar)
                    {
                        double da = d / ar.Radius;
                        var w = (Arc)tr.GetObject(id, OpenMode.ForWrite, false, true);
                        if (extremo == "end") w.EndAngle = ar.EndAngle + da; else w.StartAngle = ar.StartAngle - da;
                    }
                    else if (e is Polyline pl && !pl.Closed)
                    {
                        int i = extremo == "end" ? pl.NumberOfVertices - 1 : 0;
                        int vecino = extremo == "end" ? i - 1 : i + 1;
                        int seg = extremo == "end" ? vecino : i;
                        if (pl.NumberOfVertices < 2 || pl.GetBulgeAt(seg) != 0)
                            throw new ArgumentException("El tramo del extremo es un arco: solo se alarga un tramo recto.");
                        var p = pl.GetPoint2dAt(i); var q = pl.GetPoint2dAt(vecino);
                        var dir = (p - q).GetNormal();
                        var w = (Polyline)tr.GetObject(id, OpenMode.ForWrite, false, true);
                        w.SetPointAt(i, p + dir * d);
                    }
                    else throw new ArgumentException("Solo se alarga una línea, un arco o una polilínea abierta (no " + e.GetType().Name + ").");
                    var r = (Curve)tr.GetObject(id, OpenMode.ForRead);
                    despues = r.GetDistanceAtParameter(r.EndParam) - r.GetDistanceAtParameter(r.StartParam);
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó alargar (" + ex.ErrorStatus + "): " + ex.Message + ". No se cambió nada.");
                }
                catch (SysException) { tr.Abort(); throw; }
            }
            return new JsonObject { ["handle"] = h, ["lengthBefore"] = antes, ["lengthAfter"] = despues };
        }

        // ============================================================ ALIGN

        /// <summary>params: handles[], from1, to1 (primer par de puntos), [from2, to2] (segundo par: rota y, con scale=true, escala),
        /// [scale=false]. Con un par solo traslada; con dos, rota (y escala si se pide) para que el segmento from1-from2
        /// caiga sobre to1-to2. Vale en 2D y en 3D (traslación y rotación sobre el plano XY).</summary>
        public static JsonObject Align(Document doc, JsonObject pars)
        {
            var ids = Ids(doc, pars["handles"], "handles");
            var f1 = Punto(pars["from1"], "from1"); var t1 = Punto(pars["to1"], "to1");
            bool dos = pars["from2"] != null || pars["to2"] != null;
            if (dos && (pars["from2"] == null || pars["to2"] == null)) throw new ArgumentException("El segundo par necesita from2 Y to2.");
            bool escalar = pars["scale"]?.GetValue<bool>() ?? false;
            if (escalar && !dos) throw new ArgumentException("scale=true necesita el segundo par de puntos.");
            Matrix3d m = Matrix3d.Displacement(t1 - f1);
            double ang = 0, factor = 1;
            if (dos)
            {
                var f2 = Punto(pars["from2"], "from2"); var t2 = Punto(pars["to2"], "to2");
                var vf = new Vector3d(f2.X - f1.X, f2.Y - f1.Y, 0); var vt = new Vector3d(t2.X - t1.X, t2.Y - t1.Y, 0);
                if (vf.Length < 1e-12 || vt.Length < 1e-12) throw new ArgumentException("Los dos puntos de un par no pueden coincidir.");
                ang = Math.Atan2(vt.Y, vt.X) - Math.Atan2(vf.Y, vf.X);
                factor = vt.Length / vf.Length;
                m = Matrix3d.Rotation(ang, Vector3d.ZAxis, t1) * m;
                if (escalar) m = Matrix3d.Scaling(factor, t1) * m;
            }
            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    foreach (var id in ids)
                    {
                        var e = tr.GetObject(id, OpenMode.ForWrite, false, true) as Entity;
                        if (e == null) throw new ArgumentException("'" + id.Handle + "' no es una entidad de dibujo.");
                        e.TransformBy(m);
                    }
                    tr.Commit();
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD rechazó la alineación (" + ex.ErrorStatus + "): " + ex.Message + ". No se cambió nada.");
                }
                catch (SysException) { tr.Abort(); throw; }
            }
            return new JsonObject { ["aligned"] = ids.Count, ["rotationDeg"] = ang * 180.0 / Math.PI, ["scaleFactor"] = escalar ? factor : 1.0 };
        }

        // ============================================================ WIPEOUT

        /// <summary>params: points [[x,y],...] (3 o más: el contorno que tapa), [layer], [frame=false] (dibujar el marco).
        /// Máscara que oculta lo que queda debajo (rótulos sobre un achurado, texto sobre líneas). Se le da forma con
        /// SetFrom ANTES de agregarla: una Wipeout vacía no es segura de agregar.</summary>
        public static JsonObject Wipeout(Document doc, JsonObject pars)
        {
            var pa = pars["points"] as JsonArray;
            if (pa == null || pa.Count < 3) throw new ArgumentException("'points' necesita al menos 3 puntos [x, y].");
            if (pa.Count > 500) throw new ArgumentException("Máximo 500 puntos.");
            var pts = new Point2dCollection();
            foreach (var p in pa)
            {
                var pp = Punto(p, "points");
                pts.Add(new Point2d(pp.X, pp.Y));
            }
            if (pts[0].GetDistanceTo(pts[pts.Count - 1]) > 1e-9) pts.Add(pts[0]);       // SetFrom pide el contorno cerrado
            string capa = pars["layer"]?.GetValue<string>();
            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                Wipeout w = null;
                try
                {
                    if (!string.IsNullOrEmpty(capa))
                    {
                        var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
                        if (!lt.Has(capa)) throw new ArgumentException("No hay una capa llamada '" + capa + "'.");
                    }
                    w = new Wipeout();
                    w.SetDatabaseDefaults(db);
                    w.SetFrom(pts, Vector3d.ZAxis);
                    if (!string.IsNullOrEmpty(capa)) w.Layer = capa;
                    var espacio = (BlockTableRecord)tr.GetObject(db.CurrentSpaceId, OpenMode.ForWrite);
                    espacio.AppendEntity(w);
                    tr.AddNewlyCreatedDBObject(w, true);
                    var h = w.Handle.ToString();
                    tr.Commit();
                    return new JsonObject { ["handle"] = h, ["vertices"] = pts.Count - 1 };
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    if (w != null && w.ObjectId.IsNull) w.Dispose();
                    throw new InvalidOperationException("AutoCAD rechazó la máscara (" + ex.ErrorStatus + "): " + ex.Message + ". No se creó nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    if (w != null && w.ObjectId.IsNull) w.Dispose();
                    throw;
                }
            }
        }
    }
}
