using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    public static class ListEntitiesCommand
    {
        /// <summary>params: [type] (p.ej. "Line", "Polyline"), [limit] (default 200)</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string typeFilter = pars.ContainsKey("type") ? pars["type"]?.GetValue<string>() : null;
            int limit = pars["limit"] != null ? pars["limit"].GetValue<int>() : 200;

            var db = doc.Database;
            var arr = new JsonArray();

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var btr = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);

                int count = 0;
                foreach (ObjectId id in btr)
                {
                    if (count >= limit)
                        break;

                    var ent = (Entity)tr.GetObject(id, OpenMode.ForRead);
                    string typeName = ent.GetType().Name;

                    if (!string.IsNullOrEmpty(typeFilter) &&
                        !typeName.Equals(typeFilter, System.StringComparison.OrdinalIgnoreCase))
                        continue;

                    arr.Add(new JsonObject
                    {
                        ["handle"] = ent.Handle.ToString(),
                        ["type"] = typeName,
                        ["layer"] = ent.Layer
                    });
                    count++;
                }
                tr.Commit();
            }

            return new JsonObject { ["entities"] = arr, ["count"] = arr.Count };
        }
    }
}
