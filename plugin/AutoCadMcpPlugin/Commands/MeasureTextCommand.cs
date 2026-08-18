using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Cuánto mide un texto realmente, antes de dibujarlo.
    ///
    /// Estimar el ancho como "caracteres x altura x un factor" falla: depende de
    /// la fuente, del ancho del estilo y de qué letras sean. Con la estimación,
    /// un rótulo de ambiente se desborda del cuarto y termina cruzando el muro.
    /// Acá se arma un DBText en memoria (nunca entra al dibujo) y se le pide su
    /// extensión geométrica, que es la medida que AutoCAD va a usar de verdad.
    /// params: text, height, [style], [widthFactor]
    /// </summary>
    public static class MeasureTextCommand
    {
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string text = pars["text"].GetValue<string>();
            double height = pars["height"].GetValue<double>();
            string style = pars["style"]?.GetValue<string>();

            if (height <= 0)
                throw new ArgumentException("height tiene que ser > 0.");

            var db = doc.Database;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                ObjectId styleId = db.Textstyle;
                if (!string.IsNullOrEmpty(style))
                {
                    var table = (TextStyleTable)tr.GetObject(db.TextStyleTableId, OpenMode.ForRead);
                    if (!table.Has(style))
                        throw new InvalidOperationException(
                            $"No existe el estilo de texto '{style}'.");
                    styleId = table[style];
                }

                double width, realHeight;
                using (var probe = new DBText())
                {
                    probe.TextStyleId = styleId;
                    probe.TextString = string.IsNullOrEmpty(text) ? " " : text;
                    probe.Height = height;
                    probe.Position = Point3d.Origin;

                    if (pars["widthFactor"] != null)
                        probe.WidthFactor = pars["widthFactor"].GetValue<double>();

                    try
                    {
                        var ext = probe.GeometricExtents;
                        width = ext.MaxPoint.X - ext.MinPoint.X;
                        realHeight = ext.MaxPoint.Y - ext.MinPoint.Y;
                    }
                    catch (System.Exception)
                    {
                        // Texto vacío o fuente sin extensión calculable: caemos a
                        // una estimación amplia, que es preferible a fallar.
                        width = text.Length * height * 0.75;
                        realHeight = height;
                    }
                }

                tr.Commit();
                return new JsonObject
                {
                    ["text"] = text,
                    ["width"] = width,
                    ["height"] = realHeight,
                    ["charWidthRatio"] = text.Length > 0 ? width / (text.Length * height) : 0.0
                };
            }
        }
    }
}
