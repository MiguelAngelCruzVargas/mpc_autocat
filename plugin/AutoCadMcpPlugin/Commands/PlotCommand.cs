using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// export_pdf: plotea un layout ya armado (create_layout + create_viewport)
    /// a un archivo por API, en vez de mandar al usuario a hacer PLOT a mano
    /// desde AutoCAD.
    /// </summary>
    public static class PlotCommand
    {
        /// <summary>params: layout, path, [device]</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            string layoutName = pars["layout"].GetValue<string>();
            string path = pars["path"].GetValue<string>();
            string device = pars["device"] != null && pars["device"].GetValue<string>() != null
                ? pars["device"].GetValue<string>()
                : "DWG To PDF.pc3";

            var lm = LayoutManager.Current;
            ObjectId layoutId = lm.GetLayoutId(layoutName);
            if (layoutId.IsNull)
                throw new System.InvalidOperationException($"No existe un layout llamado '{layoutName}'.");

            PlotHelper.PlotToFile(doc, layoutId,
                Autodesk.AutoCAD.DatabaseServices.PlotType.Layout, device, path);

            return new JsonObject { ["path"] = path, ["layout"] = layoutName, ["device"] = device };
        }
    }
}
