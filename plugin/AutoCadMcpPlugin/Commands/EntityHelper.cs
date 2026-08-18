using System.Text.Json.Nodes;
using Autodesk.AutoCAD.Colors;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCadMcpPlugin.Commands
{
    /// <summary>
    /// Propiedades comunes a toda entidad que creamos (capa, grosor, color).
    /// Centralizado acá para que agregar una propiedad nueva no signifique
    /// tocar los 15 comandos de creación uno por uno.
    /// </summary>
    internal static class EntityHelper
    {
        /// <summary>
        /// Aplica layer / lineweight / colorIndex desde los params del request.
        /// Crea la capa si hace falta. Se llama con la entidad ya construida y
        /// la transacción abierta; sirve tanto antes como después de
        /// AppendEntity.
        /// params leídos: [layer], [lineweight] (centésimas de mm), [colorIndex] (ACI)
        /// </summary>
        public static void ApplyCommon(Database db, Transaction tr, Entity ent, JsonObject pars)
        {
            string layer = pars["layer"]?.GetValue<string>();
            if (!string.IsNullOrEmpty(layer))
            {
                LayerHelper.EnsureLayer(db, tr, layer);
                ent.Layer = layer;
            }

            // Grosor por entidad. Sin esto todo queda ByLayer, y una capa recién
            // creada nace con el grosor por defecto del dibujo (fino).
            if (pars["lineweight"] != null)
                ent.LineWeight = (LineWeight)pars["lineweight"].GetValue<int>();

            if (pars["colorIndex"] != null)
                ent.Color = Color.FromColorIndex(ColorMethod.ByAci, (short)pars["colorIndex"].GetValue<int>());
        }
    }
}
