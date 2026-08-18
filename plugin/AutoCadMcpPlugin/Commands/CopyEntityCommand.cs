using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class CopyEntityCommand
    {
        /// <summary>params: handle, dx, dy, [dz=0]</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string handleStr = pars["handle"].GetValue<string>();
            double dx = pars["dx"].GetValue<double>();
            double dy = pars["dy"].GetValue<double>();
            double dz = pars["dz"] != null ? pars["dz"].GetValue<double>() : 0.0;

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var srcId = HandleHelper.GetObjectId(db, handleStr);
                var src = (Entity)tr.GetObject(srcId, OpenMode.ForRead);
                var clone = (Entity)src.Clone();
                clone.TransformBy(Matrix3d.Displacement(new Vector3d(dx, dy, dz)));

                var btr = (BlockTableRecord)tr.GetObject(src.BlockId, OpenMode.ForWrite);
                btr.AppendEntity(clone);
                tr.AddNewlyCreatedDBObject(clone, true);

                tr.Commit();
                return new JsonObject { ["handle"] = clone.Handle.ToString() };
            }
        }
    }
}
