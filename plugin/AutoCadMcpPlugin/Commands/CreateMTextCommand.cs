using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class CreateMTextCommand
    {
        /// <summary>params: text, x, y, [z=0], height, width, [layer]</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string content = pars["text"].GetValue<string>();
            double x = pars["x"].GetValue<double>();
            double y = pars["y"].GetValue<double>();
            double z = pars["z"] != null ? pars["z"].GetValue<double>() : 0.0;
            double height = pars["height"].GetValue<double>();
            double width = pars["width"] != null ? pars["width"].GetValue<double>() : 0.0;

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var btr = SpaceHelper.Current(db, tr);

                var mtext = new MText
                {
                    Contents = content,
                    Location = new Point3d(x, y, z),
                    TextHeight = height,
                    Width = width
                };
                StyleHelper.ApplyTextStyle(db, tr, mtext, pars);
                EntityHelper.ApplyCommon(db, tr, mtext, pars);

                btr.AppendEntity(mtext);
                tr.AddNewlyCreatedDBObject(mtext, true);
                tr.Commit();

                return new JsonObject { ["handle"] = mtext.Handle.ToString() };
            }
        }
    }
}
