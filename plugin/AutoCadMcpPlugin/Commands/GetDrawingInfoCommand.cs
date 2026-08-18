using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    public static class GetDrawingInfoCommand
    {
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var btr = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);

                int entityCount = 0;
                foreach (ObjectId id in btr) entityCount++;

                string currentLayer = null;
                if (!db.Clayer.IsNull)
                    currentLayer = ((LayerTableRecord)tr.GetObject(db.Clayer, OpenMode.ForRead)).Name;

                var result = new JsonObject
                {
                    ["fileName"] = db.Filename,
                    ["units"] = db.Insunits.ToString(),
                    ["currentLayer"] = currentLayer,
                    ["entityCount"] = entityCount
                };

                tr.Commit();
                return result;
            }
        }
    }
}
