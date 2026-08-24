using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    public static class CreateHatchCommand
    {
        /// <summary>
        /// Rellena una entidad cerrada (Polyline cerrada o Circle) con un patrón
        /// de achurado — sirve tanto para los cuadraditos de una leyenda ("SOLID")
        /// como para simbología de materiales en un corte ("ANSI31", "AR-CONC", etc.,
        /// nombres de acad.pat).
        /// params: boundaryHandle, [islandHandles[]], [pattern="SOLID"], [scale=1],
        ///         [angleDeg=0], [layer]
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

                // Islas: contornos que quedan SIN rellenar dentro del externo.
                //
                // Sin esto no se podia achurar un anillo, ni una losa con un
                // hueco de escalera, ni un patio dentro de una planta -- todo
                // caso donde el material rodea algo que no lo lleva. Se veia
                // rellenando el espacio entre un circulo y un hexagono
                // inscripto: el hatch tapaba el hexagono entero.
                //
                // En la API administrada NO existe AppendInnerLoop, y tampoco
                // HatchLoopTypes.Inner -- eso se probo y no compila. El enum
                // real es: Default, External, Polyline, Derived, Textbox,
                // Outermost, NotClosed, SelfIntersecting, TextIsland,
                // Duplicate. Una isla es 'Default': el lazo comun, que con
                // HatchStyle.Normal queda sin rellenar por estar adentro de
                // uno Outermost.
                var islas = pars["islandHandles"] as JsonArray;
                int nIslas = 0;
                if (islas != null)
                {
                    foreach (var h in islas)
                    {
                        var islaId = HandleHelper.GetObjectId(
                            db, h.GetValue<string>());
                        if (islaId == boundaryId)
                            throw new InvalidOperationException(
                                "Un contorno no puede ser isla de si mismo: " +
                                $"'{h.GetValue<string>()}' esta en las dos listas.");
                        hatch.AppendLoop(HatchLoopTypes.Default,
                                         new ObjectIdCollection { islaId });
                        nIslas++;
                    }
                    // Con islas explicitas, Normal es el estilo que las
                    // respeta: alterna relleno/vacio de afuera hacia adentro.
                    hatch.HatchStyle = HatchStyle.Normal;
                }

                hatch.EvaluateHatch(true);

                EntityHelper.ApplyCommon(db, tr, hatch, pars);

                tr.Commit();
                return new JsonObject { ["handle"] = hatch.Handle.ToString(),
                                        ["islands"] = nIslas };
            }
        }
    }
}
