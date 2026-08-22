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

                // La caja real que ocupa, calculada por AutoCAD.
                //
                // Sin esto no habia forma de saber cuanto mide un MText: se
                // devolvia su punto de insercion y nada mas. Y sin la caja no
                // se puede preguntar "que hay debajo de este texto", que es la
                // unica manera honesta de detectar que un rotulo esta encima
                // del dibujo. check_annotations comparaba contra un registro
                // interno que solo llenan las tools de alto nivel: un dibujo
                // hecho con create_polyline crudo le resultaba INVISIBLE.
                try
                {
                    var ext = ent.GeometricExtents;
                    result["bbox"] = new JsonArray {
                        ext.MinPoint.X, ext.MinPoint.Y,
                        ext.MaxPoint.X, ext.MaxPoint.Y };
                }
                catch (System.Exception)
                {
                    // Un texto vacio o un bloque sin geometria no tienen
                    // extents y GeometricExtents tira. No es un error de la
                    // consulta: es que no ocupan lugar.
                    result["bbox"] = null;
                }

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

                    // Una sola rama para las seis clases de cota
                    // (RotatedDimension, AlignedDimension, Radial...): todas
                    // heredan de Dimension y lo que interesa está ahí.
                    case Dimension dim:
                        // Measurement es lo que la cota MIDE de verdad;
                        // DimensionText es el texto que muestra. Vienen
                        // distintos cuando alguien piso el numero a mano, y
                        // ese es justo el caso que hay que poder detectar.
                        result["measurement"] = dim.Measurement;
                        result["dimensionText"] = dim.DimensionText;
                        result["overridden"] = !string.IsNullOrEmpty(dim.DimensionText);
                        result["styleName"] = dim.DimensionStyleName;
                        result["textPosition"] = PointToJson(dim.TextPosition);
                        try { result["textHeight"] = dim.Dimtxt; } catch (System.Exception) { }
                        try { result["dimScale"] = dim.Dimscale; } catch (System.Exception) { }
                        break;

                    // El viewport es lo que convierte un modelo desordenado
                    // en una lamina limpia: recorta una zona, la muestra a
                    // una escala fija y apaga las capas que no le tocan.
                    case Viewport vp:
                        result["centerPoint"] = PointToJson(vp.CenterPoint);
                        result["width"] = vp.Width;
                        result["height"] = vp.Height;
                        result["viewCenter"] = new JsonArray { vp.ViewCenter.X, vp.ViewCenter.Y };
                        result["viewHeight"] = vp.ViewHeight;
                        result["customScale"] = vp.CustomScale;
                        // CustomScale son unidades de papel por unidad de
                        // modelo: 0.01 es 1:100 dibujando en las mismas
                        // unidades. Se devuelve el reciproco ya hecho porque
                        // es como se lee una lamina.
                        if (vp.CustomScale > 0)
                            result["scaleDenominator"] = 1.0 / vp.CustomScale;
                        result["locked"] = vp.Locked;
                        result["viewportNumber"] = vp.Number;
                        result["on"] = vp.On;
                        var congeladas = new JsonArray();
                        try
                        {
                            foreach (ObjectId lid in vp.GetFrozenLayers())
                                congeladas.Add(((LayerTableRecord)tr.GetObject(
                                    lid, OpenMode.ForRead)).Name);
                        }
                        catch (System.Exception) { }
                        result["frozenLayers"] = congeladas;
                        break;

                    case MLeader ml:
                        result["leaderCount"] = ml.LeaderCount;
                        result["styleName"] = ml.MLeaderStyle.IsNull ? null
                            : ((MLeaderStyle)tr.GetObject(ml.MLeaderStyle,
                                OpenMode.ForRead)).Name;
                        try
                        {
                            // El texto va ADENTRO del MLeader (por eso la
                            // flecha lo sigue al moverlo); en el Leader viejo
                            // es una entidad suelta al lado.
                            if (ml.MText != null)
                                result["text"] = ml.MText.Contents;
                        }
                        catch (System.Exception) { }
                        break;
                }

                tr.Commit();
                return result;
            }
        }

        private static JsonArray PointToJson(Point3d p) => new JsonArray { p.X, p.Y, p.Z };
    }
}
