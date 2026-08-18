using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class CreateLineCommand
    {
        /// <summary>params: x1, y1, [z1], x2, y2, [z2], [layer]</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            double x1 = pars["x1"].GetValue<double>();
            double y1 = pars["y1"].GetValue<double>();
            double z1 = pars["z1"] != null ? pars["z1"].GetValue<double>() : 0.0;
            double x2 = pars["x2"].GetValue<double>();
            double y2 = pars["y2"].GetValue<double>();
            double z2 = pars["z2"] != null ? pars["z2"].GetValue<double>() : 0.0;

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var btr = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);

                var line = new Line(new Point3d(x1, y1, z1), new Point3d(x2, y2, z2));
                EntityHelper.ApplyCommon(db, tr, line, pars);

                btr.AppendEntity(line);
                tr.AddNewlyCreatedDBObject(line, true);
                tr.Commit();

                return new JsonObject
                {
                    ["handle"] = line.Handle.ToString(),
                    ["length"] = line.Length
                };
            }
        }
    }
}
