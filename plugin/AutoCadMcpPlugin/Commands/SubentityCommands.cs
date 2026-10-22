using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using SysException = System.Exception;
using BR = Autodesk.AutoCAD.BoundaryRepresentation;
using DbSurface = Autodesk.AutoCAD.DatabaseServices.Surface;
using GeoPlane = Autodesk.AutoCAD.Geometry.Plane;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Edición por CARAS y ARISTAS de sólidos, mallas y superficies: SOLIDEDIT (extruir/desfasar/inclinar/quitar caras, vaciar),
    /// CHAMFEREDGE, MESHEXTRUDE / MESHMERGE / MESHSPLIT / MESHCREASE / MESHCOLLAPSE / MESHCAP / MESHSPIN, SURFTRIM, SURFEXTEND y SURFFILLET.
    ///
    /// Una cara o arista se identifica por un SubentityId que cambia en cuanto el objeto se edita y que nadie sabe de memoria. Por eso
    /// las tools no piden índices a ciegas: <c>list_subentities</c> da cada cara y arista con su normal, centro, área y largo, y todas
    /// las tools que editan aceptan un SELECTOR por geometría (normal, altura Z, tipo, área, largo, "pertenece a la cara...") además
    /// del índice. Un selector con una clave que no existe se rechaza (un error de tipeo no puede seleccionar todo).
    ///
    /// Precondiciones leídas con tools/precondiciones.py: los métodos que modifican (ExtrudeFaces, ChamferEdges, ExtendEdges, los de
    /// SubDMesh) exigen el objeto abierto para ESCRITURA; las estáticas de Surface (TrimSurface, CreateFilletSurface) abren por sí mismas
    /// los objetos que reciben, así que no se los deja abiertos en escritura. En una malla los índices de cara son estables al extruir
    /// (la cara extruida conserva su índice y las laterales se agregan al final) —se comprobó en vivo—, pero igual se relee la ruta por
    /// índice antes de cada operación. Todo en una transacción: si AutoCAD rechaza la operación no queda nada a medias.
    /// </summary>
    public static class SubentityCommands
    {
        // ============================================================ modelo de lectura

        private sealed class Cara
        {
            public long Index;
            public SubentityId Sid;
            public string Kind = "otra";
            public bool Plana;
            public Vector3d Normal;
            public Point3d PuntoPlano;
            public double Area;
            public Point3d Centro;
            public Point3d Min, Max;
            public List<Point3d> Pts = new List<Point3d>();
            public List<int> Vertices = new List<int>(); // solo mallas
        }

        private sealed class Arista
        {
            public long Index;
            public SubentityId Sid;
            public Point3d P1, P2;
            public double Largo;
            public string Kind = "otra";
            public HashSet<long> Caras = new HashSet<long>();
        }

        private static ObjectId Id(Document doc, JsonNode n, string cual)
        {
            string h = n?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(h)) throw new ArgumentException("Falta '" + cual + "' (un handle).");
            return HandleHelper.GetObjectId(doc.Database, h);
        }

        private static double Num(JsonObject pars, string clave, double porDefecto)
        {
            if (pars[clave] == null) return porDefecto;
            double v = pars[clave].GetValue<double>();
            if (double.IsNaN(v) || double.IsInfinity(v)) throw new ArgumentException("'" + clave + "' tiene que ser un número finito.");
            return v;
        }

        private static double NumPos(JsonObject pars, string clave, string que)
        {
            if (pars[clave] == null) throw new ArgumentException("Falta '" + clave + "' (" + que + ").");
            double v = Num(pars, clave, 0);
            if (v <= 0) throw new ArgumentException("'" + clave + "' tiene que ser mayor que cero.");
            return v;
        }

        private static Point3d Punto(JsonNode n, string cual)
        {
            var a = n as JsonArray;
            if (a == null || a.Count < 2 || a.Count > 3) throw new ArgumentException("'" + cual + "' es [x, y] o [x, y, z].");
            double x = a[0].GetValue<double>(), y = a[1].GetValue<double>(), z = a.Count == 3 ? a[2].GetValue<double>() : 0.0;
            if (double.IsNaN(x) || double.IsNaN(y) || double.IsNaN(z) || double.IsInfinity(x) || double.IsInfinity(y) || double.IsInfinity(z))
                throw new ArgumentException("'" + cual + "' tiene coordenadas inválidas.");
            return new Point3d(x, y, z);
        }

        private static Vector3d Vector(JsonNode n, string cual)
        {
            var a = n as JsonArray;
            if (a == null || a.Count != 3) throw new ArgumentException("'" + cual + "' es un vector [x, y, z].");
            var v = new Vector3d(a[0].GetValue<double>(), a[1].GetValue<double>(), a[2].GetValue<double>());
            if (double.IsNaN(v.X) || double.IsNaN(v.Y) || double.IsNaN(v.Z) || double.IsInfinity(v.Length))
                throw new ArgumentException("'" + cual + "' tiene coordenadas inválidas.");
            if (v.Length < 1e-12) throw new ArgumentException("'" + cual + "' no puede ser el vector cero.");
            return v;
        }

        private static JsonArray Arr(Point3d p)
        {
            return new JsonArray(Math.Round(p.X, 6), Math.Round(p.Y, 6), Math.Round(p.Z, 6));
        }

        private static JsonArray Arr(Vector3d p)
        {
            return new JsonArray(Math.Round(p.X, 6), Math.Round(p.Y, 6), Math.Round(p.Z, 6));
        }

        private static double ARadianes(double grados)
        {
            return grados * Math.PI / 180.0;
        }

        private static JsonObject Extension(Entity e)
        {
            try
            {
                var x = e.GeometricExtents;
                return new JsonObject { ["min"] = Arr(x.MinPoint), ["max"] = Arr(x.MaxPoint) };
            }
            catch (SysException) { return null; }
        }

        // ============================================================ lectura de una B-Rep (sólido, superficie, región)

        private static string TipoCara(ExternalBoundedSurface eb)
        {
            if (eb.IsPlane) return "plane";
            if (eb.IsCylinder) return "cylinder";
            if (eb.IsCone) return "cone";
            if (eb.IsSphere) return "sphere";
            if (eb.IsTorus) return "torus";
            if (eb.IsNurbs) return "nurbs";
            return "otra";
        }

        private static string TipoCurva(Curve3d c)
        {
            var ext = c as ExternalCurve3d;
            if (ext != null)
            {
                if (ext.IsLineSegment || ext.IsLine) return "line";
                if (ext.IsCircularArc)
                {
                    try { return c.StartPoint.DistanceTo(c.EndPoint) < 1e-9 ? "circle" : "arc"; } catch (SysException) { return "arc"; }
                }
                if (ext.IsEllipticalArc) return "ellipse";
                if (ext.IsNurbCurve) return "spline";
                return "otra";
            }
            if (c is LineSegment3d || c is Line3d) return "line";
            var ca = c as CircularArc3d;
            if (ca != null)
            {
                try { return ca.IsClosed() ? "circle" : "arc"; } catch (SysException) { return "arc"; }
            }
            if (c is EllipticalArc3d) return "ellipse";
            if (c is NurbCurve3d) return "spline";
            return c.GetType().Name;
        }

        /// <summary>Sólidos y regiones: B-Rep. Las SUPERFICIES no se dejan abrir como B-Rep desde su ruta (BoundaryRepresentation.Exception, se vio en
        /// vivo con ExtrudedSurface y con el empalme), así que ahí se recorren las subentidades con <c>Entity.GetSubentity</c>, que sí responde
        /// (aristas y caras numeradas desde 1, seguidas). Sin área, tipo ni adyacencia: en una superficie las aristas no informan sus caras.</summary>
        private static void LeerBrep(Entity ent, List<Cara> caras, List<Arista> aristas)
        {
            if (ent is DbSurface)
            {
                LeerPorSubentidades(ent, caras, aristas);
                return;
            }
            LeerBrepReal(ent, caras, aristas);
        }

        private static void LeerPorSubentidades(Entity ent, List<Cara> caras, List<Arista> aristas)
        {
            int fallos = 0;
            for (int i = 1; i < 5000 && fallos < 4; i++)
            {
                var fp = new FullSubentityPath(new ObjectId[] { ent.ObjectId }, new SubentityId(SubentityType.Edge, (IntPtr)i));
                Entity sub = null;
                try { sub = ent.GetSubentity(fp); } catch (SysException) { }
                if (sub == null) { fallos++; continue; }
                fallos = 0;
                using (sub)
                {
                    var cv = sub as Curve;
                    if (cv == null) continue;
                    var a = new Arista { Sid = fp.SubentId, Index = i };
                    a.P1 = cv.StartPoint; a.P2 = cv.EndPoint;
                    a.Largo = a.P1.DistanceTo(a.P2);
                    try { double l = cv.GetDistanceAtParameter(cv.EndParam); if (l > 0 && !double.IsNaN(l)) a.Largo = l; } catch (SysException) { }
                    if (cv is Line) a.Kind = "line";
                    else if (cv is Circle) a.Kind = "circle";
                    else if (cv is Arc) a.Kind = "arc";
                    else if (cv is Ellipse) a.Kind = "ellipse";
                    else if (cv is Spline) a.Kind = "spline";
                    else a.Kind = cv.GetType().Name.ToLowerInvariant();
                    aristas.Add(a);
                }
            }
            fallos = 0;
            for (int i = 1; i < 500 && fallos < 4; i++)
            {
                var fp = new FullSubentityPath(new ObjectId[] { ent.ObjectId }, new SubentityId(SubentityType.Face, (IntPtr)i));
                Entity sub = null;
                try { sub = ent.GetSubentity(fp); } catch (SysException) { }
                if (sub == null) { fallos++; continue; }
                fallos = 0;
                using (sub)
                {
                    var c = new Cara { Sid = fp.SubentId, Index = i };
                    try
                    {
                        var x = sub.GeometricExtents;
                        c.Min = x.MinPoint; c.Max = x.MaxPoint;
                        c.Centro = new Point3d((x.MinPoint.X + x.MaxPoint.X) / 2, (x.MinPoint.Y + x.MaxPoint.Y) / 2, (x.MinPoint.Z + x.MaxPoint.Z) / 2);
                    }
                    catch (SysException) { }
                    caras.Add(c);
                }
            }
        }

        private static void LeerBrepReal(Entity ent, List<Cara> caras, List<Arista> aristas)
        {
            var ruta = new FullSubentityPath(new ObjectId[] { ent.ObjectId }, new SubentityId(SubentityType.Null, IntPtr.Zero));
            using (var brep = new BR.Brep(ruta))
            {
                foreach (BR.Face f in brep.Faces)
                {
                    var c = new Cara();
                    c.Sid = f.SubentityPath.SubentId;
                    c.Index = c.Sid.IndexPtr.ToInt64();
                    var eb = f.Surface as ExternalBoundedSurface;
                    if (eb != null)
                    {
                        c.Kind = TipoCara(eb);
                        if (eb.IsPlane)
                        {
                            var pl = eb.BaseSurface as GeoPlane;
                            if (pl != null)
                            {
                                c.Plana = true;
                                c.Normal = f.IsOrientToSurface ? pl.Normal : pl.Normal.Negate();
                                c.PuntoPlano = pl.PointOnPlane;
                            }
                        }
                    }
                    try { c.Area = f.GetArea(); } catch (SysException) { }
                    try
                    {
                        foreach (BR.BoundaryLoop lp in f.Loops)
                        {
                            try { foreach (BR.Vertex v in lp.Vertices) c.Pts.Add(v.Point); } catch (SysException) { }
                            if (c.Pts.Count == 0)
                            {
                                try
                                {
                                    foreach (BR.Edge e in lp.Edges)
                                    {
                                        var cu = e.Curve;
                                        c.Pts.Add(cu.StartPoint); c.Pts.Add(cu.EndPoint);
                                    }
                                }
                                catch (SysException) { }
                            }
                        }
                    }
                    catch (SysException) { }
                    CajaYCentro(c);
                    caras.Add(c);
                }
                foreach (BR.Edge e in brep.Edges)
                {
                    var a = new Arista();
                    a.Sid = e.SubentityPath.SubentId;
                    a.Index = a.Sid.IndexPtr.ToInt64();
                    Curve3d cu = null;
                    try { cu = e.Curve; } catch (SysException) { }
                    try { a.P1 = e.Vertex1.Point; a.P2 = e.Vertex2.Point; }
                    catch (SysException)
                    {
                        if (cu != null) { a.P1 = cu.StartPoint; a.P2 = cu.EndPoint; }
                    }
                    a.Largo = a.P1.DistanceTo(a.P2);
                    if (cu != null)
                    {
                        a.Kind = TipoCurva(cu);
                        try
                        {
                            var iv = cu.GetInterval();
                            double l = cu.GetLength(iv.LowerBound, iv.UpperBound, 1e-6);
                            if (l > 0 && !double.IsNaN(l) && !double.IsInfinity(l)) a.Largo = l;
                        }
                        catch (SysException) { }
                    }
                    try
                    {
                        foreach (BR.BoundaryLoop lp in e.Loops)
                        {
                            try { a.Caras.Add(lp.Face.SubentityPath.SubentId.IndexPtr.ToInt64()); } catch (SysException) { }
                        }
                    }
                    catch (SysException) { }
                    aristas.Add(a);
                }
            }
        }

        private static void CajaYCentro(Cara c)
        {
            if (c.Pts.Count == 0)
            {
                c.Centro = c.PuntoPlano; c.Min = c.PuntoPlano; c.Max = c.PuntoPlano;
                return;
            }
            double x0 = c.Pts.Min(p => p.X), y0 = c.Pts.Min(p => p.Y), z0 = c.Pts.Min(p => p.Z);
            double x1 = c.Pts.Max(p => p.X), y1 = c.Pts.Max(p => p.Y), z1 = c.Pts.Max(p => p.Z);
            c.Min = new Point3d(x0, y0, z0); c.Max = new Point3d(x1, y1, z1);
            c.Centro = new Point3d((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
        }

        // ============================================================ lectura de una malla SubDMesh

        private static string ClaveVertice(Point3d p)
        {
            return Math.Round(p.X, 6).ToString("R", CultureInfo.InvariantCulture) + "|" + Math.Round(p.Y, 6).ToString("R", CultureInfo.InvariantCulture)
                + "|" + Math.Round(p.Z, 6).ToString("R", CultureInfo.InvariantCulture);
        }

        private static void LeerMalla(SubDMesh m, List<Cara> caras, List<Arista> aristas, List<Point3d> vertices)
        {
            int nv = m.NumberOfVertices;
            for (int i = 0; i < nv; i++) vertices.Add(m.GetVertexAt(i));
            var fa = m.FaceArray;
            int k = 0, idx = 0;
            while (k < fa.Count)
            {
                int n = fa[k];
                if (n < 3 || k + n >= fa.Count) break;
                var c = new Cara();
                for (int j = 1; j <= n; j++) c.Vertices.Add(fa[k + j]);
                k += n + 1;
                var sp = m.GetSubentPath(idx, SubentityType.Face);
                c.Sid = sp[0].SubentId;
                c.Index = idx;
                foreach (int vi in c.Vertices) if (vi >= 0 && vi < vertices.Count) c.Pts.Add(vertices[vi]);
                try
                {
                    var pl = m.GetFacePlane(c.Sid);
                    c.Plana = true; c.Kind = "plane"; c.Normal = pl.Normal; c.PuntoPlano = pl.PointOnPlane;
                }
                catch (SysException) { }
                c.Area = AreaPoligono(c.Pts);
                CajaYCentro(c);
                caras.Add(c);
                idx++;
            }
            var clave = new Dictionary<string, int>();
            for (int i = 0; i < vertices.Count; i++) { string kk = ClaveVertice(vertices[i]); if (!clave.ContainsKey(kk)) clave[kk] = i; }
            int ne = m.NumberOfEdges;
            for (int i = 0; i < ne; i++)
            {
                var a = new Arista();
                var p = m.GetSubentPath(i, SubentityType.Edge)[0];
                a.Sid = p.SubentId; a.Index = i; a.Kind = "line";
                using (var ent = m.GetSubentity(p))
                {
                    var cv = ent as Curve;
                    if (cv != null) { a.P1 = cv.StartPoint; a.P2 = cv.EndPoint; }
                }
                a.Largo = a.P1.DistanceTo(a.P2);
                int v1, v2;
                if (clave.TryGetValue(ClaveVertice(a.P1), out v1) && clave.TryGetValue(ClaveVertice(a.P2), out v2))
                {
                    foreach (var c in caras)
                    {
                        int n = c.Vertices.Count;
                        for (int j = 0; j < n; j++)
                        {
                            int x = c.Vertices[j], y = c.Vertices[(j + 1) % n];
                            if ((x == v1 && y == v2) || (x == v2 && y == v1)) { a.Caras.Add(c.Index); break; }
                        }
                    }
                }
                aristas.Add(a);
            }
        }

        private static double AreaPoligono(List<Point3d> pts)
        {
            if (pts.Count < 3) return 0;
            double nx = 0, ny = 0, nz = 0;
            for (int i = 0; i < pts.Count; i++)
            {
                var a = pts[i]; var b = pts[(i + 1) % pts.Count];
                nx += (a.Y - b.Y) * (a.Z + b.Z);
                ny += (a.Z - b.Z) * (a.X + b.X);
                nz += (a.X - b.X) * (a.Y + b.Y);
            }
            return 0.5 * Math.Sqrt(nx * nx + ny * ny + nz * nz);
        }

        // ============================================================ selectores

        private static readonly string[] ClavesCara = { "indices", "normal", "tol_deg", "z", "z_tol", "kind", "min_area", "max_area", "all" };
        private static readonly string[] ClavesArista = { "indices", "z", "z_tol", "vertical", "horizontal", "kind", "min_length", "max_length", "on_face", "all" };

        private static void ClavesValidas(JsonObject o, string[] validas, string cual)
        {
            foreach (var kv in o)
                if (Array.IndexOf(validas, kv.Key) < 0)
                    throw new ArgumentException("El selector '" + cual + "' no conoce la clave '" + kv.Key + "'. Válidas: " + string.Join(", ", validas) + ".");
        }

        private static List<long> Indices(JsonObject o, string cual)
        {
            var r = new List<long>();
            var a = o["indices"] as JsonArray;
            if (a == null) throw new ArgumentException("En '" + cual + "', 'indices' tiene que ser una lista de enteros.");
            foreach (var n in a)
            {
                double d = n.GetValue<double>();
                if (d < 0 || Math.Abs(d - Math.Round(d)) > 1e-9) throw new ArgumentException("En '" + cual + "', los índices son enteros >= 0.");
                r.Add((long)d);
            }
            return r;
        }

        private static List<Cara> SelCaras(List<Cara> todas, JsonNode sel, string cual)
        {
            var o = sel as JsonObject;
            if (o == null) throw new ArgumentException("'" + cual + "' es un selector de caras, p.ej. {\"normal\": [0,0,1]}, {\"indices\": [0, 3]} o {\"all\": true}. Mirá las caras con list_subentities.");
            ClavesValidas(o, ClavesCara, cual);
            bool todo = o["all"] != null && o["all"].GetValue<bool>();
            bool hayFiltro = o["indices"] != null || o["normal"] != null || o["z"] != null || o["kind"] != null || o["min_area"] != null || o["max_area"] != null;
            if (!hayFiltro && !todo) throw new ArgumentException("El selector '" + cual + "' está vacío: poné un filtro (indices, normal, z, kind, min_area...) o {\"all\": true}.");
            IEnumerable<Cara> r = todas;
            if (o["indices"] != null)
            {
                var ix = Indices(o, cual);
                foreach (long i in ix)
                    if (!todas.Any(c => c.Index == i))
                        throw new ArgumentException("No hay una cara con índice " + i + " (hay " + todas.Count + " caras; los índices válidos salen de list_subentities).");
                r = r.Where(c => ix.Contains(c.Index));
            }
            if (o["normal"] != null)
            {
                var nv = Vector(o["normal"], cual + ".normal").GetNormal();
                double tol = o["tol_deg"] != null ? o["tol_deg"].GetValue<double>() : 5.0;
                if (tol < 0 || tol > 90) throw new ArgumentException("'tol_deg' va de 0 a 90.");
                double lim = Math.Cos(ARadianes(tol));
                r = r.Where(c => c.Plana && c.Normal.GetNormal().DotProduct(nv) >= lim - 1e-12);
            }
            if (o["z"] != null)
            {
                double z = o["z"].GetValue<double>();
                double zt = o["z_tol"] != null ? o["z_tol"].GetValue<double>() : 1e-4;
                r = r.Where(c => c.Plana && Math.Abs(Math.Abs(c.Normal.GetNormal().Z) - 1.0) < 1e-6 && Math.Abs(c.PuntoPlano.Z - z) <= zt);
            }
            if (o["kind"] != null)
            {
                string k = o["kind"].GetValue<string>().ToLowerInvariant();
                r = r.Where(c => c.Kind == k);
            }
            if (o["min_area"] != null) { double v = o["min_area"].GetValue<double>(); r = r.Where(c => c.Area >= v); }
            if (o["max_area"] != null) { double v = o["max_area"].GetValue<double>(); r = r.Where(c => c.Area <= v); }
            var lista = r.ToList();
            if (lista.Count == 0)
                throw new ArgumentException("Ninguna cara cumple el selector '" + cual + "' (el objeto tiene " + todas.Count + " caras; mirá sus normales y centros con list_subentities).");
            return lista;
        }

        private static List<Arista> SelAristas(List<Arista> todas, List<Cara> caras, JsonNode sel, string cual)
        {
            var o = sel as JsonObject;
            if (o == null) throw new ArgumentException("'" + cual + "' es un selector de aristas, p.ej. {\"z\": 0}, {\"indices\": [2, 5]}, {\"on_face\": {\"normal\": [0,0,1]}} o {\"all\": true}. Mirá las aristas con list_subentities.");
            ClavesValidas(o, ClavesArista, cual);
            bool todo = o["all"] != null && o["all"].GetValue<bool>();
            bool hayFiltro = o["indices"] != null || o["z"] != null || o["vertical"] != null || o["horizontal"] != null || o["kind"] != null
                || o["min_length"] != null || o["max_length"] != null || o["on_face"] != null;
            if (!hayFiltro && !todo) throw new ArgumentException("El selector '" + cual + "' está vacío: poné un filtro (indices, z, vertical, horizontal, kind, min_length, on_face...) o {\"all\": true}.");
            IEnumerable<Arista> r = todas;
            if (o["indices"] != null)
            {
                var ix = Indices(o, cual);
                foreach (long i in ix)
                    if (!todas.Any(a => a.Index == i))
                        throw new ArgumentException("No hay una arista con índice " + i + " (hay " + todas.Count + " aristas; los índices válidos salen de list_subentities).");
                r = r.Where(a => ix.Contains(a.Index));
            }
            if (o["z"] != null)
            {
                double z = o["z"].GetValue<double>();
                double zt = o["z_tol"] != null ? o["z_tol"].GetValue<double>() : 1e-4;
                r = r.Where(a => Math.Abs(a.P1.Z - a.P2.Z) <= zt && Math.Abs(a.P1.Z - z) <= zt);
            }
            if (o["vertical"] != null && o["vertical"].GetValue<bool>())
                r = r.Where(a => Math.Abs(a.P1.X - a.P2.X) < 1e-6 && Math.Abs(a.P1.Y - a.P2.Y) < 1e-6 && Math.Abs(a.P1.Z - a.P2.Z) > 1e-6);
            if (o["horizontal"] != null && o["horizontal"].GetValue<bool>())
                r = r.Where(a => Math.Abs(a.P1.Z - a.P2.Z) < 1e-6);
            if (o["kind"] != null)
            {
                string k = o["kind"].GetValue<string>().ToLowerInvariant();
                r = r.Where(a => a.Kind == k);
            }
            if (o["min_length"] != null) { double v = o["min_length"].GetValue<double>(); r = r.Where(a => a.Largo >= v); }
            if (o["max_length"] != null) { double v = o["max_length"].GetValue<double>(); r = r.Where(a => a.Largo <= v); }
            if (o["on_face"] != null)
            {
                var cs = SelCaras(caras, o["on_face"], cual + ".on_face");
                var ids = new HashSet<long>(cs.Select(c => c.Index));
                r = r.Where(a => a.Caras.Any(ids.Contains));
            }
            var lista = r.ToList();
            if (lista.Count == 0)
                throw new ArgumentException("Ninguna arista cumple el selector '" + cual + "' (el objeto tiene " + todas.Count + " aristas; mirá sus extremos con list_subentities).");
            return lista;
        }

        // ============================================================ list_subentities

        private static JsonObject CaraJson(Cara c, bool malla)
        {
            var j = new JsonObject
            {
                ["index"] = c.Index,
                ["kind"] = c.Kind,
                ["area"] = Math.Round(c.Area, 6),
                ["center"] = Arr(c.Centro),
                ["min"] = Arr(c.Min),
                ["max"] = Arr(c.Max)
            };
            if (c.Plana) { j["normal"] = Arr(c.Normal.GetNormal()); j["z"] = Math.Round(c.PuntoPlano.Z, 6); }
            if (malla) j["vertices"] = new JsonArray(c.Vertices.Select(v => (JsonNode)v).ToArray());
            return j;
        }

        private static JsonObject AristaJson(Arista a)
        {
            return new JsonObject
            {
                ["index"] = a.Index,
                ["kind"] = a.Kind,
                ["length"] = Math.Round(a.Largo, 6),
                ["p1"] = Arr(a.P1),
                ["p2"] = Arr(a.P2),
                ["faces"] = new JsonArray(a.Caras.OrderBy(x => x).Select(x => (JsonNode)x).ToArray())
            };
        }

        /// <summary>params: handle (Solid3d | Surface | Region | SubDMesh), [kind=faces | edges | vertices (solo malla)], [select] (selector que
        /// filtra lo que se lista), [limit=200]. Devuelve cada cara/arista con su índice, que es el que piden las tools de edición.</summary>
        public static JsonObject List(Document doc, JsonObject pars)
        {
            string kind = (pars["kind"]?.GetValue<string>() ?? "faces").ToLowerInvariant();
            if (kind != "faces" && kind != "edges" && kind != "vertices")
                throw new ArgumentException("kind '" + kind + "' no existe: faces, edges o vertices (esta última solo en mallas).");
            int limite = pars["limit"] != null ? (int)Num(pars, "limit", 200) : 200;
            if (limite < 1 || limite > 5000) throw new ArgumentException("'limit' va de 1 a 5000.");
            var db = doc.Database;
            var id = Id(doc, pars["handle"], "handle");
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var ent = tr.GetObject(id, OpenMode.ForRead) as Entity;
                var caras = new List<Cara>(); var aristas = new List<Arista>(); var verts = new List<Point3d>();
                bool malla = ent is SubDMesh;
                if (malla) LeerMalla((SubDMesh)ent, caras, aristas, verts);
                else if (ent is Solid3d || ent is DbSurface || ent is Region || ent is Body) LeerBrep(ent, caras, aristas);
                else throw new ArgumentException("'" + pars["handle"].GetValue<string>() + "' (" + (ent == null ? "no es una entidad" : ent.GetType().Name) + ") no tiene caras ni aristas editables: usá un sólido, una superficie, una región o una malla.");
                if (kind == "vertices" && !malla) throw new ArgumentException("Los vértices solo se listan en mallas; en un sólido o superficie elegí faces o edges.");

                var items = new JsonArray();
                int total;
                var sel = pars["select"];
                if (kind == "faces")
                {
                    var l = sel != null ? SelCaras(caras, sel, "select") : caras;
                    total = l.Count;
                    foreach (var c in l.Take(limite)) items.Add(CaraJson(c, malla));
                }
                else if (kind == "edges")
                {
                    var l = sel != null ? SelAristas(aristas, caras, sel, "select") : aristas;
                    total = l.Count;
                    foreach (var a in l.Take(limite)) items.Add(AristaJson(a));
                }
                else
                {
                    total = verts.Count;
                    for (int i = 0; i < verts.Count && i < limite; i++) items.Add(new JsonObject { ["index"] = i, ["point"] = Arr(verts[i]) });
                }
                var r = new JsonObject
                {
                    ["handle"] = ent.Handle.ToString(),
                    ["type"] = ent.GetType().Name,
                    ["kind"] = kind,
                    ["totalFaces"] = caras.Count,
                    ["totalEdges"] = aristas.Count,
                    ["total"] = total,
                    ["returned"] = items.Count,
                    ["truncated"] = total > items.Count,
                    ["items"] = items
                };
                if (malla) r["totalVertices"] = verts.Count;
                tr.Commit();
                return r;
            }
        }

        // ============================================================ edit_solid_faces

        private static Entity AbrirEscritura(Transaction tr, ObjectId id, string handle, Type[] tipos, string quien)
        {
            var o = tr.GetObject(id, OpenMode.ForWrite, false, true) as Entity;
            if (o == null || !tipos.Any(t => t.IsInstanceOfType(o)))
                throw new ArgumentException("'" + handle + "' (" + (o == null ? "no es una entidad" : o.GetType().Name) + ") no es " + quien + ".");
            return o;
        }

        /// <summary>params: handle (Solid3d), op (extrude | offset | remove | taper | shell), faces (selector; en shell es opcional: las
        /// caras que quedan ABIERTAS), y según la operación: extrude → height, [taper_deg=0]; offset → distance (positiva engorda hacia afuera);
        /// taper → base_point, direction, angle_deg; shell → thickness; remove → nada. [dry_run=false] solo dice qué caras tocaría.</summary>
        public static JsonObject EditSolidFaces(Document doc, JsonObject pars)
        {
            string op = (pars["op"]?.GetValue<string>() ?? "").ToLowerInvariant();
            if (op != "extrude" && op != "offset" && op != "remove" && op != "taper" && op != "shell")
                throw new ArgumentException("op '" + op + "' no existe: extrude, offset, remove, taper o shell.");
            bool seco = pars["dry_run"] != null && pars["dry_run"].GetValue<bool>();
            // validar todo lo numérico ANTES de abrir nada
            double altura = 0, dist = 0, ahusado = 0, grosor = 0, angulo = 0; Point3d basePt = Point3d.Origin; Vector3d dir = Vector3d.ZAxis;
            if (op == "extrude")
            {
                if (pars["height"] == null) throw new ArgumentException("extrude necesita 'height' (la altura, positiva hacia afuera de la cara).");
                altura = Num(pars, "height", 0);
                if (Math.Abs(altura) < 1e-9) throw new ArgumentException("'height' no puede ser 0.");
                ahusado = ARadianes(Num(pars, "taper_deg", 0));
                if (Math.Abs(ahusado) >= Math.PI / 2) throw new ArgumentException("'taper_deg' tiene que estar entre -90 y 90 (exclusivo).");
            }
            else if (op == "offset")
            {
                if (pars["distance"] == null) throw new ArgumentException("offset necesita 'distance' (positiva engorda hacia afuera).");
                dist = Num(pars, "distance", 0);
                if (Math.Abs(dist) < 1e-9) throw new ArgumentException("'distance' no puede ser 0.");
            }
            else if (op == "taper")
            {
                basePt = Punto(pars["base_point"], "base_point");
                dir = Vector(pars["direction"], "direction");
                if (pars["angle_deg"] == null) throw new ArgumentException("taper necesita 'angle_deg'.");
                angulo = ARadianes(Num(pars, "angle_deg", 0));
                if (Math.Abs(angulo) >= Math.PI / 2) throw new ArgumentException("'angle_deg' tiene que estar entre -90 y 90 (exclusivo).");
            }
            else if (op == "shell")
            {
                grosor = NumPos(pars, "thickness", "el espesor de la pared");
            }
            if (op != "shell" && pars["faces"] == null) throw new ArgumentException("Falta 'faces' (un selector de caras: " + op + " opera sobre caras).");

            var db = doc.Database;
            var id = Id(doc, pars["handle"], "handle");
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var s = (Solid3d)AbrirEscritura(tr, id, pars["handle"].GetValue<string>(), new[] { typeof(Solid3d) }, "un sólido 3D");
                    var caras = new List<Cara>(); var aristas = new List<Arista>();
                    LeerBrep(s, caras, aristas);
                    List<Cara> elegidas = pars["faces"] != null ? SelCaras(caras, pars["faces"], "faces") : new List<Cara>();
                    var resumen = new JsonArray(elegidas.Select(c => (JsonNode)CaraJson(c, false)).ToArray());
                    var antes = Extension(s);
                    if (seco)
                    {
                        tr.Abort();
                        return new JsonObject { ["dry_run"] = true, ["op"] = op, ["selected"] = elegidas.Count, ["faces"] = resumen, ["totalFaces"] = caras.Count };
                    }
                    var ids = elegidas.Select(c => c.Sid).ToArray();
                    switch (op)
                    {
                        case "extrude": s.ExtrudeFaces(ids, altura, ahusado); break;
                        case "offset": s.OffsetFaces(ids, dist); break;
                        case "remove": s.RemoveFaces(ids); break;
                        case "taper": s.TaperFaces(ids, basePt, dir, angulo); break;
                        case "shell": s.ShellBody(ids, -grosor); break; // como SOLIDEDIT: el espesor se mide hacia ADENTRO (la API da positivo = hacia afuera)
                    }
                    var caras2 = new List<Cara>(); var aristas2 = new List<Arista>();
                    LeerBrep(s, caras2, aristas2);
                    var r = new JsonObject
                    {
                        ["handle"] = s.Handle.ToString(),
                        ["op"] = op,
                        ["selected"] = elegidas.Count,
                        ["facesBefore"] = caras.Count,
                        ["facesAfter"] = caras2.Count,
                        ["edgesBefore"] = aristas.Count,
                        ["edgesAfter"] = aristas2.Count,
                        ["extentsBefore"] = antes,
                        ["extentsAfter"] = Extension(s)
                    };
                    try { r["volume"] = s.MassProperties.Volume; } catch (SysException) { }
                    tr.Commit();
                    return r;
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD no pudo hacer '" + op + "' en las caras elegidas (" + ex.ErrorStatus + "): " + ex.Message
                        + ". No se cambió nada. Causas típicas: la cara no se puede mover sin que el sólido se corte a sí mismo, el espesor es mayor que lo que el sólido permite, o la cara no es removible (solo se quitan agujeros, redondeos y chaflanes).");
                }
                catch (SysException) { tr.Abort(); throw; }
            }
        }

        // ============================================================ chamfer_solid_edges

        /// <summary>params: handle (Solid3d), edges (selector), base_face (selector que da UNA sola cara a la que pertenezcan todas las aristas),
        /// distance (sobre la cara base), [distance2=distance] (sobre la otra cara). [dry_run=false].</summary>
        public static JsonObject ChamferSolidEdges(Document doc, JsonObject pars)
        {
            if (pars["edges"] == null) throw new ArgumentException("Falta 'edges' (un selector de aristas).");
            if (pars["base_face"] == null) throw new ArgumentException("Falta 'base_face' (un selector que dé UNA cara: la que contiene a las aristas y sobre la que se mide 'distance').");
            double d1 = NumPos(pars, "distance", "la distancia del chaflán sobre la cara base");
            double d2 = pars["distance2"] != null ? NumPos(pars, "distance2", "la distancia sobre la otra cara") : d1;
            bool seco = pars["dry_run"] != null && pars["dry_run"].GetValue<bool>();
            var db = doc.Database;
            var id = Id(doc, pars["handle"], "handle");
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var s = (Solid3d)AbrirEscritura(tr, id, pars["handle"].GetValue<string>(), new[] { typeof(Solid3d) }, "un sólido 3D");
                    var caras = new List<Cara>(); var aristas = new List<Arista>();
                    LeerBrep(s, caras, aristas);
                    var bases = SelCaras(caras, pars["base_face"], "base_face");
                    if (bases.Count != 1)
                        throw new ArgumentException("'base_face' dio " + bases.Count + " caras y tiene que dar exactamente una (índices: " + string.Join(", ", bases.Select(c => c.Index)) + "). Acotá el selector.");
                    var elegidas = SelAristas(aristas, caras, pars["edges"], "edges");
                    var fuera = elegidas.Where(a => !a.Caras.Contains(bases[0].Index)).ToList();
                    if (fuera.Count > 0)
                        throw new ArgumentException("Estas aristas no pertenecen a la cara base " + bases[0].Index + ": " + string.Join(", ", fuera.Select(a => a.Index))
                            + ". El chaflán se mide desde la cara base, así que todas las aristas tienen que tocarla.");
                    if (seco)
                    {
                        tr.Abort();
                        return new JsonObject { ["dry_run"] = true, ["baseFace"] = bases[0].Index, ["edges"] = new JsonArray(elegidas.Select(a => (JsonNode)AristaJson(a)).ToArray()) };
                    }
                    var antes = caras.Count;
                    s.ChamferEdges(elegidas.Select(a => a.Sid).ToArray(), bases[0].Sid, d1, d2);
                    var caras2 = new List<Cara>(); var aristas2 = new List<Arista>();
                    LeerBrep(s, caras2, aristas2);
                    var r = new JsonObject
                    {
                        ["handle"] = s.Handle.ToString(),
                        ["edges"] = elegidas.Count,
                        ["baseFace"] = bases[0].Index,
                        ["distance"] = d1,
                        ["distance2"] = d2,
                        ["facesBefore"] = antes,
                        ["facesAfter"] = caras2.Count
                    };
                    try { r["volume"] = s.MassProperties.Volume; } catch (SysException) { }
                    tr.Commit();
                    return r;
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD no pudo achaflanar (" + ex.ErrorStatus + "): " + ex.Message
                        + ". No se cambió nada. Causas típicas: la distancia es mayor que la cara o que lo que permite el sólido en esa esquina, o las aristas no son consecutivas con la cara base.");
                }
                catch (SysException) { tr.Abort(); throw; }
            }
        }

        // ============================================================ edit_mesh_faces

        private static FullSubentityPath[] RutasCara(SubDMesh m, IEnumerable<long> indices)
        {
            return indices.Select(i => m.GetSubentPath((int)i, SubentityType.Face)[0]).ToArray();
        }

        private static FullSubentityPath[] RutasArista(SubDMesh m, IEnumerable<long> indices)
        {
            return indices.Select(i => m.GetSubentPath((int)i, SubentityType.Edge)[0]).ToArray();
        }

        private static int EntRango(JsonObject pars, string clave, int max, string que)
        {
            if (pars[clave] == null) throw new ArgumentException("Falta '" + clave + "' (" + que + ").");
            double d = pars[clave].GetValue<double>();
            if (d < 0 || Math.Abs(d - Math.Round(d)) > 1e-9 || d >= max)
                throw new ArgumentException("'" + clave + "' tiene que ser un entero entre 0 y " + (max - 1) + " (índice de " + que + ").");
            return (int)d;
        }

        /// <summary>params: handle (SubDMesh), op, y según la operación:
        ///   extrude:  faces, length, [direction] (sin ella, cada grupo de caras sale por su normal), [taper_deg=0], [connected=false]
        ///   merge:    faces (2 o más, vecinas y coplanares)
        ///   split:    face, edge_a, edge_b (aristas de ESA cara), [t_a=0.5], [t_b=0.5] (posición sobre cada arista, 0..1)
        ///   crease:   level (>=0) y faces y/o edges (selectores), o whole_mesh=true
        ///   collapse: face | edge (índice)
        ///   cap:      edges (selector de aristas del borde abierto)
        ///   spin:     edge (índice de la arista compartida por DOS triángulos: la gira a la otra diagonal)
        /// </summary>
        public static JsonObject EditMeshFaces(Document doc, JsonObject pars)
        {
            string op = (pars["op"]?.GetValue<string>() ?? "").ToLowerInvariant();
            string[] ops = { "extrude", "merge", "split", "crease", "collapse", "cap", "spin" };
            if (Array.IndexOf(ops, op) < 0) throw new ArgumentException("op '" + op + "' no existe: " + string.Join(", ", ops) + ".");
            double largo = 0, ahusado = 0, nivel = 0, ta = 0.5, tb = 0.5;
            Vector3d? dirFija = null;
            bool conectadas = false, todaLaMalla = false;
            if (op == "extrude")
            {
                if (pars["length"] == null) throw new ArgumentException("extrude necesita 'length' (la distancia, positiva hacia afuera de la cara).");
                largo = Num(pars, "length", 0);
                if (Math.Abs(largo) < 1e-9) throw new ArgumentException("'length' no puede ser 0.");
                ahusado = ARadianes(Num(pars, "taper_deg", 0));
                if (Math.Abs(ahusado) >= Math.PI / 2) throw new ArgumentException("'taper_deg' tiene que estar entre -90 y 90 (exclusivo).");
                if (pars["direction"] != null) dirFija = Vector(pars["direction"], "direction").GetNormal();
                conectadas = pars["connected"] != null && pars["connected"].GetValue<bool>();
                if (pars["faces"] == null) throw new ArgumentException("extrude necesita 'faces' (un selector de caras).");
            }
            else if (op == "merge")
            {
                if (pars["faces"] == null) throw new ArgumentException("merge necesita 'faces' (un selector de 2 o más caras vecinas y coplanares).");
            }
            else if (op == "crease")
            {
                if (pars["level"] == null) throw new ArgumentException("crease necesita 'level' (>= 0; cuanto más alto, más filosa la arista).");
                nivel = Num(pars, "level", 0);
                if (nivel < 0) throw new ArgumentException("'level' no puede ser negativo.");
                todaLaMalla = pars["whole_mesh"] != null && pars["whole_mesh"].GetValue<bool>();
                if (!todaLaMalla && pars["faces"] == null && pars["edges"] == null)
                    throw new ArgumentException("crease necesita 'faces' y/o 'edges' (selectores) o whole_mesh=true.");
            }
            else if (op == "cap")
            {
                if (pars["edges"] == null) throw new ArgumentException("cap necesita 'edges' (un selector de las aristas del borde abierto).");
            }
            else if (op == "split")
            {
                ta = Num(pars, "t_a", 0.5); tb = Num(pars, "t_b", 0.5);
                if (ta <= 0 || ta >= 1 || tb <= 0 || tb >= 1) throw new ArgumentException("'t_a' y 't_b' van entre 0 y 1 sin tocar los extremos (0.5 = punto medio).");
            }
            var db = doc.Database;
            var id = Id(doc, pars["handle"], "handle");
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var m = (SubDMesh)AbrirEscritura(tr, id, pars["handle"].GetValue<string>(), new[] { typeof(SubDMesh) }, "una malla (SubDMesh)");
                    var caras = new List<Cara>(); var aristas = new List<Arista>(); var verts = new List<Point3d>();
                    LeerMalla(m, caras, aristas, verts);
                    int f0 = m.NumberOfFaces, v0 = m.NumberOfVertices, e0 = m.NumberOfEdges;
                    string aviso = null;
                    switch (op)
                    {
                        case "extrude":
                        {
                            var el = SelCaras(caras, pars["faces"], "faces");
                            var grupos = new List<List<Cara>>();
                            var normales = new List<Vector3d>();
                            if (dirFija.HasValue) { grupos.Add(el); normales.Add(dirFija.Value); }
                            else
                            {
                                foreach (var c in el)
                                {
                                    if (!c.Plana) throw new ArgumentException("La cara " + c.Index + " no tiene normal definida: pasá 'direction'.");
                                    var n = c.Normal.GetNormal();
                                    int g = normales.FindIndex(x => x.DotProduct(n) > 1 - 1e-6);
                                    if (g < 0) { normales.Add(n); grupos.Add(new List<Cara>()); g = grupos.Count - 1; }
                                    grupos[g].Add(c);
                                }
                            }
                            for (int g = 0; g < grupos.Count; g++)
                            {
                                var rutas = RutasCara(m, grupos[g].Select(c => c.Index));
                                if (conectadas) m.ExtrudeConnectedFaces(rutas, largo, normales[g], ahusado);
                                else m.ExtrudeFaces(rutas, largo, normales[g], ahusado);
                            }
                            break;
                        }
                        case "merge":
                        {
                            var el = SelCaras(caras, pars["faces"], "faces");
                            if (el.Count < 2) throw new ArgumentException("merge necesita 2 o más caras (el selector dio " + el.Count + ").");
                            m.MergeFaces(RutasCara(m, el.Select(c => c.Index)));
                            if (m.NumberOfFaces >= f0) aviso = "AutoCAD no fusionó nada: las caras tienen que ser vecinas (compartir arista) y coplanares.";
                            break;
                        }
                        case "split":
                        {
                            int cara = EntRango(pars, "face", caras.Count, "cara");
                            int ea = EntRango(pars, "edge_a", aristas.Count, "arista");
                            int eb = EntRango(pars, "edge_b", aristas.Count, "arista");
                            if (ea == eb) throw new ArgumentException("'edge_a' y 'edge_b' tienen que ser aristas distintas.");
                            var A = aristas[ea]; var B = aristas[eb];
                            if (!A.Caras.Contains(cara) || !B.Caras.Contains(cara))
                                throw new ArgumentException("Las aristas " + ea + " y " + eb + " tienen que ser bordes de la cara " + cara + " (la arista " + ea + " toca las caras " + string.Join(",", A.Caras) + " y la " + eb + " las " + string.Join(",", B.Caras) + ").");
                            var pa = A.P1 + (A.P2 - A.P1) * ta; var pb = B.P1 + (B.P2 - B.P1) * tb;
                            m.SplitFace(caras[cara].Sid, A.Sid, pa, B.Sid, pb);
                            if (m.NumberOfFaces <= f0) aviso = "AutoCAD no dividió la cara.";
                            break;
                        }
                        case "crease":
                        {
                            if (todaLaMalla) { m.SetCrease(nivel); break; }
                            var rutas = new List<FullSubentityPath>();
                            if (pars["faces"] != null) rutas.AddRange(RutasCara(m, SelCaras(caras, pars["faces"], "faces").Select(c => c.Index)));
                            if (pars["edges"] != null) rutas.AddRange(RutasArista(m, SelAristas(aristas, caras, pars["edges"], "edges").Select(a => a.Index)));
                            m.SetCrease(rutas.ToArray(), nivel);
                            break;
                        }
                        case "collapse":
                        {
                            bool hayCara = pars["face"] != null, hayArista = pars["edge"] != null;
                            if (hayCara == hayArista) throw new ArgumentException("collapse necesita 'face' O 'edge' (un índice), no los dos ni ninguno.");
                            if (hayCara) m.Collapse(caras[EntRango(pars, "face", caras.Count, "cara")].Sid);
                            else m.Collapse(aristas[EntRango(pars, "edge", aristas.Count, "arista")].Sid);
                            if (m.NumberOfVertices >= v0) aviso = "AutoCAD no colapsó nada.";
                            break;
                        }
                        case "cap":
                        {
                            var el = SelAristas(aristas, caras, pars["edges"], "edges");
                            var abiertas = el.Where(a => a.Caras.Count < 2).ToList();
                            if (abiertas.Count == 0)
                                throw new ArgumentException("Esas aristas ya son vecinas de dos caras: cap tapa un borde ABIERTO (aristas con una sola cara). Listá aristas con list_subentities.");
                            m.Cap(RutasArista(m, abiertas.Select(a => a.Index)));
                            if (m.NumberOfFaces <= f0) aviso = "AutoCAD no agregó ninguna cara (el borde tiene que formar un lazo cerrado).";
                            break;
                        }
                        case "spin":
                        {
                            int ar = EntRango(pars, "edge", aristas.Count, "arista");
                            var A = aristas[ar];
                            var tri = A.Caras.Where(c => caras[(int)c].Vertices.Count == 3).ToList();
                            if (A.Caras.Count != 2 || tri.Count != 2)
                                throw new ArgumentException("spin gira la arista compartida de DOS TRIÁNGULOS: la arista " + ar + " toca " + A.Caras.Count + " cara(s) y " + tri.Count + " de ellas es(son) triángulo(s). Convertí la malla a triángulos o elegí la diagonal entre dos triángulos.");
                            m.Spin(A.Sid);
                            break;
                        }
                    }
                    var r = new JsonObject
                    {
                        ["handle"] = m.Handle.ToString(),
                        ["op"] = op,
                        ["facesBefore"] = f0,
                        ["facesAfter"] = m.NumberOfFaces,
                        ["verticesBefore"] = v0,
                        ["verticesAfter"] = m.NumberOfVertices,
                        ["edgesBefore"] = e0,
                        ["edgesAfter"] = m.NumberOfEdges
                    };
                    if (aviso != null) r["warning"] = aviso;
                    tr.Commit();
                    return r;
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD no pudo hacer '" + op + "' en la malla (" + ex.ErrorStatus + "): " + ex.Message + ". No se cambió nada.");
                }
                catch (SysException) { tr.Abort(); throw; }
            }
        }

        // ============================================================ trim_surface / extend_surface / fillet_surfaces

        private static DbSurface Superficie(Transaction tr, ObjectId id, string cual, bool escritura)
        {
            var o = tr.GetObject(id, escritura ? OpenMode.ForWrite : OpenMode.ForRead, false, true) as DbSurface;
            if (o == null) throw new ArgumentException("'" + cual + "' no es una superficie (usá create_surface para hacer una).");
            return o;
        }

        /// <summary>params: blank (handle de la superficie a recortar), pick_point [x,y,z] (un punto sobre la parte que SE QUITA), y las
        /// herramientas de corte: tools[] (superficies) y/o curves[] (curvas que se proyectan sobre la superficie), [project_dir=[0,0,1]]
        /// (dirección de proyección de las curvas), [auto_extend=false] (alarga las herramientas hasta cortar del todo).</summary>
        public static JsonObject TrimSurface(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var blank = Id(doc, pars["blank"], "blank");
            var punto = Punto(pars["pick_point"], "pick_point");
            var tools = new ObjectIdCollection(); var curvas = new ObjectIdCollection();
            foreach (var h in (pars["tools"] as JsonArray) ?? new JsonArray()) tools.Add(HandleHelper.GetObjectId(db, h.GetValue<string>()));
            foreach (var h in (pars["curves"] as JsonArray) ?? new JsonArray()) curvas.Add(HandleHelper.GetObjectId(db, h.GetValue<string>()));
            if (tools.Count + curvas.Count == 0) throw new ArgumentException("Falta el corte: pasá 'tools' (superficies) y/o 'curves' (curvas).");
            if (tools.Contains(blank) || curvas.Contains(blank)) throw new ArgumentException("La superficie a recortar no puede ser su propia herramienta de corte.");
            var proy = pars["project_dir"] != null ? Vector(pars["project_dir"], "project_dir") : Vector3d.ZAxis;
            bool extender = pars["auto_extend"] != null && pars["auto_extend"].GetValue<bool>();
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var s = Superficie(tr, blank, "blank", false);
                    foreach (ObjectId t in tools) Superficie(tr, t, "tools", false);
                    foreach (ObjectId c in curvas)
                        if (!(tr.GetObject(c, OpenMode.ForRead) is Curve)) throw new ArgumentException("Un elemento de 'curves' no es una curva.");
                    var antes = Extension(s);
                    var vectores = new Vector3dCollection();
                    for (int i = 0; i < curvas.Count; i++) vectores.Add(proy);
                    DbSurface.TrimSurface(blank, tools, curvas, vectores, punto, proy, extender, false);
                    var r = new JsonObject
                    {
                        ["handle"] = s.Handle.ToString(),
                        ["extentsBefore"] = antes,
                        ["extentsAfter"] = Extension(s)
                    };
                    tr.Commit();
                    return r;
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD no pudo recortar la superficie (" + ex.ErrorStatus + "): " + ex.Message
                        + ". No se cambió nada. Causas típicas: la herramienta no corta a la superficie (probá auto_extend=true) o el punto no cae sobre la superficie.");
                }
                catch (SysException) { tr.Abort(); throw; }
            }
        }

        /// <summary>params: handle (superficie), edges (selector de aristas: p.ej. {"indices":[2]} o {"all":true}), distance (> 0),
        /// [mode=extend | stretch] (extend sigue la forma de la superficie; stretch la estira recta), [associative=false].</summary>
        public static JsonObject ExtendSurface(Document doc, JsonObject pars)
        {
            if (pars["edges"] == null) throw new ArgumentException("Falta 'edges' (un selector de aristas del borde a extender; list_subentities las da).");
            double dist = NumPos(pars, "distance", "cuánto se extiende");
            string modo = (pars["mode"]?.GetValue<string>() ?? "extend").ToLowerInvariant();
            if (modo != "extend" && modo != "stretch") throw new ArgumentException("mode '" + modo + "' no existe: extend o stretch.");
            bool asoc = pars["associative"] != null && pars["associative"].GetValue<bool>();
            var db = doc.Database;
            var id = Id(doc, pars["handle"], "handle");
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    var s = Superficie(tr, id, "handle", true);
                    var caras = new List<Cara>(); var aristas = new List<Arista>();
                    LeerBrep(s, caras, aristas);
                    var el = SelAristas(aristas, caras, pars["edges"], "edges");
                    var antes = Extension(s);
                    var rutas = el.Select(a => new FullSubentityPath(new ObjectId[] { s.ObjectId }, a.Sid)).ToArray();
                    s.ExtendEdges(rutas, dist, modo == "extend" ? DbSurface.EdgeExtensionType.ExtendEdge : DbSurface.EdgeExtensionType.StretchEdge, asoc);
                    var r = new JsonObject
                    {
                        ["handle"] = s.Handle.ToString(),
                        ["edges"] = el.Count,
                        ["distance"] = dist,
                        ["mode"] = modo,
                        ["extentsBefore"] = antes,
                        ["extentsAfter"] = Extension(s)
                    };
                    tr.Commit();
                    return r;
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD no pudo extender la superficie (" + ex.ErrorStatus + "): " + ex.Message
                        + ". No se cambió nada. Causas típicas: la arista es de una superficie cerrada o no se puede prolongar esa distancia.");
                }
                catch (SysException) { tr.Abort(); throw; }
            }
        }

        /// <summary>params: surface1, pick1 [x,y,z], surface2, pick2 [x,y,z] (los puntos eligen de qué lado de cada superficie va el empalme),
        /// radius (> 0), [trim=both | none | first | second] (qué superficies se recortan contra el empalme), [direction=[0,0,1]] (dirección de
        /// la vista con que se proyectan los puntos), [associative=false]. Crea una superficie nueva con el empalme.</summary>
        public static JsonObject FilletSurfaces(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var id1 = Id(doc, pars["surface1"], "surface1");
            var id2 = Id(doc, pars["surface2"], "surface2");
            if (id1 == id2) throw new ArgumentException("surface1 y surface2 tienen que ser superficies distintas.");
            var p1 = Punto(pars["pick1"], "pick1"); var p2 = Punto(pars["pick2"], "pick2");
            double radio = NumPos(pars, "radius", "el radio del empalme");
            string trim = (pars["trim"]?.GetValue<string>() ?? "both").ToLowerInvariant();
            FilletTrimMode modo;
            switch (trim)
            {
                case "both": modo = FilletTrimMode.TrimBoth; break;
                case "none": modo = FilletTrimMode.TrimNone; break;
                case "first": modo = FilletTrimMode.TrimStart; break;
                case "second": modo = FilletTrimMode.TrimSecond; break;
                default: throw new ArgumentException("trim '" + trim + "' no existe: both, none, first o second.");
            }
            var dir = pars["direction"] != null ? Vector(pars["direction"], "direction") : Vector3d.ZAxis;
            bool asoc = pars["associative"] != null && pars["associative"].GetValue<bool>();
            using (var tr = db.TransactionManager.StartTransaction())
            {
                try
                {
                    Superficie(tr, id1, "surface1", false);
                    Superficie(tr, id2, "surface2", false);
                    var nuevo = DbSurface.CreateFilletSurface(id1, p1, id2, p2, radio, modo, dir, asoc);
                    if (nuevo.IsNull) throw new InvalidOperationException("AutoCAD no devolvió la superficie del empalme.");
                    var s = (Entity)tr.GetObject(nuevo, OpenMode.ForRead);
                    var r = new JsonObject
                    {
                        ["handle"] = s.Handle.ToString(),
                        ["type"] = s.GetType().Name,
                        ["radius"] = radio,
                        ["trim"] = trim,
                        ["extents"] = Extension(s)
                    };
                    tr.Commit();
                    return r;
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    throw new InvalidOperationException("AutoCAD no pudo empalmar las superficies (" + ex.ErrorStatus + "): " + ex.Message
                        + ". No se creó nada. Causas típicas: las superficies son paralelas o no se acercan, o el radio no cabe entre ellas.");
                }
                catch (SysException) { tr.Abort(); throw; }
            }
        }
    }
}
