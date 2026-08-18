using System;
using System.Collections.Generic;
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
        /// el offset; si no se pasa, se usa el signo de 'distance')
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

                // GetOffsetCurves devuelve UN lado por llamada, el que marca el
                // signo de la distancia. Un círculo ofrece dos paralelas
                // válidas (adentro y afuera) y cada llamada da una sola: para
                // poder elegir por punto de referencia hay que pedir las dos.
                var candidates = new List<Curve>();
                var pools = new List<DBObjectCollection>();

                var positive = src.GetOffsetCurves(distance);
                pools.Add(positive);
                foreach (DBObject o in positive)
                    if (o is Curve c) candidates.Add(c);

                if (hasSide)
                {
                    var negative = src.GetOffsetCurves(-distance);
                    pools.Add(negative);
                    foreach (DBObject o in negative)
                        if (o is Curve c) candidates.Add(c);
                }

                if (candidates.Count == 0)
                {
                    DisposeAll(pools, null);
                    throw new InvalidOperationException(
                        "No se pudo calcular el offset (¿distancia inválida para esa curva?).");
                }

                Curve chosen = candidates[0];
                if (hasSide && candidates.Count > 1)
                {
                    var sidePoint = new Point3d(sideX, sideY, 0);
                    double bestDist = double.MaxValue;
                    foreach (var curve in candidates)
                    {
                        var closest = curve.GetClosestPointTo(sidePoint, false);
                        double d = closest.DistanceTo(sidePoint);
                        if (d < bestDist) { bestDist = d; chosen = curve; }
                    }
                }

                var btr = (BlockTableRecord)tr.GetObject(src.BlockId, OpenMode.ForWrite);
                chosen.Layer = src.Layer;
                btr.AppendEntity(chosen);
                tr.AddNewlyCreatedDBObject(chosen, true);

                // Las curvas que no elegimos son objetos transitorios que nunca
                // llegaron a la base de datos: hay que liberarlas a mano.
                DisposeAll(pools, chosen);

                tr.Commit();
                return new JsonObject { ["handle"] = chosen.Handle.ToString() };
            }
        }

        private static void DisposeAll(List<DBObjectCollection> pools, Entity keep)
        {
            foreach (var pool in pools)
            {
                foreach (DBObject obj in pool)
                {
                    if (!ReferenceEquals(obj, keep))
                    {
                        try { obj.Dispose(); } catch { /* ya liberado */ }
                    }
                }
            }
        }
    }
}
