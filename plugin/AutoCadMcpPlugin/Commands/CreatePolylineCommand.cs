using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class CreatePolylineCommand
    {
        /// <summary>
        /// params: points ([[x,y], ...]), [closed], [layer], [bulges]
        ///
        /// 'bulges' es opcional, un valor por vértice: la tangente de un cuarto
        /// del ángulo del arco hasta el vértice siguiente (0 = tramo recto). Es
        /// la única forma de trazar una polilínea con curvas —un eje de calle,
        /// una curva de nivel— en vez de una quebrada de muchos segmentos.
        /// </summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            var pointsArray = pars["points"].AsArray();
            bool closed = pars["closed"]?.GetValue<bool>() ?? false;
            var bulgesArray = pars["bulges"] as JsonArray;

            if (bulgesArray != null && bulgesArray.Count != pointsArray.Count)
                throw new System.ArgumentException(
                    $"'bulges' tiene {bulgesArray.Count} valores y 'points' " +
                    $"{pointsArray.Count}: tiene que haber uno por vértice.");

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var btr = SpaceHelper.Current(db, tr);

                var pl = new Polyline();
                int i = 0;
                foreach (var pt in pointsArray)
                {
                    var coords = pt.AsArray();
                    double x = coords[0].GetValue<double>();
                    double y = coords[1].GetValue<double>();
                    double bulge = bulgesArray != null
                        ? bulgesArray[i].GetValue<double>() : 0.0;
                    pl.AddVertexAt(i, new Point2d(x, y), bulge, 0, 0);
                    i++;
                }
                pl.Closed = closed;
                EntityHelper.ApplyCommon(db, tr, pl, pars);

                btr.AppendEntity(pl);
                tr.AddNewlyCreatedDBObject(pl, true);
                tr.Commit();

                return new JsonObject
                {
                    ["handle"] = pl.Handle.ToString(),
                    ["area"] = pl.Closed ? pl.Area : 0.0,
                    ["length"] = pl.Length
                };
            }
        }
    }
}
