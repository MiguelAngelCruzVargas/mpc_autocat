using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Los tipos de cota que no son la alineada.
    ///
    /// Una cota alineada mide la distancia recta entre dos puntos, y con eso
    /// solo no se acota un plano real: un eje de calle necesita el radio de sus
    /// curvas y el ángulo entre tangentes, un despiece necesita cotas rotadas
    /// respecto de un eje, y una curva necesita su desarrollo.
    /// </summary>
    public static class DimensionCommands
    {
        private static ObjectId Style(Database db, Transaction tr, JsonObject pars)
        {
            return StyleHelper.ResolveDimStyle(db, tr, pars);
        }

        private static void Finish(Database db, Transaction tr, Dimension dim,
                                   JsonObject pars, JsonObject result)
        {
            EntityHelper.ApplyCommon(db, tr, dim, pars);
            if (pars["scale"] != null)
                dim.Dimscale = pars["scale"].GetValue<double>();
            if (pars["text"] != null)
                dim.DimensionText = pars["text"].GetValue<string>();

            var bt = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
            var btr = (BlockTableRecord)tr.GetObject(
                bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite);
            btr.AppendEntity(dim);
            tr.AddNewlyCreatedDBObject(dim, true);

            result["handle"] = dim.Handle.ToString();
            result["measurement"] = dim.Measurement;
        }

        /// <summary>
        /// Cota lineal proyectada sobre una dirección: mide solo la componente
        /// horizontal, vertical o en el ángulo que se pida, no la distancia
        /// recta. Es la que se usa para acotar anchos y separaciones en planta.
        /// params: x1, y1, x2, y2, dimLineX, dimLineY, [angleDeg=0], [style],
        ///         [scale], [text], [layer], [lineweight]
        /// </summary>
        public static JsonObject Rotated(Document doc, JsonObject pars)
        {
            double x1 = pars["x1"].GetValue<double>();
            double y1 = pars["y1"].GetValue<double>();
            double x2 = pars["x2"].GetValue<double>();
            double y2 = pars["y2"].GetValue<double>();
            double lx = pars["dimLineX"].GetValue<double>();
            double ly = pars["dimLineY"].GetValue<double>();
            double angle = pars["angleDeg"] != null
                ? pars["angleDeg"].GetValue<double>() : 0.0;

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var result = new JsonObject { ["angleDeg"] = angle };
                var dim = new RotatedDimension(
                    angle * Math.PI / 180.0,
                    new Point3d(x1, y1, 0), new Point3d(x2, y2, 0),
                    new Point3d(lx, ly, 0), null, Style(db, tr, pars));
                Finish(db, tr, dim, pars, result);
                tr.Commit();
                return result;
            }
        }

        /// <summary>
        /// Radio de un arco o círculo existente, por handle.
        /// params: handle, [leaderLengthFactor=1.5], [style], [scale], [text]
        /// </summary>
        public static JsonObject Radial(Document doc, JsonObject pars)
        {
            string handleStr = pars["handle"].GetValue<string>();
            var db = doc.Database;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var id = HandleHelper.GetObjectId(db, handleStr);
                var curva = tr.GetObject(id, OpenMode.ForRead);

                Point3d centro;
                double radio;
                if (curva is Arc arc) { centro = arc.Center; radio = arc.Radius; }
                else if (curva is Circle c) { centro = c.Center; radio = c.Radius; }
                else
                    throw new InvalidOperationException(
                        "Una cota de radio necesita un Arc o un Circle. " +
                        $"'{handleStr}' es {curva.GetType().Name}.");

                // El punto sobre la curva desde donde sale la flecha.
                double ang = curva is Arc a2
                    ? (a2.StartAngle + a2.EndAngle) / 2.0 : Math.PI / 4.0;
                var enCurva = new Point3d(centro.X + radio * Math.Cos(ang),
                                          centro.Y + radio * Math.Sin(ang), 0);
                double factor = pars["leaderLengthFactor"] != null
                    ? pars["leaderLengthFactor"].GetValue<double>() : 1.5;

                var result = new JsonObject { ["radius"] = radio };
                var dim = new RadialDimension(centro, enCurva, radio * (factor - 1.0),
                                              null, Style(db, tr, pars));
                Finish(db, tr, dim, pars, result);
                tr.Commit();
                return result;
            }
        }

        /// <summary>
        /// Diámetro de un círculo o arco existente.
        /// params: handle, [leaderLengthFactor=1.5], [style], [scale], [text]
        /// </summary>
        public static JsonObject Diametric(Document doc, JsonObject pars)
        {
            string handleStr = pars["handle"].GetValue<string>();
            var db = doc.Database;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var id = HandleHelper.GetObjectId(db, handleStr);
                var curva = tr.GetObject(id, OpenMode.ForRead);

                Point3d centro;
                double radio;
                if (curva is Circle c) { centro = c.Center; radio = c.Radius; }
                else if (curva is Arc a) { centro = a.Center; radio = a.Radius; }
                else
                    throw new InvalidOperationException(
                        "Una cota de diámetro necesita un Circle o un Arc. " +
                        $"'{handleStr}' es {curva.GetType().Name}.");

                double ang = Math.PI / 4.0;
                var p1 = new Point3d(centro.X + radio * Math.Cos(ang),
                                     centro.Y + radio * Math.Sin(ang), 0);
                var p2 = new Point3d(centro.X - radio * Math.Cos(ang),
                                     centro.Y - radio * Math.Sin(ang), 0);
                double factor = pars["leaderLengthFactor"] != null
                    ? pars["leaderLengthFactor"].GetValue<double>() : 1.5;

                var result = new JsonObject { ["diameter"] = radio * 2.0 };
                var dim = new DiametricDimension(p1, p2, radio * (factor - 1.0),
                                                 null, Style(db, tr, pars));
                Finish(db, tr, dim, pars, result);
                tr.Commit();
                return result;
            }
        }

        /// <summary>
        /// Ángulo entre dos rectas definidas por el vértice y dos puntos.
        /// params: vertexX, vertexY, x1, y1, x2, y2, arcX, arcY (por dónde pasa
        ///         el arco de cota), [style], [scale], [text]
        /// </summary>
        public static JsonObject Angular(Document doc, JsonObject pars)
        {
            var vertice = new Point3d(pars["vertexX"].GetValue<double>(),
                                      pars["vertexY"].GetValue<double>(), 0);
            var p1 = new Point3d(pars["x1"].GetValue<double>(),
                                 pars["y1"].GetValue<double>(), 0);
            var p2 = new Point3d(pars["x2"].GetValue<double>(),
                                 pars["y2"].GetValue<double>(), 0);
            var arco = new Point3d(pars["arcX"].GetValue<double>(),
                                   pars["arcY"].GetValue<double>(), 0);

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var result = new JsonObject();
                var dim = new LineAngularDimension2(
                    vertice, p1, vertice, p2, arco, null, Style(db, tr, pars));
                Finish(db, tr, dim, pars, result);
                result["measurementDeg"] = dim.Measurement * 180.0 / Math.PI;
                tr.Commit();
                return result;
            }
        }

        /// <summary>
        /// Desarrollo de un arco: cuánto mide recorrido, no en línea recta. Es
        /// el dato con el que se cuantifica una curva de calle o de tubería.
        /// params: handle (de un Arc), arcX, arcY (por dónde pasa la cota),
        ///         [style], [scale], [text]
        /// </summary>
        public static JsonObject ArcLength(Document doc, JsonObject pars)
        {
            string handleStr = pars["handle"].GetValue<string>();
            var db = doc.Database;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var id = HandleHelper.GetObjectId(db, handleStr);
                var arc = tr.GetObject(id, OpenMode.ForRead) as Arc;
                if (arc == null)
                    throw new InvalidOperationException(
                        $"Una cota de desarrollo necesita un Arc. '{handleStr}' no lo es.");

                var arcPoint = new Point3d(pars["arcX"].GetValue<double>(),
                                           pars["arcY"].GetValue<double>(), 0);
                var result = new JsonObject
                {
                    ["radius"] = arc.Radius,
                    ["sweepDeg"] = (arc.EndAngle - arc.StartAngle) * 180.0 / Math.PI,
                    ["developedLength"] = arc.Length
                };

                var dim = new ArcDimension(arc.Center, arc.StartPoint, arc.EndPoint,
                                           arcPoint, null, Style(db, tr, pars));
                Finish(db, tr, dim, pars, result);
                tr.Commit();
                return result;
            }
        }
    }
}
