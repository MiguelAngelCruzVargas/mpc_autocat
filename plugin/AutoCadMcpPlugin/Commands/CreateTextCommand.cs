using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class CreateTextCommand
    {
        /// <summary>params: text, x, y, [z=0], height, [layer], [rotationDeg=0]</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string content = pars["text"].GetValue<string>();
            double x = pars["x"].GetValue<double>();
            double y = pars["y"].GetValue<double>();
            double z = pars["z"] != null ? pars["z"].GetValue<double>() : 0.0;
            double height = pars["height"].GetValue<double>();
            double rotationDeg = pars["rotationDeg"] != null ? pars["rotationDeg"].GetValue<double>() : 0.0;

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var btr = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);

                var text = new DBText
                {
                    TextString = content,
                    Position = new Point3d(x, y, z),
                    Height = height,
                    Rotation = rotationDeg * System.Math.PI / 180.0
                };
                StyleHelper.ApplyTextStyle(db, tr, text, pars);
                EntityHelper.ApplyCommon(db, tr, text, pars);

                btr.AppendEntity(text);
                tr.AddNewlyCreatedDBObject(text, true);
                tr.Commit();

                return new JsonObject { ["handle"] = text.Handle.ToString() };
            }
        }
    }
}
