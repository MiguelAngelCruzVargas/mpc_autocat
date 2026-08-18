using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Borrar layouts y definiciones de bloque. Sin esto, todo lo que se crea
    /// queda para siempre: un dibujo se va llenando de láminas y símbolos de
    /// prueba que solo se pueden sacar a mano.
    /// </summary>
    public static class PurgeCommands
    {
        /// <summary>params: name</summary>
        public static JsonObject DeleteLayout(Document doc, JsonObject pars)
        {
            string name = pars["name"].GetValue<string>();

            if (string.Equals(name, "Model", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException(
                    "El espacio modelo no se puede borrar.");

            var lm = LayoutManager.Current;
            if (lm.GetLayoutId(name).IsNull)
                throw new InvalidOperationException($"No existe un layout llamado '{name}'.");

            if (lm.LayoutCount <= 1)
                throw new InvalidOperationException(
                    "Es el único layout del dibujo: AutoCAD necesita al menos uno.");

            // Borrar el layout activo deja a AutoCAD sin pestaña donde pararse.
            if (string.Equals(lm.CurrentLayout, name, StringComparison.OrdinalIgnoreCase))
                lm.CurrentLayout = "Model";

            lm.DeleteLayout(name);
            return new JsonObject { ["deleted"] = name, ["remaining"] = lm.LayoutCount };
        }

        /// <summary>
        /// Borra una definición de bloque. Falla si todavía hay inserciones
        /// suyas en el dibujo: hay que borrarlas primero, si no quedarían
        /// referencias colgadas.
        /// params: name
        /// </summary>
        public static JsonObject PurgeBlock(Document doc, JsonObject pars)
        {
            string name = pars["name"].GetValue<string>();
            var db = doc.Database;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                if (!bt.Has(name))
                    throw new InvalidOperationException(
                        $"No existe un bloque llamado '{name}'.");

                var btr = (BlockTableRecord)tr.GetObject(bt[name], OpenMode.ForWrite);

                if (btr.IsLayout)
                    throw new InvalidOperationException(
                        $"'{name}' es el bloque de un layout, no un símbolo: " +
                        "usá delete_layout.");

                var refs = btr.GetBlockReferenceIds(true, true);
                if (refs.Count > 0)
                    throw new InvalidOperationException(
                        $"El bloque '{name}' todavía tiene {refs.Count} inserción(es) " +
                        "en el dibujo. Borralas primero con delete_entity.");

                btr.Erase();
                tr.Commit();
                return new JsonObject { ["purged"] = name };
            }
        }
    }
}
