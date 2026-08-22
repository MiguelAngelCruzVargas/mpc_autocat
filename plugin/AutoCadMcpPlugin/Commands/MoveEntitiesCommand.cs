using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Mueve MUCHAS entidades de una sola pasada, todas por el mismo vector.
    ///
    /// Existe por la composición de láminas: acomodar una vista es mover
    /// todas sus entidades juntas, y una vista de detalle tiene fácil un
    /// par de cientos. Con move_entity una por una eso son N viajes por el
    /// socket y N transacciones; acá es uno y una.
    ///
    /// Mismo criterio que SelectCommands.DeleteMany con los handles que ya
    /// no existen: al recomponer es normal que algo se haya borrado, y no
    /// tiene por qué tumbar el acomodo entero.
    /// </summary>
    public static class MoveEntitiesCommand
    {
        /// <summary>params: handles[], dx, dy, [dz=0], [ignoreMissing=true]</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            var handleArray = pars["handles"].AsArray();
            double dx = pars["dx"].GetValue<double>();
            double dy = pars["dy"].GetValue<double>();
            double dz = pars["dz"] != null ? pars["dz"].GetValue<double>() : 0.0;
            bool ignorarFaltantes = pars["ignoreMissing"] == null
                || pars["ignoreMissing"].GetValue<bool>();

            var db = doc.Database;
            var desplazamiento = Matrix3d.Displacement(new Vector3d(dx, dy, dz));
            int movidas = 0;
            var fallidas = new JsonArray();

            using (var tr = db.TransactionManager.StartTransaction())
            {
                foreach (var h in handleArray)
                {
                    string handleStr = h.GetValue<string>();
                    try
                    {
                        var ent = (Entity)tr.GetObject(
                            HandleHelper.GetObjectId(db, handleStr), OpenMode.ForWrite);
                        ent.TransformBy(desplazamiento);
                        movidas++;
                    }
                    catch (System.Exception)
                    {
                        if (!ignorarFaltantes)
                            throw;
                        fallidas.Add(handleStr);
                    }
                }
                tr.Commit();
            }

            return new JsonObject
            {
                ["moved"] = movidas,
                ["notFound"] = fallidas,
                ["requested"] = handleArray.Count
            };
        }
    }
}
