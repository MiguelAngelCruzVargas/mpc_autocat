using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class CreateCircleCommand
    {
        /// <summary>params: x, y, [z=0], radius, [layer]</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            double x = pars["x"].GetValue<double>();
            double y = pars["y"].GetValue<double>();
            double z = pars["z"] != null ? pars["z"].GetValue<double>() : 0.0;
            double radius = pars["radius"].GetValue<double>();

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var btr = SpaceHelper.Current(db, tr);

                var circle = new Circle(new Point3d(x, y, z), Vector3d.ZAxis, radius);
                EntityHelper.ApplyCommon(db, tr, circle, pars);

                btr.AppendEntity(circle);
                tr.AddNewlyCreatedDBObject(circle, true);
                tr.Commit();

                return new JsonObject
                {
                    ["handle"] = circle.Handle.ToString(),
                    ["area"] = circle.Area
                };
            }
        }
    }
}
