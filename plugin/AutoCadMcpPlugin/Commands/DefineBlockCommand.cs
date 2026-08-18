using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class DefineBlockCommand
    {
        /// <summary>
        /// Convierte entidades ya dibujadas en el espacio modelo (por handle) en
        /// una definiciÃ³n de bloque reutilizable â€” equivalente al comando BLOCK,
        /// sin necesitar ningÃºn archivo externo. Las entidades originales sueltas
        /// se borran del espacio modelo (quedan "adentro" del bloque nuevo);
        /// despuÃ©s se insertan con insert_block(name=...).
        /// params: name, handles ([...]), basePointX, basePointY, [basePointZ=0]
        /// </summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string name = pars["name"].GetValue<string>();
            var handleArray = pars["handles"].AsArray();
            double baseX = pars["basePointX"].GetValue<double>();
            double baseY = pars["basePointY"].GetValue<double>();
            double baseZ = pars["basePointZ"] != null ? pars["basePointZ"].GetValue<double>() : 0.0;

            if (handleArray.Count == 0)
                throw new InvalidOperationException("Hay que pasar al menos un handle en 'handles'.");

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForWrite);
                if (bt.Has(name))
                    throw new InvalidOperationException($"Ya existe un bloque llamado '{name}'.");

                var newBtr = new BlockTableRecord
                {
                    Name = name,
                    Origin = new Point3d(baseX, baseY, baseZ)
                };
                var newBtrId = bt.Add(newBtr);
                tr.AddNewlyCreatedDBObject(newBtr, true);

                foreach (var h in handleArray)
                {
                    string handleStr = h.GetValue<string>();
                    var srcId = HandleHelper.GetObjectId(db, handleStr);
                    var src = (Entity)tr.GetObject(srcId, OpenMode.ForWrite);
                    var clone = (Entity)src.Clone();
                    newBtr.AppendEntity(clone);
                    tr.AddNewlyCreatedDBObject(clone, true);
                    src.Erase();
                }

                tr.Commit();
                return new JsonObject { ["name"] = name };
            }
        }
    }
}
