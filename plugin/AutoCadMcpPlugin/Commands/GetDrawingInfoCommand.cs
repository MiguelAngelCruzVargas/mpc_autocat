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
                // El espacio ACTIVO, igual que GetExtentsCommand/ListEntitiesCommand/
                // SelectCommands: si no, con un layout de papel abierto el conteo
                // no coincide con lo que esas tools reportan para el mismo dibujo.
                var btr = (BlockTableRecord)tr.GetObject(db.CurrentSpaceId, OpenMode.ForRead);

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
