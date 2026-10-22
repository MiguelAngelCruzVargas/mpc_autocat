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
    /// Modelado de sólidos a partir de geometría YA dibujada (EXTRUDE, REVOLVE, SWEEP, LOFT): perfiles
    /// que están en el dibujo, por handle. Complementa a extrude_profile (que dibuja el contorno él mismo
    /// desde puntos) y a create_object('Solid3d', 'CreateBox'...) (primitivas).
    ///
    /// Los perfiles tienen que ser CERRADOS (círculo, polilínea cerrada, elipse, spline cerrada, región):
    /// uno abierto produciría una superficie, no un sólido, y eso queda fuera de esta herramienta. Cada
    /// operación va en una transacción: si algo falla no queda un sólido vacío ni se borra el perfil.
    /// </summary>
    public static class Solid3dOpsCommands
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

        private static Vector3d Vector(JsonNode n, string cual)
        {
            var p = Punto(n, cual);
            var v = new Vector3d(p.X, p.Y, p.Z);
            if (v.Length < 1e-12) throw new ArgumentException("'" + cual + "' no puede ser un vector nulo.");
            return v;
        }

        private static double Num(JsonObject pars, string clave, double porDefecto)
        {
            if (pars[clave] == null) return porDefecto;
            double v = pars[clave].GetValue<double>();
            if (double.IsNaN(v) || double.IsInfinity(v)) throw new ArgumentException("'" + clave + "' tiene que ser un número finito.");
            return v;
        }

        /// <summary>El perfil: entidad cerrada del dibujo (curva cerrada, región o superficie plana).</summary>
        private static Entity Perfil(Transaction tr, ObjectId id, string cual)
        {
            var e = tr.GetObject(id, OpenMode.ForRead) as Entity;
            if (e == null) throw new ArgumentException("'" + cual + "' no es una entidad de dibujo.");
            if (e is Curve c)
            {
                if (!c.Closed)
                    throw new ArgumentException("'" + cual + "' (" + e.GetType().Name + ") es una curva ABIERTA: para un sólido el perfil tiene que estar cerrado " +
                        "(polilínea cerrada, círculo, elipse, spline cerrada).");
            }
            else if (!(e is Region) && !(e is PlaneSurface))
                throw new ArgumentException("'" + cual + "' (" + e.GetType().Name + ") no sirve de perfil: usá una curva cerrada, una región o una superficie plana.");
            return e;
        }

        private static JsonObject Cerrar(Transaction tr, Solid3d s, Entity molde, JsonObject pars, List<ObjectId> aBorrar)
        {
            var db = molde.Database;
            string capa = pars["layer"]?.GetValue<string>();
            if (!string.IsNullOrEmpty(capa))
            {
                var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
                if (!lt.Has(capa)) throw new ArgumentException("No hay una capa llamada '" + capa + "'.");
                s.Layer = capa;
            }
            else s.SetPropertiesFrom(molde);
            var espacio = (BlockTableRecord)tr.GetObject(molde.BlockId, OpenMode.ForWrite);
            espacio.AppendEntity(s);
            tr.AddNewlyCreatedDBObject(s, true);
            foreach (var id in aBorrar)
            {
                var o = tr.GetObject(id, OpenMode.ForWrite);
                if (!o.IsErased) o.Erase(true);
            }
            var salida = new JsonObject { ["handle"] = s.Handle.ToString() };
            try { salida["volume"] = s.MassProperties.Volume; } catch (SysException) { salida["volume"] = null; }
            return salida;
        }

        // ============================================================ EXTRUDE

        /// <summary>params: profile (handle), height (con signo, a lo largo de la normal del perfil) o direction [x,y,z]
        /// (vector; su largo es la altura), [taper_deg=0], [delete_profile=false], [layer].</summary>
        public static JsonObject Extrude(Document doc, JsonObject pars)
        {
            var id = Id(doc, pars["profile"], "profile");
            bool borrar = pars["delete_profile"]?.GetValue<bool>() ?? false;
            double taper = Num(pars, "taper_deg", 0.0) * Math.PI / 180.0;
            bool tieneAltura = pars["height"] != null, tieneDir = pars["direction"] != null;
            if (tieneAltura == tieneDir) throw new ArgumentException("Pasá 'height' o 'direction', uno de los dos.");
            double altura = tieneAltura ? Num(pars, "height", 0.0) : 0.0;
            if (tieneAltura && Math.Abs(altura) < 1e-9) throw new ArgumentException("'height' no puede ser 0.");
            Vector3d? dir = tieneDir ? Vector(pars["direction"], "direction") : (Vector3d?)null;

            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                Solid3d s = null;
                try
                {
                    var perfil = Perfil(tr, id, "profile");
                    Vector3d d;
                    if (dir.HasValue) d = dir.Value;
                    else
                    {
                        Vector3d normal;
                        if (perfil is Curve c)
                        {
                            Plane pl = c.GetPlane();
                            normal = pl.Normal;
                        }
                        else if (perfil is Region r) normal = r.Normal;
                        else normal = Vector3d.ZAxis;
                        d = normal.GetNormal() * altura;
                    }
                    var b = new SweepOptionsBuilder { DraftAngle = taper };
                    s = new Solid3d();
                    s.CreateExtrudedSolid(perfil, d, b.ToSweepOptions());
                    var r2 = Cerrar(tr, s, perfil, pars, borrar ? new List<ObjectId> { id } : new List<ObjectId>());
                    tr.Commit();
                    return r2;
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    if (s != null && !s.IsDisposed && s.ObjectId.IsNull) s.Dispose();
                    throw new InvalidOperationException("AutoCAD no pudo extruir el perfil (" + ex.ErrorStatus + "): " + ex.Message + ". No se creó nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    if (s != null && !s.IsDisposed && s.ObjectId.IsNull) s.Dispose();
                    throw;
                }
            }
        }

        // ============================================================ REVOLVE

        /// <summary>params: profile, axis_point [x,y,z], axis_dir [x,y,z], [angle_deg=360], [start_angle_deg=0],
        /// [twist_deg=0], [draft_deg=0], [close_to_axis=false], [delete_profile=false], [layer].</summary>
        public static JsonObject Revolve(Document doc, JsonObject pars)
        {
            var id = Id(doc, pars["profile"], "profile");
            var ejeP = Punto(pars["axis_point"], "axis_point");
            var ejeD = Vector(pars["axis_dir"], "axis_dir");
            double ang = Num(pars, "angle_deg", 360.0);
            if (Math.Abs(ang) < 1e-9 || Math.Abs(ang) > 360.0 + 1e-9) throw new ArgumentException("'angle_deg' va de -360 a 360 y no puede ser 0.");
            double ini = Num(pars, "start_angle_deg", 0.0) * Math.PI / 180.0;
            bool borrar = pars["delete_profile"]?.GetValue<bool>() ?? false;
            bool cerrarEje = pars["close_to_axis"]?.GetValue<bool>() ?? false;

            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                Solid3d s = null;
                try
                {
                    var perfil = Perfil(tr, id, "profile");
                    var b = new RevolveOptionsBuilder
                    {
                        CloseToAxis = cerrarEje,
                        TwistAngle = Num(pars, "twist_deg", 0.0) * Math.PI / 180.0,
                        DraftAngle = Num(pars, "draft_deg", 0.0) * Math.PI / 180.0
                    };
                    s = new Solid3d();
                    s.CreateRevolvedSolid(perfil, ejeP, ejeD, ang * Math.PI / 180.0, ini, b.ToRevolveOptions());
                    var r = Cerrar(tr, s, perfil, pars, borrar ? new List<ObjectId> { id } : new List<ObjectId>());
                    tr.Commit();
                    return r;
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    if (s != null && !s.IsDisposed && s.ObjectId.IsNull) s.Dispose();
                    throw new InvalidOperationException("AutoCAD no pudo revolucionar el perfil (" + ex.ErrorStatus + "): " + ex.Message +
                        ". ¿El perfil cruza el eje? No se creó nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    if (s != null && !s.IsDisposed && s.ObjectId.IsNull) s.Dispose();
                    throw;
                }
            }
        }

        // ============================================================ SWEEP

        /// <summary>params: profile, path (handle de una curva), [twist_deg=0], [scale=1], [align=true] (el perfil se
        /// orienta perpendicular a la trayectoria), [bank=false], [delete_profile=false], [delete_path=false], [layer].</summary>
        public static JsonObject Sweep(Document doc, JsonObject pars)
        {
            var id = Id(doc, pars["profile"], "profile");
            var idPath = Id(doc, pars["path"], "path");
            if (id == idPath) throw new ArgumentException("El perfil y la trayectoria no pueden ser la misma entidad.");
            bool alinear = pars["align"]?.GetValue<bool>() ?? true;
            double escala = Num(pars, "scale", 1.0);
            if (escala <= 0) throw new ArgumentException("'scale' tiene que ser mayor que cero.");
            var aBorrar = new List<ObjectId>();
            if (pars["delete_profile"]?.GetValue<bool>() ?? false) aBorrar.Add(id);
            if (pars["delete_path"]?.GetValue<bool>() ?? false) aBorrar.Add(idPath);

            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                Solid3d s = null;
                try
                {
                    var perfil = Perfil(tr, id, "profile");
                    var path = tr.GetObject(idPath, OpenMode.ForRead) as Curve;
                    if (path == null) throw new ArgumentException("'path' tiene que ser una línea, arco, polilínea o spline.");
                    var b = new SweepOptionsBuilder
                    {
                        Align = alinear ? SweepOptionsAlignOption.AlignSweepEntityToPath : SweepOptionsAlignOption.NoAlignment,
                        Bank = pars["bank"]?.GetValue<bool>() ?? false,
                        TwistAngle = Num(pars, "twist_deg", 0.0) * Math.PI / 180.0,
                        ScaleFactor = escala
                    };
                    s = new Solid3d();
                    s.CreateSweptSolid(perfil, path, b.ToSweepOptions());
                    var r = Cerrar(tr, s, perfil, pars, aBorrar);
                    tr.Commit();
                    return r;
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    if (s != null && !s.IsDisposed && s.ObjectId.IsNull) s.Dispose();
                    throw new InvalidOperationException("AutoCAD no pudo barrer el perfil (" + ex.ErrorStatus + "): " + ex.Message + ". No se creó nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    if (s != null && !s.IsDisposed && s.ObjectId.IsNull) s.Dispose();
                    throw;
                }
            }
        }

        // ============================================================ LOFT

        /// <summary>params: sections[] (2 o más handles de perfiles cerrados, EN ORDEN), [guides[]], [path], [ruled=false],
        /// [closed=false] (une el último con el primero), [delete_sources=false], [layer].</summary>
        public static JsonObject Loft(Document doc, JsonObject pars)
        {
            var secciones = (pars["sections"] as JsonArray ?? throw new ArgumentException("Falta 'sections' (2 o más handles)."))
                .Select(n => HandleHelper.GetObjectId(doc.Database, n.GetValue<string>())).ToList();
            if (secciones.Count < 2) throw new ArgumentException("Un loft necesita al menos 2 secciones.");
            if (secciones.Count > 50) throw new ArgumentException("Máximo 50 secciones.");
            if (secciones.Distinct().Count() != secciones.Count) throw new ArgumentException("Hay una sección repetida.");
            var guias = pars["guides"] is JsonArray ga
                ? ga.Select(n => HandleHelper.GetObjectId(doc.Database, n.GetValue<string>())).ToList() : new List<ObjectId>();
            ObjectId idPath = pars["path"] != null ? Id(doc, pars["path"], "path") : ObjectId.Null;
            if (guias.Count > 0 && !idPath.IsNull) throw new ArgumentException("Un loft lleva guías O trayectoria, no las dos.");
            bool borrar = pars["delete_sources"]?.GetValue<bool>() ?? false;

            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                Solid3d s = null;
                try
                {
                    var cortes = secciones.Select(i => Perfil(tr, i, "sections")).ToArray();
                    var guiasE = guias.Select(i => (Entity)tr.GetObject(i, OpenMode.ForRead)).ToArray();
                    Entity pathE = idPath.IsNull ? null : (Entity)tr.GetObject(idPath, OpenMode.ForRead);
                    var b = new LoftOptionsBuilder
                    {
                        Ruled = pars["ruled"]?.GetValue<bool>() ?? false,
                        Closed = pars["closed"]?.GetValue<bool>() ?? false
                    };
                    s = new Solid3d();
                    s.CreateLoftedSolid(cortes, guiasE, pathE, b.ToLoftOptions());
                    var aBorrar = new List<ObjectId>();
                    if (borrar) { aBorrar.AddRange(secciones); aBorrar.AddRange(guias); if (!idPath.IsNull) aBorrar.Add(idPath); }
                    var r = Cerrar(tr, s, cortes[0], pars, aBorrar);
                    tr.Commit();
                    return r;
                }
                catch (AcException ex)
                {
                    tr.Abort();
                    if (s != null && !s.IsDisposed && s.ObjectId.IsNull) s.Dispose();
                    throw new InvalidOperationException("AutoCAD no pudo hacer el loft (" + ex.ErrorStatus + "): " + ex.Message +
                        ". Las secciones tienen que ser curvas cerradas, del mismo tipo y en planos distintos. No se creó nada.");
                }
                catch (SysException)
                {
                    tr.Abort();
                    if (s != null && !s.IsDisposed && s.ObjectId.IsNull) s.Dispose();
                    throw;
                }
            }
        }
    }
}
