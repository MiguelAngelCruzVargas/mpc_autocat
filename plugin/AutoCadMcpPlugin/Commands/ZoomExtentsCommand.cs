using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;

namespace AutoCadMcpPlugin.Commands
{
    public static class ZoomExtentsCommand
    {
        /// <summary>
        /// Stub simple: encola el comando de línea de comandos ZOOM Extents.
        /// Suficiente para probar el pipeline; si más adelante queremos vistas
        /// con nombre / viewports / layouts, esto se reemplaza por manipulación
        /// directa de ViewTableRecord vía la API.
        /// </summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            doc.SendStringToExecute("_.ZOOM _Extents ", true, false, false);
            return new JsonObject { ["status"] = "encolado" };
        }
    }
}
