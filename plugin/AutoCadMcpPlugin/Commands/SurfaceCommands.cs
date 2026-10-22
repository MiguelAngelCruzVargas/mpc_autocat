using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using AcException = Autodesk.AutoCAD.Runtime.Exception;
using SysException = System.Exception;
using DbSurface = Autodesk.AutoCAD.DatabaseServices.Surface;
using DbNurbSurface = Autodesk.AutoCAD.DatabaseServices.NurbSurface;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Superficies y mallas por la API administrada: PLANESURF, EXTRUDE/REVOLVE/SWEEP/LOFT con perfiles ABIERTOS (dan superficie,
    /// no sólido), SURFOFFSET, superficie NURBS desde una cuadrícula de puntos (terreno) y malla desde vértices y caras.
    ///
    /// Precondiciones leídas con tools/precondiciones.py: las clases de superficie (ExtrudedSurface, RevolvedSurface, SweptSurface,
    /// LoftedSurface) tienen constructor vacío y un método Create* de INSTANCIA que le da forma: se la da ANTES de agregarla al dibujo
    /// (como Solid3d). Los perfiles que reciben pueden estar en la base de datos: se abren en lectura. Todo en una transacción, validado
    /// entero antes; si algo falla no queda una superficie vacía.
    /// </summary>
    public static class SurfaceCommands
    {
        private static ObjectId Id(Document doc, JsonNode n, string cual)
        {
            string h = n?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(h)) throw new ArgumentException("Falta '" + cual + "' (un handle).");
            return HandleHelper.GetObjectId(doc.Database, h);
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

        private static double Num(JsonObject pars, string clave, double porDefecto)
        {
            if (pars[clave] == null) return porDefecto;
            double v = pars[clave].GetValue<double>();
            if (double.IsNaN(v) || double.IsInfinity(v)) throw new ArgumentException("'" + clave + "' tiene que ser un número finito.");
            return v;
        }

        private static Entity Perfil(Transaction tr, ObjectId id, string cual)
        {
            var e = tr.GetObject(id, OpenMode.ForRead) as Entity;
            if (e == null) throw new ArgumentException("'" + cual + "' no es una entidad de dibujo.");
            if (!(e is Curve) && !(e is Region) && !(e is PlaneSurface))
                throw new ArgumentException("'" + cual + "' (" + e.GetType().Name + ") no sirve de perfil: usá una curva, una región o una superficie plana.");
            return e;
        }

        private static JsonObject Agregar(Transaction tr, Database db, Entity nueva, Entity molde, JsonObject pars, List<ObjectId> aBorrar)
        {
            string capa = pars["layer"]?.GetValue<string>();
            if (!string.IsNullOrEmpty(capa))
            {
                var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
                if (!lt.Has(capa)) throw new ArgumentException("No hay una capa llamada '" + capa + "'.");
                nueva.Layer = capa;
            }
            else if (molde != null) nueva.SetPropertiesFrom(molde);
            var espacio = (BlockTableRecord)tr.GetObject(db.CurrentSpaceId, OpenMode.ForWrite);
            espacio.AppendEntity(nueva);
            tr.AddNewlyCreatedDBObject(nueva, true);
            foreach (var id in aBorrar)
            {
                var o = tr.GetObject(id, OpenMode.ForWrite, false, true);
                if (!o.IsErased) o.Erase(true);
            }
            return new JsonObject { ["handle"] = nueva.Handle.ToString(), ["type"] = nueva.GetType().Name };
        }

        private static void Liberar(Entity e)
        {
            try { if (e != null && !e.IsDisposed && e.ObjectId.IsNull) e.Dispose(); } catch (SysException) { }
        }

        // ============================================================ create_surface

        /// <summary>params: kind (plane | extrude | revolve | sweep | loft), y según el tipo:
        ///   plane:   profile (curva cerrada o región)
        ///   extrude: profile, height | direction [x,y,z], [taper_deg]
        ///   revolve: profile, axis_point, axis_dir, [angle_deg=360], [start_angle_deg=0]
        ///   sweep:   profile, path, [twist_deg], [scale]
        ///   loft:    sections[] (2+), [guides[]] | [path], [ruled], [closed]
        /// [delete_sources=false], [layer]. El perfil puede estar ABIERTO (salvo plane): da una superficie, no un sólido.</summary>
        public static JsonObject Create(Document doc, JsonObject pars)
        {
            string kind = (pars["kind"]?.GetValue<string>() ?? "").ToLowerInvariant();
            var db = doc.Database;
            bool borrar = pars["delete_sources"]?.GetValue<bool>() ?? false;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                Entity s = null;
                try
                {
                    var aBorrar = new List<ObjectId>();
                    Entity molde;
                    switch (kind)
                    {
                        case "plane":
                        {
                            var id = Id(doc, pars["profile"], "profile");
                            molde = Perfil(tr, id, "profile");
                            if (molde is Curve cp && !cp.Closed) throw new ArgumentException("Una superficie plana necesita un perfil CERRADO.");
                            s = DbSurface.CreateFrom(molde);
                            if (borrar) aBorrar.Add(id);
                            break;
                        }
                        case "extrude":
                        {
                            var id = Id(doc, pars["profile"], "profile");
                            molde = Perfil(tr, id, "profile");
                            bool tieneAltura = pars["height"] != null, tieneDir = pars["direction"] != null;
                            if (tieneAltura == tieneDir) throw new ArgumentException("Pasá 'height' o 'direction', uno de los dos.");
                            Vector3d d;
                            if (tieneDir)
                            {
                                var p = Punto(pars["direction"], "direction");
                                d = new Vector3d(p.X, p.Y, p.Z);
                                if (d.Length < 1e-12) throw new ArgumentException("'direction' no puede ser un vector nulo.");
                            }
                            else
                            {
                                double h = Num(pars, "height", 0);
                                if (Math.Abs(h) < 1e-9) throw new ArgumentException("'height' no puede ser 0.");
                                Vector3d normal = Vector3d.ZAxis;
                                if (molde is Curve cc) { try { normal = cc.GetPlane().Normal; } catch (SysException) { } }
                                else if (molde is Region rg) normal = rg.Normal;
                                d = normal.GetNormal() * h;
                            }
                            var b = new SweepOptionsBuilder { DraftAngle = Num(pars, "taper_deg", 0) * Math.PI / 180.0 };
                            var e = new ExtrudedSurface();
                            s = e;
                            e.CreateExtrudedSurface(molde, d, b.ToSweepOptions());
                            if (borrar) aBorrar.Add(id);
                            break;
                        }
                        case "revolve":
                        {
                            var id = Id(doc, pars["profile"], "profile");
                            molde = Perfil(tr, id, "profile");
                            var ejeP = Punto(pars["axis_point"], "axis_point");
                            var pd = Punto(pars["axis_dir"], "axis_dir");
                            var ejeD = new Vector3d(pd.X, pd.Y, pd.Z);
                            if (ejeD.Length < 1e-12) throw new ArgumentException("'axis_dir' no puede ser un vector nulo.");
                            double ang = Num(pars, "angle_deg", 360);
                            if (Math.Abs(ang) < 1e-9 || Math.Abs(ang) > 360.0 + 1e-9) throw new ArgumentException("'angle_deg' va de -360 a 360 y no puede ser 0.");
                            var e = new RevolvedSurface();
                            s = e;
                            e.CreateRevolvedSurface(molde, ejeP, ejeD, ang * Math.PI / 180.0, Num(pars, "start_angle_deg", 0) * Math.PI / 180.0,
                                                    new RevolveOptionsBuilder().ToRevolveOptions());
                            if (borrar) aBorrar.Add(id);
                            break;
                        }
                        case "sweep":
                        {
                            var id = Id(doc, pars["profile"], "profile");
                            var idPath = Id(doc, pars["path"], "path");
                            if (id == idPath) throw new ArgumentException("El perfil y la trayectoria no pueden ser la misma entidad.");
                            molde = Perfil(tr, id, "profile");
                            var path = tr.GetObject(idPath, OpenMode.ForRead) as Curve;
                            if (path == null) throw new ArgumentException("'path' tiene que ser una curva.");
                            double esc = Num(pars, "scale", 1.0);
                            if (esc <= 0) throw new ArgumentException("'scale' tiene que ser mayor que cero.");
                            var b = new SweepOptionsBuilder
                            {
                                Align = SweepOptionsAlignOption.AlignSweepEntityToPath,
                                TwistAngle = Num(pars, "twist_deg", 0) * Math.PI / 180.0, ScaleFactor = esc
                            };
                            var e = new SweptSurface();
                            s = e;
                            e.CreateSweptSurface(molde, path, b.ToSweepOptions());
                            if (borrar) { aBorrar.Add(id); }
                            break;
                        }
                        case "loft":
                        {
                            var ids = (pars["sections"] as JsonArray ?? throw new ArgumentException("Falta 'sections' (2 o más handles)."))
                                .Select(n => HandleHelper.GetObjectId(db, n.GetValue<string>())).ToList();
                            if (ids.Count < 2) throw new ArgumentException("Un loft necesita al menos 2 secciones.");
                            if (ids.Count > 50) throw new ArgumentException("Máximo 50 secciones.");
                            if (ids.Distinct().Count() != ids.Count) throw new ArgumentException("Hay una sección repetida.");
                            var guiasIds = pars["guides"] is JsonArray ga ? ga.Select(n => HandleHelper.GetObjectId(db, n.GetValue<string>())).ToList() : new List<ObjectId>();
                            ObjectId idPath = pars["path"] != null ? Id(doc, pars["path"], "path") : ObjectId.Null;
                            if (guiasIds.Count > 0 && !idPath.IsNull) throw new ArgumentException("Un loft lleva guías O trayectoria, no las dos.");
                            var cortes = ids.Select(i => Perfil(tr, i, "sections")).ToArray();
                            var guias = guiasIds.Select(i => (Entity)tr.GetObject(i, OpenMode.ForRead)).ToArray();
                            Entity pathE = idPath.IsNull ? null : (Entity)tr.GetObject(idPath, OpenMode.ForRead);
                            var b = new LoftOptionsBuilder { Ruled = pars["ruled"]?.GetValue<bool>() ?? false, Closed = pars["closed"]?.GetValue<bool>() ?? false };
                            var e = new LoftedSurface();
                            s = e;
                            e.CreateLoftedSurface(cortes, guias, pathE, b.ToLoftOptions());
                            molde = cortes[0];
                            if (borrar) { aBorrar.AddRange(ids); aBorrar.AddRange(guiasIds); if (!idPath.IsNull) aBorrar.Add(idPath); }
                            break;
                        }
                        default:
                            throw new ArgumentException("kind '" + kind + "' no existe: plane, extrude, revolve, sweep o loft.");
                    }
                    var r = Agregar(tr, db, s, molde, pars, aBorrar);
                    tr.Commit();
                    return r;
                }
                catch (AcException ex)
                {
                    tr.Abort(); Liberar(s);
                    throw new InvalidOperationException("AutoCAD no pudo crear la superficie (" + ex.ErrorStatus + "): " + ex.Message + ". No se creó nada.");
                }
                catch (SysException) { tr.Abort(); Liberar(s); throw; }
            }
        }

        // ============================================================ offset_surface

        /// <summary>params: handle (superficie), distance (con signo: hacia un lado o el otro), [layer]. SURFOFFSET: otra superficie paralela.</summary>
        public static JsonObject Offset(Document doc, JsonObject pars)
        {
            var id = Id(doc, pars["handle"], "handle");
            double d = Num(pars, "distance", 0);
            if (Math.Abs(d) < 1e-12) throw new ArgumentException("'distance' no puede ser 0.");
            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                Entity nueva = null;
                try
                {
                    var origen = tr.GetObject(id, OpenMode.ForRead) as Entity;
                    if (!(origen is DbSurface)) throw new ArgumentException("'handle' tiene que ser una superficie (no " + (origen?.GetType().Name ?? "nada") + ").");
                    nueva = DbSurface.CreateOffsetSurface(origen, d);
                    if (nueva == null) throw new InvalidOperationException("AutoCAD no devolvió la superficie desfasada.");
                    var r = Agregar(tr, db, nueva, origen, pars, new List<ObjectId>());
                    tr.Commit();
                    return r;
                }
                catch (AcException ex)
                {
                    tr.Abort(); Liberar(nueva);
                    throw new InvalidOperationException("AutoCAD rechazó el desfase (" + ex.ErrorStatus + "): " + ex.Message + ". No se creó nada.");
                }
                catch (SysException) { tr.Abort(); Liberar(nueva); throw; }
            }
        }

        // ============================================================ create_nurb_surface

        /// <summary>params: points (cuadrícula: lista de FILAS, cada una con la misma cantidad de puntos [x,y,z]), [degree=3], [layer].
        /// Superficie NURBS que pasa cerca de los puntos de control (terreno, cubiertas curvas, lonas): filas = dirección V, columnas = U.
        /// Nudos uniformes con extremos sujetos. Mínimo degree+1 puntos por lado.</summary>
        public static JsonObject NurbsDesdePuntos(Document doc, JsonObject pars)
        {
            var filas = pars["points"] as JsonArray;
            if (filas == null || filas.Count < 2) throw new ArgumentException("'points' es una lista de al menos 2 filas de puntos.");
            int v = filas.Count;
            int u = (filas[0] as JsonArray)?.Count ?? 0;
            if (u < 2) throw new ArgumentException("Cada fila necesita al menos 2 puntos.");
            if (v * u > 40000) throw new ArgumentException("Máximo 40000 puntos de control.");
            int grado = pars["degree"] != null ? pars["degree"].GetValue<int>() : 3;
            grado = Math.Min(grado, Math.Min(u, v) - 1);
            if (grado < 1) throw new ArgumentException("'degree' es al menos 1 (y menor que la cantidad de puntos por lado).");
            var pts = new Point3dCollection();
            for (int j = 0; j < v; j++)
            {
                var fila = filas[j] as JsonArray;
                if (fila == null || fila.Count != u) throw new ArgumentException("La fila " + j + " tiene " + (fila?.Count ?? 0) + " puntos y la primera " + u + ": tienen que ser todas iguales.");
                for (int i = 0; i < u; i++) pts.Add(Punto(fila[i], "points[" + j + "][" + i + "]"));
            }
            KnotCollection Nudos(int n)
            {
                var k = new KnotCollection();
                int total = n + grado + 1;
                for (int i = 0; i < total; i++)
                {
                    double val = i <= grado ? 0.0 : i >= n ? 1.0 : (double)(i - grado) / (n - grado);
                    k.Add(val);
                }
                return k;
            }
            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                DbNurbSurface ns = null;
                try
                {
                    ns = new DbNurbSurface(grado, grado, false, u, v, pts, new DoubleCollection(), Nudos(u), Nudos(v));
                    var r = Agregar(tr, db, ns, null, pars, new List<ObjectId>());
                    r["controlPoints"] = v * u; r["degree"] = grado;
                    tr.Commit();
                    return r;
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    if (ns != null) Liberar(ns);
                    throw new InvalidOperationException("AutoCAD rechazó la superficie NURBS (" + ex.ErrorStatus + "): " + ex.Message + ". No se creó nada.");
                }
                catch (SysException) { tr.Abort(); if (ns != null) Liberar(ns); throw; }
            }
        }

        // ============================================================ create_mesh_from_faces

        /// <summary>params: vertices [[x,y,z],...], faces [[i,j,k,(l,...)],...] (índices base 0; 3 o más por cara), [smooth=0] (0-4), [layer].
        /// Malla de subdivisión desde vértices y caras (un TIN de terreno, un casco, una pieza modelada punto a punto).</summary>
        public static JsonObject MallaDesdeCaras(Document doc, JsonObject pars)
        {
            var va = pars["vertices"] as JsonArray;
            var fa = pars["faces"] as JsonArray;
            if (va == null || va.Count < 3) throw new ArgumentException("'vertices' necesita al menos 3 puntos.");
            if (fa == null || fa.Count < 1) throw new ArgumentException("'faces' necesita al menos una cara.");
            if (va.Count > 100000 || fa.Count > 100000) throw new ArgumentException("Máximo 100000 vértices y 100000 caras.");
            int suave = pars["smooth"] != null ? pars["smooth"].GetValue<int>() : 0;
            if (suave < 0 || suave > 4) throw new ArgumentException("'smooth' va de 0 a 4.");
            var vertices = new Point3dCollection();
            for (int i = 0; i < va.Count; i++) vertices.Add(Punto(va[i], "vertices[" + i + "]"));
            var indices = new Int32Collection();
            for (int c = 0; c < fa.Count; c++)
            {
                var cara = fa[c] as JsonArray;
                if (cara == null || cara.Count < 3) throw new ArgumentException("La cara " + c + " necesita al menos 3 índices.");
                indices.Add(cara.Count);
                var vistos = new HashSet<int>();
                foreach (var n in cara)
                {
                    int ix = n.GetValue<int>();
                    if (ix < 0 || ix >= va.Count) throw new ArgumentException("La cara " + c + " usa el vértice " + ix + ", que no existe (hay " + va.Count + ").");
                    if (!vistos.Add(ix)) throw new ArgumentException("La cara " + c + " repite el vértice " + ix + ".");
                    indices.Add(ix);
                }
            }
            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                SubDMesh m = null;
                try
                {
                    m = new SubDMesh();
                    m.SetSubDMesh(vertices, indices, suave);
                    var r = Agregar(tr, db, m, null, pars, new List<ObjectId>());
                    r["vertices"] = m.NumberOfVertices; r["faces"] = m.NumberOfFaces; r["edges"] = m.NumberOfEdges;
                    tr.Commit();
                    return r;
                }
                catch (AcException ex)
                {
                    tr.Abort(); Liberar(m);
                    throw new InvalidOperationException("AutoCAD rechazó la malla (" + ex.ErrorStatus + "): " + ex.Message + ". No se creó nada.");
                }
                catch (SysException) { tr.Abort(); Liberar(m); throw; }
            }
        }
    }
}
