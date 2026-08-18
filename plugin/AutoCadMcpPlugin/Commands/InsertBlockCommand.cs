using System;
using System.IO;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class InsertBlockCommand
    {
        /// <summary>
        /// Inserta una referencia de bloque (sÃ­mbolo: puerta, ventana, columna, etc.)
        /// params: name, x, y, [z=0], [scale=1], [rotationDeg=0], [layer],
        ///         [path] (dwg externo con la definiciÃ³n, si el bloque todavÃ­a no
        ///         existe en el dibujo actual â€” se importa una sola vez),
        ///         [attributes] ({TAG: valor, ...} para bloques con atributos)
        /// </summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string name = pars["name"].GetValue<string>();
            double x = pars["x"].GetValue<double>();
            double y = pars["y"].GetValue<double>();
            double z = pars["z"] != null ? pars["z"].GetValue<double>() : 0.0;
            double scale = pars["scale"] != null ? pars["scale"].GetValue<double>() : 1.0;
            double rotationDeg = pars["rotationDeg"] != null ? pars["rotationDeg"].GetValue<double>() : 0.0;
            string path = pars.ContainsKey("path") ? pars["path"]?.GetValue<string>() : null;
            JsonObject attributes = pars["attributes"] as JsonObject;

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);

                if (!bt.Has(name))
                {
                    if (string.IsNullOrEmpty(path))
                        throw new InvalidOperationException(
                            $"El bloque '{name}' no existe en el dibujo y no se pasÃ³ 'path' para importarlo.");
                    if (!File.Exists(path))
                        throw new FileNotFoundException($"No se encontrÃ³ el archivo de bloque: {path}");

                    ImportBlockFromFile(db, name, path);
                    bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                }

                var btr = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);

                var blockDefId = bt[name];
                var blockDef = (BlockTableRecord)tr.GetObject(blockDefId, OpenMode.ForRead);

                var br = new BlockReference(new Point3d(x, y, z), blockDefId)
                {
                    ScaleFactors = new Scale3d(scale),
                    Rotation = rotationDeg * Math.PI / 180.0
                };
                EntityHelper.ApplyCommon(db, tr, br, pars);

                btr.AppendEntity(br);
                tr.AddNewlyCreatedDBObject(br, true);

                if (blockDef.HasAttributeDefinitions)
                {
                    foreach (ObjectId defId in blockDef)
                    {
                        var defObj = tr.GetObject(defId, OpenMode.ForRead);
                        if (defObj is AttributeDefinition attDef && !attDef.Constant)
                        {
                            var attRef = new AttributeReference();
                            attRef.SetAttributeFromBlock(attDef, br.BlockTransform);
                            if (attributes != null && attributes.ContainsKey(attDef.Tag))
                                attRef.TextString = attributes[attDef.Tag]?.GetValue<string>() ?? "";
                            br.AttributeCollection.AppendAttribute(attRef);
                            tr.AddNewlyCreatedDBObject(attRef, true);
                        }
                    }
                }

                tr.Commit();
                return new JsonObject { ["handle"] = br.Handle.ToString() };
            }
        }

        private static void ImportBlockFromFile(Database db, string blockName, string path)
        {
            using (var sideDb = new Database(false, true))
            {
                sideDb.ReadDwgFile(path, FileOpenMode.OpenForReadAndAllShare, true, null);
                db.Insert(blockName, sideDb, false);
            }
        }
    }
}
