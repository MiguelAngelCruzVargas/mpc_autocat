using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    public static class CreateHatchCommand
    {
        /// <summary>
        /// Rellena una entidad cerrada (Polyline cerrada o Circle) con un patrÃ³n
        /// de achurado â€” sirve tanto para los cuadraditos de una leyenda ("SOLID")
        /// como para simbologÃ­a de materiales en un corte ("ANSI31", "AR-CONC", etc.,
        /// nombres de acad.pat).
        /// params: boundaryHandle, [pattern="SOLID"], [scale=1], [angleDeg=0], [layer]
        /// </summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string boundaryHandleStr = pars["boundaryHandle"].GetValue<string>();
            string pattern = pars["pattern"] != null ? pars["pattern"].GetValue<string>() : "SOLID";
            double scale = pars["scale"] != null ? pars["scale"].GetValue<double>() : 1.0;
            double angleDeg = pars["angleDeg"] != null ? pars["angleDeg"].GetValue<double>() : 0.0;

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var boundaryId = HandleHelper.GetObjectId(db, boundaryHandleStr);

                var btr = SpaceHelper.Current(db, tr);

                var hatch = new Hatch();
                btr.AppendEntity(hatch);
                tr.AddNewlyCreatedDBObject(hatch, true);

                hatch.SetHatchPattern(HatchPatternType.PreDefined, pattern);
                hatch.PatternScale = scale;
                hatch.PatternAngle = angleDeg * Math.PI / 180.0;
                hatch.AppendLoop(HatchLoopTypes.Outermost, new ObjectIdCollection { boundaryId });
                hatch.EvaluateHatch(true);

                EntityHelper.ApplyCommon(db, tr, hatch, pars);

                tr.Commit();
                return new JsonObject { ["handle"] = hatch.Handle.ToString() };
            }
        }
    }
}
