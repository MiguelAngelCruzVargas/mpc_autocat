using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Estilos de texto y de cota con nombre. Sin esto todo sale con el estilo
    /// por defecto del dibujo (Standard), que cambia de plantilla en plantilla:
    /// el mismo plano se ve distinto según con qué DWG arrancaste.
    /// </summary>
    public static class StyleCommands
    {
        /// <summary>
        /// params: name, [font="arial.ttf" o "txt.shx"], [height=0] (0 = altura
        /// libre, la fija cada texto), [widthFactor=1], [oblique=0],
        /// [setCurrent=false]
        /// </summary>
        public static JsonObject SetTextStyle(Document doc, JsonObject pars)
        {
            string name = pars["name"].GetValue<string>();
            string font = pars["font"]?.GetValue<string>();
            double height = pars["height"] != null ? pars["height"].GetValue<double>() : 0.0;
            double widthFactor = pars["widthFactor"] != null
                ? pars["widthFactor"].GetValue<double>() : 1.0;
            double oblique = pars["oblique"] != null ? pars["oblique"].GetValue<double>() : 0.0;
            bool setCurrent = pars["setCurrent"] != null && pars["setCurrent"].GetValue<bool>();

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var table = (TextStyleTable)tr.GetObject(db.TextStyleTableId, OpenMode.ForRead);

                TextStyleTableRecord record;
                if (table.Has(name))
                {
                    record = (TextStyleTableRecord)tr.GetObject(table[name], OpenMode.ForWrite);
                }
                else
                {
                    table.UpgradeOpen();
                    record = new TextStyleTableRecord { Name = name };
                    table.Add(record);
                    tr.AddNewlyCreatedDBObject(record, true);
                }

                if (!string.IsNullOrEmpty(font))
                {
                    // Las TrueType van por TypeFace; las SHX por FileName.
                    if (font.EndsWith(".ttf", StringComparison.OrdinalIgnoreCase))
                    {
                        var current = record.Font;
                        record.Font = new Autodesk.AutoCAD.GraphicsInterface.FontDescriptor(
                            System.IO.Path.GetFileNameWithoutExtension(font),
                            current.Bold, current.Italic, current.CharacterSet, current.PitchAndFamily);
                    }
                    else
                    {
                        record.FileName = font;
                    }
                }

                record.TextSize = height;
                record.XScale = widthFactor;
                record.ObliquingAngle = oblique * Math.PI / 180.0;

                if (setCurrent)
                    db.Textstyle = record.ObjectId;

                var result = new JsonObject
                {
                    ["name"] = record.Name,
                    ["font"] = string.IsNullOrEmpty(record.FileName)
                        ? record.Font.TypeFace : record.FileName,
                    ["height"] = record.TextSize,
                    ["widthFactor"] = record.XScale,
                    ["isCurrent"] = db.Textstyle == record.ObjectId
                };
                tr.Commit();
                return result;
            }
        }

        /// <summary>
        /// params: name, [textHeight], [arrowSize], [scale] (DIMSCALE global),
        /// [decimalPlaces], [textStyle] (nombre de un estilo de texto),
        /// [unitsFactor] (DIMLFAC: 1 dibujando en mm, 1000 en metros si querés
        /// que la cota diga milímetros), [setCurrent=false]
        /// </summary>
        public static JsonObject SetDimStyle(Document doc, JsonObject pars)
        {
            string name = pars["name"].GetValue<string>();
            var db = doc.Database;

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var table = (DimStyleTable)tr.GetObject(db.DimStyleTableId, OpenMode.ForRead);

                DimStyleTableRecord record;
                if (table.Has(name))
                {
                    record = (DimStyleTableRecord)tr.GetObject(table[name], OpenMode.ForWrite);
                }
                else
                {
                    table.UpgradeOpen();
                    record = new DimStyleTableRecord { Name = name };
                    table.Add(record);
                    tr.AddNewlyCreatedDBObject(record, true);
                }

                if (pars["textHeight"] != null)
                    record.Dimtxt = pars["textHeight"].GetValue<double>();
                if (pars["arrowSize"] != null)
                    record.Dimasz = pars["arrowSize"].GetValue<double>();
                if (pars["scale"] != null)
                    record.Dimscale = pars["scale"].GetValue<double>();
                if (pars["decimalPlaces"] != null)
                    record.Dimdec = pars["decimalPlaces"].GetValue<int>();
                if (pars["unitsFactor"] != null)
                    record.Dimlfac = pars["unitsFactor"].GetValue<double>();

                // Separación de la línea de cota respecto del objeto y salida de
                // las líneas de extensión: sin esto las cotas se pegan al dibujo.
                if (pars["extensionOffset"] != null)
                    record.Dimexo = pars["extensionOffset"].GetValue<double>();
                if (pars["extensionBeyond"] != null)
                    record.Dimexe = pars["extensionBeyond"].GetValue<double>();

                if (pars["textStyle"] != null)
                {
                    string styleName = pars["textStyle"].GetValue<string>();
                    var tst = (TextStyleTable)tr.GetObject(db.TextStyleTableId, OpenMode.ForRead);
                    if (!tst.Has(styleName))
                        throw new InvalidOperationException(
                            $"No existe el estilo de texto '{styleName}'. Creálo primero con set_text_style.");
                    record.Dimtxsty = tst[styleName];
                }

                if (pars["setCurrent"] != null && pars["setCurrent"].GetValue<bool>())
                    db.Dimstyle = record.ObjectId;

                var result = new JsonObject
                {
                    ["name"] = record.Name,
                    ["textHeight"] = record.Dimtxt,
                    ["arrowSize"] = record.Dimasz,
                    ["scale"] = record.Dimscale,
                    ["decimalPlaces"] = record.Dimdec,
                    ["isCurrent"] = db.Dimstyle == record.ObjectId
                };
                tr.Commit();
                return result;
            }
        }

        /// <summary>params: (ninguno)</summary>
        public static JsonObject ListStyles(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            var texts = new JsonArray();
            var dims = new JsonArray();

            using (var tr = db.TransactionManager.StartTransaction())
            {
                var tst = (TextStyleTable)tr.GetObject(db.TextStyleTableId, OpenMode.ForRead);
                foreach (ObjectId id in tst)
                {
                    var r = (TextStyleTableRecord)tr.GetObject(id, OpenMode.ForRead);
                    texts.Add(new JsonObject
                    {
                        ["name"] = r.Name,
                        ["font"] = string.IsNullOrEmpty(r.FileName) ? r.Font.TypeFace : r.FileName,
                        ["height"] = r.TextSize,
                        ["isCurrent"] = db.Textstyle == id
                    });
                }

                var dst = (DimStyleTable)tr.GetObject(db.DimStyleTableId, OpenMode.ForRead);
                foreach (ObjectId id in dst)
                {
                    var r = (DimStyleTableRecord)tr.GetObject(id, OpenMode.ForRead);
                    dims.Add(new JsonObject
                    {
                        ["name"] = r.Name,
                        ["textHeight"] = r.Dimtxt,
                        ["scale"] = r.Dimscale,
                        ["isCurrent"] = db.Dimstyle == id
                    });
                }
                tr.Commit();
            }

            return new JsonObject { ["textStyles"] = texts, ["dimStyles"] = dims };
        }
    }
}
