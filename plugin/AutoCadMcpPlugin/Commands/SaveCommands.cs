using System;
using System.IO;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Guardar el dibujo y exportar bloques a archivos DWG.
    /// </summary>
    public static class SaveCommands
    {
        /// <summary>
        /// params: [path] (si falta, guarda sobre el archivo actual; si el
        /// dibujo nunca se guardó hace falta pasarlo), [overwrite=false]
        ///
        /// Escribe el archivo con la API. AutoCAD puede seguir mostrando el
        /// nombre viejo en la pestaña hasta que lo reabras: el archivo en disco
        /// queda bien igual.
        /// </summary>
        public static JsonObject Save(Document doc, JsonObject pars)
        {
            string path = pars["path"]?.GetValue<string>();
            bool overwrite = pars["overwrite"] != null && pars["overwrite"].GetValue<bool>();
            var db = doc.Database;

            if (string.IsNullOrEmpty(path))
            {
                string current = doc.Name;
                if (string.IsNullOrEmpty(current)
                    || !current.EndsWith(".dwg", StringComparison.OrdinalIgnoreCase)
                    || !File.Exists(current))
                {
                    throw new InvalidOperationException(
                        "Este dibujo todavía no está guardado en ningún archivo: " +
                        "pasá 'path' con la ruta .dwg donde querés guardarlo.");
                }
                path = current;
                overwrite = true;
            }

            path = Path.GetFullPath(path);
            if (!path.EndsWith(".dwg", StringComparison.OrdinalIgnoreCase))
                path += ".dwg";

            string dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                throw new DirectoryNotFoundException($"No existe la carpeta: {dir}");

            if (File.Exists(path) && !overwrite
                && !string.Equals(path, doc.Name, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException(
                    $"Ya existe '{path}'. Pasá overwrite=true si querés reemplazarlo.");
            }

            db.SaveAs(path, DwgVersion.Current);

            return new JsonObject
            {
                ["path"] = path,
                ["sizeBytes"] = new FileInfo(path).Length
            };
        }

        /// <summary>
        /// Exporta una definición de bloque a su propio archivo DWG, para poder
        /// reinsertarlo en otros dibujos con insert_block(path=...).
        /// params: name (bloque existente), path (.dwg destino), [overwrite=false]
        /// </summary>
        public static JsonObject ExportBlock(Document doc, JsonObject pars)
        {
            string name = pars["name"].GetValue<string>();
            string path = pars["path"].GetValue<string>();
            bool overwrite = pars["overwrite"] != null && pars["overwrite"].GetValue<bool>();

            path = Path.GetFullPath(path);
            if (!path.EndsWith(".dwg", StringComparison.OrdinalIgnoreCase))
                path += ".dwg";

            string dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                throw new DirectoryNotFoundException($"No existe la carpeta: {dir}");
            if (File.Exists(path) && !overwrite)
                throw new InvalidOperationException(
                    $"Ya existe '{path}'. Pasá overwrite=true si querés reemplazarlo.");

            var db = doc.Database;
            ObjectId blockId;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                if (!bt.Has(name))
                    throw new InvalidOperationException(
                        $"No existe un bloque llamado '{name}' en este dibujo.");
                blockId = bt[name];
                tr.Commit();
            }

            // Wblock arma una base de datos nueva con la definición adentro;
            // hay que liberarla siempre, salga bien o mal.
            using (Database exported = db.Wblock(blockId))
            {
                exported.SaveAs(path, DwgVersion.Current);
            }

            return new JsonObject
            {
                ["name"] = name,
                ["path"] = path,
                ["sizeBytes"] = new FileInfo(path).Length
            };
        }
    }
}
