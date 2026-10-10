using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    public static class ListEntitiesCommand
    {
        /// <summary>El contenido de un texto, para no tener que pedir
        /// get_entity uno por uno (~0.5 s cada viaje): revisar los textos de
        /// un juego de planos pasaba de minutos a una llamada.</summary>
        private static void AgregarTexto(JsonObject o, Entity ent, bool incluir)
        {
            if (!incluir)
                return;
            if (ent is DBText t)
                o["text"] = t.TextString;
            else if (ent is MText m)
                o["text"] = m.Text;
        }

        private static JsonObject TodosLosEspacios(Document doc, string typeFilter, int limit,
                                                   bool incluirTexto)
        {
            var db = doc.Database;
            var arr = new JsonArray();
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var dict = (DBDictionary)tr.GetObject(db.LayoutDictionaryId, OpenMode.ForRead);
                foreach (DBDictionaryEntry entry in dict)
                {
                    var layout = (Layout)tr.GetObject(entry.Value, OpenMode.ForRead);
                    var btr = (BlockTableRecord)tr.GetObject(layout.BlockTableRecordId, OpenMode.ForRead);
                    foreach (ObjectId id in btr)
                    {
                        if (arr.Count >= limit)
                            break;
                        var ent = (Entity)tr.GetObject(id, OpenMode.ForRead);
                        string typeName = ent.GetType().Name;
                        if (!string.IsNullOrEmpty(typeFilter) &&
                            !typeName.Equals(typeFilter, System.StringComparison.OrdinalIgnoreCase))
                            continue;
                        // El viewport general de cada lámina no es dibujo.
                        if (ent is Viewport vp && vp.Number == 1)
                            continue;
                        var o = new JsonObject
                        {
                            ["handle"] = ent.Handle.ToString(),
                            ["type"] = typeName,
                            ["layer"] = ent.Layer,
                            ["space"] = layout.LayoutName
                        };
                        AgregarTexto(o, ent, incluirTexto);
                        arr.Add(o);
                    }
                }
                tr.Commit();
            }
            return new JsonObject { ["entities"] = arr, ["count"] = arr.Count, ["allSpaces"] = true };
        }

        /// <summary>params: [type] (p.ej. "Line", "Polyline"), [limit] (default 200),
        /// [allSpaces], [includeText]: devuelve también el contenido de cada
        /// DBText/MText.</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string typeFilter = pars.ContainsKey("type") ? pars["type"]?.GetValue<string>() : null;
            int limit = pars["limit"] != null ? pars["limit"].GetValue<int>() : 200;
            // allSpaces: el modelo Y todas las láminas. Una revisión del
            // dibujo (estándar de oficina) que mira solo el espacio activo
            // no ve lo que hay en el modelo mientras hay una lámina abierta.
            bool todos = pars["allSpaces"] != null && pars["allSpaces"].GetValue<bool>();
            bool incluirTexto = pars["includeText"] != null && pars["includeText"].GetValue<bool>();
            if (todos)
                return TodosLosEspacios(doc, typeFilter, limit, incluirTexto);

            var db = doc.Database;
            var arr = new JsonArray();

            using (var tr = db.TransactionManager.StartTransaction())
            {
                // El espacio ACTIVO, igual que SpaceHelper (ver GetExtentsCommand
                // para el porque: si no, esto no ve lo dibujado con un layout
                // abierto).
                var btr = (BlockTableRecord)tr.GetObject(db.CurrentSpaceId, OpenMode.ForRead);

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

                    var o = new JsonObject
                    {
                        ["handle"] = ent.Handle.ToString(),
                        ["type"] = typeName,
                        ["layer"] = ent.Layer
                    };
                    AgregarTexto(o, ent, incluirTexto);
                    arr.Add(o);
                    count++;
                }
                tr.Commit();
            }

            return new JsonObject { ["entities"] = arr, ["count"] = arr.Count };
        }
    }
}
