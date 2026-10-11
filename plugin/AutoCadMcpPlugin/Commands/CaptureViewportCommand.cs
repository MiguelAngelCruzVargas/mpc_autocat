using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// capture_viewport: una foto PNG de lo que hay dibujado, vía el driver
    /// de plotting "PublishToWeb PNG.pc3" — no captura de pantalla (eso
    /// depende de que la ventana de AutoCAD esté visible y sin taparse), sino
    /// la misma API de plotting que usa export_pdf, así que funciona igual
    /// esté la ventana minimizada o no.
    /// </summary>
    public static class CaptureViewportCommand
    {
        private const string Device = "PublishToWeb PNG.pc3";

        /// <summary>params: path, [layout]</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string path = pars["path"].GetValue<string>();
            string layoutName = pars["layout"] != null && pars["layout"].GetValue<string>() != null
                ? pars["layout"].GetValue<string>()
                : null;

            var lm = LayoutManager.Current;
            // Sin 'layout' explícito, captura el espacio ACTIVO — mismo
            // criterio que ya usan las demás tools de inspección del
            // proyecto (get_extents, list_entities): lo que está a la vista
            // ahora, no siempre "Model" a secas.
            if (layoutName == null)
                layoutName = lm.CurrentLayout;

            ObjectId layoutId = lm.GetLayoutId(layoutName);
            if (layoutId.IsNull)
                throw new System.InvalidOperationException($"No existe un layout llamado '{layoutName}'.");

            bool isModel;
            using (var tr = doc.Database.TransactionManager.StartTransaction())
            {
                var layout = (Layout)tr.GetObject(layoutId, OpenMode.ForRead);
                isModel = layout.ModelType;
                tr.Commit();
            }

            var plotType = isModel
                ? Autodesk.AutoCAD.DatabaseServices.PlotType.Extents
                : Autodesk.AutoCAD.DatabaseServices.PlotType.Layout;

            // Ventana explicita: capturar UNA ZONA, no todo. Sin esto no
            // habia forma de mirar un detalle -- la foto salia siempre a la
            // extension completa y un mueble de 60 cm en un plano de 16 m
            // quedaba de unos pocos pixeles, asi que revisar si dos lineas
            // estaban encimadas era imposible. zoom_window no alcanzaba:
            // el plot por Extents ignora la vista de pantalla.
            Extents2d? ventana = null;
            if (pars["minX"] != null && pars["minY"] != null
                && pars["maxX"] != null && pars["maxY"] != null)
            {
                double wx0 = pars["minX"].GetValue<double>();
                double wy0 = pars["minY"].GetValue<double>();
                double wx1 = pars["maxX"].GetValue<double>();
                double wy1 = pars["maxY"].GetValue<double>();
                ventana = new Extents2d(System.Math.Min(wx0, wx1),
                                        System.Math.Min(wy0, wy1),
                                        System.Math.Max(wx0, wx1),
                                        System.Math.Max(wy0, wy1));
                // La ventana del plot va en coordenadas de la VISTA (DCS),
                // no del mundo: con el objetivo de la vista fuera del
                // origen la foto salía corrida (se vio en una casa: se
                // pedía la planta y salía la mitad de la sala). En el
                // modelo se pasa al DCS de la vista activa.
                if (isModel)
                    ventana = ADcs(doc.Database, ventana.Value);
                plotType = Autodesk.AutoCAD.DatabaseServices.PlotType.Window;
            }

            PlotHelper.PlotToFile(doc, layoutId, plotType, Device, path, ventana);

            return new JsonObject
            {
                ["path"] = path,
                ["layout"] = layoutName,
                ["space"] = isModel ? "model" : "paper",
                ["window"] = ventana == null ? null : new JsonArray(
                    pars["minX"].GetValue<double>(), pars["minY"].GetValue<double>(),
                    pars["maxX"].GetValue<double>(), pars["maxY"].GetValue<double>())
            };
        }

        /// <summary>Del mundo al sistema de la vista activa del modelo
        /// (objetivo, dirección y giro del VPORT *Active).</summary>
        private static Extents2d ADcs(Database db, Extents2d w)
        {
            using (var tr = db.TransactionManager.StartTransaction())
            {
                var vt = (ViewportTable)tr.GetObject(db.ViewportTableId, OpenMode.ForRead);
                if (!vt.Has("*Active"))
                {
                    tr.Commit();
                    return w;
                }
                var vp = (ViewportTableRecord)tr.GetObject(vt["*Active"], OpenMode.ForRead);
                Matrix3d aMundo =
                    Matrix3d.Rotation(-vp.ViewTwist, vp.ViewDirection, vp.Target) *
                    Matrix3d.Displacement(vp.Target - Point3d.Origin) *
                    Matrix3d.PlaneToWorld(vp.ViewDirection);
                Matrix3d aVista = aMundo.Inverse();
                tr.Commit();
                double x0 = double.MaxValue, y0 = double.MaxValue;
                double x1 = double.MinValue, y1 = double.MinValue;
                foreach (var p in new[] {
                    new Point3d(w.MinPoint.X, w.MinPoint.Y, 0), new Point3d(w.MaxPoint.X, w.MinPoint.Y, 0),
                    new Point3d(w.MaxPoint.X, w.MaxPoint.Y, 0), new Point3d(w.MinPoint.X, w.MaxPoint.Y, 0) })
                {
                    var q = p.TransformBy(aVista);
                    x0 = System.Math.Min(x0, q.X); y0 = System.Math.Min(y0, q.Y);
                    x1 = System.Math.Max(x1, q.X); y1 = System.Math.Max(y1, q.Y);
                }
                return new Extents2d(x0, y0, x1, y1);
            }
        }
    }
}
