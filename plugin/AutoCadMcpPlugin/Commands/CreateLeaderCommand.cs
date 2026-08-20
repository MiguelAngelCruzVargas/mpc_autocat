using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class CreateLeaderCommand
    {
        /// <summary>
        /// Línea de referencia con flecha + texto (callout), como los que apuntan
        /// al detalle de juntas en un corte.
        /// params: points ([[x,y], ...], al menos 2 — el último es donde arranca el
        /// texto), text, [textHeight=2.5], [arrowSize] (por defecto, la del
        /// DIMSTYLE activo -set_dim_style-, para que coincida con las cotas del
        /// mismo plano), [layer]
        /// </summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            var pointsArray = pars["points"].AsArray();
            string content = pars["text"].GetValue<string>();
            double textHeight = pars["textHeight"] != null ? pars["textHeight"].GetValue<double>() : 2.5;

            if (pointsArray.Count < 2)
                throw new System.ArgumentException("Un leader necesita al menos 2 puntos.");

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var btr = SpaceHelper.Current(db, tr);

                var lastPoint = pointsArray[pointsArray.Count - 1].AsArray();
                var mtext = new MText
                {
                    Contents = content,
                    Location = new Point3d(lastPoint[0].GetValue<double>(), lastPoint[1].GetValue<double>(), 0),
                    TextHeight = textHeight
                };
                EntityHelper.ApplyCommon(db, tr, mtext, pars);
                btr.AppendEntity(mtext);
                tr.AddNewlyCreatedDBObject(mtext, true);

                var leader = new Leader { HasArrowHead = true };
                foreach (var pt in pointsArray)
                {
                    var coords = pt.AsArray();
                    leader.AppendVertex(new Point3d(coords[0].GetValue<double>(), coords[1].GetValue<double>(), 0));
                }

                // EvaluateLeader() recalcula el landing/gap contra el DIMSTYLE
                // ACTIVO del dibujo (Dimasz/Dimgap), no contra textHeight. Si ese
                // dimstyle quedo con un DIMSCALE grande -de otro plano dibujado
                // antes en la misma sesion, a otra escala- el gap se dispara y el
                // MText termina metros mas abajo de donde se lo puso, aunque su
                // Location reporte el punto correcto. Fijar el override ACA, por
                // entidad, deja al leader independiente del estado ambiente.
                //
                // El tamano de flecha default sale del DIMSTYLE activo (el mismo
                // que usan las cotas de create_dimension*), no de un ratio fijo:
                // si no, la flecha del leader queda de otro tamano que la de las
                // cotas en el mismo plano aunque se haya configurado arrow_size
                // con set_dim_style. arrowSize explicito pisa eso.
                double arrowSize = pars["arrowSize"] != null
                    ? pars["arrowSize"].GetValue<double>()
                    : ActiveDimAsz(db, tr, textHeight);
                leader.Dimasz = arrowSize;
                leader.Dimgap = textHeight * 0.5;
                leader.Dimscale = 1.0;

                EntityHelper.ApplyCommon(db, tr, leader, pars);

                // El leader tiene que estar YA en la base de datos antes de
                // apuntarlo a su anotación: asignar Annotation sobre una entidad
                // suelta tira eNotInDatabase.
                btr.AppendEntity(leader);
                tr.AddNewlyCreatedDBObject(leader, true);

                leader.Annotation = mtext.ObjectId;
                leader.EvaluateLeader();

                var result = new JsonObject
                {
                    ["handle"] = leader.Handle.ToString(),
                    ["textHandle"] = mtext.Handle.ToString()
                };
                tr.Commit();
                return result;
            }
        }

        /// <summary>
        /// Dimasz del DIMSTYLE activo, escalado igual que las cotas (Dimasz *
        /// Dimscale). Un dimstyle recien creado o sin arrowSize configurado
        /// trae Dimasz en 0, que dibujaria un leader sin flecha visible: para
        /// eso cae al ratio de textHeight que se usaba antes.
        /// </summary>
        private static double ActiveDimAsz(Database db, Transaction tr, double textHeight)
        {
            if (db.Dimstyle.IsNull)
                return textHeight * 0.6;

            var record = (DimStyleTableRecord)tr.GetObject(db.Dimstyle, OpenMode.ForRead);
            double asz = record.Dimasz * record.Dimscale;
            return asz > 0 ? asz : textHeight * 0.6;
        }
    }
}
