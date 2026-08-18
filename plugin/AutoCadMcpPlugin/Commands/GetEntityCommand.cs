using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class GetEntityCommand
    {
        /// <summary>params: handle. Devuelve propiedades genéricas + específicas del tipo.</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string handleStr = pars["handle"].GetValue<string>();
            var db = doc.Database;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var ent = (Entity)tr.GetObject(HandleHelper.GetObjectId(db, handleStr), OpenMode.ForRead);

                var result = new JsonObject
                {
                    ["handle"] = ent.Handle.ToString(),
                    ["type"] = ent.GetType().Name,
                    ["layer"] = ent.Layer,
                    ["colorIndex"] = ent.ColorIndex,
                    ["linetype"] = ent.Linetype
                };

                switch (ent)
                {
                    case Line line:
                        result["startPoint"] = PointToJson(line.StartPoint);
                        result["endPoint"] = PointToJson(line.EndPoint);
                        result["length"] = line.Length;
                        break;

                    case Circle circle:
                        result["center"] = PointToJson(circle.Center);
                        result["radius"] = circle.Radius;
                        result["area"] = circle.Area;
                        break;

                    case Arc arc:
                        result["center"] = PointToJson(arc.Center);
                        result["radius"] = arc.Radius;
                        result["startAngleDeg"] = arc.StartAngle * 180.0 / Math.PI;
                        result["endAngleDeg"] = arc.EndAngle * 180.0 / Math.PI;
                        break;

                    case Polyline pl:
                        result["closed"] = pl.Closed;
                        result["area"] = pl.Closed ? pl.Area : 0.0;
                        result["length"] = pl.Length;
                        var pts = new JsonArray();
                        var bulges = new JsonArray();
                        bool tieneArcos = false;
                        for (int i = 0; i < pl.NumberOfVertices; i++)
                        {
                            var p = pl.GetPoint2dAt(i);
                            pts.Add(new JsonArray { p.X, p.Y });

                            // El bulge es la tangente de un cuarto del ángulo
                            // del arco entre este vértice y el siguiente: 0 es
                            // tramo recto. Sin esto una polilínea curva se lee
                            // como si fuera una quebrada, que es lo que pasa en
                            // casi cualquier plano de obra civil.
                            double b = pl.GetBulgeAt(i);
                            bulges.Add(b);
                            if (System.Math.Abs(b) > 1e-9)
                                tieneArcos = true;
                        }
                        result["points"] = pts;
                        result["bulges"] = bulges;
                        result["hasArcs"] = tieneArcos;
                        break;

                    case DBText text:
                        result["text"] = text.TextString;
                        result["position"] = PointToJson(text.Position);
                        result["height"] = text.Height;
                        break;

                    case MText mtext:
                        result["text"] = mtext.Contents;
                        result["location"] = PointToJson(mtext.Location);
                        break;

                    case Hatch hatch:
                        // Sin esto no se puede saber con que textura esta
                        // resuelto un material en un plano ajeno, que es lo
                        // primero que hace falta para replicarlo.
                        result["patternName"] = hatch.PatternName;
                        result["patternType"] = hatch.PatternType.ToString();
                        result["patternScale"] = hatch.PatternScale;
                        result["patternAngleDeg"] = hatch.PatternAngle * 180.0 / Math.PI;
                        result["isSolid"] = hatch.IsSolidFill;
                        result["loops"] = hatch.NumberOfLoops;
                        try { result["hatchArea"] = hatch.Area; } catch (System.Exception) { }
                        break;

                    case BlockReference br:
                        var btr = (BlockTableRecord)tr.GetObject(br.BlockTableRecord, OpenMode.ForRead);
                        result["blockName"] = btr.Name;
                        result["position"] = PointToJson(br.Position);
                        var attrs = new JsonObject();
                        foreach (ObjectId attId in br.AttributeCollection)
                        {
                            var att = (AttributeReference)tr.GetObject(attId, OpenMode.ForRead);
                            attrs[att.Tag] = att.TextString;
                        }
                        result["attributes"] = attrs;
                        break;
                }

                tr.Commit();
                return result;
            }
        }

        private static JsonArray PointToJson(Point3d p) => new JsonArray { p.X, p.Y, p.Z };
    }
}
