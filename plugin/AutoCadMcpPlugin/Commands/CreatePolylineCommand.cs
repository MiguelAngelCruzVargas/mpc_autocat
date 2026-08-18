using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class CreatePolylineCommand
    {
        /// <summary>params: points ([[x,y], ...]), [closed], [layer]</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            var pointsArray = pars["points"].AsArray();
            bool closed = pars["closed"]?.GetValue<bool>() ?? false;

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var btr = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);

                var pl = new Polyline();
                int i = 0;
                foreach (var pt in pointsArray)
                {
                    var coords = pt.AsArray();
                    double x = coords[0].GetValue<double>();
                    double y = coords[1].GetValue<double>();
                    pl.AddVertexAt(i++, new Point2d(x, y), 0, 0, 0);
                }
                pl.Closed = closed;
                EntityHelper.ApplyCommon(db, tr, pl, pars);

                btr.AppendEntity(pl);
                tr.AddNewlyCreatedDBObject(pl, true);
                tr.Commit();

                return new JsonObject
                {
                    ["handle"] = pl.Handle.ToString(),
                    ["area"] = pl.Closed ? pl.Area : 0.0
                };
            }
        }
    }
}
