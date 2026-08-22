using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class MirrorEntityCommand
    {
        /// <summary>
        /// Espejo geométrico real (mismo criterio que MIRRTEXT=1: el texto
        /// también se refleja, no queda "legible" — si hace falta un rótulo
        /// legible del otro lado, se vuelve a escribir con create_text en vez
        /// de espejar el existente).
        /// params: handle, x1, y1, x2, y2 (eje de simetría), [copy=true]
        /// </summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string handleStr = pars["handle"].GetValue<string>();
            double x1 = pars["x1"].GetValue<double>();
            double y1 = pars["y1"].GetValue<double>();
            double x2 = pars["x2"].GetValue<double>();
            double y2 = pars["y2"].GetValue<double>();
            bool copy = pars["copy"] == null || pars["copy"].GetValue<bool>();

            var axis = new Line3d(new Point3d(x1, y1, 0), new Point3d(x2, y2, 0));
            var mirror = Matrix3d.Mirroring(axis);

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var srcId = HandleHelper.GetObjectId(db, handleStr);

                if (copy)
                {
                    var src = (Entity)tr.GetObject(srcId, OpenMode.ForRead);
                    var clone = (Entity)src.Clone();
                    clone.TransformBy(mirror);
                    var btr = (BlockTableRecord)tr.GetObject(src.BlockId, OpenMode.ForWrite);
                    btr.AppendEntity(clone);
                    tr.AddNewlyCreatedDBObject(clone, true);
                    tr.Commit();
                    return new JsonObject { ["handle"] = clone.Handle.ToString() };
                }

                var ent = (Entity)tr.GetObject(srcId, OpenMode.ForWrite);
                ent.TransformBy(mirror);
                tr.Commit();
                return new JsonObject { ["handle"] = handleStr };
            }
        }
    }
}
