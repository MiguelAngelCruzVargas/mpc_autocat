using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class CreateTextCommand
    {
        /// <summary>params: text, x, y, [z=0], height, [layer], [rotationDeg=0],
        /// [justify]: left (default, (x,y) es abajo a la izquierda), center,
        /// right, middle_left, middle_center, middle_right. Con justify, (x,y)
        /// es el punto de alineación: AutoCAD centra con la forma REAL de la
        /// letra. Centrar a mano con un ancho estimado dejaba el "1" corrido
        /// en los globos de eje.</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string content = pars["text"].GetValue<string>();
            double x = pars["x"].GetValue<double>();
            double y = pars["y"].GetValue<double>();
            double z = pars["z"] != null ? pars["z"].GetValue<double>() : 0.0;
            double height = pars["height"].GetValue<double>();
            double rotationDeg = pars["rotationDeg"] != null ? pars["rotationDeg"].GetValue<double>() : 0.0;

            var db = doc.Database;
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var btr = SpaceHelper.Current(db, tr);

                var text = new DBText
                {
                    TextString = content,
                    Position = new Point3d(x, y, z),
                    Height = height,
                    Rotation = rotationDeg * System.Math.PI / 180.0
                };
                StyleHelper.ApplyTextStyle(db, tr, text, pars);
                EntityHelper.ApplyCommon(db, tr, text, pars);

                string justify = pars["justify"]?.GetValue<string>();
                bool alinear = !string.IsNullOrEmpty(justify) && justify != "left";
                if (alinear)
                {
                    switch (justify)
                    {
                        case "center": text.HorizontalMode = TextHorizontalMode.TextCenter; break;
                        case "right": text.HorizontalMode = TextHorizontalMode.TextRight; break;
                        case "middle_left":
                            text.HorizontalMode = TextHorizontalMode.TextLeft;
                            text.VerticalMode = TextVerticalMode.TextVerticalMid; break;
                        case "middle_center":
                            text.HorizontalMode = TextHorizontalMode.TextCenter;
                            text.VerticalMode = TextVerticalMode.TextVerticalMid; break;
                        case "middle_right":
                            text.HorizontalMode = TextHorizontalMode.TextRight;
                            text.VerticalMode = TextVerticalMode.TextVerticalMid; break;
                        default:
                            throw new System.ArgumentException(
                                $"justify '{justify}' no existe. Usá left, center, right, " +
                                "middle_left, middle_center o middle_right.");
                    }
                    text.AlignmentPoint = new Point3d(x, y, z);
                }

                btr.AppendEntity(text);
                tr.AddNewlyCreatedDBObject(text, true);
                // Con alineación, la posición final la calcula AutoCAD.
                if (alinear)
                    text.AdjustAlignment(db);
                tr.Commit();

                return new JsonObject { ["handle"] = text.Handle.ToString() };
            }
        }
    }
}
