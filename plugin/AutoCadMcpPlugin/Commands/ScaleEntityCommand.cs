using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class ScaleEntityCommand
    {
        /// <summary>params: handle, baseX, baseY, factor</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string handleStr = pars["handle"].GetValue<string>();
            double baseX = pars["baseX"].GetValue<double>();
            double baseY = pars["baseY"].GetValue<double>();
            double factor = pars["factor"].GetValue<double>();

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var ent = (Entity)tr.GetObject(HandleHelper.GetObjectId(db, handleStr), OpenMode.ForWrite);
                var basePoint = new Point3d(baseX, baseY, 0);
                ent.TransformBy(Matrix3d.Scaling(factor, basePoint));
                tr.Commit();
                return new JsonObject { ["status"] = "ok" };
            }
        }
    }
}
