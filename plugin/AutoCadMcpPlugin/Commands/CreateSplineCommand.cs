using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Spline por puntos de ajuste: la curva pasa exactamente por los puntos
    /// dados. Es lo que hace falta para trazos que no son arcos de círculo —
    /// curvas de nivel, ejes de calle curvos, límites de terreno irregulares.
    /// params: points ([[x,y], ...], al menos 2), [closed=false], [layer],
    ///         [lineweight], [colorIndex]
    /// </summary>
    public static class CreateSplineCommand
    {
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            var pointsArray = pars["points"].AsArray();
            bool closed = pars["closed"]?.GetValue<bool>() ?? false;

            if (pointsArray.Count < 2)
                throw new ArgumentException("Un spline necesita al menos 2 puntos.");

            var fitPoints = new Point3dCollection();
            foreach (var pt in pointsArray)
            {
                var coords = pt.AsArray();
                double z = coords.Count > 2 ? coords[2].GetValue<double>() : 0.0;
                fitPoints.Add(new Point3d(
                    coords[0].GetValue<double>(), coords[1].GetValue<double>(), z));
            }

            // Spline.Closed es de solo lectura para un spline por puntos de
            // ajuste: se cierra repitiendo el primer punto al final, que es
            // exactamente lo que hace SPLINE con la opcion Cerrar.
            if (closed && fitPoints.Count > 2)
            {
                var first = fitPoints[0];
                var last = fitPoints[fitPoints.Count - 1];
                if (first.DistanceTo(last) > 1e-9)
                    fitPoints.Add(first);
            }

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var btr = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);

                // Tangentes nulas = que AutoCAD las calcule solo, que es lo que
                // uno espera al dar solo los puntos por donde pasa la curva.
                var spline = new Spline(fitPoints, Vector3d.ZAxis, Vector3d.ZAxis, 3, 0.0);
                EntityHelper.ApplyCommon(db, tr, spline, pars);

                btr.AppendEntity(spline);
                tr.AddNewlyCreatedDBObject(spline, true);

                var result = new JsonObject
                {
                    ["handle"] = spline.Handle.ToString(),
                    ["numFitPoints"] = spline.NumFitPoints,
                    ["closed"] = closed,
                    ["length"] = SafeLength(spline)
                };
                tr.Commit();
                return result;
            }
        }

        /// <summary>
        /// GetDistanceAtParameter puede tirar en splines degenerados; el largo
        /// es informativo, no vale romper la creación por eso.
        /// </summary>
        private static double SafeLength(Spline spline)
        {
            try
            {
                return spline.GetDistanceAtParameter(spline.EndParam)
                       - spline.GetDistanceAtParameter(spline.StartParam);
            }
            catch (System.Exception)
            {
                return 0.0;
            }
        }
    }
}
