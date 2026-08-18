using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class CreateArcCommand
    {
        /// <summary>params: x, y, [z=0], radius, startAngleDeg, endAngleDeg, [layer]</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            double x = pars["x"].GetValue<double>();
            double y = pars["y"].GetValue<double>();
            double z = pars["z"] != null ? pars["z"].GetValue<double>() : 0.0;
            double radius = pars["radius"].GetValue<double>();
            double startDeg = pars["startAngleDeg"].GetValue<double>();
            double endDeg = pars["endAngleDeg"].GetValue<double>();

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var btr = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);

                var arc = new Arc(new Point3d(x, y, z), radius,
                    startDeg * System.Math.PI / 180.0, endDeg * System.Math.PI / 180.0);
                EntityHelper.ApplyCommon(db, tr, arc, pars);

                btr.AppendEntity(arc);
                tr.AddNewlyCreatedDBObject(arc, true);
                tr.Commit();

                return new JsonObject { ["handle"] = arc.Handle.ToString() };
            }
        }
    }
}
