using System;
using System.Text;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Buscar y reemplazar texto en todo el espacio ACTIVO: DBText, MText y
    /// atributos de bloque. Para corregir un dato repetido (un número de
    /// lámina, un nombre mal escrito) de una pasada, en vez de rótulo por
    /// rótulo.
    /// </summary>
    public static class FindReplaceTextCommand
    {
        /// <summary>params: find, replace, [caseSensitive=false]</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string find = pars["find"].GetValue<string>();
            string replace = pars["replace"].GetValue<string>();
            bool caseSensitive = pars["caseSensitive"] != null && pars["caseSensitive"].GetValue<bool>();

            if (string.IsNullOrEmpty(find))
                throw new ArgumentException("'find' no puede estar vacío.");

            var comparison = caseSensitive ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
            var db = doc.Database;
            var changed = new JsonArray();

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var btr = SpaceHelper.Current(db, tr);
                foreach (ObjectId id in btr)
                {
                    var obj = tr.GetObject(id, OpenMode.ForRead);

                    if (obj is DBText text && text.TextString.IndexOf(find, comparison) >= 0)
                    {
                        text.UpgradeOpen();
                        text.TextString = ReplaceAll(text.TextString, find, replace, comparison);
                        changed.Add(new JsonObject { ["handle"] = text.Handle.ToString(), ["type"] = "DBText" });
                    }
                    else if (obj is MText mtext && mtext.Contents.IndexOf(find, comparison) >= 0)
                    {
                        mtext.UpgradeOpen();
                        mtext.Contents = ReplaceAll(mtext.Contents, find, replace, comparison);
                        changed.Add(new JsonObject { ["handle"] = mtext.Handle.ToString(), ["type"] = "MText" });
                    }
                    else if (obj is BlockReference br && br.AttributeCollection.Count > 0)
                    {
                        foreach (ObjectId attId in br.AttributeCollection)
                        {
                            var att = (AttributeReference)tr.GetObject(attId, OpenMode.ForRead);
                            if (att.TextString.IndexOf(find, comparison) < 0) continue;
                            att.UpgradeOpen();
                            att.TextString = ReplaceAll(att.TextString, find, replace, comparison);
                            changed.Add(new JsonObject {
                                ["handle"] = br.Handle.ToString(), ["type"] = "Attribute",
                                ["tag"] = att.Tag
                            });
                        }
                    }
                }
                tr.Commit();
            }

            return new JsonObject { ["changed"] = changed, ["count"] = changed.Count };
        }

        private static string ReplaceAll(string source, string find, string replace,
                                         StringComparison comparison)
        {
            var sb = new StringBuilder();
            int pos = 0;
            while (true)
            {
                int idx = source.IndexOf(find, pos, comparison);
                if (idx < 0) { sb.Append(source, pos, source.Length - pos); break; }
                sb.Append(source, pos, idx - pos);
                sb.Append(replace);
                pos = idx + find.Length;
            }
            return sb.ToString();
        }
    }
}
