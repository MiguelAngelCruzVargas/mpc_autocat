using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

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

            PlotHelper.PlotToFile(doc, layoutId, plotType, Device, path);

            return new JsonObject
            {
                ["path"] = path,
                ["layout"] = layoutName,
                ["space"] = isModel ? "model" : "paper"
            };
        }
    }
}
