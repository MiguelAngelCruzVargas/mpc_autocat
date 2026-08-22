using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Arreglo rectangular o polar de una entidad ya dibujada — copias reales,
    /// no un objeto Array asociativo (mismo criterio que el resto del plugin:
    /// create_axis_grid o los muebles repetidos también son copias sueltas,
    /// cada una con su propio handle editable).
    /// </summary>
    public static class ArrayEntityCommand
    {
        /// <summary>
        /// params: handle, mode ('rectangular'|'polar')
        /// rectangular: rows, cols, [rowSpacing=0], [colSpacing=0]
        /// polar: centerX, centerY, count, [angleTotal=360], [rotateItems=true]
        /// El original NO se cuenta aparte: ya ocupa la posición [0,0] (o el
        /// ángulo 0), así que 'rows x cols' o 'count' es el total de piezas
        /// resultantes, original incluido.
        /// </summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string handleStr = pars["handle"].GetValue<string>();
            string mode = pars["mode"]?.GetValue<string>() ?? "rectangular";

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var srcId = HandleHelper.GetObjectId(db, handleStr);
                var src = (Entity)tr.GetObject(srcId, OpenMode.ForRead);
                var btr = (BlockTableRecord)tr.GetObject(src.BlockId, OpenMode.ForWrite);
                var handles = new JsonArray();

                if (mode == "rectangular")
                {
                    int rows = pars["rows"] != null ? pars["rows"].GetValue<int>() : 1;
                    int cols = pars["cols"] != null ? pars["cols"].GetValue<int>() : 1;
                    double rowSpacing = pars["rowSpacing"] != null ? pars["rowSpacing"].GetValue<double>() : 0.0;
                    double colSpacing = pars["colSpacing"] != null ? pars["colSpacing"].GetValue<double>() : 0.0;
                    if (rows < 1 || cols < 1)
                        throw new ArgumentException("rows y cols tienen que ser >= 1.");

                    for (int r = 0; r < rows; r++)
                    {
                        for (int c = 0; c < cols; c++)
                        {
                            if (r == 0 && c == 0) continue; // el original ya esta ahi
                            var clone = (Entity)src.Clone();
                            clone.TransformBy(Matrix3d.Displacement(
                                new Vector3d(c * colSpacing, r * rowSpacing, 0)));
                            btr.AppendEntity(clone);
                            tr.AddNewlyCreatedDBObject(clone, true);
                            handles.Add(clone.Handle.ToString());
                        }
                    }
                }
                else if (mode == "polar")
                {
                    double cx = pars["centerX"].GetValue<double>();
                    double cy = pars["centerY"].GetValue<double>();
                    int count = pars["count"].GetValue<int>();
                    double angleTotal = pars["angleTotal"] != null ? pars["angleTotal"].GetValue<double>() : 360.0;
                    bool rotateItems = pars["rotateItems"] == null || pars["rotateItems"].GetValue<bool>();
                    if (count < 1)
                        throw new ArgumentException("count tiene que ser >= 1.");

                    // Circulo completo: n items repartidos en 360/n. Arco
                    // parcial: el ULTIMO item cae justo en angleTotal, asi que
                    // el paso es angleTotal/(count-1) -mismo criterio que
                    // ARRAYPOLAR de AutoCAD.
                    double step = angleTotal >= 360.0 - 1e-9
                        ? angleTotal / count
                        : (count > 1 ? angleTotal / (count - 1) : 0.0);
                    var center = new Point3d(cx, cy, 0);

                    for (int i = 1; i < count; i++)
                    {
                        double angRad = step * i * Math.PI / 180.0;
                        var clone = (Entity)src.Clone();

                        if (rotateItems)
                        {
                            clone.TransformBy(Matrix3d.Rotation(angRad, Vector3d.ZAxis, center));
                        }
                        else
                        {
                            // Traslada al punto del arco sin rotar la pieza:
                            // se mueve el centro de su caja, no se la gira.
                            Point3d refPoint = center;
                            var bounds = clone.Bounds;
                            if (bounds.HasValue)
                                refPoint = new Point3d(
                                    (bounds.Value.MinPoint.X + bounds.Value.MaxPoint.X) / 2.0,
                                    (bounds.Value.MinPoint.Y + bounds.Value.MaxPoint.Y) / 2.0, 0);
                            var rotated = refPoint.TransformBy(Matrix3d.Rotation(angRad, Vector3d.ZAxis, center));
                            clone.TransformBy(Matrix3d.Displacement(rotated - refPoint));
                        }

                        btr.AppendEntity(clone);
                        tr.AddNewlyCreatedDBObject(clone, true);
                        handles.Add(clone.Handle.ToString());
                    }
                }
                else
                {
                    throw new ArgumentException(
                        $"mode tiene que ser 'rectangular' o 'polar', no '{mode}'.");
                }

                tr.Commit();
                return new JsonObject { ["handles"] = handles, ["count"] = handles.Count };
            }
        }
    }
}
