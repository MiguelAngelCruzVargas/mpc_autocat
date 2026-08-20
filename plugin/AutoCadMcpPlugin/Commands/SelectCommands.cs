using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Seleccionar y borrar por zona, capa o tipo.
    ///
    /// Es lo que permite corregir un ambiente sin rehacer el plano entero: se
    /// pide lo que hay dentro de ese rectángulo, se borra y se vuelve a dibujar
    /// solo eso. Sin esto, cambiar una recámara obliga a tirar el dibujo y
    /// empezar de cero.
    /// </summary>
    public static class SelectCommands
    {
        /// <summary>
        /// params: [x1,y1,x2,y2] (rectángulo; sin esto, todo el espacio ACTIVO),
        ///         [layers], [types], [mode] ("inside" solo lo que entra
        ///         entero, "crossing" también lo que lo cruza; default inside)
        /// </summary>
        public static JsonObject Select(Document doc, JsonObject pars)
        {
            bool hayZona = pars["x1"] != null && pars["y1"] != null
                           && pars["x2"] != null && pars["y2"] != null;
            double x1 = 0, y1 = 0, x2 = 0, y2 = 0;
            if (hayZona)
            {
                x1 = pars["x1"].GetValue<double>();
                y1 = pars["y1"].GetValue<double>();
                x2 = pars["x2"].GetValue<double>();
                y2 = pars["y2"].GetValue<double>();
                if (x2 < x1) { var t = x1; x1 = x2; x2 = t; }
                if (y2 < y1) { var t = y1; y1 = y2; y2 = t; }
            }

            var capas = ToSet(pars["layers"] as JsonArray);
            var tipos = ToSet(pars["types"] as JsonArray);
            bool cruzando = string.Equals(
                pars["mode"]?.GetValue<string>(), "crossing",
                StringComparison.OrdinalIgnoreCase);

            var db = doc.Database;
            var encontrados = new JsonArray();

            using (var tr = db.TransactionManager.StartTransaction())
            {
                // El espacio ACTIVO, igual que SpaceHelper/GetExtentsCommand: si
                // no, una entidad dibujada con un layout abierto es invisible
                // para esto aunque este mal ubicada en el papel.
                var btr = (BlockTableRecord)tr.GetObject(db.CurrentSpaceId, OpenMode.ForRead);

                foreach (ObjectId id in btr)
                {
                    var ent = tr.GetObject(id, OpenMode.ForRead) as Entity;
                    if (ent == null)
                        continue;

                    if (capas.Count > 0 && !capas.Contains(ent.Layer))
                        continue;
                    if (tipos.Count > 0 && !tipos.Contains(ent.GetType().Name))
                        continue;

                    if (hayZona)
                    {
                        Extents3d ext;
                        try { ext = ent.GeometricExtents; }
                        catch (System.Exception) { continue; }

                        bool dentro = ext.MinPoint.X >= x1 && ext.MaxPoint.X <= x2
                                      && ext.MinPoint.Y >= y1 && ext.MaxPoint.Y <= y2;
                        bool cruza = ext.MinPoint.X <= x2 && ext.MaxPoint.X >= x1
                                     && ext.MinPoint.Y <= y2 && ext.MaxPoint.Y >= y1;

                        if (cruzando ? !cruza : !dentro)
                            continue;
                    }

                    encontrados.Add(new JsonObject
                    {
                        ["handle"] = ent.Handle.ToString(),
                        ["type"] = ent.GetType().Name,
                        ["layer"] = ent.Layer
                    });
                }
                tr.Commit();
            }

            return new JsonObject
            {
                ["entities"] = encontrados,
                ["count"] = encontrados.Count,
                ["mode"] = cruzando ? "crossing" : "inside"
            };
        }

        /// <summary>
        /// Borra varias entidades de una sola pasada.
        /// params: handles ([...]), [ignoreMissing=true]
        /// </summary>
        public static JsonObject DeleteMany(Document doc, JsonObject pars)
        {
            var handleArray = pars["handles"].AsArray();
            bool ignorarFaltantes = pars["ignoreMissing"] == null
                || pars["ignoreMissing"].GetValue<bool>();

            var db = doc.Database;
            int borradas = 0;
            var fallidas = new JsonArray();

            using (var tr = db.TransactionManager.StartTransaction())
            {
                foreach (var h in handleArray)
                {
                    string handleStr = h.GetValue<string>();
                    try
                    {
                        var ent = (Entity)tr.GetObject(
                            HandleHelper.GetObjectId(db, handleStr), OpenMode.ForWrite);
                        ent.Erase();
                        borradas++;
                    }
                    catch (System.Exception)
                    {
                        // Un handle que ya no existe no es un error cuando se
                        // esta limpiando: puede haberse borrado en cascada.
                        if (!ignorarFaltantes)
                            throw;
                        fallidas.Add(handleStr);
                    }
                }
                tr.Commit();
            }

            return new JsonObject
            {
                ["deleted"] = borradas,
                ["notFound"] = fallidas,
                ["requested"] = handleArray.Count
            };
        }

        private static HashSet<string> ToSet(JsonArray arr)
        {
            var set = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (arr == null) return set;
            foreach (var n in arr)
            {
                var s = n?.GetValue<string>();
                if (!string.IsNullOrEmpty(s)) set.Add(s);
            }
            return set;
        }
    }
}
