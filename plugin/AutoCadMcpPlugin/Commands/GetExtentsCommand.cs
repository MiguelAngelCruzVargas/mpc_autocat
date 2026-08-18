using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Cuánto ocupa lo que ya está dibujado.
    ///
    /// Es lo que permite invertir el orden de trabajo: en vez de poner el cajón
    /// primero y confiar en que el dibujo entre, se dibuja, se mide y recién
    /// entonces se encuadra. Si el dibujo crece, el marco se adapta; al revés,
    /// el dibujo se sale de la hoja.
    /// params: [layers] (lista de capas a considerar; sin esto, todo el espacio
    ///         modelo), [excludeLayers] (para dejar afuera el propio cajón y
    ///         rótulo al reencuadrar)
    /// </summary>
    public static class GetExtentsCommand
    {
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var incluir = ToSet(pars["layers"] as JsonArray);
            var excluir = ToSet(pars["excludeLayers"] as JsonArray);

            double minX = double.MaxValue, minY = double.MaxValue;
            double maxX = double.MinValue, maxY = double.MinValue;
            int contadas = 0, sinExtension = 0;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var btr = (BlockTableRecord)tr.GetObject(
                    bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);

                foreach (ObjectId id in btr)
                {
                    var ent = tr.GetObject(id, OpenMode.ForRead) as Entity;
                    if (ent == null)
                        continue;

                    string capa = ent.Layer;
                    if (incluir.Count > 0 && !incluir.Contains(capa))
                        continue;
                    if (excluir.Contains(capa))
                        continue;

                    Extents3d ext;
                    try
                    {
                        ext = ent.GeometricExtents;
                    }
                    catch (System.Exception)
                    {
                        // Hay entidades sin extensión calculable (un texto
                        // vacío, por ejemplo). No son un error: se saltean.
                        sinExtension++;
                        continue;
                    }

                    minX = Math.Min(minX, ext.MinPoint.X);
                    minY = Math.Min(minY, ext.MinPoint.Y);
                    maxX = Math.Max(maxX, ext.MaxPoint.X);
                    maxY = Math.Max(maxY, ext.MaxPoint.Y);
                    contadas++;
                }
                tr.Commit();
            }

            if (contadas == 0)
            {
                return new JsonObject
                {
                    ["isEmpty"] = true,
                    ["entities"] = 0,
                    ["skipped"] = sinExtension
                };
            }

            return new JsonObject
            {
                ["isEmpty"] = false,
                ["minX"] = minX,
                ["minY"] = minY,
                ["maxX"] = maxX,
                ["maxY"] = maxY,
                ["width"] = maxX - minX,
                ["height"] = maxY - minY,
                ["centerX"] = (minX + maxX) / 2.0,
                ["centerY"] = (minY + maxY) / 2.0,
                ["entities"] = contadas,
                ["skipped"] = sinExtension
            };
        }

        private static HashSet<string> ToSet(JsonArray arr)
        {
            var set = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (arr == null)
                return set;
            foreach (var n in arr)
            {
                var s = n?.GetValue<string>();
                if (!string.IsNullOrEmpty(s))
                    set.Add(s);
            }
            return set;
        }
    }
}
