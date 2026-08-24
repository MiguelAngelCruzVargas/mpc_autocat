using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    public static class ZoomExtentsCommand
    {
        /// <summary>
        /// Zoom a la extensión del dibujo, SÍNCRONO: manipula la vista por
        /// API (SetCurrentView) en vez de encolar "_.ZOOM _Extents" en la
        /// línea de comandos.
        ///
        /// La versión anterior (SendStringToExecute) devolvía "encolado" y el
        /// ZOOM corría después, cuando AutoCAD procesara su cola — y un
        /// capture_viewport pedido justo detrás chocaba con el comando en
        /// curso y moría con eInvalidInput. El cliente reintentaba, gastaba
        /// tiempo y tokens, y la segunda vez pasaba. Ahora cuando esto
        /// devuelve, el zoom YA está hecho.
        ///
        /// Asume vista en planta sin twist (WCS ≈ DCS), que es como trabaja
        /// todo este plugin — planos 2D.
        /// </summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            var db = doc.Database;
            // Recalcula Extmin/Extmax por si hay geometría nueva o borrada.
            db.UpdateExt(true);
            Point3d min = db.Extmin, max = db.Extmax;

            // zoom_window: encuadrar una ZONA en vez de todo el dibujo. Sin
            // esto, mirar un detalle de un plano grande era imposible --
            // capture_viewport siempre salía a la extensión completa y en un
            // DWG en coordenadas UTM el detalle quedaba de un píxel.
            if (pars["minX"] != null && pars["minY"] != null
                && pars["maxX"] != null && pars["maxY"] != null)
            {
                double wx0 = pars["minX"].GetValue<double>();
                double wy0 = pars["minY"].GetValue<double>();
                double wx1 = pars["maxX"].GetValue<double>();
                double wy1 = pars["maxY"].GetValue<double>();
                min = new Point3d(System.Math.Min(wx0, wx1),
                                  System.Math.Min(wy0, wy1), 0.0);
                max = new Point3d(System.Math.Max(wx0, wx1),
                                  System.Math.Max(wy0, wy1), 0.0);
            }

            double w = max.X - min.X;
            double h = max.Y - min.Y;
            if (w <= 0 || h <= 0 || w > 1e90)
            {
                // Dibujo vacío (los extents de fábrica son basura enorme):
                // no hay nada que encuadrar y moverse ahí marea al usuario.
                return new JsonObject { ["status"] = "vacio" };
            }

            using (var view = doc.Editor.GetCurrentView())
            {
                view.CenterPoint = new Point2d((min.X + max.X) / 2.0,
                                               (min.Y + max.Y) / 2.0);
                // 3% de aire alrededor, como hace el ZOOM Extents de verdad.
                // La vista mantiene su relación de aspecto sola: alcanza con
                // asegurar que entren el ancho Y el alto.
                double aspecto = view.Width / view.Height;
                double anchoNecesario = w * 1.03;
                double altoNecesario = h * 1.03;
                if (anchoNecesario / altoNecesario > aspecto)
                {
                    view.Width = anchoNecesario;
                    view.Height = anchoNecesario / aspecto;
                }
                else
                {
                    view.Height = altoNecesario;
                    view.Width = altoNecesario * aspecto;
                }
                doc.Editor.SetCurrentView(view);
            }

            return new JsonObject
            {
                ["status"] = "ok",
                ["minX"] = min.X, ["minY"] = min.Y,
                ["maxX"] = max.X, ["maxY"] = max.Y,
            };
        }
    }
}
