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
                        var pts = new JsonArray();
                        for (int i = 0; i < pl.NumberOfVertices; i++)
                        {
                            var p = pl.GetPoint2dAt(i);
                            pts.Add(new JsonArray { p.X, p.Y });
                        }
                        result["points"] = pts;
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
