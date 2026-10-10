using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    public static class ListLayersCommand
    {
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var arr = new JsonArray();

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var lt = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
                foreach (ObjectId id in lt)
                {
                    var ltr = (LayerTableRecord)tr.GetObject(id, OpenMode.ForRead);
                    var ltype = (LinetypeTableRecord)tr.GetObject(ltr.LinetypeObjectId, OpenMode.ForRead);

                    arr.Add(new JsonObject
                    {
                        ["name"] = ltr.Name,
                        ["colorIndex"] = ltr.Color.ColorIndex,
                        ["linetype"] = ltype.Name,
                        ["off"] = ltr.IsOff,
                        ["frozen"] = ltr.IsFrozen,
                        ["locked"] = ltr.IsLocked,
                        // Para revisar contra un estándar de oficina y que
                        // un test en vivo pueda verificar que el marco de
                        // viewport NO se imprime.
                        ["plottable"] = ltr.IsPlottable,
                        ["lineweight"] = (int)ltr.LineWeight
                    });
                }
                tr.Commit();
            }
            return new JsonObject { ["layers"] = arr };
        }
    }
}
