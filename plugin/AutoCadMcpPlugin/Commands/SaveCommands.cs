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
                // doc.Name de un dibujo nuevo sigue siendo "Drawing2.dwg"
                // aunque ya se haya guardado con SaveAs: el archivo real está
                // en db.Filename.
                string current = File.Exists(doc.Name) ? doc.Name : db.Filename;
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

            // Guardar otra vez donde ESTA base de datos ya se guardó no es
            // pisar un archivo ajeno: visto en vivo, un dibujo nuevo guardado
            // una vez ya no se podía volver a guardar ("Ya existe…") y la
            // regla de guardar seguido quedaba imposible de cumplir.
            bool yaEsSuyo = !string.IsNullOrEmpty(db.Filename)
                && string.Equals(Path.GetFullPath(db.Filename), path,
                                 StringComparison.OrdinalIgnoreCase);
            if (File.Exists(path) && !overwrite && !yaEsSuyo
                && !string.Equals(path, doc.Name, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException(
                    $"Ya existe '{path}'. Pasá overwrite=true si querés reemplazarlo.");
            }

            // Guardar sobre el MISMO archivo del que se abrió el dibujo: con
            // SaveAs(path, version) AutoCAD tira eFilerError, porque el .dwg
            // está tomado por esta misma base de datos. Hay que pedirle que
            // lo pase a .bak y renombre (la sobrecarga con bBakAndRename), que
            // es lo que hace QSAVE. Sin esto, el ciclo de corrección —abrir
            // un plano, corregir, guardar— fallaba justo en el último paso.
            bool mismoArchivo = (!string.IsNullOrEmpty(db.Filename)
                    && string.Equals(Path.GetFullPath(db.Filename), path,
                                     StringComparison.OrdinalIgnoreCase))
                || string.Equals(SafeFullPath(doc.Name), path,
                                 StringComparison.OrdinalIgnoreCase);
            if (mismoArchivo)
            {
                // La base de datos lee el .dwg A DEMANDA y lo deja abierto:
                // sin soltarlo, el rename a .bak falla igual con eFilerError
                // (visto en vivo: plano abierto con open_document, corregido,
                // y el guardado fallaba). CloseInput(true) termina de cargar
                // todo a memoria y suelta el archivo, como hace QSAVE.
                try { db.CloseInput(true); } catch (Autodesk.AutoCAD.Runtime.Exception) { }
                db.SaveAs(path, true, DwgVersion.Current, db.SecurityParameters);
            }
            else
                db.SaveAs(path, DwgVersion.Current);

            return new JsonObject
            {
                ["path"] = path,
                ["sizeBytes"] = new FileInfo(path).Length
            };
        }

        /// <summary>
        /// Guarda una COPIA del dibujo activo en otro formato o versión, sin cambiar el nombre ni el estado del
        /// dibujo abierto: DWG de una versión anterior (para pasárselo a quien trabaja en un AutoCAD viejo) o DXF.
        /// params: path (.dwg o .dxf), [version] 2018 | 2013 | 2010 | 2007 | 2004 | 2000 (default 2018),
        /// [precision] decimales del DXF (0-16, default 16), [overwrite=false].
        ///
        /// DWG: se arma una base de datos con TODO el dibujo (Database.Wblock() sin argumentos) y se guarda ESA,
        /// de modo que el original no se toca; después se relee la copia y se comparan entidades y láminas. DXF:
        /// Database.DxfOut. Desde AutoCAD 2018 hasta la 2027 el formato de archivo es el mismo (AC1032): solo
        /// hace falta bajar la versión para entregar a una 2017 o anterior.
        /// </summary>
        public static JsonObject ExportCopy(Document doc, JsonObject pars)
        {
            string path = pars["path"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(path)) throw new ArgumentException("Falta 'path' (.dwg o .dxf).");
            path = Path.GetFullPath(path);
            string ext = Path.GetExtension(path).ToLowerInvariant();
            if (ext != ".dwg" && ext != ".dxf")
                throw new ArgumentException("La extensión del archivo tiene que ser .dwg o .dxf.");
            string dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                throw new DirectoryNotFoundException("No existe la carpeta: " + dir);
            bool overwrite = pars["overwrite"]?.GetValue<bool>() ?? false;
            if (File.Exists(path) && !overwrite)
                throw new InvalidOperationException("Ya existe '" + path + "'. Pasá overwrite=true si querés reemplazarlo.");
            var db = doc.Database;
            if (!string.IsNullOrEmpty(db.Filename) && string.Equals(SafeFullPath(db.Filename), path, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Esa es la ruta del propio dibujo abierto: para eso está save_drawing.");

            string v = pars["version"]?.GetValue<string>() ?? "2018";
            DwgVersion version;
            switch (v)
            {
                case "2018": version = DwgVersion.AC1032; break;
                case "2013": version = DwgVersion.AC1027; break;
                case "2010": version = DwgVersion.AC1024; break;
                case "2007": version = DwgVersion.AC1021; break;
                case "2004": version = DwgVersion.AC1800; break;
                case "2000": version = DwgVersion.AC1015; break;
                default: throw new ArgumentException("'version' es 2018, 2013, 2010, 2007, 2004 o 2000.");
            }
            int precision = pars["precision"]?.GetValue<int>() ?? 16;
            if (precision < 0 || precision > 16) throw new ArgumentException("'precision' va de 0 a 16.");

            var salida = new JsonObject { ["path"] = path, ["format"] = ext.Substring(1), ["version"] = v };
            if (ext == ".dxf")
            {
                db.DxfOut(path, precision, version);
            }
            else
            {
                using (Database copia = db.Wblock())
                    copia.SaveAs(path, version);
                // Se vuelve a leer lo escrito: una copia que no abre, o a la que le faltan cosas, no es un entregable.
                using (var leida = new Database(false, true))
                {
                    leida.ReadDwgFile(path, FileOpenMode.OpenForReadAndAllShare, true, "");
                    leida.CloseInput(true);
                    int ents = 0, lays = 0;
                    using (var tr = leida.TransactionManager.StartTransaction())
                    {
                        var bt = (BlockTable)tr.GetObject(leida.BlockTableId, OpenMode.ForRead);
                        var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                        foreach (ObjectId _ in ms) ents++;
                        var ld = (DBDictionary)tr.GetObject(leida.LayoutDictionaryId, OpenMode.ForRead);
                        foreach (DBDictionaryEntry _ in ld) lays++;
                        tr.Commit();
                    }
                    int entsOriginal = 0, laysOriginal = 0;
                    using (var tr = db.TransactionManager.StartTransaction())
                    {
                        var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                        var ms = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                        foreach (ObjectId _ in ms) entsOriginal++;
                        var ld = (DBDictionary)tr.GetObject(db.LayoutDictionaryId, OpenMode.ForRead);
                        foreach (DBDictionaryEntry _ in ld) laysOriginal++;
                        tr.Commit();
                    }
                    salida["verify"] = new JsonObject
                    {
                        ["modelEntities"] = ents, ["modelEntitiesOriginal"] = entsOriginal,
                        ["layouts"] = lays, ["layoutsOriginal"] = laysOriginal,
                        ["match"] = ents == entsOriginal && lays == laysOriginal
                    };
                }
            }
            salida["sizeBytes"] = new FileInfo(path).Length;
            if (v != "2018")
                salida["warning"] = "Guardado como AutoCAD " + v + ": lo que esa versión no conoce se convierte o se pierde (objetos de versiones nuevas pasan a proxy).";
            return salida;
        }

        private static string SafeFullPath(string p)
        {
            try { return string.IsNullOrEmpty(p) ? "" : Path.GetFullPath(p); }
            catch (System.Exception) { return ""; }
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
