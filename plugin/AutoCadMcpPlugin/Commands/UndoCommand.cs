using System;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// undo: deshace las últimas N operaciones del dibujo activo. Cada
    /// llamada del MCP que modificó el dibujo ya quedó registrada como una
    /// operación de UNDO normal de AutoCAD — no hace falta rastrear qué hizo
    /// cada tool call por separado, alcanza con delegarle el conteo al UNDO
    /// nativo (mismo criterio que ZoomExtentsCommand: encolar en la línea de
    /// comandos en vez de tocar la Database a mano).
    /// </summary>
    public static class UndoCommand
    {
        /// <summary>params: [steps=1]</summary>
        public static JsonObject Run(Document doc, JsonObject pars)
        {
            int steps = pars["steps"] != null ? pars["steps"].GetValue<int>() : 1;
            if (steps <= 0)
                throw new ArgumentException("'steps' tiene que ser >= 1.");

            doc.SendStringToExecute($"_.UNDO {steps} ", true, false, false);
            return new JsonObject { ["status"] = "encolado", ["steps"] = steps };
        }
    }
}
