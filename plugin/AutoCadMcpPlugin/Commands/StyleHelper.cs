using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Resuelve el parámetro opcional 'style' de textos y cotas al registro de
    /// la tabla correspondiente. Sin 'style' se usa el estilo actual del
    /// dibujo, que es el comportamiento de siempre.
    /// </summary>
    internal static class StyleHelper
    {
        public static void ApplyTextStyle(Database db, Transaction tr, DBText text, JsonObject pars)
        {
            var id = ResolveTextStyle(db, tr, pars);
            if (!id.IsNull)
                text.TextStyleId = id;
        }

        public static void ApplyTextStyle(Database db, Transaction tr, MText mtext, JsonObject pars)
        {
            var id = ResolveTextStyle(db, tr, pars);
            if (!id.IsNull)
                mtext.TextStyleId = id;
        }

        private static ObjectId ResolveTextStyle(Database db, Transaction tr, JsonObject pars)
        {
            string name = pars["style"]?.GetValue<string>();
            if (string.IsNullOrEmpty(name))
                return ObjectId.Null;

            var table = (TextStyleTable)tr.GetObject(db.TextStyleTableId, OpenMode.ForRead);
            if (!table.Has(name))
                throw new InvalidOperationException(
                    $"No existe el estilo de texto '{name}'. Creálo primero con set_text_style.");
            return table[name];
        }

        public static ObjectId ResolveDimStyle(Database db, Transaction tr, JsonObject pars)
        {
            string name = pars["style"]?.GetValue<string>();
            if (string.IsNullOrEmpty(name))
                return db.Dimstyle;

            var table = (DimStyleTable)tr.GetObject(db.DimStyleTableId, OpenMode.ForRead);
            if (!table.Has(name))
                throw new InvalidOperationException(
                    $"No existe el estilo de cota '{name}'. Creálo primero con set_dim_style.");
            return table[name];
        }
    }
}
