using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class OffsetEntityCommand
    {
        /// <summary>
        /// Crea una curva paralela a otra (típico para trazar una guarnición
        /// paralela al eje de una calle).
        /// params: handle (de una Line, Arc, Circle o Polyline), distance,
        /// [sideX, sideY] (punto de referencia para elegir de qué lado queda
        /// el offset cuando hay ambigüedad; si no se pasa, agarra el primer
        /// resultado que devuelve la API)
        /// </summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string handleStr = pars["handle"].GetValue<string>();
            double distance = pars["distance"].GetValue<double>();
            // ContainsKey no alcanza: el cliente Python manda la clave igual con
            // valor JSON null cuando el parámetro opcional no se pasa.
            bool hasSide = pars["sideX"] != null && pars["sideY"] != null;
            double sideX = hasSide ? pars["sideX"].GetValue<double>() : 0;
            double sideY = hasSide ? pars["sideY"].GetValue<double>() : 0;

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var srcId = HandleHelper.GetObjectId(db, handleStr);
                var src = tr.GetObject(srcId, OpenMode.ForRead) as Curve;
                if (src == null)
                    throw new InvalidOperationException(
                        "offset_entity solo soporta Line, Arc, Circle o Polyline.");

                var results = src.GetOffsetCurves(distance);
                if (results.Count == 0)
                    throw new InvalidOperationException("No se pudo calcular el offset (¿distancia inválida?).");

                Entity chosen = (Entity)results[0];
                if (hasSide && results.Count > 1)
                {
                    var sidePoint = new Point3d(sideX, sideY, 0);
                    double bestDist = double.MaxValue;
                    foreach (DBObject obj in results)
                    {
                        var curve = (Curve)obj;
                        var closest = curve.GetClosestPointTo(sidePoint, false);
                        double d = closest.DistanceTo(sidePoint);
                        if (d < bestDist) { bestDist = d; chosen = curve; }
                    }
                }

                var btr = (BlockTableRecord)tr.GetObject(src.BlockId, OpenMode.ForWrite);
                chosen.Layer = src.Layer;
                btr.AppendEntity(chosen);
                tr.AddNewlyCreatedDBObject(chosen, true);

                // Las curvas de offset que no elegimos son objetos transitorios,
                // nunca quedaron en la base de datos: hay que liberarlas a mano.
                foreach (DBObject obj in results)
                {
                    if (!ReferenceEquals(obj, chosen))
                        obj.Dispose();
                }

                tr.Commit();
                return new JsonObject { ["handle"] = chosen.Handle.ToString() };
            }
        }
    }
}
