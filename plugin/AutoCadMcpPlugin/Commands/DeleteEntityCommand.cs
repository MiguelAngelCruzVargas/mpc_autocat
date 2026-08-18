using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    public static class DeleteEntityCommand
    {
        /// <summary>params: handle</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string handleStr = pars["handle"].GetValue<string>();
            var db = doc.Database;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var ent = (Entity)tr.GetObject(HandleHelper.GetObjectId(db, handleStr), OpenMode.ForWrite);
                ent.Erase();
                tr.Commit();
                return new JsonObject { ["status"] = "ok" };
            }
        }
    }
}
