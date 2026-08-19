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
        /// texto), text, [textHeight=2.5], [layer]
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
    }
}
