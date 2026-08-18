using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    public static class CalculateAreaCommand
    {
        /// <summary>params: handle (string hex, p.ej. "2A3"). Soporta Polyline cerrada, Region, Circle.</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string handleStr = pars["handle"].GetValue<string>();
            var db = doc.Database;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var ent = tr.GetObject(HandleHelper.GetObjectId(db, handleStr), OpenMode.ForRead);

                double area;
                switch (ent)
                {
                    case Polyline pl:
                        if (!pl.Closed)
                            throw new InvalidOperationException("La polilínea no está cerrada.");
                        area = pl.Area;
                        break;
                    case Region region:
                        area = region.Area;
                        break;
                    case Circle circle:
                        area = circle.Area;
                        break;
                    default:
                        throw new NotSupportedException(
                            $"Calcular área no soportado todavía para '{ent.GetType().Name}'.");
                }

                tr.Commit();
                return new JsonObject { ["area"] = area };
            }
        }
    }
}
