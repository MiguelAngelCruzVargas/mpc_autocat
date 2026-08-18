using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class CreateDimensionCommand
    {
        /// <summary>
        /// Cota alineada entre dos puntos.
        /// params: x1, y1, x2, y2, dimLineX, dimLineY, [layer]
        /// (dimLineX/Y define a qué distancia y de qué lado se dibuja la línea de cota)
        /// </summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            double x1 = pars["x1"].GetValue<double>();
            double y1 = pars["y1"].GetValue<double>();
            double x2 = pars["x2"].GetValue<double>();
            double y2 = pars["y2"].GetValue<double>();
            double dimLineX = pars["dimLineX"].GetValue<double>();
            double dimLineY = pars["dimLineY"].GetValue<double>();
            // Multiplicador sobre el DIMSCALE del estilo activo (texto, flechas,
            // separación de líneas de extensión, todo junto). El estilo por
            // defecto suele estar calibrado para dibujos en milímetros; en un
            // dibujo a otra unidad (p.ej. 1 unidad = 1 metro) hay que achicarlo
            // o el texto sale gigante. 1.0 = sin cambios (comportamiento previo).
            double dimScale = pars["scale"] != null ? pars["scale"].GetValue<double>() : 1.0;

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
                var btr = (BlockTableRecord)tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);

                var dim = new AlignedDimension(
                    new Point3d(x1, y1, 0),
                    new Point3d(x2, y2, 0),
                    new Point3d(dimLineX, dimLineY, 0),
                    null,
                    StyleHelper.ResolveDimStyle(db, tr, pars));

                EntityHelper.ApplyCommon(db, tr, dim, pars);
                if (pars["scale"] != null)
                    dim.Dimscale = dimScale;

                btr.AppendEntity(dim);
                tr.AddNewlyCreatedDBObject(dim, true);
                tr.Commit();

                return new JsonObject
                {
                    ["handle"] = dim.Handle.ToString(),
                    ["measurement"] = dim.Measurement
                };
            }
        }
    }
}
