using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class RotateEntityCommand
    {
        /// <summary>params: handle, baseX, baseY, angleDeg</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string handleStr = pars["handle"].GetValue<string>();
            double baseX = pars["baseX"].GetValue<double>();
            double baseY = pars["baseY"].GetValue<double>();
            double angleDeg = pars["angleDeg"].GetValue<double>();

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var ent = (Entity)tr.GetObject(HandleHelper.GetObjectId(db, handleStr), OpenMode.ForWrite);
                var basePoint = new Point3d(baseX, baseY, 0);
                ent.TransformBy(Matrix3d.Rotation(angleDeg * System.Math.PI / 180.0, Vector3d.ZAxis, basePoint));
                tr.Commit();
                return new JsonObject { ["status"] = "ok" };
            }
        }
    }
}
