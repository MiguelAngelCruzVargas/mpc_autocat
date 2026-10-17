using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using BR = Autodesk.AutoCAD.BoundaryRepresentation;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Redondea aristas de un sólido 3D (el FILLETEDGE de AutoCAD, por API).
    ///
    /// Las aristas se eligen por geometría, no por índice: un índice cambia en
    /// cuanto el sólido se edita y nadie sabe de memoria cuál es cuál.
    /// params: handle (Solid3d), radius, [zPlanes] (solo aristas planas que
    /// yacen en alguna de esas cotas Z — p.ej. [0, 7.3] = canto de abajo y de
    /// arriba), [outerOnly=false] (solo aristas que tocan el perímetro de la
    /// caja del sólido: deja afuera los bordes de rebajes y agujeros).
    /// Sin zPlanes redondea todas las aristas que pasen el filtro outerOnly.
    /// </summary>
    public static class FilletSolidEdgesCommand
    {
        const double Tol = 1e-6;

        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string handle = pars["handle"].GetValue<string>();
            double radio = pars["radius"].GetValue<double>();
            bool soloExterior = pars["outerOnly"] != null
                && pars["outerOnly"].GetValue<bool>();

            if (radio <= 0)
                throw new ArgumentException("El radio del fillet debe ser > 0.");

            var zPlanos = new List<double>();
            if (pars["zPlanes"] != null)
                foreach (var z in pars["zPlanes"].AsArray())
                    zPlanos.Add(z.GetValue<double>());

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var solido = tr.GetObject(
                    HandleHelper.GetObjectId(db, handle), OpenMode.ForRead) as Solid3d;
                if (solido == null)
                    throw new InvalidOperationException(
                        $"'{handle}' no es un sólido 3D.");

                var ext = solido.GeometricExtents;
                var ids = new List<SubentityId>();
                int total = 0;
                string diag = null;

                // La B-Rep se arma desde el SUBENTITY PATH del sólido, no desde la
                // entidad: así cada arista conoce su SubentityId (de la otra forma
                // e.SubentityPath tira BoundaryRepresentation.Exception).
                var rutaSolido = new FullSubentityPath(
                    new ObjectId[] { solido.ObjectId },
                    new SubentityId(SubentityType.Null, IntPtr.Zero));
                using (var brep = new BR.Brep(rutaSolido))
                {
                    foreach (BR.Edge e in brep.Edges)
                    {
                        total++;
                        Point3d p1, p2;
                        SubentityId sid;
                        try
                        {
                            sid = e.SubentityPath.SubentId;
                        }
                        catch (System.Exception ex)
                        {
                            if (diag == null) diag = "SubentityPath: " + ex.Message;
                            continue;
                        }
                        try
                        {
                            p1 = e.Vertex1.Point;
                            p2 = e.Vertex2.Point;
                        }
                        catch (System.Exception)
                        {
                            // Sin vértices propios (círculo completo): se toman los
                            // extremos de su curva.
                            try
                            {
                                var c = e.Curve;
                                p1 = c.StartPoint;
                                p2 = c.EndPoint;
                            }
                            catch (System.Exception ex2)
                            {
                                if (diag == null) diag = "Vertex/Curve: " + ex2.Message;
                                continue;
                            }
                        }

                        if (zPlanos.Count > 0)
                        {
                            // Plana: ambos extremos a la misma Z, y esa Z pedida.
                            // (Un arco de esquina también cumple: sus dos
                            // extremos están a la misma altura.)
                            if (Math.Abs(p1.Z - p2.Z) > Tol) continue;
                            bool enPlano = false;
                            foreach (double z in zPlanos)
                                if (Math.Abs(p1.Z - z) < 1e-4) { enPlano = true; break; }
                            if (!enPlano) continue;
                        }

                        if (soloExterior && !TocaPerimetro(p1, p2, ext))
                            continue;

                        ids.Add(sid);
                    }
                }

                if (ids.Count == 0)
                    throw new InvalidOperationException(
                        $"Ninguna de las {total} aristas pasó el filtro; nada que redondear." +
                        (diag != null ? " Primer error de la B-Rep: " + diag : ""));

                solido.UpgradeOpen();
                var radios = new DoubleCollection();
                var cero1 = new DoubleCollection();
                var cero2 = new DoubleCollection();
                foreach (var _ in ids)
                {
                    radios.Add(radio);
                    cero1.Add(0.0);
                    cero2.Add(0.0);
                }

                try
                {
                    solido.FilletEdges(ids.ToArray(), radios, cero1, cero2);
                }
                catch (System.Exception ex)
                {
                    throw new InvalidOperationException(
                        $"AutoCAD no pudo redondear {ids.Count} aristas con radio " +
                        $"{radio}: {ex.Message}. Un radio mayor que lo que permite " +
                        "una pared o un radio de esquina vecino es la causa típica.");
                }

                var salida = new JsonObject
                {
                    ["handle"] = handle,
                    ["edgesFilleted"] = ids.Count,
                    ["edgesTotal"] = total,
                    ["radius"] = radio,
                    ["volume"] = solido.MassProperties.Volume
                };
                tr.Commit();
                return salida;
            }
        }

        // Una arista del perímetro exterior tiene algún extremo sobre la caja
        // del sólido en X o en Y. Los bordes de un rebaje interior quedan
        // adentro de la caja y no la tocan.
        static bool TocaPerimetro(Autodesk.AutoCAD.Geometry.Point3d a,
                                  Autodesk.AutoCAD.Geometry.Point3d b, Extents3d ext)
        {
            return Toca(a, ext) || Toca(b, ext);
        }

        static bool Toca(Autodesk.AutoCAD.Geometry.Point3d p, Extents3d ext)
        {
            return Math.Abs(p.X - ext.MinPoint.X) < 1e-4
                || Math.Abs(p.X - ext.MaxPoint.X) < 1e-4
                || Math.Abs(p.Y - ext.MinPoint.Y) < 1e-4
                || Math.Abs(p.Y - ext.MaxPoint.Y) < 1e-4;
        }
    }
}
