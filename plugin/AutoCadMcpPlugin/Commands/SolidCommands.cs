using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Sólidos 3D por API, sin run_code: extruir un contorno y combinar sólidos.
    /// Es lo mínimo con que se modela una pieza (un teléfono, una carcasa, una
    /// pieza mecánica): contornos planos de líneas y arcos → extrusión →
    /// booleanas → fillet_solid_edges.
    /// </summary>
    public static class SolidCommands
    {
        /// <summary>
        /// Extruye un contorno CERRADO de líneas y arcos (polilínea con bulges,
        /// el equivalente directo de líneas+arcos unidos con JOIN).
        /// params: points ([[x,y],...]), [bulges] (uno por vértice, 0 = recto),
        /// z0 (cota de la base), height (> 0 hacia +Z, &lt; 0 hacia -Z),
        /// [taper=0] (grados), [layer], [colorIndex], [lineweight],
        /// [plane="xy"|"xz"]: con "xz" el contorno se interpreta como (x, z) —un alzado— y se
        /// extruye a lo largo de Y, ocupando de y0 a y0+|height| ([y0=0]); z0 debe ser 0.
        /// Devuelve handle, volume y los extents.
        /// </summary>
        public static JsonObject Extrude(Document doc, JsonObject pars)
        {
            var pts = pars["points"].AsArray();
            var bulges = pars["bulges"] as JsonArray;
            double z0 = pars["z0"]?.GetValue<double>() ?? 0.0;
            double height = pars["height"].GetValue<double>();
            double taper = pars["taper"]?.GetValue<double>() ?? 0.0;

            if (pts.Count < 2)
                throw new ArgumentException("El contorno necesita al menos 2 vértices.");
            if (bulges != null && bulges.Count != pts.Count)
                throw new ArgumentException(
                    $"'bulges' tiene {bulges.Count} valores y 'points' {pts.Count}: " +
                    "tiene que haber uno por vértice.");
            if (Math.Abs(height) < 1e-9)
                throw new ArgumentException("La altura de extrusión no puede ser 0.");

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var btr = SpaceHelper.Current(db, tr);

                var pl = new Polyline();
                for (int i = 0; i < pts.Count; i++)
                {
                    var c = pts[i].AsArray();
                    double b = bulges != null ? bulges[i].GetValue<double>() : 0.0;
                    pl.AddVertexAt(i, new Point2d(
                        c[0].GetValue<double>(), c[1].GetValue<double>()), b, 0, 0);
                }
                pl.Closed = true;
                pl.Elevation = z0;

                var curvas = new DBObjectCollection();
                curvas.Add(pl);
                var regiones = Region.CreateFromCurves(curvas);
                if (regiones.Count != 1)
                    throw new InvalidOperationException(
                        "El contorno no forma una región única (¿se cruza a sí mismo?).");

                var region = (Region)regiones[0];
                var solido = new Solid3d();
                try
                {
                    solido.Extrude(region, height, taper * Math.PI / 180.0);
                }
                catch (System.Exception ex)
                {
                    throw new InvalidOperationException(
                        "AutoCAD no pudo extruir el contorno: " + ex.Message);
                }
                finally
                {
                    region.Dispose();
                    pl.Dispose();
                }

                string plano = (pars["plane"]?.GetValue<string>() ?? "xy").ToLowerInvariant();
                if (plano == "xz")
                {
                    // (x, y, z) -> (x, -z, y): el contorno queda en el plano XZ y la extrusión corre
                    // a lo largo de -Y; luego se desplaza para que ocupe de y0 hacia +Y.
                    double y0 = pars["y0"]?.GetValue<double>() ?? 0.0;
                    solido.TransformBy(Matrix3d.Rotation(Math.PI / 2.0, Vector3d.XAxis, Point3d.Origin));
                    var e0 = solido.GeometricExtents;
                    solido.TransformBy(Matrix3d.Displacement(new Vector3d(0, y0 - e0.MinPoint.Y, 0)));
                }
                else if (plano != "xy")
                {
                    throw new ArgumentException($"plane '{plano}' no existe: xy o xz.");
                }

                EntityHelper.ApplyCommon(db, tr, solido, pars);
                btr.AppendEntity(solido);
                tr.AddNewlyCreatedDBObject(solido, true);

                var ext = solido.GeometricExtents;
                var salida = new JsonObject
                {
                    ["handle"] = solido.Handle.ToString(),
                    ["volume"] = solido.MassProperties.Volume,
                    ["z0"] = Math.Min(ext.MinPoint.Z, ext.MaxPoint.Z),
                    ["z1"] = Math.Max(ext.MinPoint.Z, ext.MaxPoint.Z)
                };
                tr.Commit();
                return salida;
            }
        }

        /// <summary>
        /// Booleana entre sólidos. params: target (handle), tools ([handles]),
        /// op ("subtract" | "union" | "intersect"), [deleteTools=true] (las
        /// herramientas se consumen igual que en SUBTRACT/UNION de AutoCAD).
        /// El target conserva su handle, capa y color.
        /// </summary>
        public static JsonObject Boolean(Document doc, JsonObject pars)
        {
            string op = (pars["op"]?.GetValue<string>() ?? "subtract").ToLowerInvariant();
            BooleanOperationType tipo;
            switch (op)
            {
                case "subtract": tipo = BooleanOperationType.BoolSubtract; break;
                case "union": tipo = BooleanOperationType.BoolUnite; break;
                case "intersect": tipo = BooleanOperationType.BoolIntersect; break;
                default:
                    throw new ArgumentException(
                        $"op '{op}' no existe: subtract, union o intersect.");
            }

            var herramientas = pars["tools"].AsArray();
            if (herramientas.Count == 0)
                throw new ArgumentException("Faltan 'tools': nada que combinar.");
            bool borrar = pars["deleteTools"]?.GetValue<bool>() ?? true;

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                string hT = pars["target"].GetValue<string>();
                var objetivo = tr.GetObject(
                    HandleHelper.GetObjectId(db, hT), OpenMode.ForWrite) as Solid3d;
                if (objetivo == null)
                    throw new InvalidOperationException($"'{hT}' no es un sólido 3D.");

                int aplicadas = 0;
                foreach (var h in herramientas)
                {
                    string hs = h.GetValue<string>();
                    var herr = tr.GetObject(
                        HandleHelper.GetObjectId(db, hs), OpenMode.ForWrite) as Solid3d;
                    if (herr == null)
                        throw new InvalidOperationException($"'{hs}' no es un sólido 3D.");
                    try
                    {
                        if (borrar)
                        {
                            // BooleanOperate consume la herramienta.
                            objetivo.BooleanOperation(tipo, herr);
                        }
                        else
                        {
                            using (var copia = (Solid3d)herr.Clone())
                                objetivo.BooleanOperation(tipo, copia);
                        }
                    }
                    catch (System.Exception ex)
                    {
                        throw new InvalidOperationException(
                            $"La booleana '{op}' falló con '{hs}': {ex.Message}. " +
                            "Si las piezas no se tocan, la resta/intersección no tiene qué hacer.");
                    }
                    aplicadas++;
                }

                var salida = new JsonObject
                {
                    ["handle"] = hT,
                    ["op"] = op,
                    ["applied"] = aplicadas,
                    ["volume"] = objetivo.MassProperties.Volume
                };
                tr.Commit();
                return salida;
            }
        }
    }
}
