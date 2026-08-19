using System.IO;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class AttachImageCommand
    {
        /// <summary>
        /// Inserta una imagen raster (logo, mapa de microlocalización, etc.) a
        /// partir de un archivo que YA existe en disco — este comando no genera
        /// contenido de imagen, solo la referencia dentro del dibujo.
        /// params: path, x, y, width, [height] (si falta, respeta la proporción
        /// real del archivo), [layer]
        /// </summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string path = pars["path"].GetValue<string>();
            double x = pars["x"].GetValue<double>();
            double y = pars["y"].GetValue<double>();
            double width = pars["width"].GetValue<double>();
            double? heightParam = pars["height"] != null ? pars["height"].GetValue<double>() : (double?)null;

            if (!File.Exists(path))
                throw new FileNotFoundException($"No se encontró el archivo de imagen: {path}");

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var dictId = RasterImageDef.GetImageDictionary(db);
                if (dictId.IsNull)
                    dictId = RasterImageDef.CreateImageDictionary(db);

                var imageDict = (DBDictionary)tr.GetObject(dictId, OpenMode.ForWrite);
                string defName = Path.GetFileNameWithoutExtension(path);

                RasterImageDef def;
                ObjectId defId;
                if (imageDict.Contains(defName))
                {
                    defId = imageDict.GetAt(defName);
                    def = (RasterImageDef)tr.GetObject(defId, OpenMode.ForWrite);
                }
                else
                {
                    def = new RasterImageDef { SourceFileName = path };
                    def.Load();
                    defId = imageDict.SetAt(defName, def);
                    tr.AddNewlyCreatedDBObject(def, true);
                }

                double pixelW = def.Size.X;
                double pixelH = def.Size.Y;
                double height = heightParam ?? (width * pixelH / pixelW);

                var image = new RasterImage
                {
                    ImageDefId = defId,
                    Orientation = new CoordinateSystem3d(
                        new Point3d(x, y, 0),
                        new Vector3d(width, 0, 0),
                        new Vector3d(0, height, 0))
                };

                var btr = SpaceHelper.Current(db, tr);

                EntityHelper.ApplyCommon(db, tr, image, pars);

                btr.AppendEntity(image);
                tr.AddNewlyCreatedDBObject(image, true);

                RasterImage.EnableReactors(true);
                image.AssociateRasterDef(def);

                tr.Commit();
                return new JsonObject { ["handle"] = image.Handle.ToString() };
            }
        }
    }
}
